"""
第四阶段：Neo4j 图谱入库、Cypher 生成与 Demo 查询准备。

这一阶段接在 normalize_graph.py 后面：

    standard_graph.json
    -> 生成 import_graph.cypher
    -> 生成 demo_queries.cypher
    -> 可选：连接 Neo4j 自动执行导入
    -> 输出 neo4j_import_report.json

默认只生成 Cypher 文件，不强制连接 Neo4j。等 Neo4j Desktop 安装并启动后，
可以加 --execute 自动导入。
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


DEFAULT_INPUT_GRAPH = "work/oop_kg_demo/output/programming_kg/graph_hierarchy/standard_graph.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/programming_kg/neo4j_import"


@dataclass
class GeneratedFiles:
    """第四步生成的文件路径。"""

    import_cypher: Path
    demo_queries: Path
    report: Path


class Neo4jCypherBuilder:
    """把 standard_graph.json 转换成 Neo4j 可执行的 Cypher。"""

    def __init__(self, graph: dict[str, Any], clear_before_import: bool) -> None:
        self.graph = graph
        self.clear_before_import = clear_before_import
        self.nodes = self._ensure_list(graph.get("nodes", []), "nodes")
        self.edges = self._ensure_list(graph.get("edges", []), "edges")

    def build_import_statements(self) -> list[str]:
        """生成可逐条执行的 Cypher 语句。"""
        statements: list[str] = []
        statements.append(
            "CREATE CONSTRAINT knowledge_node_id IF NOT EXISTS\n"
            "FOR (n:KnowledgeNode)\n"
            "REQUIRE n.id IS UNIQUE"
        )
        if self.clear_before_import:
            statements.append("MATCH (n:KnowledgeNode) DETACH DELETE n")

        for node in self.nodes:
            statements.append(self._node_statement(node))
        for edge in self.edges:
            statements.append(self._edge_statement(edge))
        return statements

    def build_import_cypher_text(self) -> str:
        """生成方便复制到 Neo4j Browser 的完整导入文件。"""
        header = [
            "// 编程领域知识图谱 Neo4j 导入脚本",
            f"// 生成时间：{datetime.now().isoformat(timespec='seconds')}",
            "// 说明：可复制到 Neo4j Browser 中执行；重复执行会按 id 更新，不会重复插入。",
            "",
        ]
        body = [statement + ";" for statement in self.build_import_statements()]
        return "\n\n".join(header + body) + "\n"

    def build_demo_queries_text(self) -> str:
        """生成展示和汇报用的查询语句。"""
        queries = [
            (
                "1. 整体图谱预览",
                "MATCH p=(n:KnowledgeNode)-[r]->(m:KnowledgeNode)\n"
                "RETURN p\n"
                "LIMIT 80;",
            ),
            (
                "2. 面向对象核心概念网络",
                "MATCH p=(n:OOPConcept)-[r]-(m:OOPConcept)\n"
                "WHERE n.name IN ['类', '对象', '封装', '继承', '多态', '抽象', '接口']\n"
                "   OR m.name IN ['类', '对象', '封装', '继承', '多态', '抽象', '接口']\n"
                "RETURN p\n"
                "LIMIT 80;",
            ),
            (
                "3. 语法与概念对应",
                "MATCH p=(s:SyntaxRule)-[:`表达概念`|`具有语法`]-(c:OOPConcept)\n"
                "RETURN p\n"
                "LIMIT 50;",
            ),
            (
                "4. 学习路径查询",
                "MATCH p=(:OOPConcept {name: '继承'})-[:`前置依赖`*1..3]->(:OOPConcept)\n"
                "RETURN p\n"
                "LIMIT 50;",
            ),
            (
                "5. Java 与 C++ 差异",
                "MATCH p=(:ProgrammingLanguage {name: 'Java'})-[:`不同于`]-(:ProgrammingLanguage)\n"
                "RETURN p\n"
                "LIMIT 20;",
            ),
            (
                "6. 查看某个知识点详情",
                "MATCH (n:KnowledgeNode {name: '多态'})\n"
                "RETURN n.id AS id,\n"
                "       labels(n) AS labels,\n"
                "       n.description AS description,\n"
                "       n.confidence AS confidence,\n"
                "       n.source_files AS source_files,\n"
                "       n.source_pages AS source_pages;",
            ),
            (
                "7. 节点类型分布",
                "MATCH (n:KnowledgeNode)\n"
                "RETURN n.type AS node_type, count(n) AS count\n"
                "ORDER BY count DESC;",
            ),
            (
                "8. 关系类型分布",
                "MATCH (:KnowledgeNode)-[r]->(:KnowledgeNode)\n"
                "RETURN type(r) AS relation_type, count(r) AS count\n"
                "ORDER BY count DESC;",
            ),
            (
                "9. 查看某个概念的一跳邻居",
                "MATCH p=(n:KnowledgeNode {name: '多态'})-[r]-(m:KnowledgeNode)\n"
                "RETURN p\n"
                "LIMIT 50;",
            ),
            (
                "10. 查看证据来源",
                "MATCH (n:KnowledgeNode {name: '多态'})\n"
                "RETURN n.name AS name,\n"
                "       n.source_files AS source_files,\n"
                "       n.source_pages AS source_pages,\n"
                "       n.sources_json AS sources_json;",
            ),
        ]
        lines = [
            "// 编程领域知识图谱 Demo 查询",
            f"// 生成时间：{datetime.now().isoformat(timespec='seconds')}",
            "// 用法：把下面任意一段查询复制到 Neo4j Browser 中运行。",
            "",
        ]
        for title, query in queries:
            lines.append(f"// {title}")
            lines.append(query)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def demo_query_groups(self) -> list[str]:
        return [
            "整体图谱预览",
            "面向对象核心概念网络",
            "语法与概念对应",
            "学习路径查询",
            "语言差异查询",
            "知识点详情查询",
            "节点/关系类型分布",
            "证据来源查询",
        ]

    def _node_statement(self, node: dict[str, Any]) -> str:
        node_id = required_str(node, "id")
        node_type = required_str(node, "type")
        label = safe_cypher_identifier(node_type, "节点标签")
        props = normalize_node_properties(node)
        return (
            f"MERGE (n:KnowledgeNode:{label} {{id: {cypher_literal(node_id)}}})\n"
            f"SET n += {cypher_map_literal(props)}"
        )

    def _edge_statement(self, edge: dict[str, Any]) -> str:
        edge_id = required_str(edge, "id")
        source_id = required_str(edge, "source")
        target_id = required_str(edge, "target")
        relation_name = str(edge.get("neo4j_type") or edge.get("relation_name") or edge.get("type") or "").strip()
        rel_type = safe_cypher_identifier(relation_name, "关系类型")
        props = normalize_edge_properties(edge, relation_name)
        return (
            f"MATCH (source:KnowledgeNode {{id: {cypher_literal(source_id)}}})\n"
            f"MATCH (target:KnowledgeNode {{id: {cypher_literal(target_id)}}})\n"
            f"MERGE (source)-[r:{rel_type} {{id: {cypher_literal(edge_id)}}}]->(target)\n"
            f"SET r += {cypher_map_literal(props)}"
        )

    @staticmethod
    def _ensure_list(value: Any, field_name: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise ValueError(f"standard_graph.json 的 {field_name} 必须是数组。")
        return [item for item in value if isinstance(item, dict)]


class Neo4jExecutor:
    """可选的自动入库执行器。没有安装 neo4j 驱动时，会给出清晰报错。"""

    def __init__(self, uri: str, user: str, password: str, database: str | None) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database

    def execute(self, statements: list[str]) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "当前 Python 环境没有安装 neo4j 驱动。可以先使用生成的 import_graph.cypher，"
                "或者安装驱动后再运行 --execute。"
            ) from exc

        driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        try:
            with driver.session(database=self.database) if self.database else driver.session() as session:
                for statement in statements:
                    session.run(statement).consume()
        finally:
            driver.close()


def normalize_node_properties(node: dict[str, Any]) -> dict[str, Any]:
    """把节点属性转换成 Neo4j 支持的简单属性。"""
    sources = as_dict_list(node.get("sources", []))
    return {
        "id": required_str(node, "id"),
        "name": str(node.get("name", "")),
        "type": str(node.get("type", "")),
        "aliases": as_str_list(node.get("aliases", [])),
        "description": str(node.get("description", "")),
        "confidence": safe_float(node.get("confidence", 0.0)),
        "source_chunk_ids": as_str_list(node.get("source_chunk_ids", [])),
        "source_files": unique_non_empty(str(source.get("source_file", "")) for source in sources),
        "source_pages": unique_non_empty(str(source.get("page", "")) for source in sources),
        "original_entity_ids": as_str_list(node.get("original_entity_ids", [])),
        "sources_json": json.dumps(sources, ensure_ascii=False),
    }


def normalize_edge_properties(edge: dict[str, Any], neo4j_type: str) -> dict[str, Any]:
    """把关系属性转换成 Neo4j 支持的简单属性。"""
    sources = as_dict_list(edge.get("sources", []))
    return {
        "id": required_str(edge, "id"),
        "type": str(edge.get("type", "")).lower(),
        "relation_name": str(edge.get("relation_name") or neo4j_type),
        "neo4j_type": neo4j_type,
        "confidence": safe_float(edge.get("confidence", 0.0)),
        "evidence": str(edge.get("evidence", "")),
        "source_chunks": as_str_list(edge.get("source_chunks", [])),
        "source_files": unique_non_empty(str(source.get("source_file", "")) for source in sources),
        "source_pages": unique_non_empty(str(source.get("page", "")) for source in sources),
        "original_relation_ids": as_str_list(edge.get("original_relation_ids", [])),
        "sources_json": json.dumps(sources, ensure_ascii=False),
    }


def cypher_map_literal(props: dict[str, Any]) -> str:
    items = [f"{key}: {cypher_literal(value)}" for key, value in props.items()]
    if len(items) <= 3:
        return "{" + ", ".join(items) + "}"
    body = ",\n  ".join(items)
    return "{\n  " + body + "\n}"


def cypher_literal(value: Any) -> str:
    """把 Python 值转换成 Cypher 字面量。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(cypher_literal(item) for item in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def safe_cypher_identifier(value: str, label: str) -> str:
    """生成安全的 Cypher 标识符，兼容中文展示关系。"""
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} 不能为空。")
    if re.search(r"[\r\n\x00]", normalized):
        raise ValueError(f"{label} 不合法：{value}")
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", normalized):
        return normalized
    # Neo4j 对包含中文的关系类型需要使用反引号。
    return "`" + normalized.replace("`", "``") + "`"


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


def as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def unique_non_empty(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def load_graph(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("standard_graph.json 顶层必须是对象。")
    if not isinstance(payload.get("nodes"), list) or not isinstance(payload.get("edges"), list):
        raise ValueError("standard_graph.json 必须包含 nodes 和 edges 数组。")
    return payload


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_report(
    graph_path: Path,
    files: GeneratedFiles,
    graph: dict[str, Any],
    args: argparse.Namespace,
    execute_success: bool,
    errors: list[str],
    builder: Neo4jCypherBuilder,
) -> dict[str, Any]:
    return {
        "schema_version": "programming_kg_neo4j_import_v2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_graph": str(graph_path),
        "node_count": len(graph.get("nodes", [])),
        "edge_count": len(graph.get("edges", [])),
        "generated_files": {
            "import_graph": str(files.import_cypher),
            "demo_queries": str(files.demo_queries),
            "report": str(files.report),
        },
        "execute_enabled": bool(args.execute),
        "execute_success": execute_success,
        "clear_before_import": bool(args.clear),
        "neo4j": {
            "uri": args.uri,
            "user": args.user,
            "database": args.database or "default",
            "password_source": args.password_env,
        },
        "imported_node_count": len(graph.get("nodes", [])) if execute_success else 0,
        "imported_edge_count": len(graph.get("edges", [])) if execute_success else 0,
        "errors": errors,
        "node_label_strategy": "KnowledgeNode + concrete type label",
        "relationship_type_strategy": "中文展示名；英文内部码保存在关系属性 type 中",
        "demo_query_groups": builder.demo_query_groups(),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第四阶段：Neo4j 图谱入库与 Demo 查询生成。")
    parser.add_argument("--input", default=DEFAULT_INPUT_GRAPH, help="standard_graph.json 路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Neo4j 导入产物输出目录")
    parser.add_argument("--generate-cypher", action="store_true", help="生成 Cypher 文件。默认也会生成。")
    parser.add_argument("--execute", action="store_true", help="生成 Cypher 后连接 Neo4j 自动执行导入")
    parser.add_argument("--clear", action="store_true", help="导入前清空 KnowledgeNode 图谱。默认不清空，只合并更新")
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"), help="Neo4j Bolt 地址")
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"), help="Neo4j 用户名")
    parser.add_argument("--password-env", default="NEO4J_PASSWORD", help="保存 Neo4j 密码的环境变量名")
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", ""), help="Neo4j 数据库名。留空使用默认库")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    graph_path = Path(args.input)
    output_dir = Path(args.output_dir)
    files = GeneratedFiles(
        import_cypher=output_dir / "import_graph.cypher",
        demo_queries=output_dir / "demo_queries.cypher",
        report=output_dir / "neo4j_import_report.json",
    )

    graph = load_graph(graph_path)
    builder = Neo4jCypherBuilder(graph, clear_before_import=args.clear)
    import_statements = builder.build_import_statements()

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
                executor = Neo4jExecutor(
                    uri=args.uri,
                    user=args.user,
                    password=password,
                    database=args.database or None,
                )
                executor.execute(import_statements)
                execute_success = True
            except Exception as exc:
                errors.append(str(exc))

    report = build_report(
        graph_path=graph_path,
        files=files,
        graph=graph,
        args=args,
        execute_success=execute_success,
        errors=errors,
        builder=builder,
    )
    write_json(files.report, report)

    print(f"节点数量：{len(graph.get('nodes', []))}")
    print(f"关系数量：{len(graph.get('edges', []))}")
    print(f"导入脚本：{files.import_cypher}")
    print(f"展示查询：{files.demo_queries}")
    print(f"入库报告：{files.report}")
    if args.execute:
        if execute_success:
            print("Neo4j 自动导入：成功")
        else:
            print("Neo4j 自动导入：未成功，详情见 neo4j_import_report.json")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

