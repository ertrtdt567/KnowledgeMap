# 02 实体与关系抽取

入口：`../src/extract_graph.py`

职责：依据 Schema 候选集合执行规则优先、LLM 补充的实体关系抽取，并保存证据片段、置信度、来源页码和质量统计。

`outputs/` 中的 `entities.json.gz`、`relations.json.gz` 是最终课程图实际使用的抽取结果；对应的 `extraction_report.json` 记录数量与异常。

API 调用缓存和失败模型目录未纳入发布包。

