"""
第二阶段：从 clean_chunks.json 中抽取实体和关系。

这一阶段接在 preprocess_materials.py 后面：

    clean_chunks.json
    → 规则抽取明显的编程实体
    → 调用大模型 API 抽取语义实体和关系
    → 按 Schema 做合法性校验
    → 去重、合并、质量统计
    → 输出 entities.json / relations.json / extraction_report.json

设计重点：
1. 实体类型采用“分层 Schema”，避免老师指出的“实体类型不在同一维度”问题。
2. 关系类型采用“收敛 Schema”，避免泛泛的 related_to、contains 之类关系。
3. Demo 阶段不把 TeachingResource 作为节点，来源保存在 source_file/page/chunk_id 属性中。
4. CodeExample 作为实体保留，用来体现编程知识图谱的代码特色。
5. 支持通义千问和 DeepSeek 的 OpenAI-compatible API；默认使用通义千问。
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


# 实体类型：按层级设计，避免把“类、Java、习题、代码示例”混在同一维度。
ENTITY_TYPES = {
    "ProgrammingParadigm",  # 编程范式：面向对象编程
    "OOPConcept",  # OOP 核心概念：类、对象、继承、多态等
    "CodeStructure",  # 代码结构：Student 类、main 方法、继承结构等
    "SyntaxRule",  # 语法规则：class、extends、implements 等
    "ProgrammingLanguage",  # 编程语言：Java、Python、C++
    "CodeExample",  # 代码示例：来自 PPT/PDF 的代码片段
    "Exercise",  # 习题：选择题、编程题、改错题
    "ErrorPattern",  # 错误模式：重写签名错误、忘记实例化对象等
    "Skill",  # 能力要求：分析继承关系、判断多态调用结果等
}


# 关系类型：只保留语义明确的关系，避免泛化为“相关”。
RELATION_TYPES = {
    "belongs_to_paradigm",
    "part_of",
    "prerequisite_of",
    "implemented_in",
    "has_syntax",
    "expresses_concept",
    "has_code_structure",
    "demonstrates",
    "uses_syntax",
    "contains_structure",
    "assesses",
    "requires_skill",
    "may_cause",
    "confused_with",
    "equivalent_to",
    "differs_from",
    # 下面两个是为了表达代码结构中特有的继承/接口实现关系。
    # 它们不是泛化关系，而是编程领域很具体的结构关系。
    "inherits_from",
    "implements_interface",
}


# 每种关系允许的头尾实体类型。校验时会用它挡掉不合理关系。
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


# 常见术语归一化，避免 OOP / 面向对象程序设计 / 面向对象编程被当成多个实体。
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


# 规则抽取用的 OOP 概念词典。API 抽取失败时，这些规则可以兜底。
OOP_CONCEPT_TERMS = {
    "类",
    "对象",
    "属性",
    "方法",
    "成员变量",
    "构造方法",
    "构造函数",
    "封装",
    "继承",
    "多态",
    "抽象",
    "抽象类",
    "接口",
    "重载",
    "重写",
    "父类",
    "子类",
    "动态绑定",
    "向上转型",
    "信息隐藏",
    "消息传递",
    "实例化",
    "类型",
}


# 模型有时会把“动态绑定、属性、方法”误标成 CodeStructure。
# 这里建立一个强制类型映射：只要名称属于通用 OOP 术语，就归为 OOPConcept。
FORCED_ENTITY_TYPES = {
    term: "OOPConcept" for term in OOP_CONCEPT_TERMS
}
FORCED_ENTITY_TYPES.update(
    {
        "面向对象编程": "ProgrammingParadigm",
        "Alan Kay的OOP五大原则": "OOPConcept",
        "OOP五大原则": "OOPConcept",
        "Java对象": "OOPConcept",
    }
)


SYNTAX_TERMS = {
    "class",
    "extends",
    "implements",
    "interface",
    "abstract",
    "final",
    "public",
    "private",
    "protected",
    "this",
    "super",
    "new",
    "static",
}


SYNTAX_TO_CONCEPT = {
    "class": "类",
    "extends": "继承",
    "implements": "接口",
    "interface": "接口",
    "abstract": "抽象类",
    "private": "封装",
    "protected": "封装",
    "public": "封装",
    "this": "对象",
    "super": "继承",
    "new": "对象",
}


@dataclass
class Entity:
    """图谱实体。"""

    id: str
    name: str
    type: str
    description: str = ""
    confidence: float = 0.0
    source_chunk_ids: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Relation:
    """图谱关系。"""

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
    """从大模型返回文本中提取 JSON。"""

    @staticmethod
    def parse(text: str) -> dict[str, Any]:
        """支持纯 JSON 和 Markdown ```json 代码块。"""
        text = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if fenced:
            text = fenced.group(1)
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("模型返回的 JSON 顶层不是对象。")
        data.setdefault("entities", [])
        data.setdefault("relations", [])
        return data


class LLMClient:
    """
    大模型客户端。

    默认调用通义千问 DashScope 的 OpenAI-compatible 接口。
    同时预留 DeepSeek，方便后面切换。
    """

    PROVIDER_CONFIG = {
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
        if provider not in self.PROVIDER_CONFIG and provider != "rule":
            raise ValueError(f"不支持的 provider：{provider}")
        self.provider = provider
        self.timeout = timeout
        self.retries = retries
        if provider == "rule":
            self.model = "rule-only"
            self.base_url = ""
            self.api_key = ""
            return
        config = self.PROVIDER_CONFIG[provider]
        self.model = model or config["model"]
        self.base_url = base_url or config["base_url"]
        self.api_key = os.getenv(config["api_key_env"], "").strip()
        if not self.api_key:
            raise RuntimeError(f"未找到环境变量 {config['api_key_env']}，无法调用 {provider} API。")

    def extract(self, chunk: dict[str, Any]) -> dict[str, Any]:
        """调用模型，从一个 chunk 中抽取实体和关系。"""
        if self.provider == "rule":
            return {"entities": [], "relations": []}

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._user_prompt(chunk)},
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
        }
        raw_text = self._post_chat_completion(payload)
        return JsonCleaner.parse(raw_text)

    def _post_chat_completion(self, payload: dict[str, Any]) -> str:
        """发送 HTTP 请求；失败会按 retries 重试。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(self.base_url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response_body = response.read().decode("utf-8")
                data = json.loads(response_body)
                return data["choices"][0]["message"]["content"]
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"API 调用失败：{last_error}")

    @staticmethod
    def _system_prompt() -> str:
        """抽取提示词：强制模型按我们的 Schema 输出。"""
        entity_types = ", ".join(sorted(ENTITY_TYPES))
        relation_types = ", ".join(sorted(RELATION_TYPES))
        relation_schema_text = "\n".join(
            f"- {rel}: {sorted(head_types)} -> {sorted(tail_types)}"
            for rel, (head_types, tail_types) in sorted(RELATION_SCHEMA.items())
        )
        return f"""
你是一个编程领域知识图谱抽取助手。

你的任务：
从给定教学片段中抽取实体和关系，必须严格遵守 Schema。

实体类型只能从下面选择：
{entity_types}

关系类型只能从下面选择：
{relation_types}

关系头尾类型必须满足：
{relation_schema_text}

抽取原则：
1. 只抽取片段中有明确依据的内容，不要凭空扩展。
2. 不使用 related_to、contains、关联、包含 这类泛化关系。
3. CodeExample 可以作为实体；如果片段包含代码或代码形态，要抽取 CodeExample。
4. 代码里的具体类名、接口名、方法名属于 CodeStructure，不属于 OOPConcept。
5. Java、Python、C++ 属于 ProgrammingLanguage。
6. class、extends、implements、interface、abstract 等属于 SyntaxRule。
7. 类、对象、继承、多态、封装、抽象、接口等通用知识属于 OOPConcept。
8. CodeStructure 只用于具体代码标识符或结构，例如 Student、Person、main、Student extends Person；不要把“属性、方法、动态绑定、向上转型”标成 CodeStructure。
9. 每个实体和关系都要给 confidence，范围 0 到 1。
10. evidence 必须是原文中的短语或句子。

只输出 JSON，不要输出解释文字。格式如下：
{{
  "entities": [
    {{
      "name": "实体名称",
      "type": "实体类型",
      "description": "简短说明",
      "confidence": 0.90,
      "evidence": "原文证据"
    }}
  ],
  "relations": [
    {{
      "head": "头实体",
      "head_type": "头实体类型",
      "relation": "关系类型",
      "tail": "尾实体",
      "tail_type": "尾实体类型",
      "confidence": 0.90,
      "evidence": "原文证据"
    }}
  ]
}}
""".strip()

    @staticmethod
    def _user_prompt(chunk: dict[str, Any]) -> str:
        """把 chunk 和来源信息交给模型。"""
        return json.dumps(
            {
                "chunk_id": chunk.get("chunk_id"),
                "source_file": chunk.get("source_file"),
                "page": chunk.get("page"),
                "language": chunk.get("language"),
                "material_role": chunk.get("material_role"),
                "keywords": chunk.get("keywords", []),
                "content": chunk.get("content", ""),
            },
            ensure_ascii=False,
            indent=2,
        )


class CacheStore:
    """API 缓存，避免同一个 chunk 反复花 token。"""

    def __init__(self, cache_dir: Path, refresh_cache: bool) -> None:
        self.cache_dir = cache_dir
        self.refresh_cache = refresh_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> dict[str, Any] | None:
        if self.refresh_cache:
            return None
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self.cache_dir / f"{key}.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class RuleExtractor:
    """
    规则抽取器。

    这部分体现“编程类知识图谱的特定处理方式”：
    明显的语言、语法关键字、代码结构不完全依赖 LLM，而是用规则稳定抽取。
    """

    def extract(self, chunk: dict[str, Any]) -> dict[str, Any]:
        content = str(chunk.get("content", ""))
        normalized = self._normalize_content(content)
        language = str(chunk.get("language") or "")
        material_role = str(chunk.get("material_role") or "")
        entities: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []

        entities.append(self._entity("面向对象编程", "ProgrammingParadigm", "面向对象编程范式", 0.95, "面向对象"))

        if language and language not in {"通用OOP", "未识别"}:
            entities.append(self._entity(language, "ProgrammingLanguage", "编程语言", 0.9, language))

        concepts = self._extract_concepts(normalized)
        syntax_rules = self._extract_syntax_rules(content)
        structures = self._extract_code_structures(content)

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

        if material_role == "code_example" or self._looks_like_code(content):
            code_name = f"CodeExample_{chunk.get('chunk_id', 'unknown')}"
            entities.append(self._entity(code_name, "CodeExample", "教学材料中的代码示例", 0.9, self._short_evidence(content)))
            for concept in concepts:
                relations.append(self._relation(code_name, "CodeExample", "demonstrates", concept, "OOPConcept", 0.82, concept))
            for syntax in syntax_rules:
                relations.append(self._relation(code_name, "CodeExample", "uses_syntax", syntax, "SyntaxRule", 0.84, syntax))
            for structure in structures:
                entities.append(self._entity(structure["name"], "CodeStructure", structure["description"], 0.86, structure["evidence"]))
                relations.append(
                    self._relation(code_name, "CodeExample", "contains_structure", structure["name"], "CodeStructure", 0.86, structure["evidence"])
                )

        for relation in self._extract_code_structure_relations(content):
            head, rel, tail, evidence = relation
            entities.append(self._entity(head, "CodeStructure", "代码结构实体", 0.86, evidence))
            entities.append(self._entity(tail, "CodeStructure", "代码结构实体", 0.86, evidence))
            relations.append(self._relation(head, "CodeStructure", rel, tail, "CodeStructure", 0.88, evidence))

        return {"entities": entities, "relations": relations}

    @staticmethod
    def _entity(name: str, entity_type: str, description: str, confidence: float, evidence: str) -> dict[str, Any]:
        return {
            "name": name,
            "type": entity_type,
            "description": description,
            "confidence": confidence,
            "evidence": evidence,
        }

    @staticmethod
    def _relation(
        head: str,
        head_type: str,
        relation: str,
        tail: str,
        tail_type: str,
        confidence: float,
        evidence: str,
    ) -> dict[str, Any]:
        return {
            "head": head,
            "head_type": head_type,
            "relation": relation,
            "tail": tail,
            "tail_type": tail_type,
            "confidence": confidence,
            "evidence": evidence,
        }

    @staticmethod
    def _normalize_content(content: str) -> str:
        normalized = content
        for old, new in ENTITY_NORMALIZATION.items():
            normalized = re.sub(re.escape(old), new, normalized, flags=re.IGNORECASE)
        return normalized

    @staticmethod
    def _extract_concepts(content: str) -> list[str]:
        return sorted({term for term in OOP_CONCEPT_TERMS if term in content}, key=lambda item: (len(item), item))

    @staticmethod
    def _extract_syntax_rules(content: str) -> list[str]:
        lower = content.lower()
        return sorted({term for term in SYNTAX_TERMS if re.search(rf"\b{re.escape(term)}\b", lower)}, key=lambda item: (len(item), item))

    @staticmethod
    def _extract_code_structures(content: str) -> list[dict[str, str]]:
        structures: list[dict[str, str]] = []
        for match in re.finditer(r"\bclass\s+([A-Za-z_]\w*)", content):
            structures.append({"name": match.group(1), "description": "代码中的类结构", "evidence": match.group(0)})
        for match in re.finditer(r"\binterface\s+([A-Za-z_]\w*)", content):
            structures.append({"name": match.group(1), "description": "代码中的接口结构", "evidence": match.group(0)})
        for match in re.finditer(r"\b(?:public|private|protected)?\s*(?:static\s+)?(?:void|int|String|boolean|double|float|char)\s+([A-Za-z_]\w*)\s*\(", content):
            structures.append({"name": match.group(1), "description": "代码中的方法结构", "evidence": match.group(0)})
        return structures

    @staticmethod
    def _extract_code_structure_relations(content: str) -> list[tuple[str, str, str, str]]:
        relations: list[tuple[str, str, str, str]] = []
        for match in re.finditer(r"\bclass\s+([A-Za-z_]\w*)\s+extends\s+([A-Za-z_]\w*)", content):
            evidence = match.group(0)
            relations.append((match.group(1), "inherits_from", match.group(2), evidence))
        for match in re.finditer(r"\bclass\s+([A-Za-z_]\w*)\s+implements\s+([A-Za-z_]\w*)", content):
            evidence = match.group(0)
            relations.append((match.group(1), "implements_interface", match.group(2), evidence))
        return relations

    @staticmethod
    def _looks_like_code(content: str) -> bool:
        return bool(re.search(r"\b(class|interface|extends|implements|public|private|protected|void|new)\b|[{};]", content))

    @staticmethod
    def _short_evidence(content: str) -> str:
        content = re.sub(r"\s+", " ", content).strip()
        return content[:120]


class GraphExtractor:
    """实体关系抽取总控类。"""

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
            combined = self._extract_one_chunk(chunk)
            self._merge_result(chunk, combined)

        entity_list = sorted(self.entities.values(), key=lambda item: (item.type, item.name))
        relation_list = sorted(self.relations.values(), key=lambda item: (item.relation, item.head, item.tail))
        report = self._build_report(chunks, entity_list, relation_list)
        return entity_list, relation_list, report

    def _extract_one_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]:
        rule_result = self.rule_extractor.extract(chunk)
        llm_result = {"entities": [], "relations": []}
        if self.llm.provider == "rule":
            return {
                "entities": rule_result.get("entities", []),
                "relations": rule_result.get("relations", []),
            }
        cache_key = self._cache_key(chunk)
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            llm_result = cached
        else:
            try:
                llm_result = self.llm.extract(chunk)
                self.api_calls += 1
                self.cache.set(cache_key, llm_result)
            except Exception as exc:  # noqa: BLE001 - Demo 阶段需要记录失败并继续。
                self.failures.append(
                    {
                        "chunk_id": chunk.get("chunk_id"),
                        "source_file": chunk.get("source_file"),
                        "page": chunk.get("page"),
                        "error": str(exc),
                    }
                )
        return {
            "entities": rule_result.get("entities", []) + llm_result.get("entities", []),
            "relations": rule_result.get("relations", []) + llm_result.get("relations", []),
        }

    def _merge_result(self, chunk: dict[str, Any], result: dict[str, Any]) -> None:
        source = self._source_info(chunk)
        valid_entity_keys: set[tuple[str, str]] = set()

        for raw_entity in result.get("entities", []):
            entity = self._normalize_entity(raw_entity, source)
            if entity is None:
                continue
            if entity.confidence < self.min_entity_conf:
                self.invalid_entities.append({"reason": "low_confidence", "raw": raw_entity, "source": source})
                continue
            key = (entity.name, entity.type)
            valid_entity_keys.add(key)
            self._add_entity(entity)

        for raw_relation in result.get("relations", []):
            relation = self._normalize_relation(raw_relation, source)
            if relation is None:
                continue
            if relation.confidence < self.min_relation_conf:
                self.invalid_relations.append({"reason": "low_confidence", "raw": raw_relation, "source": source})
                continue
            if not self._relation_type_is_valid(relation):
                self.invalid_relations.append({"reason": "schema_invalid", "raw": raw_relation, "source": source})
                continue
            self._ensure_relation_endpoints(relation, source, valid_entity_keys)
            self._add_relation(relation)

    def _normalize_entity(self, raw: dict[str, Any], source: dict[str, Any]) -> Entity | None:
        name = self._normalize_name(str(raw.get("name", "")).strip())
        entity_type = self._normalize_entity_type(name, str(raw.get("type", "")).strip())
        if not name or entity_type not in ENTITY_TYPES:
            self.invalid_entities.append({"reason": "schema_invalid", "raw": raw, "source": source})
            return None
        confidence = self._adjust_confidence(float(raw.get("confidence", 0.72) or 0.72), raw.get("evidence"), source)
        return Entity(
            id=self._entity_id(name, entity_type),
            name=name,
            type=entity_type,
            description=str(raw.get("description", "")).strip(),
            confidence=confidence,
            source_chunk_ids=[source["chunk_id"]],
            sources=[source],
        )

    def _normalize_relation(self, raw: dict[str, Any], source: dict[str, Any]) -> Relation | None:
        head = self._normalize_name(str(raw.get("head", "")).strip())
        tail = self._normalize_name(str(raw.get("tail", "")).strip())
        head_type = self._normalize_entity_type(head, str(raw.get("head_type", "")).strip())
        tail_type = self._normalize_entity_type(tail, str(raw.get("tail_type", "")).strip())
        relation_type = str(raw.get("relation", "")).strip()
        head, head_type, relation_type, tail, tail_type = self._repair_relation_fields(
            head=head,
            head_type=head_type,
            relation_type=relation_type,
            tail=tail,
            tail_type=tail_type,
        )
        if not head or not tail or relation_type not in RELATION_TYPES:
            self.invalid_relations.append({"reason": "schema_invalid", "raw": raw, "source": source})
            return None
        if head_type not in ENTITY_TYPES or tail_type not in ENTITY_TYPES:
            self.invalid_relations.append({"reason": "endpoint_type_invalid", "raw": raw, "source": source})
            return None
        confidence = self._adjust_confidence(float(raw.get("confidence", 0.7) or 0.7), raw.get("evidence"), source)
        return Relation(
            id=self._relation_id(head, relation_type, tail),
            head=head,
            head_type=head_type,
            relation=relation_type,
            tail=tail,
            tail_type=tail_type,
            confidence=confidence,
            evidence=str(raw.get("evidence", "")).strip(),
            source_chunk_ids=[source["chunk_id"]],
            sources=[source],
        )

    @staticmethod
    def _repair_relation_fields(
        head: str,
        head_type: str,
        relation_type: str,
        tail: str,
        tail_type: str,
    ) -> tuple[str, str, str, str, str]:
        """
        修复模型常见的关系方向和关系类型偏差。

        这一步不是随便改关系，而是把“语义清楚但不符合 Schema”的表达规范化：
        - 封装 part_of 面向对象编程 → 封装 belongs_to_paradigm 面向对象编程
        - 面向对象编程 belongs_to_paradigm 对象 → 对象 belongs_to_paradigm 面向对象编程
        - Java belongs_to_paradigm 面向对象编程 → 面向对象编程 implemented_in Java
        - 对象 has_code_structure 方法 → 方法 part_of 对象
        - abstract has_syntax 抽象类 → 抽象类 has_syntax abstract
        - 重写 expresses_concept 多态 → 重写 part_of 多态
        """
        if relation_type == "part_of" and head_type == "OOPConcept" and tail_type == "ProgrammingParadigm":
            return head, head_type, "belongs_to_paradigm", tail, tail_type

        if relation_type == "part_of" and head_type == "OOPConcept" and tail_type == "ProgrammingLanguage":
            return head, head_type, "implemented_in", tail, tail_type

        if relation_type == "belongs_to_paradigm" and head_type == "ProgrammingParadigm" and tail_type == "OOPConcept":
            return tail, tail_type, "belongs_to_paradigm", head, head_type

        if relation_type == "belongs_to_paradigm" and head_type == "ProgrammingLanguage" and tail_type == "ProgrammingParadigm":
            return tail, tail_type, "implemented_in", head, head_type

        if relation_type == "has_code_structure" and head_type == "OOPConcept" and tail_type == "OOPConcept":
            return tail, tail_type, "part_of", head, head_type

        if relation_type == "has_syntax" and head_type == "SyntaxRule" and tail_type == "OOPConcept":
            return tail, tail_type, "has_syntax", head, head_type

        if relation_type == "expresses_concept" and head_type == "OOPConcept" and tail_type == "OOPConcept":
            return head, head_type, "part_of", tail, tail_type

        return head, head_type, relation_type, tail, tail_type

    def _relation_type_is_valid(self, relation: Relation) -> bool:
        head_types, tail_types = RELATION_SCHEMA[relation.relation]
        return relation.head_type in head_types and relation.tail_type in tail_types

    def _ensure_relation_endpoints(self, relation: Relation, source: dict[str, Any], valid_entity_keys: set[tuple[str, str]]) -> None:
        for name, entity_type in [(relation.head, relation.head_type), (relation.tail, relation.tail_type)]:
            key = (name, entity_type)
            if key not in self.entities and key not in valid_entity_keys:
                self._add_entity(
                    Entity(
                        id=self._entity_id(name, entity_type),
                        name=name,
                        type=entity_type,
                        description="由关系端点补全的实体",
                        confidence=max(self.min_entity_conf, relation.confidence - 0.05),
                        source_chunk_ids=[source["chunk_id"]],
                        sources=[source],
                    )
                )

    def _add_entity(self, entity: Entity) -> None:
        key = (entity.name, entity.type)
        old = self.entities.get(key)
        if old is None:
            self.entities[key] = entity
            return
        old.confidence = round(max(old.confidence, entity.confidence), 4)
        if entity.description and len(entity.description) > len(old.description):
            old.description = entity.description
        self._merge_unique(old.source_chunk_ids, entity.source_chunk_ids)
        self._merge_sources(old.sources, entity.sources)

    def _add_relation(self, relation: Relation) -> None:
        key = (relation.head, relation.relation, relation.tail)
        old = self.relations.get(key)
        if old is None:
            self.relations[key] = relation
            return
        old.confidence = round(max(old.confidence, relation.confidence), 4)
        if relation.evidence and len(relation.evidence) > len(old.evidence):
            old.evidence = relation.evidence
        self._merge_unique(old.source_chunk_ids, relation.source_chunk_ids)
        self._merge_sources(old.sources, relation.sources)

    @staticmethod
    def _merge_unique(target: list[str], new_values: list[str]) -> None:
        for value in new_values:
            if value not in target:
                target.append(value)

    @staticmethod
    def _merge_sources(target: list[dict[str, Any]], new_sources: list[dict[str, Any]]) -> None:
        seen = {(item.get("chunk_id"), item.get("source_file"), item.get("page")) for item in target}
        for source in new_sources:
            key = (source.get("chunk_id"), source.get("source_file"), source.get("page"))
            if key not in seen:
                target.append(source)
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
        """
        修正模型可能出现的类型漂移。

        例如“动态绑定”“向上转型”“属性”“方法”是 OOP 概念，
        不是具体代码结构；这里强制归为 OOPConcept。
        """
        if name in FORCED_ENTITY_TYPES:
            return FORCED_ENTITY_TYPES[name]
        return entity_type

    @staticmethod
    def _adjust_confidence(confidence: float, evidence: Any, source: dict[str, Any]) -> float:
        score = max(0.0, min(float(confidence), 1.0))
        evidence_text = str(evidence or "").strip()
        content = str(source.get("content", ""))
        if evidence_text and evidence_text in content:
            score += 0.05
        if not evidence_text:
            score -= 0.08
        return round(max(0.0, min(score, 0.98)), 4)

    @staticmethod
    def _source_info(chunk: dict[str, Any]) -> dict[str, Any]:
        return {
            "chunk_id": str(chunk.get("chunk_id", "")),
            "source_file": chunk.get("source_file"),
            "page": chunk.get("page"),
            "evidence_location": chunk.get("evidence_location"),
            "material_role": chunk.get("material_role"),
            "content": chunk.get("content", ""),
        }

    @staticmethod
    def _entity_id(name: str, entity_type: str) -> str:
        return "ent_" + hashlib.md5(f"{entity_type}:{name}".encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _relation_id(head: str, relation: str, tail: str) -> str:
        return "rel_" + hashlib.md5(f"{head}:{relation}:{tail}".encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _cache_key(chunk: dict[str, Any]) -> str:
        raw = json.dumps(
            {
                "schema": SCHEMA_VERSION,
                "chunk_id": chunk.get("chunk_id"),
                "content": chunk.get("content"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _build_report(self, chunks: list[dict[str, Any]], entities: list[Entity], relations: list[Relation]) -> dict[str, Any]:
        high_entities = sum(1 for item in entities if item.confidence >= 0.85)
        high_relations = sum(1 for item in relations if item.confidence >= 0.85)
        avg_entity_conf = self._average([item.confidence for item in entities])
        avg_relation_conf = self._average([item.confidence for item in relations])
        total_invalid = len(self.invalid_entities) + len(self.invalid_relations)
        total_valid = len(entities) + len(relations)
        schema_valid_rate = round(total_valid / (total_valid + total_invalid), 4) if total_valid + total_invalid else 1.0
        return {
            "schema_version": SCHEMA_VERSION,
            "total_chunks": len(chunks),
            "processed_chunks": len(chunks),
            "entity_count": len(entities),
            "relation_count": len(relations),
            "entity_type_distribution": self._distribution([item.type for item in entities]),
            "relation_type_distribution": self._distribution([item.relation for item in relations]),
            "high_confidence_entity_count": high_entities,
            "high_confidence_relation_count": high_relations,
            "average_entity_confidence": avg_entity_conf,
            "average_relation_confidence": avg_relation_conf,
            "invalid_entity_count": len(self.invalid_entities),
            "invalid_relation_count": len(self.invalid_relations),
            "schema_valid_rate": schema_valid_rate,
            "api_calls": self.api_calls,
            "cache_hits": self.cache_hits,
            "failure_count": len(self.failures),
            "failures": self.failures[:50],
            "quality_rules": {
                "schema_validity": "实体类型和关系类型必须属于预定义 Schema。",
                "type_consistency": "关系头尾实体类型必须满足 RELATION_SCHEMA。",
                "evidence_traceability": "实体和关系保留 source_file/page/chunk_id/evidence_location。",
                "confidence_thresholds": {
                    "entity_min_confidence": self.min_entity_conf,
                    "relation_min_confidence": self.min_relation_conf,
                    "high_confidence": ">= 0.85",
                },
                "deduplication": "实体按 name+type 合并，关系按 head+relation+tail 合并。",
            },
        }

    @staticmethod
    def _average(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    @staticmethod
    def _distribution(values: list[str]) -> dict[str, int]:
        result: dict[str, int] = {}
        for value in values:
            result[value] = result.get(value, 0) + 1
        return dict(sorted(result.items()))


def load_chunks(input_path: Path, limit: int | None) -> list[dict[str, Any]]:
    chunks = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(chunks, list):
        raise ValueError("clean_chunks.json 顶层必须是数组。")
    if limit is not None:
        return chunks[:limit]
    return chunks


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, list):
        serializable = [item.__dict__ if hasattr(item, "__dict__") else item for item in payload]
    elif hasattr(payload, "__dict__"):
        serializable = payload.__dict__
    else:
        serializable = payload
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract OOP knowledge graph entities and relations from clean chunks.")
    parser.add_argument("--input", required=True, help="Path to clean_chunks.json")
    parser.add_argument("--output-dir", required=True, help="Folder for entities.json, relations.json, extraction_report.json")
    parser.add_argument("--provider", default="qwen", choices=["qwen", "deepseek", "rule"], help="LLM provider. Use rule for local rule-only mode.")
    parser.add_argument("--model", default=None, help="Model name. Default: qwen-plus for qwen, deepseek-chat for deepseek")
    parser.add_argument("--base-url", default=None, help="Override OpenAI-compatible chat completions endpoint")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N chunks for debugging")
    parser.add_argument("--refresh-cache", action="store_true", help="Ignore API cache and call model again")
    parser.add_argument("--timeout", type=int, default=60, help="API timeout seconds")
    parser.add_argument("--retries", type=int, default=2, help="API retry count")
    parser.add_argument("--min-entity-confidence", type=float, default=0.55, help="Drop entities below this confidence")
    parser.add_argument("--min-relation-confidence", type=float, default=0.6, help="Drop relations below this confidence")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    cache_dir = output_dir / "api_cache"

    chunks = load_chunks(input_path, args.limit)
    llm = LLMClient(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        timeout=args.timeout,
        retries=args.retries,
    )
    cache = CacheStore(cache_dir=cache_dir, refresh_cache=args.refresh_cache)
    extractor = GraphExtractor(
        llm=llm,
        cache=cache,
        min_entity_conf=args.min_entity_confidence,
        min_relation_conf=args.min_relation_confidence,
    )

    entities, relations, report = extractor.run(chunks)

    write_json(output_dir / "entities.json", entities)
    write_json(output_dir / "relations.json", relations)
    write_json(output_dir / "extraction_report.json", report)

    print(f"实体数量：{len(entities)}")
    print(f"关系数量：{len(relations)}")
    print(f"质量报告：{output_dir / 'extraction_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
