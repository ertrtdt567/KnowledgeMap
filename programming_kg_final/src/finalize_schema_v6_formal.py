"""Promote approved third-review results into a formal Schema v6 graph.

This script is intentionally deterministic: it reads a versioned curriculum
catalog and a third-review report, writes a new graph directory, and never
edits the previous candidate graph in place.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from audit_formal_graph import check_prerequisite_dag, check_root_connectivity
from curriculum_catalog import CurriculumCatalog
from formal_schema_v6 import DISPLAY_NAMES, SPECIALIZED_TEACHING_TYPES, validate_graph_schema


ROOT = "curriculum_ROOT"
OVERVIEW_NODE_IDS = {
    "curriculum_D4_2": "跨主题概览",
    "curriculum_D6_5": "组合专题概览；已拆分为 DAG 概念和拓扑排序算法",
    "curriculum_D7_1": "组合专题概览；已拆分为查找表与平均查找长度指标",
    "curriculum_D8_1": "排序概览与性能比较",
    "curriculum_G1_1": "多操作课程主题",
}
OBSOLETE_SEMANTIC_EDGES = {
    # After v0.7 adds the explicit “散列表 -> 散列查找” relation, the old
    # domain-level relation becomes redundant and over-general.
    ("curriculum_D7", "has_algorithm", "curriculum_D7_6"),
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def unique_sources(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        key = (value.get("chunk_id"), value.get("source_file"), value.get("page"))
        if key not in seen:
            seen.add(key)
            result.append(copy.deepcopy(value))
    return result


def catalog_node_payload(catalog_node: dict[str, Any], sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sources = unique_sources(sources or [])
    direct = bool(sources)
    return {
        "id": f"curriculum_{catalog_node['id']}",
        "name": catalog_node["name"],
        "type": catalog_node["type"],
        "aliases": list(catalog_node.get("aliases", [])),
        "description": f"标准课程知识节点：{catalog_node['name']}",
        "confidence": 0.98 if direct else 1.0,
        "source_chunk_ids": sorted({str(item.get("chunk_id", "")) for item in sources if item.get("chunk_id")}),
        "sources": sources,
        "original_entity_ids": [],
        "coverage_status": "direct" if direct else "structural",
        "evidence_status": "direct_material" if direct else "catalog_structure",
        "catalog_id": catalog_node["id"],
        "catalog_managed": True,
        "language_scope": [],
        "language_scope_status": "unspecified",
    }


def edge_payload(
    source: str,
    target: str,
    relation_type: str,
    sources: list[dict[str, Any]],
    evidence: str,
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "id": stable_id("schema_v6_formal", source, relation_type, target),
        "source": source,
        "target": target,
        "type": relation_type,
        "relation_name": DISPLAY_NAMES.get(relation_type, relation_type),
        "neo4j_type": DISPLAY_NAMES.get(relation_type, relation_type),
        "confidence": confidence,
        "evidence": evidence,
        "source_chunks": sorted({str(item.get("chunk_id", "")) for item in sources if item.get("chunk_id")}),
        "sources": unique_sources(sources),
    }


def record_sources(record: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [item for item in record.get("sources", []) if isinstance(item, dict)]
    if sources:
        return unique_sources(sources)
    return [
        {"chunk_id": chunk_id, "source_file": "", "page": None, "evidence_location": "第三轮复核"}
        for chunk_id in record.get("source_chunk_ids", [])
    ]


def add_edge(edges: dict[tuple[str, str, str], dict[str, Any]], edge: dict[str, Any]) -> None:
    edges.setdefault((edge["source"], edge["type"], edge["target"]), edge)


def catalog_id_for_record(catalog: CurriculumCatalog, record: dict[str, Any]) -> str:
    node = record.get("proposed_node", {})
    candidates = [str(node.get("name", "")), str(record.get("name", ""))]
    for name in candidates:
        matched = catalog.match_name(name)
        if matched:
            return str(matched["id"])
    raise ValueError(f"第三轮纳入项未在 v0.7 课程目录中登记：{record.get('name')}")


def apply_catalog_aliases(nodes: dict[str, dict[str, Any]], catalog: CurriculumCatalog) -> None:
    for catalog_id, catalog_node in catalog.by_id.items():
        node_id = f"curriculum_{catalog_id}"
        if node_id not in nodes:
            continue
        node = nodes[node_id]
        node["name"] = catalog_node["name"]
        node["type"] = catalog_node["type"]
        node["aliases"] = list(catalog_node.get("aliases", []))
        node["catalog_id"] = catalog_id
        node["catalog_managed"] = True


def build_formal_graph(
    base: dict[str, Any],
    catalog: CurriculumCatalog,
    review: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = {str(node["id"]): copy.deepcopy(node) for node in base.get("nodes", [])}
    edges = {
        (str(edge["source"]), str(edge["type"]), str(edge["target"])): copy.deepcopy(edge)
        for edge in base.get("edges", [])
    }
    for key in OBSOLETE_SEMANTIC_EDGES:
        edges.pop(key, None)
    apply_catalog_aliases(nodes, catalog)
    direct_sources: dict[str, list[dict[str, Any]]] = {}
    promoted: list[dict[str, Any]] = []

    for record in review["records"]:
        if record.get("decision") != "add_node":
            continue
        catalog_id = catalog_id_for_record(catalog, record)
        direct_sources[catalog_id] = record_sources(record)
        promoted.append({
            "catalog_id": catalog_id,
            "name": catalog.node(catalog_id)["name"],
            "type": catalog.node(catalog_id)["type"],
            "review_name": record["name"],
            "evidence_chunk_count": record["evidence_chunk_count"],
        })

    # The two approved composite-topic splits bring in one additional concept
    # each.  Evidence is copied from the reviewed candidate record/overview.
    review_by_name = {str(item.get("name", "")): item for item in review["records"]}
    direct_sources["D6_5_1"] = record_sources(review_by_name.get("有向无环图", {})) or list(nodes["curriculum_D6_5"].get("sources", []))
    direct_sources["D6_5_2"] = list(nodes["curriculum_D6_5"].get("sources", []))
    direct_sources["D7_1_1"] = record_sources(review_by_name.get("查找表", {})) or list(nodes["curriculum_D7_1"].get("sources", []))
    promoted.extend(
        [
            {"catalog_id": "D6_5_1", "name": "有向无环图", "type": "KnowledgePoint", "review_name": "组合节点拆分", "evidence_chunk_count": len(direct_sources["D6_5_1"])},
            {"catalog_id": "D6_5_2", "name": "拓扑排序算法", "type": "Algorithm", "review_name": "组合节点拆分", "evidence_chunk_count": len(direct_sources["D6_5_2"])},
            {"catalog_id": "D7_1_1", "name": "查找表", "type": "KnowledgePoint", "review_name": "组合节点拆分", "evidence_chunk_count": len(direct_sources["D7_1_1"])},
        ]
    )

    # Every direct node and every structural ancestor is materialized.  This
    # guarantees that no newly approved leaf becomes a disconnected island.
    required_catalog_ids: set[str] = set()
    for catalog_id in direct_sources:
        required_catalog_ids.update(catalog.ancestor_ids(catalog_id))
    for catalog_id in sorted(required_catalog_ids):
        node_id = f"curriculum_{catalog_id}"
        if node_id not in nodes:
            nodes[node_id] = catalog_node_payload(catalog.node(catalog_id), direct_sources.get(catalog_id))
        elif catalog_id in direct_sources:
            node = nodes[node_id]
            sources = unique_sources([*node.get("sources", []), *direct_sources[catalog_id]])
            node["sources"] = sources
            node["source_chunk_ids"] = sorted({str(item.get("chunk_id", "")) for item in sources if item.get("chunk_id")})
            node["coverage_status"] = "direct"
            node["evidence_status"] = "direct_material"

    # Ensure the unique catalog hierarchy for newly materialized nodes.
    # Catalog ownership is authoritative.  When v0.7 refines a previous
    # parent (for example, 散列查找 moves under 散列表), replace only that
    # child's obsolete part_of edge instead of leaving two tree parents.
    for catalog_id in sorted(required_catalog_ids):
        if catalog_id == "ROOT":
            continue
        child = f"curriculum_{catalog_id}"
        parent_catalog_id = str(catalog.node(catalog_id)["parent_id"])
        parent = f"curriculum_{parent_catalog_id}"
        stale_keys = [key for key in edges if key[0] == child and key[1] == "part_of" and key[2] != parent]
        for key in stale_keys:
            del edges[key]
        if (child, "part_of", parent) not in edges:
            add_edge(edges, edge_payload(child, parent, "part_of", nodes[child].get("sources", []), "v0.7 课程目录唯一主父节点", 1.0))

    # Third-review semantic edges supplement, but never replace, part_of.
    for item in promoted:
        catalog_id = item["catalog_id"]
        catalog_node = catalog.node(catalog_id)
        child = f"curriculum_{catalog_id}"
        parent_catalog_id = str(catalog_node["parent_id"])
        parent = f"curriculum_{parent_catalog_id}"
        relation = {
            "Algorithm": "has_algorithm",
            "OperationRule": "has_operation_rule",
            "ComplexityMetric": "has_complexity_metric",
        }.get(str(catalog_node["type"]))
        if relation:
            add_edge(edges, edge_payload(parent, child, relation, nodes[child].get("sources", []), "第三轮复核通过的教学语义关系", 1.0))

    # Approved catalog semantic and prerequisite links are added only when
    # both endpoints are present in this formal graph.
    for relation in catalog.approved_semantic_relations():
        source = f"curriculum_{relation['source_id']}"
        target = f"curriculum_{relation['target_id']}"
        if source in nodes and target in nodes:
            edge = edge_payload(source, target, relation["type"], [], "v0.7 人工维护语义关系", 1.0)
            display_name = catalog.semantic_relation_types[relation["type"]]["display_name"]
            edge["relation_name"] = display_name
            edge["neo4j_type"] = display_name
            add_edge(edges, edge)
    for relation in catalog.approved_prerequisite_relations():
        source = f"curriculum_{relation['source_id']}"
        target = f"curriculum_{relation['target_id']}"
        if source in nodes and target in nodes:
            add_edge(edges, edge_payload(source, target, "prerequisite_of", [], "v0.7 人工维护先修依赖", 1.0))

    for node_id, note in OVERVIEW_NODE_IDS.items():
        if node_id in nodes:
            nodes[node_id]["is_overview_node"] = True
            nodes[node_id]["overview_note"] = note

    graph = copy.deepcopy(base)
    graph["schema_version"] = "programming_kg_standard_graph_v6_formal"
    graph["nodes"] = sorted(nodes.values(), key=lambda item: str(item["id"]))
    graph["edges"] = sorted(edges.values(), key=lambda item: (str(item["type"]), str(item["source"]), str(item["target"])))
    graph.setdefault("schema", {})["curriculum_catalog"] = catalog.payload.get("schema_version")
    graph["schema"]["node_types"] = sorted({str(node.get("type", "")) for node in graph["nodes"]})
    graph["schema"]["edge_types"] = sorted({str(edge.get("type", "")) for edge in graph["edges"]})
    graph["schema"].setdefault("semantic_relation_types", {}).update(
        {
            "has_algorithm": {"display_name": DISPLAY_NAMES["has_algorithm"]},
            "has_operation_rule": {"display_name": DISPLAY_NAMES["has_operation_rule"]},
            "has_complexity_metric": {"display_name": DISPLAY_NAMES["has_complexity_metric"]},
        }
    )
    graph.setdefault("metadata", {}).update(
        {
            "schema_v6_status": "formal_after_third_review",
            "schema_v6_policy": "第三轮复核通过项与组合专题拆分已纳入；其余候选保留审核池。",
            "catalog_version": catalog.payload.get("schema_version"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    report = {
        "schema_version": "programming_kg_schema_v6_formal_upgrade_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "promoted_node_count": len(promoted),
        "promoted_nodes": promoted,
        "overview_nodes": OVERVIEW_NODE_IDS,
        "candidate_records_not_promoted": sum(1 for item in review["records"] if item.get("decision") == "keep_candidate"),
        "specialized_type_distribution": dict(Counter(node.get("type", "") for node in graph["nodes"] if node.get("type") in SPECIALIZED_TEACHING_TYPES)),
    }
    return graph, report


def validate(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = {str(node["id"]): node for node in graph["nodes"]}
    edges = graph["edges"]
    semantic_types = set(graph.get("schema", {}).get("semantic_relation_types", {}))
    schema = validate_graph_schema(nodes, edges, semantic_types)
    root = check_root_connectivity(nodes, edges)
    prerequisite = check_prerequisite_dag(nodes, edges, {"KnowledgeUnit", "KnowledgePoint", "Algorithm", "OperationRule", "ComplexityMetric"})
    edge_keys = [(edge["source"], edge["type"], edge["target"]) for edge in edges]
    code_examples = [node for node in graph["nodes"] if node.get("type") == "CodeExample"]
    outgoing = {str(edge["source"]) for edge in edges}
    return {
        "passed": bool(schema["valid"] and root["valid"] and prerequisite["valid"] and len(edge_keys) == len(set(edge_keys)) and not any(str(node["id"]) in outgoing for node in code_examples)),
        "schema": schema,
        "root_connectivity": root,
        "prerequisite_dag": prerequisite,
        "duplicate_edge_count": len(edge_keys) - len(set(edge_keys)),
        "non_leaf_code_example_count": sum(1 for node in code_examples if str(node["id"]) in outgoing),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Formalize Schema v6 after third review.")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    catalog = CurriculumCatalog.load(args.catalog)
    graph, report = build_formal_graph(read_json(args.base), catalog, read_json(args.review))
    validation = validate(graph)
    report["validation"] = validation
    write_json(args.output_dir / "standard_graph.json", graph)
    write_json(args.output_dir / "schema_v6_formal_upgrade_report.json", report)
    print(f"节点：{len(graph['nodes'])}")
    print(f"关系：{len(graph['edges'])}")
    print(f"升级校验通过：{validation['passed']}")
    print(f"输出：{args.output_dir}")
    raise SystemExit(0 if validation["passed"] else 2)


if __name__ == "__main__":
    main()
