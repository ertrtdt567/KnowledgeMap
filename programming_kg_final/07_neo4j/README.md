# 07 Neo4j 入库

课程图入口：`../src/import_to_neo4j.py`

习题层入口：`../src/import_questions_to_neo4j.py`

入库验证：`../src/verify_question_import.py`

正式替换图谱时使用 `--execute --clear`，确保旧架构数据不会和课程中心版混合。连接信息从环境变量读取，仓库不保存密码。

`reports/` 保存最后一次课程图和习题层自动导入结果。

