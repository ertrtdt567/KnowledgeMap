"""
第五阶段 D：习题节点与习题关系入 Neo4j。

它读取：
    output/question_mapping/questions.json
    output/question_mapping/question_knowledge_links.json

生成：
    output/neo4j_import/import_questions.cypher
    output/neo4j_import/demo_question_queries.cypher
    output/neo4j_import/question_import_report.json

默认只生成 Cypher 文件；加 --execute 后会直连 Neo4j 自动导入。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_QUESTIONS = "work/oop_kg_demo/output/programming_kg/questions/official_questions.json"
DEFAULT_LINKS = "work/oop_kg_demo/output/programming_kg/question_mapping/question_knowledge_links.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/programming_kg/neo4j_import"


@dataclass
class ImportFiles:
    import_cypher: Path
    demo_queries: Path
    report: Path


class QuestionCypherBuilder:
    """把标准习题和映射关系转换成 Cypher。"""

    def __init__(self, questions: list[dict[str, Any]], mappings: list[dict[str, Any]], clear_question_layer: bool) -> None:
        self.questions = questions
        self.mappings = mappings
        self.clear_question_layer = clear_question_layer
        self.mapping_by_id = {item.get("question_id"): item for item in mappings if isinstance(item, dict)}

    def build_import_statements(self) -> list[str]:
        statements = [
            "CREATE CONSTRAINT question_id IF NOT EXISTS\nFOR (q:Question)\nREQUIRE q.id IS UNIQUE",
            "CREATE CONSTRAINT ability_name IF NOT EXISTS\nFOR (a:Ability)\nREQUIRE a.name IS UNIQUE",
            "CREATE CONSTRAINT difficulty_name IF NOT EXISTS\nFOR (d:Difficulty)\nREQUIRE d.name IS UNIQUE",
            "CREATE CONSTRAINT question_type_name IF NOT EXISTS\nFOR (t:QuestionType)\nREQUIRE t.name IS UNIQUE",
        ]
        if self.clear_question_layer:
            statements.extend(
                [
                    "MATCH (q:Question) DETACH DELETE q",
                    "MATCH (a:Ability) DETACH DELETE a",
                    "MATCH (d:Difficulty) DETACH DELETE d",
                    "MATCH (t:QuestionType) DETACH DELETE t",
                ]
            )

        for question in self.questions:
            statements.extend(self._question_statements(question))
        return statements

    def build_import_cypher_text(self) -> str:
        header = [
            "// 编程领域知识图谱：习题节点导入脚本",
            f"// 生成时间：{datetime.now().isoformat(timespec='seconds')}",
            "// 说明：先导入前四阶段的 KnowledgeNode 图谱，再执行本文件。",
            "",
        ]
        body = [statement + ";" for statement in self.build_import_statements()]
        return "\n\n".join(header + body) + "\n"

    def build_demo_queries_text(self) -> str:
        queries = [
            (
                "1. 查看习题-知识点整体网络",
                "MATCH p=(q:Question)-[:`考察`]->(k:KnowledgeNode)\nRETURN p\nLIMIT 100;",
            ),
            (
                "2. 查看某个知识点对应的习题",
                "MATCH p=(q:Question)-[r:`考察`]->(k:KnowledgeNode {name: '多态'})\nRETURN p\nLIMIT 50;",
            ),
            (
                "3. 查看一道题考察什么",
                "MATCH p=(q:Question {id: 'Q003'})-[r]->(n)\nRETURN p\nLIMIT 50;",
            ),
            (
                "4. 查询代码阅读题及其知识点",
                "MATCH p=(q:Question)-[:`题型`]->(:QuestionType {name: '代码阅读题'})\nMATCH p2=(q)-[:`考察`]->(:KnowledgeNode)\nRETURN p, p2\nLIMIT 80;",
            ),
            (
                "5. 查询中等难度题",
                "MATCH p=(q:Question)-[:`具有难度`]->(:Difficulty {name: '中等'})\nRETURN p\nLIMIT 80;",
            ),
            (
                "6. 按知识点统计习题数量",
                "MATCH (:Question)-[r:`考察`]->(k:KnowledgeNode)\nRETURN k.name AS knowledge, count(r) AS question_count\nORDER BY question_count DESC;",
            ),
            (
                "7. 按题型统计习题数量",
                "MATCH (q:Question)-[:`题型`]->(t:QuestionType)\nRETURN t.name AS type, count(q) AS question_count\nORDER BY question_count DESC;",
            ),
            (
                "8. 查看主考知识点关系",
                "MATCH p=(q:Question)-[r:`考察` {role: 'primary'}]->(k:KnowledgeNode)\nRETURN p\nLIMIT 80;",
            ),
        ]
        lines = [
            "// 编程领域知识图谱：习题 Demo 查询",
            f"// 生成时间：{datetime.now().isoformat(timespec='seconds')}",
            "",
        ]
        for title, query in queries:
            lines.append(f"// {title}")
            lines.append(query)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _question_statements(self, question: dict[str, Any]) -> list[str]:
        question_id = required_str(question, "question_id")
        props = normalize_question_properties(question)
        statements = [
            f"MERGE (q:Question {{id: {cypher_literal(question_id)}}})\nSET q += {cypher_map_literal(props)}",
            self._type_statement(question),
            self._difficulty_statement(question),
        ]
        for ability in question.get("abilities", []):
            ability_name = str(ability).strip()
            if ability_name:
                statements.append(self._ability_statement(question_id, ability_name))

        mapping = self.mapping_by_id.get(question_id, {})
        for link in mapping.get("links", []):
            if isinstance(link, dict):
                statements.append(self._knowledge_link_statement(question_id, link, str(mapping.get("method", ""))))
        return statements

    def _type_statement(self, question: dict[str, Any]) -> str:
        question_id = required_str(question, "question_id")
        type_name = str(question.get("type_label") or question.get("type") or "").strip()
        type_code = str(question.get("type", "")).strip()
        return (
            f"MATCH (q:Question {{id: {cypher_literal(question_id)}}})\n"
            f"MERGE (t:QuestionType {{name: {cypher_literal(type_name)}}})\n"
            f"SET t.code = {cypher_literal(type_code)}\n"
            "MERGE (q)-[r:`题型`]->(t)\nSET r.relation_code = 'has_type', r.relation_name = '题型'"
        )

    def _difficulty_statement(self, question: dict[str, Any]) -> str:
        question_id = required_str(question, "question_id")
        difficulty = int(question.get("difficulty", 2))
        label = str(question.get("difficulty_label", difficulty)).strip()
        return (
            f"MATCH (q:Question {{id: {cypher_literal(question_id)}}})\n"
            f"MERGE (d:Difficulty {{name: {cypher_literal(label)}}})\n"
            f"SET d.level = {difficulty}\n"
            "MERGE (q)-[r:`具有难度`]->(d)\nSET r.relation_code = 'has_difficulty', r.relation_name = '具有难度'"
        )

    def _ability_statement(self, question_id: str, ability_name: str) -> str:
        return (
            f"MATCH (q:Question {{id: {cypher_literal(question_id)}}})\n"
            f"MERGE (a:Ability {{name: {cypher_literal(ability_name)}}})\n"
            "MERGE (q)-[r:`需要能力`]->(a)\nSET r.relation_code = 'requires_ability', r.relation_name = '需要能力'"
        )

    def _knowledge_link_statement(self, question_id: str, link: dict[str, Any], mapping_method: str) -> str:
        knowledge_id = required_str(link, "knowledge_node_id")
        rel_id = f"question_link_{question_id}_{knowledge_id}"
        props = {
            "id": rel_id,
            "relation_code": "assesses",
            "relation_name": "考察",
            "role": str(link.get("role", "secondary")),
            "confidence": safe_float(link.get("confidence", 0.0)),
            "evidence": str(link.get("evidence", "")),
            "rank": int(link.get("rank", 0) or 0),
            "method": str(link.get("method") or mapping_method),
        }
        return (
            f"MATCH (q:Question {{id: {cypher_literal(question_id)}}})\n"
            f"MATCH (k:KnowledgeNode {{id: {cypher_literal(knowledge_id)}}})\n"
            f"MERGE (q)-[r:`考察` {{id: {cypher_literal(rel_id)}}}]->(k)\n"
            f"SET r += {cypher_map_literal(props)}"
        )


class Neo4jExecutor:
    """可选的 Neo4j 自动执行器。"""

    def __init__(self, uri: str, user: str, password: str, database: str | None) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database

    def execute(self, statements: list[str]) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except ImportError as exc:
            raise RuntimeError("当前 Python 环境没有安装 neo4j 驱动。可先使用生成的 import_questions.cypher。") from exc

        driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        try:
            with driver.session(database=self.database) if self.database else driver.session() as session:
                for statement in statements:
                    session.run(statement).consume()
        finally:
            driver.close()


def normalize_question_properties(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": required_str(question, "question_id"),
        "type": str(question.get("type", "")),
        "type_label": str(question.get("type_label", "")),
        "language": str(question.get("language", "")),
        "stem": str(question.get("stem", "")),
        "code": str(question.get("code", "")),
        "options": as_str_list(question.get("options", [])),
        "answer": str(question.get("answer", "")),
        "analysis": str(question.get("analysis", "")),
        "difficulty": int(question.get("difficulty", 2)),
        "difficulty_label": str(question.get("difficulty_label", "")),
        "abilities": as_str_list(question.get("abilities", [])),
        "gold_knowledge_points_json": json.dumps(question.get("gold_knowledge_points", []), ensure_ascii=False),
    }


def cypher_map_literal(props: dict[str, Any]) -> str:
    items = [f"{key}: {cypher_literal(value)}" for key, value in props.items()]
    if len(items) <= 3:
        return "{" + ", ".join(items) + "}"
    return "{\n  " + ",\n  ".join(items) + "\n}"


def cypher_literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(cypher_literal(item) for item in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def required_str(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"缺少必要字段：{key}")
    return value


def safe_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(number, 1.0))


def as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_report(
    questions_path: Path,
    links_path: Path,
    files: ImportFiles,
    questions: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    args: argparse.Namespace,
    execute_success: bool,
    errors: list[str],
) -> dict[str, Any]:
    link_count = sum(len(item.get("links", [])) for item in mappings if isinstance(item, dict))
    ability_names = sorted({ability for question in questions for ability in as_str_list(question.get("abilities", []))})
    difficulty_names = sorted({str(question.get("difficulty_label", "")) for question in questions})
    type_names = sorted({str(question.get("type_label", "")) for question in questions})
    return {
        "schema_version": "programming_kg_question_neo4j_import_v2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_questions": str(questions_path),
        "input_links": str(links_path),
        "generated_files": {
            "import_questions": str(files.import_cypher),
            "demo_question_queries": str(files.demo_queries),
            "report": str(files.report),
        },
        "question_count": len(questions),
        "assesses_relation_count": link_count,
        "ability_count": len(ability_names),
        "difficulty_count": len(difficulty_names),
        "question_type_count": len(type_names),
        "execute_enabled": bool(args.execute),
        "execute_success": execute_success,
        "clear_question_layer": bool(args.clear_question_layer),
        "neo4j": {
            "uri": args.uri,
            "user": args.user,
            "database": args.database or "default",
            "password_source": args.password_env,
        },
        "errors": errors,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第五阶段 D：习题节点与习题关系入 Neo4j。")
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS, help="标准习题 questions.json 路径")
    parser.add_argument("--links", default=DEFAULT_LINKS, help="映射结果 question_knowledge_links.json 路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Neo4j 导入产物输出目录")
    parser.add_argument("--execute", action="store_true", help="生成 Cypher 后连接 Neo4j 自动导入")
    parser.add_argument("--clear-question-layer", action="store_true", help="导入前清空 Question/Ability/Difficulty/QuestionType 层")
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"), help="Neo4j Bolt 地址")
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"), help="Neo4j 用户名")
    parser.add_argument("--password-env", default="NEO4J_PASSWORD", help="保存 Neo4j 密码的环境变量名")
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", ""), help="Neo4j 数据库名。留空使用默认库")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    questions_path = Path(args.questions)
    links_path = Path(args.links)
    output_dir = Path(args.output_dir)
    files = ImportFiles(
        import_cypher=output_dir / "import_questions.cypher",
        demo_queries=output_dir / "demo_question_queries.cypher",
        report=output_dir / "question_import_report.json",
    )

    questions = load_json(questions_path)
    mappings = load_json(links_path)
    if not isinstance(questions, list) or not isinstance(mappings, list):
        raise ValueError("questions 和 links 顶层都必须是数组。")

    builder = QuestionCypherBuilder(questions, mappings, clear_question_layer=args.clear_question_layer)
    statements = builder.build_import_statements()
    write_text(files.import_cypher, builder.build_import_cypher_text())
    write_text(files.demo_queries, builder.build_demo_queries_text())

    errors: list[str] = []
    execute_success = False
    if args.execute:
        password = os.getenv(args.password_env, "").strip()
        if not password:
            errors.append(f"未找到环境变量 {args.password_env}，无法连接 Neo4j。")
        else:
            try:
                executor = Neo4jExecutor(args.uri, args.user, password, args.database or None)
                executor.execute(statements)
                execute_success = True
            except Exception as exc:
                errors.append(str(exc))

    report = build_report(questions_path, links_path, files, questions, mappings, args, execute_success, errors)
    write_json(files.report, report)

    print(f"习题节点数量：{len(questions)}")
    print(f"考察关系数量：{report['assesses_relation_count']}")
    print(f"导入脚本：{files.import_cypher}")
    print(f"展示查询：{files.demo_queries}")
    print(f"入库报告：{files.report}")
    if args.execute:
        print("Neo4j 自动导入：成功" if execute_success else "Neo4j 自动导入：未成功，详情见 question_import_report.json")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

