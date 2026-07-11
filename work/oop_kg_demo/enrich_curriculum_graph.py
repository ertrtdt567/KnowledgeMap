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


DEFAULT_INPUT = "work/oop_kg_demo/output/programming_kg/graph_normalized/standard_graph.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/programming_kg/graph_hierarchy"

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
CURRICULUM_TYPES = {"KnowledgeDomain", "KnowledgeUnit", "KnowledgePoint"}


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

    def enrich(self, raw_graph: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        raw_nodes = [item for item in as_list(raw_graph.get("nodes")) if isinstance(item, dict)]
        raw_edges = [item for item in as_list(raw_graph.get("edges")) if isinstance(item, dict)]
        catalog_sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        catalog_aliases: dict[str, list[str]] = defaultdict(list)
        old_to_new: dict[str, str] = {}
        candidates: list[dict[str, Any]] = []

        for node in raw_nodes:
            old_id = str(node.get("id", ""))
            name = str(node.get("name", "")).strip()
            catalog_node = self.catalog.match_name(name)
            if catalog_node:
                catalog_id = str(catalog_node["id"])
                old_to_new[old_id] = f"curriculum_{catalog_id}"
                catalog_sources[catalog_id].extend(as_list(node.get("sources")))
                if name and name != catalog_node.get("name"):
                    catalog_aliases[catalog_id].append(name)
            elif str(node.get("type", "")) in CURRICULUM_TYPES:
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
                "aliases": sorted(set(catalog_aliases.get(catalog_id, []) + as_list(catalog_node.get("aliases")))),
                "description": "标准知识目录节点" if not direct else "由课程材料直接证实的标准知识节点",
                "confidence": 0.98 if direct else 0.9,
                "source_chunk_ids": unique_strings(source.get("chunk_id") for source in direct_sources),
                "sources": direct_sources,
                "original_entity_ids": [],
                "catalog_id": catalog_id,
                "coverage_status": "direct" if direct else "structural",
                "evidence_status": "direct_material" if direct else "supported_by_covered_descendant",
            }

        for node in raw_nodes:
            old_id = str(node.get("id", ""))
            new_id = old_to_new.get(old_id)
            if not new_id or new_id in nodes:
                continue
            copied = dict(node)
            copied["coverage_status"] = "direct"
            copied["evidence_status"] = "direct_material"
            nodes[new_id] = copied

        edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        dropped_auto_hierarchy = 0
        for edge in raw_edges:
            if str(edge.get("type", "")) == "part_of":
                dropped_auto_hierarchy += 1
                continue
            source = old_to_new.get(str(edge.get("source", "")))
            target = old_to_new.get(str(edge.get("target", "")))
            relation = str(edge.get("type", ""))
            if not source or not target or source not in nodes or target not in nodes or relation not in DISPLAY_NAMES:
                continue
            key = (source, relation, target)
            copied = dict(edge)
            copied["source"] = source
            copied["target"] = target
            copied["relation_name"] = DISPLAY_NAMES[relation]
            copied["neo4j_type"] = DISPLAY_NAMES[relation]
            copied["id"] = stable_id("edge", source, relation, target)
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
                "relation_name": DISPLAY_NAMES["part_of"],
                "neo4j_type": DISPLAY_NAMES["part_of"],
                "confidence": 1.0,
                "evidence": "标准知识目录 v0.2 的唯一主父节点定义",
                "source_chunks": nodes[child_node_id].get("source_chunk_ids", []),
                "sources": nodes[child_node_id].get("sources", []),
                "original_relation_ids": [],
                "hierarchy_source": "curriculum_catalog_v0_2",
            }

        edge_list = sorted(edges.values(), key=lambda item: (item["type"], item["source"], item["target"]))
        hierarchy_report = validate_hierarchy(nodes, edge_list)
        leaf_report = validate_code_example_leaves(nodes, edge_list)
        report = {
            "schema_version": "programming_kg_curriculum_enrichment_v3",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input_node_count": len(raw_nodes),
            "input_edge_count": len(raw_edges),
            "formal_node_count": len(nodes),
            "formal_edge_count": len(edge_list),
            "directly_covered_catalog_node_count": len(catalog_sources),
            "structural_catalog_node_count": len(included_catalog_ids) - len(catalog_sources),
            "dropped_auto_hierarchy_edge_count": dropped_auto_hierarchy,
            "candidate_node_count": len(candidates),
            "hierarchy_validation": hierarchy_report,
            "code_example_leaf_validation": leaf_report,
        }
        graph = {
            "schema_version": "programming_kg_standard_graph_v3",
            "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
            "edges": edge_list,
            "schema": {
                "node_types": sorted({str(node.get("type", "")) for node in nodes.values()}),
                "edge_types": sorted({str(edge.get("type", "")) for edge in edge_list}),
                "edge_display_names": {key: value for key, value in DISPLAY_NAMES.items() if any(edge["type"] == key for edge in edge_list)},
                "curriculum_catalog": self.catalog.payload.get("schema_version"),
                "hierarchy_relation": "part_of",
            },
            "metadata": {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "display_language": "zh-CN",
                "catalog_policy": "仅有课程材料证据的目录节点及其结构祖先进入正式图谱；目录外知识点进入候选报告。",
                "code_example_policy": "CodeExample 为叶子节点，只能作为关系终点。",
            },
        }
        return graph, report, {"schema_version": "programming_kg_candidate_nodes_v2", "generated_at": datetime.now().isoformat(timespec="seconds"), "candidates": candidates}


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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将抽取图谱映射为标准编程课程层级。")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="规范化后的标准图谱路径")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG, help="标准知识目录路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    graph = load_json(Path(args.input))
    if not isinstance(graph, dict):
        raise ValueError("输入标准图谱必须是对象。")
    enriched, report, candidates = CurriculumGraphEnricher(CurriculumCatalog.load(args.catalog)).enrich(graph)
    output_dir = Path(args.output_dir)
    write_json(output_dir / "standard_graph.json", enriched)
    write_json(output_dir / "curriculum_enrichment_report.json", report)
    write_json(output_dir / "candidate_nodes_report.json", candidates)
    print(f"正式节点数量：{len(enriched['nodes'])}")
    print(f"正式关系数量：{len(enriched['edges'])}")
    print(f"候选知识点数量：{report['candidate_node_count']}")
    print(f"层级校验通过：{report['hierarchy_validation']['valid']}")
    print(f"标准图谱：{output_dir / 'standard_graph.json'}")
    return 0 if report["hierarchy_validation"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

