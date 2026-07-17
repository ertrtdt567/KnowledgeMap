"""Three-round audit for the course-centered graph."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from curriculum_catalog import CurriculumCatalog
from formal_schema_v8_course_centered import validate_graph_schema
from formal_schema_v8_course_centered import TEACHING_TYPES


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="课程中心图谱三轮质量审计。")
    parser.add_argument("--graph", default="work/oop_kg_demo/output/programming_kg/course_centered_v8/standard_graph.json")
    parser.add_argument("--builder-report", default="work/oop_kg_demo/output/programming_kg/course_centered_v8/course_centered_report.json")
    parser.add_argument("--catalog", default="work/oop_kg_demo/data/programming_curriculum_v0_10_delivery_repair.json")
    parser.add_argument("--output", default="work/oop_kg_demo/output/programming_kg/course_centered_v8/three_round_audit_report.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    graph = load_json(Path(args.graph))
    builder_report = load_json(Path(args.builder_report))
    catalog = CurriculumCatalog.load(Path(args.catalog))
    nodes = {str(item.get("id", "")): item for item in graph.get("nodes", []) if isinstance(item, dict)}
    edges = [item for item in graph.get("edges", []) if isinstance(item, dict)]
    course_ids = set(graph.get("metadata", {}).get("course_ids", []))

    # Round 1: every course-local tree must have one parent route to its Course.
    parents: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.get("type") == "part_of":
            parents[str(edge.get("source", ""))].append(str(edge.get("target", "")))
    tree_issues: list[dict[str, Any]] = []
    for node_id, node in nodes.items():
        course_id = str(node.get("course_id", ""))
        if not course_id or node.get("type") == "Course" or node.get("type") not in TEACHING_TYPES:
            continue
        current, visited = node_id, set()
        while current not in course_ids:
            if current in visited or len(parents.get(current, [])) != 1:
                tree_issues.append({"node_id": node_id, "course_id": course_id, "reason": "无法沿唯一 part_of 路径到达课程根。"})
                break
            visited.add(current)
            current = parents[current][0]
            if current not in nodes:
                tree_issues.append({"node_id": node_id, "course_id": course_id, "reason": "part_of 指向不存在节点。"})
                break

    # Round 2: Schema endpoints and local/global boundary.
    schema = validate_graph_schema(nodes, edges, set(catalog.semantic_relation_types))

    # Round 3: review-ready evidence checks for automatic core mappings.
    core_issues: list[dict[str, Any]] = []
    for edge in edges:
        if edge.get("type") != "maps_to_core":
            continue
        source = nodes.get(str(edge.get("source", "")), {})
        target = nodes.get(str(edge.get("target", "")), {})
        supporting_courses = target.get("supporting_course_ids", [])
        if len(set(supporting_courses)) < 2 or not source.get("sources"):
            core_issues.append({"edge_id": edge.get("id", ""), "reason": "核心映射缺少两门课程证据或本地直接证据。"})

    degree = Counter()
    for edge in edges:
        degree[str(edge.get("source", ""))] += 1
        degree[str(edge.get("target", ""))] += 1
    isolated = [node_id for node_id in nodes if degree[node_id] == 0]
    result = {
        "schema_version": "course_centered_three_round_audit_v1",
        "round_1_course_tree": {"passed": not tree_issues, "issue_count": len(tree_issues), "issues": tree_issues[:100]},
        "round_2_schema": schema,
        "round_3_core_review": {"passed": not core_issues, "issue_count": len(core_issues), "issues": core_issues[:100]},
        "global_checks": {"isolated_node_count": len(isolated), "isolated_nodes": isolated[:100]},
        "passed": not tree_issues and bool(schema.get("valid")) and not core_issues and not isolated,
        "candidate_core_count": len(builder_report.get("cross_course_core_candidates", [])),
    }
    write_json(Path(args.output), result)
    print(f"第一轮课程树通过：{result['round_1_course_tree']['passed']}")
    print(f"第二轮 Schema 通过：{result['round_2_schema']['valid']}")
    print(f"第三轮核心映射通过：{result['round_3_core_review']['passed']}")
    print(f"全局审计通过：{result['passed']}")
    print(f"审计报告：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
