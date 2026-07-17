"""Create curriculum catalog v0.13 from the reviewed candidate list."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from curriculum_catalog import CurriculumCatalog


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def add_unique(node: dict[str, Any], field: str, values: list[str]) -> None:
    current = node.setdefault(field, [])
    for value in values:
        if value not in current:
            current.append(value)


def upgrade(payload: dict[str, Any]) -> dict[str, Any]:
    upgraded = deepcopy(payload)
    nodes = upgraded["nodes"]
    by_id = {str(node["id"]): node for node in nodes}

    # These terms improve evidence alignment for existing syllabus nodes. They
    # are deliberately not aliases because they describe subtopics or examples.
    term_updates: dict[str, list[str]] = {
        "C1_2": ["参数传递方式", "值传递", "引用传递"],
        "D5_7": ["LL型平衡旋转", "RR型平衡旋转", "LR型平衡旋转", "RL型平衡旋转"],
        "D5_8": ["堆的定义", "大顶堆(max heap)", "小顶堆(min heap)"],
        "D5_9": ["赫夫曼树的构造", "赫夫曼编码", "赫夫曼编码与译码"],
        "D5_10": ["并查集的概念", "并查集的实现以及优化", "路径压缩"],
        "D7_6": ["链地址法", "开放定址法", "线性探测", "二次探测", "再散列", "散列查找性能"],
        "D8_3": ["一趟划分", "划分(Partition)", "快速排序中的一趟划分"],
        "F2_2": ["Eclipse调试"],
        "J1_1": ["识别用例"],
        "J1_2": ["用例建模流程"],
        "J1_6": ["构建初始用例模型", "重构用例模型"],
        "J1_12": ["对用例进行分包和分级", "用例分包和分级"],
    }
    for node_id, terms in term_updates.items():
        node = by_id[node_id]
        add_unique(node, "alignment_terms", terms)
        add_unique(node, "evidence_terms", terms)

    new_nodes = [
        {
            "id": "D3_9",
            "name": "约瑟夫环问题",
            "type": "AlgorithmProblem",
            "parent_id": "D3",
            "aliases": ["Josephus问题", "Josephus Problem"],
            "alignment_terms": ["约瑟夫环", "约瑟夫问题", "Josephus"],
            "evidence_terms": ["约瑟夫环", "约瑟夫问题", "Josephus"],
            "keywords": ["约瑟夫环", "循环链表", "Josephus"],
        },
        {
            "id": "J1_13",
            "name": "非功能需求与FURPS",
            "type": "KnowledgePoint",
            "parent_id": "J1",
            "aliases": ["非功能性需求"],
            "alignment_terms": ["非功能需求", "FURPS", "FURPS准则", "FURPS+"],
            "evidence_terms": ["非功能需求", "非功能性需求", "FURPS", "FURPS准则", "FURPS+"],
            "keywords": ["非功能需求", "FURPS", "质量属性"],
        },
        {
            "id": "J2_8",
            "name": "对象图",
            "type": "KnowledgePoint",
            "parent_id": "J2",
            "aliases": ["Object Diagram"],
            "alignment_terms": ["对象图"],
            "evidence_terms": ["对象图", "Object Diagram"],
            "keywords": ["对象图", "对象实例", "Object Diagram"],
        },
        {
            "id": "J2_9",
            "name": "部署图",
            "type": "KnowledgePoint",
            "parent_id": "J2",
            "aliases": ["Deployment Diagram"],
            "alignment_terms": ["部署图"],
            "evidence_terms": ["部署图", "Deployment Diagram"],
            "keywords": ["部署图", "节点", "连接", "Deployment Diagram"],
        },
    ]
    duplicate_ids = sorted({str(node["id"]) for node in new_nodes} & set(by_id))
    if duplicate_ids:
        raise ValueError(f"新增目录节点 ID 已存在：{duplicate_ids}")
    nodes.extend(new_nodes)

    upgraded["schema_version"] = "programming_curriculum_v0_13_candidate_finalized"
    upgraded["title"] = "编程领域标准课程知识目录 v0.13（候选复核定稿版）"
    upgraded["upgrade_notes"] = [
        *upgraded.get("upgrade_notes", []),
        "根据课件直接证据新增约瑟夫环问题、非功能需求与FURPS、对象图和部署图。",
        "将调试、参数传递、排序、树、散列和用例建模候选词收敛为既有节点的对齐与证据词，不重复扩张课程树。",
        "CRUD 等建模反例及教材名、教师名、工具名继续留在候选复核层，不进入正式课程知识树。",
    ]
    return upgraded


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reviewed curriculum catalog v0.13.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    upgraded = upgrade(read_json(args.input))
    write_json(args.output, upgraded)
    catalog = CurriculumCatalog.load(args.output)
    print(f"课程树节点：{len(catalog.nodes)}")
    print(f"目录版本：{catalog.payload.get('schema_version')}")
    print(f"输出：{args.output}")


if __name__ == "__main__":
    main()
