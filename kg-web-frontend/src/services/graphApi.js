const API_BASE = (import.meta.env.VITE_KG_API_BASE ?? "").replace(/\/$/, "");
const MOCK_DELAY_MS = 180;
const CODE_EXAMPLES_URL = `${import.meta.env.BASE_URL}data/code_examples.json`;

let codeExamplesPromise;
let mockGraphPromise;

function createAbortError() {
  return new DOMException("请求已取消", "AbortError");
}

function throwIfAborted(signal) {
  if (signal?.aborted) {
    throw createAbortError();
  }
}

function sleep(ms, signal) {
  throwIfAborted(signal);

  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", handleAbort);
      resolve();
    }, ms);
    const handleAbort = () => {
      window.clearTimeout(timer);
      reject(createAbortError());
    };

    signal?.addEventListener("abort", handleAbort, { once: true });
  });
}

function loadMockGraph() {
  if (!mockGraphPromise) {
    mockGraphPromise = import("../data/mockGraph.js").catch((error) => {
      mockGraphPromise = undefined;
      throw error;
    });
  }
  return mockGraphPromise;
}

async function requestJson(path, { signal } = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      Accept: "application/json"
    },
    signal
  });

  if (!response.ok) {
    throw new Error(`接口请求失败: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

export function getApiMode() {
  return API_BASE ? "remote" : "mock";
}

export async function fetchApiHealth({ signal } = {}) {
  if (!API_BASE) {
    return {
      ok: true,
      mode: "mock",
      exists: {},
      counts: {},
      integrity: {}
    };
  }

  return requestJson("/api/health", { signal });
}

export async function fetchGraph(graphId = "root", { signal } = {}) {
  if (API_BASE) {
    return requestJson(`/api/graphs/${encodeURIComponent(graphId)}`, { signal });
  }

  await sleep(MOCK_DELAY_MS, signal);
  const { cloneGraph } = await loadMockGraph();
  throwIfAborted(signal);
  return cloneGraph(graphId);
}

export async function fetchNodeDetail(nodeId, { signal } = {}) {
  if (API_BASE) {
    return requestJson(`/api/nodes/${encodeURIComponent(nodeId)}`, { signal });
  }

  await sleep(MOCK_DELAY_MS, signal);
  const { findNode } = await loadMockGraph();
  throwIfAborted(signal);
  return findNode(nodeId);
}

export async function searchKnowledge(query, { limit = 8, signal } = {}) {
  const normalizedLimit = Math.max(1, Math.min(20, Number(limit) || 8));
  if (API_BASE) {
    const params = new URLSearchParams({
      q: query,
      limit: String(normalizedLimit)
    });
    return requestJson(`/api/search?${params.toString()}`, { signal });
  }

  await sleep(120, signal);
  const { searchMockNodes } = await loadMockGraph();
  throwIfAborted(signal);
  return searchMockNodes(query).slice(0, normalizedLimit);
}

export async function fetchCodeExamples() {
  if (!codeExamplesPromise) {
    codeExamplesPromise = fetch(CODE_EXAMPLES_URL, {
      headers: { Accept: "application/json" }
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Code example data request failed: ${response.status}`);
        }
        return response.json();
      })
      .then((items) => {
        const entries = Array.isArray(items) ? items : [];
        return new Map(
          entries
            .filter((item) => item?.id && typeof item.code === "string")
            .map((item) => [item.id, item])
        );
      })
      .catch((error) => {
        codeExamplesPromise = undefined;
        throw error;
      });
  }

  return codeExamplesPromise;
}
