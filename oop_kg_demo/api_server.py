"""
Lightweight web API for the OOP knowledge graph demo.

The server reads JSON artifacts produced by the existing pipeline and exposes
frontend-friendly endpoints. It intentionally uses only the Python standard
library so it can run in the current demo repository without extra installs.
"""

from __future__ import annotations

import argparse
import json
import math
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
MAX_SUBGRAPH_ITEMS = 36
MAX_FOCUS_EXAMPLES = 12
MAX_FOCUS_SUPPORT_NODES = 20
DEFAULT_ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # Playwright uses a separate local Vite port for end-to-end tests.
    "http://localhost:4173",
    "http://127.0.0.1:4173",
}
CURRICULUM_NODE_TYPES = {
    "Course",
    "KnowledgeDomain",
    "KnowledgeUnit",
    "KnowledgePoint",
    "AlgorithmStrategy",
}
EXPANDABLE_NODE_TYPES = CURRICULUM_NODE_TYPES | {"OOPConcept"}
COURSE_ROOT_IDS = (
    "course_python",
    "course_java",
    "course_cpp",
    "course_data_structures",
    "course_uml",
)
COURSE_DISPLAY_LABELS = {
    "course_python": "python",
    "course_java": "java",
    "course_cpp": "c++",
    "course_data_structures": "数据结构",
    "course_uml": "uml建模设计与分析",
}
COURSE_GRAPH_HUB_ID = "course_graph_hub"
# The root overview has a fixed three-level hierarchy.  Dense groups use at
# most two local rings so the graph stays compact at every level.
DENSE_COURSE_CHILD_THRESHOLD = 8
DENSE_MAJOR_INNER_RADIUS = 440
DENSE_MAJOR_OUTER_RADIUS = 555
STANDARD_MAJOR_RADIUS = 500
STANDARD_MINOR_RADIUS = 785
DENSE_MINOR_INNER_RADIUS = 740
DENSE_MINOR_OUTER_RADIUS = 840
ROOT_HIDDEN_NODE_IDS = {
    "curriculum_D1_6",
    "curriculum_D1_7",
    "curriculum_D1_8",
    "curriculum_D1_9",
}


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
    label = normalize_text(node.get("label") or node.get("name") or node.get("id"))
    node_id = normalize_text(node.get("id"))
    if node_id in COURSE_DISPLAY_LABELS:
        return COURSE_DISPLAY_LABELS[node_id]
    if node_id == "curriculum_L11_1":
        return "数据流模型"
    if normalize_text(node.get("type")) == "CodeExample" and (
        label.lower().startswith("codeexample") or len(label) > 28
    ):
        description = normalize_text(node.get("description") or node.get("summary"))
        if description and description not in {"教学材料中的代码示例", "代码示例"}:
            return f"示例 · {description[:18]}{'…' if len(description) > 18 else ''}"
        sources = as_list(node.get("sources"))
        first_source = as_dict(sources[0]) if sources else {}
        source_file = normalize_text(first_source.get("source_file"))
        page = first_source.get("page")
        if source_file:
            source_name = Path(source_file).stem
            page_text = f" · P{page}" if page not in {None, ""} else ""
            return f"示例 · {source_name[:14]}{page_text}"
        suffix = label[-10:] if len(label) > 10 else label
        return f"代码示例 · {suffix}"
    return label


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
    if normalized in {"course", "programmingparadigm", "knowledgedomain"}:
        return "course"
    if normalized in {"oopconcept", "core", "knowledge_node", "knowledgepoint"}:
        return "core"
    if normalized in {"exercise", "practice", "errorpattern", "codeexample"}:
        return "practice"
    if normalized in {"knowledgeunit", "syntaxrule", "skill"}:
        return "topic"
    if normalized in {"codestructure"}:
        return "concept"
    if normalized in {"programminglanguage"}:
        return "external"
    if normalized == "external":
        return "external"
    return "concept"


def frontend_edge_type(raw_type: str) -> str:
    normalized = raw_type.lower()
    if normalized in {"part_of", "belongs_to_paradigm", "contains"}:
        return "contains"
    if normalized in {"prerequisite_of", "prerequisite"}:
        return "prerequisite"
    if normalized in {"assesses", "requires_skill", "demonstrates", "practice", "has_code_example"}:
        return "practice"
    if normalized == "external":
        return "external"
    return "related"


def frontend_edge_label(raw_type: str) -> str:
    labels = {
        "part_of": "包含",
        "contains": "包含",
        "contains_structure": "包含代码结构",
        "has_code_structure": "具有代码结构",
        "has_algorithm": "包含算法",
        "has_algorithm_problem": "包含算法问题",
        "has_algorithm_strategy": "包含算法策略",
        "has_complexity_metric": "具有复杂度指标",
        "has_concurrency_mechanism": "具有并发机制",
        "has_control_structure": "具有控制结构",
        "has_core_concept": "具有核心概念",
        "maps_to_core": "映射到核心概念",
        "has_core_feature": "具有核心特性",
        "has_data_structure": "具有数据结构",
        "has_engineering_practice": "具有工程实践",
        "has_error_handling": "具有异常处理机制",
        "has_implementation_mechanism": "具有实现机制",
        "has_operation_rule": "具有操作规则",
        "has_persistence_mechanism": "具有持久化机制",
        "demonstrates": "演示知识",
        "has_code_example": "示例代码",
        "appears_in_example": "出现于示例",
        "used_in_example": "示例使用",
        "uses_syntax": "使用语法",
        "has_syntax": "具有语法",
        "expresses_concept": "表达概念",
        "implemented_in": "实现于语言",
        "implements_interface": "实现接口",
        "inherits_from": "继承自",
        "prerequisite_of": "前置于",
        "prerequisite": "前置于",
        "belongs_to_paradigm": "属于编程范式",
        "assesses": "考查",
        "requires_skill": "需要技能",
        "may_cause": "可能导致",
        "confused_with": "易与其混淆",
        "equivalent_to": "等价于",
        "differs_from": "区别于",
        "built_on_platform": "构建于平台",
        "develops_ability": "培养能力",
        "solves_problem": "解决问题",
        "supports_language": "支持语言",
        "uses_strategy": "采用策略",
    }
    normalized = normalize_text(raw_type).lower()
    return labels.get(normalized, "关联关系")


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
        self._graph_cache: dict[str, Any] | None = None
        self._graph_mtime_ns = -1

    def raw_graph(self) -> dict[str, Any]:
        try:
            mtime_ns = self.paths.graph.stat().st_mtime_ns
        except FileNotFoundError:
            mtime_ns = -1
        if self._graph_cache is not None and self._graph_mtime_ns == mtime_ns:
            return self._graph_cache

        graph = as_dict(read_json(self.paths.graph, {}))
        normalized = {
            "nodes": as_list(graph.get("nodes")),
            "edges": as_list(graph.get("edges")),
            "schema": as_dict(graph.get("schema")),
            "metadata": as_dict(graph.get("metadata")),
        }
        self._graph_cache = normalized
        self._graph_mtime_ns = mtime_ns
        return normalized

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
        view_mode = "network"
        focus_node: dict[str, Any] | None = None

        if not graph_id or graph_id == "root":
            selected = self.curriculum_root(raw)
            nodes = selected["raw_nodes"]
            edges = selected["raw_edges"]
            view_mode = "course-overview"
        else:
            selected = self.focused_graph(graph_id, depth=depth)
            nodes = selected["raw_nodes"]
            edges = selected["raw_edges"]
            view_mode = normalize_text(selected.get("view_mode") or "network")
            focus_node = self.frontend_node(as_dict(self.node_index().get(graph_id, {})))

        degree = self.degree_map(edges)
        visible_nodes, visible_edges = self.visible_graph_items(
            nodes,
            edges,
            degree,
            max_items=MAX_GRAPH_ITEMS if graph_id == "root" else MAX_SUBGRAPH_ITEMS,
            required_node_id="" if graph_id == "root" else graph_id,
        )
        frontend_nodes = [
            self.frontend_node(node, degree.get(normalize_text(node.get("id")), 0))
            for node in visible_nodes
        ]
        if graph_id == "root":
            node_layers = as_dict(selected.get("node_layers"))
            node_positions = as_dict(selected.get("node_positions"))
            layer_sizes = {1: 128, 2: 94, 3: 72}
            for node in frontend_nodes:
                layer = int(as_float(node_layers.get(node["id"]), 3))
                node["layer"] = layer
                node["size"] = 140 if node.get("systemNode") else layer_sizes.get(layer, node["size"])
                position = as_dict(node_positions.get(node["id"]))
                if position:
                    node["position"] = position
        else:
            node_layers = self.radial_layers(graph_id, visible_nodes, visible_edges)
            layer_sizes = {1: 112, 2: 76, 3: 56}
            for node in frontend_nodes:
                layer = node_layers.get(node["id"], 3)
                node["layer"] = layer
                node["size"] = layer_sizes.get(layer, node["size"])
        if graph_id != "root":
            for node in frontend_nodes:
                if node["id"] == graph_id:
                    node["children"] = None
        frontend_edges = [self.frontend_edge(edge) for edge in visible_edges]
        if graph_id == "root":
            for edge in frontend_edges:
                edge["courseOverview"] = True

        metadata = raw["metadata"]
        title = normalize_text(metadata.get("title") or metadata.get("name") or "编程课程知识图谱")
        type_counts = defaultdict(int)
        for node in raw["nodes"]:
            if isinstance(node, dict):
                type_counts[normalize_text(node.get("type"))] += 1

        if graph_id == "root":
            metrics = [
                {"label": "课程", "value": str(sum(node.get("sourceType") == "Course" for node in frontend_nodes))},
                {"label": "主要知识点", "value": str(sum(node.get("layer") == 2 for node in frontend_nodes))},
                {"label": "次要知识点", "value": str(sum(node.get("layer") == 3 for node in frontend_nodes))},
            ]
            subtitle = "五门课程三层知识总览"
            recommended_node_id = next(
                (node["id"] for node in frontend_nodes if node["id"] == "course_python"),
                frontend_nodes[0]["id"] if frontend_nodes else None,
            )
        else:
            visible_type_counts = defaultdict(int)
            for node in visible_nodes:
                visible_type_counts[normalize_text(node.get("type"))] += 1
            metrics = [
                {"label": "知识节点", "value": str(visible_type_counts["KnowledgeUnit"] + visible_type_counts["KnowledgePoint"])},
                {"label": "代码示例", "value": str(visible_type_counts["CodeExample"])},
                {"label": "关联关系", "value": str(len(frontend_edges))},
            ]
            subtitle = "知识点关联子图"
            recommended_node_id = graph_id if any(node["id"] == graph_id for node in frontend_nodes) else (
                frontend_nodes[0]["id"] if frontend_nodes else None
            )

        return {
            "id": graph_id or "root",
            "title": "五门课程知识图谱" if graph_id == "root" else f"{node_label(as_dict(self.node_index().get(graph_id, {})))} 子图",
            "subtitle": subtitle,
            "description": normalize_text(
                metadata.get("description") or "由知识抽取、标准化与题目映射流水线生成。"
            ),
            "recommendedNodeId": recommended_node_id,
            "focusNode": focus_node if graph_id != "root" and focus_node.get("id") else None,
            "viewMode": view_mode,
            "layout": "radial",
            "legend": [
                {"layer": 1, "label": "第一层 · 课程" if graph_id == "root" else "第一层 · 当前节点", "color": "#ff5375"},
                {"layer": 2, "label": "第二层 · 主要知识点" if graph_id == "root" else "第二层 · 直接关联", "color": "#ff8b63"},
                {"layer": 3, "label": "第三层 · 次要知识点" if graph_id == "root" else "第三层 · 次级关联", "color": "#a66bff"},
            ],
            "metrics": metrics,
            "nodes": frontend_nodes,
            "edges": frontend_edges,
        }

    def curriculum_root(self, raw: dict[str, Any]) -> dict[str, Any]:
        index = {
            normalize_text(node.get("id")): node
            for node in raw["nodes"]
            if isinstance(node, dict) and normalize_text(node.get("id"))
        }
        hierarchy_edges = [
            edge
            for edge in raw["edges"]
            if isinstance(edge, dict) and relation_type(edge) == "part_of"
        ]
        course_ids = [
            node_id
            for node_id in COURSE_ROOT_IDS
            if normalize_text(as_dict(index.get(node_id, {})).get("type")) == "Course"
        ]
        course_id_set = set(course_ids)
        major_edges = [
            edge
            for edge in hierarchy_edges
            if normalize_text(edge.get("target")) in course_id_set
            and normalize_text(as_dict(index.get(normalize_text(edge.get("source")), {})).get("type"))
            == "KnowledgeDomain"
        ]
        major_ids = {normalize_text(edge.get("source")) for edge in major_edges}
        minor_edges = [
            edge
            for edge in hierarchy_edges
            if normalize_text(edge.get("target")) in major_ids
        ]
        minor_ids = {normalize_text(edge.get("source")) for edge in minor_edges}
        node_ids = course_id_set | major_ids | minor_ids
        hub_node = {
            "id": COURSE_GRAPH_HUB_ID,
            "label": "面向编程领域的知识图谱",
            "type": "GraphHub",
            "summary": "五门编程课程的知识总览",
            "system_node": True,
        }
        hub_edges = [
            {
                "id": f"{COURSE_GRAPH_HUB_ID}->{course_id}:contains",
                "source": COURSE_GRAPH_HUB_ID,
                "target": course_id,
                "type": "contains",
                "confidence": 0.95,
            }
            for course_id in course_ids
        ]
        node_layers = {
            COURSE_GRAPH_HUB_ID: 1,
            **{node_id: 1 for node_id in course_ids},
            **{node_id: 2 for node_id in major_ids},
            **{node_id: 3 for node_id in minor_ids},
        }
        return {
            "raw_nodes": [hub_node, *[index[node_id] for node_id in node_ids if node_id in index]],
            "raw_edges": hub_edges + major_edges + minor_edges,
            "node_layers": node_layers,
            "node_positions": {
                COURSE_GRAPH_HUB_ID: {"x": 0, "y": 0},
                **self.course_overview_positions(course_ids, major_edges, minor_edges, index),
            },
        }

    def course_overview_positions(
        self,
        course_ids: list[str],
        major_edges: list[dict[str, Any]],
        minor_edges: list[dict[str, Any]],
        index: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, float]]:
        positions: dict[str, dict[str, float]] = {}
        if not course_ids:
            return positions

        course_angles: dict[str, float] = {}
        for course_index, course_id in enumerate(course_ids):
            angle = -math.pi / 2 + course_index * (2 * math.pi / len(course_ids))
            course_angles[course_id] = angle
            positions[course_id] = {
                "x": round(math.cos(angle) * 250, 2),
                "y": round(math.sin(angle) * 250, 2),
            }

        majors_by_course: dict[str, list[str]] = defaultdict(list)
        for edge in major_edges:
            majors_by_course[normalize_text(edge.get("target"))].append(normalize_text(edge.get("source")))

        major_angles: dict[str, float] = {}
        major_radii: dict[str, float] = {}
        course_sector = (2 * math.pi / len(course_ids)) * 0.82
        for course_id, major_ids in majors_by_course.items():
            major_ids.sort(key=lambda node_id: node_label(as_dict(index.get(node_id, {}))))
            ring_groups = (
                (
                    (major_ids[::2], DENSE_MAJOR_INNER_RADIUS),
                    (major_ids[1::2], DENSE_MAJOR_OUTER_RADIUS),
                )
                if len(major_ids) > DENSE_COURSE_CHILD_THRESHOLD
                else ((major_ids, STANDARD_MAJOR_RADIUS),)
            )
            for ring_ids, radius in ring_groups:
                count = len(ring_ids)
                for major_index, major_id in enumerate(ring_ids):
                    offset = 0 if count == 1 else (major_index / (count - 1) - 0.5) * course_sector
                    angle = course_angles[course_id] + offset
                    major_angles[major_id] = angle
                    major_radii[major_id] = radius
                    positions[major_id] = {
                        "x": round(math.cos(angle) * radius, 2),
                        "y": round(math.sin(angle) * radius, 2),
                    }

        minors_by_major: dict[str, list[str]] = defaultdict(list)
        for edge in minor_edges:
            minors_by_major[normalize_text(edge.get("target"))].append(normalize_text(edge.get("source")))

        for course_id, major_ids in majors_by_course.items():
            # Keep the third level on one course-wide ring, or two interleaved
            # rings when dense.  Per-parent rings would combine into three or
            # more visible bands whenever the second level itself has two rings.
            minor_ids = sorted(
                {
                    minor_id
                    for major_id in major_ids
                    for minor_id in minors_by_major.get(major_id, [])
                },
                key=lambda node_id: node_label(as_dict(index.get(node_id, {}))),
            )
            ring_groups = (
                (
                    (minor_ids[::2], DENSE_MINOR_INNER_RADIUS),
                    (minor_ids[1::2], DENSE_MINOR_OUTER_RADIUS),
                )
                if len(minor_ids) > DENSE_COURSE_CHILD_THRESHOLD
                else ((minor_ids, STANDARD_MINOR_RADIUS),)
            )
            for ring_ids, radius in ring_groups:
                count = len(ring_ids)
                for minor_index, minor_id in enumerate(ring_ids):
                    offset = 0 if count == 1 else (minor_index / (count - 1) - 0.5) * course_sector
                    angle = course_angles[course_id] + offset
                    positions[minor_id] = {
                        "x": round(math.cos(angle) * radius, 2),
                        "y": round(math.sin(angle) * radius, 2),
                    }
        return positions

    def radial_layers(
        self, root_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, int]:
        node_ids = {normalize_text(node.get("id")) for node in nodes if normalize_text(node.get("id"))}
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = normalize_text(edge.get("source"))
            target = normalize_text(edge.get("target"))
            if source in node_ids and target in node_ids:
                adjacency[source].add(target)
                adjacency[target].add(source)

        layers = {root_id: 1}
        queue = deque([root_id])
        while queue:
            node_id = queue.popleft()
            next_layer = min(layers[node_id] + 1, 3)
            if next_layer == 3:
                continue
            for neighbor_id in adjacency.get(node_id, set()):
                if neighbor_id not in layers:
                    layers[neighbor_id] = next_layer
                    queue.append(neighbor_id)
        return {node_id: layers.get(node_id, 3) for node_id in node_ids}

    def focused_graph(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        raw = self.raw_graph()
        index = {
            normalize_text(node.get("id")): node
            for node in raw["nodes"]
            if isinstance(node, dict) and normalize_text(node.get("id"))
        }
        focus = index.get(node_id)
        if not focus:
            return {"raw_nodes": [], "raw_edges": [], "view_mode": "network"}

        focus_type = normalize_text(focus.get("type"))
        selected_ids = {node_id}
        selected_edges: list[dict[str, Any]] = []

        hierarchy_edges = [
            edge
            for edge in raw["edges"]
            if isinstance(edge, dict)
            and relation_type(edge) == "part_of"
            and (
                normalize_text(edge.get("source")) == node_id
                or normalize_text(edge.get("target")) == node_id
            )
        ]

        if focus_type == "KnowledgeDomain":
            for edge in hierarchy_edges:
                source = normalize_text(edge.get("source"))
                target = normalize_text(edge.get("target"))
                other = target if source == node_id else source
                other_type = normalize_text(as_dict(index.get(other, {})).get("type"))
                if other_type in {"KnowledgeDomain", "KnowledgeUnit"}:
                    selected_ids.add(other)
                    selected_edges.append(edge)
            view_mode = "domain"
        elif focus_type == "KnowledgeUnit":
            child_point_ids: set[str] = set()
            for edge in hierarchy_edges:
                source = normalize_text(edge.get("source"))
                target = normalize_text(edge.get("target"))
                other = target if source == node_id else source
                other_type = normalize_text(as_dict(index.get(other, {})).get("type"))
                if other_type in {"KnowledgeDomain", "KnowledgePoint"}:
                    selected_ids.add(other)
                    selected_edges.append(edge)
                    if other_type == "KnowledgePoint" and target == node_id:
                        child_point_ids.add(other)

            if not child_point_ids:
                example_edges = self.direct_example_edges(node_id, raw, index)
                example_ids = self.select_example_ids(example_edges, index, MAX_FOCUS_EXAMPLES)
                selected_ids.update(example_ids)
                selected_edges.extend(
                    edge
                    for edge in example_edges
                    if self.example_id_for_edge(edge, index) in example_ids
                )
            view_mode = "unit"
        elif focus_type == "KnowledgePoint":
            for edge in hierarchy_edges:
                source = normalize_text(edge.get("source"))
                target = normalize_text(edge.get("target"))
                other = target if source == node_id else source
                if normalize_text(as_dict(index.get(other, {})).get("type")) == "KnowledgeUnit":
                    selected_ids.add(other)
                    selected_edges.append(edge)

            core_mapping_edges = [
                edge
                for edge in raw["edges"]
                if isinstance(edge, dict)
                and relation_type(edge) == "maps_to_core"
                and (
                    normalize_text(edge.get("source")) == node_id
                    or normalize_text(edge.get("target")) == node_id
                )
            ]
            selected_edges.extend(core_mapping_edges)
            for edge in core_mapping_edges:
                source = normalize_text(edge.get("source"))
                target = normalize_text(edge.get("target"))
                selected_ids.add(target if source == node_id else source)

            example_edges = self.direct_example_edges(node_id, raw, index)
            example_ids = self.select_example_ids(example_edges, index, MAX_FOCUS_EXAMPLES)
            selected_ids.update(example_ids)
            selected_edges.extend(
                edge
                for edge in example_edges
                if self.example_id_for_edge(edge, index) in example_ids
            )

            support_edges = [
                edge
                for edge in raw["edges"]
                if isinstance(edge, dict)
                and self.example_id_for_edge(edge, index) in example_ids
                and relation_type(edge)
                in {"contains_structure", "uses_syntax", "appears_in_example", "used_in_example"}
                and self.example_support_id(edge, index)
                and normalize_text(
                    as_dict(index.get(self.example_support_id(edge, index), {})).get("type")
                ) in {"CodeStructure", "SyntaxRule", "ProgrammingLanguage"}
            ]
            support_edges.sort(
                key=lambda edge: (
                    -as_float(edge.get("confidence")),
                    normalize_text(edge.get("source")),
                    normalize_text(edge.get("target")),
                )
            )
            support_edges = support_edges[:MAX_FOCUS_SUPPORT_NODES]
            selected_edges.extend(support_edges)
            selected_ids.update(self.example_support_id(edge, index) for edge in support_edges)
            view_mode = "knowledge"
        else:
            fallback = self.subgraph(node_id, depth=depth)
            fallback["view_mode"] = "network"
            return fallback

        selected_edge_ids = {
            normalize_text(edge.get("id") or f"{edge.get('source')}->{edge.get('target')}:{relation_type(edge)}")
            for edge in selected_edges
        }
        deduplicated_edges = []
        seen_edges: set[str] = set()
        for edge in selected_edges:
            edge_id = normalize_text(edge.get("id") or f"{edge.get('source')}->{edge.get('target')}:{relation_type(edge)}")
            if edge_id and edge_id in selected_edge_ids and edge_id not in seen_edges:
                deduplicated_edges.append(edge)
                seen_edges.add(edge_id)

        return {
            "raw_nodes": [node for node in raw["nodes"] if isinstance(node, dict) and normalize_text(node.get("id")) in selected_ids],
            "raw_edges": deduplicated_edges,
            "view_mode": view_mode,
        }

    def direct_example_edges(
        self,
        node_id: str,
        raw: dict[str, Any],
        index: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            edge
            for edge in raw["edges"]
            if isinstance(edge, dict)
            and (
                (
                    normalize_text(edge.get("target")) == node_id
                    and relation_type(edge) in {"demonstrates", "uses_syntax", "contains_structure"}
                    and normalize_text(
                        as_dict(index.get(normalize_text(edge.get("source")), {})).get("type")
                    ) == "CodeExample"
                )
                or (
                    normalize_text(edge.get("source")) == node_id
                    and relation_type(edge) == "has_code_example"
                    and normalize_text(
                        as_dict(index.get(normalize_text(edge.get("target")), {})).get("type")
                    ) == "CodeExample"
                )
            )
        ]

    def example_id_for_edge(
        self, edge: dict[str, Any], index: dict[str, dict[str, Any]]
    ) -> str:
        source = normalize_text(edge.get("source"))
        target = normalize_text(edge.get("target"))
        if normalize_text(as_dict(index.get(source, {})).get("type")) == "CodeExample":
            return source
        if normalize_text(as_dict(index.get(target, {})).get("type")) == "CodeExample":
            return target
        return ""

    def example_support_id(
        self, edge: dict[str, Any], index: dict[str, dict[str, Any]]
    ) -> str:
        example_id = self.example_id_for_edge(edge, index)
        if not example_id:
            return ""
        source = normalize_text(edge.get("source"))
        target = normalize_text(edge.get("target"))
        return target if source == example_id else source

    def select_example_ids(
        self, edges: list[dict[str, Any]], index: dict[str, dict[str, Any]], limit: int
    ) -> set[str]:
        relation_priority = {
            "has_code_example": 0,
            "demonstrates": 1,
            "uses_syntax": 2,
            "contains_structure": 3,
        }
        ordered = sorted(
            edges,
            key=lambda edge: (
                relation_priority.get(relation_type(edge), 9),
                -as_float(edge.get("confidence")),
                self.example_id_for_edge(edge, index),
            ),
        )
        selected: list[str] = []
        seen: set[str] = set()
        for edge in ordered:
            example_id = self.example_id_for_edge(edge, index)
            if example_id and example_id not in seen:
                selected.append(example_id)
                seen.add(example_id)
                if len(selected) >= limit:
                    break
        return set(selected)

    def visible_graph_items(
        self,
        nodes: list[Any],
        edges: list[Any],
        degree: dict[str, int],
        max_items: int = MAX_GRAPH_ITEMS,
        required_node_id: str = "",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        valid_nodes = [
            node
            for node in nodes
            if isinstance(node, dict) and normalize_text(node.get("id"))
        ]
        if len(valid_nodes) > max_items:
            required_nodes = [
                node for node in valid_nodes if normalize_text(node.get("id")) == required_node_id
            ]
            ranked_nodes = sorted(
                (node for node in valid_nodes if normalize_text(node.get("id")) != required_node_id),
                key=lambda node: degree.get(normalize_text(node.get("id")), 0),
                reverse=True,
            )
            valid_nodes = (required_nodes + ranked_nodes)[:max_items]

        visible_ids = {normalize_text(node.get("id")) for node in valid_nodes}
        candidate_edges = [
            edge
            for edge in edges
            if isinstance(edge, dict)
            and normalize_text(edge.get("source")) in visible_ids
            and normalize_text(edge.get("target")) in visible_ids
        ]
        if len(candidate_edges) <= max_items:
            return valid_nodes, candidate_edges

        relation_priority = {"part_of": 0, "demonstrates": 1, "uses_syntax": 2, "contains_structure": 3}
        candidate_edges.sort(
            key=lambda edge: (
                relation_priority.get(relation_type(edge), 9),
                -as_float(edge.get("confidence")),
                normalize_text(edge.get("source")),
                normalize_text(edge.get("target")),
            )
        )
        visible_edges: list[dict[str, Any]] = []
        covered_ids: set[str] = set()
        selected_edge_ids: set[str] = set()
        for edge in candidate_edges:
            source = normalize_text(edge.get("source"))
            target = normalize_text(edge.get("target"))
            edge_id = normalize_text(edge.get("id") or f"{source}->{target}:{relation_type(edge)}")
            if source not in covered_ids or target not in covered_ids:
                visible_edges.append(edge)
                covered_ids.update({source, target})
                selected_edge_ids.add(edge_id)
                if len(visible_edges) >= max_items:
                    break
        if len(visible_edges) < MAX_GRAPH_ITEMS:
            for edge in candidate_edges:
                source = normalize_text(edge.get("source"))
                target = normalize_text(edge.get("target"))
                edge_id = normalize_text(edge.get("id") or f"{source}->{target}:{relation_type(edge)}")
                if edge_id not in selected_edge_ids:
                    visible_edges.append(edge)
                    selected_edge_ids.add(edge_id)
                    if len(visible_edges) >= max_items:
                        break
        return valid_nodes, visible_edges

    def frontend_node(self, node: dict[str, Any], degree: int = 0) -> dict[str, Any]:
        node_id = normalize_text(node.get("id"))
        raw_type = normalize_text(node.get("type") or node.get("entity_type"))
        aliases = list(
            dict.fromkeys(
                normalize_text(item)
                for item in as_list(node.get("aliases"))
                if normalize_text(item)
            )
        )
        source_count = len(as_list(node.get("source_chunk_ids")) or as_list(node.get("sources")))
        node_confidence = as_float(node.get("confidence"), 0.0)
        return {
            "id": node_id,
            "label": node_label(node),
            "type": frontend_node_type(raw_type),
            "sourceType": raw_type,
            "difficulty": normalize_text(node.get("difficulty") or node.get("level") or "知识点"),
            "size": 54 + min(degree, 8) * 5,
            "mastery": as_float(node.get("mastery"), node_confidence),
            "confidence": node_confidence,
            "relationCount": degree,
            "sourceCount": source_count,
            "aliases": aliases,
            "summary": node_summary(node),
            "prerequisites": as_list(node.get("prerequisites")),
            "outcomes": as_list(node.get("outcomes")),
            "exercises": int(as_float(node.get("exercise_count"), 0)),
            "children": node_id if raw_type in EXPANDABLE_NODE_TYPES else None,
            "systemNode": bool(node.get("system_node")),
            "raw": node,
        }

    def frontend_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        raw_type = relation_type(edge)
        source = normalize_text(edge.get("source"))
        target = normalize_text(edge.get("target"))
        if raw_type == "part_of":
            source, target = target, source
        return {
            "id": normalize_text(edge.get("id") or f"{edge.get('source')}->{edge.get('target')}:{raw_type}"),
            "source": source,
            "target": target,
            "label": frontend_edge_label(raw_type),
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
                item["graphId"] = self.search_graph_id(normalize_text(node.get("id")))
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

    def search_graph_id(self, node_id: str) -> str:
        graph = self.raw_graph()
        index = self.node_index()
        node_type = normalize_text(as_dict(index.get(node_id, {})).get("type"))
        if node_type in EXPANDABLE_NODE_TYPES:
            return node_id
        if node_type == "CodeExample":
            target_priority = {"KnowledgePoint": 0, "KnowledgeUnit": 1, "KnowledgeDomain": 2}
            candidates = []
            for edge in graph["edges"]:
                if not isinstance(edge, dict):
                    continue
                edge_type = relation_type(edge)
                source = normalize_text(edge.get("source"))
                target = normalize_text(edge.get("target"))
                if source == node_id and edge_type in {"demonstrates", "uses_syntax", "contains_structure"}:
                    related_id = target
                elif target == node_id and edge_type == "has_code_example":
                    related_id = source
                else:
                    continue
                target_type = normalize_text(as_dict(index.get(related_id, {})).get("type"))
                if target_type in target_priority:
                    candidates.append((target_priority[target_type], -as_float(edge.get("confidence")), related_id))
            if candidates:
                candidates.sort()
                return candidates[0][2]
        if node_type == "CodeExample":
            course_id = normalize_text(as_dict(index.get(node_id, {})).get("course_id"))
            if normalize_text(as_dict(index.get(course_id, {})).get("type")) == "Course":
                return course_id
        return node_id if node_id in index else "root"

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
        names.update(
            normalize_text(alias).lower()
            for alias in as_list(node.get("aliases"))
            if normalize_text(alias)
        )
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
        nodes = [node for node in graph["nodes"] if isinstance(node, dict)]
        edges = [edge for edge in graph["edges"] if isinstance(edge, dict)]
        node_ids = {
            normalize_text(node.get("id"))
            for node in nodes
            if normalize_text(node.get("id"))
        }
        normalized_node_ids = {node_id.lower() for node_id in node_ids}
        node_names = set(normalized_node_ids)
        for node in nodes:
            node_names.update(
                normalize_text(value).lower()
                for value in [node.get("label"), node.get("name"), *as_list(node.get("aliases"))]
                if normalize_text(value)
            )

        invalid_edges = 0
        self_loops = 0
        connected_node_ids: set[str] = set()
        for edge in edges:
            source = normalize_text(edge.get("source"))
            target = normalize_text(edge.get("target"))
            if source not in node_ids or target not in node_ids:
                invalid_edges += 1
                continue
            connected_node_ids.update({source, target})
            if source == target:
                self_loops += 1

        questions = self.questions()
        question_ids = {
            normalize_text(question.get("question_id"))
            for question in questions
            if normalize_text(question.get("question_id"))
        }
        mappings = self.question_links()
        mapped_question_ids: set[str] = set()
        invalid_question_ids = 0
        invalid_link_ids = 0
        fallback_name_matches = 0
        unresolved_question_links = 0
        total_question_links = 0
        for mapping in mappings:
            question_id = normalize_text(mapping.get("question_id"))
            if question_id:
                mapped_question_ids.add(question_id)
                if question_id not in question_ids:
                    invalid_question_ids += 1
            for link in as_list(mapping.get("links")):
                if not isinstance(link, dict):
                    continue
                total_question_links += 1
                linked_id = normalize_text(link.get("knowledge_node_id")).lower()
                if linked_id in normalized_node_ids:
                    continue
                invalid_link_ids += 1
                linked_name = normalize_text(link.get("knowledge_name") or link.get("name")).lower()
                if linked_name and linked_name in node_names:
                    fallback_name_matches += 1
                else:
                    unresolved_question_links += 1

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
                "nodes": len(nodes),
                "edges": len(edges),
                "questions": len(questions),
                "question_links": len(mappings),
            },
            "integrity": {
                "invalid_edges": invalid_edges,
                "self_loops": self_loops,
                "isolated_nodes": len(node_ids - connected_node_ids),
                "question_mapping": {
                    "links": total_question_links,
                    "invalid_question_ids": invalid_question_ids,
                    "invalid_node_ids": invalid_link_ids,
                    "fallback_name_matches": fallback_name_matches,
                    "unresolved_links": unresolved_question_links,
                    "questions_without_mapping": len(question_ids - mapped_question_ids),
                },
            },
        }


def allowed_origins() -> set[str]:
    configured = os.getenv("KG_ALLOWED_ORIGINS", "")
    if not configured.strip():
        return DEFAULT_ALLOWED_ORIGINS
    return {origin.strip() for origin in configured.split(",") if origin.strip()}


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    origin = normalize_text(handler.headers.get("Origin"))
    if origin and origin in allowed_origins():
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
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
        graph_path = Path(args.graph)
        paths = DataPaths(
            graph_path,
            Path(args.questions)
            if args.questions
            else first_existing_path(
                [graph_path.parent / "combined_official_questions.json", paths.questions]
            ),
            Path(args.question_links)
            if args.question_links
            else first_existing_path(
                [graph_path.parent / "question_knowledge_links.json", paths.question_links]
            ),
        )
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
