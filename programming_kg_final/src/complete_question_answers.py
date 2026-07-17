"""为缺少答案的结构化习题生成并复核答案，保留完整可信度与来源记录。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from map_questions_to_knowledge import LLMClient


DEFAULT_INPUT = "work/oop_kg_demo/output/programming_kg/questions/questions.json"
DEFAULT_OUTPUT_DIR = "work/oop_kg_demo/output/programming_kg/questions"

# 这些题已在 2026-07-11 的人工抽查中发现事实错误或题面解析缺失。
# 即使模型再次给出高置信度，也不能自动进入正式题库。
KNOWN_REVIEW_ISSUES = {
    "CPP_DOCX_001": "题目要求不修改 main，但当前题面抽取把关键语句与 main 分离，需要回看原文重建题面。",
    "CPP_DOCX_011": "类型转换与重载解析答案存在编译和语义问题，必须由 C++ 编译器与人工共同复核。",
    "CPP_DOCX_021": "旧答案误称析构函数名中的空格非法；真正确定的问题是构造函数不能声明 void 返回类型。",
    "CPP_DOCX_022": "旧答案漏掉派生类访问基类 private 成员 x 的核心错误。",
    "CPP_DOCX_024": "旧答案漏掉非标准 void main，应同时检查静态/非静态成员调用。",
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_float(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


class AnswerCompleter:
    def __init__(self, llm: LLMClient | None, min_confidence: float) -> None:
        self.llm = llm
        self.min_confidence = min_confidence
        self.review_items: list[dict[str, Any]] = []

    def complete(self, question: dict[str, Any]) -> dict[str, Any]:
        result = dict(question)
        if str(result.get("answer", "")).strip():
            # 已有答案不等于已完成配对。只有上游记录了可回溯的原文题干-答案证据，
            # 才能把它标记为来源已验证；其余情况一律留给人工审核。
            pairing = result.get("answer_pairing") if isinstance(result.get("answer_pairing"), dict) else {}
            if pairing.get("status") == "verified":
                result["answer_source"] = result.get("answer_source") or "source_provided"
                result["answer_kind"] = result.get("answer_kind") or "standard_answer"
                result["answer_status"] = "source_verified"
                result["answer_confidence"] = 1.0
            else:
                result["answer_status"] = "needs_review"
                result["answer_confidence"] = 0.0
                self._review(result, "已有答案缺少可回溯的题干-答案配对证据，不能自动进入正式题库。")
            return result
        if self.llm is None:
            result["answer_status"] = "needs_review"
            result["answer_source"] = "missing"
            self._review(result, "未调用 API，无法为缺答案题目生成参考解答。")
            return result
        try:
            generated = self.llm.complete_json(build_generation_prompt(result))
            verified = self.llm.complete_json(build_verification_prompt(result, generated))
        except Exception as exc:
            result["answer_status"] = "needs_review"
            result["answer_source"] = "llm_failed"
            self._review(result, f"API 生成或复核失败：{exc}")
            return result

        answer_kind = str(generated.get("answer_kind", "reference_solution"))
        answer = str(verified.get("answer") or generated.get("answer") or "").strip()
        analysis = str(verified.get("analysis") or generated.get("analysis") or "").strip()
        confidence = min(safe_float(generated.get("confidence")), safe_float(verified.get("confidence")))
        accepted = bool(verified.get("accepted", False)) and bool(answer)
        # 同一个模型的二次回答只能算模型自审，不能等同于独立验证。
        status = "model_verified" if accepted and confidence >= self.min_confidence else "needs_review"
        result.update(
            {
                "answer": answer,
                "analysis": analysis,
                "answer_source": "llm_generated",
                "answer_kind": "reference_solution" if answer_kind == "reference_solution" else "standard_answer",
                "answer_status": status,
                "answer_confidence": round(confidence, 4),
                "answer_generation": {"generated": generated, "verification": verified},
                "verification_method": "same_model_review",
            }
        )
        known_issue = KNOWN_REVIEW_ISSUES.get(str(result.get("question_id", "")))
        if known_issue:
            result["answer_status"] = "needs_review"
            result["known_review_issue"] = known_issue
            self._review(result, known_issue)
        elif status == "model_verified":
            self._review(result, "仅完成同模型自审，仍需人工确认或编译/测试验证后才能进入正式题库。")
        else:
            self._review(result, "模型复核未通过或置信度不足，不能自动进入正式题库。")
        return result

    def _review(self, question: dict[str, Any], reason: str) -> None:
        self.review_items.append(
            {
                "question_id": question.get("question_id"),
                "reason": reason,
                "answer_source": question.get("answer_source"),
                "answer_confidence": question.get("answer_confidence", 0.0),
                "source": question.get("source", {}),
            }
        )


def build_generation_prompt(question: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是严谨的编程课程助教。只根据题目内容作答；开放编程题只能给出一种可行的参考解答，"
        "不能声称唯一正确。输出 JSON：answer_kind(standard_answer/reference_solution)、answer、analysis、confidence。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(question, ensure_ascii=False)}]


def build_verification_prompt(question: dict[str, Any], generated: dict[str, Any]) -> list[dict[str, str]]:
    system = (
        "你是独立的编程题答案审校员。检查候选答案是否与题目相符、是否有明显编译或逻辑错误。"
        "开放题只验证其是否为合理参考方案。输出 JSON：accepted(boolean)、answer、analysis、confidence(0-1)、reason。"
    )
    payload = {"question": question, "candidate_answer": generated}
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为缺答案习题生成并复核答案。")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="标准化 questions.json 路径")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录")
    parser.add_argument("--provider", default="qwen", choices=["qwen", "deepseek"], help="答案生成 API 提供方")
    parser.add_argument("--model", default=None, help="模型名称")
    parser.add_argument("--base-url", default=None, help="OpenAI-compatible API 地址")
    parser.add_argument("--no-llm", action="store_true", help="只生成待审核报告，不调用 API")
    parser.add_argument("--timeout", type=int, default=90, help="API 超时时间")
    parser.add_argument("--retries", type=int, default=2, help="API 重试次数")
    parser.add_argument("--min-confidence", type=float, default=0.85, help="自动入库的最小复核置信度")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 道题，0 表示全部")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    questions = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(questions, list):
        raise ValueError("questions.json 顶层必须是数组。")
    output_dir = Path(args.output_dir)
    llm = None
    if not args.no_llm:
        llm = LLMClient(args.provider, args.model, args.base_url, args.timeout, args.retries, output_dir / "answer_cache", True)
    completer = AnswerCompleter(llm, args.min_confidence)
    selected = questions[: args.limit] if args.limit else questions
    output_questions = output_dir / "questions_with_answers.json"
    partial_path = output_dir / "questions_with_answers.partial.json"
    report_path = output_dir / "answer_completion_report.json"
    review_path = output_dir / "answer_review_report.json"
    completed: list[dict[str, Any]] = []
    total = len(selected)

    # 逐题写入临时结果：模型响应也有独立缓存，网络中断后重跑不会白白消耗调用额度。
    for index, question in enumerate(selected, start=1):
        question_id = str(question.get("question_id", f"第{index}题"))
        print(f"[{index}/{total}] 生成并复核 {question_id}...", flush=True)
        result = completer.complete(question)
        completed.append(result)
        write_json(partial_path, completed)
        print(
            f"[{index}/{total}] {question_id} 完成：{result.get('answer_status', 'unknown')} "
            f"(置信度 {result.get('answer_confidence', 0.0)})",
            flush=True,
        )

    write_json(output_questions, completed)
    counts = Counter(str(question.get("answer_status", "")) for question in completed)
    write_json(
        report_path,
        {
            "schema_version": "programming_kg_answer_completion_v1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "input": args.input,
            "output": str(output_questions),
            "question_count": len(completed),
            "status_counts": dict(counts),
            "provider": "none" if args.no_llm else args.provider,
            "min_confidence": args.min_confidence,
        },
    )
    write_json(review_path, {"generated_at": datetime.now().isoformat(timespec="seconds"), "review_items": completer.review_items})
    print(f"处理习题数量：{len(completed)}")
    print(f"教师/人工答案已验证数量：{counts.get('verified', 0)}")
    print(f"仅模型自审数量：{counts.get('model_verified', 0)}")
    print(f"待审核数量：{counts.get('needs_review', 0)}")
    print(f"习题输出：{output_questions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
