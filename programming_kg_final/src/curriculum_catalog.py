"""编程领域标准知识目录的读取、匹配与层级校验工具。"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any


DEFAULT_CATALOG = "work/oop_kg_demo/data/programming_curriculum_v0_8_algorithm_formal.json"


class CurriculumCatalog:
    """标准目录是正式教学层级的唯一来源，不由模型自由生成。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        nodes = payload.get("nodes", [])
        if not isinstance(nodes, list):
            raise ValueError("标准知识目录的 nodes 必须是数组。")
        self.payload = payload
        self.nodes = [item for item in nodes if isinstance(item, dict)]
        self.by_id = {str(item.get("id", "")): item for item in self.nodes}
        if len(self.by_id) != len(self.nodes) or "ROOT" not in self.by_id:
            raise ValueError("标准知识目录缺少唯一节点 ID，或缺少 ROOT 节点。")
        self._validate_tree()
        self.ability_nodes = self._load_extension_nodes("ability_nodes", {"Ability"})
        self.technology_nodes = self._load_extension_nodes(
            "technology_nodes", {"TechnologyPlatform", "LibraryFramework"}
        )
        self.extension_nodes = [*self.ability_nodes, *self.technology_nodes]
        self.extension_by_id = {str(item["id"]): item for item in self.extension_nodes}
        if len(self.extension_by_id) != len(self.extension_nodes):
            raise ValueError("ability_nodes 与 technology_nodes 存在重复节点 ID。")
        self.extension_name_index = self._build_extension_index("name")
        self.extension_alias_index = self._build_extension_index("aliases")
        self._validate_identity_terms()
        # 名称/显式别名用于实体对齐；关键词只用于文本召回，绝不能把知识点误当成上层节点别名。
        self.name_index = self._build_index("name")
        self.alias_index = self._build_index("aliases")
        # alignment_terms 只用于把抽取词对齐到目录，不会作为别名展示给前端。
        # 它允许同一个简称指向多个候选，再结合来源文本消歧。
        self.alignment_index = self._build_index("alignment_terms")
        self.term_index = self._build_term_index()
        self.semantic_relation_types = self._load_semantic_relation_types()
        self.semantic_relations = self._load_semantic_relations()
        self.prerequisite_relations = self._load_prerequisite_relations()
        self.ability_relations = self._load_extension_relations("ability_relations", {"develops_ability"})
        self.technology_relations = self._load_technology_relations()
        self.question_mapping_policy = self._load_question_mapping_policy()

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CATALOG) -> "CurriculumCatalog":
        catalog_path = Path(path)
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("标准知识目录顶层必须是对象。")
        return cls(payload)

    def node(self, node_id: str) -> dict[str, Any]:
        return self.by_id[node_id]

    def ancestor_ids(self, node_id: str) -> list[str]:
        result: list[str] = []
        current = node_id
        while current:
            result.append(current)
            current = str(self.by_id[current].get("parent_id", ""))
        return result

    def match_name(self, value: str, context: str = "") -> dict[str, Any] | None:
        normalized = normalize_text(value)
        if not normalized:
            return None
        # 先匹配唯一正式名称，再匹配唯一显式别名；歧义简称不自动决定归属。
        node_id = self._unique_node_id(self.name_index.get(normalized, set()))
        if node_id is None:
            node_id = self._unique_node_id(self.alias_index.get(normalized, set()))
        if node_id is None:
            node_id = self._resolve_alignment_candidates(
                self.alignment_index.get(normalized, set()),
                context,
            )
        return self.by_id.get(node_id) if node_id else None

    def match_extracted_node(self, node: dict[str, Any]) -> dict[str, Any] | None:
        """结合节点来源文本对齐抽取实体，避免“重载”等简称被错误硬合并。"""
        context_parts = [str(node.get("description", ""))]
        for source in node.get("sources", []):
            if isinstance(source, dict):
                context_parts.append(str(source.get("content", "")))
                context_parts.append(str(source.get("source_file", "")))
        return self.match_name(str(node.get("name", "")), "\n".join(context_parts))

    def match_text(self, text: str, limit: int = 12) -> list[dict[str, Any]]:
        normalized_text = normalize_text(text)
        matches: list[tuple[int, dict[str, Any], str]] = []
        seen: set[str] = set()
        for term, node_ids in self.term_index.items():
            if len(term) < 2 or term not in normalized_text:
                continue
            for node_id in node_ids:
                if node_id in seen:
                    continue
                seen.add(node_id)
                node = self.by_id[node_id]
                matches.append((len(term), node, term))
        matches.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
        return [item[1] for item in matches[:limit]]

    def domain_candidates(self, text: str) -> list[str]:
        result: list[str] = []
        for node in self.match_text(text, limit=30):
            path = list(reversed(self.ancestor_ids(str(node["id"]))))
            if len(path) >= 2:
                domain_name = str(self.by_id[path[1]].get("name", ""))
                if domain_name and domain_name not in result:
                    result.append(domain_name)
        return result

    def approved_semantic_relations(self) -> list[dict[str, str]]:
        """返回目录人工确认的语义关系；这些关系才可进入正式图谱。"""
        return list(self.semantic_relations)

    def approved_prerequisite_relations(self) -> list[dict[str, str]]:
        """返回人工维护的先修依赖；方向为“先修知识 -> 后续知识”。"""
        return list(self.prerequisite_relations)

    def approved_ability_relations(self) -> list[dict[str, str]]:
        """返回知识点到能力的培养关系。"""
        return list(self.ability_relations)

    def approved_technology_relations(self) -> list[dict[str, str]]:
        """返回平台、框架和课程知识之间的人工维护关系。"""
        return list(self.technology_relations)

    def match_extension_node(self, node: dict[str, Any]) -> dict[str, Any] | None:
        """识别被上游误标为课程知识点的已配置技术组件。"""
        normalized = normalize_text(str(node.get("name", "")))
        if not normalized:
            return None
        node_id = self._unique_node_id(self.extension_name_index.get(normalized, set()))
        if node_id is None:
            node_id = self._unique_node_id(self.extension_alias_index.get(normalized, set()))
        return self.extension_by_id.get(node_id) if node_id else None

    def _build_index(self, field: str) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for node in self.nodes:
            node_id = str(node["id"])
            values = [str(node.get("name", ""))] if field == "name" else [str(item) for item in node.get(field, []) if str(item).strip()]
            for value in values:
                key = normalize_text(value)
                if key:
                    index.setdefault(key, set()).add(node_id)
        return index

    def _build_extension_index(self, field: str) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for node in self.extension_nodes:
            node_id = str(node["id"])
            values = [str(node.get("name", ""))] if field == "name" else [
                str(item) for item in node.get(field, []) if str(item).strip()
            ]
            for value in values:
                key = normalize_text(value)
                if key:
                    index.setdefault(key, set()).add(node_id)
        return index

    def _build_term_index(self) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for node in self.nodes:
            node_id = str(node["id"])
            values = [str(node.get("name", ""))]
            values.extend(str(item) for item in node.get("aliases", []) if str(item).strip())
            values.extend(str(item) for item in node.get("alignment_terms", []) if str(item).strip())
            values.extend(str(item) for item in node.get("keywords", []) if str(item).strip())
            for value in values:
                key = normalize_text(value)
                if key:
                    index.setdefault(key, set()).add(node_id)
        return index

    @staticmethod
    def _unique_node_id(node_ids: set[str]) -> str | None:
        return next(iter(node_ids)) if len(node_ids) == 1 else None

    def _resolve_alignment_candidates(self, node_ids: set[str], context: str) -> str | None:
        if len(node_ids) <= 1:
            return self._unique_node_id(node_ids)
        normalized_context = normalize_text(context)
        ranked: list[tuple[int, str]] = []
        for node_id in node_ids:
            node = self.by_id[node_id]
            score = 0
            context_keywords = node.get("alignment_context_keywords", node.get("keywords", []))
            for keyword in context_keywords:
                term = normalize_text(str(keyword))
                if len(term) >= 2 and term in normalized_context:
                    score += len(term)
            ranked.append((score, node_id))
        ranked.sort(reverse=True)
        if not ranked or ranked[0][0] == 0:
            return None
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            return None
        return ranked[0][1]

    def _load_semantic_relation_types(self) -> dict[str, dict[str, str]]:
        raw_types = self.payload.get("semantic_relation_types", {})
        if not isinstance(raw_types, dict):
            raise ValueError("semantic_relation_types 必须是对象。")
        result: dict[str, dict[str, str]] = {}
        for relation_type, definition in raw_types.items():
            if not isinstance(definition, dict) or not str(definition.get("display_name", "")).strip():
                raise ValueError(f"语义关系类型 {relation_type} 缺少 display_name。")
            result[str(relation_type)] = {
                "display_name": str(definition["display_name"]),
                "description": str(definition.get("description", "")),
            }
        return result

    def _load_semantic_relations(self) -> list[dict[str, str]]:
        raw_relations = self.payload.get("semantic_relations", [])
        if not isinstance(raw_relations, list):
            raise ValueError("semantic_relations 必须是数组。")
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in raw_relations:
            if not isinstance(item, dict):
                raise ValueError("semantic_relations 中存在非对象项。")
            source_id = str(item.get("source_id", ""))
            target_id = str(item.get("target_id", ""))
            relation_type = str(item.get("type", ""))
            if source_id not in self.by_id or target_id not in self.by_id:
                raise ValueError(f"语义关系引用了不存在的节点：{source_id} -> {target_id}")
            if relation_type not in self.semantic_relation_types:
                raise ValueError(f"语义关系使用了未定义类型：{relation_type}")
            key = (source_id, relation_type, target_id)
            if key not in seen:
                seen.add(key)
                result.append({"source_id": source_id, "target_id": target_id, "type": relation_type})
        return result

    def _load_extension_nodes(self, field: str, allowed_types: set[str]) -> list[dict[str, Any]]:
        """读取不属于课程树、但受目录版本控制的正式节点。"""
        raw_nodes = self.payload.get(field, [])
        if not isinstance(raw_nodes, list):
            raise ValueError(f"{field} 必须是数组。")
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw_nodes:
            if not isinstance(item, dict):
                raise ValueError(f"{field} 中存在非对象项。")
            node_id = str(item.get("id", "")).strip()
            node_type = str(item.get("type", "")).strip()
            name = str(item.get("name", "")).strip()
            if not node_id or not name or node_type not in allowed_types:
                raise ValueError(f"{field} 中节点必须具有合法 id、name 和 type。")
            if node_id in self.by_id or node_id in seen:
                raise ValueError(f"{field} 中节点 ID 与课程树或同类节点重复：{node_id}")
            seen.add(node_id)
            copied = dict(item)
            copied["id"] = node_id
            copied["name"] = name
            copied["type"] = node_type
            copied["aliases"] = [str(alias) for alias in item.get("aliases", []) if str(alias).strip()]
            copied["evidence_terms"] = [
                str(term) for term in item.get("evidence_terms", []) if str(term).strip()
            ]
            result.append(copied)
        return result

    def _load_prerequisite_relations(self) -> list[dict[str, str]]:
        raw_relations = self.payload.get("prerequisite_relations", [])
        if not isinstance(raw_relations, list):
            raise ValueError("prerequisite_relations 必须是数组。")
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_relations:
            if not isinstance(item, dict):
                raise ValueError("prerequisite_relations 中存在非对象项。")
            source_id = str(item.get("source_id", ""))
            target_id = str(item.get("target_id", ""))
            if source_id not in self.by_id or target_id not in self.by_id or source_id == target_id:
                raise ValueError(f"先修依赖引用了不存在或相同的课程节点：{source_id} -> {target_id}")
            teaching_types = {
                "KnowledgeUnit", "KnowledgePoint", "Algorithm", "OperationRule", "ComplexityMetric",
                "AlgorithmStrategy", "AlgorithmProblem",
            }
            if self.by_id[source_id].get("type") not in teaching_types:
                raise ValueError(f"先修依赖源节点不是可教学单元：{source_id}")
            if self.by_id[target_id].get("type") not in teaching_types:
                raise ValueError(f"先修依赖目标节点不是可教学单元：{target_id}")
            key = (source_id, target_id)
            if key not in seen:
                seen.add(key)
                result.append({"source_id": source_id, "target_id": target_id, "type": "prerequisite_of"})
        self._validate_prerequisite_dag(result)
        return result

    def _validate_prerequisite_dag(self, relations: list[dict[str, str]]) -> None:
        adjacency: dict[str, set[str]] = {}
        for relation in relations:
            adjacency.setdefault(relation["source_id"], set()).add(relation["target_id"])
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError(f"先修依赖存在环：{node_id}")
            if node_id in visited:
                return
            visiting.add(node_id)
            for target_id in adjacency.get(node_id, set()):
                visit(target_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in adjacency:
            visit(node_id)

    def _load_extension_relations(self, field: str, allowed_types: set[str]) -> list[dict[str, str]]:
        raw_relations = self.payload.get(field, [])
        if not isinstance(raw_relations, list):
            raise ValueError(f"{field} 必须是数组。")
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in raw_relations:
            if not isinstance(item, dict):
                raise ValueError(f"{field} 中存在非对象项。")
            source_id = str(item.get("source_id", ""))
            target_id = str(item.get("target_id", ""))
            relation_type = str(item.get("type", ""))
            if source_id not in self.by_id or target_id not in self.extension_by_id:
                raise ValueError(f"{field} 引用了不存在的节点：{source_id} -> {target_id}")
            if relation_type not in allowed_types:
                raise ValueError(f"{field} 使用了不允许的关系类型：{relation_type}")
            key = (source_id, relation_type, target_id)
            if key not in seen:
                seen.add(key)
                result.append({"source_id": source_id, "target_id": target_id, "type": relation_type})
        return result

    def _load_technology_relations(self) -> list[dict[str, str]]:
        raw_relations = self.payload.get("technology_relations", [])
        if not isinstance(raw_relations, list):
            raise ValueError("technology_relations 必须是数组。")
        allowed_types = {"supports_language", "built_on_platform", "supports_practice"}
        result: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in raw_relations:
            if not isinstance(item, dict):
                raise ValueError("technology_relations 中存在非对象项。")
            source_id = str(item.get("source_id", ""))
            target_id = str(item.get("target_id", ""))
            target_language = str(item.get("target_language", ""))
            relation_type = str(item.get("type", ""))
            if source_id not in self.extension_by_id or relation_type not in allowed_types:
                raise ValueError(f"technology_relations 配置无效：{source_id} / {relation_type}")
            if bool(target_id) == bool(target_language):
                raise ValueError("technology_relations 每条关系只能指定 target_id 或 target_language。")
            if target_id and target_id not in self.by_id and target_id not in self.extension_by_id:
                raise ValueError(f"technology_relations 引用了不存在节点：{target_id}")
            if target_language and target_language not in {"Java", "Python", "C++"}:
                raise ValueError(f"technology_relations 使用了未支持语言：{target_language}")
            target_key = target_id or f"language:{target_language}"
            key = (source_id, relation_type, target_key)
            if key not in seen:
                seen.add(key)
                copied = {"source_id": source_id, "type": relation_type}
                if target_id:
                    copied["target_id"] = target_id
                else:
                    copied["target_language"] = target_language
                result.append(copied)
        return result

    def _load_question_mapping_policy(self) -> dict[str, Any]:
        policy = self.payload.get("question_mapping_policy", {})
        if not isinstance(policy, dict):
            raise ValueError("question_mapping_policy 必须是对象。")
        return dict(policy)

    def _validate_tree(self) -> None:
        for node_id, node in self.by_id.items():
            parent_id = str(node.get("parent_id", ""))
            if node_id == "ROOT":
                if parent_id:
                    raise ValueError("ROOT 节点不能有父节点。")
                continue
            if parent_id not in self.by_id:
                raise ValueError(f"节点 {node_id} 的父节点不存在：{parent_id}")
            visited: set[str] = set()
            current = node_id
            while current:
                if current in visited:
                    raise ValueError(f"标准知识目录存在层级环：{node_id}")
                visited.add(current)
                current = str(self.by_id[current].get("parent_id", ""))

    def _validate_identity_terms(self) -> None:
        """阻止同一个词同时承担不同节点的正式名称或别名。"""
        names: dict[str, str] = {}
        aliases: dict[str, str] = {}
        for node in [*self.nodes, *self.extension_nodes]:
            node_id = str(node["id"])
            name_key = normalize_text(str(node.get("name", "")))
            if not name_key:
                raise ValueError(f"节点 {node_id} 缺少正式名称。")
            previous_name = names.get(name_key)
            if previous_name and previous_name != node_id:
                raise ValueError(f"正式名称重复：{node_id} 与 {previous_name}")
            names[name_key] = node_id
            for alias in node.get("aliases", []):
                alias_key = normalize_text(str(alias))
                if not alias_key:
                    continue
                previous_alias = aliases.get(alias_key)
                if previous_alias and previous_alias != node_id:
                    raise ValueError(f"别名重复：{alias} 同时属于 {previous_alias} 和 {node_id}")
                canonical_owner = names.get(alias_key)
                if canonical_owner and canonical_owner != node_id:
                    raise ValueError(f"别名不能占用其他节点正式名称：{alias} -> {canonical_owner}")
                aliases[alias_key] = node_id
        for alias_key, owner in aliases.items():
            canonical_owner = names.get(alias_key)
            if canonical_owner and canonical_owner != owner:
                raise ValueError(f"别名不能占用其他节点正式名称：{alias_key} -> {canonical_owner}")


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = re.sub(r"[\s_\-·.。,:：;；()（）\[\]【】{}<>《》/\\]+", "", text)
    return text
