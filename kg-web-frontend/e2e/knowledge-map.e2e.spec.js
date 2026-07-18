import { expect, test } from "@playwright/test";

const rootNode = {
  id: "course-python",
  label: "python",
  type: "course",
  sourceType: "Course",
  difficulty: "课程",
  size: 128,
  mastery: 0.98,
  confidence: 0.98,
  relationCount: 2,
  sourceCount: 1,
  aliases: [],
  summary: "Python 课程知识总览",
  prerequisites: [],
  outcomes: [],
  exercises: 0,
  children: "course-python",
  systemNode: false,
  raw: { id: "course-python", type: "Course" },
  layer: 1,
  position: { x: 180, y: -40 }
};

const recursionNode = {
  id: "recursion",
  label: "递归",
  type: "concept",
  sourceType: "KnowledgePoint",
  difficulty: "知识点",
  size: 94,
  mastery: 0.92,
  confidence: 0.92,
  relationCount: 2,
  sourceCount: 2,
  aliases: [],
  summary: "通过函数自身调用解决可分解的问题。",
  prerequisites: [],
  outcomes: [],
  exercises: 1,
  children: null,
  systemNode: false,
  raw: { id: "recursion", type: "KnowledgePoint" },
  layer: 2,
  position: { x: 380, y: 50 }
};

const codeExampleNode = {
  id: "course-python__CodeExample_demo",
  label: "示例 · 引用赋值",
  type: "practice",
  sourceType: "CodeExample",
  difficulty: "知识点",
  size: 72,
  mastery: 0.95,
  confidence: 0.95,
  relationCount: 1,
  sourceCount: 1,
  aliases: [],
  summary: "用于说明引用赋值效果的示例。",
  prerequisites: [],
  outcomes: [],
  exercises: 0,
  children: null,
  systemNode: false,
  raw: {
    id: "course-python__CodeExample_demo",
    local_id: "CodeExample_demo",
    type: "CodeExample",
    sources: [
      {
        source_file: "Python 示例课件.pdf",
        page: 12,
        content: "下面程序段的运行结果是什么？\\nvalue = 1\\nref = value\\nref = 5\\nprint(value)"
      }
    ]
  },
  layer: 2,
  position: { x: 460, y: -80 }
};

const graph = (id, title, nodes, recommendedNodeId) => ({
  id,
  title,
  subtitle: "知识点关联子图",
  description: "测试图谱",
  recommendedNodeId,
  focusNode: id === "root" ? null : nodes[0],
  viewMode: id === "root" ? "course-overview" : "network",
  legend: [
    { layer: 1, label: "第一层 · 课程", color: "#ff5375" },
    { layer: 2, label: "第二层 · 主要知识点", color: "#ff8b63" },
    { layer: 3, label: "第三层 · 次要知识点", color: "#a66bff" }
  ],
  metrics: [],
  nodes,
  edges: []
});

const graphs = {
  root: graph(
    "root",
    "五门课程知识图谱",
    [
      {
        id: "course_graph_hub",
        label: "面向编程领域的知识图谱",
        type: "concept",
        sourceType: "GraphHub",
        size: 140,
        summary: "课程总览",
        children: null,
        systemNode: true,
        layer: 1,
        position: { x: 0, y: 0 }
      },
      rootNode
    ],
    "course-python"
  ),
  "course-python": graph("course-python", "python 子图", [rootNode, recursionNode], "course-python"),
  recursion: graph("recursion", "递归 子图", [recursionNode], "recursion")
};

const questionResult = {
  id: "Q-DEMO-1",
  label: "引用赋值后 value 的输出结果是什么？",
  resultType: "question",
  type: "code_reading",
  type_label: "代码阅读题",
  stem: "引用赋值后 value 的输出结果是什么？",
  code: "value = 1\\nref = value\\nref = 5\\nprint(value)",
  options: ["A. 1", "B. 5"],
  answer: "A. 1",
  analysis: "该示例用于验证引用绑定语义。"
};

async function mockApi(page) {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const send = (body) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(body)
    });

    if (url.pathname.startsWith("/api/graphs/")) {
      const graphId = decodeURIComponent(url.pathname.split("/").pop());
      return send(graphs[graphId] ?? graphs.root);
    }
    if (url.pathname.startsWith("/api/nodes/")) {
      const nodeId = decodeURIComponent(url.pathname.split("/").pop());
      const node = [rootNode, recursionNode, codeExampleNode].find((item) => item.id === nodeId);
      return send(node ?? recursionNode);
    }
    if (url.pathname === "/api/search") {
      const query = url.searchParams.get("q") ?? "";
      if (query.includes("递归")) {
        return send([{ ...recursionNode, graphId: "recursion", resultType: "knowledge" }]);
      }
      if (query.includes("示例")) {
        return send([{ ...codeExampleNode, graphId: "course-python", resultType: "knowledge" }]);
      }
      if (query.includes("练习")) {
        return send([questionResult]);
      }
      return send([]);
    }
    return send({});
  });
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("根图加载并可钻取后返回", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "五门课程知识图谱" })).toBeVisible();
  await expect(page.getByLabel("节点层级图例")).toBeVisible();
  await expect(page.getByLabel("知识图谱画布").locator(".cy-canvas")).toBeVisible();
  await expect(page.getByRole("button", { name: "进入子图" })).toBeVisible();

  await page.getByRole("button", { name: "进入子图" }).click();
  await expect(page.getByRole("heading", { name: "python 子图" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "图谱路径" })).toContainText("python");

  await page.getByRole("button", { name: "返回上级" }).click();
  await expect(page.getByRole("heading", { name: "五门课程知识图谱" })).toBeVisible();
});

test("搜索知识点后跳转到对应子图", async ({ page }) => {
  await page.goto("/");
  const search = page.getByPlaceholder("输入名称或关键词");
  await search.fill("递归");
  await page.getByRole("option", { name: /递归/ }).click();

  await expect(page.getByRole("heading", { name: "递归 子图" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "图谱路径" })).toContainText("递归");
  await expect(page.getByRole("heading", { name: "递归", exact: true })).toBeVisible();
});

test("新版代码示例可回退展示图谱中的原题材料", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("输入名称或关键词").fill("示例");
  await page.getByRole("option", { name: /示例 · 引用赋值/ }).click();

  await expect(page.getByRole("heading", { name: "原题" })).toBeVisible();
  await expect(page.getByText("下面程序段的运行结果是什么？", { exact: false })).toBeVisible();
  await expect(page.getByText("Python 示例课件.pdf · P12")).toBeVisible();
});

test("搜索题目可打开练习弹窗", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("输入名称或关键词").fill("练习");
  await page.getByRole("option", { name: /引用赋值后 value 的输出结果是什么/ }).click();

  const dialog = page.getByRole("dialog", { name: "知识点练习" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("引用赋值后 value 的输出结果是什么？");
  await page.getByRole("button", { name: "关闭习题" }).click();
  await expect(dialog).toBeHidden();
});
