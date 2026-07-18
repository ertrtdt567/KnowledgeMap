"""Create the delivery catalog after final human review.

v0.14 removes the retired "算法设计与分析" subtree and retracts the
manually curated relations that the relation sample review found unsound.
It is the catalog to use for future rebuilds; old catalogs remain snapshots.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from curriculum_catalog import CurriculumCatalog


RETIRED_ROOT_ID = "L"
RETRACTED_PREREQUISITES = {("A2_1", "D1_1"), ("A3_1", "A3_2")}
RETRACTED_ABILITY_RELATIONS = {("E", "ABILITY_OOP_MODELING", "develops_ability")}


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("课程目录顶层必须是对象。")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def descendant_ids(nodes: list[dict[str, Any]], root_id: str) -> set[str]:
    children: dict[str, list[str]] = {}
    for node in nodes:
        node_id = str(node.get("id", ""))
        parent_id = str(node.get("parent_id", ""))
        children.setdefault(parent_id, []).append(node_id)
    removed = {root_id}
    pending = [root_id]
    while pending:
        parent = pending.pop()
        for child in children.get(parent, []):
            if child not in removed:
                removed.add(child)
                pending.append(child)
    return removed


def filter_relation_list(
    relations: list[dict[str, Any]], removed_ids: set[str], predicate: Any | None = None
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for relation in relations:
        source = str(relation.get("source_id", ""))
        target = str(relation.get("target_id", ""))
        if source in removed_ids or target in removed_ids:
            continue
        if predicate is not None and predicate(relation):
            continue
        result.append(relation)
    return result


def upgrade(payload: dict[str, Any]) -> dict[str, Any]:
    upgraded = deepcopy(payload)
    nodes = [node for node in upgraded.get("nodes", []) if isinstance(node, dict)]
    removed_ids = descendant_ids(nodes, RETIRED_ROOT_ID)
    if RETIRED_ROOT_ID not in {str(node.get("id", "")) for node in nodes}:
        raise ValueError("输入目录不包含待移除的算法课程根节点 L。")

    upgraded["nodes"] = [node for node in nodes if str(node.get("id", "")) not in removed_ids]
    for field in ("semantic_relations", "prerequisite_relations", "ability_relations", "technology_relations"):
        relations = upgraded.get(field, [])
        if not isinstance(relations, list):
            continue
        def retract(relation: dict[str, Any], field_name: str = field) -> bool:
            triple = (
                str(relation.get("source_id", "")),
                str(relation.get("target_id", "")),
                str(relation.get("type", "")),
            )
            if field_name == "prerequisite_relations" and triple[:2] in RETRACTED_PREREQUISITES:
                return True
            return triple in RETRACTED_ABILITY_RELATIONS
        upgraded[field] = filter_relation_list(
            [item for item in relations if isinstance(item, dict)], removed_ids, retract
        )

    upgraded["schema_version"] = "programming_curriculum_v0_14_delivery"
    upgraded["title"] = "编程领域标准课程知识目录 v0.14（正式交付版）"
    upgraded["upgrade_notes"] = [
        *upgraded.get("upgrade_notes", []),
        "按最终范围决策移除算法设计与分析（L）及其全部子树；它不再作为独立课程或课程局部目录出现。",
        "按关系抽样复核撤回基本数据类型→字符串、运算符与表达式→输入输出的严格先修关系，以及面向对象编程→面向对象建模的能力培养关系。",
        "后续重建默认使用 v0.14；v0.13 及更早目录仅作为可追溯历史快照。",
    ]
    upgraded["release_policy"] = {
        "retired_catalog_roots": [RETIRED_ROOT_ID],
        "retracted_prerequisites": [list(item) for item in sorted(RETRACTED_PREREQUISITES)],
        "retracted_ability_relations": [list(item) for item in sorted(RETRACTED_ABILITY_RELATIONS)],
    }
    return upgraded


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 v0.14 正式交付课程目录。")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    upgraded = upgrade(read_json(args.input))
    write_json(args.output, upgraded)
    catalog = CurriculumCatalog.load(args.output)
    print(f"课程树节点：{len(catalog.nodes)}")
    print(f"目录版本：{catalog.payload.get('schema_version')}")
    print(f"输出：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
