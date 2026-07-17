"""
第五阶段 C：习题-知识点映射质量评估。

它把自动映射结果 question_knowledge_links.json 和样例题中的人工标准答案
gold_knowledge_points 做对比，输出 Precision、Recall、F1、主考知识点准确率等指标。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_QUESTIONS = "work/oop_kg_demo/output/programming_kg/questions/official_questions.json"
DEFAULT_LINKS = "work/oop_kg_demo/output/programming_kg/question_mapping/question_knowledge_links.json"
DEFAULT_OUTPUT = "work/oop_kg_demo/output/programming_kg/question_mapping/question_mapping_evaluation.json"


def evaluate_question(question: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    gold_points = question.get("gold_knowledge_points", [])
    links = mapping.get("links", [])

    gold_names = {normalize_name(item.get("name")) for item in gold_points if isinstance(item, dict)}
    predicted_names = {normalize_name(item.get("knowledge_name")) for item in links if isinstance(item, dict)}
    gold_names.discard("")
    predicted_names.discard("")

    true_positive = gold_names & predicted_names
    false_positive = predicted_names - gold_names
    false_negative = gold_names - predicted_names

    precision = safe_div(len(true_positive), len(predicted_names))
    recall = safe_div(len(true_positive), len(gold_names))
    f1 = safe_div(2 * precision * recall, precision + recall)

    gold_primary = {
        normalize_name(item.get("name"))
        for item in gold_points
        if isinstance(item, dict) and item.get("role") == "primary"
    }
    predicted_primary = {
        normalize_name(item.get("knowledge_name"))
        for item in links
        if isinstance(item, dict) and item.get("role") == "primary"
    }
    gold_primary.discard("")
    predicted_primary.discard("")

    top_1 = normalize_name(links[0].get("knowledge_name")) if links else ""
    top_3 = {normalize_name(item.get("knowledge_name")) for item in links[:3] if isinstance(item, dict)}
    primary_hit = bool(gold_primary & predicted_primary)
    top_1_hit = top_1 in gold_names if top_1 else False
    top_3_hit = bool(gold_names & top_3)

    return {
        "question_id": question["question_id"],
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "primary_hit": primary_hit,
        "top_1_hit": top_1_hit,
        "top_3_hit": top_3_hit,
        "gold": sorted(gold_names),
        "predicted": sorted(predicted_names),
        "true_positive": sorted(true_positive),
        "false_positive": sorted(false_positive),
        "false_negative": sorted(false_negative),
        "predicted_primary": sorted(predicted_primary),
        "gold_primary": sorted(gold_primary),
    }


def build_report(
    questions_path: Path,
    links_path: Path,
    output_path: Path,
    per_question: list[dict[str, Any]],
) -> dict[str, Any]:
    count = len(per_question)
    avg_precision = average(item["precision"] for item in per_question)
    avg_recall = average(item["recall"] for item in per_question)
    avg_f1 = average(item["f1"] for item in per_question)
    primary_accuracy = safe_div(sum(1 for item in per_question if item["primary_hit"]), count)
    top_1_accuracy = safe_div(sum(1 for item in per_question if item["top_1_hit"]), count)
    top_3_accuracy = safe_div(sum(1 for item in per_question if item["top_3_hit"]), count)
    unmapped_rate = safe_div(sum(1 for item in per_question if not item["predicted"]), count)

    return {
        "schema_version": "programming_kg_question_mapping_evaluation_v2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_questions": str(questions_path),
        "input_links": str(links_path),
        "output_report": str(output_path),
        "evaluated_question_count": count,
        "metrics": {
            "precision": round(avg_precision, 4),
            "recall": round(avg_recall, 4),
            "f1": round(avg_f1, 4),
            "primary_accuracy": round(primary_accuracy, 4),
            "top_1_accuracy": round(top_1_accuracy, 4),
            "top_3_accuracy": round(top_3_accuracy, 4),
            "unmapped_rate": round(unmapped_rate, 4),
        },
        "per_question": per_question,
        "metric_explanation": {
            "precision": "自动映射出的知识点中，有多少属于人工标准答案。",
            "recall": "人工标准答案中的知识点，有多少被自动映射找回。",
            "f1": "precision 和 recall 的综合分数。",
            "primary_accuracy": "自动判断的主考知识点是否命中人工主考知识点。",
            "top_1_accuracy": "排序第一的知识点是否属于人工标准答案。",
            "top_3_accuracy": "前三个知识点中是否包含人工标准答案。",
            "unmapped_rate": "没有映射出任何知识点的题目比例。",
        },
    }


def normalize_name(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def average(values: Any) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第五阶段 C：习题-知识点映射质量评估。")
    parser.add_argument("--questions", default=DEFAULT_QUESTIONS, help="标准习题 questions.json 路径")
    parser.add_argument("--links", default=DEFAULT_LINKS, help="自动映射 question_knowledge_links.json 路径")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="评估报告输出路径")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    questions_path = Path(args.questions)
    links_path = Path(args.links)
    output_path = Path(args.output)

    questions = load_json(questions_path)
    mappings = load_json(links_path)
    if not isinstance(questions, list) or not isinstance(mappings, list):
        raise ValueError("questions 和 links 顶层都必须是数组。")

    mapping_by_id = {item.get("question_id"): item for item in mappings if isinstance(item, dict)}
    labelled_questions = [question for question in questions if question.get("gold_knowledge_points")]
    per_question = [evaluate_question(question, mapping_by_id.get(question["question_id"], {})) for question in labelled_questions]
    report = build_report(questions_path, links_path, output_path, per_question)
    report["total_question_count"] = len(questions)
    report["unlabelled_question_count"] = len(questions) - len(labelled_questions)
    report["evaluation_status"] = "ready" if labelled_questions else "pending_manual_gold_labels"
    write_json(output_path, report)

    metrics = report["metrics"]
    print(f"评估题目数：{report['evaluated_question_count']}（总题目 {report['total_question_count']}）")
    print(f"Precision：{metrics['precision']}")
    print(f"Recall：{metrics['recall']}")
    print(f"F1：{metrics['f1']}")
    print(f"主考知识点命中率：{metrics['primary_accuracy']}")
    print(f"评估报告：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
