# 编程知识图谱前端

这是“知识驱动的智能编程辅导系统”的前端原型，采用 `React + Vite + Cytoscape.js` 实现课程知识图谱、节点详情、搜索和知识点钻取。

## 本地运行

```bash
pnpm install
pnpm dev
```

## 当前能力

- 课程级知识图谱展示
- 节点拖拽、缩放、适应视图
- 点击节点查看详情
- 点击“进入知识点”钻取子图谱
- 子图谱中保留父级知识点虚化背景
- 外部关联节点可继续跳转到其他子图谱
- 搜索知识点并跳转到对应图谱
- 支持模拟数据和后端接口两种模式

## 后端接口预留

默认使用 `src/data/mockGraph.js` 的模拟数据。后端准备好后，在 `.env` 中配置：

```bash
VITE_KG_API_BASE=http://localhost:8080
```

前端会自动切换为远程接口模式，并调用：

```text
GET /api/graphs/:graphId
GET /api/nodes/:nodeId
GET /api/search?q=递归
```

`GET /api/graphs/:graphId` 返回结构：

```json
{
  "id": "recursion",
  "title": "递归知识点子图谱",
  "subtitle": "知识点钻取视图",
  "focusNode": {
    "id": "recursion",
    "label": "递归",
    "summary": "父级节点说明"
  },
  "recommendedNodeId": "base-case",
  "metrics": [
    { "label": "子知识点", "value": "12" }
  ],
  "nodes": [
    {
      "id": "base-case",
      "label": "基线条件",
      "type": "core",
      "difficulty": "核心",
      "size": 74,
      "mastery": 0.68,
      "children": "base-case",
      "summary": "节点说明",
      "prerequisites": ["分支结构"],
      "outcomes": ["写出终止条件"],
      "exercises": 7,
      "position": { "x": -210, "y": -100 }
    }
  ],
  "edges": [
    {
      "id": "r1",
      "source": "base-case",
      "target": "recursive-step",
      "label": "共同构成",
      "type": "related",
      "strength": 92
    }
  ]
}
```

字段说明：

- `node.children`：存在时表示可以继续钻取，值为目标 `graphId`
- `node.position`：可选；后端不传时前端会使用自动布局
- `node.type`：建议使用 `course | topic | core | concept | practice | external | ghost`
- `edge.type`：建议使用 `contains | prerequisite | related | practice | external`

部署到 Vercel 时，导入仓库后保持默认 Vite 配置即可。
