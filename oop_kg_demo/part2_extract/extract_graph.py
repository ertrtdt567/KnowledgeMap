"""
Part 2: extract entities and relations from clean_chunks.json.

The module combines rule extraction and LLM extraction, then applies Schema
validation, normalization, relation repair, deduplication, caching, and quality
reporting. It supports Qwen/DashScope and DeepSeek OpenAI-compatible APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "oop_kg_schema_v1"

ENTITY_TYPES = {
    "ProgrammingParadigm", "OOPConcept", "CodeStructure", "SyntaxRule",
    "ProgrammingLanguage", "CodeExample", "Exercise", "ErrorPattern", "Skill",
}

RELATION_TYPES = {
    "belongs_to_paradigm", "part_of", "prerequisite_of", "implemented_in",
    "has_syntax", "expresses_concept", "has_code_structure", "demonstrates",
    "uses_syntax", "contains_structure", "assesses", "requires_skill", "may_cause",
    "confused_with", "equivalent_to", "differs_from", "inherits_from", "implements_interface",
}

RELATION_SCHEMA: dict[str, tuple[set[str], set[str]]] = {
    "belongs_to_paradigm": ({"OOPConcept", "SyntaxRule", "CodeStructure"}, {"ProgrammingParadigm"}),
    "part_of": ({"OOPConcept", "SyntaxRule", "CodeStructure"}, {"OOPConcept", "CodeStructure"}),
    "prerequisite_of": ({"OOPConcept"}, {"OOPConcept"}),
    "implemented_in": ({"ProgrammingParadigm", "OOPConcept", "SyntaxRule", "CodeStructure"}, {"ProgrammingLanguage"}),
    "has_syntax": ({"OOPConcept"}, {"SyntaxRule"}),
    "expresses_concept": ({"SyntaxRule"}, {"OOPConcept"}),
    "has_code_structure": ({"OOPConcept"}, {"CodeStructure"}),
    "demonstrates": ({"CodeExample"}, {"OOPConcept"}),
    "uses_syntax": ({"CodeExample"}, {"SyntaxRule"}),
    "contains_structure": ({"CodeExample"}, {"CodeStructure"}),
    "assesses": ({"Exercise"}, {"OOPConcept", "Skill"}),
    "requires_skill": ({"OOPConcept", "Exercise", "CodeExample"}, {"Skill"}),
    "may_cause": ({"OOPConcept", "Skill"}, {"ErrorPattern"}),
    "confused_with": ({"OOPConcept", "SyntaxRule"}, {"OOPConcept", "SyntaxRule"}),
    "equivalent_to": (ENTITY_TYPES, ENTITY_TYPES),
    "differs_from": ({"OOPConcept", "SyntaxRule", "ProgrammingLanguage"}, {"OOPConcept", "SyntaxRule", "ProgrammingLanguage"}),
    "inherits_from": ({"CodeStructure"}, {"CodeStructure"}),
    "implements_interface": ({"CodeStructure"}, {"CodeStructure"}),
}

ENTITY_NORMALIZATION = {
    "OOP": "面向对象编程",
    "面向对象": "面向对象编程",
    "面向对象程序设计": "面向对象编程",
    "ProgrammingParadigm": "面向对象编程",
    "object-oriented programming": "面向对象编程",
    "class": "类",
    "object": "对象",
    "method": "方法",
    "field": "属性",
    "member variable": "属性",
    "constructor": "构造方法",
    "inheritance": "继承",
    "polymorphism": "多态",
    "encapsulation": "封装",
    "interface": "接口",
}

OOP_CONCEPT_TERMS = {
    "类", "对象", "属性", "方法", "成员变量", "构造方法", "构造函数", "封装", "继承",
    "多态", "抽象", "抽象类", "接口", "重载", "重写", "父类", "子类", "动态绑定",
    "向上转型", "信息隐藏", "消息传递", "实例化", "类型",
}
FORCED_ENTITY_TYPES = {term: "OOPConcept" for term in OOP_CONCEPT_TERMS}
FORCED_ENTITY_TYPES.update({"面向对象编程": "ProgrammingParadigm", "Alan Kay的OOP五大原则": "OOPConcept", "OOP五大原则": "OOPConcept", "Java对象": "OOPConcept"})

SYNTAX_TERMS = {"class", "extends", "implements", "interface", "abstract", "final", "public", "private", "protected", "this", "super", "new", "static"}
SYNTAX_TO_CONCEPT = {"class": "类", "extends": "继承", "implements": "接口", "interface": "接口", "abstract": "抽象类", "private": "封装", "protected": "封装", "public": "封装", "this": "对象", "super": "继承", "new": "对象"}


@dataclass
class Entity:
    id: str
    name: str
    type: str
    description: str = ""
    confidence: float = 0.0
    source_chunk_ids: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Relation:
    id: str
    head: str
    head_type: str
    relation: str
    tail: str
    tail_type: str
    confidence: float
    evidence: str = ""
    source_chunk_ids: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)


class JsonCleaner:
    @staticmethod
    def parse(text: str) -> dict[str, Any]:
        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if fenced:
            text = fenced.group(1)
        if not text.startswith("{"):
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
        data = json.loads(text)
        data.setdefault("entities", [])
        data.setdefault("relations", [])
        return data


class LLMClient:
    PROVIDERS = {
        "qwen": {
            "api_key_env": "DASHSCOPE_API_KEY",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "model": "qwen-plus",
        },
        "deepseek": {
            "api_key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-chat",
        },
    }

    def __init__(self, provider: str, model: str | None, base_url: str | None, timeout: int, retries: int) -> None:
        self.provider = provider
        self.timeout = timeout
        self.retries = retries
        if provider == "rule":
            self.model = "rule-only"
            self.base_url = ""
            self.api_key = ""
            return
        if provider not in self.PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        config = self.PROVIDERS[provider]
        self.model = model or config["model"]
        self.base_url = base_url or config["base_url"]
        self.api_key = os.getenv(config["api_key_env"], "").strip()
        if not self.api_key:
            raise RuntimeError(f"Missing environment variable: {config['api_key_env']}")

    def extract(self, chunk: dict[str, Any]) -> dict[str, Any]:
        if self.provider == "rule":
            return {"entities": [], "relations": []}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": json.dumps({
                    "chunk_id": chunk.get("chunk_id"),
                    "source_file": chunk.get("source_file"),
                    "page": chunk.get("page"),
                    "language": chunk.get("language"),
                    "material_role": chunk.get("material_role"),
                    "keywords": chunk.get("keywords", []),
                    "content": chunk.get("content", ""),
                }, ensure_ascii=False, indent=2)},
            ],
            "temperature": 0.1,
        }
        return JsonCleaner.parse(self._post(payload))

    def _post(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(self.base_url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"API call failed: {last_error}")

    @staticmethod
    def _system_prompt() -> str:
        relation_schema = "\n".join(f"- {rel}: {sorted(h)} -> {sorted(t)}" for rel, (h, t) in sorted(RELATION_SCHEMA.items()))
        return f"""
你是一个编程领域知识图谱抽取助手。必须严格遵守 Schema。

实体类型只能从下面选择：{', '.join(sorted(ENTITY_TYPES))}
关系类型只能从下面选择：{', '.join(sorted(RELATION_TYPES))}
关系头尾类型必须满足：
{relation_schema}

规则：
1. 只抽取片段中有明确依据的内容，不要凭空扩展。
2. 不使用 related_to、contains、关联、包含 这类泛化关系。
3. CodeExample 可以作为实体；如果片段包含代码或代码形态，要抽取 CodeExample。
4. 代码里的具体类名、接口名、方法名属于 CodeStructure，不属于 OOPConcept。
5. Java、Python、C++ 属于 ProgrammingLanguage。
6. class、extends、implements、interface、abstract 等属于 SyntaxRule。
7. 类、对象、继承、多态、封装、抽象、接口等通用知识属于 OOPConcept。
8. CodeStructure 只用于具体代码标识符或结构，不要把“属性、方法、动态绑定、向上转型”标成 CodeStructure。
9. 每个实体和关系都要给 confidence，范围 0 到 1。
10. evidence 必须是原文中的短语或句子。

只输出 JSON：
{{"entities":[{{"name":"实体名称","type":"实体类型","description":"简短说明","confidence":0.9,"evidence":"原文证据"}}],"relations":[{{"head":"头实体","head_type":"头实体类型","relation":"关系类型","tail":"尾实体","tail_type":"尾实体类型","confidence":0.9,"evidence":"原文证据"}}]}}
""".strip()


class CacheStore:
    def __init__(self, cache_dir: Path, refresh_cache: bool) -> None:
        self.cache_dir = cache_dir
        self.refresh_cache = refresh_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict[str, Any] | None:
        if self.refresh_cache:
            return None
        path = self.cache_dir / f"{key}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        (self.cache_dir / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class RuleExtractor:
    def extract(self, chunk: dict[str, Any]) -> dict[str, Any]:
        content = str(chunk.get("content", ""))
        normalized = self._normalize(content)
        language = str(chunk.get("language") or "")
        role = str(chunk.get("material_role") or "")
        entities: list[dict[str, Any]] = [self._entity("面向对象编程", "ProgrammingParadigm", "面向对象编程范式", 0.95, "面向对象")]
        relations: list[dict[str, Any]] = []
        if language and language not in {"通用OOP", "未识别"}:
            entities.append(self._entity(language, "ProgrammingLanguage", "编程语言", 0.9, language))
        concepts = sorted({term for term in OOP_CONCEPT_TERMS if term in normalized}, key=lambda x: (len(x), x))
        syntax_rules = sorted({term for term in SYNTAX_TERMS if re.search(rf"\b{re.escape(term)}\b", content.lower())}, key=lambda x: (len(x), x))
        structures = self._code_structures(content)
        for concept in concepts:
            entities.append(self._entity(concept, "OOPConcept", "面向对象核心概念", 0.82, concept))
            relations.append(self._relation(concept, "OOPConcept", "belongs_to_paradigm", "面向对象编程", "ProgrammingParadigm", 0.88, concept))
            if language and language not in {"通用OOP", "未识别"}:
                relations.append(self._relation(concept, "OOPConcept", "implemented_in", language, "ProgrammingLanguage", 0.72, language))
        for syntax in syntax_rules:
            entities.append(self._entity(syntax, "SyntaxRule", "编程语言语法规则", 0.86, syntax))
            if language and language not in {"通用OOP", "未识别"}:
                relations.append(self._relation(syntax, "SyntaxRule", "implemented_in", language, "ProgrammingLanguage", 0.8, syntax))
            concept = SYNTAX_TO_CONCEPT.get(syntax)
            if concept:
                entities.append(self._entity(concept, "OOPConcept", "面向对象核心概念", 0.8, concept))
                relations.append(self._relation(concept, "OOPConcept", "has_syntax", syntax, "SyntaxRule", 0.86, syntax))
                relations.append(self._relation(syntax, "SyntaxRule", "expresses_concept", concept, "OOPConcept", 0.86, syntax))
        if role == "code_example" or self._looks_like_code(content):
            code_name = f"CodeExample_{chunk.get('chunk_id', 'unknown')}"
            entities.append(self._entity(code_name, "CodeExample", "教学材料中的代码示例", 0.9, content[:120]))
            for concept in concepts:
                relations.append(self._relation(code_name, "CodeExample", "demonstrates", concept, "OOPConcept", 0.82, concept))
            for syntax in syntax_rules:
                relations.append(self._relation(code_name, "CodeExample", "uses_syntax", syntax, "SyntaxRule", 0.84, syntax))
            for structure in structures:
                entities.append(self._entity(structure["name"], "CodeStructure", structure["description"], 0.86, structure["evidence"]))
                relations.append(self._relation(code_name, "CodeExample", "contains_structure", structure["name"], "CodeStructure", 0.86, structure["evidence"]))
        for head, rel, tail, ev in self._structure_relations(content):
            entities.append(self._entity(head, "CodeStructure", "代码结构实体", 0.86, ev))
            entities.append(self._entity(tail, "CodeStructure", "代码结构实体", 0.86, ev))
            relations.append(self._relation(head, "CodeStructure", rel, tail, "CodeStructure", 0.88, ev))
        return {"entities": entities, "relations": relations}

    @staticmethod
    def _entity(name: str, entity_type: str, description: str, confidence: float, evidence: str) -> dict[str, Any]:
        return {"name": name, "type": entity_type, "description": description, "confidence": confidence, "evidence": evidence}

    @staticmethod
    def _relation(head: str, head_type: str, relation: str, tail: str, tail_type: str, confidence: float, evidence: str) -> dict[str, Any]:
        return {"head": head, "head_type": head_type, "relation": relation, "tail": tail, "tail_type": tail_type, "confidence": confidence, "evidence": evidence}

    @staticmethod
    def _normalize(content: str) -> str:
        for old, new in ENTITY_NORMALIZATION.items():
            content = re.sub(re.escape(old), new, content, flags=re.IGNORECASE)
        return content

    @staticmethod
    def _looks_like_code(content: str) -> bool:
        return bool(re.search(r"\b(class|interface|extends|implements|public|private|protected|void|new)\b|[{};]", content))

    @staticmethod
    def _code_structures(content: str) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for m in re.finditer(r"\bclass\s+([A-Za-z_]\w*)", content):
            items.append({"name": m.group(1), "description": "代码中的类结构", "evidence": m.group(0)})
        for m in re.finditer(r"\binterface\s+([A-Za-z_]\w*)", content):
            items.append({"name": m.group(1), "description": "代码中的接口结构", "evidence": m.group(0)})
        for m in re.finditer(r"\b(?:public|private|protected)?\s*(?:static\s+)?(?:void|int|String|boolean|double|float|char)\s+([A-Za-z_]\w*)\s*\(", content):
            items.append({"name": m.group(1), "description": "代码中的方法结构", "evidence": m.group(0)})
        return items

    @staticmethod
    def _structure_relations(content: str) -> list[tuple[str, str, str, str]]:
        rels: list[tuple[str, str, str, str]] = []
        for m in re.finditer(r"\bclass\s+([A-Za-z_]\w*)\s+extends\s+([A-Za-z_]\w*)", content):
            rels.append((m.group(1), "inherits_from", m.group(2), m.group(0)))
        for m in re.finditer(r"\bclass\s+([A-Za-z_]\w*)\s+implements\s+([A-Za-z_]\w*)", content):
            rels.append((m.group(1), "implements_interface", m.group(2), m.group(0)))
        return rels


class GraphExtractor:
    def __init__(self, llm: LLMClient, cache: CacheStore, min_entity_conf: float, min_relation_conf: float) -> None:
        self.llm = llm
        self.cache = cache
        self.rule_extractor = RuleExtractor()
        self.min_entity_conf = min_entity_conf
        self.min_relation_conf = min_relation_conf
        self.entities: dict[tuple[str, str], Entity] = {}
        self.relations: dict[tuple[str, str, str], Relation] = {}
        self.failures: list[dict[str, Any]] = []
        self.invalid_entities: list[dict[str, Any]] = []
        self.invalid_relations: list[dict[str, Any]] = []
        self.cache_hits = 0
        self.api_calls = 0

    def run(self, chunks: list[dict[str, Any]]) -> tuple[list[Entity], list[Relation], dict[str, Any]]:
        for index, chunk in enumerate(chunks, start=1):
            chunk_id = str(chunk.get("chunk_id") or f"chunk_{index}")
            print(f"[{index}/{len(chunks)}] 抽取 {chunk_id}")
            self._merge_result(chunk, self._extract_one(chunk))
        entities = sorted(self.entities.values(), key=lambda x: (x.type, x.name))
        relations = sorted(self.relations.values(), key=lambda x: (x.relation, x.head, x.tail))
        return entities, relations, self._report(chunks, entities, relations)

    def _extract_one(self, chunk: dict[str, Any]) -> dict[str, Any]:
        rule_result = self.rule_extractor.extract(chunk)
        if self.llm.provider == "rule":
            return rule_result
        key = self._cache_key(chunk)
        cached = self.cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            llm_result = cached
        else:
            try:
                llm_result = self.llm.extract(chunk)
                self.api_calls += 1
                self.cache.set(key, llm_result)
            except Exception as exc:  # Keep the demo running when one chunk fails.
                self.failures.append({"chunk_id": chunk.get("chunk_id"), "source_file": chunk.get("source_file"), "page": chunk.get("page"), "error": str(exc)})
                llm_result = {"entities": [], "relations": []}
        return {"entities": rule_result.get("entities", []) + llm_result.get("entities", []), "relations": rule_result.get("relations", []) + llm_result.get("relations", [])}

    def _merge_result(self, chunk: dict[str, Any], result: dict[str, Any]) -> None:
        source = self._source(chunk)
        for raw in result.get("entities", []):
            ent = self._normalize_entity(raw, source)
            if ent is None or ent.confidence < self.min_entity_conf:
                continue
            self._add_entity(ent)
        for raw in result.get("relations", []):
            rel = self._normalize_relation(raw, source)
            if rel is None or rel.confidence < self.min_relation_conf:
                continue
            if not self._relation_valid(rel):
                self.invalid_relations.append({"reason": "schema_invalid", "raw": raw, "source": source})
                continue
            self._ensure_endpoint(rel.head, rel.head_type, rel.confidence, source)
            self._ensure_endpoint(rel.tail, rel.tail_type, rel.confidence, source)
            self._add_relation(rel)

    def _normalize_entity(self, raw: dict[str, Any], source: dict[str, Any]) -> Entity | None:
        name = self._normalize_name(str(raw.get("name", "")).strip())
        entity_type = self._normalize_entity_type(name, str(raw.get("type", "")).strip())
        if not name or entity_type not in ENTITY_TYPES:
            self.invalid_entities.append({"reason": "schema_invalid", "raw": raw, "source": source})
            return None
        conf = self._adjust_conf(float(raw.get("confidence", 0.72) or 0.72), raw.get("evidence"), source)
        return Entity(self._entity_id(name, entity_type), name, entity_type, str(raw.get("description", "")).strip(), conf, [source["chunk_id"]], [source])

    def _normalize_relation(self, raw: dict[str, Any], source: dict[str, Any]) -> Relation | None:
        head = self._normalize_name(str(raw.get("head", "")).strip())
        tail = self._normalize_name(str(raw.get("tail", "")).strip())
        head_type = self._normalize_entity_type(head, str(raw.get("head_type", "")).strip())
        tail_type = self._normalize_entity_type(tail, str(raw.get("tail_type", "")).strip())
        rel_type = str(raw.get("relation", "")).strip()
        head, head_type, rel_type, tail, tail_type = self._repair_relation(head, head_type, rel_type, tail, tail_type)
        if not head or not tail or rel_type not in RELATION_TYPES or head_type not in ENTITY_TYPES or tail_type not in ENTITY_TYPES:
            self.invalid_relations.append({"reason": "schema_invalid", "raw": raw, "source": source})
            return None
        conf = self._adjust_conf(float(raw.get("confidence", 0.7) or 0.7), raw.get("evidence"), source)
        return Relation(self._relation_id(head, rel_type, tail), head, head_type, rel_type, tail, tail_type, conf, str(raw.get("evidence", "")).strip(), [source["chunk_id"]], [source])

    @staticmethod
    def _repair_relation(head: str, head_type: str, rel: str, tail: str, tail_type: str) -> tuple[str, str, str, str, str]:
        if rel == "part_of" and head_type == "OOPConcept" and tail_type == "ProgrammingParadigm":
            return head, head_type, "belongs_to_paradigm", tail, tail_type
        if rel == "part_of" and head_type == "OOPConcept" and tail_type == "ProgrammingLanguage":
            return head, head_type, "implemented_in", tail, tail_type
        if rel == "belongs_to_paradigm" and head_type == "ProgrammingParadigm" and tail_type == "OOPConcept":
            return tail, tail_type, "belongs_to_paradigm", head, head_type
        if rel == "belongs_to_paradigm" and head_type == "ProgrammingLanguage" and tail_type == "ProgrammingParadigm":
            return tail, tail_type, "implemented_in", head, head_type
        if rel == "has_code_structure" and head_type == "OOPConcept" and tail_type == "OOPConcept":
            return tail, tail_type, "part_of", head, head_type
        if rel == "has_syntax" and head_type == "SyntaxRule" and tail_type == "OOPConcept":
            return tail, tail_type, "has_syntax", head, head_type
        if rel == "expresses_concept" and head_type == "OOPConcept" and tail_type == "OOPConcept":
            return head, head_type, "part_of", tail, tail_type
        return head, head_type, rel, tail, tail_type

    def _relation_valid(self, rel: Relation) -> bool:
        heads, tails = RELATION_SCHEMA[rel.relation]
        return rel.head_type in heads and rel.tail_type in tails

    def _ensure_endpoint(self, name: str, entity_type: str, confidence: float, source: dict[str, Any]) -> None:
        key = (name, entity_type)
        if key not in self.entities:
            self._add_entity(Entity(self._entity_id(name, entity_type), name, entity_type, "由关系端点补全的实体", max(self.min_entity_conf, confidence - 0.05), [source["chunk_id"]], [source]))

    def _add_entity(self, ent: Entity) -> None:
        key = (ent.name, ent.type)
        old = self.entities.get(key)
        if old is None:
            self.entities[key] = ent
            return
        old.confidence = round(max(old.confidence, ent.confidence), 4)
        if ent.description and len(ent.description) > len(old.description):
            old.description = ent.description
        self._merge_unique(old.source_chunk_ids, ent.source_chunk_ids)
        self._merge_sources(old.sources, ent.sources)

    def _add_relation(self, rel: Relation) -> None:
        key = (rel.head, rel.relation, rel.tail)
        old = self.relations.get(key)
        if old is None:
            self.relations[key] = rel
            return
        old.confidence = round(max(old.confidence, rel.confidence), 4)
        if rel.evidence and len(rel.evidence) > len(old.evidence):
            old.evidence = rel.evidence
        self._merge_unique(old.source_chunk_ids, rel.source_chunk_ids)
        self._merge_sources(old.sources, rel.sources)

    @staticmethod
    def _merge_unique(target: list[str], values: list[str]) -> None:
        for value in values:
            if value not in target:
                target.append(value)

    @staticmethod
    def _merge_sources(target: list[dict[str, Any]], values: list[dict[str, Any]]) -> None:
        seen = {(x.get("chunk_id"), x.get("source_file"), x.get("page")) for x in target}
        for value in values:
            key = (value.get("chunk_id"), value.get("source_file"), value.get("page"))
            if key not in seen:
                target.append(value)
                seen.add(key)

    @staticmethod
    def _normalize_name(name: str) -> str:
        name = re.sub(r"\s+", " ", name).strip()
        for old, new in ENTITY_NORMALIZATION.items():
            if name.lower() == old.lower():
                return new
        return name

    @staticmethod
    def _normalize_entity_type(name: str, entity_type: str) -> str:
        return FORCED_ENTITY_TYPES.get(name, entity_type)

    @staticmethod
    def _adjust_conf(confidence: float, evidence: Any, source: dict[str, Any]) -> float:
        score = max(0.0, min(float(confidence), 1.0))
        ev = str(evidence or "").strip()
        content = str(source.get("content", ""))
        if ev and ev in content:
            score += 0.05
        if not ev:
            score -= 0.08
        return round(max(0.0, min(score, 0.98)), 4)

    @staticmethod
    def _source(chunk: dict[str, Any]) -> dict[str, Any]:
        return {"chunk_id": str(chunk.get("chunk_id", "")), "source_file": chunk.get("source_file"), "page": chunk.get("page"), "evidence_location": chunk.get("evidence_location"), "material_role": chunk.get("material_role"), "content": chunk.get("content", "")}

    @staticmethod
    def _entity_id(name: str, entity_type: str) -> str:
        return "ent_" + hashlib.md5(f"{entity_type}:{name}".encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _relation_id(head: str, rel: str, tail: str) -> str:
        return "rel_" + hashlib.md5(f"{head}:{rel}:{tail}".encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _cache_key(chunk: dict[str, Any]) -> str:
        raw = json.dumps({"schema": SCHEMA_VERSION, "chunk_id": chunk.get("chunk_id"), "content": chunk.get("content")}, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _report(self, chunks: list[dict[str, Any]], entities: list[Entity], relations: list[Relation]) -> dict[str, Any]:
        total_invalid = len(self.invalid_entities) + len(self.invalid_relations)
        total_valid = len(entities) + len(relations)
        return {
            "schema_version": SCHEMA_VERSION,
            "total_chunks": len(chunks),
            "processed_chunks": len(chunks),
            "entity_count": len(entities),
            "relation_count": len(relations),
            "entity_type_distribution": self._dist([x.type for x in entities]),
            "relation_type_distribution": self._dist([x.relation for x in relations]),
            "average_entity_confidence": self._avg([x.confidence for x in entities]),
            "average_relation_confidence": self._avg([x.confidence for x in relations]),
            "invalid_entity_count": len(self.invalid_entities),
            "invalid_relation_count": len(self.invalid_relations),
            "schema_valid_rate": round(total_valid / (total_valid + total_invalid), 4) if total_valid + total_invalid else 1.0,
            "api_calls": self.api_calls,
            "cache_hits": self.cache_hits,
            "failure_count": len(self.failures),
            "failures": self.failures[:50],
            "quality_rules": {
                "schema_validity": "实体类型和关系类型必须属于预定义 Schema。",
                "type_consistency": "关系头尾实体类型必须满足 RELATION_SCHEMA。",
                "evidence_traceability": "实体和关系保留 source_file/page/chunk_id/evidence_location。",
                "deduplication": "实体按 name+type 合并，关系按 head+relation+tail 合并。",
            },
        }

    @staticmethod
    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    @staticmethod
    def _dist(values: list[str]) -> dict[str, int]:
        result: dict[str, int] = {}
        for value in values:
            result[value] = result.get(value, 0) + 1
        return dict(sorted(result.items()))


def load_chunks(path: Path, limit: int | None) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("clean_chunks.json 顶层必须是数组。")
    return data[:limit] if limit is not None else data


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, list):
        payload = [x.__dict__ if hasattr(x, "__dict__") else x for x in payload]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract OOP knowledge graph entities and relations from clean chunks.")
    parser.add_argument("--input", required=True, help="Path to clean_chunks.json")
    parser.add_argument("--output-dir", required=True, help="Folder for entities.json, relations.json, extraction_report.json")
    parser.add_argument("--provider", default="qwen", choices=["qwen", "deepseek", "rule"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--min-entity-confidence", type=float, default=0.55)
    parser.add_argument("--min-relation-confidence", type=float, default=0.6)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    chunks = load_chunks(Path(args.input), args.limit)
    out_dir = Path(args.output_dir)
    extractor = GraphExtractor(
        llm=LLMClient(args.provider, args.model, args.base_url, args.timeout, args.retries),
        cache=CacheStore(out_dir / "api_cache", args.refresh_cache),
        min_entity_conf=args.min_entity_confidence,
        min_relation_conf=args.min_relation_confidence,
    )
    entities, relations, report = extractor.run(chunks)
    write_json(out_dir / "entities.json", entities)
    write_json(out_dir / "relations.json", relations)
    write_json(out_dir / "extraction_report.json", report)
    print(f"实体数量：{len(entities)}")
    print(f"关系数量：{len(relations)}")
    print(f"质量报告：{out_dir / 'extraction_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
