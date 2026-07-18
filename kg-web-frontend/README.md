# 编程知识图谱前端

本项目是“知识驱动的智能编程辅导系统”的知识图谱前端，采用 React、Vite、Cytoscape.js 和 Lucide 实现五门课程的图谱浏览、搜索、子图下钻、节点详情、代码示例和习题查看。

## 环境要求

- Node.js 18+
- pnpm
- 正式演示时需启动本项目配套 Python API

## 本地启动

在 `kg-web-frontend` 目录安装依赖：

```powershell
pnpm install
```

创建 `.env.local` 并连接本地 API：

```powershell
Set-Content .env.local "VITE_KG_API_BASE=http://127.0.0.1:8000"
```

先启动相邻目录中的后端，再启动前端：

```powershell
powershell -ExecutionPolicy Bypass -File ..\KnowledgeMap-backend\start-api.ps1
pnpm dev
```

访问地址：

- 前端：`http://localhost:5173/`
- API 健康检查：`http://127.0.0.1:8000/api/health`

正式验收时，健康检查应显示 2,612 个节点、6,059 条关系、45 道题和 73 条题目映射，且无失效关系、自环、孤立节点或失效题目映射。

## 数据模式

配置 `VITE_KG_API_BASE` 时，前端从后端 API 加载正式数据。当前正式数据版本为 `v2026.07.18`，后端启动脚本会显式读取同版本图谱、题库和映射文件。

未配置 API 地址时，前端回退到 `src/data/mockGraph.js`。模拟数据仅用于界面开发，不能作为正式验收数据。

## 主要功能

- 五门课程根图和三层课程总览
- 知识领域、知识单元和知识点子图下钻
- 节点拖拽、缩放、适应视图和响应式布局
- 名称、别名、知识点及题目搜索跳转
- 节点详情、来源、关联节点和返回路径
- 代码示例原始材料展示
- 习题题干、选项、答案和知识点映射
- API 启动健康检查与数据完整性提示

## API 接口

前端使用以下接口：

```text
GET /api/health
GET /api/graphs/:graphId
GET /api/nodes/:nodeId
GET /api/search?q=关键词&limit=8
GET /api/questions
GET /api/questions/:questionId
GET /api/schema
```

图谱节点以 `id` 为稳定主键，`label` 为展示名；`children` 存在时表示可以进入对应子图。正式 JSON 中 `part_of` 的方向为“子节点 -> 父节点”，API 会将其适配为前端使用的父子视图。

## 构建与测试

生产构建：

```powershell
pnpm run build
```

运行 Playwright 自动化测试：

```powershell
pnpm run test:e2e
```

需要同时验证正在运行的本地 API 时：

```powershell
$env:KG_E2E_LIVE = "1"
pnpm run test:e2e
```

测试覆盖根图加载、子图钻取、搜索跳转、代码示例回退和习题弹窗。测试报告生成在 `playwright-report/`。

## 部署

Vercel 或 Netlify 构建命令使用 `pnpm run build`，输出目录为 `dist`。部署环境需要设置 `VITE_KG_API_BASE`，并保证后端允许该前端域名访问。只部署静态前端且不配置 API 时，页面会使用模拟数据。
