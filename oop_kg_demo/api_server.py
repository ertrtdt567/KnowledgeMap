"""
Lightweight web API for the OOP knowledge graph demo.

The server reads JSON artifacts produced by the existing pipeline and exposes
frontend-friendly endpoints. It intentionally uses only the Python standard
library so it can run in the current demo repository without extra installs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_GRAPH_ITEMS = 500


@dataclass(frozen=True)
class DataPaths:
    graph: Path
    questions: Path
    question_links: Path


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def first_existing_path(candidates: list[Path]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def node_label(node: dict[str, Any]) -> str:
    return normalize_text(node.get("label") or node.get("name") or node.get("id"))


def node_summary(node: dict[str, Any]) -> str:
    return normalize_text(
        node.get("summary")
        or node.get("description")
        or node.get("definition")
        or node.get("content")
    )


def relation_type(edge: dict[str, Any]) -> str:
    return normalize_text(edge.get("type") or edge.get("relation_type") or edge.get("neo4j_type"))


def frontend_node_type(raw_type: str) -> str:
    normalized = raw_type.lower()
    if normalized in {"course", "programmingparadigm"}:
        return "course"
    if normalized in {"oopconcept", "core", "knowledge_node"}:
        return "core"
    if normalized in {"exercise", "practice", "errorpattern"}:
        return "practice"
    if normalized in {"syntaxrule", "codestructure", "programminglanguage", "skill"}:
        return "topic"
    if normalized == "external":
        return "external"
    return "concept"


def frontend_edge_type(raw_type: str) -> str:
    normalized = raw_type.lower()
    if normalized in {"part_of", "belongs_to_paradigm", "contains"}:
        return "contains"
    if normalized in {"prerequisite_of", "prerequisite"}:
        return "prerequisite"
    if normalized in {"assesses", "requires_skill", "demonstrates", "practice"}:
        return "practice"
    if normalized == "external":
        return "external"
    return "related"


def confidence_to_strength(value: Any, default: int = 64) -> int:
    confidence = as_float(value, -1)
    if confidence < 0:
        return default
    if confidence <= 1:
        return max(45, min(95, round(confidence * 100)))
    return max(45, min(95, round(confidence)))


class KnowledgeGraphStore:
    def __init__(self, paths: DataPaths) -> None:
        self.paths = paths

    def raw_graph(self) -> dict[str, Any]:
        graph = as_dict(read_json(self.paths.graph, {}))
        return {
            "nodes": as_list(graph.get("nodes")),
            "edges": as_list(graph.get("edges")),
            "schema": as_dict(graph.get("schema")),
            "metadata": as_dict(graph.get("metadata")),
        }

    def questions(self) -> list[dict[str, Any]]:
        return [item for item in as_list(read_json(self.paths.questions, [])) if isinstance(item, dict)]

    def question_links(self) -> list[dict[str, Any]]:
        payload = read_json(self.paths.question_links, [])
        if isinstance(payload, dict):
            payload = payload.get("mappings") or payload.get("links") or payload.get("items") or []
        return [item for item in as_list(payload) if isinstance(item, dict)]

    def node_index(self) -> dict[str, dict[str, Any]]:
        return {
            normalize_text(node.get("id")): node
            for node in self.raw_graph()["nodes"]
            if isinstance(node, dict) and normalize_text(node.get("id"))
        }

    def adjacency(self) -> dict[str, set[str]]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in self.raw_graph()["edges"]:
            if not isinstance(edge, dict):
                continue
            source = normalize_text(edge.get("source"))
            target = normalize_text(edge.get("target"))
            if source and target:
                adjacency[source].add(target)
                adjacency[target].add(source)
        return adjacency

    def frontend_graph(self, graph_id: str = "root", depth: int = 1) -> dict[str, Any]:
        raw = self.raw_graph()
        nodes = raw["nodes"]
        edges = raw["edges"]
        focus_node: dict[str, Any] | None = None

        if graph_id and graph_id != "root":
            subgraph = self.subgraph(graph_id, depth=depth)
            nodes = subgraph["raw_nodes"]
            edges = subgraph["raw_edges"]
            focus_node = self.frontend_node(as_dict(self.node_index().get(graph_id, {})))

        degree = self.degree_map(raw["edges"])
        frontend_nodes = [self.frontend_node(node, degree.get(normalize_text(node.get("id")), 0)) for node in nodes]
        frontend_edges = [self.frontend_edge(edge) for edge in edges]

        metadata = raw["metadata"]
        title = normalize_text(metadata.get("title") or metadata.get("name") or "面向对象编程知识图谱")
        return {
            "id": graph_id or "root",
            "title": title if graph_id == "root" else f"{node_label(as_dict(self.node_index().get(graph_id, {})))} 子图",
            "subtitle": "后端 JSON 图谱接口",
            "description": normalize_text(
                metadata.get("description") or "由知识抽取、标准化与题目映射流水线生成。"
            ),
            "recommendedNodeId": frontend_nodes[0]["id"] if frontend_nodes else None,
            "focusNode": focus_node if graph_id != "root" and focus_node.get("id") else None,
            "metrics": [
                {"label": "知识点", "value": str(len(raw["nodes"]))},
                {"label": "关系", "value": str(len(raw["edges"]))},
                {"label": "习题", "value": str(len(self.questions()))},
            ],
            "nodes": frontend_nodes[:MAX_GRAPH_ITEMS],
            "edges": frontend_edges[:MAX_GRAPH_ITEMS],
        }

    def frontend_node(self, node: dict[str, Any], degree: int = 0) -> dict[str, Any]:
        node_id = normalize_text(node.get("id"))
        raw_type = normalize_text(node.get("type") or node.get("entity_type"))
        return {
            "id": node_id,
            "label": node_label(node),
            "type": frontend_node_type(raw_type),
            "sourceType": raw_type,
            "difficulty": normalize_text(node.get("difficulty") or node.get("level") or "知识点"),
            "size": 54 + min(degree, 8) * 5,
            "mastery": as_float(node.get("mastery"), as_float(node.get("confidence"), 0.55)),
            "summary": node_summary(node),
            "prerequisites": as_list(node.get("prerequisites")),
            "outcomes": as_list(node.get("outcomes")),
            "exercises": int(as_float(node.get("exercise_count"), 0)),
            "children": node_id if degree > 0 else None,
            "raw": node,
        }

    def frontend_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        raw_type = relation_type(edge)
        return {
            "id": normalize_text(edge.get("id") or f"{edge.get('source')}->{edge.get('target')}:{raw_type}"),
            "source": normalize_text(edge.get("source")),
            "target": normalize_text(edge.get("target")),
            "label": normalize_text(edge.get("label") or raw_type.replace("_", " ")),
            "type": frontend_edge_type(raw_type),
            "sourceType": raw_type,
            "strength": confidence_to_strength(edge.get("confidence"), 64),
            "raw": edge,
        }

    def degree_map(self, edges: list[Any]) -> dict[str, int]:
        degree: dict[str, int] = defaultdict(int)
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = normalize_text(edge.get("source"))
            target = normalize_text(edge.get("target"))
            if source:
                degree[source] += 1
            if target:
                degree[target] += 1
        return degree

    def node_detail(self, node_id: str) -> dict[str, Any] | None:
        node = self.node_index().get(node_id)
        if not node:
            return None
        adjacency = self.adjacency()
        graph = self.raw_graph()
        incident_edges = [
            self.frontend_edge(edge)
            for edge in graph["edges"]
            if isinstance(edge, dict)
            and (normalize_text(edge.get("source")) == node_id or normalize_text(edge.get("target")) == node_id)
        ]
        neighbor_ids = sorted(adjacency.get(node_id, set()))
        index = self.node_index()
        detail = self.frontend_node(node, len(neighbor_ids))
        detail.update(
            {
                "neighbors": [
                    self.frontend_node(index[item], len(adjacency.get(item, set())))
                    for item in neighbor_ids
                    if item in index
                ],
                "relations": incident_edges,
                "questions": self.questions_for_knowledge(node_id),
            }
        )
        return detail

    def subgraph(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        depth = max(1, min(depth, 3))
        index = self.node_index()
        if node_id not in index:
            return {"raw_nodes": [], "raw_edges": []}

        adjacency = self.adjacency()
        seen = {node_id}
        queue: deque[tuple[str, int]] = deque([(node_id, 0)])
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for neighbor in adjacency.get(current, set()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, current_depth + 1))

        raw_edges = [
            edge
            for edge in self.raw_graph()["edges"]
            if isinstance(edge, dict)
            and normalize_text(edge.get("source")) in seen
            and normalize_text(edge.get("target")) in seen
        ]
        return {
            "raw_nodes": [index[item] for item in seen if item in index],
            "raw_edges": raw_edges,
        }

    def search(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        query = query.strip().lower()
        if not query:
            return []

        results: list[dict[str, Any]] = []
        degree = self.degree_map(self.raw_graph()["edges"])
        for node in self.raw_graph()["nodes"]:
            if not isinstance(node, dict):
                continue
            haystack = " ".join(
                [
                    normalize_text(node.get("id")),
                    node_label(node),
                    normalize_text(node.get("type")),
                    node_summary(node),
                ]
            ).lower()
            if query in haystack:
                item = self.frontend_node(node, degree.get(normalize_text(node.get("id")), 0))
                item["resultType"] = "knowledge"
                results.append(item)
                if len(results) >= limit:
                    return results

        for question in self.questions():
            haystack = " ".join(
                [
                    normalize_text(question.get("question_id")),
                    normalize_text(question.get("stem")),
                    normalize_text(question.get("analysis")),
                    " ".join(map(str, as_list(question.get("abilities")))),
                ]
            ).lower()
            if query in haystack:
                results.append(self.frontend_question(question))
                if len(results) >= limit:
                    break
        return results

    def frontend_question(self, question: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": normalize_text(question.get("question_id")),
            "question_id": normalize_text(question.get("question_id")),
            "label": normalize_text(question.get("stem")),
            "resultType": "question",
            "type": normalize_text(question.get("type")),
            "type_label": normalize_text(question.get("type_label") or question.get("type")),
            "difficulty": question.get("difficulty"),
            "difficulty_label": normalize_text(question.get("difficulty_label") or question.get("difficulty")),
            "abilities": as_list(question.get("abilities")),
            "stem": normalize_text(question.get("stem")),
            "code": normalize_text(question.get("code")),
            "options": as_list(question.get("options")),
            "answer": question.get("answer"),
            "analysis": normalize_text(question.get("analysis")),
            "raw": question,
        }

    def question_by_id(self, question_id: str) -> dict[str, Any] | None:
        for question in self.questions():
            if normalize_text(question.get("question_id")) == question_id:
                return self.frontend_question(question)
        return None

    def questions_for_knowledge(self, knowledge_id: str) -> list[dict[str, Any]]:
        node = self.node_index().get(knowledge_id, {})
        names = {
            knowledge_id.lower(),
            node_label(node).lower(),
            normalize_text(node.get("name")).lower(),
        }
        question_ids: set[str] = set()
        for mapping in self.question_links():
            current_id = normalize_text(mapping.get("question_id"))
            for link in as_list(mapping.get("links")):
                if not isinstance(link, dict):
                    continue
                linked_id = normalize_text(link.get("knowledge_node_id")).lower()
                linked_name = normalize_text(link.get("knowledge_name") or link.get("name")).lower()
                if linked_id in names or linked_name in names:
                    question_ids.add(current_id)

        results = []
        for question in self.questions():
            current_id = normalize_text(question.get("question_id"))
            gold_points = as_list(question.get("gold_knowledge_points"))
            gold_names = {
                normalize_text(point.get("name")).lower()
                for point in gold_points
                if isinstance(point, dict)
            }
            if current_id in question_ids or names.intersection(gold_names):
                results.append(self.frontend_question(question))
        return results

    def list_questions(self, query: str = "", knowledge_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        if knowledge_id:
            questions = self.questions_for_knowledge(knowledge_id)
        else:
            questions = [self.frontend_question(item) for item in self.questions()]
        query = query.strip().lower()
        if query:
            questions = [
                item
                for item in questions
                if query in json.dumps(item, ensure_ascii=False).lower()
            ]
        return questions[: max(1, min(limit, 200))]

    def health(self) -> dict[str, Any]:
        graph = self.raw_graph()
        return {
            "ok": True,
            "service": "knowledge-map-api",
            "paths": {
                "graph": str(self.paths.graph),
                "questions": str(self.paths.questions),
                "question_links": str(self.paths.question_links),
            },
            "exists": {
                "graph": self.paths.graph.exists(),
                "questions": self.paths.questions.exists(),
                "question_links": self.paths.question_links.exists(),
            },
            "counts": {
                "nodes": len(graph["nodes"]),
                "edges": len(graph["edges"]),
                "questions": len(self.questions()),
                "question_links": len(self.question_links()),
            },
        }


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
    handler.end_headers()
    handler.wfile.write(body)


def parse_int(query: dict[str, list[str]], key: str, default: int) -> int:
    try:
        return int(query.get(key, [default])[0])
    except (TypeError, ValueError):
        return default


def make_handler(store: KnowledgeGraphStore, verbose: bool) -> type[BaseHTTPRequestHandler]:
    class ApiHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            json_response(self, {"ok": True})

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            segments = [unquote(item) for item in path.split("/") if item]

            try:
                payload = self.route(segments, query)
                json_response(self, payload)
            except KeyError as exc:
                json_response(self, {"error": str(exc).strip("'")}, HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover - defensive API boundary
                json_response(self, {"error": f"internal server error: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def route(self, segments: list[str], query: dict[str, list[str]]) -> Any:
            if not segments:
                return {
                    "service": "knowledge-map-api",
                    "endpoints": [
                        "/api/health",
                        "/api/graphs/root",
                        "/api/graphs/{nodeId}",
                        "/api/nodes/{nodeId}",
                        "/api/nodes/{nodeId}/neighbors",
                        "/api/search?q=keyword",
                        "/api/questions",
                        "/api/questions/{questionId}",
                        "/api/schema",
                    ],
                }

            if segments[:2] == ["api", "health"]:
                return store.health()

            if segments[:2] == ["api", "schema"]:
                graph = store.raw_graph()
                return {
                    "schema": graph["schema"],
                    "metadata": graph["metadata"],
                    "nodeTypes": sorted({normalize_text(node.get("type")) for node in graph["nodes"] if isinstance(node, dict)}),
                    "edgeTypes": sorted({relation_type(edge) for edge in graph["edges"] if isinstance(edge, dict)}),
                }

            if segments[:2] == ["api", "graph"]:
                return store.raw_graph()

            if len(segments) >= 2 and segments[:2] == ["api", "graphs"]:
                graph_id = segments[2] if len(segments) > 2 else "root"
                depth = parse_int(query, "depth", 1)
                return store.frontend_graph(graph_id, depth=depth)

            if len(segments) >= 3 and segments[:2] == ["api", "nodes"]:
                node_id = segments[2]
                if len(segments) == 4 and segments[3] == "neighbors":
                    depth = parse_int(query, "depth", 1)
                    return store.frontend_graph(node_id, depth=depth)
                detail = store.node_detail(node_id)
                if detail is None:
                    raise KeyError(f"node not found: {node_id}")
                return detail

            if segments[:2] == ["api", "search"]:
                query_text = query.get("q", [""])[0]
                limit = parse_int(query, "limit", 12)
                return store.search(query_text, limit=limit)

            if len(segments) >= 2 and segments[:2] == ["api", "questions"]:
                if len(segments) == 3:
                    question = store.question_by_id(segments[2])
                    if question is None:
                        raise KeyError(f"question not found: {segments[2]}")
                    return question
                return store.list_questions(
                    query=query.get("q", [""])[0],
                    knowledge_id=query.get("knowledgeId", [""])[0],
                    limit=parse_int(query, "limit", 50),
                )

            raise KeyError(f"unknown endpoint: /{'/'.join(segments)}")

        def log_message(self, format_string: str, *args: Any) -> None:
            if verbose:
                super().log_message(format_string, *args)

    return ApiHandler


def default_paths(base_dir: Path) -> DataPaths:
    repo_root = base_dir.parent
    graph_env = os.getenv("KG_GRAPH_PATH")
    questions_env = os.getenv("KG_QUESTIONS_PATH")
    links_env = os.getenv("KG_QUESTION_LINKS_PATH")

    graph_candidates = [
        Path(graph_env) if graph_env else None,
        base_dir / "output" / "graph_normalized" / "standard_graph.json",
        repo_root / "output" / "graph_normalized" / "standard_graph.json",
        repo_root / "work" / "oop_kg_demo" / "output" / "graph_normalized" / "standard_graph.json",
    ]
    question_candidates = [
        Path(questions_env) if questions_env else None,
        base_dir / "output" / "question_mapping" / "questions.json",
        base_dir / "part5_questions" / "data" / "sample_questions.json",
        repo_root / "work" / "oop_kg_demo" / "output" / "question_mapping" / "questions.json",
        repo_root / "work" / "oop_kg_demo" / "data" / "sample_questions.json",
    ]
    link_candidates = [
        Path(links_env) if links_env else None,
        base_dir / "output" / "question_mapping" / "question_knowledge_links.json",
        repo_root / "work" / "oop_kg_demo" / "output" / "question_mapping" / "question_knowledge_links.json",
    ]

    return DataPaths(
        graph=first_existing_path([item for item in graph_candidates if item is not None]),
        questions=first_existing_path([item for item in question_candidates if item is not None]),
        question_links=first_existing_path([item for item in link_candidates if item is not None]),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the OOP knowledge graph JSON web API.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host, default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port, default: 8000")
    parser.add_argument("--graph", default="", help="Path to standard_graph.json")
    parser.add_argument("--questions", default="", help="Path to questions.json or sample_questions.json")
    parser.add_argument("--question-links", default="", help="Path to question_knowledge_links.json")
    parser.add_argument("--verbose", action="store_true", help="Print HTTP access logs")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    base_dir = Path(__file__).resolve().parent
    paths = default_paths(base_dir)
    if args.graph:
        paths = DataPaths(Path(args.graph), paths.questions, paths.question_links)
    if args.questions:
        paths = DataPaths(paths.graph, Path(args.questions), paths.question_links)
    if args.question_links:
        paths = DataPaths(paths.graph, paths.questions, Path(args.question_links))

    store = KnowledgeGraphStore(paths)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, args.verbose))
    print(f"KnowledgeMap API listening on http://{args.host}:{args.port}", flush=True)
    print(json.dumps(store.health(), ensure_ascii=False, indent=2), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping KnowledgeMap API.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
