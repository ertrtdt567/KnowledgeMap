"""将答案来源明确且复核通过的习题提升为正式题库，其余题目进入人工审核清单。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_INPUT = "work/oop_kg_demo/output/programming_kg/questions/questions_with_answers.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/programming_kg/questions"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_approved(question: dict[str, Any], min_confidence: float) -> bool:
    """教师提供答案可直接使用；模型答案必须经过独立复核并达到阈值。"""
    source = str(question.get("answer_source", ""))
    if source == "provided" and str(question.get("answer", "")).strip():
        return True
    return (
        source == "llm_generated"
        and str(question.get("answer_status", "")) == "verified"
        and float(question.get("answer_confidence", 0.0) or 0.0) >= min_confidence
        and bool(str(question.get("answer", "")).strip())
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将已复核习题筛选为正式题库。")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="答案补全后的 questions_with_answers.json")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="正式题库与审核清单输出目录")
    parser.add_argument("--min-confidence", type=float, default=0.85, help="模型答案进入正式题库的最小置信度")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    questions = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(questions, list):
        raise ValueError("questions_with_answers.json 顶层必须是数组。")

    approved = [item for item in questions if isinstance(item, dict) and is_approved(item, args.min_confidence)]
    review = [item for item in questions if isinstance(item, dict) and item not in approved]
    output_dir = Path(args.output_dir)
    official_path = output_dir / "official_questions.json"
    review_path = output_dir / "question_bank_review_report.json"
    write_json(official_path, approved)
    write_json(
        review_path,
        {
            "schema_version": "programming_kg_question_curation_v1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input": args.input,
            "official_questions": str(official_path),
            "total_question_count": len(questions),
            "official_question_count": len(approved),
            "review_required_count": len(review),
            "min_confidence": args.min_confidence,
            "review_items": [
                {
                    "question_id": item.get("question_id"),
                    "answer_source": item.get("answer_source"),
                    "answer_status": item.get("answer_status"),
                    "answer_confidence": item.get("answer_confidence"),
                }
                for item in review
            ],
        },
    )
    print(f"正式题库数量：{len(approved)}")
    print(f"待人工审核数量：{len(review)}")
    print(f"正式题库：{official_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

