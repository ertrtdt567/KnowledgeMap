"""核验 Neo4j 中正式习题层是否与输入 JSON 完全一致。"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def expected_pairs(mappings: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (str(record["question_id"]), str(link["knowledge_node_id"]))
        for record in mappings
        for link in record.get("links", [])
        if isinstance(link, dict)
    }


def find_cypher_shell() -> Path:
    configured = os.getenv("NEO4J_CYPHER_SHELL", "").strip()
    if configured and Path(configured).is_file():
        return Path(configured)
    candidates = sorted(
        (Path.home() / ".Neo4jDesktop2" / "Data" / "dbmss").glob(
            "*/bin/cypher-shell.bat"
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("未找到 neo4j Python 驱动或 Neo4j Desktop cypher-shell。")
    return candidates[0]


def run_shell_query(
    shell: Path,
    uri: str,
    user: str,
    password: str,
    database: str,
    query: str,
) -> list[dict[str, str]]:
    result = subprocess.run(
        [
            str(shell),
            "-a",
            uri,
            "-u",
            user,
            "-p",
            password,
            "-d",
            database,
            "--format",
            "plain",
            query,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "cypher-shell 查询失败。")
    return list(csv.DictReader(io.StringIO(result.stdout), skipinitialspace=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="核验 Neo4j 正式习题层。")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--links", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password-env", default="NEO4J_PASSWORD")
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--expected-knowledge-nodes", type=int, default=2560)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    password = os.getenv(args.password_env, "").strip()
    if not password:
        raise RuntimeError(f"未找到环境变量 {args.password_env}。")

    questions = load_json(args.questions)
    mappings = load_json(args.links)
    expected_question_ids = {str(item["question_id"]) for item in questions}
    expected_assesses = expected_pairs(mappings)

    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError:
        GraphDatabase = None

    if GraphDatabase is not None:
        driver = GraphDatabase.driver(args.uri, auth=(args.user, password))
        try:
            with driver.session(database=args.database) as session:
                knowledge_node_count = session.run(
                    "MATCH (n:KnowledgeNode) RETURN count(n) AS count"
                ).single()["count"]
                actual_question_ids = {
                    record["id"]
                    for record in session.run("MATCH (q:Question) RETURN q.id AS id")
                }
                assesses_rows = list(
                    session.run(
                        "MATCH (q:Question)-[r:`考察`]->(k:KnowledgeNode) "
                        "RETURN q.id AS question_id, k.id AS knowledge_id, "
                        "k.type AS knowledge_type, count(r) AS copies"
                    )
                )
                orphan_questions = [
                    record["id"]
                    for record in session.run(
                        "MATCH (q:Question) WHERE NOT (q)-[:`考察`]->() "
                        "RETURN q.id AS id ORDER BY id"
                    )
                ]
                empty_answers = [
                    record["id"]
                    for record in session.run(
                        "MATCH (q:Question) WHERE trim(coalesce(q.answer, '')) = '' "
                        "RETURN q.id AS id ORDER BY id"
                    )
                ]
        finally:
            driver.close()
    else:
        shell = find_cypher_shell()
        query = lambda text: run_shell_query(
            shell, args.uri, args.user, password, args.database, text
        )
        knowledge_node_count = int(
            query("MATCH (n:KnowledgeNode) RETURN count(n) AS count;")[0]["count"]
        )
        actual_question_ids = {
            row["id"] for row in query("MATCH (q:Question) RETURN q.id AS id;")
        }
        assesses_rows = query(
            "MATCH (q:Question)-[r:`考察`]->(k:KnowledgeNode) "
            "RETURN q.id AS question_id, k.id AS knowledge_id, "
            "k.type AS knowledge_type, count(r) AS copies;"
        )
        for row in assesses_rows:
            row["copies"] = int(row["copies"])
        orphan_questions = [
            row["id"]
            for row in query(
                "MATCH (q:Question) WHERE NOT (q)-[:`考察`]->() "
                "RETURN q.id AS id ORDER BY id;"
            )
        ]
        empty_answers = [
            row["id"]
            for row in query(
                "MATCH (q:Question) WHERE trim(coalesce(q.answer, '')) = '' "
                "RETURN q.id AS id ORDER BY id;"
            )
        ]

    actual_assesses = {
        (row["question_id"], row["knowledge_id"]) for row in assesses_rows
    }
    duplicate_assesses = [
        {
            "question_id": row["question_id"],
            "knowledge_id": row["knowledge_id"],
            "copies": row["copies"],
        }
        for row in assesses_rows
        if row["copies"] != 1
    ]
    non_point_targets = [
        {
            "question_id": row["question_id"],
            "knowledge_id": row["knowledge_id"],
            "knowledge_type": row["knowledge_type"],
        }
        for row in assesses_rows
        if row["knowledge_type"] != "KnowledgePoint"
    ]

    errors = {
        "missing_questions": sorted(expected_question_ids - actual_question_ids),
        "unexpected_questions": sorted(actual_question_ids - expected_question_ids),
        "missing_assesses": sorted(expected_assesses - actual_assesses),
        "unexpected_assesses": sorted(actual_assesses - expected_assesses),
        "duplicate_assesses": duplicate_assesses,
        "non_knowledge_point_targets": non_point_targets,
        "orphan_questions": orphan_questions,
        "empty_answers": empty_answers,
        "knowledge_node_count_mismatch": (
            []
            if knowledge_node_count == args.expected_knowledge_nodes
            else [
                {
                    "expected": args.expected_knowledge_nodes,
                    "actual": knowledge_node_count,
                }
            ]
        ),
    }
    passed = not any(errors.values())
    report = {
        "schema_version": "neo4j_precise_question_import_audit_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "counts": {
            "knowledge_nodes": knowledge_node_count,
            "questions": len(actual_question_ids),
            "assesses_relations": len(actual_assesses),
        },
        "errors": errors,
    }
    atomic_write_json(args.output, report)
    print(f"KnowledgeNode：{knowledge_node_count}")
    print(f"习题节点：{len(actual_question_ids)}")
    print(f"考察关系：{len(actual_assesses)}")
    print(f"数据库级核验通过：{passed}")
    print(f"核验报告：{args.output}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
