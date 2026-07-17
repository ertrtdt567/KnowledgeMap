"""Rebase verified questions from legacy catalog IDs to course-local node IDs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LANGUAGE_TO_COURSE = {
    "java": "course_java",
    "python": "course_python",
    "c++": "course_cpp",
    "cpp": "course_cpp",
    "数据结构": "course_data_structures",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def legacy_catalog_id(node_id: str) -> str:
    prefix = "curriculum_"
    return node_id[len(prefix):] if node_id.startswith(prefix) else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将已验证题目映射迁移到课程本地知识节点。")
    parser.add_argument("--questions", default="work/oop_kg_demo/output/programming_kg/questions/combined_official_questions.json")
    parser.add_argument("--links", default="work/oop_kg_demo/output/programming_kg/question_mapping/question_knowledge_links.json")
    parser.add_argument("--graph", default="work/oop_kg_demo/output/programming_kg/course_centered_v8/standard_graph.json")
    parser.add_argument("--output", default="work/oop_kg_demo/output/programming_kg/course_centered_v8/question_knowledge_links.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    questions = {str(item.get("question_id", "")): item for item in load_json(Path(args.questions)) if isinstance(item, dict)}
    legacy_links = [item for item in load_json(Path(args.links)) if isinstance(item, dict)]
    graph = load_json(Path(args.graph))
    graph_nodes = {str(item.get("id", "")): item for item in graph.get("nodes", []) if isinstance(item, dict)}

    rebased: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for record in legacy_links:
        question_id = str(record.get("question_id", ""))
        question = questions.get(question_id)
        language = str((question or {}).get("language", "")).strip().casefold()
        course_id = LANGUAGE_TO_COURSE.get(language)
        if not course_id:
            unresolved.append({"question_id": question_id, "reason": "题目未声明可确定的课程/语言范围。"})
            continue

        copied = dict(record)
        copied_links: list[dict[str, Any]] = []
        for link in record.get("links", []):
            if not isinstance(link, dict):
                continue
            catalog_id = legacy_catalog_id(str(link.get("knowledge_node_id", "")))
            local_id = f"{course_id}__curriculum_{catalog_id}" if catalog_id else ""
            # SyntaxRule and similar non-catalog nodes keep their old local
            # identifier after the course prefix; this is an ID migration, not
            # a semantic guess.
            if not local_id:
                local_id = f"{course_id}__{str(link.get('knowledge_node_id', ''))}"
            local_node = graph_nodes.get(local_id)
            if not local_node:
                unresolved.append(
                    {
                        "question_id": question_id,
                        "legacy_knowledge_node_id": link.get("knowledge_node_id", ""),
                        "expected_course_id": course_id,
                        "reason": "课程树中不存在该知识点，不能猜测替代节点。",
                    }
                )
                continue
            rebased_link = dict(link)
            rebased_link["knowledge_node_id"] = local_id
            rebased_link["knowledge_name"] = local_node.get("name", rebased_link.get("knowledge_name", ""))
            rebased_link["knowledge_type"] = local_node.get("type", rebased_link.get("knowledge_type", ""))
            rebased_link["course_id"] = course_id
            copied_links.append(rebased_link)
        copied["links"] = copied_links
        copied["course_id"] = course_id
        copied["mapping_schema"] = "course_centered_v8"
        rebased.append(copied)

    payload = {
        "schema_version": "question_mapping_course_centered_v8",
        "links": rebased,
        "unresolved": unresolved,
        "summary": {
            "question_count": len(questions),
            "mapped_question_count": sum(1 for item in rebased if item.get("links")),
            "link_count": sum(len(item.get("links", [])) for item in rebased),
            "unresolved_count": len(unresolved),
        },
    }
    write_json(Path(args.output), payload)
    print(f"迁移题目数：{payload['summary']['mapped_question_count']}")
    print(f"迁移关系数：{payload['summary']['link_count']}")
    print(f"待复核数：{payload['summary']['unresolved_count']}")
    print(f"映射结果：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
