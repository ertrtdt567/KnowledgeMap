# 第五阶段：习题节点与知识点映射

这一阶段接在前四阶段之后，用来把“习题”纳入知识图谱。

## 目标

把 Java/OOP 样例题变成图谱中的 `Question` 节点，并建立：

- `Question -[:ASSESSES]-> KnowledgeNode`
- `Question -[:REQUIRES_ABILITY]-> Ability`
- `Question -[:HAS_DIFFICULTY]-> Difficulty`
- `Question -[:HAS_TYPE]-> QuestionType`

## 运行顺序

先生成标准习题：

```powershell
python work\oop_kg_demo\process_questions.py
```

再做习题到知识点映射。调用通义千问：

```powershell
python work\oop_kg_demo\map_questions_to_knowledge.py --provider qwen
```

离线规则模式：

```powershell
python work\oop_kg_demo\map_questions_to_knowledge.py --no-llm
```

评估映射质量：

```powershell
python work\oop_kg_demo\evaluate_question_mapping.py
```

生成 Neo4j 导入脚本：

```powershell
python work\oop_kg_demo\import_questions_to_neo4j.py
```

如果已经配置好 Neo4j 密码环境变量，可以自动导入：

```powershell
python work\oop_kg_demo\import_questions_to_neo4j.py --execute
```

## 主要输出

- `output\question_mapping\questions.json`
- `output\question_mapping\question_knowledge_links.json`
- `output\question_mapping\question_mapping_report.json`
- `output\question_mapping\question_mapping_evaluation.json`
- `output\neo4j_import\import_questions.cypher`
- `output\neo4j_import\demo_question_queries.cypher`
- `output\neo4j_import\question_import_report.json`

## Demo 说明

当前样例题库在 `data\sample_questions.json`，共 20 道 Java/OOP 题。

题型包括选择题、判断题、代码阅读题、代码改错题、编程填空题和简短编程题。

每道题都带有 `gold_knowledge_points`，作为人工标准答案，用来评估自动映射结果。
