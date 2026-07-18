import cytoscape from "cytoscape";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

const NODE_PALETTE = {
  course: { core: "#f3c15f", glow: "#fff0bc", nucleus: "#ffe8a3" },
  core: { core: "#f15bbb", glow: "#ffd8ef", nucleus: "#ffffff" },
  topic: { core: "#57d7ff", glow: "#dff8ff", nucleus: "#ffffff" },
  concept: { core: "#47d18c", glow: "#caffdf", nucleus: "#ffffff" },
  practice: { core: "#ff8f5e", glow: "#ffd6c4", nucleus: "#ffffff" },
  external: { core: "#8993a4", glow: "#d5dae5", nucleus: "#eef2f8" },
  ghost: { core: "#dbe7ff", glow: "#eef6ff", nucleus: "#ffffff" }
};

const LAYER_PALETTE = {
  1: { core: "#ff5375", glow: "#ffc45d", nucleus: "#fff0c4" },
  2: { core: "#ff8b63", glow: "#ffd17a", nucleus: "#fff2cf" },
  3: { core: "#a66bff", glow: "#f29bff", nucleus: "#fbe7ff" }
};

const COURSE_CONTEXT_LABELS = {
  course_python: "Python",
  course_java: "Java",
  course_cpp: "C++",
  course_data_structures: "数据结构",
  course_uml: "UML"
};

function paletteFor(node) {
  return LAYER_PALETTE[node.layer] ?? NODE_PALETTE[node.type] ?? NODE_PALETTE.topic;
}

function hashString(value) {
  return [...value].reduce((hash, char) => hash + char.charCodeAt(0), 0);
}

function dendriteOffsets(node) {
  const seed = hashString(node.id);
  const count = node.type === "external" ? 3 : 4;
  const radius = Math.max(40, (node.size ?? 56) * 0.72);

  return Array.from({ length: count }, (_, index) => {
    const angle = ((seed * 37 + index * 93) % 360) * (Math.PI / 180);
    const stretch = radius * (0.78 + ((seed + index * 17) % 22) / 100);
    return {
      dx: Math.cos(angle) * stretch,
      dy: Math.sin(angle) * stretch,
      size: 4 + ((seed + index * 5) % 4)
    };
  });
}

function edgeCurveClass(edge) {
  const index = hashString(edge.id ?? `${edge.source}-${edge.target}`) % 4;
  return ["curve-a", "curve-b", "curve-c", "curve-d"][index];
}

function graphNodeLabel(node, labelCounts) {
  const label = String(node.label ?? "").trim();
  if (!label || (labelCounts.get(label) ?? 0) < 2) {
    return label;
  }

  const courseLabel = COURSE_CONTEXT_LABELS[node.raw?.course_id];
  return courseLabel ? `${courseLabel} · ${label}` : label;
}

function isCodeExampleNode(node) {
  return node.sourceType === "CodeExample" || node.raw?.type === "CodeExample";
}

function shouldRenderCodeExample(node, graph, graphNodesById) {
  const connectedNodeIds = new Set();

  graph.edges.forEach((edge) => {
    if (edge.source !== node.id && edge.target !== node.id) {
      return;
    }

    const otherNodeId = edge.source === node.id ? edge.target : edge.source;
    const otherNode = graphNodesById.get(otherNodeId);
    if (otherNode && !isCodeExampleNode(otherNode)) {
      connectedNodeIds.add(otherNodeId);
    }
  });

  // 仅保留承担两个以上知识节点桥接作用的示例，普通示例只在详情栏展示。
  return connectedNodeIds.size >= 2;
}

function toElements(graph) {
  // 神经元末梢是装饰元素，不参与业务关系、搜索或自动布局计算。
  const decorativeNodes = [];
  const decorativeEdges = [];
  const graphNodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const visibleGraphNodes = graph.nodes.filter(
    (node) => !isCodeExampleNode(node) || shouldRenderCodeExample(node, graph, graphNodesById)
  );
  const nodeIds = new Set(visibleGraphNodes.map((node) => node.id));
  const labelCounts = new Map();
  visibleGraphNodes.forEach((node) => {
    const label = String(node.label ?? "").trim();
    if (label) {
      labelCounts.set(label, (labelCounts.get(label) ?? 0) + 1);
    }
  });

  const nodes = visibleGraphNodes.map((node) => ({
    data: {
      ...node,
      graphLabel: graphNodeLabel(node, labelCounts),
      size: node.size ?? 56,
      mastery: node.mastery ?? 0.5,
      graphX: node.position?.x,
      graphY: node.position?.y,
      coreColor: paletteFor(node).core,
      glowColor: paletteFor(node).glow
    },
    position: node.position,
    classes: [
      node.type === "ghost" ? "parent-ghost" : "neuron",
      node.type,
      node.layer ? `layer-${node.layer}` : "",
      node.children ? "expandable" : "",
      node.systemNode ? "graph-hub" : "",
      node.type === "external" ? "external-node" : ""
    ]
      .filter(Boolean)
      .join(" ")
  }));

  visibleGraphNodes.forEach((node) => {
    if (node.type === "ghost") {
      return;
    }

    const palette = paletteFor(node);
    const position = node.position ?? { x: 0, y: 0 };

    dendriteOffsets(node).forEach((offset, index) => {
      const tipId = `${node.id}__d${index}`;
      decorativeNodes.push({
        data: {
          id: tipId,
          label: "",
          decorative: true,
          ownerId: node.id,
          dx: offset.dx,
          dy: offset.dy,
          size: offset.size,
          glowColor: palette.glow,
          graphX: position.x + offset.dx,
          graphY: position.y + offset.dy
        },
        position: {
          x: position.x + offset.dx,
          y: position.y + offset.dy
        },
        selectable: false,
        grabbable: false,
        classes: "dendrite-tip"
      });
      decorativeEdges.push({
        data: {
          id: `${node.id}__twig${index}`,
          source: node.id,
          target: tipId,
          label: "",
          decorative: true,
          glowColor: palette.glow,
          strength: 46
        },
        selectable: false,
        classes: "dendrite-edge"
      });
    });
  });

  const edges = graph.edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge) => ({
      data: {
        ...edge,
        strength: edge.strength ?? 60
      },
      classes: [
        edge.type,
        edge.courseOverview ? "course-overview-edge" : "",
        edgeCurveClass(edge),
        edge.type === "external" ? "external-edge" : ""
      ]
        .filter(Boolean)
        .join(" ")
    }));

  return [...decorativeNodes, ...nodes, ...decorativeEdges, ...edges];
}

const stylesheet = [
  {
    selector: "node",
    style: {
      width: "mapData(size, 40, 150, 34, 146)",
      height: "mapData(size, 40, 150, 34, 146)",
      shape: "ellipse",
      "background-color": "#57d7ff",
      "background-opacity": 0.86,
      "border-color": "#dff8ff",
      "border-width": 1.6,
      "font-size": 12,
      "font-weight": 700,
      color: "#eafbff",
      label: "data(graphLabel)",
      "text-wrap": "wrap",
      "text-max-width": 92,
      "min-zoomed-font-size": 7,
      "text-halign": "center",
      "text-valign": "center",
      "text-outline-color": "#07080b",
      "text-outline-opacity": 0.78,
      "text-outline-width": 2,
      "overlay-opacity": 0
    }
  },
  {
    selector: "node.neuron",
    style: {
      "border-opacity": 0.82,
      "z-index": 6
    }
  },
  {
    selector: "node.neuron-aura",
    style: {
      width: "data(size)",
      height: "data(size)",
      label: "",
      "background-color": "data(glowColor)",
      "background-opacity": 0,
      "border-color": "data(glowColor)",
      "border-width": 1,
      "border-opacity": 0,
      "overlay-opacity": 0,
      "z-index": 0
    }
  },
  {
    selector: "node.dendrite-tip",
    style: {
      width: "data(size)",
      height: "data(size)",
      label: "",
      "background-color": "data(glowColor)",
      "background-opacity": 0.54,
      "border-color": "data(glowColor)",
      "border-width": 1,
      "border-opacity": 0.44,
      "overlay-opacity": 0,
      "z-index": 1
    }
  },
  {
    selector: "node[type = 'course']",
    style: {
      "background-color": "#f3c15f",
      "border-color": "#ffe4a7"
    }
  },
  {
    selector: "node[type = 'core']",
    style: {
      "background-color": "#f15bbb",
      "border-color": "#ffd8ef"
    }
  },
  {
    selector: "node[type = 'topic']",
    style: {
      "background-color": "#57d7ff",
      "border-color": "#dff8ff"
    }
  },
  {
    selector: "node[type = 'concept']",
    style: {
      "background-color": "#47d18c",
      "border-color": "#caffdf"
    }
  },
  {
    selector: "node[type = 'practice']",
    style: {
      "background-color": "#ff8f5e",
      "border-color": "#ffd6c4"
    }
  },
  {
    selector: "node[type = 'external']",
    style: {
      "background-color": "#8993a4",
      "background-opacity": 0.34,
      "border-color": "#d5dae5",
      "border-style": "dashed",
      color: "#d8dde7"
    }
  },
  {
    selector: "node[type = 'ghost']",
    style: {
      "background-color": "#dbe7ff",
      "background-opacity": 0.18,
      "border-color": "#dbe7ff",
      "border-opacity": 0.3,
      "border-width": 12,
      color: "#f5f7ff",
      opacity: 0.48,
      "text-opacity": 0.56,
      "font-size": 20,
      "text-outline-opacity": 0.54
    }
  },
  {
    selector: "node.layer-1",
    style: {
      "background-color": "#ff5375",
      "border-color": "#ffd87a",
      "border-width": 4.8,
      "font-size": 16,
      "text-max-width": 124
    }
  },
  {
    selector: "node.layer-2",
    style: {
      "background-color": "#ff8b63",
      "border-color": "#ffd89a",
      "border-width": 3.4,
      "font-size": 12,
      "text-max-width": 102
    }
  },
  {
    selector: "node.layer-3",
    style: {
      "background-color": "#a66bff",
      "border-color": "#f1b6ff",
      "border-width": 2.2,
      "font-size": 10,
      "text-max-width": 82
    }
  },
  {
    selector: "node.graph-hub",
    style: {
      "background-color": "#ff5375",
      "border-color": "#ffd87a",
      "border-width": 4.8,
      "font-size": 17,
      "text-max-width": 132,
      "z-index": 9
    }
  },
  {
    selector: "node.parent-ghost",
    style: {
      "border-opacity": 0.28
    }
  },
  {
    selector: "node.expandable",
    style: {
      "border-width": 3,
      "border-color": "#fff4bd"
    }
  },
  {
    selector: "node.is-selected",
    style: {
      "border-width": 5,
      "border-color": "#fff4bd",
      "z-index": 12
    }
  },
  {
    selector: "node.is-hovered",
    style: {
      "border-width": 5,
      "border-opacity": 0.95,
      "background-opacity": 0.98,
      "z-index": 10
    }
  },
  {
    selector: "edge",
    style: {
      width: "mapData(strength, 45, 95, 1.2, 4.6)",
      "curve-style": "straight",
      "line-color": "#5fcbe8",
      "line-opacity": 0.54,
      "target-arrow-shape": "triangle",
      "target-arrow-color": "#5fcbe8",
      "arrow-scale": 0.8,
      label: "data(label)",
      "font-size": 9,
      color: "#b8c6d8",
      "text-background-color": "#0b0d12",
      "text-background-opacity": 0.76,
      "text-background-padding": 3,
      "text-rotation": "autorotate",
      "min-zoomed-font-size": 7
    }
  },
  {
    selector: "edge.curve-a",
    style: {
      "control-point-distances": 72
    }
  },
  {
    selector: "edge.curve-b",
    style: {
      "control-point-distances": -72
    }
  },
  {
    selector: "edge.curve-c",
    style: {
      "control-point-distances": 112
    }
  },
  {
    selector: "edge.curve-d",
    style: {
      "control-point-distances": -112
    }
  },
  {
    selector: "edge.dendrite-edge",
    style: {
      width: 1.2,
      "curve-style": "bezier",
      "line-color": "data(glowColor)",
      "line-opacity": 0.34,
      "target-arrow-shape": "none",
      label: "",
      "z-index": 0
    }
  },
  {
    selector: "edge[type = 'prerequisite']",
    style: {
      "line-color": "#f3c15f",
      "target-arrow-color": "#f3c15f"
    }
  },
  {
    selector: "edge[type = 'practice']",
    style: {
      "line-color": "#ff8f5e",
      "target-arrow-color": "#ff8f5e",
      "line-style": "dotted"
    }
  },
  {
    selector: "edge[type = 'external']",
    style: {
      "line-color": "#a7afbd",
      "target-arrow-color": "#a7afbd",
      "line-style": "dashed",
      "line-opacity": 0.36
    }
  },
  {
    selector: "edge[type = 'contains']",
    style: {
      "line-color": "#57d7ff",
      "target-arrow-color": "#57d7ff",
      "line-opacity": 0.3
    }
  },
  {
    selector: "edge.course-overview-edge",
    style: {
      width: 1.8,
      "curve-style": "straight",
      "line-color": "#ffb34f",
      "target-arrow-color": "#ffb34f",
      "line-style": "dashed",
      "line-opacity": 0.82,
      "target-arrow-shape": "triangle"
    }
  }
];

const GraphCanvas = forwardRef(function GraphCanvas(
  { graph, selectedNodeId, onNodeSelect, onNodeEnter },
  ref
) {
  const containerRef = useRef(null);
  const cyRef = useRef(null);

  useImperativeHandle(ref, () => ({
    fit() {
      cyRef.current?.fit(undefined, 56);
    },
    zoomIn() {
      const cy = cyRef.current;
      if (!cy) return;
      cy.zoom({
        level: Math.min(cy.maxZoom(), cy.zoom() * 1.18),
        renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 }
      });
    },
    zoomOut() {
      const cy = cyRef.current;
      if (!cy) return;
      cy.zoom({
        level: Math.max(cy.minZoom(), cy.zoom() / 1.18),
        renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 }
      });
    }
  }));

  useEffect(() => {
    if (!containerRef.current) {
      return undefined;
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements: toElements(graph),
      style: stylesheet,
      minZoom: 0.12,
      maxZoom: 2.25,
      wheelSensitivity: 0.18,
      selectionType: "single",
      boxSelectionEnabled: false,
      autoungrabify: false
    });

    cyRef.current = cy;
    cy.nodes().forEach((node) => {
      const graphX = node.data("graphX");
      const graphY = node.data("graphY");
      if (Number.isFinite(graphX) && Number.isFinite(graphY)) {
        node.position({ x: graphX, y: graphY });
      }
    });
    let fitTimer = null;
    let lastTap = { id: "", at: 0 };
    let lastDrag = { id: "", at: 0 };
    let lastEnter = { id: "", at: 0 };
    let draggingNodeId = "";
    const hoverPulseTimers = new Map();
    let activeLayout = null;
    let disposed = false;

    const usePresetLayout =
      cy
        .nodes()
        .filter(
          (node) =>
            !node.data("decorative") &&
            Number.isFinite(node.data("graphX")) &&
            Number.isFinite(node.data("graphY"))
        ).length > 0;
    // 关系名越长适当增加节点间距，但在密集大图中限制额外扩张。
    const longestRelationLabel = Math.max(
      0,
      ...graph.edges.map((edge) => Array.from(String(edge.label ?? "")).length)
    );
    const baseRelationSpacing = Math.min(90, Math.max(0, longestRelationLabel - 4) * 14);
    const relationDensityScale = Math.min(1, Math.max(0.14, 16 / Math.max(1, graph.nodes.length)));
    const extraRelationSpacing = Math.round(baseRelationSpacing * relationDensityScale);
    const relationSpacingFactor = 1 + extraRelationSpacing / 100;
    const layout =
      graph.layout === "radial"
        ? {
            name: "concentric",
            fit: false,
            padding: 88,
            avoidOverlap: true,
            minNodeSpacing: 30 + extraRelationSpacing,
            spacingFactor: 1 + extraRelationSpacing / 160,
            animate: false,
            concentric: (node) => 4 - Math.min(3, Number(node.data("layer")) || 3),
            levelWidth: () => 1
          }
        : graph.layout === "hierarchy"
          ? {
              name: "breadthfirst",
              directed: true,
              fit: false,
              padding: 72,
              spacingFactor: 1.35 * relationSpacingFactor,
              avoidOverlap: true,
              animate: false
            }
          : {
              name: "cose",
              fit: false,
              padding: 72,
              animate: false,
              nodeRepulsion: 11000,
              idealEdgeLength: 138 + extraRelationSpacing
            };

    const syncDecorations = (node) => {
      if (disposed || cy.destroyed()) {
        return;
      }
      if (node.data("decorative")) {
        return;
      }

      const position = node.position();
      for (let index = 0; index < 4; index += 1) {
        const tip = cy.$id(`${node.id()}__d${index}`);
        if (tip.length) {
          tip.position({
            x: position.x + (tip.data("dx") ?? 0),
            y: position.y + (tip.data("dy") ?? 0)
          });
        }
      }
    };

    const syncAllDecorations = () => {
      cy.nodes(".neuron, .parent-ghost").forEach(syncDecorations);
    };

    const fitPadding = () => {
      const nodeCount = cy.nodes(".neuron, .parent-ghost").length;
      if (nodeCount > 80) {
        return 28;
      }
      if (nodeCount > 40) {
        return 46;
      }
      return 72;
    };

    const stopHoverPulse = (node) => {
      const timer = hoverPulseTimers.get(node.id());
      if (timer) {
        window.clearInterval(timer);
        hoverPulseTimers.delete(node.id());
      }
      node.stop(true, false);
      node.removeStyle("border-width background-opacity");
    };

    const startHoverPulse = (node) => {
      if (draggingNodeId || hoverPulseTimers.has(node.id())) {
        return;
      }

      const pulse = () => {
        if (disposed || cy.destroyed() || !node.hasClass("is-hovered")) {
          return;
        }

        node
          .animate(
            { style: { "border-width": 6.4, "background-opacity": 1 } },
            { duration: 380, easing: "ease-in-out" }
          )
          .animate(
            { style: { "border-width": 4.6, "background-opacity": 0.94 } },
            { duration: 560, easing: "ease-in-out" }
          );
      };

      pulse();
      hoverPulseTimers.set(node.id(), window.setInterval(pulse, 1000));
    };

    const enterExactNode = (node) => {
      if (node.data("decorative") || node.data("systemNode") || !node.data("children")) {
        return;
      }

      const now = Date.now();
      const nodeId = node.id();
      const wasJustDragged =
        lastDrag.id === nodeId && now - lastDrag.at < 260;
      const isDuplicateEvent =
        lastEnter.id === nodeId && now - lastEnter.at < 600;
      if (wasJustDragged || isDuplicateEvent) {
        return;
      }

      lastEnter = { id: nodeId, at: now };
      onNodeSelect?.(node.data());
      onNodeEnter?.(node.data());
    };

    const fitGraph = () => {
      fitTimer = window.setTimeout(() => {
        if (cy.destroyed()) {
          return;
        }
        if (usePresetLayout) {
          cy.nodes().forEach((node) => {
            const graphX = node.data("graphX");
            const graphY = node.data("graphY");
            if (Number.isFinite(graphX) && Number.isFinite(graphY)) {
              node.position({ x: graphX, y: graphY });
            }
          });
        }
        syncAllDecorations();
        cy.resize();
        cy.fit(cy.nodes(".neuron, .parent-ghost"), fitPadding());
      }, 40);
    };

    cy.ready(() => {
      if (!usePresetLayout) {
        const layoutElements = cy.elements().filter((element) => !element.data("decorative"));
        activeLayout = layoutElements.layout(layout);
        activeLayout.one("layoutstop", () => {
          syncAllDecorations();
          fitGraph();
        });
        activeLayout.run();
      } else {
        fitGraph();
      }
      cy.nodes().forEach((node, index) => {
        if (node.data("decorative")) {
          return;
        }
        node.delay(index * 18).animate(
          {
            style: {
              "background-opacity": node.hasClass("external-node") ? 0.42 : 0.92
            }
          },
          { duration: 450 }
        );
      });
    });

    cy.on("tap", "node", (event) => {
      const node = event.target;
      if (node.data("decorative") || node.data("systemNode")) {
        return;
      }

      onNodeSelect?.(node.data());
      const now = Date.now();
      // Cytoscape 在不同设备上不一定产生 dbltap，因此同时保留 1500ms 双击判定。
      const isSecondTap = lastTap.id === node.id() && now - lastTap.at < 1500;
      lastTap = { id: node.id(), at: now };
      if (isSecondTap) {
        enterExactNode(node);
      }
    });

    cy.on("dbltap dblclick", "node", (event) => {
      enterExactNode(event.target);
    });

    cy.on("mouseover", "node", (event) => {
      if (event.target.data("decorative") || event.target.data("systemNode") || draggingNodeId) {
        return;
      }
      event.target.addClass("is-hovered");
      containerRef.current.classList.add("is-hovering-node");
      startHoverPulse(event.target);
    });

    cy.on("mouseout", "node", (event) => {
      if (event.target.data("decorative") || event.target.data("systemNode")) {
        return;
      }
      stopHoverPulse(event.target);
      event.target.removeClass("is-hovered");
      containerRef.current.classList.remove("is-hovering-node");
    });

    cy.on("grab", "node", (event) => {
      if (event.target.data("decorative") || event.target.data("systemNode")) {
        return;
      }
      draggingNodeId = event.target.id();
      stopHoverPulse(event.target);
      event.target.removeClass("is-hovered");
      containerRef.current.classList.remove("is-hovering-node");
    });
    cy.on("free", "node", (event) => {
      if (!event.target.data("decorative") && !event.target.data("systemNode")) {
        lastDrag = { id: event.target.id(), at: Date.now() };
        draggingNodeId = "";
      }
    });
    cy.on("position", "node", (event) => {
      syncDecorations(event.target);
    });

    return () => {
      disposed = true;
      hoverPulseTimers.forEach((timer) => window.clearInterval(timer));
      window.clearTimeout(fitTimer);
      activeLayout?.stop();
      cy.elements().stop(true, false);
      cy.destroy();
      cyRef.current = null;
    };
  }, [graph, onNodeEnter, onNodeSelect]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") {
      return undefined;
    }

    let resizeFrame = 0;
    let fitTimer = 0;
    const observer = new ResizeObserver(() => {
      window.cancelAnimationFrame(resizeFrame);
      window.clearTimeout(fitTimer);
      resizeFrame = window.requestAnimationFrame(() => {
        const cy = cyRef.current;
        if (!cy || cy.destroyed()) {
          return;
        }
        cy.resize();
        fitTimer = window.setTimeout(() => {
          if (!cy.destroyed()) {
            const nodeCount = cy.nodes(".neuron, .parent-ghost").length;
            const padding = nodeCount > 80 ? 28 : nodeCount > 40 ? 46 : 72;
            cy.fit(cy.nodes(".neuron, .parent-ghost"), padding);
          }
        }, 120);
      });
    });

    observer.observe(container);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(resizeFrame);
      window.clearTimeout(fitTimer);
    };
  }, [graph]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }

    cy.nodes().removeClass("is-selected");
    if (selectedNodeId) {
      const selected = cy.$id(selectedNodeId);
      if (selected.length) {
        selected.addClass("is-selected");
        selected.closedNeighborhood().edges().animate(
          {
            style: {
              "line-opacity": 0.78
            }
          },
          { duration: 220 }
        );
      }
    }
  }, [selectedNodeId]);

  return (
    <div className="graph-stage">
      {graph.legend?.length ? (
        <aside className="graph-layer-legend" aria-label="节点层级图例">
          <span className="graph-layer-legend-title">节点层级</span>
          {graph.legend.map((item) => (
            <div className="graph-layer-legend-item" key={item.layer}>
              <i style={{ "--legend-color": item.color }} />
              <span>{item.label}</span>
            </div>
          ))}
        </aside>
      ) : null}
      {graph.focusNode ? (
        <div className="focus-halo" aria-hidden="true">
          <span>{graph.focusNode.label}</span>
        </div>
      ) : null}
      <div className="neural-field" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
      <div className="cy-canvas" ref={containerRef} />
    </div>
  );
});

export default GraphCanvas;
