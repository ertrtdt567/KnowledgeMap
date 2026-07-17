"""合并历史样例题与通过答案审核的新习题，生成统一正式题库。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LEGACY = "work/oop_kg_demo/output/question_mapping/questions.json"
DEFAULT_REVIEWED = "work/oop_kg_demo/output/programming_kg/questions/official_questions.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/programming_kg/questions"


def load_questions(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path} 必须是由习题对象组成的 JSON 数组。")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_legacy_question(question: dict[str, Any]) -> dict[str, Any]:
    """为早期样例题补齐新版题库所需的答案来源与审核字段。"""
    result = dict(question)
    if not str(result.get("answer", "")).strip():
        raise ValueError(f"历史题 {result.get('question_id', '<unknown>')} 缺少答案，不能进入正式题库。")
    result.setdefault("answer_source", "legacy_provided")
    result.setdefault("answer_kind", "standard_answer")
    result.setdefault("answer_status", "verified")
    result.setdefault("answer_confidence", 1.0)
    result["bank_source"] = "legacy_oop_sample"
    return result


def normalize_reviewed_question(question: dict[str, Any]) -> dict[str, Any]:
    result = dict(question)
    source_verified = (
        result.get("answer_source") in {"provided", "source_provided"}
        and isinstance(result.get("answer_pairing"), dict)
        and result["answer_pairing"].get("status") == "verified"
        and result.get("answer_status") in {"source_verified", "verified"}
    )
    independently_verified = result.get("answer_status") in {"human_verified", "compiler_verified"}
    if (not source_verified and not independently_verified) or not str(result.get("answer", "")).strip():
        raise ValueError(f"补充题 {result.get('question_id', '<unknown>')} 未通过答案审核，不能进入正式题库。")
    result["bank_source"] = "reviewed_supplement"
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="合并旧样例题与通过审核的补充习题。")
    parser.add_argument("--legacy", default=DEFAULT_LEGACY, help="旧样例题 questions.json 路径")
    parser.add_argument("--reviewed", default=DEFAULT_REVIEWED, help="通过审核的补充题 official_questions.json 路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="统一正式题库输出目录")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    legacy = [normalize_legacy_question(item) for item in load_questions(Path(args.legacy))]
    reviewed = [normalize_reviewed_question(item) for item in load_questions(Path(args.reviewed))]

    merged = legacy + reviewed
    ids = [str(item.get("question_id", "")) for item in merged]
    empty_ids = [question_id for question_id in ids if not question_id]
    duplicate_ids = sorted({question_id for question_id in ids if ids.count(question_id) > 1})
    if empty_ids or duplicate_ids:
        raise ValueError(f"题库合并失败：空 ID 数量 {len(empty_ids)}，重复 ID：{duplicate_ids}")

    output_dir = Path(args.output_dir)
    output_path = output_dir / "combined_official_questions.json"
    report_path = output_dir / "combined_question_bank_report.json"
    write_json(output_path, merged)
    write_json(
        report_path,
        {
            "schema_version": "programming_kg_combined_question_bank_v2",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "legacy_input": args.legacy,
            "reviewed_input": args.reviewed,
            "output": str(output_path),
            "total_question_count": len(merged),
            "legacy_sample_count": len(legacy),
            "reviewed_supplement_count": len(reviewed),
            "answer_source_distribution": dict(Counter(str(item.get("answer_source", "")) for item in merged)),
            "answer_status_distribution": dict(Counter(str(item.get("answer_status", "")) for item in merged)),
            "duplicate_question_ids": duplicate_ids,
        },
    )
    print(f"历史样例题数量：{len(legacy)}")
    print(f"审核通过补充题数量：{len(reviewed)}")
    print(f"统一正式题库数量：{len(merged)}")
    print(f"统一题库：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
