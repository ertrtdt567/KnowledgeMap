"""Parse lab-programming DOCX files whose questions use ``ExamN.cpp`` headings.

The parser is deliberately conservative: a question is emitted only when the
following paragraph contains a complete problem statement with input/output
sections. Short titles and sample fragments stay in the review list.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from docx import Document


HEADING_RE = re.compile(r"(?:^|\s)(?:exam\s*\d+\s*\.(?:cpp|c)|exam\d+\.(?:cpp|c))\s*$", re.IGNORECASE)
COMPLETE_MARKERS = ("输入", "输出")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="解析 ExamN.cpp 段落式上机编程题 DOCX。")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--course", default="数据结构")
    parser.add_argument("--language", default="C++")
    parser.add_argument("--source-prefix", default="XDU_DS_LAB")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    document = Document(args.input)
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
    questions: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []

    for index, text in enumerate(paragraphs):
        if not HEADING_RE.search(normalize(text)):
            continue
        next_index = index + 1
        statement = paragraphs[next_index].strip() if next_index < len(paragraphs) else ""
        compact = normalize(statement)
        record = {
            "source_paragraph": index + 1,
            "heading": text,
            "statement": statement,
            "course": args.course,
            "language": args.language,
            "source": {"file": args.input, "paragraph": index + 1, "kind": "lab_programming_docx"},
            "answer": "",
            "answer_status": "missing",
            "answer_source": "not_provided",
            "import_status": "candidate",
        }
        if statement and all(marker in compact for marker in COMPLETE_MARKERS):
            question_number = len(questions) + 1
            questions.append(
                {
                    "question_id": f"{args.source_prefix}_{question_number:03d}",
                    "type": "programming",
                    "type_label": "编程题",
                    "stem": statement,
                    "code": "",
                    "options": [],
                    "difficulty": None,
                    "difficulty_label": "待评估",
                    "abilities": ["代码实现"],
                    **record,
                }
            )
        else:
            incomplete.append({**record, "reason": "未发现可独立使用的完整输入/输出题面。"})

    payload = {
        "schema_version": "lab_programming_question_candidates_v1",
        "questions": questions,
        "incomplete_candidates": incomplete,
        "summary": {
            "formal_question_count": 0,
            "candidate_question_count": len(questions),
            "incomplete_candidate_count": len(incomplete),
            "answer_verified_count": 0,
        },
    }
    report = {
        "input": args.input,
        "paragraph_count": len(paragraphs),
        "recognized_heading_count": len(questions) + len(incomplete),
        "candidate_question_count": len(questions),
        "incomplete_candidate_count": len(incomplete),
        "policy": "无答案的上机题只进入候选池，不调用模型补写答案。",
    }
    write_json(Path(args.output), payload)
    write_json(Path(args.report), report)
    print(f"完整候选习题数：{len(questions)}")
    print(f"不完整候选数：{len(incomplete)}")
    print(f"候选习题：{args.output}")
    print(f"解析报告：{args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
