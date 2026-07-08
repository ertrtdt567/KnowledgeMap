# 第三部分：实体融合、关系消歧与标准图谱生成

`normalize_graph.py` 用于把第二部分生成的实体和关系整理成可导入 Neo4j 的标准图谱。

## 输入

默认读取第二部分输出目录：

```text
work/oop_kg_demo/output/graph_extract/
```

需要包含：

```text
entities.json
relations.json
extraction_report.json
```

其中 `extraction_report.json` 主要用于查看第二步质量，第三步核心读取的是 `entities.json` 和 `relations.json`。

## 输出

默认输出到：

```text
work/oop_kg_demo/output/graph_normalized/
```

会生成：

```text
standard_graph.json
normalization_report.json
normalization_cache/
```

`standard_graph.json` 是下一步 Neo4j 入库要用的标准图谱，核心结构是：

```json
{
  "nodes": [],
  "edges": [],
  "schema": {},
  "metadata": {}
}
```

`normalization_report.json` 用于调试和汇报，记录实体合并、关系过滤、大模型判断、数量变化等信息。

## 推荐运行方式

调用通义千问进行疑难实体消歧和关键关系复核：

```powershell
python work/oop_kg_demo/normalize_graph.py `
  --input-dir work/oop_kg_demo/output/graph_extract `
  --output-dir work/oop_kg_demo/output/graph_normalized `
  --provider qwen
```

如果只想先本地调试，不调用 API：

```powershell
python work/oop_kg_demo/normalize_graph.py `
  --input-dir work/oop_kg_demo/output/graph_extract `
  --output-dir work/oop_kg_demo/output/graph_normalized `
  --no-llm
```

## 处理原则

第三部分遵循两个保守原则：

```text
宁可少合并，也不要错合并。
宁可少保留关系，也不要把不确定关系写入标准图谱。
```

因此，规则无法确定且大模型也无法高置信判断的实体和关系，不会被强行合并或写入标准图谱。

## 与前两部分的关系

完整 Demo 流程是：

```text
第一部分 preprocess_materials.py
PPT/PDF/课本/习题 -> clean_chunks.json

第二部分 extract_graph.py
clean_chunks.json -> entities.json / relations.json / extraction_report.json

第三部分 normalize_graph.py
entities.json / relations.json -> standard_graph.json / normalization_report.json
```

第三部分不是重新抽取知识，而是把第二部分的粗糙图谱整理成可信、规范、可入库的标准图谱。
