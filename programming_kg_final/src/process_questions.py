"""
第五阶段 A：习题数据标准化。

这个脚本把 data/sample_questions.json 里的原始样例题整理成统一格式：

    data/sample_questions.json
    -> output/question_mapping/questions.json
    -> output/question_mapping/question_processing_report.json

它只做格式检查和规范化，不调用大模型，也不写 Neo4j。
这样做的好处是：后面的“知识点映射”和“入库”都可以依赖同一份干净题库。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_INPUT = "work/oop_kg_demo/output/programming_kg/questions/docx_questions_raw.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/programming_kg/questions"

QUESTION_TYPES = {
    "multiple_choice": "选择题",
    "true_false": "判断题",
    "code_reading": "代码阅读题",
    "code_fixing": "代码改错题",
    "code_fill": "编程填空题",
    "short_programming": "简短编程题",
}

DIFFICULTY_LABELS = {
    1: "简单",
    2: "中等",
    3: "较难",
    4: "困难",
    5: "挑战",
}

VALID_ROLES = {"primary", "secondary"}


@dataclass
class ProcessingFiles:
    questions: Path
    report: Path


def normalize_question(raw: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, list[str]]:
    """把单道题转成标准结构，并返回这道题的错误列表。"""
    errors: list[str] = []
    question_id = clean_text(raw.get("question_id")) or f"Q{index:03d}"
    question_type = clean_text(raw.get("type"))

    if question_type not in QUESTION_TYPES:
        errors.append(f"{question_id}: 未知题型 type={question_type!r}")

    difficulty = safe_int(raw.get("difficulty"), default=2)
    if difficulty not in DIFFICULTY_LABELS:
        errors.append(f"{question_id}: difficulty 必须是 1-5 的整数")
        difficulty = max(1, min(difficulty, 5))

    stem = clean_text(raw.get("stem"))
    if not stem:
        errors.append(f"{question_id}: stem 不能为空")

    gold_points = normalize_gold_points(raw.get("gold_knowledge_points"), question_id, errors)

    question = {
        "question_id": question_id,
        "type": question_type,
        "type_label": QUESTION_TYPES.get(question_type, question_type),
        "language": clean_text(raw.get("language")) or "Java",
        "stem": stem,
        "code": normalize_code(raw.get("code")),
        "options": normalize_string_list(raw.get("options")),
        "answer": clean_text(raw.get("answer")),
        "analysis": clean_text(raw.get("analysis")),
        "answer_source": clean_text(raw.get("answer_source")) or ("provided" if clean_text(raw.get("answer")) else "missing"),
        "answer_kind": clean_text(raw.get("answer_kind")) or ("standard_answer" if clean_text(raw.get("answer")) else "unknown"),
        "answer_status": clean_text(raw.get("answer_status")) or ("verified" if clean_text(raw.get("answer")) else "needs_generation"),
        "answer_confidence": safe_float(raw.get("answer_confidence"), default=1.0 if clean_text(raw.get("answer")) else 0.0),
        # 原始答案不能只靠“文档里出现过答案”就直接采信。若上游已完成题干-答案配对，
        # 这里完整保留它的定位证据，供后续正式题库筛选再次检查。
        "answer_pairing": raw.get("answer_pairing") if isinstance(raw.get("answer_pairing"), dict) else {},
        "difficulty": difficulty,
        "difficulty_label": DIFFICULTY_LABELS[difficulty],
        "abilities": normalize_string_list(raw.get("abilities")),
        "gold_knowledge_points": gold_points,
        "source": raw.get("source") if isinstance(raw.get("source"), dict) else {"kind": "manual_sample", "file": "data/sample_questions.json", "index": index},
    }
    return (None if errors else question), errors


def normalize_gold_points(value: Any, question_id: str, errors: list[str]) -> list[dict[str, str]]:
    """整理人工标准答案中的知识点。"""
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{question_id}: gold_knowledge_points 必须是数组")
        return []

    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            errors.append(f"{question_id}: gold_knowledge_points 中存在非对象项")
            continue
        name = clean_text(item.get("name"))
        role = clean_text(item.get("role")) or "secondary"
        if not name:
            errors.append(f"{question_id}: 标准知识点 name 不能为空")
            continue
        if role not in VALID_ROLES:
            errors.append(f"{question_id}: 知识点 {name} 的 role 只能是 primary 或 secondary")
            role = "secondary"
        key = (name, role)
        if key not in seen:
            seen.add(key)
            result.append({"name": name, "role": role})
    return result


def build_report(
    input_path: Path,
    files: ProcessingFiles,
    questions: list[dict[str, Any]],
    errors: list[str],
) -> dict[str, Any]:
    type_counts: dict[str, int] = {}
    ability_counts: dict[str, int] = {}
    difficulty_counts: dict[str, int] = {}
    gold_point_counts: dict[str, int] = {}

    for question in questions:
        type_counts[question["type_label"]] = type_counts.get(question["type_label"], 0) + 1
        difficulty_counts[question["difficulty_label"]] = difficulty_counts.get(question["difficulty_label"], 0) + 1
        for ability in question["abilities"]:
            ability_counts[ability] = ability_counts.get(ability, 0) + 1
        for point in question["gold_knowledge_points"]:
            name = point["name"]
            gold_point_counts[name] = gold_point_counts.get(name, 0) + 1

    return {
        "schema_version": "programming_kg_question_processing_v2",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input": str(input_path),
        "output_questions": str(files.questions),
        "question_count": len(questions),
        "has_error": bool(errors),
        "errors": errors,
        "type_counts": type_counts,
        "difficulty_counts": difficulty_counts,
        "ability_counts": ability_counts,
        "gold_knowledge_point_counts": gold_point_counts,
        "gold_labeled_question_count": sum(1 for question in questions if question["gold_knowledge_points"]),
        "needs_answer_generation_count": sum(1 for question in questions if question.get("answer_status") == "needs_generation"),
        "source_pair_verified_count": sum(
            1 for question in questions if question.get("answer_pairing", {}).get("status") == "verified"
        ),
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_code(value: Any) -> str:
    # 代码保留换行，不做空白压缩，方便后续模型和人工阅读。
    return str(value or "").strip("\n")


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = clean_text(item)
        if text and text not in result:
            result.append(text)
    return result


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="第五阶段 A：习题数据标准化。")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="原始习题 JSON 路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    files = ProcessingFiles(
        questions=output_dir / "questions.json",
        report=output_dir / "question_processing_report.json",
    )

    raw_questions = load_json(input_path)
    if not isinstance(raw_questions, list):
        raise ValueError("习题文件顶层必须是数组。")

    questions: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(raw_questions, start=1):
        if not isinstance(raw, dict):
            errors.append(f"第 {index} 道题不是对象。")
            continue
        question, question_errors = normalize_question(raw, index)
        errors.extend(question_errors)
        if question is None:
            continue
        question_id = question["question_id"]
        if question_id in seen_ids:
            errors.append(f"{question_id}: question_id 重复")
            continue
        seen_ids.add(question_id)
        questions.append(question)

    report = build_report(input_path, files, questions, errors)
    write_json(files.questions, questions)
    write_json(files.report, report)

    print(f"标准习题数量：{len(questions)}")
    print(f"标准习题：{files.questions}")
    print(f"处理报告：{files.report}")
    if errors:
        print(f"发现问题：{len(errors)} 个，详情见 question_processing_report.json")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
