import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from api_server import DataPaths, KnowledgeGraphStore


class KnowledgeGraphStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        base = Path(self.temp_dir.name)
        graph = {
            "nodes": [
                {"id": "course_python", "label": "Python", "type": "Course"},
                {"id": "domain", "label": "课程", "type": "KnowledgeDomain"},
                {"id": "unit", "label": "单元", "type": "KnowledgeUnit"},
                {"id": "point", "label": "排序", "type": "KnowledgePoint", "aliases": ["排序算法"]},
                {"id": "example", "label": "示例", "type": "CodeExample"},
                {"id": "lonely", "label": "孤立", "type": "KnowledgePoint"},
            ],
            "edges": [
                {"id": "course-domain", "source": "domain", "target": "course_python", "type": "part_of"},
                {"id": "domain-unit", "source": "unit", "target": "domain", "type": "part_of"},
                {"id": "unit-point", "source": "point", "target": "unit", "type": "part_of"},
                {"id": "example-point", "source": "point", "target": "example", "type": "has_code_example"},
                {"id": "self-loop", "source": "unit", "target": "unit", "type": "has_syntax"},
                {"id": "invalid", "source": "missing", "target": "point", "type": "part_of"},
            ],
        }
        questions = [{"question_id": "Q1", "stem": "排序题", "type": "single_choice"}]
        links = [
            {
                "question_id": "Q1",
                "links": [{"knowledge_node_id": "old_sort", "knowledge_name": "排序"}],
            }
        ]
        graph_path = base / "graph.json"
        questions_path = base / "questions.json"
        links_path = base / "links.json"
        graph_path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
        questions_path.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
        links_path.write_text(json.dumps(links, ensure_ascii=False), encoding="utf-8")
        self.store = KnowledgeGraphStore(DataPaths(graph_path, questions_path, links_path))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_root_is_a_three_layer_course_overview(self) -> None:
        root = self.store.frontend_graph("root")
        nodes = {node["id"]: node for node in root["nodes"]}
        self.assertEqual("面向编程领域的知识图谱", nodes["course_graph_hub"]["label"])
        self.assertTrue(nodes["course_graph_hub"]["systemNode"])
        self.assertEqual({"x": 0, "y": 0}, nodes["course_graph_hub"]["position"])
        self.assertEqual("python", nodes["course_python"]["label"])
        self.assertEqual(1, nodes["course_python"]["layer"])
        self.assertEqual(2, nodes["domain"]["layer"])
        self.assertEqual(3, nodes["unit"]["layer"])
        self.assertNotIn("point", nodes)
        self.assertIn("position", nodes["course_python"])
        self.assertIn("position", nodes["domain"])
        self.assertIn(
            ("course_graph_hub", "course_python", "包含"),
            {(edge["source"], edge["target"], edge["label"]) for edge in root["edges"]},
        )
        self.assertIn(
            ("course_python", "domain", "包含"),
            {(edge["source"], edge["target"], edge["label"]) for edge in root["edges"]},
        )

    def test_knowledge_unit_subgraph_contains_its_point(self) -> None:
        graph = self.store.frontend_graph("unit")
        nodes = {node["id"]: node for node in graph["nodes"]}
        visible_ids = set(nodes)
        self.assertTrue({"unit", "point"}.issubset(visible_ids))
        self.assertEqual(1, nodes["unit"]["layer"])
        self.assertEqual(2, nodes["point"]["layer"])

    def test_search_and_example_jump_resolve_to_the_correct_graph(self) -> None:
        result = next(item for item in self.store.search("排序") if item["id"] == "point")
        self.assertEqual("point", result["graphId"])
        self.assertEqual("point", self.store.search_graph_id("example"))

    def test_question_mapping_can_fallback_to_knowledge_name(self) -> None:
        self.assertEqual(["Q1"], [item["question_id"] for item in self.store.questions_for_knowledge("point")])

    def test_health_reports_graph_and_mapping_integrity(self) -> None:
        integrity = self.store.health()["integrity"]
        self.assertEqual(1, integrity["invalid_edges"])
        self.assertEqual(1, integrity["self_loops"])
        self.assertEqual(1, integrity["isolated_nodes"])
        self.assertEqual(1, integrity["question_mapping"]["invalid_node_ids"])
        self.assertEqual(1, integrity["question_mapping"]["fallback_name_matches"])
        self.assertEqual(0, integrity["question_mapping"]["unresolved_links"])


if __name__ == "__main__":
    unittest.main()
