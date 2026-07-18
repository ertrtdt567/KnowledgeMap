"""Execute the formal RDF count query and persist its result.

RDFLib is used when available.  For an offline delivery machine without
RDFLib, the script falls back to a transparent, standard-library evaluator
that supports only the exact COUNT query shipped with this release.  The
result records the engine so the restricted fallback is never presented as a
general-purpose SPARQL implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_IRI = "https://github.com/ertrtdt567/KnowledgeMap/kg/v2026.07.18/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def validate_supported_query(query: str) -> None:
    normalized = " ".join(query.lower().split())
    required = (
        "count(distinct ?node)",
        "count(distinct ?edge)",
        "?node kg:nodeid ?nodeid",
        "?edge rdf:type type:relationship",
    )
    missing = [item for item in required if item not in normalized]
    if missing:
        raise ValueError(
            "标准库回退执行器只支持发布包中的节点/关系计数查询；"
            f"当前查询缺少模式：{missing}"
        )


def execute_with_rdflib(rdf_path: Path, query: str) -> tuple[str, int, int]:
    from rdflib import Graph  # type: ignore

    graph = Graph()
    graph.parse(rdf_path, format="xml")
    rows = list(graph.query(query))
    if len(rows) != 1 or len(rows[0]) != 2:
        raise ValueError(f"SPARQL 返回形状异常：rows={len(rows)}")
    return "RDFLib SPARQL", int(rows[0][0]), int(rows[0][1])


def execute_limited_count(rdf_path: Path, query: str) -> tuple[str, int, int]:
    validate_supported_query(query)
    root = ET.parse(rdf_path).getroot()
    node_subjects: set[str] = set()
    edge_subjects: set[str] = set()
    relationship_type = BASE_IRI + "type/Relationship"

    for item in root.findall(f"{{{RDF}}}Description"):
        subject = item.attrib.get(f"{{{RDF}}}about", "")
        if not subject:
            continue
        if item.find(f"{{{BASE_IRI}}}nodeId") is not None:
            node_subjects.add(subject)
        if any(
            child.tag == f"{{{RDF}}}type"
            and child.attrib.get(f"{{{RDF}}}resource") == relationship_type
            for child in item
        ):
            edge_subjects.add(subject)

    return (
        "stdlib limited SPARQL COUNT evaluator v1 (release query only)",
        len(node_subjects),
        len(edge_subjects),
    )


def execute(rdf_path: Path, query: str) -> tuple[str, int, int]:
    try:
        return execute_with_rdflib(rdf_path, query)
    except ModuleNotFoundError:
        return execute_limited_count(rdf_path, query)


def main() -> int:
    parser = argparse.ArgumentParser(description="执行正式 RDF 的 SPARQL 计数验证。")
    parser.add_argument("--rdf", type=Path, required=True, help="RDF/XML 文件")
    parser.add_argument("--query", type=Path, required=True, help="SPARQL 查询文件")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--expected-nodes", type=int, required=True)
    parser.add_argument("--expected-edges", type=int, required=True)
    args = parser.parse_args()

    query_text = args.query.read_text(encoding="utf-8")
    engine, node_count, relationship_count = execute(args.rdf, query_text)
    passed = (
        node_count == args.expected_nodes
        and relationship_count == args.expected_edges
    )
    result: dict[str, Any] = {
        "schema_version": "rdf_sparql_execution_result_v1",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "engine": engine,
        "scope": "validate_counts.sparql only",
        "rdf_file": str(args.rdf.resolve()),
        "rdf_sha256": sha256(args.rdf),
        "query_file": str(args.query.resolve()),
        "query_sha256": sha256(args.query),
        "query": query_text,
        "bindings": {
            "node_count": node_count,
            "relationship_count": relationship_count,
        },
        "expected": {
            "node_count": args.expected_nodes,
            "relationship_count": args.expected_edges,
        },
        "passed": passed,
    }
    atomic_write(
        args.output_json,
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write(
        args.output_md,
        "\n".join(
            [
                "# SPARQL 实际执行结果",
                "",
                f"- 执行时间（UTC）：{result['executed_at']}",
                f"- 执行引擎：{engine}",
                f"- RDF SHA256：`{result['rdf_sha256']}`",
                f"- 查询 SHA256：`{result['query_sha256']}`",
                f"- `node_count`：{node_count}",
                f"- `relationship_count`：{relationship_count}",
                f"- 与正式 JSON 计数一致：{passed}",
                "",
                "## 查询",
                "",
                "```sparql",
                query_text.rstrip(),
                "```",
                "",
                "说明：若执行引擎显示为 `stdlib limited`，表示本机未安装 RDFLib，",
                "本次实际执行的是随发布包提供的计数查询，不代表支持任意 SPARQL。",
            ]
        )
        + "\n",
    )
    print(f"SPARQL 引擎：{engine}")
    print(f"节点：{node_count}，关系：{relationship_count}")
    print(f"验证通过：{passed}")
    print(f"结果 JSON：{args.output_json}")
    print(f"结果报告：{args.output_md}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
