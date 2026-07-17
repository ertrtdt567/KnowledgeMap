"""生成课程知识候选的人工复核清单。

该脚本不直接把候选写入正式图谱，而是把每个候选的处理依据固定下来：
已纳入、建议拒绝或需要人工确认。若上游产生了未登记的新候选，脚本会失败，
避免它被静默遗漏。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


# 第一批具有直接材料证据、且语义与课程树位置无歧义的候选，已经写入目录配置。
DIRECT_ACTIONS = {
    "Arrays": "新增知识树节点：D2_1 数组（补充英文对齐词）。",
    "EASCII": "新增知识树节点：D1_10 扩展ASCII。",
    "Enterprise JavaBeans": "新增 LibraryFramework：Enterprise JavaBeans，并补充 Java 平台关系。",
    "Jakarta EE": "新增 TechnologyPlatform：Jakarta EE，并补充 Java 支持关系。",
    "Java": "归并至现有 ProgrammingLanguage：Java，合并上游重复实体的材料证据。",
    "JavaEE": "补充现有 TechnologyPlatform：Java EE 的别名。",
    "JavaMessage Services": "补充现有 LibraryFramework：Java Message Service 的别名。",
    "JavaSE": "补充现有 TechnologyPlatform：Java SE 的别名。",
    "JavaServer Pages": "新增 LibraryFramework：JavaServer Pages，并补充 Java/Java EE 关系。",
    "JavaServlets API": "补充现有 LibraryFramework：Servlet API 的别名。",
    "Python编码规范": "新增知识树节点：H1_2 Python编码规范，并补充 supported_in_language(Python)。",
    "Qualified Names": "新增知识树节点：C2_3 限定名称，并补充英文对齐词。",
    "Spring Boot": "新增 LibraryFramework：Spring Boot，并补充 Java 支持关系。",
    "bit": "新增知识树节点：A2_6 二进制与位，并补充英文别名。",
    "lambda表达式": "新增知识树节点：C1_6 Lambda表达式。",
    "修饰": "仅补课程节点对齐词：J4_3 UML通用机制；不作为别名。",
    "分配内存空间": "新增知识树节点：E1_8 对象的动态创建与销毁的对齐词。",
    "动态创建&销毁对象": "新增知识树节点：E1_8 对象的动态创建与销毁。",
    "可视化模型": "仅补课程节点对齐词：J4_3 UML通用机制；不作为别名。",
    "基本符号": "仅补课程节点对齐词：J4_3 UML通用机制；不作为别名。",
    "多个直接基类的继承顺序": "新增知识树节点：E3_7 多重继承中的基类顺序。",
    "对象交互": "新增知识树节点：J3_2 对象交互。",
    "对象交互协议": "新增知识树节点：J3_3 对象交互协议。",
    "对象的结构特征": "仅补课程节点对齐词：E1_3 属性与方法；不作为别名。",
    "数据成员": "仅补课程节点对齐词：E1_3 属性与方法；不作为别名。",
    "模块化程序设计": "新增知识树节点：K2 模块化程序设计。",
    "派生类": "仅补课程节点对齐词：E3_1 继承的基本概念；不作为别名。",
    "生存期": "仅补课程节点对齐词：C1_3 函数调用与生存期。",
    "直接 基类/派生类": "仅补课程节点对齐词：E3_1 继承的基本概念；不作为别名。",
    "程序执行过程": "仅补课程节点对齐词：A1_1 源代码与程序执行。",
    "程序设计范型": "新增知识树领域：K 程序设计范型。",
    "程序设计风格": "新增知识树节点：K3 程序设计风格。",
    "继承方式": "仅补课程节点对齐词：E3 继承机制；不作为别名。",
    "行为特征": "仅补课程节点对齐词：E1_3 属性与方法；不作为别名。",
    "规格说明": "仅补课程节点对齐词：J4_3 UML通用机制；不作为别名。",
    "语义背板": "仅补课程节点对齐词：J4_3 UML通用机制；不作为别名。",
    "过程程序设计": "新增知识树节点：K1 过程程序设计。",
    "错误处理": "仅补课程节点对齐词：F 异常处理与调试。",
    "限定名称": "补充现有知识树节点：C2_3 限定名称的对齐词。",
}

# 这些内容有材料证据，但会改变课程边界、树结构或 Schema，不能自动写入正式图谱。
NEEDS_CONFIRMATION = {
    "AI": "候选动作：新增“AI辅助软件开发”知识域。需先确认前沿 AI 内容是否纳入正式课程范围。",
    "Entity-Relationship Modeling": "候选动作：新增“数据建模/ER建模”知识单元。需确认是否扩展至数据库建模。",
    "软件设计": "候选动作：新增或细化“软件设计”课程单元。当前证据混有 OOAD 与 LLM 课程目录，需确定归属。",
    "Eclipse调试": "候选动作：新增 DevelopmentTool 实体类型，并新增 supports_practice 关系指向“断言与调试”。",
    "Python版本演进": "候选动作：新增 Python 语言演进知识点。需确认课程历史是否作为可学习知识入树。",
    "一次编程,到处运行": "候选动作：新增“跨平台与可移植性”知识点，并补 Java 平台关联；需确定关系语义。",
    "可读性": "候选动作：仅补关系。其来源是 UML 图的可读性，不能误作“编码规范与可读性”的别名。",
    "建模": "候选动作：仅补上下文对齐或新增建模总览节点。词义过宽，需先指定 OOAD/UML/数据建模的归属。",
    "操作": "候选动作：新增或对齐“类操作/方法”知识点。当前词义缺少上下文，需先人工确认。",
    "最终用户": "候选动作：新增用例参与者（Actor）相关节点或仅补用例关系；需确定是否将角色纳入课程树。",
    "浮点数常量": "候选动作：新增“字面量与常量”知识点或 SyntaxElement；需确定采用课程树还是代码语法层表示。",
    "确定系统输入和输出": "候选动作：新增需求分析/系统边界知识点，归入 J1 需求与用例建模。",
    "程序实现": "候选动作：与“问题分析、程序设计三阶段”合并为程序设计过程知识单元；需确认是否纳入方法论层。",
    "行为": "候选动作：仅补上下文对齐。它可能指对象行为或动态行为建模，不能脱离材料上下文直接归并。",
    "调用者": "候选动作：新增“调用者与异常传播”关系性知识点或仅补 F1_3 关系；需确认是否拆分。",
    "问题分析": "候选动作：与“程序设计三阶段”合并为分析阶段知识点；需确认方法论层范围。",
    "基于LLM的软件开发": "候选动作：新增“AI辅助软件开发”知识域下的课程单元；需先确认是否正式纳入。",
    "大语言模型概述": "候选动作：新增“AI辅助软件开发”知识域下的知识点；需先确认是否正式纳入。",
    "字符编码的发展历程": "候选动作：新增“字符编码演变”知识点，归入字符串与序列；需确认历史内容是否入树。",
    "成员的实现": "候选动作：新增“类成员的定义与实现”知识点，需先确认其与命名空间/类定义的准确归属。",
    "测试生成": "候选动作：在“AI辅助软件开发”下新增测试生成单元；需先确认是否正式纳入。",
    "程序设计三阶段": "候选动作：新增“问题分析—设计—程序实现”知识单元；需确认方法论层范围。",
    "编码辅助": "候选动作：在“AI辅助软件开发”下新增编码辅助单元；需先确认是否正式纳入。",
    "自然语言编程": "候选动作：在“AI辅助软件开发”下新增自然语言编程知识点；需先确认是否正式纳入。",
    "软件工程3.0时代": "候选动作：作为 AI 辅助软件开发的背景概念或课程单元；需先确认是否入正式知识树。",
    "需求理解": "候选动作：可新增 J1 下的需求理解节点，或作为 LLM 软件开发单元；需确定唯一归属。",
    "面向对象分析方法": "候选动作：新增 OOAD 分析方法知识单元，归入 J 面向对象分析与设计。",
}

# 以下项是标题、人物/机构、教材、案例角色、宣传性表达或局部例题，不应成为正式知识节点。
REJECT_REASONS = {
    "Oracle Java官方资源": "外部参考资源，不是课程知识。",
    "TIOBE Index": "排行榜/外部资料，不是课程知识。",
    "编程语言": "泛化词，不能替代具体编程语言节点或课程知识点。",
    "西安电子科技大学计算机学院": "机构信息。",
    "Robert C. Martin": "人物引文署名。",
    "学习 C++": "课程学习目标/标题。",
    "学习目标": "教学目标，不是知识节点。",
    "张涛": "教师信息。",
    "思维方式": "教学建议，语义过宽。",
    "技术伦理守门人": "宣传性角色描述。",
    "数字生态架构师": "宣传性角色描述。",
    "整数各位数字相加": "局部练习题情境，应由题库处理。",
    "纠正设计缺陷": "Python 版本说明中的描述性短语。",
    "编程思想": "教学建议，不能确定唯一知识树位置。",
    "蔡希尧教授": "人物信息。",
    "解的概念确定": "叙述性短语，不是稳定术语。",
    "设施骨架": "教学比喻，不是可定义的知识实体。",
    "设计理念": "教学建议，语义过宽。",
    "选择程序设计语言的重要性": "教学论述，不是可考察的原子知识点。",
    "金益民教授": "人物信息。",
    "陈平教授": "人物信息。",
    "面向分析/设计人员": "课件受众角色。",
    "面向系统工程师": "课件受众角色。",
    "面向系统集成人员": "课件受众角色。",
    "面向编程人员": "课件受众角色。",
    "C++标准委员会": "标准组织信息。",
    "Core Java (Volume 1)": "教材名称。",
    "Database Schema Design": "教材/章节名称，且当前没有独立数据库建模范围。",
    "Introduction to Java Programming": "教材名称。",
    "Java程序设计": "课程/教材名称。",
    "Java编程思想": "教材名称。",
    "Java语言程序设计(第4版)": "教材名称。",
    "Python 1 阶段": "历史分期细节；若批准“Python版本演进”，应作为其证据属性而非独立节点。",
    "Python 2 阶段": "历史分期细节；若批准“Python版本演进”，应作为其证据属性而非独立节点。",
    "Python 3 阶段": "历史分期细节；若批准“Python版本演进”，应作为其证据属性而非独立节点。",
    "TIOBE编程语言社区排行榜": "排行榜/外部资料。",
    "第4章 Unicode与字符串": "课件章节标题。",
    "第7章 面向对象程序设计": "课件章节标题。",
}


def load_candidates(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError(f"候选文件格式错误：{path}")
    return [item for item in candidates if isinstance(item, dict)]


def as_row(name: str, action: str, record_count: int) -> dict[str, Any]:
    return {"name": name, "record_count": record_count, "action": action}


def markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = ["| 候选项 | 出现次数 | 建议处理 |", "|---|---:|---|"]
    for row in rows:
        action = str(row["action"]).replace("|", "\\|")
        lines.append(f"| {row['name']} | {row['record_count']} | {action} |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="生成课程知识候选人工复核清单")
    parser.add_argument("--baseline", required=True, help="处理前候选报告")
    parser.add_argument("--current", required=True, help="处理后候选报告")
    parser.add_argument("--output-dir", required=True, help="审核文档输出目录")
    args = parser.parse_args()

    baseline = load_candidates(Path(args.baseline))
    current = load_candidates(Path(args.current))
    baseline_names = {str(item.get("name", "")).strip() for item in baseline}
    current_names = [str(item.get("name", "")).strip() for item in current]
    current_name_set = set(current_names)
    handled_names = baseline_names - current_name_set

    unknown_handled = sorted(handled_names - set(DIRECT_ACTIONS))
    missing_handled = sorted(set(DIRECT_ACTIONS) - handled_names)
    unknown_current = sorted(current_name_set - set(NEEDS_CONFIRMATION) - set(REJECT_REASONS))
    overlap = sorted(set(NEEDS_CONFIRMATION) & set(REJECT_REASONS))
    if unknown_handled or missing_handled or unknown_current or overlap:
        raise ValueError(
            "候选复核策略未覆盖全部条目："
            f"unknown_handled={unknown_handled}; missing_handled={missing_handled}; "
            f"unknown_current={unknown_current}; overlap={overlap}"
        )

    counts = Counter(current_names)
    direct_rows = [as_row(name, DIRECT_ACTIONS[name], 1) for name in sorted(handled_names)]
    confirmation_rows = [as_row(name, NEEDS_CONFIRMATION[name], counts[name]) for name in sorted(NEEDS_CONFIRMATION)]
    reject_rows = [as_row(name, REJECT_REASONS[name], counts[name]) for name in sorted(REJECT_REASONS)]
    review = {
        "baseline_candidate_records": len(baseline),
        "baseline_unique_candidates": len(baseline_names),
        "directly_handled_unique_candidates": len(handled_names),
        "remaining_candidate_records": len(current),
        "remaining_unique_candidates": len(current_name_set),
        "recommended_accept": direct_rows,
        "needs_user_confirmation": confirmation_rows,
        "recommended_reject": reject_rows,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "candidate_review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 编程领域知识图谱候选节点复核清单",
        "",
        "## 复核结论",
        "",
        f"- 初始候选：{len(baseline)} 条记录，{len(baseline_names)} 个唯一名称。",
        f"- 已按直接材料证据纳入：{len(handled_names)} 个唯一名称。",
        f"- 当前仍待处理：{len(current)} 条记录，{len(current_name_set)} 个唯一名称。",
        "- 原则：仅把语义明确、课程位置明确且有直接材料证据的内容写入正式图谱；"
        "同义词才进入 aliases，相关概念通过节点和边表达，教材标题、人物、机构、例题情境不入树。",
        "",
        "## 已按建议纳入",
        "",
        "下表内容已进入正式 `graph_hierarchy` 图谱，且已通过正式质量审计。",
        *markdown_table(direct_rows),
        "",
        "## 需要你确认",
        "",
        "这些项不是错误抽取，但会扩大课程边界、增加实体/关系类型或需要明确树位置，因此仍保留在候选报告中，不会被自动入库。",
        *markdown_table(confirmation_rows),
        "",
        "## 建议拒绝",
        "",
        "这些项保持在审计记录中，但不进入正式知识树、技术实体层或关系层。",
        *markdown_table(reject_rows),
        "",
        "## 可重复性",
        "",
        "每次候选报告变化后重新运行本脚本。若出现未登记的新候选，脚本会报错而不是静默遗漏，"
        "随后应先补充本文件中的处理规则，再决定是否更新知识树或 Schema。",
    ]
    (output_dir / "candidate_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已纳入：{len(handled_names)}")
    print(f"待确认：{len(confirmation_rows)}")
    print(f"建议拒绝：{len(reject_rows)}")
    print(f"审核文档：{output_dir / 'candidate_review.md'}")


if __name__ == "__main__":
    main()
