"""从正式图谱导出 CodeExample 的标题与具体代码，供前端展示或单独检索。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_GRAPH = "work/oop_kg_demo/output/programming_kg/graph_hierarchy/standard_graph.json"
DEFAULT_OUTPUT = "work/oop_kg_demo/output/programming_kg/code_examples.json"
DEFAULT_REPORT = "work/oop_kg_demo/output/programming_kg/code_examples_report.json"


def as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def detect_language(node: dict[str, Any]) -> str:
    """优先使用节点来源中的语言线索，未识别时返回通用编程。"""
    source_text = " ".join(
        f"{source.get('source_file', '')} {source.get('content', '')}".lower()
        for source in as_dict_list(node.get("sources"))
    )
    if any(marker in source_text for marker in ["java", "system.out", "public class"]):
        return "Java"
    if any(marker in source_text for marker in ["python", "def ", "print("]):
        return "Python"
    if any(marker in source_text for marker in ["c++", "#include", "std::", "cout"]):
        return "C++"
    return "通用编程"


def export_examples(graph: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = graph.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("standard_graph.json 的 nodes 必须是数组。")

    examples: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict) or node.get("type") != "CodeExample":
            continue
        sources = as_dict_list(node.get("sources"))
        # CodeExample 目前由一个课程片段生成；仍兼容未来一个示例对应多个来源的情况。
        code_parts = [str(source.get("content", "")).strip() for source in sources if str(source.get("content", "")).strip()]
        code = "\n\n".join(dict.fromkeys(code_parts))
        examples.append(
            {
                "id": str(node.get("id", "")),
                "title": str(node.get("name", "")),
                "code": code,
                "language": detect_language(node),
                "source_chunk_ids": node.get("source_chunk_ids", []),
                "sources": [
                    {
                        "chunk_id": source.get("chunk_id"),
                        "source_file": source.get("source_file"),
                        "page": source.get("page"),
                        "evidence_location": source.get("evidence_location"),
                    }
                    for source in sources
                ],
            }
        )
    return sorted(examples, key=lambda item: item["title"])


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出 CodeExample 标题与代码。")
    parser.add_argument("--graph", default=DEFAULT_GRAPH, help="正式 standard_graph.json 路径")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="code_examples.json 输出路径")
    parser.add_argument("--report", default=DEFAULT_REPORT, help="导出报告输出路径")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    if not isinstance(graph, dict):
        raise ValueError("standard_graph.json 顶层必须是对象。")
    examples = export_examples(graph)
    if any(not item["title"] or not item["code"] for item in examples):
        raise ValueError("存在缺少标题或代码内容的 CodeExample，不能导出不完整记录。")

    language_counts = Counter(item["language"] for item in examples)
    write_json(Path(args.output), examples)
    write_json(
        Path(args.report),
        {
            "schema_version": "programming_kg_code_examples_v1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input_graph": args.graph,
            "output": args.output,
            "code_example_count": len(examples),
            "language_counts": dict(sorted(language_counts.items())),
            "validation": {
                "all_examples_have_title": all(bool(item["title"]) for item in examples),
                "all_examples_have_code": all(bool(item["code"]) for item in examples),
            },
        },
    )
    print(f"已导出 CodeExample 数量：{len(examples)}")
    print(f"代码文件：{args.output}")
    print(f"导出报告：{args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

