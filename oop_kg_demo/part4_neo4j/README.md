# 第四部分：Neo4j 入库与展示查询

`import_to_neo4j.py` 用于把第三部分生成的 `standard_graph.json` 转换成 Neo4j 图数据库可以使用的内容。

## 输入

默认读取：

```text
work/oop_kg_demo/output/graph_normalized/standard_graph.json
```

## 输出

默认输出到：

```text
work/oop_kg_demo/output/neo4j_import/
```

会生成：

```text
import_graph.cypher
demo_queries.cypher
neo4j_import_report.json
```

其中：

- `import_graph.cypher`：导入节点和关系的 Cypher 脚本。
- `demo_queries.cypher`：汇报和展示用的查询脚本。
- `neo4j_import_report.json`：记录节点数量、关系数量、执行状态和生成文件。

## 节点设计

Neo4j 节点采用：

```text
KnowledgeNode + 具体实体类型标签
```

例如：

```cypher
(:KnowledgeNode:OOPConcept {name: "多态"})
(:KnowledgeNode:SyntaxRule {name: "abstract"})
(:KnowledgeNode:ProgrammingLanguage {name: "Java"})
```

这样既可以统一查询所有知识节点，也可以按实体类型查询。

## 关系设计

关系类型使用标准 Schema 的大写形式：

```text
part_of             -> :PART_OF
prerequisite_of     -> :PREREQUISITE_OF
implemented_in      -> :IMPLEMENTED_IN
differs_from        -> :DIFFERS_FROM
```

## 方式一：只生成 Cypher 文件

你现在还没有配置好 Neo4j 时，先运行这一种即可：

```powershell
& "C:\Users\23189\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" work\oop_kg_demo\import_to_neo4j.py --generate-cypher
```

运行后会生成：

```text
work\oop_kg_demo\output\neo4j_import\import_graph.cypher
work\oop_kg_demo\output\neo4j_import\demo_queries.cypher
work\oop_kg_demo\output\neo4j_import\neo4j_import_report.json
```

然后打开 Neo4j Browser，把 `import_graph.cypher` 里的内容复制进去执行。

## 方式二：自动连接 Neo4j 并导入

等你安装并启动 Neo4j Desktop 后，可以使用自动导入。

常见本地配置：

```text
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=你创建数据库时设置的密码
```

在 PowerShell 中设置密码环境变量：

```powershell
[Environment]::SetEnvironmentVariable("NEO4J_PASSWORD", "你的Neo4j密码", "User")
```

重新打开 PowerShell 后运行：

```powershell
& "C:\Users\23189\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" work\oop_kg_demo\import_to_neo4j.py --execute
```

如果你的 Neo4j 地址或用户名不是默认值，可以这样指定：

```powershell
& "C:\Users\23189\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" work\oop_kg_demo\import_to_neo4j.py `
  --execute `
  --uri bolt://localhost:7687 `
  --user neo4j
```

## 重复导入策略

脚本默认不会清空旧图谱，而是按 `id` 合并更新：

```cypher
MERGE (n:KnowledgeNode {id: ...})
MERGE (source)-[r:REL_TYPE {id: ...}]->(target)
```

这意味着你可以重复运行导入，不会产生重复节点。

如果确实需要清空旧图谱后重新导入，才使用：

```powershell
& "C:\Users\23189\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" work\oop_kg_demo\import_to_neo4j.py --execute --clear
```

## 展示查询

导入完成后，在 Neo4j Browser 中打开：

```text
work\oop_kg_demo\output\neo4j_import\demo_queries.cypher
```

里面包含：

```text
1. 整体图谱预览
2. 面向对象核心概念网络
3. 语法与概念对应
4. 学习路径查询
5. Java 与 C++ 差异
6. 某个知识点详情
7. 节点类型分布
8. 关系类型分布
9. 某个概念的一跳邻居
10. 证据来源查询
```

## 常见问题

如果 `--execute` 提示没有 `NEO4J_PASSWORD`，说明密码环境变量没有配置，或者配置后没有重新打开 PowerShell。

如果提示没有安装 `neo4j` 驱动，可以先使用 `import_graph.cypher` 手动导入；自动导入等 Python 环境安装 Neo4j 驱动后再使用。

如果 Neo4j Browser 中执行 Cypher 报错，先确认数据库已经启动，并且使用的是 Neo4j 4.4 或 5.x 版本。
