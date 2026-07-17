# 编程领域知识图谱最终版

本目录是 `KnowledgeMap` 项目的最终课程中心版知识图谱发布包。它保留从课程资料预处理、实体关系抽取、融合消歧、课程知识树构建、Schema 校验、习题映射到 Neo4j 交付的完整链路，并与仓库中早期“面向对象 Demo”代码隔离。

## 最终交付物

- 完整图谱（课程知识点 + 习题 + 映射）：`08_delivery/standard_graph.json.gz`
- 纯课程知识图谱：`04_curriculum/outputs/course_centered_standard_graph.json.gz`
- 最终课程目录：`config/programming_curriculum_v0_13_candidate_finalized.json`
- 完整图审计：`08_delivery/frontend_complete_graph_audit.json`
- 全流程实现说明：`docs/项目完整实现总结.md`

运行 `python tools/restore_artifacts.py` 可将所有 `.json.gz` 恢复为 JSON。恢复后，前端应使用 `08_delivery/standard_graph.json`。

## 流程结构

| 阶段 | 目录 | 核心源码 |
|---|---|---|
| 1. 资料预处理 | `01_preprocess` | `preprocess_materials.py` |
| 2. 实体关系抽取 | `02_extract` | `extract_graph.py` |
| 3. 融合消歧与规范化 | `03_normalize` | `normalize_graph.py`、Schema v5-v8 |
| 4. 课程树与课程中心图 | `04_curriculum` | `curriculum_catalog.py`、`enrich_curriculum_graph.py`、`build_course_centered_graph.py` |
| 5. 三轮质量核验 | `05_quality` | `audit_*.py`、关系金标准脚本 |
| 6. 习题处理与映射 | `06_questions` | 题目解析、答案核验、`map_questions_to_knowledge.py`、`build_frontend_complete_graph.py` |
| 7. Neo4j 入库 | `07_neo4j` | `import_to_neo4j.py`、`import_questions_to_neo4j.py` |
| 8. 最终交付 | `08_delivery` | 完整标准图谱和完整性审计 |

所有可执行源码统一放在 `src/`，各阶段目录保存该阶段说明与最终有效产物。这样避免同一公共模块在多个阶段重复出现并产生版本分叉。

## 最终数据范围

课程中心图包含 Java、Python、C++、数据结构、UML 面向对象设计与分析五门课程。跨课程公共概念使用全局核心概念节点复用，各课程通过映射关系连接到核心概念；课程内部知识点仍保持各自的层级和证据来源。

完整交付图在课程中心图上增加了经过审核的习题节点和题目到知识点的映射关系。候选项、证据不足题目和未通过复核的关系不进入最终标准图谱。

## 环境变量

复制 `.env.example` 中的变量名到本机环境。密钥和密码不得写入仓库。

主要变量：

- `DASHSCOPE_API_KEY`：大模型抽取、复核和题目映射
- `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`、`NEO4J_DATABASE`：Neo4j 自动导入

## 推荐执行顺序

1. `python src/preprocess_materials.py ...`
2. `python src/extract_graph.py ...`
3. `python src/normalize_graph.py ...`
4. `python src/build_course_centered_graph.py ...`
5. `python src/audit_course_centered_graph.py ...`
6. 运行 `06_questions/README.md` 中的题库统一与映射流程
7. `python src/build_frontend_complete_graph.py ...`
8. `python src/import_to_neo4j.py --execute --clear ...`

完整参数和最终产物对应关系见各阶段 README。

## 版本边界

本发布包不包含：原始 PPT/PDF/Word、API 响应缓存、失败模型输出、烟雾测试目录、已移除的算法设计课程、早期 OOP Demo 快照。上述内容不影响最终图谱复现；原始课程资料需由项目组按授权方式单独保存。

