"""Merge question sources that passed both answer pairing and completeness checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def load_bank(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path} 必须是习题对象数组。")
    return payload


def validate_question(question: dict[str, Any], source_path: Path) -> None:
    question_id = str(question.get("question_id", "")).strip()
    pairing = question.get("answer_pairing") if isinstance(question.get("answer_pairing"), dict) else {}
    completeness = question.get("answer_completeness") if isinstance(question.get("answer_completeness"), dict) else {}
    if not question_id:
        raise ValueError(f"{source_path} 中存在空 question_id。")
    if not str(question.get("stem", "")).strip() or not str(question.get("answer", "")).strip():
        raise ValueError(f"题目 {question_id} 缺少题干或答案。")
    if pairing.get("status") != "verified":
        raise ValueError(f"题目 {question_id} 未通过题目-答案来源配对。")
    if completeness.get("status") != "complete" or not question.get("formal_import_eligible"):
        raise ValueError(f"题目 {question_id} 未通过答案完整性审核。")


def content_fingerprint(question: dict[str, Any]) -> str:
    parts = [str(question.get("stem", "")), *[str(item) for item in question.get("options", [])]]
    normalized = "|".join(re.sub(r"\s+", "", part).casefold() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="合并通过来源与完整性审核的正式题库。")
    parser.add_argument("--inputs", nargs="+", required=True, help="一个或多个已审核 questions.json")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    merged: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for raw_path in args.inputs:
        source_path = Path(raw_path)
        questions = load_bank(source_path)
        for question in questions:
            validate_question(question, source_path)
        merged.extend(questions)
        source_counts[str(source_path)] = len(questions)

    ids = [str(item["question_id"]) for item in merged]
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    fingerprints = [content_fingerprint(item) for item in merged]
    duplicate_content = sorted({item for item in fingerprints if fingerprints.count(item) > 1})
    if duplicate_ids or duplicate_content:
        raise ValueError(
            f"拒绝合并：重复 ID {duplicate_ids}；重复题目内容组数量 {len(duplicate_content)}。"
        )

    output_dir = Path(args.output_dir)
    questions_path = output_dir / "verified_questions.json"
    report_path = output_dir / "verified_question_merge_report.json"
    write_json(questions_path, merged)
    write_json(
        report_path,
        {
            "schema_version": "programming_kg_verified_question_merge_v1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "inputs": source_counts,
            "question_count": len(merged),
            "duplicate_id_count": len(duplicate_ids),
            "duplicate_content_count": len(duplicate_content),
            "output": str(questions_path),
        },
    )
    print(f"合并后的可映射题目数量：{len(merged)}")
    print(f"重复 ID 数量：{len(duplicate_ids)}")
    print(f"重复内容数量：{len(duplicate_content)}")
    print(f"统一题库：{questions_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
