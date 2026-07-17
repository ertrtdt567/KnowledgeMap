"""对正式知识图谱、正式题库和考点映射执行可重复的质量审计。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import formal_schema_v5 as v5
import formal_schema_v6 as v6
import formal_schema_v7 as v7
import formal_schema_v8_course_centered as v8


DEFAULT_GRAPH = "work/oop_kg_demo/output/programming_kg/graph_hierarchy/standard_graph.json"
DEFAULT_QUESTIONS = "work/oop_kg_demo/output/programming_kg/questions/combined_official_questions.json"
DEFAULT_LINKS = "work/oop_kg_demo/output/programming_kg/question_mapping/question_knowledge_links.json"
DEFAULT_OUTPUT = "work/oop_kg_demo/output/programming_kg/quality_audit_report.json"
ROOT_NODE_ID = "curriculum_ROOT"
OPTIONAL_MAPPING_COGNITIVE_LEVELS = {"remember", "understand", "apply", "analyze", "evaluate", "create"}
OPTIONAL_MAPPING_STATUSES = {"draft", "reviewed", "approved"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    """原子写入审计报告，避免前端或后续程序读到半写入文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def check_root_connectivity(
    by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    root_node_id: str,
) -> dict[str, Any]:
    """验证每个正式节点都能通过关系路径接入课程根节点。"""
    if root_node_id not in by_id:
        return {
            "valid": False,
            "root_present": False,
            "connected_node_count": 0,
            "disconnected_node_ids": sorted(by_id)[:50],
        }
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source in by_id and target in by_id:
            adjacency[source].add(target)
            adjacency[target].add(source)
    connected = {root_node_id}
    stack = [root_node_id]
    while stack:
        current = stack.pop()
        for neighbor in adjacency[current]:
            if neighbor not in connected:
                connected.add(neighbor)
                stack.append(neighbor)
    disconnected = sorted(set(by_id) - connected)
    return {
        "valid": not disconnected,
        "root_present": True,
        "connected_node_count": len(connected),
        "disconnected_node_ids": disconnected[:50],
    }


def check_prerequisite_dag(
    by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    teaching_types: set[str],
) -> dict[str, Any]:
    """先修边可以跨层级，但必须保持“先修 -> 后续”的有向无环结构。"""
    adjacency: dict[str, set[str]] = defaultdict(set)
    invalid_endpoints: list[str] = []
    for edge in edges:
        if edge.get("type") != "prerequisite_of":
            continue
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        source_type = str(by_id.get(source, {}).get("type", ""))
        target_type = str(by_id.get(target, {}).get("type", ""))
        if source_type not in teaching_types or target_type not in teaching_types:
            invalid_endpoints.append(str(edge.get("id", "")))
            continue
        adjacency[source].add(target)

    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            cycle_nodes.add(node_id)
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
        "valid": not invalid_endpoints and not cycle_nodes,
        "relation_count": sum(len(targets) for targets in adjacency.values()),
        "invalid_endpoint_edge_ids": invalid_endpoints[:50],
        "cycle_node_ids": sorted(cycle_nodes),
    }


def check_language_scope(nodes: list[dict[str, Any]], course_centered: bool = False) -> dict[str, Any]:
    """范围字段为空是允许的，代表材料没有给出明确语言限定。"""
    invalid_nodes: list[str] = []
    scoped_count = 0
    for node in nodes:
        if course_centered:
            node_type = str(node.get("type", ""))
            # 课程中心图通过 course_id 隔离课程局部节点；共享核心概念和总根节点不属于单门课程。
            if node_type in {"CoreConcept", "Course"} or str(node.get("id", "")) == "programming_domain_root":
                continue
            if not str(node.get("course_id", "")):
                invalid_nodes.append(str(node.get("id", "")))
            else:
                scoped_count += 1
            continue
        scope = node.get("language_scope")
        status = str(node.get("language_scope_status", ""))
        if not isinstance(scope, list) or any(not isinstance(item, str) or not item for item in scope):
            invalid_nodes.append(str(node.get("id", "")))
            continue
        if status not in {"explicit", "inferred_from_descendants", "unspecified"}:
            invalid_nodes.append(str(node.get("id", "")))
        if scope:
            scoped_count += 1
    return {"valid": not invalid_nodes, "scoped_node_count": scoped_count, "invalid_node_ids": invalid_nodes[:50]}


def audit(
    graph: dict[str, Any],
    questions: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    by_id = {str(node.get("id", "")): node for node in nodes}
    node_ids = [str(node.get("id", "")) for node in nodes]
    semantic_types = set(graph.get("schema", {}).get("semantic_relation_types", {}))
    schema_version = str(graph.get("schema_version", ""))
    course_centered = str(graph.get("metadata", {}).get("organization", "")) == "course_centered"
    schema_module = v8 if course_centered else (v7 if "v7" in schema_version else (v6 if "v6" in schema_version else v5))
    if schema_module is v8:
        teaching_types = v8.TEACHING_TYPES | {v8.CORE_CONCEPT_TYPE}
    else:
        teaching_types = schema_module.TEACHING_TYPES if schema_module in {v6, v7} else v5.CURRICULUM_TYPES
    schema_report = schema_module.validate_graph_schema(by_id, edges, semantic_types)
    root_node_id = str(graph.get("metadata", {}).get("root_node_id", ROOT_NODE_ID))
    root_connectivity = check_root_connectivity(by_id, edges, root_node_id)
    prerequisite_report = check_prerequisite_dag(by_id, edges, teaching_types)
    language_scope_report = check_language_scope(nodes, course_centered)

    edge_keys = [
        (str(edge.get("source", "")), str(edge.get("type", "")), str(edge.get("target", "")))
        for edge in edges
    ]
    dangling = [
        edge
        for edge in edges
        if str(edge.get("source", "")) not in by_id or str(edge.get("target", "")) not in by_id
    ]
    self_loops = [edge for edge in edges if edge.get("source") == edge.get("target")]
    fact_errors = []
    for edge in edges:
        if str(edge.get("source", "")) not in by_id or str(edge.get("target", "")) not in by_id:
            continue
        fact_module = v7 if schema_module is v8 else schema_module
        valid, reason = fact_module.relation_is_factually_valid(edge, by_id)
        if not valid:
            fact_errors.append({"edge_id": edge.get("id", ""), "reason": reason})

    incoming = Counter(str(edge.get("target", "")) for edge in edges)
    outgoing = Counter(str(edge.get("source", "")) for edge in edges)
    code_examples = [node for node in nodes if node.get("type") == "CodeExample"]
    invalid_examples = []
    for node in code_examples:
        valid, reason, score = v5.code_example_quality(node)
        if not valid:
            invalid_examples.append({"id": node.get("id", ""), "reason": reason, "score": score})
    orphan_examples = [node["id"] for node in code_examples if not incoming[str(node["id"])]]
    code_structure_errors = [
        node["id"]
        for node in nodes
        if node.get("type") == "CodeStructure"
        and (not node.get("scope_example_id") or not node.get("structure_kind"))
    ]

    canonical_names: dict[tuple[str, str], str] = {}
    alias_owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    alias_collisions: list[dict[str, str]] = []
    for node in nodes:
        if node.get("type") in {"CodeStructure", "CodeExample"}:
            continue
        namespace = str(node.get("course_id", "")) if course_centered else "global"
        key = (namespace, str(node.get("name", "")).strip().casefold())
        if key[1]:
            canonical_names[key] = str(node.get("id", ""))
    for node in nodes:
        if node.get("type") in {"CodeStructure", "CodeExample"}:
            continue
        for alias in node.get("aliases", []):
            namespace = str(node.get("course_id", "")) if course_centered else "global"
            key = (namespace, str(alias).strip().casefold())
            if not key[1]:
                continue
            alias_owners[key].add(str(node.get("id", "")))
            owner = canonical_names.get(key)
            if owner and owner != str(node.get("id", "")):
                alias_collisions.append(
                    {"alias": str(alias), "alias_owner": str(node.get("id", "")), "canonical_owner": owner}
                )
    multi_aliases = {
        f"{namespace}:{alias}" if namespace else alias: sorted(owners)
        for (namespace, alias), owners in alias_owners.items()
        if len(owners) > 1
    }

    question_ids = [str(question.get("question_id", "")) for question in questions]
    question_by_id = {str(question.get("question_id", "")): question for question in questions}
    mapping_by_id = {str(mapping.get("question_id", "")): mapping for mapping in mappings}
    bad_answer_status = []
    for question in questions:
        source = str(question.get("answer_source", ""))
        status = str(question.get("answer_status", ""))
        if source == "llm_generated" and status not in {"human_verified", "compiler_verified"}:
            bad_answer_status.append(str(question.get("question_id", "")))

    bad_mapping_refs: list[dict[str, str]] = []
    mapping_policy_errors: list[dict[str, Any]] = []
    for question_id, mapping in mapping_by_id.items():
        links = [link for link in mapping.get("links", []) if isinstance(link, dict)]
        limit = 5 if mapping.get("method") == "human_gold" else 3
        if len(links) > limit:
            mapping_policy_errors.append({"question_id": question_id, "reason": f"考点数量超过 {limit}"})
        if not any(link.get("role") == "primary" for link in links):
            mapping_policy_errors.append({"question_id": question_id, "reason": "缺少 primary 考点"})
        if mapping.get("unresolved_gold_items"):
            mapping_policy_errors.append({"question_id": question_id, "reason": "存在未解析人工金标准项"})
        seen_targets: set[str] = set()
        for link in links:
            target = str(link.get("knowledge_node_id", ""))
            if target not in by_id:
                bad_mapping_refs.append({"question_id": question_id, "knowledge_node_id": target})
            if target in seen_targets:
                mapping_policy_errors.append({"question_id": question_id, "reason": f"重复考点：{target}"})
            seen_targets.add(target)
            # 这些字段是新版扩展，旧题库可以缺省；一旦提供就必须满足约束。
            if "role_weight" in link:
                try:
                    role_weight = float(link["role_weight"])
                except (TypeError, ValueError):
                    role_weight = -1.0
                if not 0.0 <= role_weight <= 1.0:
                    mapping_policy_errors.append({"question_id": question_id, "reason": "role_weight 必须在 0 到 1 之间"})
            cognitive_level = str(link.get("cognitive_level", "")).strip()
            if cognitive_level and cognitive_level not in OPTIONAL_MAPPING_COGNITIVE_LEVELS:
                mapping_policy_errors.append({"question_id": question_id, "reason": f"未知认知层级：{cognitive_level}"})
            mapping_status = str(link.get("mapping_status", "")).strip()
            if mapping_status and mapping_status not in OPTIONAL_MAPPING_STATUSES:
                mapping_policy_errors.append({"question_id": question_id, "reason": f"未知映射状态：{mapping_status}"})

    checks = {
        "schema_version_supported": course_centered or schema_version.endswith("v5") or "v6" in schema_version or "v7" in schema_version,
        "unique_node_ids": len(node_ids) == len(set(node_ids)) and all(node_ids),
        "unique_question_ids": len(question_ids) == len(set(question_ids)) and all(question_ids),
        "unique_mapping_ids": len(mapping_by_id) == len(mappings),
        "question_mapping_coverage": set(question_by_id) == set(mapping_by_id),
        "no_dangling_edges": not dangling,
        "no_self_loops": not self_loops,
        "no_duplicate_edges": len(edge_keys) == len(set(edge_keys)),
        "formal_schema_valid": bool(schema_report.get("valid")),
        "all_nodes_connected_to_curriculum_root": bool(root_connectivity.get("valid")),
        "prerequisite_dag_valid": bool(prerequisite_report.get("valid")),
        "language_scope_valid": bool(language_scope_report.get("valid")),
        "language_facts_valid": not fact_errors,
        "aliases_valid": not alias_collisions and not multi_aliases,
        "code_examples_valid": not invalid_examples and not orphan_examples and not any(outgoing[str(node["id"])] for node in code_examples),
        "code_structures_scoped": not code_structure_errors,
        "formal_answers_independently_verified": not bad_answer_status,
        "mapping_references_valid": not bad_mapping_refs,
        "mapping_policy_valid": not mapping_policy_errors,
    }
    return {
        "schema_version": "programming_kg_quality_audit_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "checks": checks,
        "counts": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "root_connected_node_count": root_connectivity.get("connected_node_count", 0),
            "question_count": len(questions),
            "mapping_count": len(mappings),
            "assessment_link_count": sum(len(mapping.get("links", [])) for mapping in mappings),
            "node_type_distribution": dict(Counter(str(node.get("type", "")) for node in nodes)),
            "edge_type_distribution": dict(Counter(str(edge.get("type", "")) for edge in edges)),
        },
        "issues": {
            "dangling_edges": dangling[:50],
            "self_loops": self_loops[:50],
            "schema_violations": schema_report.get("violations", []),
            "root_connectivity": root_connectivity,
            "prerequisite_dag": prerequisite_report,
            "language_scope": language_scope_report,
            "language_fact_errors": fact_errors,
            "alias_collisions": alias_collisions,
            "multi_owner_aliases": multi_aliases,
            "invalid_code_examples": invalid_examples,
            "orphan_code_examples": orphan_examples,
            "unscoped_code_structures": code_structure_errors,
            "formal_llm_answers_without_independent_verification": bad_answer_status,
            "bad_mapping_references": bad_mapping_refs,
            "mapping_policy_errors": mapping_policy_errors,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计正式编程知识图谱与习题层。")
    parser.add_argument("--graph", default=DEFAULT_GRAPH)
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS)
    parser.add_argument("--links", default=DEFAULT_LINKS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--graph-only",
        action="store_true",
        help="只审计图谱；课程重建阶段可避免旧题目映射 ID 干扰图结构与 Schema 校验。",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    graph = load_json(Path(args.graph))
    questions = [] if args.graph_only else load_json(Path(args.questions))
    mappings = [] if args.graph_only else load_json(Path(args.links))
    if not isinstance(graph, dict) or not isinstance(questions, list) or not isinstance(mappings, list):
        raise ValueError("图谱必须是对象，题库和映射必须是数组。")
    report = audit(graph, questions, mappings)
    write_json(Path(args.output), report)
    print(f"质量审计通过：{report['passed']}")
    print(f"节点：{report['counts']['node_count']}，关系：{report['counts']['edge_count']}")
    print(f"习题：{report['counts']['question_count']}，考察关系：{report['counts']['assessment_link_count']}")
    print(f"审计报告：{args.output}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
