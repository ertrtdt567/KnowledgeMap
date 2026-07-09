# 知识图谱 Web API

`api_server.py` 是面向前端联调的轻量 Web 接口层。它不依赖 FastAPI/Flask，只使用 Python 标准库，直接读取前四/五阶段生成的 JSON 产物。

## 启动

在 `oop_kg_demo` 目录运行：

```powershell
python api_server.py --host 127.0.0.1 --port 8000
```

如果输出文件不在默认位置，可以显式指定：

```powershell
python api_server.py `
  --graph output/graph_normalized/standard_graph.json `
  --questions output/question_mapping/questions.json `
  --question-links output/question_mapping/question_knowledge_links.json
```

也可以用环境变量：

```powershell
$env:KG_GRAPH_PATH = "output/graph_normalized/standard_graph.json"
$env:KG_QUESTIONS_PATH = "output/question_mapping/questions.json"
$env:KG_QUESTION_LINKS_PATH = "output/question_mapping/question_knowledge_links.json"
python api_server.py
```

## 前端配置

前端 Vite 项目可以设置：

```text
VITE_KG_API_BASE=http://127.0.0.1:8000
```

已有前端预留的接口会自动请求：

```text
GET /api/graphs/root
GET /api/nodes/{nodeId}
GET /api/search?q=keyword
```

## 接口

### 健康检查

```http
GET /api/health
```

返回当前读取到的图谱、题目、映射文件路径和数量。

### 前端图谱

```http
GET /api/graphs/root
GET /api/graphs/{nodeId}?depth=1
```

返回适配前端 Cytoscape 视图的结构：

```json
{
  "id": "root",
  "title": "面向对象编程知识图谱",
  "metrics": [],
  "nodes": [],
  "edges": []
}
```

`/api/graphs/{nodeId}` 会返回某个知识点的一跳子图，可用于双击进入二级图谱。

### 节点详情

```http
GET /api/nodes/{nodeId}
GET /api/nodes/{nodeId}/neighbors?depth=1
```

节点详情包含邻居、相关关系、关联题目。

### 搜索

```http
GET /api/search?q=多态&limit=12
```

会同时搜索知识点和题目。

### 题目

```http
GET /api/questions
GET /api/questions?knowledgeId={nodeId}
GET /api/questions/{questionId}
```

用于展示某个知识点关联的练习题。

### 原始图谱

```http
GET /api/graph
GET /api/schema
```

`/api/graph` 返回 `standard_graph.json` 的原始 `nodes/edges/schema/metadata`，`/api/schema` 返回节点和关系类型摘要。

## 说明

- 这个 API 层是文件型服务，不负责重新抽取图谱。
- 如果 Neo4j 尚未部署，前端仍可通过 JSON 文件联调。
- 如果后续要改成 Neo4j 实时查询，可以保留这些 URL，不改变前端调用方式，只替换 `KnowledgeGraphStore` 的数据来源。
