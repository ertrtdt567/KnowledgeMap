"""写入关系评测样本的 Codex 第一轮人工复核结论。"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = (
    BASE_DIR / "output/programming_kg/evaluation/relation_gold_sample_v1.json"
)
DEFAULT_OUTPUT = (
    BASE_DIR
    / "output/programming_kg/evaluation/relation_gold_sample_v1_first_review.json"
)


INCORRECT = {
    17: "示例中的“类C语言”表示类C伪代码，不是在讲解面向对象的类，属于关键词误匹配。",
    84: "斐波那契脚本的教学重点不是字符串，仅因出现字符串字面量而挂接，粒度不成立。",
    88: "类型系统是程序设计基础的核心概念，不是实现机制，关系类型选择错误。",
    120: "斐波那契脚本没有执行文件或目录操作，属于“源程序文件”字样造成的误匹配。",
    136: "数组可用于邻接矩阵，但不是理解图的基本概念与存储的必要先修条件。",
    148: "原证据说明指针或引用可避免信息丢失，当前 may_cause 关系与证据方向相反。",
    169: "Java 数组不实现 Iterable，数组也不是迭代器概念的必要先修条件。",
    181: "“用类C语言实现”中的“类”不是面向对象的类，属于关键词误匹配。",
    186: "类型系统是程序设计基础的核心概念，不是实现机制，关系类型选择错误。",
    187: "形参是实参副本是值传递语义，不是 ErrorPattern，may_cause 关系不成立。",
    200: "ASL成功是平均查找长度的分类/组成指标，不是由平均查找长度先修得到。",
}

UNCERTAIN = {
    70: "需求与用例建模通常早于动态行为建模，但是否定义为严格先修需按课程教学顺序确认。",
    96: "基本数据类型与字符串存在教学顺序，但是否构成严格先修关系需确认课程口径。",
    153: "Java 面向对象编程是否明确培养“面向对象建模”能力，需要课程目标或教学大纲佐证。",
    156: "数据结构课程中的“抽象类”是否与跨课程 CoreConcept 同义，需要核对原材料语境。",
    172: "Java 基本数据类型与 String 分属基本类型和引用类型，是否作为严格先修需确认。",
    182: "运算符与表达式通常先于输入输出，但在 UML 课程中是否构成严格先修需确认。",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def markdown(payload: dict[str, Any]) -> str:
    stats = payload["first_review"]
    lines = [
        "# 关系抽取准确率第一轮复核",
        "",
        f"- 样本：{payload['sample_size']} 条",
        f"- 明确正确：{stats['correct']} 条",
        f"- 明确错误：{stats['incorrect']} 条",
        f"- 待确认：{stats['uncertain']} 条",
        f"- 已判定样本准确率：{stats['precision_on_decided']:.2%}",
        f"- 保守准确率（待确认全部按错）：{stats['conservative_precision']:.2%}",
        f"- 乐观准确率（待确认全部按对）：{stats['optimistic_precision']:.2%}",
        "",
        "## 待用户确认",
        "",
        "|序号|课程|源节点|关系|目标节点|争议原因|最终标签|",
        "|---:|---|---|---|---|---|---|",
    ]
    for item in payload["items"]:
        if item["assistant_label"] != "uncertain":
            continue
        lines.append(
            f"|{item['sample_index']}|{item['course_id']}|{item['source_name']}"
            f"|{item['relation_name']}|{item['target_name']}|{item['review_note']}| |"
        )
    lines.extend(
        [
            "",
            "## 明确错误",
            "",
            "|序号|源节点|关系|目标节点|错误原因|",
            "|---:|---|---|---|---|",
        ]
    )
    for item in payload["items"]:
        if item["assistant_label"] != "incorrect":
            continue
        lines.append(
            f"|{item['sample_index']}|{item['source_name']}|{item['relation_name']}"
            f"|{item['target_name']}|{item['review_note']}|"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="应用关系样本第一轮人工复核。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = load_json(args.input)
    seen = {item["sample_index"] for item in payload["items"]}
    missing_decisions = (set(INCORRECT) | set(UNCERTAIN)) - seen
    if missing_decisions:
        raise ValueError(f"复核序号不存在：{sorted(missing_decisions)}")

    for item in payload["items"]:
        index = item["sample_index"]
        if index in INCORRECT:
            item["assistant_label"] = "incorrect"
            item["review_note"] = INCORRECT[index]
        elif index in UNCERTAIN:
            item["assistant_label"] = "uncertain"
            item["review_note"] = UNCERTAIN[index]
        else:
            item["assistant_label"] = "correct"
            item["review_note"] = "源节点、关系类型与目标节点语义一致，且结构或材料证据可支持。"

    counts = Counter(item["assistant_label"] for item in payload["items"])
    decided = counts["correct"] + counts["incorrect"]
    by_course: dict[str, Counter[str]] = defaultdict(Counter)
    by_relation: dict[str, Counter[str]] = defaultdict(Counter)
    for item in payload["items"]:
        by_course[item["course_id"]][item["assistant_label"]] += 1
        by_relation[item["relation_type"]][item["assistant_label"]] += 1
    payload["first_review"] = {
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "Codex first-pass semantic review",
        "correct": counts["correct"],
        "incorrect": counts["incorrect"],
        "uncertain": counts["uncertain"],
        "precision_on_decided": counts["correct"] / decided,
        "conservative_precision": counts["correct"] / payload["sample_size"],
        "optimistic_precision": (
            counts["correct"] + counts["uncertain"]
        )
        / payload["sample_size"],
        "by_course": {key: dict(value) for key, value in sorted(by_course.items())},
        "by_relation": {
            key: dict(value) for key, value in sorted(by_relation.items())
        },
    }
    atomic_write_json(args.output, payload)
    atomic_write_text(args.output.with_suffix(".md"), markdown(payload))
    print(f"明确正确：{counts['correct']}")
    print(f"明确错误：{counts['incorrect']}")
    print(f"待确认：{counts['uncertain']}")
    print(f"已判定准确率：{counts['correct'] / decided:.2%}")
    print(f"保守准确率：{counts['correct'] / payload['sample_size']:.2%}")
    print(f"第一轮复核：{args.output}")
    print(f"人工确认表：{args.output.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
