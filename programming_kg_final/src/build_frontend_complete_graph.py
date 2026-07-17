"""生成包含课程、习题及映射关系的前端完整 standard_graph.json。"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_GRAPH = (
    BASE_DIR
    / "output/programming_kg/course_centered_v12_candidate_finalized/standard_graph.json"
)
DEFAULT_QUESTIONS = (
    BASE_DIR
    / "output/programming_kg/questions/unified_v1_review/formal_precise_questions.json"
)
DEFAULT_MAPPINGS = (
    BASE_DIR
    / "output/programming_kg/questions/unified_v1_review/formal_precise_question_knowledge_links.json"
)
DEFAULT_OUTPUT = (
    BASE_DIR
    / "output/programming_kg/course_centered_v12_with_questions/standard_graph.json"
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def display_name(question: dict[str, Any]) -> str:
    stem = " ".join(str(question.get("stem", "")).split())
    if len(stem) > 38:
        stem = stem[:37] + "…"
    return f"{question.get('type_label', '习题')}：{stem}"


def make_edge(
    source: str,
    target: str,
    relation_type: str,
    relation_name: str,
    **properties: Any,
) -> dict[str, Any]:
    edge = {
        "id": stable_id("edge", f"{source}|{relation_type}|{target}"),
        "source": source,
        "target": target,
        "type": relation_type,
        "relation_name": relation_name,
        "neo4j_type": relation_name,
        "confidence": float(properties.pop("confidence", 1.0)),
        "evidence": str(properties.pop("evidence", "")),
        "sources": properties.pop("sources", []),
    }
    edge.update(properties)
    return edge


def question_node(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(question["question_id"]),
        "name": display_name(question),
        "type": "Question",
        "aliases": [],
        "description": str(question.get("stem", "")),
        "confidence": float(question.get("answer_confidence", 1.0)),
        "course_id": str(question.get("course_id", "")),
        "question_type": str(question.get("type", "")),
        "type_label": str(question.get("type_label", "")),
        "language": str(question.get("language", "")),
        "stem": str(question.get("stem", "")),
        "code": str(question.get("code", "")),
        "options": question.get("options", []),
        "answer": str(question.get("answer", "")),
        "analysis": str(question.get("analysis", "")),
        "difficulty": int(question.get("difficulty", 2)),
        "difficulty_label": str(question.get("difficulty_label", "")),
        "abilities": question.get("abilities", []),
        "answer_source": str(question.get("answer_source", "")),
        "answer_kind": str(question.get("answer_kind", "")),
        "answer_status": str(question.get("answer_status", "")),
        "answer_pairing": question.get("answer_pairing", {}),
        "source": question.get("source", {}),
        "source_occurrences": question.get("source_occurrences", []),
        "sources": question.get("source_occurrences", []),
    }


def metadata_node(node_id: str, name: str, node_type: str) -> dict[str, Any]:
    return {
        "id": node_id,
        "name": name,
        "type": node_type,
        "aliases": [],
        "description": f"习题层{node_type}：{name}",
        "confidence": 1.0,
        "sources": [],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="构建前端完整 standard_graph.json。")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    graph = deepcopy(load_json(args.graph))
    questions = load_json(args.questions)
    mappings = load_json(args.mappings)
    if not isinstance(questions, list) or not isinstance(mappings, list):
        raise ValueError("questions 和 mappings 顶层必须是数组。")

    base_node_count = len(graph["nodes"])
    base_edge_count = len(graph["edges"])
    base_node_ids = {node["id"] for node in graph["nodes"]}
    mapping_by_id = {record["question_id"]: record for record in mappings}

    type_ids: dict[str, str] = {}
    difficulty_ids: dict[str, str] = {}
    ability_ids: dict[str, str] = {}
    added_nodes: list[dict[str, Any]] = []
    added_edges: list[dict[str, Any]] = []

    for question in questions:
        question_id = str(question["question_id"])
        added_nodes.append(question_node(question))

        type_label = str(question.get("type_label", "")).strip()
        type_id = type_ids.setdefault(
            type_label, stable_id("question_type", type_label)
        )
        difficulty_label = str(question.get("difficulty_label", "")).strip()
        difficulty_id = difficulty_ids.setdefault(
            difficulty_label, stable_id("question_difficulty", difficulty_label)
        )
        added_edges.append(
            make_edge(question_id, type_id, "has_type", "题型")
        )
        added_edges.append(
            make_edge(question_id, difficulty_id, "has_difficulty", "具有难度")
        )
        for ability in question.get("abilities", []):
            ability_name = str(ability).strip()
            if not ability_name:
                continue
            ability_id = ability_ids.setdefault(
                ability_name, stable_id("question_ability", ability_name)
            )
            added_edges.append(
                make_edge(question_id, ability_id, "requires_ability", "需要能力")
            )

        record = mapping_by_id.get(question_id)
        if record is None:
            raise ValueError(f"题目缺少映射记录：{question_id}")
        for link in record.get("links", []):
            target_id = str(link["knowledge_node_id"])
            if target_id not in base_node_ids:
                raise ValueError(f"映射目标不存在：{question_id} -> {target_id}")
            if link.get("knowledge_type") != "KnowledgePoint":
                raise ValueError(f"正式映射目标不是 KnowledgePoint：{target_id}")
            added_edges.append(
                make_edge(
                    question_id,
                    target_id,
                    "assesses",
                    "考察",
                    confidence=link.get("confidence", 0.0),
                    evidence=link.get("evidence", ""),
                    role=link.get("role", "secondary"),
                    role_weight=link.get("role_weight", 0.0),
                    rank=link.get("rank", 0),
                    mapping_status=link.get("mapping_status", ""),
                )
            )

    added_nodes.extend(
        metadata_node(node_id, name, "QuestionType")
        for name, node_id in sorted(type_ids.items())
    )
    added_nodes.extend(
        metadata_node(node_id, name, "Difficulty")
        for name, node_id in sorted(difficulty_ids.items())
    )
    added_nodes.extend(
        metadata_node(node_id, name, "QuestionAbility")
        for name, node_id in sorted(ability_ids.items())
    )

    graph["nodes"].extend(added_nodes)
    graph["edges"].extend(added_edges)
    display_names = graph.setdefault("schema", {}).setdefault(
        "relationship_display_names", {}
    )
    display_names.update(
        {
            "assesses": "考察",
            "has_type": "题型",
            "has_difficulty": "具有难度",
            "requires_ability": "需要能力",
        }
    )
    graph["schema_version"] = "programming_kg_course_centered_v12_questions_v1"
    graph.setdefault("metadata", {})["question_layer"] = {
        "source": str(args.questions.resolve()),
        "question_count": len(questions),
        "assesses_relation_count": sum(
            len(record.get("links", [])) for record in mappings
        ),
        "question_type_count": len(type_ids),
        "difficulty_count": len(difficulty_ids),
        "question_ability_count": len(ability_ids),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    node_ids = [node["id"] for node in graph["nodes"]]
    edge_ids = [edge["id"] for edge in graph["edges"]]
    all_node_ids = set(node_ids)
    invalid_edges = [
        edge["id"]
        for edge in graph["edges"]
        if edge["source"] not in all_node_ids or edge["target"] not in all_node_ids
    ]
    question_ids = {question["question_id"] for question in questions}
    mapped_question_ids = {
        edge["source"] for edge in added_edges if edge["type"] == "assesses"
    }
    empty_answer_ids = [
        question["question_id"]
        for question in questions
        if not str(question.get("answer", "")).strip()
    ]
    errors = {
        "duplicate_node_ids": sorted(
            {node_id for node_id in node_ids if node_ids.count(node_id) > 1}
        ),
        "duplicate_edge_ids": sorted(
            {edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1}
        ),
        "invalid_edges": invalid_edges,
        "questions_without_assesses": sorted(question_ids - mapped_question_ids),
        "empty_answer_questions": empty_answer_ids,
    }
    if any(errors.values()):
        raise ValueError(f"完整图谱校验失败：{errors}")

    atomic_write_json(args.output, graph)
    report = {
        "schema_version": "frontend_complete_graph_audit_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": True,
        "base": {"nodes": base_node_count, "edges": base_edge_count},
        "added": {
            "nodes": len(added_nodes),
            "edges": len(added_edges),
            "questions": len(questions),
            "assesses": sum(edge["type"] == "assesses" for edge in added_edges),
        },
        "final": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])},
        "errors": errors,
        "output": str(args.output.resolve()),
    }
    report_path = args.output.with_name("frontend_complete_graph_audit.json")
    atomic_write_json(report_path, report)
    print(f"课程基础节点：{base_node_count}，基础关系：{base_edge_count}")
    print(f"新增习题层节点：{len(added_nodes)}，新增关系：{len(added_edges)}")
    print(f"完整节点：{len(graph['nodes'])}，完整关系：{len(graph['edges'])}")
    print(f"完整图谱：{args.output}")
    print(f"质量校验通过：True")
    print(f"校验报告：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
