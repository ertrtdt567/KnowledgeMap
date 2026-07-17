"""Create a non-destructive schema v6 candidate graph and quality comparison.

The script deliberately does not write Neo4j.  It merges the current formal
graph with the reviewed data-structures graph, migrates only explicitly listed
high-confidence nodes, and records every other possible type change for human
review.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from audit_formal_graph import check_root_connectivity
from formal_schema_v5 import code_example_quality
from formal_schema_v6 import (
    CURRICULUM_TYPES,
    DISPLAY_NAMES,
    SPECIALIZED_TEACHING_TYPES,
    TEACHING_TYPES,
    relation_is_factually_valid,
    validate_graph_schema,
)


ALGORITHM_NODE_IDS = {
    "curriculum_D1_14",
    "curriculum_D7_2",
    "curriculum_D7_3",
    "curriculum_D7_4",
    "curriculum_D7_6",
    "curriculum_D8_2",
    "curriculum_D8_3",
    "curriculum_D8_4",
    "curriculum_D8_5",
    "curriculum_D8_6",
}
OPERATION_RULE_NODE_IDS = {"curriculum_D1_11"}
COMPLEXITY_METRIC_NODE_IDS: set[str] = set()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def stable_id(*parts: str) -> str:
    value = "|".join(parts)
    return "schema_v6_" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


def unique_items(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def merge_records(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(left)
    for key, value in right.items():
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = copy.deepcopy(value)
        elif isinstance(merged[key], list) and isinstance(value, list):
            merged[key] = unique_items([*merged[key], *value])
        elif key == "confidence":
            try:
                merged[key] = max(float(merged[key]), float(value))
            except (TypeError, ValueError):
                pass
    return merged


def merge_graphs(base: dict[str, Any], incremental: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {str(node["id"]): copy.deepcopy(node) for node in base.get("nodes", [])}
    conflicts: list[dict[str, Any]] = []
    overlap_count = 0
    for node in incremental.get("nodes", []):
        node_id = str(node["id"])
        existing = nodes.get(node_id)
        if existing is None:
            nodes[node_id] = copy.deepcopy(node)
            continue
        overlap_count += 1
        if (existing.get("name"), existing.get("type")) != (node.get("name"), node.get("type")):
            conflicts.append(
                {
                    "id": node_id,
                    "base": {"name": existing.get("name"), "type": existing.get("type")},
                    "incremental": {"name": node.get("name"), "type": node.get("type")},
                }
            )
            continue
        nodes[node_id] = merge_records(existing, node)

    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    for graph in (base, incremental):
        for edge in graph.get("edges", []):
            key = (str(edge.get("source", "")), str(edge.get("type", "")), str(edge.get("target", "")))
            if key in edges:
                edges[key] = merge_records(edges[key], edge)
            else:
                edges[key] = copy.deepcopy(edge)

    merged = copy.deepcopy(base)
    merged["nodes"] = sorted(nodes.values(), key=lambda node: str(node["id"]))
    merged["edges"] = sorted(edges.values(), key=lambda edge: (str(edge["type"]), str(edge["source"]), str(edge["target"])))
    merged.setdefault("metadata", {})["schema_v6_candidate_sources"] = [
        "existing_formal_graph",
        "data_structures_reviewed_candidate_graph",
    ]
    return merged, {
        "overlapping_node_count": overlap_count,
        "node_conflict_count": len(conflicts),
        "node_conflicts": conflicts,
        "merged_node_count": len(nodes),
        "merged_edge_count": len(edges),
    }


def requested_type(node_id: str) -> tuple[str | None, str]:
    if node_id in ALGORITHM_NODE_IDS:
        return "Algorithm", "explicit curriculum algorithm with direct material evidence"
    if node_id in OPERATION_RULE_NODE_IDS:
        return "OperationRule", "explicit operational procedure with direct material evidence"
    if node_id in COMPLEXITY_METRIC_NODE_IDS:
        return "ComplexityMetric", "explicit evaluation metric with direct material evidence"
    return None, ""


def looks_type_sensitive(name: str) -> bool:
    terms = (
        "\u7b97\u6cd5", "\u6392\u5e8f", "\u67e5\u627e", "\u64cd\u4f5c", "\u590d\u6742\u5ea6", "\u89c4\u5219", "\u6d41\u7a0b",
        "algorithm", "sort", "search", "operation", "complexity", "rule", "workflow",
    )
    normalized = name.casefold()
    return any(term.casefold() in normalized for term in terms)


def migrate_types(graph: dict[str, Any]) -> dict[str, Any]:
    migrated: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}
    for node_id, node in nodes.items():
        if node.get("type") != "KnowledgePoint":
            continue
        new_type, reason = requested_type(node_id)
        confidence = float(node.get("confidence", 0.0) or 0.0)
        has_sources = bool(node.get("sources"))
        if new_type and confidence >= 0.95 and has_sources:
            previous_type = str(node["type"])
            node["type"] = new_type
            node["previous_type"] = previous_type
            node["schema_v6_type_confidence"] = 0.98
            node["schema_v6_migration_reason"] = reason
            migrated.append(
                {
                    "id": node_id,
                    "name": node.get("name", ""),
                    "previous_type": previous_type,
                    "new_type": new_type,
                    "confidence": 0.98,
                    "reason": reason,
                }
            )
        elif looks_type_sensitive(str(node.get("name", ""))):
            review.append(
                {
                    "id": node_id,
                    "name": node.get("name", ""),
                    "current_type": node.get("type", ""),
                    "recommendation": "retain KnowledgePoint pending human review",
                    "reason": "name may indicate an algorithm, rule, or metric but evidence is not sufficient for automatic migration",
                }
            )

    existing_keys = {(str(edge.get("source", "")), str(edge.get("type", "")), str(edge.get("target", ""))) for edge in graph.get("edges", [])}
    new_edges: list[dict[str, Any]] = []
    for item in migrated:
        node_id = item["id"]
        relation_type = {
            "Algorithm": "has_algorithm",
            "OperationRule": "has_operation_rule",
            "ComplexityMetric": "has_complexity_metric",
        }[item["new_type"]]
        parents = [str(edge["target"]) for edge in graph.get("edges", []) if edge.get("type") == "part_of" and str(edge.get("source")) == node_id]
        for parent_id in parents:
            parent = nodes.get(parent_id, {})
            if parent.get("type") not in TEACHING_TYPES:
                continue
            key = (parent_id, relation_type, node_id)
            if key in existing_keys:
                continue
            new_edges.append(
                {
                    "id": stable_id(*key),
                    "source": parent_id,
                    "target": node_id,
                    "type": relation_type,
                    "relation_name": DISPLAY_NAMES[relation_type],
                    "neo4j_type": DISPLAY_NAMES[relation_type],
                    "confidence": 1.0,
                    "evidence": "schema v6 high-confidence type migration",
                    "source_chunks": list(node.get("source_chunk_ids", [])),
                    "sources": list(node.get("sources", [])),
                }
            )
            existing_keys.add(key)
    graph["edges"].extend(new_edges)
    graph["edges"].sort(key=lambda edge: (str(edge["type"]), str(edge["source"]), str(edge["target"])))
    return {"migrated_nodes": migrated, "review_nodes": review, "new_semantic_edges": new_edges}


def classify_data_structure_candidates(candidate_report: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in candidate_report.get("candidates", []):
        name = str(item.get("name", ""))
        normalized = name.casefold()
        if any(token in normalized for token in ("\u65cb\u8f6c", "\u63a2\u6d4b", "\u63d2\u5165", "\u5220\u9664", "\u8f6c\u7f6e", "\u904d\u5386", "\u64cd\u4f5c")):
            bucket = "operation_rule_review"
            action = "consider OperationRule after parent relation and material evidence are confirmed"
        elif any(token in normalized for token in ("\u590d\u6742\u5ea6", "o(", "\u6027\u80fd", "\u6548\u7387", "\u6bd4\u8f83\u6b21\u6570", "\u8f85\u52a9\u7a7a\u95f4", "\u88c5\u586b\u56e0\u5b50")):
            bucket = "complexity_metric_review"
            action = "consider ComplexityMetric or a metric value after unit and scope are confirmed"
        elif any(token in normalized for token in ("\u7b97\u6cd5", "\u6392\u5e8f", "\u67e5\u627e", "kmp", "prim", "kruskal", "floyd", "dijkstra")):
            bucket = "algorithm_review"
            action = "consider Algorithm after duplicate and parent checks"
        elif any(token in normalized for token in ("\u6570\u636e\u7ed3\u6784", "\u54c8\u5e0c\u8868", "\u6563\u5217\u8868", "\u4e32(string)")):
            bucket = "alias_or_alignment_review"
            action = "prefer alias or alignment-term update when it is a synonym of an existing node"
        else:
            bucket = "manual_curriculum_review"
            action = "retain as candidate until its teaching granularity and parent are confirmed"
        buckets[bucket].append(
            {
                "id": item.get("id", ""),
                "name": name,
                "source_type": item.get("type", ""),
                "confidence": item.get("confidence", 0.0),
                "recommended_action": action,
                "source_chunk_ids": item.get("source_chunk_ids", []),
            }
        )
    return {"counts": {key: len(value) for key, value in sorted(buckets.items())}, "items": dict(buckets)}


def alias_collisions(nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    canonical: dict[str, str] = {}
    owners: dict[str, set[str]] = defaultdict(set)
    collisions: list[dict[str, str]] = []
    for node_id, node in nodes.items():
        if node.get("type") in {"CodeStructure", "CodeExample"}:
            continue
        name = str(node.get("name", "")).strip().casefold()
        if name:
            canonical[name] = node_id
    for node_id, node in nodes.items():
        if node.get("type") in {"CodeStructure", "CodeExample"}:
            continue
        for alias in node.get("aliases", []):
            key = str(alias).strip().casefold()
            if not key:
                continue
            owners[key].add(node_id)
            if key in canonical and canonical[key] != node_id:
                collisions.append({"alias": str(alias), "alias_owner": node_id, "canonical_owner": canonical[key]})
    duplicates = {alias: sorted(node_ids) for alias, node_ids in owners.items() if len(node_ids) > 1}
    return {"valid": not collisions and not duplicates, "canonical_collisions": collisions[:100], "duplicate_aliases": duplicates}


def sanitize_aliases(nodes: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    """Remove aliases that are now formal names of a different node.

    This is a deterministic ontology repair, not a semantic merge: the old
    node remains in the graph, but it can no longer claim a new formal node's
    identity as an alias.
    """
    canonical: dict[str, str] = {}
    for node_id, node in nodes.items():
        if node.get("type") in {"CodeStructure", "CodeExample"}:
            continue
        key = str(node.get("name", "")).strip().casefold()
        if key:
            canonical[key] = node_id
    repairs: list[dict[str, str]] = []
    for node_id, node in nodes.items():
        aliases = list(node.get("aliases", []))
        kept: list[Any] = []
        for alias in aliases:
            owner = canonical.get(str(alias).strip().casefold())
            if owner and owner != node_id:
                repairs.append({"node_id": node_id, "removed_alias": str(alias), "canonical_owner": owner})
            else:
                kept.append(alias)
        node["aliases"] = kept
    return repairs


def check_prerequisite_dag_v6(by_id: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate v6 prerequisite edges, including Algorithm and OperationRule."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    invalid_endpoints: list[str] = []
    allowed = TEACHING_TYPES - {"KnowledgeDomain"}
    for edge in edges:
        if edge.get("type") != "prerequisite_of":
            continue
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if str(by_id.get(source, {}).get("type", "")) not in allowed or str(by_id.get(target, {}).get("type", "")) not in allowed:
            invalid_endpoints.append(str(edge.get("id", "")))
            continue
        adjacency[source].add(target)

    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            cycles.add(node_id)
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for target_id in adjacency.get(node_id, set()):
            visit(target_id)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in adjacency:
        visit(node_id)
    return {
        "valid": not invalid_endpoints and not cycles,
        "relation_count": sum(len(targets) for targets in adjacency.values()),
        "invalid_endpoint_edge_ids": invalid_endpoints[:50],
        "cycle_node_ids": sorted(cycles),
    }


def mapping_report(questions: list[dict[str, Any]], mappings: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    question_ids = {str(question.get("question_id", "")) for question in questions}
    mapping_by_id = {str(mapping.get("question_id", "")): mapping for mapping in mappings}
    missing_questions = sorted(question_ids - set(mapping_by_id))
    extra_mappings = sorted(set(mapping_by_id) - question_ids)
    invalid_targets: list[dict[str, str]] = []
    type_changes: list[dict[str, str]] = []
    link_count = 0
    for question_id, mapping in mapping_by_id.items():
        for link in mapping.get("links", []):
            link_count += 1
            target_id = str(link.get("knowledge_node_id", ""))
            node = nodes.get(target_id)
            if node is None:
                invalid_targets.append({"question_id": question_id, "knowledge_node_id": target_id})
                continue
            old_type = str(link.get("knowledge_type", ""))
            new_type = str(node.get("type", ""))
            if old_type and old_type != new_type:
                type_changes.append(
                    {"question_id": question_id, "knowledge_node_id": target_id, "old_type": old_type, "new_type": new_type}
                )
    return {
        "question_count": len(question_ids),
        "mapping_count": len(mapping_by_id),
        "assessment_link_count": link_count,
        "missing_question_mappings": missing_questions,
        "extra_mappings": extra_mappings,
        "invalid_knowledge_targets": invalid_targets,
        "mapped_target_type_changes": type_changes,
        "valid": not missing_questions and not extra_mappings and not invalid_targets,
    }


def quality_report(
    base: dict[str, Any],
    candidate: dict[str, Any],
    questions: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    merge_info: dict[str, Any],
    migration: dict[str, Any],
) -> dict[str, Any]:
    base_nodes = {str(node["id"]): node for node in base.get("nodes", [])}
    candidate_nodes = {str(node["id"]): node for node in candidate.get("nodes", [])}
    base_edge_keys = {(str(edge["source"]), str(edge["type"]), str(edge["target"])) for edge in base.get("edges", [])}
    candidate_edge_keys = {(str(edge["source"]), str(edge["type"]), str(edge["target"])) for edge in candidate.get("edges", [])}
    semantic_types = set(candidate.get("schema", {}).get("semantic_relation_types", {}))
    schema = validate_graph_schema(candidate_nodes, candidate.get("edges", []), semantic_types)
    root = check_root_connectivity(candidate_nodes, candidate.get("edges", []))
    prerequisite = check_prerequisite_dag_v6(candidate_nodes, candidate.get("edges", []))
    aliases = alias_collisions(candidate_nodes)
    fact_errors = []
    for edge in candidate.get("edges", []):
        if str(edge.get("source", "")) not in candidate_nodes or str(edge.get("target", "")) not in candidate_nodes:
            continue
        valid, reason = relation_is_factually_valid(edge, candidate_nodes)
        if not valid:
            fact_errors.append({"edge_id": edge.get("id", ""), "reason": reason})
    code_examples = [node for node in candidate_nodes.values() if node.get("type") == "CodeExample"]
    incoming = Counter(str(edge.get("target", "")) for edge in candidate.get("edges", []))
    outgoing = Counter(str(edge.get("source", "")) for edge in candidate.get("edges", []))
    bad_examples = []
    for node in code_examples:
        valid, reason, score = code_example_quality(node)
        if not valid:
            bad_examples.append({"id": node.get("id", ""), "reason": reason, "score": score})
    orphan_examples = [str(node["id"]) for node in code_examples if not incoming[str(node["id"])]]
    leaf_violations = [str(node["id"]) for node in code_examples if outgoing[str(node["id"])]]
    mapping = mapping_report(questions, mappings, candidate_nodes)
    checks = {
        "base_nodes_preserved": set(base_nodes).issubset(candidate_nodes),
        "base_edges_preserved": base_edge_keys.issubset(candidate_edge_keys),
        "merge_has_no_node_conflict": merge_info["node_conflict_count"] == 0,
        "schema_v6_valid": bool(schema["valid"]),
        "root_connectivity_valid": bool(root["valid"]),
        "prerequisite_dag_valid": bool(prerequisite["valid"]),
        "aliases_valid": bool(aliases["valid"]),
        "language_facts_valid": not fact_errors,
        "code_examples_remain_leaves": not leaf_violations,
        "code_examples_remain_valid": not bad_examples and not orphan_examples,
        "question_mapping_preserved": bool(mapping["valid"]),
    }
    return {
        "schema_version": "programming_kg_schema_v6_quality_comparison_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "checks": checks,
        "baseline": {
            "node_count": len(base_nodes),
            "edge_count": len(base_edge_keys),
            "node_type_distribution": dict(Counter(str(node.get("type", "")) for node in base_nodes.values())),
            "edge_type_distribution": dict(Counter(edge[1] for edge in base_edge_keys)),
        },
        "candidate": {
            "node_count": len(candidate_nodes),
            "edge_count": len(candidate_edge_keys),
            "node_type_distribution": dict(Counter(str(node.get("type", "")) for node in candidate_nodes.values())),
            "edge_type_distribution": dict(Counter(edge[1] for edge in candidate_edge_keys)),
            "added_node_count": len(candidate_nodes) - len(base_nodes),
            "added_edge_count": len(candidate_edge_keys) - len(base_edge_keys),
            "specialized_teaching_type_count": sum(
                1 for node in candidate_nodes.values() if node.get("type") in SPECIALIZED_TEACHING_TYPES
            ),
        },
        "merge": merge_info,
        "migration": {
            "migrated_node_count": len(migration["migrated_nodes"]),
            "new_semantic_edge_count": len(migration["new_semantic_edges"]),
            "review_node_count": len(migration["review_nodes"]),
        },
        "schema_validation": schema,
        "root_connectivity": root,
        "prerequisite_validation": prerequisite,
        "alias_validation": aliases,
        "language_fact_errors": fact_errors[:100],
        "code_example_validation": {
            "code_example_count": len(code_examples),
            "invalid_examples": bad_examples[:100],
            "orphan_example_ids": orphan_examples[:100],
            "non_leaf_example_ids": leaf_violations[:100],
        },
        "question_mapping": mapping,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a schema v6 candidate graph without changing Neo4j.")
    parser.add_argument("--base", required=True, help="Current approved formal graph JSON.")
    parser.add_argument("--incremental", required=True, help="Reviewed incremental data-structures graph JSON.")
    parser.add_argument("--questions", required=True, help="Approved question bank JSON.")
    parser.add_argument("--mappings", required=True, help="Question-to-knowledge mapping JSON.")
    parser.add_argument("--candidate-report", required=True, help="Data-structures candidate report JSON.")
    parser.add_argument("--output-dir", required=True, help="Candidate output directory.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    base = load_json(Path(args.base))
    incremental = load_json(Path(args.incremental))
    questions = load_json(Path(args.questions))
    mappings = load_json(Path(args.mappings))
    candidate_report = load_json(Path(args.candidate_report))
    if not isinstance(questions, list) or not isinstance(mappings, list):
        raise ValueError("questions and mappings must be JSON arrays")

    graph, merge_info = merge_graphs(base, incremental)
    migration = migrate_types(graph)
    alias_repairs = sanitize_aliases({str(node["id"]): node for node in graph.get("nodes", [])})
    migration["alias_repairs"] = alias_repairs
    semantic_types = graph.setdefault("schema", {}).setdefault("semantic_relation_types", {})
    if not isinstance(semantic_types, dict):
        semantic_types = {str(item): {"display_name": str(item)} for item in semantic_types}
        graph["schema"]["semantic_relation_types"] = semantic_types
    semantic_types.update(
        {
            "has_algorithm": {"display_name": DISPLAY_NAMES["has_algorithm"]},
            "has_operation_rule": {"display_name": DISPLAY_NAMES["has_operation_rule"]},
            "has_complexity_metric": {"display_name": DISPLAY_NAMES["has_complexity_metric"]},
        }
    )
    graph["schema_version"] = "programming_kg_standard_graph_v6_candidate"
    graph["schema"]["node_types"] = sorted({str(node.get("type", "")) for node in graph.get("nodes", [])})
    graph["schema"]["edge_types"] = sorted({str(edge.get("type", "")) for edge in graph.get("edges", [])})
    graph.setdefault("metadata", {}).update(
        {
            "schema_v6_status": "candidate_only_not_imported_to_neo4j",
            "schema_v6_policy": "Only pre-approved high-confidence IDs are migrated; uncertain nodes retain KnowledgePoint.",
            "schema_v6_specialized_types": sorted(SPECIALIZED_TEACHING_TYPES),
        }
    )

    comparison = quality_report(base, graph, questions, mappings, merge_info, migration)
    candidate_recommendations = classify_data_structure_candidates(candidate_report)
    output_dir = Path(args.output_dir)
    write_json(output_dir / "standard_graph.json", graph)
    write_json(output_dir / "schema_migration_review.json", migration)
    write_json(output_dir / "data_structure_candidate_recommendations.json", candidate_recommendations)
    write_json(output_dir / "quality_comparison_report.json", comparison)
    print(f"Candidate graph nodes: {len(graph['nodes'])}")
    print(f"Candidate graph edges: {len(graph['edges'])}")
    print(f"Migrated nodes: {len(migration['migrated_nodes'])}")
    print(f"Quality comparison passed: {comparison['passed']}")
    print(f"Output directory: {output_dir}")
    return 0 if comparison["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
