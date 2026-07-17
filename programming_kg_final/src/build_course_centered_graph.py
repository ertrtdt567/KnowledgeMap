"""Build a course-centered graph from existing extraction evidence.

This module never calls an LLM. It reuses extracted entities, relations and
page-level evidence for Java, Python, C++ and Data Structures. UML is handled
later by the same builder after its own extraction output exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from curriculum_catalog import CurriculumCatalog
from enrich_curriculum_graph import CurriculumGraphEnricher
from formal_schema_v8_course_centered import (
    CORE_CONCEPT_TYPE,
    DISPLAY_NAMES,
    LOCAL_CORE_CANDIDATE_TYPES,
    validate_graph_schema,
)
from normalize_graph import GraphNormalizer, LLMJudge, NormalizationCache


ROOT_ID = "programming_domain_root"
CATALOG_ROOT_ID = "curriculum_ROOT"
DEFAULT_CATALOG = "work/oop_kg_demo/data/programming_curriculum_v0_13_candidate_finalized.json"


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    """Atomically publish JSON so a frontend never sees a half-written graph."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def sources_of(item: dict[str, Any]) -> list[dict[str, Any]]:
    sources = item.get("sources", [])
    return [source for source in sources if isinstance(source, dict)] if isinstance(sources, list) else []


def source_files(item: dict[str, Any]) -> list[str]:
    return [str(source.get("source_file", "")) for source in sources_of(item) if source.get("source_file")]


def dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source in sources:
        key = (str(source.get("chunk_id", "")), str(source.get("source_file", "")), str(source.get("page", "")))
        if key not in seen:
            seen.add(key)
            result.append(source)
    return result


def clone_with_sources(item: dict[str, Any], predicate: Callable[[str], bool]) -> dict[str, Any] | None:
    selected = [source for source in sources_of(item) if predicate(str(source.get("source_file", "")))]
    if not selected:
        return None
    copied = dict(item)
    copied["sources"] = dedupe_sources(selected)
    copied["source_chunk_ids"] = sorted({str(source.get("chunk_id", "")) for source in selected if source.get("chunk_id")})
    return copied


def java_source(filename: str) -> bool:
    return "java" in filename.casefold()


def python_source(filename: str) -> bool:
    return "python" in filename.casefold()


def cpp_source(filename: str) -> bool:
    # OODC is the existing C++ course material naming convention.
    return filename.casefold().startswith("oodc")


COURSES: list[dict[str, Any]] = [
    {"id": "course_java", "name": "Java", "predicate": java_source, "source_set": "main"},
    {"id": "course_python", "name": "Python", "predicate": python_source, "source_set": "main"},
    {"id": "course_cpp", "name": "C++", "predicate": cpp_source, "source_set": "main"},
    {"id": "course_data_structures", "name": "数据结构", "predicate": lambda _: True, "source_set": "data_structures"},
]


class CourseCenteredBuilder:
    def __init__(self, catalog_path: Path, output_dir: Path) -> None:
        self.catalog_path = catalog_path
        self.output_dir = output_dir
        self.catalog = CurriculumCatalog.load(catalog_path)
        self.enricher = CurriculumGraphEnricher(self.catalog)

    def build(
        self,
        main_extract_dir: Path,
        main_chunks_path: Path,
        data_structures_extract_dir: Path,
        data_structures_chunks_path: Path,
        uml_extract_dir: Path | None = None,
        uml_chunks_path: Path | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        main_entities, main_relations = self._load_extract(main_extract_dir)
        ds_entities, ds_relations = self._load_extract(data_structures_extract_dir)
        main_chunks = self._load_list(main_chunks_path)
        ds_chunks = self._load_list(data_structures_chunks_path)
        courses = list(COURSES)
        uml_entities: list[dict[str, Any]] = []
        uml_relations: list[dict[str, Any]] = []
        uml_chunks: list[dict[str, Any]] = []
        # UML is optional while its material-specific catalog candidates are
        # under review. Once extracted, it enters through the same local-tree
        # pipeline, never through cross-course fusion.
        if uml_extract_dir and uml_chunks_path and uml_extract_dir.exists() and uml_chunks_path.exists():
            uml_entities, uml_relations = self._load_extract(uml_extract_dir)
            uml_chunks = self._load_list(uml_chunks_path)
            courses.append({"id": "course_uml", "name": "UML 面向对象分析与设计", "predicate": lambda _: True, "source_set": "uml"})

        nodes: dict[str, dict[str, Any]] = {
            ROOT_ID: {
                "id": ROOT_ID,
                "name": "编程领域",
                "type": "KnowledgeDomain",
                "aliases": ["程序设计"],
                "description": "面向课程组织的编程领域知识图谱根节点",
                "confidence": 1.0,
                "source_chunk_ids": [],
                "sources": [],
                "coverage_status": "manual",
                "evidence_status": "curriculum_design",
            }
        }
        edges: list[dict[str, Any]] = []
        reports: dict[str, Any] = {"courses": {}, "cross_course_core_candidates": []}

        for course in courses:
            if course["source_set"] == "main":
                raw_entities, raw_relations, chunks = main_entities, main_relations, main_chunks
            elif course["source_set"] == "data_structures":
                raw_entities, raw_relations, chunks = ds_entities, ds_relations, ds_chunks
            else:
                raw_entities, raw_relations, chunks = uml_entities, uml_relations, uml_chunks
            course_graph, course_report = self._build_one_course(
                course, raw_entities, raw_relations, chunks
            )
            reports["courses"][course["id"]] = course_report
            for node in course_graph["nodes"]:
                nodes[str(node["id"])] = node
            edges.extend(course_graph["edges"])

        core_nodes, core_edges, core_candidates = self._build_core_layer(nodes)
        for node in core_nodes:
            nodes[str(node["id"])] = node
        edges.extend(core_edges)
        reports["cross_course_core_candidates"] = core_candidates

        edge_list = self._dedupe_edges(edges)
        semantic_types = set(self.catalog.semantic_relation_types)
        validation = validate_graph_schema(nodes, edge_list, semantic_types)
        audit = self._audit(nodes, edge_list, validation)
        graph = {
            "schema_version": "programming_kg_course_centered_v12",
            "schema": {
                # 将构建时实际采用的关系白名单写入交付图谱，保证独立审计、
                # Neo4j 导入和前端解释都使用同一份规则，而不是依赖本机目录文件。
                "semantic_relation_types": sorted(semantic_types),
                "relationship_display_names": {
                    relation: DISPLAY_NAMES.get(relation, relation)
                    for relation in sorted({str(edge.get("type", "")) for edge in edge_list})
                },
            },
            "nodes": sorted(nodes.values(), key=lambda item: str(item["id"])),
            "edges": edge_list,
            "metadata": {
                "organization": "course_centered",
                "root_node_id": ROOT_ID,
                "course_ids": [course["id"] for course in courses],
                "core_mapping_gate": "same catalog node, direct evidence in at least two courses",
                "excluded_course": "算法设计与分析",
            },
        }
        reports["schema_validation"] = validation
        reports["audit"] = audit
        return graph, reports

    def _load_extract(self, directory: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        entities_path = directory / "entities.json"
        relations_path = directory / "relations.json"
        if entities_path.exists() and relations_path.exists():
            return self._load_list(entities_path), self._load_list(relations_path)

        standard_graph_path = directory / "standard_graph.json"
        if not standard_graph_path.exists():
            raise FileNotFoundError(
                f"{directory} 既不包含 entities.json/relations.json，也不包含 standard_graph.json"
            )

        graph = read_json(standard_graph_path)
        if not isinstance(graph, dict):
            raise ValueError(f"{standard_graph_path} 顶层必须是 JSON 对象")
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError(f"{standard_graph_path} 的 nodes 和 edges 必须是数组")

        entities = [dict(node) for node in nodes if isinstance(node, dict)]
        node_by_id = {str(node.get("id", "")): node for node in entities if node.get("id")}
        relations: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = node_by_id.get(str(edge.get("source", "")))
            target = node_by_id.get(str(edge.get("target", "")))
            if not source or not target:
                continue
            relations.append(
                {
                    "id": edge.get("id"),
                    "head": source.get("name"),
                    "head_type": source.get("type"),
                    "relation": edge.get("type"),
                    "tail": target.get("name"),
                    "tail_type": target.get("type"),
                    "confidence": edge.get("confidence", 0.8),
                    "evidence": edge.get("evidence", ""),
                    "source_chunk_ids": edge.get("source_chunks", []),
                    "sources": edge.get("sources", []),
                    "original_relation_ids": edge.get("original_relation_ids", []),
                }
            )
        return entities, relations

    @staticmethod
    def _load_list(path: Path) -> list[dict[str, Any]]:
        payload = read_json(path)
        if not isinstance(payload, list):
            raise ValueError(f"{path} 必须是 JSON 数组")
        return [item for item in payload if isinstance(item, dict)]

    def _build_one_course(
        self,
        course: dict[str, Any],
        raw_entities: list[dict[str, Any]],
        raw_relations: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
        predicate = course["predicate"]
        filtered_entities = [item for item in (clone_with_sources(entity, predicate) for entity in raw_entities) if item]
        filtered_relations = [item for item in (clone_with_sources(relation, predicate) for relation in raw_relations) if item]
        filtered_chunks = [chunk for chunk in chunks if predicate(str(chunk.get("source_file", "")))]

        # Re-normalize only within one course. Rule mode makes this reproducible
        # and guarantees that no cross-course entity fusion occurs.
        normalizer = GraphNormalizer(
            llm=LLMJudge("rule", None, None, 1, 0, NormalizationCache(self.output_dir / "cache" / course["id"], False)),
            min_entity_confidence=0.55,
            min_relation_confidence=0.60,
            max_llm_entity_groups=0,
            max_llm_relations=0,
            review_key_relations=False,
        )
        normalized, normalization_report = normalizer.normalize(filtered_entities, filtered_relations)
        enriched, enrichment_report, hierarchy_report = self.enricher.enrich(normalized, filtered_chunks)
        localized = self._localize_course_graph(course, enriched)
        report = {
            "course_name": course["name"],
            "raw_entity_count": len(filtered_entities),
            "raw_relation_count": len(filtered_relations),
            "chunk_count": len(filtered_chunks),
            "local_node_count": len(localized["nodes"]),
            "local_edge_count": len(localized["edges"]),
            "normalization": normalization_report,
            "enrichment": enrichment_report,
            "hierarchy": hierarchy_report,
        }
        return localized, report

    def _localize_course_graph(self, course: dict[str, Any], graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        course_id = str(course["id"])
        identifier_map: dict[str, str] = {CATALOG_ROOT_ID: course_id}
        course_node = {
            "id": course_id,
            "name": course["name"],
            "type": "Course",
            "aliases": [],
            "description": f"{course['name']}课程的知识树根节点",
            "confidence": 1.0,
            "course_id": course_id,
            "source_chunk_ids": [],
            "sources": [],
            "coverage_status": "manual",
            "evidence_status": "curriculum_design",
        }
        localized_nodes: list[dict[str, Any]] = [course_node]
        for node in graph.get("nodes", []):
            old_id = str(node.get("id", ""))
            if old_id == CATALOG_ROOT_ID:
                continue
            new_id = f"{course_id}__{old_id}"
            identifier_map[old_id] = new_id
            copied = dict(node)
            copied["id"] = new_id
            copied["course_id"] = course_id
            copied["local_id"] = old_id
            localized_nodes.append(copied)

        localized_edges = [
            {
                "id": stable_id("edge", course_id, "part_of", ROOT_ID),
                "source": course_id,
                "target": ROOT_ID,
                "type": "part_of",
                "relation_name": DISPLAY_NAMES["part_of"],
                "neo4j_type": DISPLAY_NAMES["part_of"],
                "confidence": 1.0,
                "evidence": "课程组织结构定义",
                "sources": [],
            }
        ]
        for edge in graph.get("edges", []):
            source = identifier_map.get(str(edge.get("source", "")))
            target = identifier_map.get(str(edge.get("target", "")))
            if not source or not target or source == target:
                continue
            copied = dict(edge)
            copied["source"] = source
            copied["target"] = target
            copied["id"] = stable_id("edge", source, str(copied.get("type", "")), target)
            copied["course_id"] = course_id
            localized_edges.append(copied)
        return {"nodes": localized_nodes, "edges": localized_edges}

    def _build_core_layer(
        self, nodes: dict[str, dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in nodes.values():
            catalog_id = str(node.get("catalog_id", ""))
            if (
                catalog_id
                and str(node.get("type", "")) in LOCAL_CORE_CANDIDATE_TYPES
                and str(node.get("coverage_status", "")) == "direct"
                and node.get("course_id")
            ):
                grouped[catalog_id].append(node)

        core_nodes: list[dict[str, Any]] = []
        core_edges: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        for catalog_id, local_nodes in sorted(grouped.items()):
            by_course = {str(node["course_id"]): node for node in local_nodes}
            entry = {
                "catalog_id": catalog_id,
                "name": str(local_nodes[0].get("name", "")),
                "type": str(local_nodes[0].get("type", "")),
                "course_ids": sorted(by_course),
                "direct_evidence_count": len(by_course),
            }
            if len(by_course) < 2:
                entry["decision"] = "candidate_only"
                entry["reason"] = "仅一门课程具有直接材料证据，不满足跨课程核心概念门槛。"
                candidates.append(entry)
                continue

            core_id = f"core_{catalog_id}"
            core_nodes.append(
                {
                    "id": core_id,
                    "name": entry["name"],
                    "type": CORE_CONCEPT_TYPE,
                    "aliases": [],
                    "description": "至少两门课程具有直接材料证据的共享编程核心概念",
                    "confidence": 0.98,
                    "catalog_id": catalog_id,
                    "supporting_course_ids": entry["course_ids"],
                    "evidence_status": "cross_course_direct_material",
                    "coverage_status": "direct",
                    "source_chunk_ids": sorted({chunk_id for node in by_course.values() for chunk_id in node.get("source_chunk_ids", [])}),
                    "sources": dedupe_sources([source for node in by_course.values() for source in sources_of(node)]),
                }
            )
            entry["decision"] = "auto_approved"
            entry["reason"] = "同一标准目录节点在至少两门课程中被直接材料证实。"
            candidates.append(entry)
            for course_id, local_node in sorted(by_course.items()):
                core_edges.append(
                    {
                        "id": stable_id("edge", str(local_node["id"]), "maps_to_core", core_id),
                        "source": local_node["id"],
                        "target": core_id,
                        "type": "maps_to_core",
                        "relation_name": DISPLAY_NAMES["maps_to_core"],
                        "neo4j_type": DISPLAY_NAMES["maps_to_core"],
                        "confidence": 0.98,
                        "evidence": "同一标准目录节点在多门课程中具有直接材料证据。",
                        "course_id": course_id,
                        "sources": sources_of(local_node),
                    }
                )
        return core_nodes, core_edges, candidates

    @staticmethod
    def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[tuple[str, str, str], dict[str, Any]] = {}
        for edge in edges:
            key = (str(edge.get("source", "")), str(edge.get("type", "")), str(edge.get("target", "")))
            if not all(key) or key[0] == key[2]:
                continue
            existing = unique.get(key)
            if existing is None or float(edge.get("confidence", 0.0)) > float(existing.get("confidence", 0.0)):
                unique[key] = edge
        return sorted(unique.values(), key=lambda item: (str(item["source"]), str(item["type"]), str(item["target"])))

    @staticmethod
    def _audit(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], validation: dict[str, Any]) -> dict[str, Any]:
        degree = Counter()
        for edge in edges:
            degree[str(edge["source"])] += 1
            degree[str(edge["target"])] += 1
        isolated = [node_id for node_id in nodes if degree[node_id] == 0]
        local_nodes = [node for node in nodes.values() if node.get("course_id") and node.get("type") != "Course"]
        bad_course_tree_edges = [
            edge for edge in edges
            if edge.get("type") == "part_of"
            and nodes[str(edge["source"])].get("type") != "Course"
            and nodes[str(edge["source"])].get("course_id") != nodes[str(edge["target"])].get("course_id")
        ]
        return {
            "passed": bool(validation.get("valid")) and not isolated and not bad_course_tree_edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "course_local_node_count": len(local_nodes),
            "core_concept_count": sum(1 for node in nodes.values() if node.get("type") == CORE_CONCEPT_TYPE),
            "isolated_node_count": len(isolated),
            "isolated_nodes": isolated[:100],
            "cross_course_part_of_violation_count": len(bad_course_tree_edges),
            "schema_violation_count": validation.get("violation_count", 0),
        }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建按课程分层的编程领域知识图谱（不调用 API）。")
    parser.add_argument("--main-extract-dir", default="work/oop_kg_demo/output/programming_kg/graph_extract")
    parser.add_argument("--main-chunks", default="work/oop_kg_demo/output/programming_kg/clean_chunks.json")
    parser.add_argument("--data-structures-extract-dir", default="work/oop_kg_demo/output/data_structures_incremental/graph_extract_qwen_max")
    parser.add_argument("--data-structures-chunks", default="work/oop_kg_demo/output/data_structures_incremental/clean_chunks.json")
    parser.add_argument("--uml-extract-dir", default="", help="UML 抽取或规范化目录；缺省时仅构建已有四门课。")
    parser.add_argument("--uml-chunks", default="", help="UML 清洗片段 JSON；与 --uml-extract-dir 同时提供才纳入 UML。")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", default="work/oop_kg_demo/output/programming_kg/course_centered_v12_candidate_finalized")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir)
    builder = CourseCenteredBuilder(Path(args.catalog), output_dir)
    graph, report = builder.build(
        Path(args.main_extract_dir),
        Path(args.main_chunks),
        Path(args.data_structures_extract_dir),
        Path(args.data_structures_chunks),
        Path(args.uml_extract_dir) if args.uml_extract_dir else None,
        Path(args.uml_chunks) if args.uml_chunks else None,
    )
    write_json(output_dir / "standard_graph.json", graph)
    write_json(output_dir / "course_centered_report.json", report)
    print(f"正式节点数量：{len(graph['nodes'])}")
    print(f"正式关系数量：{len(graph['edges'])}")
    print(f"正式图谱：{output_dir / 'standard_graph.json'}")
    print(f"构建报告：{output_dir / 'course_centered_report.json'}")
    print(f"质量校验通过：{report['audit']['passed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
