import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  GitBranch,
  Home,
  Layers3,
  Maximize2,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Search,
  Sparkles,
  Target,
  X,
  ZoomIn,
  ZoomOut
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchApiHealth,
  fetchCodeExamples,
  fetchGraph,
  fetchNodeDetail,
  searchKnowledge
} from "./services/graphApi.js";

const GraphCanvas = lazy(() => import("./components/GraphCanvas.jsx"));

function metricClass(index) {
  return ["metric-cyan", "metric-amber", "metric-pink"][index % 3];
}

function nodeTypeLabel(type) {
  const labels = {
    KnowledgeDomain: "知识领域",
    KnowledgeUnit: "知识单元",
    KnowledgePoint: "知识点",
    CodeExample: "代码示例",
    CodeStructure: "代码结构",
    SyntaxRule: "语法规则",
    ProgrammingLanguage: "编程语言",
    course: "课程",
    topic: "主题",
    core: "核心",
    concept: "概念",
    practice: "练习",
    external: "外部关联",
    ghost: "父级",
    multiple_choice: "选择题",
    single_choice: "单选题",
    multiple_select: "多选题",
    code_reading: "代码阅读题",
    code_completion: "代码补全题",
    code_fixing: "代码改错题",
    short_programming: "编程题",
    programming: "编程题",
    fill_blank: "填空题",
    true_false: "判断题",
    judgment: "判断题",
    short_answer: "简答题",
    essay: "简答题",
    debugging: "调试题"
  };
  return labels[type] ?? type;
}

function searchResultTypeLabel(result) {
  if (result?.resultType === "question") {
    const localizedType = nodeTypeLabel(result.type);
    return result.type_label ||
      (localizedType && localizedType !== result.type ? localizedType : "练习题");
  }
  return nodeTypeLabel(result?.sourceType ?? result?.type) || "知识点";
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

function getNodeKey(node) {
  return node ? `${node.id}-${node.label}` : "";
}

function resolveOriginalQuestion(node, codeExamples) {
  if (!node) {
    return null;
  }

  const rawNode = node.raw ?? {};
  const storedExample =
    codeExamples.get(node.id) ?? codeExamples.get(rawNode.local_id);
  if (storedExample) {
    return storedExample;
  }

  // 新版图谱的示例 ID 与旧静态索引不一致时，直接回退到节点证据内容。
  const sources = (rawNode.sources ?? []).filter(
    (source) => typeof source?.content === "string" && source.content.trim()
  );
  if (!sources.length) {
    return null;
  }

  return {
    code: sources.map((source) => source.content.trim()).join("\n\n---\n\n"),
    language: rawNode.language ?? rawNode.language_scope?.[0] ?? "",
    sources
  };
}

function summarizeApiHealth(health) {
  if (!health || health.mode === "mock") {
    return null;
  }

  const missingFiles = Object.entries(health.exists ?? {})
    .filter(([, exists]) => !exists)
    .map(([name]) => name);
  if (!health.ok || missingFiles.length) {
    return {
      level: "error",
      message: missingFiles.length
        ? `API 关键数据文件缺失：${missingFiles.join("、")}`
        : "API 健康检查未通过"
    };
  }

  const integrity = health.integrity ?? {};
  const questionMapping = integrity.question_mapping ?? {};
  const issues = [];
  if (integrity.invalid_edges > 0) {
    issues.push(`${integrity.invalid_edges} 条无效关系`);
  }
  if (integrity.self_loops > 0) {
    issues.push(`${integrity.self_loops} 条自环`);
  }
  if (integrity.isolated_nodes > 0) {
    issues.push(`${integrity.isolated_nodes} 个孤立节点`);
  }
  if (questionMapping.invalid_node_ids > 0) {
    issues.push(`${questionMapping.invalid_node_ids} 个失效知识点映射`);
  }
  if (questionMapping.unresolved_links > 0) {
    issues.push(`${questionMapping.unresolved_links} 条未解析映射`);
  }
  if (questionMapping.questions_without_mapping > 0) {
    issues.push(`${questionMapping.questions_without_mapping} 道题无映射`);
  }

  return issues.length
    ? { level: "warning", message: `数据完整性检查：${issues.join("，")}` }
    : {
        level: "success",
        message: `API 健康检查通过：${health.counts?.nodes ?? 0} 个节点，${
          health.counts?.edges ?? 0
        } 条关系，${health.counts?.questions ?? 0} 道题，${
          questionMapping.links ?? 0
        } 条题目映射`
      };
}

function indexHierarchy(graph) {
  const labels = new Map(
    (graph?.nodes ?? []).map((node) => [node.id, node.label])
  );
  // part_of 在正式 JSON 中方向为“子 -> 父”，这里反向建立面包屑父级索引。
  const parents = new Map(
    (graph?.edges ?? [])
      .filter((edge) => edge.sourceType === "part_of")
      .map((edge) => [edge.target, edge.source])
  );

  return { labels, parents };
}

function buildHierarchyTrail(node, hierarchy, rootItem) {
  const path = [];
  const visited = new Set();
  let currentId = node?.id;

  while (currentId && !visited.has(currentId)) {
    visited.add(currentId);
    path.unshift({
      id: currentId,
      label: hierarchy.labels.get(currentId) ?? node.label
    });

    const parentId = hierarchy.parents.get(currentId);
    if (!parentId || parentId === "curriculum_ROOT") {
      break;
    }
    currentId = parentId;
  }

  return path.length > 1 || hierarchy.parents.has(node?.id)
    ? [rootItem, ...path]
    : null;
}

export default function App() {
  const graphRef = useRef(null);
  const searchInputRef = useRef(null);
  const hierarchyRef = useRef({ labels: new Map(), parents: new Map() });
  const codeExamplesRequestRef = useRef(null);
  const pendingSearchNodeRef = useRef(null);
  const [graphId, setGraphId] = useState("root");
  const [trail, setTrail] = useState([{ id: "root", label: "课程图谱" }]);
  const [graph, setGraph] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [nodeDetail, setNodeDetail] = useState(null);
  const [detailBackNode, setDetailBackNode] = useState(null);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [activeSearchIndex, setActiveSearchIndex] = useState(-1);
  const [searchError, setSearchError] = useState("");
  const [codeExamples, setCodeExamples] = useState(() => new Map());
  const [hasLoadedCodeExamples, setHasLoadedCodeExamples] = useState(false);
  const [isCodeExamplesLoading, setIsCodeExamplesLoading] = useState(false);
  const [codeExamplesError, setCodeExamplesError] = useState("");
  const [codeExamplesReloadKey, setCodeExamplesReloadKey] = useState(0);
  const [isGraphLoading, setIsGraphLoading] = useState(true);
  const [graphReloadKey, setGraphReloadKey] = useState(0);
  const [healthReloadKey, setHealthReloadKey] = useState(0);
  const [apiHealthAlert, setApiHealthAlert] = useState(null);
  const [isApiHealthChecking, setIsApiHealthChecking] = useState(true);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState("");
  const [isLeftRailCollapsed, setIsLeftRailCollapsed] = useState(false);
  const [isRightRailCollapsed, setIsRightRailCollapsed] = useState(false);
  const [isPracticeOpen, setIsPracticeOpen] = useState(false);
  const [practiceIndex, setPracticeIndex] = useState(0);
  const [isPracticeAnswerVisible, setIsPracticeAnswerVisible] = useState(false);
  const [standalonePracticeQuestion, setStandalonePracticeQuestion] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    setIsApiHealthChecking(true);
    fetchApiHealth({ signal: controller.signal })
      .then((health) => {
        if (active) {
          setApiHealthAlert(summarizeApiHealth(health));
        }
      })
      .catch((err) => {
        if (active && !isAbortError(err)) {
          setApiHealthAlert({
            level: "error",
            message: `API 无法连接：${err.message || "健康检查请求失败"}`
          });
        }
      })
      .finally(() => {
        if (active) {
          setIsApiHealthChecking(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [healthReloadKey]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    setIsGraphLoading(true);
    setError("");
    setGraph(null);
    if (!pendingSearchNodeRef.current) {
      setSelectedNode(null);
    }
    setNodeDetail(null);
    fetchGraph(graphId, { signal: controller.signal })
      .then((nextGraph) => {
        if (!active) {
          return;
        }
        if (graphId === "root") {
          hierarchyRef.current = indexHierarchy(nextGraph);
        }
        setGraph(nextGraph);
      })
      .catch((err) => {
        if (active && !isAbortError(err)) {
          setError(err.message || "图谱加载失败");
        }
      })
      .finally(() => {
        if (active) {
          setIsGraphLoading(false);
        }
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [graphId, graphReloadKey]);

  useEffect(() => {
    if (!graph || graph.id !== graphId) {
      return;
    }

    const pendingSearchNode = pendingSearchNodeRef.current;
    const target =
      graph.nodes.find((node) => node.id === pendingSearchNode?.id) ??
      pendingSearchNode ??
      graph.nodes.find((node) => node.id === graph.recommendedNodeId) ??
      graph.nodes.find((node) => node.type !== "ghost") ??
      graph.nodes[0];
    setSelectedNode(target ?? null);
    pendingSearchNodeRef.current = null;
  }, [graph, graphId]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    async function loadDetail() {
      if (!selectedNode) {
        setNodeDetail(null);
        return;
      }

      setNodeDetail(null);
      try {
        const detail = await fetchNodeDetail(selectedNode.id, {
          signal: controller.signal
        });
        if (active) {
          setNodeDetail(detail ?? selectedNode);
        }
      } catch (err) {
        if (active && !isAbortError(err)) {
          setNodeDetail(selectedNode);
        }
      }
    }

    loadDetail();
    return () => {
      active = false;
      controller.abort();
    };
  }, [selectedNode]);

  useEffect(() => {
    const selectedIsCodeExample =
      (selectedNode?.sourceType ?? selectedNode?.type) === "CodeExample" ||
      (nodeDetail?.id === selectedNode?.id &&
        (nodeDetail?.sourceType ?? nodeDetail?.type) === "CodeExample");
    if (
      !selectedIsCodeExample ||
      hasLoadedCodeExamples ||
      codeExamplesRequestRef.current
    ) {
      return;
    }

    setIsCodeExamplesLoading(true);
    setCodeExamplesError("");
    const request = fetchCodeExamples();
    codeExamplesRequestRef.current = request;
    request
      .then((items) => {
        setCodeExamples(items);
        setHasLoadedCodeExamples(true);
      })
      .catch(() => {
        setCodeExamples(new Map());
        setCodeExamplesError("原题数据加载失败，请重试。");
      })
      .finally(() => {
        if (codeExamplesRequestRef.current === request) {
          codeExamplesRequestRef.current = null;
        }
        setIsCodeExamplesLoading(false);
      });
  }, [
    codeExamplesReloadKey,
    hasLoadedCodeExamples,
    nodeDetail?.id,
    nodeDetail?.sourceType,
    nodeDetail?.type,
    selectedNode?.id,
    selectedNode?.sourceType,
    selectedNode?.type
  ]);

  useEffect(() => {
    setIsPracticeOpen(false);
    setPracticeIndex(0);
    setIsPracticeAnswerVisible(false);
    setStandalonePracticeQuestion(null);
  }, [selectedNode?.id]);

  useEffect(() => {
    const text = query.trim();
    if (!text) {
      setSearchResults([]);
      setActiveSearchIndex(-1);
      setSearchError("");
      setIsSearching(false);
      return undefined;
    }

    const controller = new AbortController();
    let active = true;
    setSearchResults([]);
    setActiveSearchIndex(-1);
    setSearchError("");
    setIsSearching(true);
    const timer = window.setTimeout(async () => {
      try {
        const results = await searchKnowledge(text, {
          limit: 8,
          signal: controller.signal
        });
        if (active) {
          setSearchResults(Array.isArray(results) ? results.slice(0, 8) : []);
        }
      } catch (err) {
        if (active && !isAbortError(err)) {
          setSearchResults([]);
          setSearchError(err.message || "搜索失败，请稍后重试。");
        }
      } finally {
        if (active) {
          setIsSearching(false);
        }
      }
    }, 220);

    return () => {
      active = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  useEffect(() => {
    if (activeSearchIndex < 0) {
      return;
    }
    document
      .getElementById(`knowledge-search-option-${activeSearchIndex}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [activeSearchIndex]);

  const currentSummary = useMemo(() => {
    if (!graph) {
      return [];
    }

    const countType = (sourceType) =>
      graph.nodes.filter((node) => node.sourceType === sourceType).length;
    if (graph.viewMode === "hierarchy") {
      return [
        { label: "知识领域", value: countType("KnowledgeDomain") },
        { label: "知识单元", value: countType("KnowledgeUnit") },
        { label: "知识点", value: countType("KnowledgePoint") }
      ];
    }
    return [
      {
        label: "知识节点",
        value:
          countType("KnowledgeDomain") +
          countType("KnowledgeUnit") +
          countType("KnowledgePoint")
      },
      { label: "代码示例", value: countType("CodeExample") },
      { label: "关联关系", value: graph.edges.length }
    ];
  }, [graph]);

  const enterNode = useCallback((node) => {
    if (!node?.children || node.children === graphId) {
      return;
    }

    setTrail((items) => {
      const rootItem = items[0]?.id === "root" ? items[0] : { id: "root", label: "课程图谱" };
      const hierarchyTrail = buildHierarchyTrail(node, hierarchyRef.current, rootItem);
      if (hierarchyTrail) {
        return hierarchyTrail;
      }

      const existingIndex = items.findIndex((item) => item.id === node.children);
      if (existingIndex >= 0) {
        return items.slice(0, existingIndex + 1);
      }
      return [...items, { id: node.children, label: node.label }];
    });
    setGraphId(node.children);
    pendingSearchNodeRef.current = null;
  }, [graphId]);

  const openRelatedNode = useCallback((node) => {
    if (!node) {
      return;
    }

    if (node.children && node.children !== graphId) {
      setDetailBackNode(null);
      enterNode(node);
      return;
    }

    if (node.id !== selectedNode?.id) {
      setDetailBackNode((current) => current ?? selectedNode);
    }
    setSelectedNode(node);
  }, [enterNode, graphId, selectedNode]);

  const returnToDetailNode = useCallback(() => {
    if (!detailBackNode) {
      return;
    }
    setSelectedNode(detailBackNode);
    setDetailBackNode(null);
  }, [detailBackNode]);

  const selectGraphNode = useCallback((node) => {
    setDetailBackNode(null);
    setSelectedNode(node);
  }, []);

  const goBack = useCallback(() => {
    setTrail((items) => {
      if (items.length <= 1) {
        return items;
      }
      const next = items.slice(0, -1);
      setGraphId(next[next.length - 1].id);
      return next;
    });
  }, []);

  const goTrail = useCallback((index) => {
    setTrail((items) => {
      const next = items.slice(0, index + 1);
      setGraphId(next[next.length - 1].id);
      return next;
    });
  }, []);

  const clearSearch = useCallback((refocus = false) => {
    setQuery("");
    setSearchResults([]);
    setActiveSearchIndex(-1);
    setSearchError("");
    setIsSearching(false);
    if (refocus) {
      window.requestAnimationFrame(() => searchInputRef.current?.focus());
    }
  }, []);

  const selectSearchResult = useCallback((result) => {
    if (result.resultType === "question") {
      clearSearch(false);
      setStandalonePracticeQuestion(result);
      setPracticeIndex(0);
      setIsPracticeAnswerVisible(false);
      setIsPracticeOpen(true);
      return;
    }

    // 搜索结果先切换到所属子图，待图加载完成后再选中目标节点。
    const resultGraphId = result.graphId ?? "root";
    const resultGraphLabel = hierarchyRef.current.labels.get(resultGraphId) ?? result.label;
    clearSearch(false);
    setDetailBackNode(null);
    setTrail([{ id: "root", label: "课程图谱" }]);
    if (resultGraphId !== "root") {
      setTrail([
        { id: "root", label: "课程图谱" },
        { id: resultGraphId, label: resultGraphLabel }
      ]);
    }
    pendingSearchNodeRef.current = result;
    setSelectedNode(result);
    setGraphId(resultGraphId);
  }, [clearSearch]);

  const handleSearchKeyDown = useCallback((event) => {
    if (event.isComposing || event.nativeEvent?.isComposing) {
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      clearSearch(false);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (searchResults.length) {
        setActiveSearchIndex((index) => (index + 1) % searchResults.length);
      }
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (searchResults.length) {
        setActiveSearchIndex((index) =>
          index <= 0 ? searchResults.length - 1 : index - 1
        );
      }
      return;
    }
    if (event.key === "Enter" && activeSearchIndex >= 0) {
      const result = searchResults[activeSearchIndex];
      if (result) {
        event.preventDefault();
        selectSearchResult(result);
      }
    }
  }, [activeSearchIndex, clearSearch, searchResults, selectSearchResult]);

  const selectedDisplay = nodeDetail ?? selectedNode;
  const selectedKey = getNodeKey(selectedDisplay);
  const isCodeExample =
    (selectedDisplay?.sourceType ?? selectedDisplay?.type) === "CodeExample";
  const originalQuestion = isCodeExample
    ? resolveOriginalQuestion(selectedDisplay, codeExamples)
    : null;
  const primarySource = originalQuestion?.sources?.[0];
  const nodeQuestions = selectedDisplay?.questions ?? [];
  const activePracticeQuestion =
    standalonePracticeQuestion ?? nodeQuestions[practiceIndex] ?? null;
  const practiceQuestionCount = standalonePracticeQuestion
    ? 1
    : nodeQuestions.length;
  const searchIsOpen = Boolean(query.trim());
  const activeSearchOptionId =
    activeSearchIndex >= 0 ? `knowledge-search-option-${activeSearchIndex}` : undefined;
  const isOriginalQuestionPending =
    isCodeExample &&
    !originalQuestion &&
    !hasLoadedCodeExamples &&
    !codeExamplesError;
  const shellClassName = [
    "app-shell",
    isLeftRailCollapsed ? "left-rail-collapsed" : "",
    isRightRailCollapsed ? "right-rail-collapsed" : ""
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={shellClassName}>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Network size={22} />
          </div>
          <div>
            <h1>编程知识图谱</h1>
            <p>知识驱动的智能编程辅导系统</p>
          </div>
        </div>

        <nav className="breadcrumbs" aria-label="图谱路径">
          {trail.map((item, index) => (
            <button
              key={`${item.id}-${index}`}
              className={index === trail.length - 1 ? "crumb is-active" : "crumb"}
              onClick={() => goTrail(index)}
              type="button"
            >
              {index === 0 ? <Home size={14} /> : <GitBranch size={14} />}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        {apiHealthAlert ? (
          <div
            className={`api-health-alert is-${apiHealthAlert.level}`}
            role="alert"
            title={apiHealthAlert.message}
          >
            <AlertTriangle aria-hidden="true" size={16} />
            <span>{apiHealthAlert.message}</span>
            <button
              aria-label="重新检查 API"
              disabled={isApiHealthChecking}
              onClick={() => setHealthReloadKey((key) => key + 1)}
              title="重新检查 API"
              type="button"
            >
              <RefreshCw
                aria-hidden="true"
                className={isApiHealthChecking ? "is-spinning" : ""}
                size={15}
              />
            </button>
          </div>
        ) : null}

      </header>

      <main className="workspace">
        <section className="canvas-header">
          <div>
            <p>{graph?.subtitle ?? "加载中"}</p>
            <h2>{graph?.title ?? "图谱加载中"}</h2>
          </div>
          <div aria-label="图谱工具" className="canvas-actions" role="toolbar">
            <button
              aria-controls="knowledge-left-rail"
              aria-expanded={!isLeftRailCollapsed}
              aria-label={isLeftRailCollapsed ? "展开左侧栏" : "收起左侧栏"}
              className="icon-button"
              onClick={() => setIsLeftRailCollapsed((collapsed) => !collapsed)}
              title={isLeftRailCollapsed ? "展开左侧栏" : "收起左侧栏"}
              type="button"
            >
              {isLeftRailCollapsed ? (
                <PanelLeftOpen aria-hidden="true" size={18} />
              ) : (
                <PanelLeftClose aria-hidden="true" size={18} />
              )}
            </button>
            <button
              aria-label="返回上级"
              className="icon-button"
              title="返回上级"
              onClick={goBack}
              disabled={trail.length <= 1}
              type="button"
            >
              <ArrowLeft size={18} />
            </button>
            <button
              aria-label="放大图谱"
              className="icon-button"
              title="放大"
              onClick={() => graphRef.current?.zoomIn()}
              type="button"
            >
              <ZoomIn size={18} />
            </button>
            <button
              aria-label="缩小图谱"
              className="icon-button"
              title="缩小"
              onClick={() => graphRef.current?.zoomOut()}
              type="button"
            >
              <ZoomOut size={18} />
            </button>
            <button
              aria-label="适应视图"
              className="icon-button"
              title="适应视图"
              onClick={() => graphRef.current?.fit()}
              type="button"
            >
              <Maximize2 size={18} />
            </button>
            <button
              aria-controls="knowledge-right-rail"
              aria-expanded={!isRightRailCollapsed}
              aria-label={isRightRailCollapsed ? "展开右侧栏" : "收起右侧栏"}
              className="icon-button"
              onClick={() => setIsRightRailCollapsed((collapsed) => !collapsed)}
              title={isRightRailCollapsed ? "展开右侧栏" : "收起右侧栏"}
              type="button"
            >
              {isRightRailCollapsed ? (
                <PanelRightOpen aria-hidden="true" size={18} />
              ) : (
                <PanelRightClose aria-hidden="true" size={18} />
              )}
            </button>
          </div>
        </section>

        <section
          aria-busy={isGraphLoading}
          aria-label="知识图谱画布"
          className="graph-wrap"
        >
          {isGraphLoading ? (
            <div aria-live="polite" className="state-message" role="status">
              图谱加载中…
            </div>
          ) : error ? (
            <div className="state-message" role="alert">
              <div className="state-message-content">
                <p>{error}</p>
                <button
                  className="secondary-action"
                  onClick={() => setGraphReloadKey((key) => key + 1)}
                  type="button"
                >
                  重新加载
                </button>
              </div>
            </div>
          ) : graph ? (
            <Suspense
              fallback={
                <div aria-live="polite" className="state-message" role="status">
                  图谱组件加载中...
                </div>
              }
            >
              <GraphCanvas
                ref={graphRef}
                graph={graph}
                selectedNodeId={selectedNode?.id}
                onNodeSelect={selectGraphNode}
                onNodeEnter={enterNode}
              />
            </Suspense>
          ) : (
            <div className="state-message" role="status">
              暂无图谱数据
            </div>
          )}
        </section>
      </main>

      <aside
        className="left-rail"
        hidden={isLeftRailCollapsed}
        id="knowledge-left-rail"
      >
        <section className="panel search-panel">
          <label className="panel-title" htmlFor="knowledge-search">
            <Search aria-hidden="true" size={17} />
            <span>搜索知识点</span>
          </label>
          <div className="search-box">
            <Search aria-hidden="true" size={17} />
            <input
              aria-activedescendant={activeSearchOptionId}
              aria-autocomplete="list"
              aria-controls="knowledge-search-results"
              aria-expanded={searchIsOpen}
              aria-haspopup="listbox"
              autoComplete="off"
              id="knowledge-search"
              onKeyDown={handleSearchKeyDown}
              ref={searchInputRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入名称或关键词"
              role="combobox"
            />
            {query ? (
              <button
                aria-label="清除搜索"
                className="practice-close-button search-clear-button"
                onClick={() => clearSearch(true)}
                title="清除搜索"
                type="button"
              >
                <X aria-hidden="true" size={16} />
              </button>
            ) : null}
          </div>
          {isSearching ? (
            <div aria-live="polite" className="result-empty" role="status">
              检索中…
            </div>
          ) : null}
          {searchError ? (
            <div className="result-empty search-error" role="alert">
              {searchError}
            </div>
          ) : null}
          {!isSearching && !searchError && searchIsOpen && searchResults.length === 0 ? (
            <div aria-live="polite" className="result-empty" role="status">
              暂无匹配
            </div>
          ) : null}
          {!isSearching && !searchError && searchResults.length > 0 ? (
            <div aria-live="polite" className="result-empty result-count" role="status">
              找到 {searchResults.length} 项结果
            </div>
          ) : null}
          <div
            aria-busy={isSearching}
            aria-label="知识搜索结果"
            className="result-list"
            id="knowledge-search-results"
            role="listbox"
          >
            {searchResults.map((result, index) => (
              <button
                aria-selected={activeSearchIndex === index}
                className="result-item"
                id={`knowledge-search-option-${index}`}
                key={`${result.graphId ?? "root"}-${result.id}`}
                onClick={() => selectSearchResult(result)}
                onFocus={() => setActiveSearchIndex(index)}
                onMouseEnter={() => setActiveSearchIndex(index)}
                role="option"
                tabIndex={-1}
                type="button"
              >
                <span>{result.label}</span>
                <small>{searchResultTypeLabel(result)}</small>
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">
            <Layers3 size={17} />
            <span>图谱概览</span>
          </div>
          <div className="metric-grid">
            {(graph?.metrics ?? []).map((metric, index) => (
              <div className={`metric ${metricClass(index)}`} key={metric.label}>
                <strong>{metric.value}</strong>
                <span>{metric.label}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-title">
            <Target size={17} />
            <span>当前视图</span>
          </div>
          <div className="summary-list">
            {currentSummary.map((item) => (
              <div className="summary-row" key={item.label}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
        </section>
      </aside>

      <aside
        className="detail-rail"
        hidden={isRightRailCollapsed}
        id="knowledge-right-rail"
      >
        <section className="panel detail-panel" key={selectedKey}>
          {detailBackNode && selectedDisplay?.id !== detailBackNode.id ? (
            <button
              className="detail-return-button"
              onClick={returnToDetailNode}
              type="button"
            >
              <ArrowLeft size={16} />
              <span>返回 {detailBackNode.label}</span>
            </button>
          ) : null}
          <div className="detail-heading">
            <div>
              <span className="type-tag">
                {nodeTypeLabel(selectedDisplay?.sourceType ?? selectedDisplay?.type)}
              </span>
              <h3>{selectedDisplay?.label ?? "未选择知识点"}</h3>
            </div>
            <Sparkles size={20} />
          </div>

          <p className="detail-summary">
            {selectedDisplay?.summary || "选择图谱节点后查看知识点说明。"}
          </p>

          {isCodeExample ? (
            <div className="detail-block original-question-block">
              <div className="original-question-heading">
                <h4>原题</h4>
                {originalQuestion?.language ? (
                  <span>{originalQuestion.language}</span>
                ) : null}
              </div>
              <pre className="original-question-content">
                {isCodeExamplesLoading || isOriginalQuestionPending
                  ? "原题加载中..."
                  : originalQuestion?.code ||
                    codeExamplesError ||
                    "未找到该代码示例的原题内容。"}
              </pre>
              {codeExamplesError && !originalQuestion ? (
                <button
                  className="secondary-action"
                  onClick={() => {
                    setCodeExamplesError("");
                    setCodeExamplesReloadKey((key) => key + 1);
                  }}
                  type="button"
                >
                  重试加载原题
                </button>
              ) : null}
              {primarySource ? (
                <p className="original-question-source">
                  {primarySource.source_file}
                  {primarySource.page ? ` · P${primarySource.page}` : ""}
                </p>
              ) : null}
            </div>
          ) : null}

          <div className="detail-stats">
            <div>
              <span>置信度</span>
              <strong>
                {Number.isFinite(selectedDisplay?.confidence)
                  ? `${Math.round(selectedDisplay.confidence * 100)}%`
                  : "--"}
              </strong>
            </div>
            <div>
              <span>关联</span>
              <strong>{selectedDisplay?.relationCount ?? selectedDisplay?.relations?.length ?? 0}</strong>
            </div>
            <div>
              <span>来源</span>
              <strong>{selectedDisplay?.sourceCount ?? 0}</strong>
            </div>
          </div>

          <div className="progress-track" aria-hidden="true">
            <span
              style={{
                width: `${Math.round((selectedDisplay?.confidence ?? 0) * 100)}%`
              }}
            />
          </div>

          <div className="detail-block">
            <h4>别名</h4>
            <div className="tag-list">
              {(selectedDisplay?.aliases?.length
                ? selectedDisplay.aliases
                : ["暂无别名"]
              ).map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          </div>

          <div className="detail-block">
            <h4>关联节点</h4>
            <div className="tag-list">
              {(selectedDisplay?.neighbors?.length
                ? selectedDisplay.neighbors.slice(0, 8).map((item) => (
                    <button
                      className="related-node-button"
                      key={item.id}
                      onClick={() => openRelatedNode(item)}
                      title={`查看 ${item.label}`}
                      type="button"
                    >
                      <GitBranch size={14} />
                      <span>{item.label}</span>
                    </button>
                  ))
                : <span>暂无关联节点</span>
              )}
            </div>
          </div>

          <div className="detail-actions">
            <button
              className="primary-action"
              onClick={() => enterNode(selectedDisplay)}
              disabled={
                !selectedDisplay?.children || selectedDisplay.children === graphId
              }
              type="button"
            >
              <GitBranch size={17} />
              <span>进入子图</span>
            </button>
            <button
              className="secondary-action"
              disabled={nodeQuestions.length === 0}
              onClick={() => {
                setStandalonePracticeQuestion(null);
                setPracticeIndex(0);
                setIsPracticeAnswerVisible(false);
                setIsPracticeOpen(true);
              }}
              type="button"
            >
              <BookOpen size={17} />
              <span>
                {nodeQuestions.length
                  ? `${nodeQuestions.length} 道练习`
                  : "暂无练习"}
              </span>
            </button>
          </div>
        </section>
      </aside>

      {isPracticeOpen && activePracticeQuestion ? (
        <div className="practice-overlay" role="presentation">
          <section
            aria-label="知识点练习"
            aria-modal="true"
            className="practice-dialog"
            role="dialog"
          >
            <div className="practice-dialog-header">
              <div>
                <span className="type-tag">
                  {activePracticeQuestion.type_label || "练习题"}
                </span>
                <h3>
                  {standalonePracticeQuestion
                    ? "搜索题目"
                    : selectedDisplay?.label} · {practiceIndex + 1} / {practiceQuestionCount}
                </h3>
              </div>
              <button
                aria-label="关闭习题"
                className="practice-close-button"
                onClick={() => {
                  setIsPracticeOpen(false);
                  setStandalonePracticeQuestion(null);
                }}
                type="button"
              >
                <X size={20} />
              </button>
            </div>

            <p className="practice-stem">{activePracticeQuestion.stem}</p>
            {activePracticeQuestion.code ? (
              <pre className="practice-code">{activePracticeQuestion.code}</pre>
            ) : null}
            {activePracticeQuestion.options?.length ? (
              <ol className="practice-options">
                {activePracticeQuestion.options.map((option) => (
                  <li key={option}>{option}</li>
                ))}
              </ol>
            ) : null}

            {isPracticeAnswerVisible ? (
              <div className="practice-answer">
                <strong>答案：{activePracticeQuestion.answer}</strong>
                {activePracticeQuestion.analysis ? (
                  <p>{activePracticeQuestion.analysis}</p>
                ) : null}
              </div>
            ) : null}

            <div className="practice-actions">
              <button
                className="secondary-action"
                onClick={() => setIsPracticeAnswerVisible((visible) => !visible)}
                type="button"
              >
                {isPracticeAnswerVisible ? "隐藏答案" : "查看答案"}
              </button>
              <button
                className="secondary-action"
                disabled={Boolean(standalonePracticeQuestion) || practiceIndex === 0}
                onClick={() => {
                  setPracticeIndex((index) => Math.max(0, index - 1));
                  setIsPracticeAnswerVisible(false);
                }}
                type="button"
              >
                上一题
              </button>
              <button
                className="primary-action"
                disabled={
                  Boolean(standalonePracticeQuestion) ||
                  practiceIndex >= practiceQuestionCount - 1
                }
                onClick={() => {
                  setPracticeIndex((index) =>
                    Math.min(practiceQuestionCount - 1, index + 1)
                  );
                  setIsPracticeAnswerVisible(false);
                }}
                type="button"
              >
                下一题
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
