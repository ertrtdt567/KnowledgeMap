"""从正式课程图谱中生成固定、分层且课程平衡的关系评测样本。"""

from __future__ import annotations

import argparse
import json
import random
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_GRAPH = (
    BASE_DIR
    / "output/programming_kg/course_centered_v12_candidate_finalized/standard_graph.json"
)
DEFAULT_OUTPUT = (
    BASE_DIR / "output/programming_kg/evaluation/relation_gold_sample_v1.json"
)
SEED = 20260717
COURSE_ORDER = [
    "course_java",
    "course_python",
    "course_cpp",
    "course_data_structures",
    "course_uml",
    "global",
]


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


def course_for(source: dict[str, Any], target: dict[str, Any]) -> str:
    return str(source.get("course_id") or target.get("course_id") or "global")


def source_summary(edge: dict[str, Any]) -> str:
    sources = edge.get("sources", [])
    if not sources:
        return ""
    first = sources[0]
    if not isinstance(first, dict):
        return str(first)
    file_name = Path(str(first.get("source_file") or first.get("file") or "")).name
    page = first.get("page") or first.get("evidence_location") or ""
    return f"{file_name} P{page}".strip()


def balanced_sample(
    rows: list[dict[str, Any]], count: int, rng: random.Random
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["course_id"]].append(row)
    for values in groups.values():
        rng.shuffle(values)

    result: list[dict[str, Any]] = []
    while len(result) < count:
        progressed = False
        for course_id in COURSE_ORDER:
            if groups[course_id] and len(result) < count:
                result.append(groups[course_id].pop())
                progressed = True
        for course_id in sorted(set(groups) - set(COURSE_ORDER)):
            if groups[course_id] and len(result) < count:
                result.append(groups[course_id].pop())
                progressed = True
        if not progressed:
            break
    if len(result) != count:
        raise ValueError(f"样本池不足：需要 {count}，实际 {len(result)}")
    return result


def sample_by_type(
    rows: list[dict[str, Any]], relation_type: str, count: int, rng: random.Random
) -> list[dict[str, Any]]:
    return balanced_sample(
        [row for row in rows if row["relation_type"] == relation_type], count, rng
    )


def build_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 关系抽取准确率人工复核表",
        "",
        f"- 样本量：{payload['sample_size']}",
        f"- 固定随机种子：{payload['seed']}",
        "- 标签：`correct` / `incorrect` / `uncertain`",
        "- 第一轮由 Codex 预审，`uncertain` 与低把握项由项目成员最终确认。",
        "",
        "|序号|课程|源节点|关系|目标节点|置信度|第一轮标签|复核说明|",
        "|---:|---|---|---|---|---:|---|---|",
    ]
    for item in payload["items"]:
        source = str(item["source_name"]).replace("|", "\\|")
        target = str(item["target_name"]).replace("|", "\\|")
        lines.append(
            f"|{item['sample_index']}|{item['course_id']}|{source}"
            f"|{item['relation_name']}|{target}|{item['confidence']:.2f}"
            f"|{item['assistant_label']}|{item['review_note']}|"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成关系准确率分层评测样本。")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    graph = load_json(args.graph)
    nodes = {node["id"]: node for node in graph["nodes"]}
    rows: list[dict[str, Any]] = []
    for edge in graph["edges"]:
        source = nodes[edge["source"]]
        target = nodes[edge["target"]]
        rows.append(
            {
                "edge_id": edge["id"],
                "course_id": course_for(source, target),
                "source_id": source["id"],
                "source_name": source.get("name", ""),
                "source_type": source.get("type", ""),
                "relation_type": edge.get("type", ""),
                "relation_name": edge.get("relation_name", edge.get("type", "")),
                "target_id": target["id"],
                "target_name": target.get("name", ""),
                "target_type": target.get("type", ""),
                "confidence": float(edge.get("confidence", 0.0)),
                "evidence": str(edge.get("evidence", "")),
                "source_reference": source_summary(edge),
                "assistant_label": "pending",
                "review_note": "",
                "user_label": "",
            }
        )

    rng = random.Random(SEED)
    sampled: list[dict[str, Any]] = []
    fixed_quotas = {
        "has_code_example": 20,
        "syntax_used_in_example": 20,
        "appears_in_example": 20,
        "part_of": 25,
        "prerequisite_of": 20,
        "maps_to_core": 15,
        "supported_in_language": 5,
        "belongs_to_language": 5,
        "has_core_concept": 10,
    }
    for relation_type, count in fixed_quotas.items():
        sampled.extend(sample_by_type(rows, relation_type, count, rng))

    selected_ids = {item["edge_id"] for item in sampled}
    reserved_types = set(fixed_quotas)
    semantic_pool = [
        row
        for row in rows
        if row["relation_type"] not in reserved_types
        and row["edge_id"] not in selected_ids
    ]
    semantic_types = sorted({row["relation_type"] for row in semantic_pool})
    for relation_type in semantic_types:
        available = [
            row for row in semantic_pool if row["relation_type"] == relation_type
        ]
        take = min(2, len(available))
        chosen = balanced_sample(available, take, rng)
        sampled.extend(chosen)
        selected_ids.update(item["edge_id"] for item in chosen)
    remaining = 200 - len(sampled)
    sampled.extend(
        balanced_sample(
            [row for row in semantic_pool if row["edge_id"] not in selected_ids],
            remaining,
            rng,
        )
    )

    rng.shuffle(sampled)
    for index, item in enumerate(sampled, start=1):
        item["sample_index"] = index
    if len(sampled) != 200 or len({item["edge_id"] for item in sampled}) != 200:
        raise ValueError("关系样本数量或唯一性校验失败。")

    payload = {
        "schema_version": "relation_gold_sample_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph": str(args.graph.resolve()),
        "seed": SEED,
        "sample_size": len(sampled),
        "sampling_strategy": "relation_category_stratified_and_course_balanced",
        "distribution": {
            "by_course": dict(Counter(item["course_id"] for item in sampled)),
            "by_relation": dict(
                Counter(item["relation_type"] for item in sampled)
            ),
            "by_confidence_band": {
                "high_0.9_1.0": sum(item["confidence"] >= 0.9 for item in sampled),
                "medium_0.75_0.9": sum(
                    0.75 <= item["confidence"] < 0.9 for item in sampled
                ),
                "low_below_0.75": sum(item["confidence"] < 0.75 for item in sampled),
            },
        },
        "items": sampled,
    }
    atomic_write_json(args.output, payload)
    atomic_write_text(args.output.with_suffix(".md"), build_markdown(payload))
    print(f"关系评测样本：{len(sampled)}")
    print(f"课程分布：{payload['distribution']['by_course']}")
    print(f"关系类型数：{len(payload['distribution']['by_relation'])}")
    print(f"样本文件：{args.output}")
    print(f"复核表：{args.output.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
