# 05 质量核验

质量控制包含三层：

1. 课程知识树覆盖和层级校验。
2. Schema 类型、方向、基数、自环、悬空边和叶子约束校验。
3. 人工复核候选知识点、易混淆关系和抽样三元组。

入口：`audit_course_centered_graph.py`、`audit_formal_graph.py`、`build_relation_gold_sample.py`、`apply_relation_first_review.py`。

`reports/` 保存最终课程图审计以及 200 条关系金标准和首轮人工复核结果。

