"""Publish one immutable, internally consistent programming-KG release.

The release ties the graph, question bank and question mappings together by
one versioned manifest.  It deliberately derives every published file from
the current formal inputs rather than from the older demo snapshots.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_GRAPH = BASE_DIR / "output/programming_kg/course_centered_v12_with_questions/standard_graph.json"
DEFAULT_QUESTIONS = BASE_DIR / "output/programming_kg/questions/unified_v1_review/formal_precise_questions.json"
DEFAULT_MAPPINGS = BASE_DIR / "output/programming_kg/questions/unified_v1_review/formal_precise_question_knowledge_links.json"
DEFAULT_OUTPUT = BASE_DIR / "output/programming_kg/release/v2026.07.18"
VERSION = "v2026.07.18"
RETIRED_ALGORITHM_NAMES = {"算法设计与分析"}
RETRACTED_EDGE_IDS = {
    "edge_7cd24253063e9a28",
    "edge_9e8894739d444faa",
    "edge_73223ac1f63d872e",
    "edge_49e06ab63ce5e4fe",
    "edge_71ac91e30eaa66c0",
}
RETRACTED_NODE_IDS = {"course_java__extension_ABILITY_OOP_MODELING"}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def algorithm_subtree_ids(graph: dict[str, Any]) -> set[str]:
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    seeds = {
        str(node["id"])
        for node in nodes
        if str(node.get("name", "")) in RETIRED_ALGORITHM_NAMES
    }
    children: dict[str, list[str]] = defaultdict(list)
    for edge in graph.get("edges", []):
        if isinstance(edge, dict) and edge.get("type") == "part_of":
            children[str(edge.get("target", ""))].append(str(edge.get("source", "")))
    removed = set(seeds)
    pending = list(seeds)
    while pending:
        parent = pending.pop()
        for child in children.get(parent, []):
            if child not in removed:
                removed.add(child)
                pending.append(child)
    return removed


def update_graph(graph: dict[str, Any], generated_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
    copied = json.loads(json.dumps(graph, ensure_ascii=False))
    removed_nodes = algorithm_subtree_ids(copied)
    before_nodes = len(copied.get("nodes", []))
    before_edges = len(copied.get("edges", []))
    copied["nodes"] = [
        node for node in copied.get("nodes", [])
        if isinstance(node, dict)
        and str(node.get("id", "")) not in removed_nodes
        and str(node.get("id", "")) not in RETRACTED_NODE_IDS
    ]
    existing_retracted = {
        str(edge.get("id", ""))
        for edge in copied.get("edges", [])
        if isinstance(edge, dict) and str(edge.get("id", "")) in RETRACTED_EDGE_IDS
    }
    if existing_retracted != RETRACTED_EDGE_IDS:
        missing = sorted(RETRACTED_EDGE_IDS - existing_retracted)
        raise ValueError(f"待撤回关系不在正式源图谱中：{missing}")
    copied["edges"] = [
        edge for edge in copied.get("edges", [])
        if isinstance(edge, dict)
        and str(edge.get("source", "")) not in removed_nodes
        and str(edge.get("target", "")) not in removed_nodes
        and str(edge.get("source", "")) not in RETRACTED_NODE_IDS
        and str(edge.get("target", "")) not in RETRACTED_NODE_IDS
        and str(edge.get("id", "")) not in RETRACTED_EDGE_IDS
    ]

    course_nodes = [node for node in copied["nodes"] if node.get("id") == "course_uml"]
    if len(course_nodes) != 1:
        raise ValueError("正式源图谱缺少唯一的 course_uml 节点。")
    uml = course_nodes[0]
    uml["name"] = "uml建模设计与分析"
    aliases = [str(item) for item in uml.get("aliases", []) if str(item).strip()]
    if "UML 面向对象分析与设计" not in aliases:
        aliases.append("UML 面向对象分析与设计")
    uml["aliases"] = aliases
    uml["description"] = "uml建模设计与分析课程的知识树根节点"
    root_nodes = [node for node in copied["nodes"] if node.get("id") == "programming_domain_root"]
    if len(root_nodes) != 1:
        raise ValueError("正式源图谱缺少唯一的编程领域根节点。")
    # “程序设计”已经作为题目能力节点出现，不能再同时作为根节点别名。
    root_nodes[0]["aliases"] = [
        value for value in root_nodes[0].get("aliases", []) if str(value) != "程序设计"
    ]
    for edge in copied["edges"]:
        if edge.get("type") == "assesses":
            edge["mapping_status"] = "approved"

    copied["schema_version"] = "programming_kg_course_centered_v13_release"
    metadata = copied.setdefault("metadata", {})
    metadata["release"] = {
        "version": VERSION,
        "generated_at": generated_at,
        "source_graph": "course_centered_v12_with_questions/standard_graph.json",
        "catalog_version": "programming_curriculum_v0_14_delivery",
        "question_bank_version": "formal_precise_questions_v1",
        "retired_algorithm_subtree_node_ids": sorted(removed_nodes),
        "retracted_relation_ids": sorted(RETRACTED_EDGE_IDS),
        "retracted_orphan_node_ids": sorted(RETRACTED_NODE_IDS),
        "uml_course_name": "uml建模设计与分析",
        "uml_aliases": ["UML 面向对象分析与设计"],
    }
    metadata["excluded_course"] = "算法设计与分析"
    change_summary = {
        "removed_nodes": before_nodes - len(copied["nodes"]),
        "removed_algorithm_edges": before_edges - len(graph.get("edges", [])) + len(copied["edges"]) - len(copied["edges"]),
        "retracted_relation_count": len(RETRACTED_EDGE_IDS),
        "node_count": len(copied["nodes"]),
        "edge_count": len(copied["edges"]),
    }
    # The exact removed edge count is clearer when calculated against the source.
    change_summary["removed_total_edges"] = before_edges - len(copied["edges"])
    return copied, change_summary


def validate_release(graph: dict[str, Any], questions: list[dict[str, Any]], mappings: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    node_ids = [str(node.get("id", "")) for node in nodes]
    edge_ids = [str(edge.get("id", "")) for edge in edges]
    node_set = set(node_ids)
    invalid_edges = [str(edge.get("id", "")) for edge in edges if str(edge.get("source", "")) not in node_set or str(edge.get("target", "")) not in node_set]
    self_loops = [str(edge.get("id", "")) for edge in edges if edge.get("source") == edge.get("target")]
    question_ids = {str(question.get("question_id", "")) for question in questions}
    mapping_by_id = {str(item.get("question_id", "")): item for item in mappings if isinstance(item, dict)}
    invalid_links: list[dict[str, str]] = []
    mapped_questions: set[str] = set()
    for question_id, record in mapping_by_id.items():
        for link in record.get("links", []):
            if not isinstance(link, dict):
                invalid_links.append({"question_id": question_id, "reason": "非对象映射"})
                continue
            target = str(link.get("knowledge_node_id", ""))
            if target not in node_set:
                invalid_links.append({"question_id": question_id, "knowledge_node_id": target})
            else:
                mapped_questions.add(question_id)
    answer_missing = [str(question.get("question_id", "")) for question in questions if not str(question.get("answer", "")).strip()]
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if source in node_set and target in node_set:
            adjacency[source].add(target)
            adjacency[target].add(source)
    connected = {"programming_domain_root"}
    pending = ["programming_domain_root"]
    while pending:
        node_id = pending.pop()
        for neighbor in adjacency.get(node_id, set()):
            if neighbor not in connected:
                connected.add(neighbor)
                pending.append(neighbor)
    errors = {
        "duplicate_node_ids": sorted({item for item in node_ids if node_ids.count(item) > 1}),
        "duplicate_edge_ids": sorted({item for item in edge_ids if edge_ids.count(item) > 1}),
        "invalid_edges": invalid_edges,
        "self_loops": self_loops,
        "invalid_node_ids_in_question_links": invalid_links,
        "unmapped_questions": sorted(question_ids - mapped_questions),
        "empty_answer_questions": answer_missing,
        "disconnected_node_ids": sorted(node_set - connected),
    }
    return {
        "passed": not any(errors.values()),
        "nodes": len(nodes),
        "edges": len(edges),
        "questions": len(questions),
        "mapping_records": len(mappings),
        "valid_mapping_links": sum(len(record.get("links", [])) for record in mappings if isinstance(record, dict)) - len(invalid_links),
        "errors": errors,
        "node_type_counts": dict(sorted(Counter(str(node.get("type", "")) for node in nodes).items())),
        "edge_type_counts": dict(sorted(Counter(str(edge.get("type", "")) for edge in edges).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="发布唯一的正式课程知识图谱版本。")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--generated-at",
        help="固定发布生成时间（ISO 8601）；省略时使用当前 UTC 时间。",
    )
    args = parser.parse_args()

    generated_at = args.generated_at or datetime.now(timezone.utc).isoformat()
    source_graph = load_json(args.graph)
    questions = load_json(args.questions)
    mappings = load_json(args.mappings)
    if not isinstance(questions, list) or not isinstance(mappings, list):
        raise ValueError("题库和映射文件顶层必须是数组。")
    # A release never exposes provisional mapping status.  The original files
    # remain untouched as review provenance; the versioned copy is approved.
    mappings = json.loads(json.dumps(mappings, ensure_ascii=False))
    for record in mappings:
        if isinstance(record, dict):
            record["release_status"] = "approved"
            for link in record.get("links", []):
                if isinstance(link, dict):
                    link["mapping_status"] = "approved"
    graph, changes = update_graph(source_graph, generated_at)
    audit = validate_release(graph, questions, mappings)
    if not audit["passed"]:
        raise ValueError(f"发布前一致性校验失败：{audit['errors']}")

    output = args.output_dir
    graph_path = output / f"standard_graph_{VERSION}.json"
    questions_path = output / f"questions_{VERSION}.json"
    mappings_path = output / f"question_knowledge_links_{VERSION}.json"
    audit_path = output / "release_consistency_report.json"
    atomic_write_json(graph_path, graph)
    atomic_write_json(questions_path, questions)
    atomic_write_json(mappings_path, mappings)
    audit.update({"generated_at": generated_at, "version": VERSION, "changes": changes})
    atomic_write_json(audit_path, audit)
    manifest = {
        "release_version": VERSION,
        "generated_at": generated_at,
        "producer": "publish_formal_release.py",
        "source_versions": {
            "graph": str(args.graph.resolve()),
            "questions": str(args.questions.resolve()),
            "mappings": str(args.mappings.resolve()),
            "catalog": "programming_curriculum_v0_14_delivery",
        },
        "artifacts": {
            "graph": {"file": graph_path.name, "sha256": sha256(graph_path), "nodes": audit["nodes"], "edges": audit["edges"]},
            "questions": {"file": questions_path.name, "sha256": sha256(questions_path), "questions": audit["questions"]},
            "mappings": {"file": mappings_path.name, "sha256": sha256(mappings_path), "mapping_records": audit["mapping_records"], "valid_mapping_links": audit["valid_mapping_links"]},
            "consistency_report": {"file": audit_path.name, "sha256": sha256(audit_path)},
        },
        "compatibility": {
            "api_and_frontend_must_load_from_manifest": True,
            "neo4j_import_must_use_graph_artifact": graph_path.name,
            "legacy_snapshots_are_not_formal_release": True,
        },
    }
    atomic_write_json(output / "release_manifest.json", manifest)
    print(f"正式发布版本：{VERSION}")
    print(f"节点数量：{audit['nodes']}")
    print(f"关系数量：{audit['edges']}")
    print(f"正式题目数：{audit['questions']}")
    print(f"有效题目映射：{audit['valid_mapping_links']}")
    print(f"正式图谱：{graph_path}")
    print(f"发布清单：{output / 'release_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
