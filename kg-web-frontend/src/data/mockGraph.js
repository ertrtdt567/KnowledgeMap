export const graphCatalog = {
  root: {
    id: "root",
    title: "程序设计基础知识图谱",
    subtitle: "课程级知识网络",
    description:
      "围绕编程基础课程组织核心概念、先修关系、练习映射和跨章节关联。",
    recommendedNodeId: "recursion",
    metrics: [
      { label: "知识点", value: "56" },
      { label: "关系", value: "128" },
      { label: "练习映射", value: "84%" }
    ],
    nodes: [
      {
        id: "programming",
        label: "程序设计",
        type: "course",
        difficulty: "总览",
        size: 96,
        mastery: 0.91,
        summary: "课程顶层节点，汇总语法、控制结构、函数、数据结构和算法。",
        outcomes: ["理解程序执行过程", "建立章节之间的知识路径"],
        exercises: 18,
        position: { x: 0, y: 0 }
      },
      {
        id: "syntax",
        label: "基础语法",
        type: "topic",
        difficulty: "基础",
        size: 58,
        mastery: 0.82,
        summary: "变量、表达式、输入输出和基础语句构成编码起点。",
        outcomes: ["能够阅读简单程序", "能够完成基础输入输出题"],
        exercises: 12,
        position: { x: -300, y: -160 }
      },
      {
        id: "variable",
        label: "变量与类型",
        type: "concept",
        difficulty: "基础",
        size: 52,
        mastery: 0.78,
        summary: "变量存储、类型转换、作用域和命名规范。",
        prerequisites: ["基础语法"],
        outcomes: ["识别不同数据类型", "处理常见类型转换问题"],
        exercises: 10,
        position: { x: -390, y: 80 }
      },
      {
        id: "condition",
        label: "分支结构",
        type: "topic",
        difficulty: "基础",
        size: 60,
        mastery: 0.8,
        summary: "if、else、嵌套条件和布尔表达式。",
        prerequisites: ["变量与类型"],
        outcomes: ["实现条件判断", "分析多分支执行路径"],
        exercises: 14,
        position: { x: -210, y: 220 }
      },
      {
        id: "loop",
        label: "循环",
        type: "topic",
        difficulty: "基础",
        size: 64,
        mastery: 0.76,
        summary: "for、while、循环控制和常见遍历模式。",
        prerequisites: ["分支结构"],
        outcomes: ["完成计数与遍历", "避免死循环和边界错误"],
        exercises: 20,
        position: { x: 90, y: 250 }
      },
      {
        id: "function",
        label: "函数",
        type: "topic",
        difficulty: "核心",
        size: 72,
        mastery: 0.73,
        children: "function",
        summary: "函数定义、参数传递、返回值、调用栈和模块化设计。",
        prerequisites: ["变量与类型", "分支结构"],
        outcomes: ["拆分复杂问题", "复用逻辑并降低重复代码"],
        exercises: 22,
        position: { x: 260, y: 90 }
      },
      {
        id: "recursion",
        label: "递归",
        type: "core",
        difficulty: "较难",
        size: 84,
        mastery: 0.61,
        children: "recursion",
        summary: "递归通过函数自调用拆解问题，是树、回溯、分治和动态规划的基础。",
        prerequisites: ["函数", "分支结构"],
        outcomes: ["写出基线条件", "分析递归调用栈", "识别重复子问题"],
        exercises: 26,
        position: { x: 420, y: -120 }
      },
      {
        id: "array",
        label: "数组",
        type: "topic",
        difficulty: "核心",
        size: 68,
        mastery: 0.79,
        children: "array",
        summary: "线性存储、索引访问、遍历、切片和二维数组。",
        prerequisites: ["循环"],
        outcomes: ["完成序列处理", "掌握下标边界和遍历模式"],
        exercises: 24,
        position: { x: 130, y: -250 }
      },
      {
        id: "string",
        label: "字符串",
        type: "concept",
        difficulty: "核心",
        size: 56,
        mastery: 0.75,
        summary: "字符串索引、匹配、切分、拼接和常用处理函数。",
        prerequisites: ["数组", "循环"],
        outcomes: ["处理文本数据", "完成常见字符串题"],
        exercises: 16,
        position: { x: -80, y: -315 }
      },
      {
        id: "debugging",
        label: "调试",
        type: "practice",
        difficulty: "实践",
        size: 54,
        mastery: 0.7,
        summary: "断点、日志、变量观察和错误定位。",
        outcomes: ["定位运行时错误", "解释异常和边界问题"],
        exercises: 8,
        position: { x: -520, y: -80 }
      },
      {
        id: "complexity",
        label: "复杂度",
        type: "concept",
        difficulty: "进阶",
        size: 62,
        mastery: 0.58,
        summary: "时间复杂度、空间复杂度和常见复杂度量级。",
        prerequisites: ["循环", "递归"],
        outcomes: ["估算算法效率", "比较不同解法代价"],
        exercises: 18,
        position: { x: 530, y: 140 }
      },
      {
        id: "sorting",
        label: "排序",
        type: "topic",
        difficulty: "进阶",
        size: 66,
        mastery: 0.64,
        summary: "选择、插入、冒泡、归并和快速排序的思想与实现。",
        prerequisites: ["数组", "循环", "递归"],
        outcomes: ["理解排序过程", "比较排序算法复杂度"],
        exercises: 18,
        position: { x: 420, y: 300 }
      },
      {
        id: "dynamic-programming",
        label: "动态规划",
        type: "core",
        difficulty: "挑战",
        size: 76,
        mastery: 0.46,
        children: "dynamic-programming",
        summary: "通过状态定义和转移方程解决重叠子问题。",
        prerequisites: ["递归", "数组", "复杂度"],
        outcomes: ["识别状态", "写出状态转移", "优化重复计算"],
        exercises: 28,
        position: { x: 640, y: -250 }
      },
      {
        id: "graph-algorithm",
        label: "图算法",
        type: "topic",
        difficulty: "拓展",
        size: 60,
        mastery: 0.43,
        summary: "图的表示、遍历和路径搜索，连接后续数据结构课程。",
        prerequisites: ["数组", "递归"],
        outcomes: ["理解节点和边", "掌握 DFS/BFS 的基本流程"],
        exercises: 12,
        position: { x: 760, y: 40 }
      }
    ],
    edges: [
      { id: "e1", source: "programming", target: "syntax", label: "包含", type: "contains", strength: 76 },
      { id: "e2", source: "syntax", target: "variable", label: "先修", type: "prerequisite", strength: 66 },
      { id: "e3", source: "variable", target: "condition", label: "先修", type: "prerequisite", strength: 62 },
      { id: "e4", source: "condition", target: "loop", label: "控制流", type: "prerequisite", strength: 72 },
      { id: "e5", source: "variable", target: "function", label: "作用域", type: "prerequisite", strength: 70 },
      { id: "e6", source: "condition", target: "function", label: "逻辑封装", type: "related", strength: 60 },
      { id: "e7", source: "function", target: "recursion", label: "调用", type: "prerequisite", strength: 92 },
      { id: "e8", source: "loop", target: "array", label: "遍历", type: "prerequisite", strength: 85 },
      { id: "e9", source: "array", target: "string", label: "序列", type: "related", strength: 58 },
      { id: "e10", source: "loop", target: "complexity", label: "计数", type: "related", strength: 64 },
      { id: "e11", source: "recursion", target: "complexity", label: "递推分析", type: "related", strength: 78 },
      { id: "e12", source: "array", target: "sorting", label: "数据基础", type: "prerequisite", strength: 80 },
      { id: "e13", source: "recursion", target: "sorting", label: "分治", type: "related", strength: 74 },
      { id: "e14", source: "recursion", target: "dynamic-programming", label: "重叠子问题", type: "related", strength: 88 },
      { id: "e15", source: "complexity", target: "dynamic-programming", label: "优化", type: "related", strength: 72 },
      { id: "e16", source: "array", target: "dynamic-programming", label: "状态表", type: "prerequisite", strength: 76 },
      { id: "e17", source: "recursion", target: "graph-algorithm", label: "DFS", type: "related", strength: 66 },
      { id: "e18", source: "debugging", target: "function", label: "调用追踪", type: "practice", strength: 55 },
      { id: "e19", source: "debugging", target: "loop", label: "边界定位", type: "practice", strength: 50 },
      { id: "e20", source: "programming", target: "debugging", label: "实践", type: "practice", strength: 48 }
    ]
  },

  recursion: {
    id: "recursion",
    title: "递归知识点子图谱",
    subtitle: "知识点钻取视图",
    focusNode: {
      id: "recursion",
      label: "递归",
      summary: "从课程级节点进入后，父级知识点虚化为背景，子知识点成为当前操作对象。"
    },
    description:
      "递归子图谱展示基线条件、递推关系、调用栈、复杂度和外部知识关联。",
    recommendedNodeId: "base-case",
    metrics: [
      { label: "子知识点", value: "12" },
      { label: "外部连接", value: "7" },
      { label: "关联练习", value: "26" }
    ],
    nodes: [
      {
        id: "recursion-ghost",
        label: "递归",
        type: "ghost",
        difficulty: "父级",
        size: 150,
        mastery: 0.61,
        summary: "父级节点用于保持上下文，它在当前视图中虚化显示。",
        position: { x: 0, y: 0 }
      },
      {
        id: "base-case",
        label: "基线条件",
        type: "core",
        difficulty: "核心",
        size: 74,
        mastery: 0.68,
        summary: "递归停止条件，决定递归是否能够正确结束。",
        prerequisites: ["分支结构", "函数返回值"],
        outcomes: ["能为递归题写出终止条件", "能识别无限递归风险"],
        exercises: 7,
        position: { x: -210, y: -100 }
      },
      {
        id: "recursive-step",
        label: "递推关系",
        type: "core",
        difficulty: "核心",
        size: 78,
        mastery: 0.6,
        summary: "把大问题拆成同构的小问题，是递归设计的主体。",
        prerequisites: ["函数调用", "问题拆解"],
        outcomes: ["写出规模缩小的递归表达", "解释递归参数变化"],
        exercises: 8,
        position: { x: 190, y: -115 }
      },
      {
        id: "call-stack",
        label: "调用栈",
        type: "topic",
        difficulty: "核心",
        size: 68,
        mastery: 0.55,
        summary: "函数调用过程中的栈帧入栈、返回和局部变量保存。",
        prerequisites: ["函数", "变量作用域"],
        outcomes: ["画出递归调用过程", "定位栈溢出和返回值错误"],
        exercises: 6,
        position: { x: 20, y: 175 }
      },
      {
        id: "tree-recursion",
        label: "树形递归",
        type: "topic",
        difficulty: "进阶",
        size: 64,
        mastery: 0.48,
        summary: "一次调用产生多个子调用，常见于树遍历、组合搜索和斐波那契。",
        prerequisites: ["基线条件", "递推关系"],
        outcomes: ["分析分支数", "理解指数级复杂度来源"],
        exercises: 5,
        position: { x: -255, y: 145 }
      },
      {
        id: "tail-recursion",
        label: "尾递归",
        type: "concept",
        difficulty: "拓展",
        size: 50,
        mastery: 0.35,
        summary: "递归调用位于函数末尾，可引出迭代转换和优化讨论。",
        prerequisites: ["调用栈"],
        outcomes: ["识别尾递归形态", "理解递归转迭代思路"],
        exercises: 3,
        position: { x: 280, y: 110 }
      },
      {
        id: "divide-conquer",
        label: "分治",
        type: "topic",
        difficulty: "进阶",
        size: 62,
        mastery: 0.52,
        summary: "把问题拆分、递归求解、合并结果，是归并排序等算法基础。",
        prerequisites: ["递推关系", "数组"],
        outcomes: ["掌握分解和合并步骤", "理解归并排序递归结构"],
        exercises: 5,
        position: { x: 60, y: -260 }
      },
      {
        id: "recursion-complexity",
        label: "复杂度分析",
        type: "concept",
        difficulty: "进阶",
        size: 66,
        mastery: 0.44,
        summary: "通过递归树或递推式估计时间和空间复杂度。",
        prerequisites: ["调用栈", "树形递归"],
        outcomes: ["估计递归深度", "比较线性递归和树形递归代价"],
        exercises: 6,
        position: { x: -60, y: 315 }
      },
      {
        id: "recursion-practice",
        label: "递归练习",
        type: "practice",
        difficulty: "训练",
        size: 58,
        mastery: 0.5,
        summary: "阶乘、汉诺塔、斐波那契、二叉树深度和路径搜索练习。",
        outcomes: ["完成典型递归模板", "通过案例巩固抽象过程"],
        exercises: 26,
        position: { x: -395, y: -275 }
      },
      {
        id: "external-function",
        label: "函数",
        type: "external",
        difficulty: "外部",
        size: 48,
        mastery: 0.73,
        children: "function",
        summary: "递归依赖函数调用机制，可返回函数子图谱继续学习。",
        position: { x: -520, y: 35 }
      },
      {
        id: "external-loop",
        label: "循环",
        type: "external",
        difficulty: "外部",
        size: 46,
        mastery: 0.76,
        summary: "部分递归问题可以转换为循环实现。",
        position: { x: 500, y: 15 }
      },
      {
        id: "external-dp",
        label: "动态规划",
        type: "external",
        difficulty: "外部",
        size: 52,
        mastery: 0.46,
        children: "dynamic-programming",
        summary: "递归暴力解出现重复子问题后，可进一步进入动态规划。",
        position: { x: 500, y: -250 }
      },
      {
        id: "external-graph",
        label: "DFS",
        type: "external",
        difficulty: "外部",
        size: 44,
        mastery: 0.42,
        summary: "深度优先搜索是递归在图和树结构中的典型应用。",
        position: { x: 445, y: 305 }
      }
    ],
    edges: [
      { id: "r1", source: "recursion-ghost", target: "base-case", label: "包含", type: "contains", strength: 74 },
      { id: "r2", source: "recursion-ghost", target: "recursive-step", label: "包含", type: "contains", strength: 78 },
      { id: "r3", source: "base-case", target: "recursive-step", label: "共同构成", type: "related", strength: 92 },
      { id: "r4", source: "recursive-step", target: "call-stack", label: "调用过程", type: "related", strength: 82 },
      { id: "r5", source: "base-case", target: "tree-recursion", label: "终止", type: "prerequisite", strength: 72 },
      { id: "r6", source: "recursive-step", target: "tree-recursion", label: "多分支", type: "related", strength: 78 },
      { id: "r7", source: "call-stack", target: "tail-recursion", label: "栈优化", type: "related", strength: 55 },
      { id: "r8", source: "recursive-step", target: "divide-conquer", label: "拆分", type: "related", strength: 66 },
      { id: "r9", source: "tree-recursion", target: "recursion-complexity", label: "递归树", type: "related", strength: 82 },
      { id: "r10", source: "call-stack", target: "recursion-complexity", label: "空间", type: "related", strength: 70 },
      { id: "r11", source: "base-case", target: "recursion-practice", label: "练习", type: "practice", strength: 60 },
      { id: "r12", source: "recursive-step", target: "recursion-practice", label: "练习", type: "practice", strength: 64 },
      { id: "r13", source: "external-function", target: "call-stack", label: "调用", type: "external", strength: 76 },
      { id: "r14", source: "external-loop", target: "tail-recursion", label: "等价转换", type: "external", strength: 52 },
      { id: "r15", source: "external-dp", target: "tree-recursion", label: "重复子问题", type: "external", strength: 80 },
      { id: "r16", source: "external-graph", target: "tree-recursion", label: "DFS", type: "external", strength: 68 },
      { id: "r17", source: "external-dp", target: "recursion-complexity", label: "优化", type: "external", strength: 62 }
    ]
  },

  function: {
    id: "function",
    title: "函数知识点子图谱",
    subtitle: "知识点钻取视图",
    focusNode: {
      id: "function",
      label: "函数",
      summary: "函数是递归和模块化设计的先修知识。"
    },
    recommendedNodeId: "params",
    metrics: [
      { label: "子知识点", value: "8" },
      { label: "外部连接", value: "4" },
      { label: "关联练习", value: "22" }
    ],
    nodes: [
      {
        id: "function-ghost",
        label: "函数",
        type: "ghost",
        difficulty: "父级",
        size: 140,
        mastery: 0.73,
        summary: "父级函数节点。",
        position: { x: 0, y: 0 }
      },
      {
        id: "definition",
        label: "函数定义",
        type: "core",
        difficulty: "核心",
        size: 68,
        mastery: 0.77,
        summary: "函数名、参数列表、函数体和返回语句。",
        exercises: 7,
        position: { x: -190, y: -110 }
      },
      {
        id: "params",
        label: "参数传递",
        type: "core",
        difficulty: "核心",
        size: 70,
        mastery: 0.7,
        summary: "实参、形参、默认参数和可变参数。",
        exercises: 8,
        position: { x: 180, y: -110 }
      },
      {
        id: "return-value",
        label: "返回值",
        type: "topic",
        difficulty: "核心",
        size: 62,
        mastery: 0.74,
        summary: "return 语句、返回多个值和空返回。",
        exercises: 6,
        position: { x: -45, y: 160 }
      },
      {
        id: "scope",
        label: "作用域",
        type: "topic",
        difficulty: "核心",
        size: 58,
        mastery: 0.62,
        summary: "局部变量、全局变量和命名空间。",
        exercises: 5,
        position: { x: 260, y: 150 }
      },
      {
        id: "module-design",
        label: "模块化",
        type: "concept",
        difficulty: "实践",
        size: 56,
        mastery: 0.66,
        summary: "用函数拆分程序结构，提升复用和可读性。",
        exercises: 6,
        position: { x: -270, y: 145 }
      },
      {
        id: "external-recursion",
        label: "递归",
        type: "external",
        difficulty: "外部",
        size: 58,
        mastery: 0.61,
        children: "recursion",
        summary: "函数自调用形成递归。",
        position: { x: 490, y: -40 }
      },
      {
        id: "external-debugging",
        label: "调试",
        type: "external",
        difficulty: "外部",
        size: 48,
        mastery: 0.7,
        summary: "通过断点和调用栈观察函数执行。",
        position: { x: -470, y: -40 }
      }
    ],
    edges: [
      { id: "f1", source: "function-ghost", target: "definition", label: "包含", type: "contains", strength: 72 },
      { id: "f2", source: "definition", target: "params", label: "组成", type: "related", strength: 78 },
      { id: "f3", source: "params", target: "return-value", label: "调用结果", type: "related", strength: 70 },
      { id: "f4", source: "params", target: "scope", label: "变量", type: "related", strength: 64 },
      { id: "f5", source: "definition", target: "module-design", label: "封装", type: "practice", strength: 62 },
      { id: "f6", source: "external-recursion", target: "params", label: "自调用", type: "external", strength: 80 },
      { id: "f7", source: "external-debugging", target: "scope", label: "观察", type: "external", strength: 54 }
    ]
  },

  array: {
    id: "array",
    title: "数组知识点子图谱",
    subtitle: "知识点钻取视图",
    focusNode: {
      id: "array",
      label: "数组",
      summary: "数组连接循环、字符串、排序和动态规划。"
    },
    recommendedNodeId: "index",
    metrics: [
      { label: "子知识点", value: "9" },
      { label: "外部连接", value: "5" },
      { label: "关联练习", value: "24" }
    ],
    nodes: [
      {
        id: "array-ghost",
        label: "数组",
        type: "ghost",
        difficulty: "父级",
        size: 140,
        mastery: 0.79,
        summary: "父级数组节点。",
        position: { x: 0, y: 0 }
      },
      {
        id: "index",
        label: "索引",
        type: "core",
        difficulty: "核心",
        size: 66,
        mastery: 0.8,
        summary: "下标访问和边界判断。",
        exercises: 7,
        position: { x: -185, y: -115 }
      },
      {
        id: "traversal",
        label: "遍历",
        type: "core",
        difficulty: "核心",
        size: 72,
        mastery: 0.78,
        summary: "for 循环和双指针遍历。",
        exercises: 8,
        position: { x: 185, y: -120 }
      },
      {
        id: "two-dimensional",
        label: "二维数组",
        type: "topic",
        difficulty: "进阶",
        size: 58,
        mastery: 0.57,
        summary: "矩阵、行列遍历和坐标映射。",
        exercises: 5,
        position: { x: -40, y: 175 }
      },
      {
        id: "external-sorting",
        label: "排序",
        type: "external",
        difficulty: "外部",
        size: 52,
        mastery: 0.64,
        summary: "排序算法依赖数组交换和遍历。",
        position: { x: 470, y: 50 }
      },
      {
        id: "external-dp-array",
        label: "动态规划",
        type: "external",
        difficulty: "外部",
        size: 52,
        mastery: 0.46,
        children: "dynamic-programming",
        summary: "动态规划常用数组保存状态。",
        position: { x: -470, y: 45 }
      }
    ],
    edges: [
      { id: "a1", source: "array-ghost", target: "index", label: "包含", type: "contains", strength: 76 },
      { id: "a2", source: "index", target: "traversal", label: "访问", type: "prerequisite", strength: 85 },
      { id: "a3", source: "traversal", target: "two-dimensional", label: "嵌套", type: "related", strength: 68 },
      { id: "a4", source: "external-sorting", target: "traversal", label: "排序基础", type: "external", strength: 74 },
      { id: "a5", source: "external-dp-array", target: "index", label: "状态下标", type: "external", strength: 72 }
    ]
  },

  "dynamic-programming": {
    id: "dynamic-programming",
    title: "动态规划知识点子图谱",
    subtitle: "知识点钻取视图",
    focusNode: {
      id: "dynamic-programming",
      label: "动态规划",
      summary: "从递归中的重复子问题进一步抽象出状态和转移。"
    },
    recommendedNodeId: "state-definition",
    metrics: [
      { label: "子知识点", value: "10" },
      { label: "外部连接", value: "6" },
      { label: "关联练习", value: "28" }
    ],
    nodes: [
      {
        id: "dp-ghost",
        label: "动态规划",
        type: "ghost",
        difficulty: "父级",
        size: 150,
        mastery: 0.46,
        summary: "父级动态规划节点。",
        position: { x: 0, y: 0 }
      },
      {
        id: "state-definition",
        label: "状态定义",
        type: "core",
        difficulty: "核心",
        size: 74,
        mastery: 0.42,
        summary: "确定 dp 数组或状态含义。",
        exercises: 8,
        position: { x: -190, y: -110 }
      },
      {
        id: "transition",
        label: "状态转移",
        type: "core",
        difficulty: "核心",
        size: 78,
        mastery: 0.38,
        summary: "建立当前状态和前序状态之间的关系。",
        exercises: 10,
        position: { x: 190, y: -115 }
      },
      {
        id: "boundary",
        label: "边界初始化",
        type: "topic",
        difficulty: "核心",
        size: 62,
        mastery: 0.44,
        summary: "初始化起点状态，避免越界和空值。",
        exercises: 5,
        position: { x: -50, y: 170 }
      },
      {
        id: "external-recursion-dp",
        label: "递归",
        type: "external",
        difficulty: "外部",
        size: 52,
        mastery: 0.61,
        children: "recursion",
        summary: "由记忆化递归过渡到动态规划。",
        position: { x: -480, y: 20 }
      },
      {
        id: "external-array-dp",
        label: "数组",
        type: "external",
        difficulty: "外部",
        size: 52,
        mastery: 0.79,
        children: "array",
        summary: "使用数组或表格保存状态。",
        position: { x: 480, y: 20 }
      }
    ],
    edges: [
      { id: "d1", source: "dp-ghost", target: "state-definition", label: "包含", type: "contains", strength: 78 },
      { id: "d2", source: "state-definition", target: "transition", label: "推导", type: "related", strength: 92 },
      { id: "d3", source: "transition", target: "boundary", label: "初始化", type: "related", strength: 72 },
      { id: "d4", source: "external-recursion-dp", target: "transition", label: "记忆化", type: "external", strength: 75 },
      { id: "d5", source: "external-array-dp", target: "state-definition", label: "状态表", type: "external", strength: 74 }
    ]
  }
};

export function cloneGraph(graphId) {
  const graph = graphCatalog[graphId] ?? graphCatalog.root;
  return structuredClone(graph);
}

export function findNode(nodeId) {
  for (const graph of Object.values(graphCatalog)) {
    const node = graph.nodes.find((item) => item.id === nodeId);
    if (node) {
      return structuredClone({ ...node, graphId: graph.id });
    }
  }
  return null;
}

export function searchMockNodes(query) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return [];
  }

  const seen = new Set();
  const results = [];
  for (const graph of Object.values(graphCatalog)) {
    for (const node of graph.nodes) {
      if (node.type === "ghost") {
        continue;
      }

      const haystack = `${node.id} ${node.label} ${node.summary ?? ""}`.toLowerCase();
      if (haystack.includes(normalized) && !seen.has(node.label)) {
        seen.add(node.label);
        results.push({
          id: node.id,
          graphId: graph.id,
          label: node.label,
          type: node.type,
          difficulty: node.difficulty,
          summary: node.summary
        });
      }
    }
  }

  return results.slice(0, 8);
}
