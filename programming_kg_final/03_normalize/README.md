# 03 融合消歧与规范化

入口：`../src/normalize_graph.py`

Schema：`../src/formal_schema_v5.py` 至 `formal_schema_v8_course_centered.py`

职责：名称规范化、别名合并、同义实体消歧、关系方向校正、类型约束、非法边过滤和证据聚合。规则无法确定的候选可调用模型复核，不允许低置信结果直接污染正式图谱。

`outputs/` 保存三组最终规范化图和报告。

