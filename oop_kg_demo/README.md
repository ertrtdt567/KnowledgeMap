# 面向对象编程知识图谱 Demo

本目录包含知识图谱构建 Demo 的五个核心阶段代码：

- `part1_preprocess/`：多源教学材料预处理，将 PPT/PDF/TXT/JSON 习题清洗并切分为 `clean_chunks.json`。
- `part2_extract/`：实体与关系抽取，基于 `clean_chunks.json` 调用大模型 API 并进行 Schema 校验、去重和质量统计。
- `part3_normalize/`：实体融合、关系消歧与标准图谱生成，将抽取结果整理为 `standard_graph.json`。
- `part4_neo4j/`：Neo4j 入库脚本生成、可选自动导入与 Demo 查询准备。
- `part5_questions/`：习题节点构建、习题到知识点自动映射、映射质量评估与 Neo4j 习题层入库。

## 运行顺序

1. 先运行第一部分，生成清洗后的知识片段：

```powershell
python part1_preprocess/preprocess_materials.py --input input --output output/clean_chunks.json
```

2. 再运行第二部分，抽取实体和关系：

```powershell
python part2_extract/extract_graph.py --input output/clean_chunks.json --output-dir output/graph_extract --provider qwen --limit 20
```

其中 `--limit` 用于测试模式；去掉后会处理全部 chunk。

3. 运行第三部分，生成可入库的标准图谱：

```powershell
python part3_normalize/normalize_graph.py --input-dir output/graph_extract --output-dir output/graph_normalized --provider qwen
```

如果只想本地调试，不调用 API：

```powershell
python part3_normalize/normalize_graph.py --input-dir output/graph_extract --output-dir output/graph_normalized --no-llm
```

4. 运行第四部分，生成 Neo4j 导入脚本和展示查询：

```powershell
python part4_neo4j/import_to_neo4j.py --input output/graph_normalized/standard_graph.json --output-dir output/neo4j_import --generate-cypher
```

Neo4j Desktop 启动后，也可以配置 `NEO4J_PASSWORD` 并自动导入：

```powershell
python part4_neo4j/import_to_neo4j.py --input output/graph_normalized/standard_graph.json --output-dir output/neo4j_import --execute
```

5. 运行第五部分，把习题纳入图谱并评估映射质量：

```powershell
python part5_questions/process_questions.py --input part5_questions/data/sample_questions.json --output-dir output/question_mapping
python part5_questions/map_questions_to_knowledge.py --questions output/question_mapping/questions.json --graph output/graph_normalized/standard_graph.json --output-dir output/question_mapping --provider qwen
python part5_questions/evaluate_question_mapping.py --questions output/question_mapping/questions.json --links output/question_mapping/question_knowledge_links.json --output output/question_mapping/question_mapping_evaluation.json
```

只想离线调试第五部分时，可以把映射命令改为：

```powershell
python part5_questions/map_questions_to_knowledge.py --questions output/question_mapping/questions.json --graph output/graph_normalized/standard_graph.json --output-dir output/question_mapping --no-llm
```

Neo4j Desktop 启动后，可以把习题层自动导入：

```powershell
python part5_questions/import_questions_to_neo4j.py --questions output/question_mapping/questions.json --links output/question_mapping/question_knowledge_links.json --output-dir output/neo4j_import --execute --clear-question-layer --uri bolt://127.0.0.1:7687 --database neo4j
```

## API Key

通义千问 API Key 使用环境变量：

```powershell
[Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY", "你的API_KEY", "User")
```

DeepSeek 可使用：

```powershell
[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "你的API_KEY", "User")
```

Neo4j 自动导入使用：

```powershell
[Environment]::SetEnvironmentVariable("NEO4J_PASSWORD", "你的Neo4j密码", "User")
```
