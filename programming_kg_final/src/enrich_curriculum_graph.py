"""将抽取图谱映射到标准知识目录，并生成可验证的正式教学层级。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from curriculum_catalog import CurriculumCatalog, DEFAULT_CATALOG
from formal_schema_v5 import (
    build_frontend_compatible_graph,
    code_example_quality,
    migrate_node,
    migrate_relation_type,
    relation_types_compatible,
    scope_code_structures,
)
from formal_schema_v7 import (
    CURRICULUM_TYPES,
    DISPLAY_NAMES as V7_DISPLAY_NAMES,
    RELATION_SCHEMA as V7_RELATION_SCHEMA,
    relation_is_factually_valid,
    validate_graph_schema,
)


DEFAULT_INPUT = "work/oop_kg_demo/output/programming_kg/graph_normalized/standard_graph.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/programming_kg/graph_hierarchy"
DEFAULT_CHUNKS = "work/oop_kg_demo/output/programming_kg/clean_chunks.json"

DISPLAY_NAMES = {
    "part_of": "属于",
    "prerequisite_of": "前置依赖",
    "implemented_in": "实现于",
    "has_syntax": "具有语法",
    "expresses_concept": "表达概念",
    "has_code_structure": "具有代码结构",
    "has_code_example": "具有示例代码",
    "used_in_example": "用于示例",
    "appears_in_example": "出现于示例",
    "assesses": "考察",
    "requires_skill": "需要能力",
    "may_cause": "可能导致",
    "confused_with": "易混淆",
    "equivalent_to": "等价于",
    "differs_from": "不同于",
    "inherits_from": "继承自",
    "implements_interface": "实现接口",
}
DISPLAY_NAMES.update(V7_DISPLAY_NAMES)
ROOT_NODE_ID = "curriculum_ROOT"

# 当前正式图谱的课程材料只覆盖这三门语言。IDE、工具名和泛化词即使被上游误标为
# ProgrammingLanguage，也只能进入复核报告，不能进入正式图谱。
SUPPORTED_LANGUAGE_ALIASES = {
    "java": "Java",
    "python": "Python",
    "c++": "C++",
    "c++语言": "C++",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def stable_id(prefix: str, *parts: str) -> str:
    raw = ":".join(parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def merge_unique(target: list[Any], values: list[Any]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


class CurriculumGraphEnricher:
    def __init__(self, catalog: CurriculumCatalog) -> None:
        self.catalog = catalog
        self.display_names = dict(DISPLAY_NAMES)
        self.display_names.update(
            {
                relation_type: definition["display_name"]
                for relation_type, definition in self.catalog.semantic_relation_types.items()
            }
        )

    def enrich(
        self,
        raw_graph: dict[str, Any],
        evidence_chunks: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        raw_nodes = [item for item in as_list(raw_graph.get("nodes")) if isinstance(item, dict)]
        raw_edges = [item for item in as_list(raw_graph.get("edges")) if isinstance(item, dict)]
        catalog_source = str(self.catalog.payload.get("schema_version", "programming_curriculum_unknown"))
        excluded_code_examples: list[dict[str, Any]] = []
        excluded_non_target_languages: list[dict[str, Any]] = []
        excluded_exercises: list[dict[str, Any]] = []
        accepted_raw_nodes: list[dict[str, Any]] = []
        for node in raw_nodes:
            if str(node.get("type", "")) == "Exercise":
                # 习题由独立题库与考点映射流程处理，不能混入课程知识抽取主图。
                excluded_exercises.append(
                    {
                        "id": node.get("id", ""),
                        "name": node.get("name", ""),
                        "reason": "习题节点进入独立题库与知识点映射流程，暂不写入课程知识主图。",
                        "sources": node.get("sources", []),
                    }
                )
                continue
            if str(node.get("type", "")) == "ProgrammingLanguage":
                canonical_language = normalize_supported_language(str(node.get("name", "")))
                if not canonical_language:
                    excluded_non_target_languages.append(
                        {
                            "id": node.get("id", ""),
                            "name": node.get("name", ""),
                            "reason": "不在当前 Java/Python/C++ 正式语言范围内，或为工具/泛化词误判。",
                            "sources": node.get("sources", []),
                        }
                    )
                    continue
                node = dict(node)
                node["name"] = canonical_language
            if str(node.get("type", "")) != "CodeExample":
                accepted_raw_nodes.append(node)
                continue
            accepted, reason, score = code_example_quality(node)
            if accepted:
                copied = dict(node)
                copied["code_quality_score"] = score
                accepted_raw_nodes.append(copied)
            else:
                excluded_code_examples.append(
                    {
                        "id": node.get("id", ""),
                        "name": node.get("name", ""),
                        "reason": reason,
                        "code_quality_score": score,
                        "sources": node.get("sources", []),
                    }
                )
        raw_nodes = accepted_raw_nodes
        catalog_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # 上游模型偶尔会把 Java / Python / C++ 误标为 KnowledgeDomain 等课程类型。
        # 语言名称本身是确定的，不能因此重复落入候选清单；统一收敛到稳定语言节点，
        # 同时合并所有直接材料证据。
        language_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        language_original_entity_ids: dict[str, list[str]] = defaultdict(list)
        old_to_new: dict[str, str] = {}
        candidates: list[dict[str, Any]] = []
        semantic_candidates: list[dict[str, Any]] = []
        prerequisite_candidates: list[dict[str, Any]] = []
        extension_raw_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        represented_extension_raw_nodes: list[dict[str, Any]] = []

        # 对人工配置的精确 evidence_terms 直接检查清洗片段，补足上游没有抽出同名实体的目录节点。
        # 这里不使用宽泛 keywords，避免仅因普通词共现就错误声明材料覆盖。
        for chunk in evidence_chunks or []:
            if not isinstance(chunk, dict):
                continue
            content = str(chunk.get("normalized_content") or chunk.get("content") or "")
            lowered = content.casefold()
            if not lowered:
                continue
            for catalog_node in self.catalog.nodes:
                terms = [str(term).strip() for term in catalog_node.get("evidence_terms", []) if str(term).strip()]
                matched = next((term for term in terms if term.casefold() in lowered), None)
                if not matched:
                    continue
                catalog_sources[str(catalog_node["id"])].append(
                    {
                        "chunk_id": str(chunk.get("chunk_id", "")),
                        "source_file": chunk.get("source_file"),
                        "page": chunk.get("page"),
                        "evidence_location": chunk.get("evidence_location"),
                        "material_role": chunk.get("material_role"),
                        "content": str(chunk.get("content", "")),
                        "catalog_evidence_term": matched,
                    }
                )

        for node in raw_nodes:
            old_id = str(node.get("id", ""))
            name = str(node.get("name", "")).strip()
            # 课程树只接收上游已判定为课程概念的节点。代码标识符、语法元素等即使与
            # 课程术语同名，也不能因名称碰撞被改写为知识点。
            node_type = str(node.get("type", ""))
            canonical_language = normalize_supported_language(name)
            if canonical_language:
                language_node_id = f"ProgrammingLanguage_{canonical_language}"
                old_to_new[old_id] = language_node_id
                language_sources[canonical_language].extend(as_list(node.get("sources")))
                language_original_entity_ids[canonical_language].append(old_id)
                continue
            catalog_node = self.catalog.match_extracted_node(node) if node_type in CURRICULUM_TYPES else None
            if catalog_node:
                catalog_id = str(catalog_node["id"])
                old_to_new[old_id] = f"curriculum_{catalog_id}"
                catalog_sources[catalog_id].extend(as_list(node.get("sources")))
            elif (extension := self.catalog.match_extension_node(node)) is not None:
                # Java EE、Spring Boot 这类对象不是课程知识点。若上游把它误标成
                # KnowledgePoint/KnowledgeUnit，保留其材料证据并交给技术组件层处理。
                extension_id = str(extension["id"])
                extension_raw_sources[extension_id].extend(as_list(node.get("sources")))
                represented_extension_raw_nodes.append(
                    {
                        "id": old_id,
                        "name": name,
                        "source_type": node_type,
                        "extension_id": extension_id,
                        "extension_type": extension["type"],
                        "reason": "已由正式技术组件层表示，不再作为课程知识点候选。",
                    }
                )
            elif node_type in CURRICULUM_TYPES:
                candidates.append(
                    {
                        "name": name,
                        "type": node.get("type"),
                        "confidence": node.get("confidence", 0.0),
                        "source_chunk_ids": node.get("source_chunk_ids", []),
                        "sources": node.get("sources", []),
                        "reason": "不在标准知识目录中，不能直接进入正式教学层级。",
                    }
                )
            else:
                old_to_new[old_id] = old_id

        included_catalog_ids: set[str] = set()
        for catalog_id in catalog_sources:
            included_catalog_ids.update(self.catalog.ancestor_ids(catalog_id))

        nodes: dict[str, dict[str, Any]] = {}
        for catalog_id in sorted(included_catalog_ids):
            catalog_node = self.catalog.node(catalog_id)
            direct_sources = unique_sources(catalog_sources.get(catalog_id, []))
            direct = bool(direct_sources)
            node_id = f"curriculum_{catalog_id}"
            nodes[node_id] = {
                "id": node_id,
                "name": catalog_node["name"],
                "type": catalog_node["type"],
                # 正式别名仅来自人工维护的目录，绝不把关键词或模型抽取词回写为别名。
                "aliases": sorted(set(as_list(catalog_node.get("aliases")))),
                "description": "标准知识目录节点" if not direct else "由课程材料直接证实的标准知识节点",
                "confidence": 0.98 if direct else 0.9,
                "source_chunk_ids": unique_strings(source.get("chunk_id") for source in direct_sources),
                "sources": direct_sources,
                "original_entity_ids": [],
                "catalog_id": catalog_id,
                "coverage_status": "direct" if direct else "structural",
                "evidence_status": "direct_material" if direct else "supported_by_covered_descendant",
            }

        for language_name in sorted(language_sources):
            language_node_id = f"ProgrammingLanguage_{language_name}"
            direct_sources = unique_sources(language_sources[language_name])
            nodes[language_node_id] = {
                "id": language_node_id,
                "name": language_name,
                "type": "ProgrammingLanguage",
                "aliases": [],
                "description": "由课程材料直接证实的正式支持编程语言",
                "confidence": 0.98,
                "source_chunk_ids": unique_strings(source.get("chunk_id") for source in direct_sources),
                "sources": direct_sources,
                "original_entity_ids": unique_strings(language_original_entity_ids[language_name]),
                "coverage_status": "direct",
                "evidence_status": "direct_material",
            }

        for node in raw_nodes:
            old_id = str(node.get("id", ""))
            new_id = old_to_new.get(old_id)
            if not new_id or new_id in nodes:
                continue
            copied = dict(node)
            copied = migrate_node(copied)
            copied["coverage_status"] = "direct"
            copied["evidence_status"] = "direct_material"
            nodes[new_id] = copied

        # 能力和技术组件不属于课程树，必须从人工维护的目录配置生成。能力层是课程设计
        # 的稳定组成；平台/框架层则要求在材料中命中明确证据，避免把常识性技术名硬塞入图谱。
        extension_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for chunk in evidence_chunks or []:
            if not isinstance(chunk, dict):
                continue
            content = str(chunk.get("normalized_content") or chunk.get("content") or "")
            lowered = content.casefold()
            if not lowered:
                continue
            for extension in self.catalog.extension_nodes:
                terms = [str(term).strip() for term in extension.get("evidence_terms", []) if str(term).strip()]
                matched = next((term for term in terms if term.casefold() in lowered), None)
                if matched:
                    extension_sources[str(extension["id"])].append(
                        {
                            "chunk_id": str(chunk.get("chunk_id", "")),
                            "source_file": chunk.get("source_file"),
                            "page": chunk.get("page"),
                            "evidence_location": chunk.get("evidence_location"),
                            "material_role": chunk.get("material_role"),
                            "content": str(chunk.get("content", "")),
                            "catalog_evidence_term": matched,
                        }
                    )
        skipped_extension_nodes: list[dict[str, Any]] = []
        for extension in self.catalog.extension_nodes:
            extension_id = str(extension["id"])
            direct_sources = unique_sources([
                *extension_sources.get(extension_id, []),
                *extension_raw_sources.get(extension_id, []),
            ])
            requires_evidence = bool(extension.get("require_material_evidence", False))
            if requires_evidence and not direct_sources:
                skipped_extension_nodes.append(
                    {
                        "id": extension_id,
                        "name": extension["name"],
                        "type": extension["type"],
                        "reason": "该技术组件要求课程材料直接证据，当前未命中 evidence_terms。",
                    }
                )
                continue
            node_id = f"extension_{extension_id}"
            nodes[node_id] = {
                "id": node_id,
                "name": extension["name"],
                "type": extension["type"],
                "aliases": sorted(set(as_list(extension.get("aliases")))),
                "description": str(extension.get("description", "人工维护的课程能力或技术组件")),
                "confidence": 0.98 if not requires_evidence else 0.96,
                "source_chunk_ids": unique_strings(source.get("chunk_id") for source in direct_sources),
                "sources": direct_sources,
                "catalog_id": extension_id,
                "coverage_status": "manual" if not requires_evidence else "direct",
                "evidence_status": "manual_curriculum_model" if not requires_evidence else "direct_material",
                "catalog_managed": True,
            }

        edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        dropped_auto_hierarchy = 0
        rejected_schema_edges: list[dict[str, Any]] = []
        rejected_fact_edges: list[dict[str, Any]] = []
        rejected_self_loop_edges: list[dict[str, Any]] = []
        dropped_inverse_edges = 0
        for edge in raw_edges:
            if str(edge.get("type", "")) == "part_of":
                dropped_auto_hierarchy += 1
                continue
            source = old_to_new.get(str(edge.get("source", "")))
            target = old_to_new.get(str(edge.get("target", "")))
            if not source or not target or source not in nodes or target not in nodes:
                continue
            if source == target:
                rejected_self_loop_edges.append(
                    {
                        "edge": edge,
                        "reason": "课程树对齐后关系两端归并为同一节点，禁止写入正式图谱自环。",
                    }
                )
                continue
            mapped_edge = dict(edge)
            mapped_edge["source"] = source
            mapped_edge["target"] = target
            relation = migrate_relation_type(mapped_edge, nodes)
            if relation is None:
                dropped_inverse_edges += 1
                continue
            if relation in self.catalog.semantic_relation_types:
                # 模型可提出语义关联，但必须人工审核后写入目录配置，不能直接进入正式图谱。
                semantic_candidates.append(
                    {
                        "source": source,
                        "source_name": nodes[source].get("name", ""),
                        "target": target,
                        "target_name": nodes[target].get("name", ""),
                        "type": relation,
                        "relation_name": self.display_names[relation],
                        "confidence": edge.get("confidence", 0.0),
                        "evidence": edge.get("evidence", ""),
                        "source_chunk_ids": edge.get("source_chunk_ids", []),
                        "sources": edge.get("sources", []),
                        "reason": "模型抽取的语义关系，待人工审核后再写入标准目录。",
                    }
                )
                continue
            if relation == "prerequisite_of":
                # 学习先后关系会直接影响教学路径，模型只能提出候选，正式边必须写入
                # 版本化课程目录并通过无环校验后再发布。
                prerequisite_candidates.append(
                    {
                        "source": source,
                        "source_name": nodes[source].get("name", ""),
                        "target": target,
                        "target_name": nodes[target].get("name", ""),
                        "type": relation,
                        "relation_name": self.display_names[relation],
                        "confidence": edge.get("confidence", 0.0),
                        "evidence": edge.get("evidence", ""),
                        "source_chunk_ids": edge.get("source_chunk_ids", []),
                        "sources": edge.get("sources", []),
                        "reason": "模型抽取的先修关系，待人工审核并写入标准目录。",
                    }
                )
                continue
            if relation not in self.display_names:
                continue
            source_type = str(nodes[source].get("type", ""))
            target_type = str(nodes[target].get("type", ""))
            if not relation_types_compatible(
                relation,
                source_type,
                target_type,
                set(self.catalog.semantic_relation_types),
            ):
                rejected_schema_edges.append(
                    {
                        "edge": edge,
                        "migrated_relation": relation,
                        "source_type": source_type,
                        "target_type": target_type,
                        "reason": "关系头尾类型不符合正式 v5 Schema。",
                    }
                )
                continue
            key = (source, relation, target)
            copied = dict(edge)
            copied["source"] = source
            copied["target"] = target
            copied["type"] = relation
            copied["relation_name"] = self.display_names[relation]
            copied["neo4j_type"] = self.display_names[relation]
            copied["id"] = stable_id("edge", source, relation, target)
            fact_valid, fact_reason = relation_is_factually_valid(copied, nodes)
            if not fact_valid:
                rejected_fact_edges.append({"edge": copied, "reason": fact_reason})
                continue
            if key not in edges or float(copied.get("confidence", 0.0)) > float(edges[key].get("confidence", 0.0)):
                edges[key] = copied

        for catalog_id in sorted(included_catalog_ids):
            if catalog_id == "ROOT":
                continue
            parent_id = str(self.catalog.node(catalog_id).get("parent_id", ""))
            child_node_id = f"curriculum_{catalog_id}"
            parent_node_id = f"curriculum_{parent_id}"
            if child_node_id not in nodes or parent_node_id not in nodes:
                continue
            key = (child_node_id, "part_of", parent_node_id)
            edges[key] = {
                "id": stable_id("edge", child_node_id, "part_of", parent_node_id),
                "source": child_node_id,
                "target": parent_node_id,
                "type": "part_of",
                "relation_name": self.display_names["part_of"],
                "neo4j_type": self.display_names["part_of"],
                "confidence": 1.0,
                "evidence": f"{catalog_source} 的唯一主父节点定义",
                "source_chunks": nodes[child_node_id].get("source_chunk_ids", []),
                "sources": nodes[child_node_id].get("sources", []),
                "original_relation_ids": [],
                "hierarchy_source": catalog_source,
            }

        language_node_by_name = {
            str(node.get("name", "")): node_id
            for node_id, node in nodes.items()
            if node.get("type") == "ProgrammingLanguage"
        }
        skipped_configured_language_relations: list[dict[str, str]] = []
        for catalog_id in sorted(included_catalog_ids):
            source = f"curriculum_{catalog_id}"
            for language_name in as_list(self.catalog.node(catalog_id).get("supported_languages")):
                target = language_node_by_name.get(str(language_name), "")
                if source not in nodes or target not in nodes:
                    skipped_configured_language_relations.append(
                        {
                            "source_id": catalog_id,
                            "target_language": str(language_name),
                            "reason": "课程节点或目标语言节点尚未进入正式图谱。",
                        }
                    )
                    continue
                relation_type = "supported_in_language"
                edges[(source, relation_type, target)] = {
                    "id": stable_id("edge", source, relation_type, target),
                    "source": source,
                    "target": target,
                    "type": relation_type,
                    "relation_name": self.display_names[relation_type],
                    "neo4j_type": self.display_names[relation_type],
                    "confidence": 1.0,
                    "evidence": "人工维护的课程语言范围定义",
                    "source_chunks": nodes[source].get("source_chunk_ids", []),
                    "sources": nodes[source].get("sources", []),
                    "original_relation_ids": [],
                    "curation_source": catalog_source,
                }

        skipped_configured_semantics: list[dict[str, str]] = []
        for relation in self.catalog.approved_semantic_relations():
            source = f"curriculum_{relation['source_id']}"
            target = f"curriculum_{relation['target_id']}"
            relation_type = relation["type"]
            if source not in nodes or target not in nodes:
                skipped_configured_semantics.append(
                    {
                        **relation,
                        "reason": "关系端点尚未获得课程材料覆盖，暂不写入正式图谱。",
                    }
                )
                continue
            key = (source, relation_type, target)
            edges[key] = {
                "id": stable_id("edge", source, relation_type, target),
                "source": source,
                "target": target,
                "type": relation_type,
                "relation_name": self.display_names[relation_type],
                "neo4j_type": self.display_names[relation_type],
                "confidence": 1.0,
                "evidence": "人工维护的标准知识目录语义层定义",
                "source_chunks": [],
                "sources": [],
                "original_relation_ids": [],
                "semantic_source": catalog_source,
            }

        skipped_prerequisites: list[dict[str, str]] = []
        for relation in self.catalog.approved_prerequisite_relations():
            source = f"curriculum_{relation['source_id']}"
            target = f"curriculum_{relation['target_id']}"
            if source not in nodes or target not in nodes:
                skipped_prerequisites.append(
                    {**relation, "reason": "至少一个课程端点尚未获得材料覆盖，暂不写入正式图谱。"}
                )
                continue
            relation_type = relation["type"]
            edges[(source, relation_type, target)] = {
                "id": stable_id("edge", source, relation_type, target),
                "source": source,
                "target": target,
                "type": relation_type,
                "relation_name": self.display_names[relation_type],
                "neo4j_type": self.display_names[relation_type],
                "confidence": 1.0,
                "evidence": "人工维护的课程先修依赖定义",
                "source_chunks": [],
                "sources": [],
                "original_relation_ids": [],
                "curation_source": catalog_source,
            }

        skipped_ability_relations: list[dict[str, str]] = []
        for relation in self.catalog.approved_ability_relations():
            source = f"curriculum_{relation['source_id']}"
            target = f"extension_{relation['target_id']}"
            if source not in nodes or target not in nodes:
                skipped_ability_relations.append(
                    {**relation, "reason": "课程节点或能力节点尚未进入正式图谱。"}
                )
                continue
            relation_type = relation["type"]
            edges[(source, relation_type, target)] = {
                "id": stable_id("edge", source, relation_type, target),
                "source": source,
                "target": target,
                "type": relation_type,
                "relation_name": self.display_names[relation_type],
                "neo4j_type": self.display_names[relation_type],
                "confidence": 1.0,
                "evidence": "人工维护的课程能力培养模型",
                "source_chunks": [],
                "sources": [],
                "original_relation_ids": [],
                "curation_source": catalog_source,
            }

        skipped_technology_relations: list[dict[str, str]] = []
        for relation in self.catalog.approved_technology_relations():
            source = f"extension_{relation['source_id']}"
            if relation.get("target_language"):
                target = language_node_by_name.get(str(relation["target_language"]), "")
            else:
                target_id = str(relation.get("target_id", ""))
                target = f"extension_{target_id}" if target_id in self.catalog.extension_by_id else f"curriculum_{target_id}"
            if source not in nodes or target not in nodes:
                skipped_technology_relations.append(
                    {**relation, "reason": "技术节点、语言节点或课程节点尚未进入正式图谱。"}
                )
                continue
            relation_type = relation["type"]
            edges[(source, relation_type, target)] = {
                "id": stable_id("edge", source, relation_type, target),
                "source": source,
                "target": target,
                "type": relation_type,
                "relation_name": self.display_names[relation_type],
                "neo4j_type": self.display_names[relation_type],
                "confidence": 1.0,
                "evidence": "人工维护并受材料证据约束的技术组件关系",
                "source_chunks": nodes[source].get("source_chunk_ids", []),
                "sources": nodes[source].get("sources", []),
                "original_relation_ids": [],
                "curation_source": catalog_source,
            }

        nodes, scoped_edge_list, rejected_code_structure_edges = scope_code_structures(nodes, list(edges.values()))
        # 代码示例必须至少被一个知识点、语法元素或局部代码结构指向；孤立示例不进入正式图谱。
        incoming_ids = {str(edge.get("target", "")) for edge in scoped_edge_list}
        orphan_code_examples = [
            node
            for node_id, node in nodes.items()
            if node.get("type") == "CodeExample" and node_id not in incoming_ids
        ]
        orphan_ids = {str(node.get("id", "")) for node in orphan_code_examples}
        if orphan_ids:
            nodes = {node_id: node for node_id, node in nodes.items() if node_id not in orphan_ids}
            scoped_edge_list = [
                edge
                for edge in scoped_edge_list
                if str(edge.get("source", "")) not in orphan_ids and str(edge.get("target", "")) not in orphan_ids
            ]
        # 正式节点必须通过任意关系路径接入课程根节点。未接入的示例小图、孤立语法和
        # 上游误判实体只进入复核报告，避免在 Neo4j 中形成外围孤岛。
        apply_language_scopes(nodes, scoped_edge_list)
        nodes, scoped_edge_list, disconnected_nodes = retain_root_connected_component(nodes, scoped_edge_list)
        edge_list = sorted(scoped_edge_list, key=lambda item: (item["type"], item["source"], item["target"]))
        hierarchy_report = validate_hierarchy(nodes, edge_list)
        semantic_report = validate_semantic_layer(edge_list, set(self.catalog.semantic_relation_types), catalog_source)
        leaf_report = validate_code_example_leaves(nodes, edge_list)
        schema_report = validate_graph_schema(nodes, edge_list, set(self.catalog.semantic_relation_types))
        report = {
            "schema_version": "programming_kg_curriculum_enrichment_v7",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input_node_count": len(raw_nodes),
            "input_edge_count": len(raw_edges),
            "formal_node_count": len(nodes),
            "formal_edge_count": len(edge_list),
            "directly_covered_catalog_node_count": len(catalog_sources),
            "structural_catalog_node_count": len(included_catalog_ids) - len(catalog_sources),
            "dropped_auto_hierarchy_edge_count": dropped_auto_hierarchy,
            "candidate_node_count": len(candidates),
            "semantic_relation_candidate_count": len(semantic_candidates),
            "prerequisite_relation_candidate_count": len(prerequisite_candidates),
            "configured_semantic_relation_count": len(self.catalog.approved_semantic_relations()),
            "formal_semantic_relation_count": sum(1 for edge in edge_list if edge.get("type") in self.catalog.semantic_relation_types),
            "skipped_configured_semantic_relation_count": len(skipped_configured_semantics),
            "configured_prerequisite_relation_count": len(self.catalog.approved_prerequisite_relations()),
            "formal_prerequisite_relation_count": sum(1 for edge in edge_list if edge.get("type") == "prerequisite_of"),
            "skipped_prerequisite_relation_count": len(skipped_prerequisites),
            "formal_ability_relation_count": sum(1 for edge in edge_list if edge.get("type") == "develops_ability"),
            "formal_technology_node_count": sum(
                1 for node in nodes.values() if node.get("type") in {"TechnologyPlatform", "LibraryFramework"}
            ),
            "skipped_extension_node_count": len(skipped_extension_nodes),
            "represented_extension_raw_node_count": len(represented_extension_raw_nodes),
            "skipped_configured_language_relation_count": len(skipped_configured_language_relations),
            "hierarchy_validation": hierarchy_report,
            "semantic_relation_validation": semantic_report,
            "code_example_leaf_validation": leaf_report,
            "formal_schema_validation": schema_report,
            "excluded_code_example_count": len(excluded_code_examples),
            "excluded_non_target_language_count": len(excluded_non_target_languages),
            "excluded_exercise_count": len(excluded_exercises),
            "orphan_code_example_count": len(orphan_code_examples),
            "disconnected_formal_node_count": len(disconnected_nodes),
            "rejected_schema_edge_count": len(rejected_schema_edges),
            "rejected_fact_edge_count": len(rejected_fact_edges),
            "rejected_self_loop_edge_count": len(rejected_self_loop_edges),
            "dropped_inverse_edge_count": dropped_inverse_edges,
            "rejected_code_structure_edge_count": len(rejected_code_structure_edges),
        }
        graph = {
            "schema_version": "programming_kg_standard_graph_v7",
            "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
            "edges": edge_list,
            "schema": {
                "node_types": sorted({str(node.get("type", "")) for node in nodes.values()}),
                "edge_types": sorted({str(edge.get("type", "")) for edge in edge_list}),
                "edge_display_names": {key: value for key, value in self.display_names.items() if any(edge["type"] == key for edge in edge_list)},
                "curriculum_catalog": self.catalog.payload.get("schema_version"),
                "hierarchy_relation": "part_of",
                "semantic_relation_types": self.catalog.semantic_relation_types,
                "question_mapping_policy": self.catalog.question_mapping_policy,
                "relation_schema": {
                    relation: {
                        "source_types": sorted(source_types),
                        "target_types": sorted(target_types),
                    }
                    for relation, (source_types, target_types) in V7_RELATION_SCHEMA.items()
                    if any(edge["type"] == relation for edge in edge_list)
                },
            },
            "metadata": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "display_language": "zh-CN",
                "catalog_policy": "仅有课程材料证据的目录节点及其结构祖先进入正式图谱；目录外知识点进入候选报告。",
                "semantic_policy": "part_of 是唯一层级关系；目录人工确认的语义关系进入正式图谱，模型提出的语义关系仅进入候选报告。",
                "prerequisite_policy": "prerequisite_of 为人工维护、无环的学习先后依赖，不改变唯一主父层级。",
                "ability_policy": "Ability 是人工维护且版本化的课程培养目标；不从模型抽取结果自动生成。",
                "technology_policy": "TechnologyPlatform 与 LibraryFramework 仅在课程材料出现明确证据时进入正式图谱。",
                "language_scope_policy": "language_scope 仅记录显式语言关系或由课程树子节点归纳的范围；空数组表示未限定。",
                "code_example_policy": "CodeExample 为叶子节点，只能作为关系终点。",
                "connectivity_policy": "任何正式节点必须通过关系路径连接到编程领域课程根节点；未接入节点进入复核报告。",
                "compatibility_export": "standard_graph_frontend_compatible.json",
            },
        }
        return graph, report, {
            "schema_version": "programming_kg_candidate_review_v5",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "candidates": candidates,
            "semantic_relation_candidates": semantic_candidates,
            "prerequisite_relation_candidates": prerequisite_candidates,
            "skipped_configured_semantic_relations": skipped_configured_semantics,
            "skipped_configured_language_relations": skipped_configured_language_relations,
            "skipped_prerequisite_relations": skipped_prerequisites,
            "skipped_ability_relations": skipped_ability_relations,
            "skipped_technology_relations": skipped_technology_relations,
            "skipped_extension_nodes": skipped_extension_nodes,
            "represented_extension_raw_nodes": represented_extension_raw_nodes,
            "excluded_code_examples": excluded_code_examples,
            "excluded_non_target_languages": excluded_non_target_languages,
            "excluded_exercises": excluded_exercises,
            "orphan_code_examples": orphan_code_examples,
            "disconnected_nodes": disconnected_nodes,
            "rejected_schema_edges": rejected_schema_edges,
            "rejected_fact_edges": rejected_fact_edges,
            "rejected_self_loop_edges": rejected_self_loop_edges,
            "rejected_code_structure_edges": rejected_code_structure_edges,
        }


def normalize_supported_language(name: str) -> str | None:
    """将允许入库的语言名称收敛为 Java、Python、C++ 三个正式节点。"""
    key = "".join(str(name or "").strip().split()).casefold()
    return SUPPORTED_LANGUAGE_ALIASES.get(key)


def retain_root_connected_component(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """只保留能无向连通到课程根节点的正式节点，避免产生外围孤岛。"""
    if ROOT_NODE_ID not in nodes:
        raise ValueError(f"正式图谱缺少课程根节点：{ROOT_NODE_ID}")

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source in nodes and target in nodes:
            adjacency[source].add(target)
            adjacency[target].add(source)

    connected: set[str] = {ROOT_NODE_ID}
    stack = [ROOT_NODE_ID]
    while stack:
        current = stack.pop()
        for neighbor in adjacency[current]:
            if neighbor not in connected:
                connected.add(neighbor)
                stack.append(neighbor)

    disconnected_ids = set(nodes) - connected
    disconnected_nodes = [
        {
            "id": node_id,
            "name": nodes[node_id].get("name", ""),
            "type": nodes[node_id].get("type", ""),
            "sources": nodes[node_id].get("sources", []),
            "reason": "无法通过关系路径接入课程根节点，暂不进入正式图谱。",
        }
        for node_id in sorted(disconnected_ids)
    ]
    retained_nodes = {node_id: node for node_id, node in nodes.items() if node_id in connected}
    retained_edges = [
        edge
        for edge in edges
        if str(edge.get("source", "")) in retained_nodes and str(edge.get("target", "")) in retained_nodes
    ]
    return retained_nodes, retained_edges, disconnected_nodes


def apply_language_scopes(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """为节点补充可解释的语言范围，不把“未限定”误写成“支持所有语言”。"""
    scopes: dict[str, set[str]] = defaultdict(set)
    direct_scope_nodes: set[str] = set()
    language_relations = {"supported_in_language", "belongs_to_language", "written_in", "supports_language"}
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if edge.get("type") not in language_relations:
            continue
        language = nodes.get(target, {})
        if language.get("type") != "ProgrammingLanguage":
            continue
        language_name = str(language.get("name", "")).strip()
        if language_name:
            scopes[source].add(language_name)
            direct_scope_nodes.add(source)

    # 层级边的方向是“子 -> 父”。将子节点明确的语言范围汇总到课程单元和课程领域，
    # 让前端能正确展示“本单元覆盖哪些语言”，但不会反向把范围强加给每个子知识点。
    changed = True
    while changed:
        changed = False
        for edge in edges:
            if edge.get("type") != "part_of":
                continue
            child = str(edge.get("source", ""))
            parent = str(edge.get("target", ""))
            previous_count = len(scopes[parent])
            scopes[parent].update(scopes[child])
            changed = changed or len(scopes[parent]) != previous_count

    for node_id, node in nodes.items():
        node["language_scope"] = sorted(scopes.get(node_id, set()))
        if node_id in direct_scope_nodes:
            node["language_scope_status"] = "explicit"
        elif node["language_scope"]:
            node["language_scope_status"] = "inferred_from_descendants"
        else:
            node["language_scope_status"] = "unspecified"


def unique_sources(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        key = (value.get("chunk_id"), value.get("source_file"), value.get("page"))
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


def unique_strings(values: Any) -> list[str]:
    return sorted({str(value) for value in values if str(value)})


def validate_hierarchy(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    parent_by_child: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.get("type") == "part_of":
            parent_by_child[str(edge["source"])].append(str(edge["target"]))
    duplicate_parent_nodes = {child: parents for child, parents in parent_by_child.items() if len(parents) != 1}
    cycle_nodes: list[str] = []
    for node_id in parent_by_child:
        visited: set[str] = set()
        current = node_id
        while current in parent_by_child:
            if current in visited:
                cycle_nodes.append(current)
                break
            visited.add(current)
            current = parent_by_child[current][0]
    direct_without_evidence = [node_id for node_id, node in nodes.items() if node.get("coverage_status") == "direct" and not node.get("sources")]
    return {
        "valid": not duplicate_parent_nodes and not cycle_nodes and not direct_without_evidence,
        "hierarchy_edge_count": sum(1 for edge in edges if edge.get("type") == "part_of"),
        "nodes_with_invalid_parent_count": len(duplicate_parent_nodes),
        "cycle_count": len(set(cycle_nodes)),
        "direct_nodes_without_evidence_count": len(direct_without_evidence),
    }


def validate_code_example_leaves(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """验证代码示例只作为终点，保证它在知识树中处于叶子位置。"""
    code_example_ids = {node_id for node_id, node in nodes.items() if node.get("type") == "CodeExample"}
    outgoing_edges = [edge for edge in edges if str(edge.get("source", "")) in code_example_ids]
    return {
        "valid": not outgoing_edges,
        "code_example_count": len(code_example_ids),
        "outgoing_edge_count": len(outgoing_edges),
        "outgoing_edge_ids": [str(edge.get("id", "")) for edge in outgoing_edges[:20]],
    }


def validate_semantic_layer(
    edges: list[dict[str, Any]],
    semantic_types: set[str],
    catalog_source: str,
) -> dict[str, Any]:
    """确保正式语义层只由人工维护的目录配置产生。"""
    semantic_edges = [edge for edge in edges if str(edge.get("type", "")) in semantic_types]
    unapproved_edges = [
        edge
        for edge in semantic_edges
        if str(edge.get("semantic_source", "")) != catalog_source
    ]
    return {
        "valid": not unapproved_edges,
        "formal_semantic_relation_count": len(semantic_edges),
        "unapproved_semantic_relation_count": len(unapproved_edges),
        "unapproved_semantic_relation_ids": [str(edge.get("id", "")) for edge in unapproved_edges[:20]],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将抽取图谱映射为标准编程课程层级。")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="规范化后的标准图谱路径")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG, help="标准知识目录路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")
    parser.add_argument("--chunks", default=DEFAULT_CHUNKS, help="清洗片段路径，用于人工证据词覆盖检查")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    graph = load_json(Path(args.input))
    if not isinstance(graph, dict):
        raise ValueError("输入标准图谱必须是对象。")
    chunks_path = Path(args.chunks)
    chunks_payload = load_json(chunks_path) if chunks_path.exists() else []
    chunks = [item for item in chunks_payload if isinstance(item, dict)] if isinstance(chunks_payload, list) else []
    enriched, report, candidates = CurriculumGraphEnricher(CurriculumCatalog.load(args.catalog)).enrich(graph, chunks)
    output_dir = Path(args.output_dir)
    write_json(output_dir / "standard_graph.json", enriched)
    write_json(output_dir / "standard_graph_frontend_compatible.json", build_frontend_compatible_graph(enriched))
    write_json(output_dir / "curriculum_enrichment_report.json", report)
    write_json(output_dir / "candidate_nodes_report.json", candidates)
    print(f"正式节点数量：{len(enriched['nodes'])}")
    print(f"正式关系数量：{len(enriched['edges'])}")
    print(f"候选知识点数量：{report['candidate_node_count']}")
    print(f"层级校验通过：{report['hierarchy_validation']['valid']}")
    print(f"标准图谱：{output_dir / 'standard_graph.json'}")
    all_valid = (
        report["hierarchy_validation"]["valid"]
        and report["semantic_relation_validation"]["valid"]
        and report["code_example_leaf_validation"]["valid"]
        and report["formal_schema_validation"]["valid"]
    )
    return 0 if all_valid else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
