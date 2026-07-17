"""Conservatively extract source-verified multiple-choice questions from legacy .doc files.

The parser only publishes an item when its question number, option block and
answer-key range can all be located in the same original Word document. Other
question types are intentionally left for the stricter source-answer workflow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


VENDOR_DIR = Path(__file__).resolve().parent / ".vendor"
if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))


def normalize_text(value: str) -> str:
    value = str(value or "").replace("\r", "\n")
    value = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n", value)
    return value.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_legacy_doc(path: Path) -> str:
    """Read Unicode text from a Word 97-2003 compound document without Word COM."""
    try:
        import olefile  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 olefile；请先在 work/oop_kg_demo/.vendor 安装该依赖。") from exc

    with olefile.OleFileIO(str(path)) as document:
        if not document.exists("WordDocument"):
            raise ValueError("该文件不是可读取的 Word 97-2003 文档。")
        data = document.openstream("WordDocument").read()
    if len(data) < 32:
        raise ValueError("WordDocument 流过短，无法读取正文。")
    fc_min, fc_mac = struct.unpack_from("<II", data, 24)
    if not (0 <= fc_min <= fc_mac <= len(data)):
        raise ValueError("WordDocument 正文范围无效。")
    return normalize_text(data[fc_min:fc_mac].decode("utf-16le", errors="ignore"))


def find_choice_sections(text: str) -> list[tuple[str, str, str]]:
    """Return (section_name, question_text, answer_key_text) for matched exam sections."""
    choice_heading = re.compile(r"[一1][、．.]?\s*(?:单项)?选择题[^\n]*")
    answer_heading = re.compile(r"(?:标准答案|参考答案)")
    # Do not treat question number "2、" as a level-two section heading.
    second_heading = re.compile(r"(?:^|\n)\s*二[、．.]", re.M)
    sections: list[tuple[str, str, str]] = []

    for heading in choice_heading.finditer(text):
        # Question section ends at the next level-two heading or an answer heading.
        following = text[heading.end() :]
        answer_match = answer_heading.search(following)
        second_match = second_heading.search(following)
        candidates = [match.start() for match in (answer_match, second_match) if match]
        question_end = heading.end() + (min(candidates) if candidates else len(following))
        question_text = text[heading.end() : question_end]

        # A matching answer block must occur after the question section and include
        # another choice heading before the next exam's question section.
        answer_start = question_end
        answer_match = answer_heading.search(text, answer_start)
        if not answer_match:
            continue
        answer_choice = choice_heading.search(text, answer_match.end())
        if not answer_choice:
            continue
        next_second = second_heading.search(text, answer_choice.end())
        answer_end = next_second.start() if next_second else len(text)
        answer_text = text[answer_choice.end() : answer_end]
        if question_text.strip() and answer_text.strip():
            sections.append((normalize_text(heading.group(0)), question_text, answer_text))
    return sections


def split_choice_questions(question_text: str) -> list[dict[str, Any]]:
    # A full stop is a question separator only when it is not the decimal point
    # in a code fragment such as "Visual Studio 6.0".
    marker = re.compile(r"(?<!\d)(\d{1,2})\s*(?:[、．]\s*|\.(?!\d)\s*)")
    matches = list(marker.finditer(question_text))
    questions: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        number = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(question_text)
        raw_block = normalize_text(question_text[match.end() : end])
        option_marker = re.compile(r"(?<![A-Za-z])([A-D])\s*[\.．、]\s*")
        option_matches = list(option_marker.finditer(raw_block))
        if len(option_matches) < 2:
            continue
        stem = normalize_text(raw_block[: option_matches[0].start()])
        options: list[str] = []
        for option_index, option_match in enumerate(option_matches):
            option_end = option_matches[option_index + 1].start() if option_index + 1 < len(option_matches) else len(raw_block)
            options.append(normalize_text(raw_block[option_match.start() : option_end]))
        if stem and len(options) >= 2:
            questions.append({"number": number, "stem": stem, "options": options, "evidence": raw_block})
    return questions


def parse_answer_keys(answer_text: str) -> dict[str, dict[str, str]]:
    """Parse compact answer keys such as '1-5. C D B C C' without guessing."""
    keys: dict[str, dict[str, str]] = {}
    range_pattern = re.compile(
        r"(?P<start>\d{1,2})\s*[-—~至]\s*(?P<end>\d{1,2})\s*[、．.]?\s*"
        r"(?P<tail>.*?)(?=(?:\s+\d{1,2}\s*[-—~至]\s*\d{1,2})|$)"
    )
    for line in answer_text.splitlines():
        for match in range_pattern.finditer(line):
            start, end = int(match.group("start")), int(match.group("end"))
            if end < start or end - start > 30:
                continue
            expected_count = end - start + 1
            answers = re.findall(r"(?<![A-Za-z])[A-D](?![A-Za-z])", match.group("tail"))[:expected_count]
            if len(answers) != expected_count:
                continue
            evidence = normalize_text(match.group(0))
            for offset, answer in enumerate(answers):
                keys[str(start + offset)] = {"answer": answer, "evidence": evidence}
    return keys


def safe_part(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_") or "source"


def build_questions(
    source_file: Path, source_prefix: str, language: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    text = read_legacy_doc(source_file)
    source_hash = sha256_file(source_file)
    accepted: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    sections = find_choice_sections(text)
    source_token = safe_part(source_file.stem)

    for section_index, (section_name, question_text, answer_text) in enumerate(sections, start=1):
        questions = split_choice_questions(question_text)
        answer_keys = parse_answer_keys(answer_text)
        for question in questions:
            answer_item = answer_keys.get(question["number"])
            if not answer_item:
                review.append(
                    {
                        "section_index": section_index,
                        "section": section_name,
                        "question_number": question["number"],
                        "reason": "未能从同一试卷的答案键精确解析该题答案。",
                        "stem_evidence": question["evidence"],
                    }
                )
                continue
            accepted.append(
                {
                    "question_id": f"{source_prefix}_{source_token}_S{section_index:02d}_Q{int(question['number']):02d}",
                    "type": "multiple_choice",
                    "type_label": "选择题",
                    "language": language,
                    "stem": question["stem"],
                    "code": "",
                    "options": question["options"],
                    "answer": answer_item["answer"],
                    "analysis": "",
                    "answer_source": "source_provided",
                    "answer_kind": "standard_answer_key",
                    "answer_status": "source_verified_complete",
                    "answer_confidence": 1.0,
                    "answer_completeness": {
                        "status": "complete",
                        "confidence": 1.0,
                        "reason": "选择题答案由同一来源文档中的题号范围答案键精确展开。",
                    },
                    "formal_import_eligible": True,
                    "difficulty": 2,
                    "difficulty_label": "中等",
                    "abilities": ["概念理解"],
                    "gold_knowledge_points": [],
                    "source": {
                        "kind": "legacy_doc_answer_key",
                        "file": str(source_file),
                        "sha256": source_hash,
                        "section": section_name,
                        "section_index": section_index,
                        "question_number": question["number"],
                        "parser": "legacy_doc_mcq_v1",
                    },
                    "answer_pairing": {
                        "status": "verified",
                        "method": "same_exam_numbered_answer_key",
                        "section": section_name,
                        "question_number": question["number"],
                        "stem_evidence": question["evidence"],
                        "answer_evidence": answer_item["evidence"],
                    },
                }
            )

    report = {
        "source_text_characters": len(text),
        "choice_section_count": len(sections),
        "source_verified_choice_count": len(accepted),
        "review_required_count": len(review),
    }
    return accepted, review, report


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="保守解析带答案键的旧版 .doc 选择题。")
    parser.add_argument("--input", required=True, help="旧版 .doc 试卷路径")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--language", default="C++", help="课程语言/领域")
    parser.add_argument("--source-prefix", default="XDU_CPP", help="题目 ID 前缀")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    source_file = Path(args.input)
    output_dir = Path(args.output_dir)
    questions, review, report = build_questions(source_file, args.source_prefix, args.language)
    question_ids = [item["question_id"] for item in questions]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("生成了重复 question_id，拒绝发布。")

    questions_path = output_dir / "source_answer_complete_questions.json"
    review_path = output_dir / "source_answer_pairing_review.json"
    report_path = output_dir / "legacy_doc_mcq_report.json"
    write_json(questions_path, questions)
    write_json(review_path, {"input": str(source_file), "review_items": review})
    write_json(
        report_path,
        {
            "schema_version": "programming_kg_legacy_doc_mcq_v1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input": str(source_file),
            "questions_output": str(questions_path),
            "review_output": str(review_path),
            **report,
        },
    )
    print(f"来源答案配对通过数量：{len(questions)}")
    print(f"待人工审核项数量：{len(review)}")
    print(f"可入库选择题：{questions_path}")
    print(f"解析报告：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
