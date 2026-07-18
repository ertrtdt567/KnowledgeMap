// 编程领域知识图谱 Demo 查询
// 生成时间：2026-07-18T02:45:57
// 用法：把下面任意一段查询复制到 Neo4j Browser 中运行。

// 1. 整体图谱预览
MATCH p=(n:KnowledgeNode)-[r]->(m:KnowledgeNode)
RETURN p
LIMIT 80;

// 2. 面向对象核心概念网络
MATCH p=(n:OOPConcept)-[r]-(m:OOPConcept)
WHERE n.name IN ['类', '对象', '封装', '继承', '多态', '抽象', '接口']
   OR m.name IN ['类', '对象', '封装', '继承', '多态', '抽象', '接口']
RETURN p
LIMIT 80;

// 3. 语法与概念对应
MATCH p=(s:SyntaxRule)-[:`表达概念`|`具有语法`]-(c:OOPConcept)
RETURN p
LIMIT 50;

// 4. 学习路径查询
MATCH p=(:OOPConcept {name: '继承'})-[:`前置依赖`*1..3]->(:OOPConcept)
RETURN p
LIMIT 50;

// 5. Java 与 C++ 差异
MATCH p=(:ProgrammingLanguage {name: 'Java'})-[:`不同于`]-(:ProgrammingLanguage)
RETURN p
LIMIT 20;

// 6. 查看某个知识点详情
MATCH (n:KnowledgeNode {name: '多态'})
RETURN n.id AS id,
       labels(n) AS labels,
       n.description AS description,
       n.confidence AS confidence,
       n.source_files AS source_files,
       n.source_pages AS source_pages;

// 7. 节点类型分布
MATCH (n:KnowledgeNode)
RETURN n.type AS node_type, count(n) AS count
ORDER BY count DESC;

// 8. 关系类型分布
MATCH (:KnowledgeNode)-[r]->(:KnowledgeNode)
RETURN type(r) AS relation_type, count(r) AS count
ORDER BY count DESC;

// 9. 查看某个概念的一跳邻居
MATCH p=(n:KnowledgeNode {name: '多态'})-[r]-(m:KnowledgeNode)
RETURN p
LIMIT 50;

// 10. 查看证据来源
MATCH (n:KnowledgeNode {name: '多态'})
RETURN n.name AS name,
       n.source_files AS source_files,
       n.source_pages AS source_pages,
       n.sources_json AS sources_json;
