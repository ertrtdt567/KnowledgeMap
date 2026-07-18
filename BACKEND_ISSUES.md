# 后端现状与问题清单

## 本次已处理

1. 根图不再分别截取 500 个节点和前 500 条边。根接口现在只返回课程层级：`KnowledgeDomain -> KnowledgeUnit -> KnowledgePoint`，共 48 个节点和 47 条完整关系。
2. 子图按节点类型返回数据。领域展示下级领域/单元，单元展示知识点；没有知识点的单元显示直接关联示例；知识点显示 CodeExample 及其语法、代码结构。
3. `KnowledgeDomain`、`KnowledgeUnit`、`KnowledgePoint`、`CodeExample` 等新 Schema 类型已映射到前端类型和颜色。
4. `part_of` 在前端响应中反向为“父级 -> 子级”，保持原始 JSON 不变。
5. 图谱 JSON 增加按文件修改时间失效的内存缓存，避免每个请求反复解析约 9.7 MB 文件。
6. 搜索结果增加 `graphId`，搜索 CodeExample 后可以跳到其最具体的知识点/单元/领域子图。
7. 启动脚本优先直接读取项目根目录的 `standard_graph.json\standard_graph.json`，以后替换源文件后无需再手工复制到后端输出目录。

## 数据侧仍需处理

1. 281 个 CodeExample 中，273 个至少有一条 `demonstrates`，8 个没有 `demonstrates`，其中 1 个完全无关系。
2. `demonstrates` 的目标粒度偏粗：477 条指向 KnowledgeDomain，196 条指向 KnowledgeUnit，只有 123 条指向 KnowledgePoint。要实现“所有示例都归到具体知识点”，生成组需要重新做最细粒度映射，前端不应猜测归属。
3. 19 个 KnowledgeUnit 中有 8 个没有下级 KnowledgePoint。当前界面会为这些单元显示直接关联示例，但课程目录仍不完整。
4. 图中有 4 条自环：`curriculum_B1` 和 `curriculum_F` 各有一条 `expresses_concept` 与一条 `has_syntax` 指向自身，应在标准化阶段删除。
5. 题目映射仍引用旧节点 `oopconcept_class`、`oopconcept_object`，新图谱中不存在这两个 ID，因此当前 1 道题无法关联到新知识点。

## 工程侧后续建议

1. 为根图、知识点子图、搜索跳转和题目映射增加自动化测试。
2. 图谱文件更新应采用临时文件写完后原子替换，避免 API 在写入一半时读取到不完整 JSON。
3. 健康检查应补充无效边、自环、孤立节点和失效题目映射统计，而不只报告文件数量。
4. 生产部署时收紧 CORS，不应长期使用 `Access-Control-Allow-Origin: *`。
