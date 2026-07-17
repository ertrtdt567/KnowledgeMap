"""从“题干和原始答案在同一 PDF 页面”的试题资料中保守抽取可追溯习题。

此脚本只负责整理原文已有答案，绝不生成答案。每一题必须同时满足：
1. 题干证据和答案证据均能在同一页原文中精确找到；
2. 题干在答案之前；
3. 答案位于同一小节的下一题之前；
4. 同一来源页内的“小节 + 题号”唯一。

任一条件不满足，题目不会进入 source_verified_questions.json，而会进入审核清单。
这样可以防止扫描/版式解析导致答案错挂到相邻题目。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from map_questions_to_knowledge import LLMClient


QUESTION_TYPE_LABELS = {
    "multiple_choice": "选择题",
    "true_false": "判断题",
    "code_reading": "代码阅读题",
    "code_fixing": "代码改错题",
    "code_fill": "编程填空题",
    "short_programming": "简短编程题",
}


def normalize_text(value: str) -> str:
    """用于原文定位的保守规范化：只折叠空白，不删除任何实词或标点。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_pdf_pages(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("缺少 pypdf，无法读取 PDF。") from exc
    reader = PdfReader(str(path))
    return [normalize_text(page.extract_text() or "") for page in reader.pages]


def prompt_for_page(source_name: str, page_number: int, page_text: str, language: str) -> list[dict[str, str]]:
    system = """你是考试题库资料整理员。只抽取当前 PDF 单页中同时出现完整题干和原始答案的题目。
不要推理、补写、改正或生成任何答案。题干和答案必须都能作为该页原文的连续片段精确复制。
若题目或答案跨页、答案不完整、答案属于下一题、或无法确认对应关系，就不要输出该题。
按页面中原始顺序输出 JSON 对象：{
  \"items\": [{
    \"section\": \"简答题/读程题/改错题等当前页小节名\",
    \"question_number\": \"原题号\",
    \"type\": \"multiple_choice|true_false|code_reading|code_fixing|code_fill|short_programming\",
    \"stem\": \"原题干，不含答案\",
    \"code\": \"题内代码；没有则空字符串\",
    \"options\": [\"原选项\"],
    \"answer\": \"原始答案/输出结果/原始给出的填空内容\",
    \"analysis\": \"原文已有解析；没有则空字符串\",
    \"stem_evidence\": \"stem 中可在本页原文连续找到的非空片段\",
    \"answer_evidence\": \"answer 中可在本页原文连续找到的非空片段\"
  }]
}。禁止把题号、题干或答案改写成概括性文字。"""
    payload = {
        "source_file": source_name,
        "page_number": page_number,
        "language": language,
        "page_text": page_text,
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def prompt_for_answer_completeness(question: dict[str, Any]) -> list[dict[str, str]]:
    """Judge answer coverage only; this prompt must never repair an answer."""
    system = """你是考试题库答案质检员。只判断已有原始答案能否完整回答题干，绝不补写、纠错、润色或生成答案。

请逐项检查题干中的明确要求。若答案遗漏任何关键子问题，返回 partial；若答案与题意不符或无法判断，返回 insufficient；只有完整覆盖全部明确要求才返回 complete。
只输出 JSON：{
  "status": "complete|partial|insufficient",
  "confidence": 0.0,
  "required_aspects": ["题干要求1"],
  "covered_aspects": ["已覆盖要求"],
  "missing_aspects": ["遗漏要求"],
  "reason": "只说明判定原因，不得给出补全后的答案"
}"""
    payload = {
        "question_id": question["question_id"],
        "type": question["type"],
        "stem": question["stem"],
        "options": question["options"],
        "source_answer": question["answer"],
        "source_analysis": question["analysis"],
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def as_text(value: Any) -> str:
    return str(value or "").strip()


def as_options(value: Any) -> list[str]:
    return [as_text(item) for item in value] if isinstance(value, list) else []


def infer_difficulty(question_type: str) -> int:
    return 3 if question_type in {"code_reading", "code_fixing", "code_fill", "short_programming"} else 2


def infer_abilities(question_type: str) -> list[str]:
    return {
        "multiple_choice": ["概念理解"],
        "true_false": ["概念辨析"],
        "code_reading": ["代码阅读", "运行结果分析"],
        "code_fixing": ["错误定位", "代码修正"],
        "code_fill": ["代码补全", "程序设计"],
        "short_programming": ["程序设计", "代码实现"],
    }.get(question_type, ["概念理解"])


def validate_page_items(
    raw_items: Any,
    page_text: str,
    source_file: Path,
    source_hash: str,
    page_number: int,
    language: str,
    source_prefix: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """验证模型提出的配对。验证失败只记录原因，绝不降级为“自动配对”。"""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    page_norm = normalize_text(page_text)
    candidates = raw_items if isinstance(raw_items, list) else []
    staged: list[dict[str, Any]] = []

    for raw in candidates:
        if not isinstance(raw, dict):
            rejected.append({"page": page_number, "reason": "模型返回了非对象题目。"})
            continue
        section = as_text(raw.get("section")) or "未分小节"
        number = as_text(raw.get("question_number"))
        stem = as_text(raw.get("stem"))
        answer = as_text(raw.get("answer"))
        stem_evidence = normalize_text(as_text(raw.get("stem_evidence")))
        answer_evidence = normalize_text(as_text(raw.get("answer_evidence")))
        qtype = as_text(raw.get("type"))
        reasons: list[str] = []
        if not number or not stem or not answer:
            reasons.append("题号、题干或答案为空。")
        if qtype not in QUESTION_TYPE_LABELS:
            reasons.append(f"题型不在允许集合：{qtype!r}。")
        if len(stem_evidence) < 8 or stem_evidence not in page_norm:
            reasons.append("题干证据未能在本页原文中精确定位。")
        if len(answer_evidence) < 1 or answer_evidence not in page_norm:
            reasons.append("答案证据未能在本页原文中精确定位。")
        if answer_evidence and normalize_text(answer) not in answer_evidence:
            reasons.append("答案文本不是答案证据的连续内容，存在改写或补写风险。")
        question_offset = page_norm.find(stem_evidence) if stem_evidence else -1
        answer_offset = page_norm.find(answer_evidence) if answer_evidence else -1
        if question_offset < 0 or answer_offset < 0 or answer_offset <= question_offset:
            reasons.append("答案没有位于题干之后。")
        if reasons:
            rejected.append(
                {
                    "page": page_number,
                    "section": section,
                    "question_number": number,
                    "reason": "；".join(reasons),
                    "model_item": raw,
                }
            )
            continue
        staged.append(
            {
                "raw": raw,
                "section": section,
                "number": number,
                "stem": stem,
                "answer": answer,
                "stem_evidence": stem_evidence,
                "answer_evidence": answer_evidence,
                "question_offset": question_offset,
                "answer_offset": answer_offset,
            }
        )

    staged.sort(key=lambda item: item["question_offset"])
    seen_keys: set[tuple[str, str]] = set()
    for index, item in enumerate(staged):
        key = (item["section"], item["number"])
        if key in seen_keys:
            rejected.append({"page": page_number, "section": key[0], "question_number": key[1], "reason": "同页小节内题号重复，无法确认答案归属。", "model_item": item["raw"]})
            continue
        seen_keys.add(key)
        next_question_offset = staged[index + 1]["question_offset"] if index + 1 < len(staged) else len(page_norm)
        if item["answer_offset"] >= next_question_offset:
            rejected.append({"page": page_number, "section": item["section"], "question_number": item["number"], "reason": "答案落在下一题题干之后，拒绝自动配对。", "model_item": item["raw"]})
            continue

        raw = item["raw"]
        qtype = as_text(raw.get("type"))
        safe_section = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", item["section"]).strip("_") or "section"
        safe_number = re.sub(r"[^0-9A-Za-z]+", "_", item["number"]).strip("_") or str(index + 1)
        question_id = f"{source_prefix}_P{page_number:02d}_{safe_section}_{safe_number}"
        accepted.append(
            {
                "question_id": question_id,
                "type": qtype,
                "type_label": QUESTION_TYPE_LABELS[qtype],
                "language": language,
                "stem": item["stem"],
                "code": as_text(raw.get("code")),
                "options": as_options(raw.get("options")),
                "answer": item["answer"],
                "analysis": as_text(raw.get("analysis")),
                "answer_source": "source_provided",
                "answer_kind": "standard_answer",
                "answer_status": "source_verified",
                "answer_confidence": 1.0,
                "difficulty": infer_difficulty(qtype),
                "difficulty_label": {2: "中等", 3: "较难"}[infer_difficulty(qtype)],
                "abilities": infer_abilities(qtype),
                "gold_knowledge_points": [],
                "source": {
                    "kind": "inline_answer_pdf",
                    "file": str(source_file),
                    "sha256": source_hash,
                    "page": page_number,
                    "section": item["section"],
                    "question_number": item["number"],
                    "parser": "inline_answer_pdf_v1",
                },
                "answer_pairing": {
                    "status": "verified",
                    "method": "same_page_source_span_and_order",
                    "source_file": str(source_file),
                    "source_sha256": source_hash,
                    "question_page": page_number,
                    "answer_page": page_number,
                    "section": item["section"],
                    "question_number": item["number"],
                    "stem_evidence": item["stem_evidence"],
                    "answer_evidence": item["answer_evidence"],
                    "stem_offset": item["question_offset"],
                    "answer_offset": item["answer_offset"],
                    "next_question_offset": next_question_offset,
                },
            }
        )
    return accepted, rejected


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_answer_review(raw: Any) -> dict[str, Any]:
    """Reject malformed review results instead of upgrading an answer by default."""
    data = raw if isinstance(raw, dict) else {}
    status = as_text(data.get("status"))
    if status not in {"complete", "partial", "insufficient"}:
        status = "insufficient"
    confidence = data.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "status": status,
        "confidence": max(0.0, min(1.0, confidence)),
        "required_aspects": [as_text(item) for item in data.get("required_aspects", []) if as_text(item)],
        "covered_aspects": [as_text(item) for item in data.get("covered_aspects", []) if as_text(item)],
        "missing_aspects": [as_text(item) for item in data.get("missing_aspects", []) if as_text(item)],
        "reason": as_text(data.get("reason")) or "答案完整性结论不明确。",
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="保守抽取 PDF 内同页原始题干-答案配对。")
    parser.add_argument("--input", required=True, help="包含原始答案的 PDF 路径")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--language", default="Java", help="习题编程语言")
    parser.add_argument("--source-prefix", default="XDU_EXAM", help="生成 question_id 的前缀")
    parser.add_argument("--provider", default="qwen", choices=["qwen", "deepseek"], help="用于版式结构化的 API 提供方")
    parser.add_argument("--model", default=None, help="模型名称")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible API 地址")
    parser.add_argument("--timeout", type=int, default=120, help="单页 API 超时秒数")
    parser.add_argument("--retries", type=int, default=2, help="单页 API 重试次数")
    parser.add_argument("--limit-pages", type=int, default=0, help="仅处理前 N 页；0 表示全部")
    parser.add_argument("--no-llm", action="store_true", help="仅输出来源清单，不调用 API")
    parser.add_argument("--no-answer-completeness-review", action="store_true", help="跳过原始答案完整性审查；不建议用于正式入库。")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    source_file = Path(args.input)
    output_dir = Path(args.output_dir)
    pages = read_pdf_pages(source_file)
    source_hash = sha256_file(source_file)
    selected_pages = pages[: args.limit_pages] if args.limit_pages else pages
    cache_dir = output_dir / "inline_answer_pdf_cache"
    llm = None if args.no_llm else LLMClient(args.provider, args.model, args.base_url, args.timeout, args.retries, cache_dir, True)
    accepted: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    answer_review_items: list[dict[str, Any]] = []

    for page_number, page_text in enumerate(selected_pages, start=1):
        if not page_text:
            review_items.append({"page": page_number, "reason": "该页无可提取文本。"})
            continue
        if llm is None:
            review_items.append({"page": page_number, "reason": "未调用结构化 API；本页只保留为待处理来源。"})
            continue
        print(f"[{page_number}/{len(selected_pages)}] 结构化原始题干与答案...", flush=True)
        try:
            result = llm.complete_json(prompt_for_page(source_file.name, page_number, page_text, args.language))
        except Exception as exc:
            review_items.append({"page": page_number, "reason": f"API 结构化失败：{exc}"})
            continue
        page_accepted, page_rejected = validate_page_items(
            result.get("items"), page_text, source_file, source_hash, page_number, args.language, args.source_prefix
        )
        accepted.extend(page_accepted)
        review_items.extend(page_rejected)
        print(f"[{page_number}/{len(selected_pages)}] 通过配对校验 {len(page_accepted)} 题，待审核 {len(page_rejected)} 项", flush=True)

    # Source-span verification proves that an answer belongs to a question, but
    # it does not prove that the answer covers every sub-question. Audit that
    # distinction before a source-paired question may become formally usable.
    if llm is not None and not args.no_answer_completeness_review:
        for index, question in enumerate(accepted, start=1):
            print(f"[答案审查 {index}/{len(accepted)}] 检查原始答案完整性...", flush=True)
            try:
                audit = validate_answer_review(llm.complete_json(prompt_for_answer_completeness(question)))
            except Exception as exc:
                audit = {
                    "status": "insufficient",
                    "confidence": 0.0,
                    "required_aspects": [],
                    "covered_aspects": [],
                    "missing_aspects": [],
                    "reason": f"答案完整性审查 API 失败：{exc}",
                }
            question["answer_completeness"] = audit
            question["answer_status"] = "source_verified_complete" if audit["status"] == "complete" else "source_verified_review_required"
            question["formal_import_eligible"] = audit["status"] == "complete"
            if audit["status"] != "complete":
                answer_review_items.append(
                    {
                        "question_id": question["question_id"],
                        "status": audit["status"],
                        "reason": audit["reason"],
                        "missing_aspects": audit["missing_aspects"],
                        "source": question["source"],
                    }
                )
    else:
        for question in accepted:
            question["answer_completeness"] = {"status": "not_reviewed", "reason": "未执行答案完整性审查。"}
            question["answer_status"] = "source_verified_review_required"
            question["formal_import_eligible"] = False
            answer_review_items.append({"question_id": question["question_id"], "status": "not_reviewed", "reason": "未执行答案完整性审查。", "source": question["source"]})

    ids = [item["question_id"] for item in accepted]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"生成了重复 question_id，拒绝输出正式候选：{duplicates}")

    questions_path = output_dir / "source_verified_questions.json"
    review_path = output_dir / "source_answer_pairing_review.json"
    formal_questions_path = output_dir / "source_answer_complete_questions.json"
    completeness_review_path = output_dir / "source_answer_completeness_review.json"
    write_json(questions_path, accepted)
    write_json(formal_questions_path, [item for item in accepted if item.get("formal_import_eligible")])
    write_json(
        review_path,
        {
            "schema_version": "programming_kg_inline_source_answer_pairing_v1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input": str(source_file),
            "input_sha256": source_hash,
            "page_count": len(pages),
            "processed_page_count": len(selected_pages),
            "source_verified_question_count": len(accepted),
            "review_required_count": len(review_items),
            "answer_complete_question_count": sum(1 for item in accepted if item.get("formal_import_eligible")),
            "answer_completeness_review_required_count": len(answer_review_items),
            "questions_output": str(questions_path),
            "formal_questions_output": str(formal_questions_path),
            "review_items": review_items,
        },
    )
    write_json(
        completeness_review_path,
        {
            "schema_version": "programming_kg_source_answer_completeness_v1",
            "input": str(source_file),
            "source_paired_question_count": len(accepted),
            "formal_import_eligible_count": sum(1 for item in accepted if item.get("formal_import_eligible")),
            "review_required_count": len(answer_review_items),
            "review_items": answer_review_items,
        },
    )
    print(f"来源答案配对通过数量：{len(accepted)}")
    print(f"待人工审核项数量：{len(review_items)}")
    print(f"答案完整、可入库题目数量：{sum(1 for item in accepted if item.get('formal_import_eligible'))}")
    print(f"答案完整性待审核项数量：{len(answer_review_items)}")
    print(f"来源已验证题库：{questions_path}")
    print(f"可入库题库：{formal_questions_path}")
    print(f"配对审核报告：{review_path}")
    print(f"答案完整性审核报告：{completeness_review_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
