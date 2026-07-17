# 最终版流水线

以下命令以仓库中的 `programming_kg_final` 为当前目录。`<input>` 表示项目组单独保存的原始课程资料目录。

## 1. 预处理

```powershell
python src/preprocess_materials.py --input <input> --output <clean_chunks.json> --mode programming
```

输出为带 `chunk_id`、文本、来源文件、页码和课程信息的 JSON 片段。

## 2. 实体关系抽取

```powershell
python src/extract_graph.py --input <clean_chunks.json> --output-dir <graph_extract> --provider qwen --model <model>
```

程序优先使用确定性规则；规则无法可靠判定时调用模型。不要使用 `--refresh-cache` 重复消耗额度，除非明确需要重抽。

## 3. 规范化

```powershell
python src/normalize_graph.py --input-dir <graph_extract> --output-dir <graph_normalized> --provider qwen --model <model>
```

该阶段执行实体融合、别名清洗、关系方向修正、Schema 约束和证据聚合。

## 4. 构建课程中心图

```powershell
python src/build_course_centered_graph.py --catalog config/programming_curriculum_v0_13_candidate_finalized.json --uml-extract-dir <uml_extract_or_normalized> --uml-chunks <uml_clean_chunks.json> --output-dir <course_graph>
```

脚本默认读取 Java/Python/C++ 主课程组与数据结构的最终目录。若目录位置不同，显式传入对应参数。

## 5. 质量审计

```powershell
python src/audit_course_centered_graph.py --graph <course_graph/standard_graph.json> --catalog config/programming_curriculum_v0_13_candidate_finalized.json --output <quality_audit_report.json>
```

正式图必须满足：Schema 校验通过、无悬空边、无非法自环、课程层级可达、CodeExample 叶子约束成立、候选节点未混入正式节点。

## 6. 习题统一与映射

题面和答案先经过来源配对与人工审核，再运行：

```powershell
python src/build_unified_verified_question_bank.py <按脚本帮助填写来源参数>
python src/map_questions_to_knowledge.py --questions <formal_questions.json> --graph <course_graph/standard_graph.json> --output-dir <question_mapping> --provider qwen --model <model>
```

只接受当前图谱中真实存在的知识点 ID。无答案、答案证据不足或映射不确定的题目保留在复核清单，不进入正式图。

## 7. 生成完整交付图

```powershell
python src/build_frontend_complete_graph.py --graph <course_graph/standard_graph.json> --questions <formal_precise_questions.json> --links <formal_precise_question_knowledge_links.json> --output <complete_graph/standard_graph.json>
```

发布包中的最终结果为 `08_delivery/standard_graph.json.gz`。

## 8. Neo4j 完整替换

```powershell
python src/import_to_neo4j.py --input <complete_graph/standard_graph.json> --output-dir <neo4j_import> --execute --clear --uri $env:NEO4J_URI --database $env:NEO4J_DATABASE
```

本版图谱结构与早期 OOP Demo 不同，正式导入使用完整替换，不使用旧图增量叠加。

