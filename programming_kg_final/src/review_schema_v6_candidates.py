"""Generate a strict, read-only third-review report for Schema v6 candidates.

This script never changes the curriculum catalog, standard graph, or Neo4j.  It
only evaluates candidate terms against the agreed third-review gate:
at least two independent source chunks, an explicit parent, and no semantic
collision with an existing formal node unless it is a true alias.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


# These are deliberately conservative, evidence-backed recommendations.  A
# missing term or insufficient evidence automatically falls back to candidate
# retention instead of being silently promoted.
ADD_NODE_SPECS: dict[str, dict[str, str]] = {
    "ASL成功": {
        "type": "ComplexityMetric",
        "parent_id": "curriculum_D7_1",
        "parent_name": "查找表与平均查找长度",
        "relation": "has_complexity_metric",
        "reason": "多页材料均以成功查找的平均查找长度作为查找性能指标。",
    },
    "ASL失败": {
        "type": "ComplexityMetric",
        "parent_id": "curriculum_D7_1",
        "parent_name": "查找表与平均查找长度",
        "relation": "has_complexity_metric",
        "reason": "多页材料均以失败查找的平均查找长度作为查找性能指标。",
    },
    "平均查找长度": {
        "type": "ComplexityMetric",
        "parent_id": "curriculum_D7_1",
        "parent_name": "查找表与平均查找长度",
        "relation": "has_complexity_metric",
        "reason": "是查找算法性能分析中的标准度量，而不是普通别名。",
    },
    "三元组顺序表上的转置": {
        "type": "OperationRule",
        "parent_id": "curriculum_D2_7",
        "parent_name": "稀疏矩阵与三元组顺序表",
        "relation": "has_operation_rule",
        "reason": "材料明确给出三元组顺序表的转置操作过程。",
    },
    "二叉排序树的删除运算": {
        "type": "OperationRule",
        "parent_id": "curriculum_D5_6",
        "parent_name": "二叉排序树",
        "relation": "has_operation_rule",
        "reason": "是二叉排序树上的确定性基本操作。",
    },
    "后序线索二叉树": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D5_5",
        "parent_name": "线索二叉树",
        "relation": "part_of",
        "reason": "是线索二叉树的一种明确分类。",
    },
    "完全二叉树": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D5_0",
        "parent_name": "二叉树",
        "relation": "part_of",
        "reason": "是二叉树的标准类型，材料中反复出现。",
    },
    "散列表(哈希表)": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D7",
        "parent_name": "查找",
        "relation": "part_of",
        "reason": "散列表是查找中的数据组织结构，不能与散列查找算法混为别名。",
    },
    "最小不平衡子树": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D5_7",
        "parent_name": "平衡二叉树",
        "relation": "part_of",
        "reason": "是平衡二叉树调整中的专门结构概念。",
    },
    "有向图": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D6",
        "parent_name": "图",
        "relation": "part_of",
        "reason": "是图的基本类型，归属清晰。",
    },
    "有序顺序表": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D3_4",
        "parent_name": "顺序表",
        "relation": "part_of",
        "reason": "是顺序表在查找场景中的明确形态。",
    },
    "树形选择排序": {
        "type": "Algorithm",
        "parent_id": "curriculum_D8_4",
        "parent_name": "选择排序",
        "relation": "has_algorithm",
        "reason": "材料给出该排序算法；“树型选择排序”应作为其别名。",
    },
    "树表的查找": {
        "type": "Algorithm",
        "parent_id": "curriculum_D7",
        "parent_name": "查找",
        "relation": "has_algorithm",
        "reason": "是树表查找类别下的明确算法主题。",
    },
    "红黑树": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D5_6",
        "parent_name": "二叉排序树",
        "relation": "part_of",
        "reason": "是二叉搜索树的平衡扩展结构。",
    },
    "线性探查法": {
        "canonical_name": "线性探测法",
        "type": "OperationRule",
        "parent_id": "curriculum_D7_6",
        "parent_name": "散列查找",
        "relation": "has_operation_rule",
        "reason": "散列冲突处理方法；教材用语“探查”需归一为标准术语“探测”。",
    },
    "赫夫曼树": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D5",
        "parent_name": "树与二叉树",
        "relation": "part_of",
        "reason": "是赫夫曼编码主题的核心结构。",
    },
    "赫夫曼编码": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D5",
        "parent_name": "树与二叉树",
        "relation": "part_of",
        "reason": "是赫夫曼树主题的核心编码概念。",
    },
    "赫夫曼算法": {
        "type": "Algorithm",
        "parent_id": "curriculum_D5",
        "parent_name": "树与二叉树",
        "relation": "has_algorithm",
        "reason": "材料中作为构造赫夫曼树/编码的明确算法出现。",
    },
    "顶点": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D6",
        "parent_name": "图",
        "relation": "part_of",
        "reason": "是图的基础组成概念，语义唯一且归属清晰。",
    },
    "顺序存储": {
        "type": "KnowledgePoint",
        "parent_id": "curriculum_D0",
        "parent_name": "数据结构基本概念",
        "relation": "part_of",
        "reason": "是数据结构的基本存储方式。",
    },
    "朴素的串匹配算法": {
        "canonical_name": "朴素模式匹配算法",
        "type": "Algorithm",
        "parent_id": "curriculum_D1",
        "parent_name": "字符串与序列",
        "relation": "has_algorithm",
        "reason": "是串模式匹配的明确基础算法；“朴素的串匹配算法”作为材料别名保留。",
    },
}

ALIAS_SPECS: dict[str, dict[str, str]] = {
    "线性链表": {
        "target_id": "curriculum_D3_3",
        "target_name": "链表",
        "reason": "教材中“线性链表”是链表的同义称呼。",
    },
}

# Terms below are certainly not independent curriculum nodes at the current
# granularity.  They remain as evidence only, unless a later catalog expansion
# introduces their missing parent topic.
EXCLUDE_TERMS = {
    "程序设计语言": "仅是课程上下文，不是数据结构课程树内的教学知识点。",
    "ASL不成功": "与“ASL失败”表达重复且仅出现一次，保留后者即可。",
}

# These names are evidence-rich but require a future parent split or a more
# specific topic before becoming a formal tree node.
KEEP_REASONS = {
    "有向无环图": "当前课程树把它与拓扑排序合并；应先拆分现有组合节点，不能直接并入。",
    "一趟划分": "缺少“快速排序”这一明确父节点，直接纳入会形成悬空细节。",
    "划分(Partition)": "缺少唯一归属，可能属于快速排序或其他分治过程。",
    "创建(构造)": "操作对象不明确，不能作为独立教学节点。",
    "删除": "操作对象不明确，不能作为独立教学节点。",
    "插入": "操作对象不明确，不能作为独立教学节点。",
    "插入运算": "操作对象不明确，不能作为独立教学节点。",
    "查找性能分析": "应先拆为明确的时间/空间/平均查找长度指标。",
    "查找操作": "覆盖多个查找算法，当前粒度过泛。",
    "查找运算": "覆盖多个查找算法，当前粒度过泛。",
    "查找表": "现有“查找表与平均查找长度”为组合节点，需先完成拆分。",
    "根结点": "术语基础但跨多种树，当前课程树未设置树术语专栏。",
    "直接前驱": "跨线性表、树等多类结构，归属不唯一。",
    "直接后继": "跨线性表、树等多类结构，归属不唯一。",
    "约瑟夫环": "需要先补“循环链表”父节点后才能稳定纳入。",
    "译码": "在编码、串、图等语境下含义不同，需补充上下文。",
    "线性表的查找": "与顺序查找、折半查找等已存在算法层级交叠。",
    "赫夫曼树及赫夫曼编码的构造": "与赫夫曼算法高度重叠，待算法节点先正式纳入后再判定。",
    "散列查找的性能分析": "需要先建立具体复杂度/装填因子指标节点。",
    "数据结构 – Data Structures": "当前正式根节点为“数据组织与算法基础”，与“数据结构”并非严格同义，不能直接写入别名。",
}

# Different source materials sometimes use spelling variants for the same term.
# Merge their evidence before applying the two-source threshold.
TERM_NORMALIZATION = {
    "树型选择排序": "树形选择排序",
}


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


def evidence_count(record: dict[str, Any]) -> int:
    return len(set(record.get("source_chunk_ids", [])))


def aggregate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate/variant candidate records without losing source evidence."""
    groups: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        raw_name = candidate["name"].strip()
        name = TERM_NORMALIZATION.get(raw_name, raw_name)
        key = name
        if key not in groups:
            groups[key] = {
                "name": name,
                "type": candidate.get("type", "KnowledgePoint"),
                "source_types": [],
                "confidence": candidate.get("confidence", 0.0),
                "source_chunk_ids": [],
                "sources": [],
                "source_terms": [],
                "reason": candidate.get("reason", ""),
            }
        merged = groups[key]
        merged["confidence"] = max(merged["confidence"], candidate.get("confidence", 0.0))
        merged["source_types"].append(candidate.get("type", "KnowledgePoint"))
        merged["source_terms"].append(raw_name)
        merged["source_chunk_ids"].extend(candidate.get("source_chunk_ids", []))
        merged["sources"].extend(candidate.get("sources", []))

    result = []
    for merged in groups.values():
        merged["source_terms"] = sorted(set(merged["source_terms"]))
        merged["source_types"] = sorted(set(merged["source_types"]))
        merged["source_chunk_ids"] = sorted(set(merged["source_chunk_ids"]))
        source_by_chunk = {
            source.get("chunk_id", f"no_chunk_{index}"): source
            for index, source in enumerate(merged["sources"])
        }
        merged["sources"] = list(source_by_chunk.values())
        result.append(merged)
    return sorted(result, key=lambda item: item["name"])


def review_candidate(record: dict[str, Any], formal_names: set[str]) -> dict[str, Any]:
    name = record["name"].strip()
    count = evidence_count(record)
    result: dict[str, Any] = {
        "review_scope": "data_structure_candidate",
        "name": name,
        "source_type": record.get("type"),
        "confidence": record.get("confidence"),
        "evidence_chunk_count": count,
        "source_chunk_ids": record.get("source_chunk_ids", []),
        "source_files": sorted({source.get("source_file", "") for source in record.get("sources", []) if source.get("source_file")}),
        "sources": record.get("sources", []),
        "source_terms": record.get("source_terms", [name]),
        "original_reason": record.get("reason"),
        "decision": "keep_candidate",
        "decision_label": "保留候选",
        "proposed_action": "不修改正式图谱，进入后续人工审核池。",
        "reason": "未达到第三轮自动纳入条件。",
    }

    if name in EXCLUDE_TERMS:
        result.update({
            "decision": "exclude",
            "decision_label": "排除",
            "proposed_action": "不进入课程知识树；保留原始材料证据即可。",
            "reason": EXCLUDE_TERMS[name],
        })
        return result

    if name in ALIAS_SPECS and count >= 2:
        spec = ALIAS_SPECS[name]
        result.update({
            "decision": "alias_alignment",
            "decision_label": "别名对齐",
            "proposed_action": "将该词补充为现有正式节点的 aliases，不新增节点。",
            "target_node": {"id": spec["target_id"], "name": spec["target_name"]},
            "reason": spec["reason"],
        })
        return result

    if name in ADD_NODE_SPECS and count >= 2:
        spec = ADD_NODE_SPECS[name]
        canonical_name = spec.get("canonical_name", name)
        if canonical_name in formal_names:
            result.update({
                "decision": "relation_only",
                "decision_label": "仅补关系",
                "proposed_action": "正式图谱已有同名节点，只补充其归属关系与证据。",
                "proposed_parent": {"id": spec["parent_id"], "name": spec["parent_name"]},
                "proposed_relation_type": spec["relation"],
                "reason": spec["reason"],
            })
        else:
            result.update({
                "decision": "add_node",
                "decision_label": "新增知识树节点",
                "proposed_action": "新增节点并建立明确的父子/语义关系；本报告不执行该操作。",
                "proposed_node": {
                    "name": canonical_name,
                    "type": spec["type"],
                    "aliases": sorted({term for term in record.get("source_terms", []) if term != canonical_name}),
                },
                "proposed_parent": {"id": spec["parent_id"], "name": spec["parent_name"]},
                "proposed_relation_type": spec["relation"],
                "reason": spec["reason"],
            })
        return result

    reason = KEEP_REASONS.get(name)
    if count < 2:
        reason = "材料证据不足两处，未达到第三轮自动纳入门槛。"
    elif reason is None:
        reason = "虽有多处材料证据，但父节点、术语粒度或与现有节点的语义边界仍不够明确。"
    result["reason"] = reason
    return result


def review_migration_node(record: dict[str, Any], graph_nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    node = graph_nodes.get(record["id"], {})
    count = evidence_count(node)
    name = record["name"]
    result: dict[str, Any] = {
        "review_scope": "schema_v6_migration_sensitive_node",
        "node_id": record["id"],
        "name": name,
        "current_type": record["current_type"],
        "evidence_chunk_count": count,
        "decision": "keep_candidate",
        "decision_label": "保留候选",
        "proposed_action": "保持当前 KnowledgePoint 类型，不进行自动类型迁移。",
        "reason": "名称同时包含多个概念或可表示多个教学粒度，需要后续专题拆分后再迁移。",
    }
    if name == "查找与排序":
        result["reason"] = "是跨章节概览节点；此前已清除“查找”“排序”别名冲突，当前保留概览语义更稳妥。"
    elif name == "二叉排序树":
        result["reason"] = "是数据结构，不是算法；保持 KnowledgePoint 正确。"
    elif name == "拓扑排序与有向无环图":
        result["reason"] = "概念与算法被合并在同一标题中；应先拆为“有向无环图”和“拓扑排序算法”，不自动迁移。"
    elif name == "查找表与平均查找长度":
        result["reason"] = "结构概念与性能指标被合并；应先拆分后再将“平均查找长度”标为 ComplexityMetric。"
    elif name == "排序基本概念与性能分析":
        result["reason"] = "属于概览与比较主题，不等同于单一复杂度指标。"
    elif name == "文件与目录操作":
        result["reason"] = "覆盖多个操作规则，是课程主题而非单一操作规则。"
    elif name == "队列的基本操作":
        result["reason"] = "只有一处来源证据，且标题同时包含多个操作，暂不迁移为 OperationRule。"
    return result


def markdown_report(report: dict[str, Any]) -> str:
    counts = report["summary"]["decision_counts"]
    lines = [
        "# Schema v6 第三轮人工复核报告",
        "",
        "## 复核边界",
        "",
        "本轮仅生成审核建议，不修改课程知识树、`standard_graph.json` 或 Neo4j。自动纳入门槛为：至少两处材料证据、父节点明确、且不与正式节点发生重义冲突。",
        "",
        "## 结果概览",
        "",
        f"- 复核对象：{report['summary']['total_records']} 项，其中数据结构候选 {report['summary']['candidate_records']} 项，Schema v6 敏感节点 {report['summary']['migration_records']} 项。",
        f"- 新增知识树节点：{counts.get('add_node', 0)} 项。",
        f"- 别名对齐：{counts.get('alias_alignment', 0)} 项。",
        f"- 仅补关系：{counts.get('relation_only', 0)} 项。",
        f"- 保留候选：{counts.get('keep_candidate', 0)} 项。",
        f"- 排除：{counts.get('exclude', 0)} 项。",
        "",
        "## 建议纳入",
        "",
        "|术语|建议类型|父节点|关系|证据数|处理方式|",
        "|---|---|---|---|---:|---|",
    ]
    for item in report["records"]:
        if item["decision"] != "add_node":
            continue
        node = item["proposed_node"]
        parent = item["proposed_parent"]
        lines.append(
            f"|{node['name']}|{node['type']}|{parent['name']}|{item['proposed_relation_type']}|{item['evidence_chunk_count']}|新增知识树节点|")

    lines.extend(["", "## 别名对齐", "", "|原术语|对齐到正式节点|证据数|处理方式|", "|---|---|---:|---|"])
    for item in report["records"]:
        if item["decision"] == "alias_alignment":
            target = item["target_node"]
            lines.append(f"|{item['name']}|{target['name']}|{item['evidence_chunk_count']}|补充 aliases，不新增节点|")

    lines.extend(["", "## 仍需人工判断的重点项", ""])
    for item in report["records"]:
        if item["decision"] == "keep_candidate" and item["evidence_chunk_count"] >= 2:
            lines.append(f"- `{item['name']}`：{item['reason']}")

    lines.extend([
        "",
        "## 迁移敏感节点结论",
        "",
        "以下既有节点均维持 `KnowledgePoint`，不进行自动迁移：",
    ])
    for item in report["records"]:
        if item["review_scope"] == "schema_v6_migration_sensitive_node":
            lines.append(f"- `{item['name']}`：{item['reason']}")

    lines.extend([
        "",
        "完整的逐项证据、处理方式与原因见同目录 `third_review_report.json`。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a read-only Schema v6 third-review report.")
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--migration-review", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    candidate_report = read_json(args.candidate_report)
    migration_review = read_json(args.migration_review)
    graph = read_json(args.graph)
    nodes = {node["id"]: node for node in graph["nodes"]}
    formal_names = {node["name"].strip() for node in graph["nodes"] if node.get("name")}

    merged_candidates = aggregate_candidates(candidate_report["candidates"])
    records = [review_candidate(record, formal_names) for record in merged_candidates]
    records.extend(review_migration_node(record, nodes) for record in migration_review["review_nodes"])
    records.sort(key=lambda item: (item["review_scope"], item["decision"], item["name"]))
    reference_issues: list[str] = []
    for record in records:
        if record["decision"] in {"add_node", "relation_only"}:
            parent = record.get("proposed_parent")
            if parent and (parent["id"] not in nodes or nodes[parent["id"]]["name"] != parent["name"]):
                reference_issues.append(f"父节点无效：{record['name']} -> {parent['id']}")
        if record["decision"] == "alias_alignment":
            target = record["target_node"]
            if target["id"] not in nodes or nodes[target["id"]]["name"] != target["name"]:
                reference_issues.append(f"别名目标无效：{record['name']} -> {target['id']}")
    if reference_issues:
        raise ValueError("第三轮复核引用校验失败：" + "；".join(reference_issues))
    decision_counts = Counter(item["decision"] for item in records)
    report = {
        "review_version": "schema_v6_third_review_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "review_gate": {
            "minimum_independent_source_chunks": 2,
            "requires_explicit_parent": True,
            "requires_no_semantic_collision": True,
            "mutates_graph": False,
            "formal_reference_validation_passed": True,
        },
        "inputs": {
            "candidate_report": str(args.candidate_report),
            "migration_review": str(args.migration_review),
            "graph": str(args.graph),
        },
        "summary": {
            "total_records": len(records),
            "candidate_records": len(merged_candidates),
            "raw_candidate_records": len(candidate_report["candidates"]),
            "migration_records": len(migration_review["review_nodes"]),
            "decision_counts": dict(sorted(decision_counts.items())),
        },
        "records": records,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "third_review_report.json", report)
    (args.output_dir / "第三轮人工复核报告.md").write_text(markdown_report(report), encoding="utf-8")
    print(f"复核对象：{report['summary']['total_records']}")
    for decision, count in sorted(decision_counts.items()):
        print(f"{decision}: {count}")
    print(f"审核报告：{args.output_dir / 'third_review_report.json'}")
    print(f"摘要报告：{args.output_dir / '第三轮人工复核报告.md'}")


if __name__ == "__main__":
    main()
