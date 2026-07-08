"""
第三阶段：实体融合、关系消歧与标准图谱生成。

这一阶段接在 extract_graph.py 后面：

    entities.json / relations.json
    -> 实体名称标准化
    -> 实体类型修正
    -> 实体融合与消歧
    -> 关系类型规范化
    -> 关系质量过滤
    -> 输出 standard_graph.json / normalization_report.json

设计原则：
1. 先用规则处理确定性问题，再让大模型判断规则无法确定的部分。
2. 宁可少合并，也不要错合并。
3. 宁可少保留关系，也不要把不确定关系写进标准图谱。
4. standard_graph.json 面向 Neo4j 入库，结构保持 nodes + edges。
5. normalization_report.json 面向调试和汇报，记录合并、过滤和模型判断过程。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


try:
    from extract_graph import (  # type: ignore
        ENTITY_NORMALIZATION,
        ENTITY_TYPES,
        FORCED_ENTITY_TYPES,
        RELATION_SCHEMA,
        RELATION_TYPES,
        SCHEMA_VERSION,
    )
except ImportError as exc:  # pragma: no cover - 只有直接移动文件时才会触发
    raise RuntimeError("normalize_graph.py 需要和 extract_graph.py 放在同一个目录。") from exc


NORMALIZATION_SCHEMA_VERSION = "oop_kg_standard_graph_v1"


# 第二步的 Schema 是抽取 Schema；第三步要把外部表达收敛到这些内部类型。
ENTITY_TYPE_ALIASES = {
    "知识点": "OOPConcept",
    "概念": "OOPConcept",
    "编程概念": "OOPConcept",
    "面向对象概念": "OOPConcept",
    "oopconcept": "OOPConcept",
    "范式": "ProgrammingParadigm",
    "编程范式": "ProgrammingParadigm",
    "programmingparadigm": "ProgrammingParadigm",
    "代码结构": "CodeStructure",
    "类结构": "CodeStructure",
    "方法结构": "CodeStructure",
    "codestructure": "CodeStructure",
    "语法": "SyntaxRule",
    "语法规则": "SyntaxRule",
    "syntaxrule": "SyntaxRule",
    "语言": "ProgrammingLanguage",
    "编程语言": "ProgrammingLanguage",
    "programminglanguage": "ProgrammingLanguage",
    "代码示例": "CodeExample",
    "codeexample": "CodeExample",
    "习题": "Exercise",
    "练习题": "Exercise",
    "exercise": "Exercise",
    "错误模式": "ErrorPattern",
    "errorpattern": "ErrorPattern",
    "能力": "Skill",
    "技能": "Skill",
    "skill": "Skill",
}


# 实体别名表只做“同一个概念的不同写法”归一化，不做上下位概念合并。
ENTITY_NAME_ALIASES = {
    **ENTITY_NORMALIZATION,
    "JAVA": "Java",
    "Java语言": "Java",
    "java language": "Java",
    "面向对象方法": "面向对象编程",
    "面向对象技术": "面向对象编程",
    "面向对象语言": "面向对象编程",
    "object oriented programming": "面向对象编程",
    "oop": "面向对象编程",
    "for 循环": "for循环",
    "for-loop": "for循环",
    "for loop": "for循环",
    "for语句": "for循环",
    "class关键字": "class",
    "extends关键字": "extends",
    "implements关键字": "implements",
    "interface关键字": "interface",
    "成员函数": "方法",
    "成员方法": "方法",
    "成员变量": "属性",
    "构造函数": "构造方法",
    "上塑造型": "向上转型",
}


# 关系别名表负责把中文关系、大小写差异、Neo4j 风格写法收敛到第二步 Schema。
RELATION_ALIASES = {
    "属于": "part_of",
    "组成": "part_of",
    "包括": "part_of",
    "包含": "part_of",
    "是组成部分": "part_of",
    "partof": "part_of",
    "PART_OF": "part_of",
    "属于范式": "belongs_to_paradigm",
    "归属于范式": "belongs_to_paradigm",
    "belongs_to_paradigm": "belongs_to_paradigm",
    "BELONGS_TO_PARADIGM": "belongs_to_paradigm",
    "前置知识": "prerequisite_of",
    "先修": "prerequisite_of",
    "需要先学习": "prerequisite_of",
    "prerequisite": "prerequisite_of",
    "PREREQUISITE_OF": "prerequisite_of",
    "实现于": "implemented_in",
    "由语言实现": "implemented_in",
    "implemented_in": "implemented_in",
    "IMPLEMENTED_IN": "implemented_in",
    "语法是": "has_syntax",
    "具有语法": "has_syntax",
    "has_syntax": "has_syntax",
    "HAS_SYNTAX": "has_syntax",
    "表达": "expresses_concept",
    "表达概念": "expresses_concept",
    "expresses_concept": "expresses_concept",
    "EXPRESSES_CONCEPT": "expresses_concept",
    "演示": "demonstrates",
    "示例说明": "demonstrates",
    "demonstrates": "demonstrates",
    "DEMONSTRATES": "demonstrates",
    "使用语法": "uses_syntax",
    "uses_syntax": "uses_syntax",
    "USES_SYNTAX": "uses_syntax",
    "包含结构": "contains_structure",
    "contains_structure": "contains_structure",
    "CONTAINS_STRUCTURE": "contains_structure",
    "考察": "assesses",
    "测试": "assesses",
    "assesses": "assesses",
    "ASSESSES": "assesses",
    "需要能力": "requires_skill",
    "requires_skill": "requires_skill",
    "REQUIRES_SKILL": "requires_skill",
    "导致": "may_cause",
    "可能导致": "may_cause",
    "may_cause": "may_cause",
    "MAY_CAUSE": "may_cause",
    "易混淆": "confused_with",
    "容易混淆": "confused_with",
    "confused_with": "confused_with",
    "CONFUSED_WITH": "confused_with",
    "等价": "equivalent_to",
    "同义": "equivalent_to",
    "equivalent_to": "equivalent_to",
    "EQUIVALENT_TO": "equivalent_to",
    "不同于": "differs_from",
    "区别于": "differs_from",
    "differs_from": "differs_from",
    "DIFFERS_FROM": "differs_from",
    "继承": "inherits_from",
    "继承自": "inherits_from",
    "inherits_from": "inherits_from",
    "INHERITS_FROM": "inherits_from",
    "实现接口": "implements_interface",
    "implements_interface": "implements_interface",
    "IMPLEMENTS_INTERFACE": "implements_interface",
}


KEY_RELATIONS_FOR_LLM_REVIEW = {
    "equivalent_to",
    "differs_from",
    "inherits_from",
    "implements_interface",
    "prerequisite_of",
}


@dataclass
class PreparedEntity:
    """清洗后的实体，还没有完成最终融合。"""

    raw_id: str
    name: str
    type: str
    original_name: str
    original_type: str
    description: str = ""
    confidence: float = 0.0
    source_chunk_ids: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    inferred_from_relation: bool = False


@dataclass
class StandardNode:
    """可以写入 standard_graph.json 的标准节点。"""

    id: str
    name: str
    type: str
    aliases: list[str]
    description: str
    confidence: float
    source_chunk_ids: list[str]
    sources: list[dict[str, Any]]
    original_entity_ids: list[str]


@dataclass
class StandardEdge:
    """可以写入 standard_graph.json 的标准边。"""

    id: str
    source: str
    target: str
    type: str
    neo4j_type: str
    confidence: float
    evidence: str
    source_chunks: list[str]
    sources: list[dict[str, Any]]
    original_relation_ids: list[str]


class UnionFind:
    """实体融合用的并查集：把确认同义的实体放到同一组。"""

    def __init__(self, item_ids: list[str]) -> None:
        self.parent = {item_id: item_id for item_id in item_ids}

    def find(self, item_id: str) -> str:
        parent = self.parent[item_id]
        if parent != item_id:
            self.parent[item_id] = self.find(parent)
        return self.parent[item_id]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


class JsonCleaner:
    """从模型返回文本中提取 JSON 对象。"""

    @staticmethod
    def parse_object(text: str) -> dict[str, Any]:
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
        return data


class NormalizationCache:
    """大模型判断缓存，避免相同候选反复调用 API。"""

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


class LLMJudge:
    """
    大模型判断器。

    它不负责重新抽取知识，只负责判断“是否同义”“关系是否可信”等疑难问题。
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
        "rule": {
            "api_key_env": "",
            "base_url": "",
            "model": "rule-only",
        },
    }

    def __init__(
        self,
        provider: str,
        model: str | None,
        base_url: str | None,
        timeout: int,
        retries: int,
        cache: NormalizationCache,
    ) -> None:
        if provider not in self.PROVIDER_CONFIG:
            raise ValueError(f"不支持的 provider：{provider}")
        self.provider = provider
        self.timeout = timeout
        self.retries = retries
        self.cache = cache
        config = self.PROVIDER_CONFIG[provider]
        self.model = model or config["model"]
        self.base_url = base_url or config["base_url"]
        self.api_key = ""
        self.api_calls = 0
        self.cache_hits = 0
        if provider != "rule":
            self.api_key = os.getenv(config["api_key_env"], "").strip()
            if not self.api_key:
                raise RuntimeError(f"未找到环境变量 {config['api_key_env']}，无法调用 {provider} API。")

    @property
    def enabled(self) -> bool:
        return self.provider != "rule"

    def judge_entity_merge(self, entities: list[PreparedEntity]) -> dict[str, Any]:
        """判断一组候选实体是否应该合并。"""
        if not self.enabled:
            return {"should_merge": False, "confidence": 0.0, "reason": "未启用大模型。"}
        payload = {
            "task": "entity_merge",
            "schema_version": NORMALIZATION_SCHEMA_VERSION,
            "entities": [
                {
                    "id": item.raw_id,
                    "name": item.name,
                    "type": item.type,
                    "original_name": item.original_name,
                    "description": item.description,
                    "confidence": item.confidence,
                    "evidence": collect_evidence_snippets(item.sources, limit=2),
                }
                for item in entities
            ],
        }
        return self._cached_chat("entity_merge", payload, self._entity_merge_prompt(payload))

    def judge_relation(self, relation: dict[str, Any], source_node: StandardNode, target_node: StandardNode) -> dict[str, Any]:
        """判断一条关系是否可信，必要时给出修正后的关系类型。"""
        if not self.enabled:
            return {"action": "uncertain", "confidence": 0.0, "reason": "未启用大模型。"}
        payload = {
            "task": "relation_review",
            "schema_version": NORMALIZATION_SCHEMA_VERSION,
            "relation": {
                "id": relation.get("id", ""),
                "head": relation.get("head", ""),
                "relation": relation.get("relation", ""),
                "tail": relation.get("tail", ""),
                "confidence": relation.get("confidence", 0.0),
                "evidence": relation.get("evidence", ""),
            },
            "source_node": {
                "id": source_node.id,
                "name": source_node.name,
                "type": source_node.type,
                "aliases": source_node.aliases,
            },
            "target_node": {
                "id": target_node.id,
                "name": target_node.name,
                "type": target_node.type,
                "aliases": target_node.aliases,
            },
            "allowed_relations": relation_schema_for_prompt(source_node.type, target_node.type),
        }
        return self._cached_chat("relation_review", payload, self._relation_review_prompt(payload))

    def _cached_chat(self, kind: str, payload: dict[str, Any], messages: list[dict[str, str]]) -> dict[str, Any]:
        cache_key = hash_payload({"kind": kind, "payload": payload, "model": self.model})
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.cache_hits += 1
            return cached
        raw_text = self._post_chat_completion({"model": self.model, "messages": messages, "temperature": 0.0})
        result = JsonCleaner.parse_object(raw_text)
        self.api_calls += 1
        self.cache.set(cache_key, result)
        return result

    def _post_chat_completion(self, payload: dict[str, Any]) -> str:
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
    def _entity_merge_prompt(payload: dict[str, Any]) -> list[dict[str, str]]:
        entity_types = ", ".join(sorted(ENTITY_TYPES))
        return [
            {
                "role": "system",
                "content": f"""
你是编程领域知识图谱的实体消歧审查员。

实体类型只能从下面选择：
{entity_types}

判断原则：
1. 只有候选实体指向“同一个编程概念/同一个语法/同一个结构”时，才允许合并。
2. 只是相关、上下位、先修、组成关系，不能合并。
3. 抽象类、接口、类、对象、多态、继承、封装等概念不能因为相关就合并。
4. 不确定时必须返回 should_merge=false。
5. canonical_name 使用最适合写入图谱的中文或通用编程术语。

只输出 JSON：
{{
  "should_merge": true,
  "canonical_name": "标准名称",
  "canonical_type": "实体类型",
  "aliases": ["别名1", "别名2"],
  "confidence": 0.90,
  "reason": "一句话理由"
}}
""".strip(),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ]

    @staticmethod
    def _relation_review_prompt(payload: dict[str, Any]) -> list[dict[str, str]]:
        relation_types = ", ".join(sorted(RELATION_TYPES))
        return [
            {
                "role": "system",
                "content": f"""
你是编程领域知识图谱的关系审查员。

关系类型只能从下面选择：
{relation_types}

判断原则：
1. 只保留证据明确、语义清楚的关系。
2. 如果原关系类型不准确，可以修正为更合适的 relation_type。
3. 如果只是泛泛相关、证据不足、头尾方向错误且无法修正，返回 reject 或 uncertain。
4. 不确定时不要保留，返回 uncertain。
5. allowed_relations 给出了当前头尾类型允许的关系，优先从中选择。

只输出 JSON：
{{
  "action": "keep",
  "relation_type": "part_of",
  "confidence": 0.90,
  "reason": "一句话理由"
}}

action 只能是 keep、repair、reject、uncertain。
""".strip(),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ]


class GraphNormalizer:
    """第三阶段主流程。"""

    def __init__(
        self,
        llm: LLMJudge,
        min_entity_confidence: float,
        min_relation_confidence: float,
        max_llm_entity_groups: int,
        max_llm_relations: int,
        review_key_relations: bool,
    ) -> None:
        self.llm = llm
        self.min_entity_confidence = min_entity_confidence
        self.min_relation_confidence = min_relation_confidence
        self.max_llm_entity_groups = max_llm_entity_groups
        self.max_llm_relations = max_llm_relations
        self.review_key_relations = review_key_relations
        self.report: dict[str, Any] = {
            "merged_entities": [],
            "rejected_entities": [],
            "inferred_entities": [],
            "normalized_relations": [],
            "rejected_relations": [],
            "uncertain_relations": [],
            "llm_decisions": [],
            "warnings": [],
        }

    def normalize(self, raw_entities: list[dict[str, Any]], raw_relations: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        prepared_entities = self._prepare_entities(raw_entities, raw_relations)
        union_find = UnionFind([item.raw_id for item in prepared_entities])
        canonical_overrides: dict[str, dict[str, Any]] = {}

        self._merge_by_rules(prepared_entities, union_find)
        self._merge_by_equivalent_relations(prepared_entities, raw_relations, union_find)
        self._merge_by_llm(prepared_entities, union_find, canonical_overrides)

        nodes, entity_lookup = self._build_nodes(prepared_entities, union_find, canonical_overrides)
        edges = self._build_edges(raw_relations, nodes, entity_lookup)
        graph = self._build_standard_graph(nodes, edges)
        report = self._build_report(raw_entities, raw_relations, nodes, edges)
        return graph, report

    def _prepare_entities(self, raw_entities: list[dict[str, Any]], raw_relations: list[dict[str, Any]]) -> list[PreparedEntity]:
        prepared: list[PreparedEntity] = []
        seen_raw_ids: set[str] = set()
        endpoint_entities = self._infer_missing_entities_from_relations(raw_entities, raw_relations)
        for raw in [*raw_entities, *endpoint_entities]:
            entity = self._prepare_entity(raw)
            if entity is None:
                continue
            if entity.raw_id in seen_raw_ids:
                entity.raw_id = f"{entity.raw_id}_{len(seen_raw_ids)}"
            seen_raw_ids.add(entity.raw_id)
            prepared.append(entity)
        return prepared

    def _prepare_entity(self, raw: dict[str, Any]) -> PreparedEntity | None:
        original_name = str(raw.get("name", "")).strip()
        original_type = str(raw.get("type", "")).strip()
        name = normalize_entity_name(original_name)
        entity_type = normalize_entity_type(name, original_type)
        confidence = safe_float(raw.get("confidence", 0.0))

        if not name:
            self.report["rejected_entities"].append({"entity": raw, "reason": "实体名称为空。"})
            return None
        if entity_type not in ENTITY_TYPES:
            self.report["rejected_entities"].append({"entity": raw, "reason": f"实体类型不在 Schema 中：{original_type}"})
            return None
        if confidence < self.min_entity_confidence:
            self.report["rejected_entities"].append({"entity": raw, "reason": f"实体置信度低于阈值：{confidence}"})
            return None

        return PreparedEntity(
            raw_id=str(raw.get("id") or make_stable_id("raw_ent", original_type, original_name, str(len(self.report["rejected_entities"])))),
            name=name,
            type=entity_type,
            original_name=original_name,
            original_type=original_type,
            description=str(raw.get("description", "")).strip(),
            confidence=round(confidence, 4),
            source_chunk_ids=as_str_list(raw.get("source_chunk_ids", [])),
            sources=as_dict_list(raw.get("sources", [])),
            inferred_from_relation=bool(raw.get("_inferred_from_relation", False)),
        )

    def _infer_missing_entities_from_relations(self, raw_entities: list[dict[str, Any]], raw_relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        existing = {
            (entity_key(normalize_entity_type(normalize_entity_name(str(item.get("name", ""))), str(item.get("type", ""))), normalize_entity_name(str(item.get("name", "")))))
            for item in raw_entities
        }
        inferred: dict[tuple[str, str], dict[str, Any]] = {}
        for relation in raw_relations:
            for side_name, side_type in [("head", "head_type"), ("tail", "tail_type")]:
                name = normalize_entity_name(str(relation.get(side_name, "")))
                entity_type = normalize_entity_type(name, str(relation.get(side_type, "")))
                key = entity_key(entity_type, name)
                if not name or entity_type not in ENTITY_TYPES or key in existing:
                    continue
                if key not in inferred:
                    inferred[key] = {
                        "id": make_stable_id("inferred_ent", entity_type, name),
                        "name": name,
                        "type": entity_type,
                        "description": "由关系端点补充的实体。",
                        "confidence": max(self.min_entity_confidence, safe_float(relation.get("confidence", 0.0)) - 0.05),
                        "source_chunk_ids": as_str_list(relation.get("source_chunk_ids", [])),
                        "sources": as_dict_list(relation.get("sources", [])),
                        "_inferred_from_relation": True,
                    }
                    self.report["inferred_entities"].append({"name": name, "type": entity_type, "from_relation_id": relation.get("id", "")})
                else:
                    merge_unique(inferred[key]["source_chunk_ids"], as_str_list(relation.get("source_chunk_ids", [])))
                    merge_sources(inferred[key]["sources"], as_dict_list(relation.get("sources", [])))
        return list(inferred.values())

    def _merge_by_rules(self, entities: list[PreparedEntity], union_find: UnionFind) -> None:
        groups: dict[tuple[str, str], list[PreparedEntity]] = defaultdict(list)
        for item in entities:
            groups[(item.type, comparable_name(item.name))].append(item)
        for group in groups.values():
            if len(group) < 2:
                continue
            first = group[0]
            for other in group[1:]:
                union_find.union(first.raw_id, other.raw_id)
            self.report["merged_entities"].append(
                {
                    "method": "rule_exact_or_alias",
                    "canonical_name": first.name,
                    "canonical_type": first.type,
                    "members": [item.original_name for item in group],
                    "reason": "名称标准化后完全一致。",
                }
            )

    def _merge_by_equivalent_relations(self, entities: list[PreparedEntity], raw_relations: list[dict[str, Any]], union_find: UnionFind) -> None:
        lookup = {(entity_key(item.type, item.name)): item for item in entities}
        for relation in raw_relations:
            rel_type = normalize_relation_type(str(relation.get("relation", "")))
            confidence = safe_float(relation.get("confidence", 0.0))
            if rel_type != "equivalent_to" or confidence < 0.9:
                continue
            head_name = normalize_entity_name(str(relation.get("head", "")))
            tail_name = normalize_entity_name(str(relation.get("tail", "")))
            head_type = normalize_entity_type(head_name, str(relation.get("head_type", "")))
            tail_type = normalize_entity_type(tail_name, str(relation.get("tail_type", "")))
            head = lookup.get(entity_key(head_type, head_name))
            tail = lookup.get(entity_key(tail_type, tail_name))
            if not head or not tail or head.type != tail.type:
                continue
            if head.raw_id == tail.raw_id:
                continue
            union_find.union(head.raw_id, tail.raw_id)
            self.report["merged_entities"].append(
                {
                    "method": "high_confidence_equivalent_relation",
                    "canonical_name": choose_canonical_name([head, tail]),
                    "canonical_type": head.type,
                    "members": [head.original_name, tail.original_name],
                    "reason": "第二步抽取到高置信度 equivalent_to 关系。",
                }
            )

    def _merge_by_llm(
        self,
        entities: list[PreparedEntity],
        union_find: UnionFind,
        canonical_overrides: dict[str, dict[str, Any]],
    ) -> None:
        if not self.llm.enabled or self.max_llm_entity_groups <= 0:
            return
        checked = 0
        for candidate_group in build_ambiguous_entity_groups(entities):
            if checked >= self.max_llm_entity_groups:
                break
            if same_union_group(candidate_group, union_find):
                continue
            checked += 1
            try:
                decision = self.llm.judge_entity_merge(candidate_group)
            except Exception as exc:  # 大模型失败时按保守原则不合并
                self.report["warnings"].append(f"实体消歧 API 调用失败：{exc}")
                continue
            decision_record = {
                "task": "entity_merge",
                "candidates": [item.original_name for item in candidate_group],
                "decision": decision,
            }
            self.report["llm_decisions"].append(decision_record)
            if not self._accept_entity_merge_decision(decision):
                continue
            first = candidate_group[0]
            for other in candidate_group[1:]:
                union_find.union(first.raw_id, other.raw_id)
            root = union_find.find(first.raw_id)
            canonical_overrides[root] = {
                "name": normalize_entity_name(str(decision.get("canonical_name", first.name))),
                "type": normalize_entity_type(str(decision.get("canonical_name", first.name)), str(decision.get("canonical_type", first.type))),
                "reason": decision.get("reason", ""),
            }
            self.report["merged_entities"].append(
                {
                    "method": "llm_semantic_merge",
                    "canonical_name": canonical_overrides[root]["name"],
                    "canonical_type": canonical_overrides[root]["type"],
                    "members": [item.original_name for item in candidate_group],
                    "reason": decision.get("reason", ""),
                }
            )

    @staticmethod
    def _accept_entity_merge_decision(decision: dict[str, Any]) -> bool:
        if not bool(decision.get("should_merge", False)):
            return False
        if safe_float(decision.get("confidence", 0.0)) < 0.85:
            return False
        canonical_type = str(decision.get("canonical_type", "")).strip()
        return canonical_type in ENTITY_TYPES

    def _build_nodes(
        self,
        entities: list[PreparedEntity],
        union_find: UnionFind,
        canonical_overrides: dict[str, dict[str, Any]],
    ) -> tuple[list[StandardNode], dict[tuple[str, str], str]]:
        groups: dict[str, list[PreparedEntity]] = defaultdict(list)
        for item in entities:
            groups[union_find.find(item.raw_id)].append(item)

        nodes: list[StandardNode] = []
        entity_lookup: dict[tuple[str, str], str] = {}
        used_ids: set[str] = set()
        for root, group in groups.items():
            override = canonical_overrides.get(root, {})
            canonical_type = str(override.get("type") or choose_canonical_type(group))
            if canonical_type not in ENTITY_TYPES:
                canonical_type = choose_canonical_type(group)
            canonical_name = normalize_entity_name(str(override.get("name") or choose_canonical_name(group)))
            node_id = make_node_id(canonical_type, canonical_name)
            if node_id in used_ids:
                node_id = f"{node_id}_{hash_payload({'root': root})[:8]}"
            used_ids.add(node_id)

            aliases = sorted(
                {
                    alias
                    for item in group
                    for alias in [item.original_name, item.name]
                    if alias and normalize_entity_name(alias) != canonical_name
                }
            )
            descriptions = [item.description for item in group if item.description]
            sources: list[dict[str, Any]] = []
            source_chunk_ids: list[str] = []
            for item in group:
                merge_unique(source_chunk_ids, item.source_chunk_ids)
                merge_sources(sources, item.sources)
            node = StandardNode(
                id=node_id,
                name=canonical_name,
                type=canonical_type,
                aliases=aliases,
                description=max(descriptions, key=len) if descriptions else "",
                confidence=round(max(item.confidence for item in group), 4),
                source_chunk_ids=source_chunk_ids,
                sources=sources,
                original_entity_ids=[item.raw_id for item in group],
            )
            nodes.append(node)
            for item in group:
                entity_lookup[entity_key(item.type, item.name)] = node.id
                entity_lookup[entity_key(item.original_type, item.original_name)] = node.id
            entity_lookup[entity_key(node.type, node.name)] = node.id

        nodes.sort(key=lambda item: (item.type, item.name))
        return nodes, entity_lookup

    def _build_edges(
        self,
        raw_relations: list[dict[str, Any]],
        nodes: list[StandardNode],
        entity_lookup: dict[tuple[str, str], str],
    ) -> list[StandardEdge]:
        nodes_by_id = {node.id: node for node in nodes}
        edges_by_key: dict[tuple[str, str, str], StandardEdge] = {}
        llm_relation_reviews = 0

        for relation in raw_relations:
            confidence = safe_float(relation.get("confidence", 0.0))
            if confidence < self.min_relation_confidence:
                self._reject_relation(relation, f"关系置信度低于阈值：{confidence}")
                continue

            source_id = self._resolve_endpoint(relation, "head", "head_type", entity_lookup)
            target_id = self._resolve_endpoint(relation, "tail", "tail_type", entity_lookup)
            if not source_id or not target_id:
                self._reject_relation(relation, "关系头实体或尾实体无法映射到标准节点。")
                continue
            if source_id == target_id:
                self._reject_relation(relation, "关系头尾实体融合后变成同一个节点。")
                continue

            source_node = nodes_by_id[source_id]
            target_node = nodes_by_id[target_id]
            relation_type = normalize_relation_type(str(relation.get("relation", "")))
            needs_llm = relation_type not in RELATION_TYPES or not is_relation_type_compatible(relation_type, source_node.type, target_node.type)
            if self.review_key_relations and relation_type in KEY_RELATIONS_FOR_LLM_REVIEW and llm_relation_reviews < self.max_llm_relations:
                needs_llm = True

            if needs_llm and self.llm.enabled and llm_relation_reviews < self.max_llm_relations:
                llm_relation_reviews += 1
                repaired = self._review_relation_by_llm(relation, source_node, target_node)
                if repaired is None:
                    continue
                relation_type = repaired["relation_type"]
                confidence = min(1.0, max(confidence, safe_float(repaired.get("confidence", confidence))))

            if relation_type not in RELATION_TYPES:
                self._uncertain_relation(relation, f"关系类型无法规范化：{relation.get('relation', '')}")
                continue
            if not is_relation_type_compatible(relation_type, source_node.type, target_node.type):
                self._uncertain_relation(
                    relation,
                    f"关系类型与头尾实体类型不匹配：{source_node.type} - {relation_type} -> {target_node.type}",
                )
                continue

            edge_key = (source_id, relation_type, target_id)
            edge = StandardEdge(
                id=make_edge_id(source_id, relation_type, target_id),
                source=source_id,
                target=target_id,
                type=relation_type,
                neo4j_type=relation_type.upper(),
                confidence=round(confidence, 4),
                evidence=str(relation.get("evidence", "")).strip(),
                source_chunks=as_str_list(relation.get("source_chunk_ids", [])),
                sources=as_dict_list(relation.get("sources", [])),
                original_relation_ids=[str(relation.get("id", ""))],
            )
            old_edge = edges_by_key.get(edge_key)
            if old_edge is None:
                edges_by_key[edge_key] = edge
                self.report["normalized_relations"].append(
                    {
                        "relation_id": relation.get("id", ""),
                        "head": source_node.name,
                        "relation": relation_type,
                        "tail": target_node.name,
                        "method": "rule_or_schema_validated",
                    }
                )
            else:
                old_edge.confidence = round(max(old_edge.confidence, edge.confidence), 4)
                if len(edge.evidence) > len(old_edge.evidence):
                    old_edge.evidence = edge.evidence
                merge_unique(old_edge.source_chunks, edge.source_chunks)
                merge_sources(old_edge.sources, edge.sources)
                merge_unique(old_edge.original_relation_ids, edge.original_relation_ids)

        return sorted(edges_by_key.values(), key=lambda item: (item.type, item.source, item.target))

    def _resolve_endpoint(self, relation: dict[str, Any], name_key: str, type_key: str, entity_lookup: dict[tuple[str, str], str]) -> str | None:
        raw_name = str(relation.get(name_key, "")).strip()
        raw_type = str(relation.get(type_key, "")).strip()
        name = normalize_entity_name(raw_name)
        entity_type = normalize_entity_type(name, raw_type)
        return entity_lookup.get(entity_key(entity_type, name)) or entity_lookup.get(entity_key(raw_type, raw_name))

    def _review_relation_by_llm(self, relation: dict[str, Any], source_node: StandardNode, target_node: StandardNode) -> dict[str, Any] | None:
        try:
            decision = self.llm.judge_relation(relation, source_node, target_node)
        except Exception as exc:
            self.report["warnings"].append(f"关系审查 API 调用失败：{exc}")
            self._uncertain_relation(relation, "大模型审查失败，按保守原则不入库。")
            return None

        self.report["llm_decisions"].append(
            {
                "task": "relation_review",
                "relation_id": relation.get("id", ""),
                "head": source_node.name,
                "tail": target_node.name,
                "decision": decision,
            }
        )
        action = str(decision.get("action", "")).strip().lower()
        relation_type = normalize_relation_type(str(decision.get("relation_type", relation.get("relation", ""))))
        if action not in {"keep", "repair"}:
            self._uncertain_relation(relation, f"大模型判断为 {action or 'uncertain'}：{decision.get('reason', '')}")
            return None
        if safe_float(decision.get("confidence", 0.0)) < 0.75:
            self._uncertain_relation(relation, "大模型关系审查置信度低于 0.75。")
            return None
        if relation_type not in RELATION_TYPES or not is_relation_type_compatible(relation_type, source_node.type, target_node.type):
            self._uncertain_relation(relation, f"大模型给出的关系类型仍不合法：{relation_type}")
            return None
        return {"relation_type": relation_type, "confidence": safe_float(decision.get("confidence", 0.0))}

    def _reject_relation(self, relation: dict[str, Any], reason: str) -> None:
        self.report["rejected_relations"].append({"relation": compact_relation(relation), "reason": reason})

    def _uncertain_relation(self, relation: dict[str, Any], reason: str) -> None:
        self.report["uncertain_relations"].append({"relation": compact_relation(relation), "reason": reason})

    @staticmethod
    def _build_standard_graph(nodes: list[StandardNode], edges: list[StandardEdge]) -> dict[str, Any]:
        relation_schema = {
            relation: {"head_types": sorted(head_types), "tail_types": sorted(tail_types)}
            for relation, (head_types, tail_types) in sorted(RELATION_SCHEMA.items())
        }
        return {
            "schema_version": NORMALIZATION_SCHEMA_VERSION,
            "nodes": [node.__dict__ for node in nodes],
            "edges": [edge.__dict__ for edge in edges],
            "schema": {
                "node_types": sorted(ENTITY_TYPES),
                "edge_types": sorted(RELATION_TYPES),
                "relation_schema": relation_schema,
            },
            "metadata": {
                "source_schema_version": SCHEMA_VERSION,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "source": "graph_extract",
                "target": "neo4j_demo",
            },
        }

    def _build_report(
        self,
        raw_entities: list[dict[str, Any]],
        raw_relations: list[dict[str, Any]],
        nodes: list[StandardNode],
        edges: list[StandardEdge],
    ) -> dict[str, Any]:
        report = {
            "schema_version": NORMALIZATION_SCHEMA_VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "principles": {
                "entity_merge": "宁可少合并，也不要错合并。",
                "relation_keep": "宁可少保留关系，也不要把不确定关系写入标准图谱。",
                "llm_role": "规则先处理确定性情况，大模型只处理疑难实体和关键/异常关系。",
            },
            "thresholds": {
                "min_entity_confidence": self.min_entity_confidence,
                "min_relation_confidence": self.min_relation_confidence,
                "llm_entity_merge_min_confidence": 0.85,
                "llm_relation_review_min_confidence": 0.75,
            },
            "before": {
                "entity_count": len(raw_entities),
                "relation_count": len(raw_relations),
                "entity_type_distribution": distribution([str(item.get("type", "")) for item in raw_entities]),
                "relation_type_distribution": distribution([str(item.get("relation", "")) for item in raw_relations]),
            },
            "after": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "node_type_distribution": distribution([item.type for item in nodes]),
                "edge_type_distribution": distribution([item.type for item in edges]),
            },
            "api": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "api_calls": self.llm.api_calls,
                "cache_hits": self.llm.cache_hits,
            },
            **self.report,
        }
        return report


def normalize_entity_name(name: str) -> str:
    """统一实体名称的空格、括号、大小写和常见别名。"""
    value = unicodedata.normalize("NFKC", str(name or "")).strip()
    value = value.replace("（", "(").replace("）", ")")
    value = value.replace("：", ":").replace("，", ",").replace("；", ";")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*-\s*", "-", value)
    value = value.strip(" \t\r\n,，;；:：。.")
    value = re.sub(r"(?i)^java\s+", "Java", value)
    for alias, canonical in ENTITY_NAME_ALIASES.items():
        if value.lower() == str(alias).lower():
            return str(canonical)
    # 中英文混排中，语法关键字和中文词之间的空格通常不是概念差异。
    value = re.sub(r"(?i)\bfor\s+循环\b", "for循环", value)
    return value


def normalize_entity_type(name: str, entity_type: str) -> str:
    """把实体类型收敛到第二步定义的 Schema。"""
    normalized_name = normalize_entity_name(name)
    if normalized_name in FORCED_ENTITY_TYPES:
        return FORCED_ENTITY_TYPES[normalized_name]
    value = str(entity_type or "").strip()
    if value in ENTITY_TYPES:
        return value
    return ENTITY_TYPE_ALIASES.get(value, ENTITY_TYPE_ALIASES.get(value.lower(), value))


def normalize_relation_type(relation_type: str) -> str:
    """把关系表达收敛到第二步定义的关系 Schema。"""
    value = unicodedata.normalize("NFKC", str(relation_type or "")).strip()
    if value in RELATION_TYPES:
        return value
    if value in RELATION_ALIASES:
        return RELATION_ALIASES[value]
    lowered = value.lower()
    if lowered in RELATION_TYPES:
        return lowered
    return RELATION_ALIASES.get(lowered, lowered)


def comparable_name(name: str) -> str:
    """生成用于“确定性合并”的名称指纹。"""
    value = normalize_entity_name(name).lower()
    value = re.sub(r"[\s_\-·.。,:：;；()（）\[\]【】{}<>《》/\\]+", "", value)
    return value


def entity_key(entity_type: str, name: str) -> tuple[str, str]:
    return (normalize_entity_type(name, entity_type), comparable_name(name))


def choose_canonical_name(group: list[PreparedEntity]) -> str:
    """优先选择高置信度、标准化后较短的名称作为节点展示名。"""
    sorted_group = sorted(group, key=lambda item: (-item.confidence, len(item.name), item.name))
    return sorted_group[0].name


def choose_canonical_type(group: list[PreparedEntity]) -> str:
    types = Counter(item.type for item in group)
    return types.most_common(1)[0][0]


def build_ambiguous_entity_groups(entities: list[PreparedEntity]) -> list[list[PreparedEntity]]:
    """
    生成需要大模型判断的候选组。

    这里故意只找“看起来很像”的实体，不把所有实体都交给模型，避免过度合并。
    """
    by_type: dict[str, list[PreparedEntity]] = defaultdict(list)
    for item in entities:
        by_type[item.type].append(item)

    groups: list[list[PreparedEntity]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for items in by_type.values():
        for index, left in enumerate(items):
            for right in items[index + 1 :]:
                pair_key = tuple(sorted([left.raw_id, right.raw_id]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                left_key = comparable_name(left.name)
                right_key = comparable_name(right.name)
                if not left_key or not right_key or left_key == right_key:
                    continue
                ratio = SequenceMatcher(None, left_key, right_key).ratio()
                short_name_pair = min(len(left_key), len(right_key)) <= 2
                contains_relation = (left_key in right_key or right_key in left_key) and not short_name_pair
                if ratio >= 0.88 or contains_relation:
                    groups.append([left, right])
    return groups


def same_union_group(group: list[PreparedEntity], union_find: UnionFind) -> bool:
    roots = {union_find.find(item.raw_id) for item in group}
    return len(roots) == 1


def is_relation_type_compatible(relation_type: str, head_type: str, tail_type: str) -> bool:
    schema = RELATION_SCHEMA.get(relation_type)
    if schema is None:
        return False
    allowed_head_types, allowed_tail_types = schema
    return head_type in allowed_head_types and tail_type in allowed_tail_types


def relation_schema_for_prompt(head_type: str, tail_type: str) -> list[str]:
    return [
        relation
        for relation, (head_types, tail_types) in sorted(RELATION_SCHEMA.items())
        if head_type in head_types and tail_type in tail_types
    ]


def compact_relation(relation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": relation.get("id", ""),
        "head": relation.get("head", ""),
        "head_type": relation.get("head_type", ""),
        "relation": relation.get("relation", ""),
        "tail": relation.get("tail", ""),
        "tail_type": relation.get("tail_type", ""),
        "confidence": relation.get("confidence", 0.0),
        "evidence": relation.get("evidence", ""),
    }


def collect_evidence_snippets(sources: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    snippets = []
    for source in sources[:limit]:
        content = str(source.get("content", ""))
        snippets.append(
            {
                "chunk_id": source.get("chunk_id", ""),
                "source_file": source.get("source_file", ""),
                "page": source.get("page", ""),
                "content": content[:500],
            }
        )
    return snippets


def make_node_id(entity_type: str, name: str) -> str:
    readable = re.sub(r"[^\w\u4e00-\u9fff]+", "_", name, flags=re.UNICODE).strip("_")
    readable = readable or hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    if len(readable) > 36:
        readable = f"{readable[:24]}_{hashlib.md5(name.encode('utf-8')).hexdigest()[:8]}"
    return f"{entity_type}_{readable}"


def make_edge_id(source_id: str, relation_type: str, target_id: str) -> str:
    return make_stable_id("edge", source_id, relation_type, target_id)


def make_stable_id(prefix: str, *parts: str) -> str:
    raw = ":".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


def hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(number, 1.0))


def as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def merge_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def merge_sources(target: list[dict[str, Any]], values: list[dict[str, Any]]) -> None:
    seen = {(item.get("chunk_id"), item.get("source_file"), item.get("page")) for item in target}
    for value in values:
        key = (value.get("chunk_id"), value.get("source_file"), value.get("page"))
        if key not in seen:
            target.append(value)
            seen.add(key)


def distribution(values: list[str]) -> dict[str, int]:
    result = Counter(value for value in values if value)
    return dict(sorted(result.items()))


def load_json_candidates(input_dir: Path, candidates: list[str], payload_key: str) -> list[dict[str, Any]]:
    for filename in candidates:
        path = input_dir / filename
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and isinstance(payload.get(payload_key), list):
            return [item for item in payload[payload_key] if isinstance(item, dict)]
        raise ValueError(f"{path} 的 JSON 结构无法识别。")
    raise FileNotFoundError(f"在 {input_dir} 中没有找到候选文件：{', '.join(candidates)}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第三阶段：实体融合、关系消歧与标准图谱生成。")
    parser.add_argument("--input-dir", default="work/oop_kg_demo/output/graph_extract", help="第二步输出目录")
    parser.add_argument("--output-dir", default="work/oop_kg_demo/output/graph_normalized", help="第三步输出目录")
    parser.add_argument("--provider", default="qwen", choices=["qwen", "deepseek", "rule"], help="大模型提供方")
    parser.add_argument("--model", default=None, help="模型名称。默认：qwen-plus / deepseek-chat")
    parser.add_argument("--base-url", default=None, help="兼容 OpenAI Chat Completions 的接口地址")
    parser.add_argument("--no-llm", action="store_true", help="只使用规则，不调用大模型")
    parser.add_argument("--refresh-cache", action="store_true", help="忽略大模型判断缓存")
    parser.add_argument("--timeout", type=int, default=60, help="API 超时时间，单位秒")
    parser.add_argument("--retries", type=int, default=2, help="API 重试次数")
    parser.add_argument("--min-entity-confidence", type=float, default=0.55, help="实体最低置信度")
    parser.add_argument("--min-relation-confidence", type=float, default=0.60, help="关系最低置信度")
    parser.add_argument("--max-llm-entity-groups", type=int, default=30, help="最多交给大模型判断的实体候选组数量")
    parser.add_argument("--max-llm-relations", type=int, default=40, help="最多交给大模型复核的关系数量")
    parser.add_argument("--no-key-relation-review", action="store_true", help="不复核 equivalent/prerequisite 等关键关系")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    provider = "rule" if args.no_llm else args.provider

    raw_entities = load_json_candidates(
        input_dir,
        ["entities.json", "graph_entities.json", "extracted_entities.json"],
        "entities",
    )
    raw_relations = load_json_candidates(
        input_dir,
        ["relations.json", "graph_relations.json", "extracted_relations.json"],
        "relations",
    )

    cache = NormalizationCache(output_dir / "normalization_cache", refresh_cache=args.refresh_cache)
    llm = LLMJudge(
        provider=provider,
        model=args.model,
        base_url=args.base_url,
        timeout=args.timeout,
        retries=args.retries,
        cache=cache,
    )
    normalizer = GraphNormalizer(
        llm=llm,
        min_entity_confidence=args.min_entity_confidence,
        min_relation_confidence=args.min_relation_confidence,
        max_llm_entity_groups=args.max_llm_entity_groups,
        max_llm_relations=args.max_llm_relations,
        review_key_relations=not args.no_key_relation_review,
    )
    graph, report = normalizer.normalize(raw_entities, raw_relations)

    write_json(output_dir / "standard_graph.json", graph)
    write_json(output_dir / "normalization_report.json", report)

    print(f"标准节点数量：{len(graph['nodes'])}")
    print(f"标准关系数量：{len(graph['edges'])}")
    print(f"标准图谱：{output_dir / 'standard_graph.json'}")
    print(f"规范化报告：{output_dir / 'normalization_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
