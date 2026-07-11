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
            result["answer_source"] = result.get("answer_source") or "provided"
            result["answer_kind"] = result.get("answer_kind") or "standard_answer"
            result["answer_status"] = "verified"
            result["answer_confidence"] = 1.0
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
        status = "verified" if accepted and confidence >= self.min_confidence else "needs_review"
        result.update(
            {
                "answer": answer,
                "analysis": analysis,
                "answer_source": "llm_generated",
                "answer_kind": "reference_solution" if answer_kind == "reference_solution" else "standard_answer",
                "answer_status": status,
                "answer_confidence": round(confidence, 4),
                "answer_generation": {"generated": generated, "verification": verified},
            }
        )
        if status != "verified":
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
    completed = [completer.complete(question) for question in selected]
    output_questions = output_dir / "questions_with_answers.json"
    report_path = output_dir / "answer_completion_report.json"
    review_path = output_dir / "answer_review_report.json"
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
    print(f"答案已验证数量：{counts.get('verified', 0)}")
    print(f"待审核数量：{counts.get('needs_review', 0)}")
    print(f"习题输出：{output_questions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

