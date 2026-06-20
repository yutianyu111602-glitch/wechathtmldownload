import { useEffect, useState, useCallback, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { useGraphData } from "../hooks/useGraphData";
import {
  GraphScene,
  computeCameraTarget,
  type CameraTarget,
} from "./GraphScene";
import { Sidebar } from "./Sidebar";
import { FilterPanel } from "./FilterPanel";
import { NodeDetailPanel } from "./NodeDetailPanel";
import { ResizeHandle } from "./ResizeHandle";
import { ErrorBoundary } from "./ErrorBoundary";
import type { GraphNode, GraphData } from "../lib/types";

const ATLAS_LENSES = [
  { id: "b2b_universe", label: "B2B" },
  { id: "residency_map", label: "驻场" },
  { id: "label_roster", label: "厂牌" },
  { id: "series", label: "系列" },
  { id: "city", label: "城市" },
  { id: "style", label: "曲风" },
];

/* Persist panel widths */
function loadWidth(key: string, fallback: number): number {
  try {
    const v = localStorage.getItem(key);
    if (v) return Math.max(150, Math.min(600, parseInt(v, 10)));
  } catch { /* ignore */ }
  return fallback;
}
function saveWidth(key: string, value: number) {
  try { localStorage.setItem(key, String(Math.round(value))); } catch { /* ignore */ }
}

function useIsNarrowViewport(): boolean {
  const [isNarrow, setIsNarrow] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(max-width: 767px)").matches;
  });

  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const update = () => setIsNarrow(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return isNarrow;
}

interface GraphTabProps {
  project: string | null;
}

export function GraphTab({ project }: GraphTabProps) {
  const { data, loading, error, fetchOverview } = useGraphData();
  const [selectedLens, setSelectedLens] = useState("b2b_universe");
  const [highlightedIds, setHighlightedIds] = useState<Set<number> | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [cameraTarget, setCameraTarget] = useState<CameraTarget | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [leftWidth, setLeftWidth] = useState(() => loadWidth("atlas-left-w", 248));
  const [rightWidth, setRightWidth] = useState(() => loadWidth("atlas-right-w", 304));
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const isNarrow = useIsNarrowViewport();

  /* Filter state — all enabled by default */
  const [enabledLabels, setEnabledLabels] = useState<Set<string>>(new Set());
  const [enabledEdgeTypes, setEnabledEdgeTypes] = useState<Set<string>>(new Set());

  /* Initialize filters when data loads */
  useEffect(() => {
    if (!data) return;
    const labels = new Set(data.nodes.map((n) => n.label));
    const types = new Set(data.edges.map((e) => e.type));
    for (const lp of data.linked_projects ?? []) {
      for (const n of lp.nodes) labels.add(n.label);
      for (const e of lp.edges) types.add(e.type);
      for (const e of lp.cross_edges) types.add(e.type);
    }
    setEnabledLabels(labels);
    setEnabledEdgeTypes(types);
  }, [data]);

  /* Compute filtered data */
  const filteredData: GraphData | null = useMemo(() => {
    if (!data) return null;

    const nodes = data.nodes.filter((n) => enabledLabels.has(n.label));
    const nodeIds = new Set(nodes.map((n) => n.id));
    const edges = data.edges.filter(
      (e) =>
        enabledEdgeTypes.has(e.type) &&
        nodeIds.has(e.source) &&
        nodeIds.has(e.target),
    );

    const linked_projects = data.linked_projects?.map((lp) => {
      const lpNodes = lp.nodes.filter((n) => enabledLabels.has(n.label));
      const lpIds = new Set(lpNodes.map((n) => n.id));
      const lpEdges = lp.edges.filter(
        (e) =>
          enabledEdgeTypes.has(e.type) && lpIds.has(e.source) && lpIds.has(e.target),
      );
      const crossEdges = lp.cross_edges.filter(
        (e) =>
          enabledEdgeTypes.has(e.type) && nodeIds.has(e.source) && lpIds.has(e.target),
      );
      return { ...lp, nodes: lpNodes, edges: lpEdges, cross_edges: crossEdges };
    });

    return { ...data, nodes, edges, total_nodes: data.total_nodes, linked_projects };
  }, [data, enabledLabels, enabledEdgeTypes]);

  useEffect(() => {
    if (project) {
      fetchOverview(project, selectedLens);
      setHighlightedIds(null);
      setSelectedPath(null);
      setSelectedNode(null);
    }
  }, [project, selectedLens, fetchOverview]);

  const handleSelectPath = useCallback(
    (path: string, nodeIds: Set<number>) => {
      if (!filteredData || !path || nodeIds.size === 0) {
        setHighlightedIds(null);
        setSelectedPath(null);
        setCameraTarget(null);
        return;
      }
      setSelectedPath(path);
      setHighlightedIds(nodeIds);
      setCameraTarget(computeCameraTarget(filteredData.nodes, nodeIds));
      if (isNarrow) setMobileSidebarOpen(false);
    },
    [filteredData, isNarrow],
  );

  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      if (!filteredData) return;
      setSelectedNode(node);

      /* Highlight the node and its direct connections */
      const connectedIds = new Set([node.id]);
      for (const edge of filteredData.edges) {
        if (edge.source === node.id) connectedIds.add(edge.target);
        if (edge.target === node.id) connectedIds.add(edge.source);
      }
      setHighlightedIds(connectedIds);
      setSelectedPath(`node:${node.id}`);
      setCameraTarget(computeCameraTarget(filteredData.nodes, connectedIds));
      if (isNarrow) setMobileSidebarOpen(false);
    },
    [filteredData, isNarrow],
  );

  const handleNavigateToNode = useCallback(
    (node: GraphNode) => {
      handleNodeClick(node);
    },
    [handleNodeClick],
  );

  const toggleLabel = useCallback((label: string) => {
    setEnabledLabels((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }, []);

  const toggleEdgeType = useCallback((type: string) => {
    setEnabledEdgeTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }, []);

  const enableAll = useCallback(() => {
    if (!data) return;
    const labels = new Set(data.nodes.map((n) => n.label));
    const types = new Set(data.edges.map((e) => e.type));
    for (const lp of data.linked_projects ?? []) {
      for (const n of lp.nodes) labels.add(n.label);
      for (const e of lp.edges) types.add(e.type);
      for (const e of lp.cross_edges) types.add(e.type);
    }
    setEnabledLabels(labels);
    setEnabledEdgeTypes(types);
  }, [data]);

  const disableAll = useCallback(() => {
    setEnabledLabels(new Set());
    setEnabledEdgeTypes(new Set());
  }, []);

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-white/30 text-sm">
          正在准备 ATLAS 星图
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin mx-auto mb-3" />
          <p className="text-white/40 text-sm">正在载入星图...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center p-8">
          <p className="text-red-400 text-sm mb-2">{error}</p>
          <Button variant="outline" size="sm" onClick={() => fetchOverview(project)}>
            重试
          </Button>
        </div>
      </div>
    );
  }

  if (!data || !filteredData || filteredData.nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-white/30 text-sm mb-3">
            {data && filteredData?.nodes.length === 0
              ? "当前筛选没有节点"
              : "没有可展示节点"}
          </p>
          {data && filteredData?.nodes.length === 0 && (
            <Button size="sm" onClick={enableAll}>
              重置筛选
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex relative overflow-hidden">
      {isNarrow && mobileSidebarOpen && (
        <button
          type="button"
          aria-label="关闭筛选背景"
          className="absolute inset-0 z-20 bg-black/45"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* Left sidebar — desktop resize, mobile drawer */}
      <div
        className={[
          "atlas-left-panel border-r border-border/30 flex flex-col h-full bg-[#0b1920]/95 backdrop-blur-md",
          isNarrow
            ? `absolute inset-y-0 left-0 z-30 w-[min(86vw,340px)] max-w-[340px] shadow-2xl shadow-black/35 transition-transform duration-200 ${
                mobileSidebarOpen ? "translate-x-0" : "-translate-x-full pointer-events-none"
              }`
            : "relative shrink-0",
        ].join(" ")}
        style={isNarrow ? undefined : { width: leftWidth }}
      >
        {isNarrow && (
          <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-border/30 min-h-[40px]">
            <span className="text-[12px] font-medium text-foreground/70">筛选 / 搜索</span>
            <button
              type="button"
              onClick={() => setMobileSidebarOpen(false)}
              className="w-7 h-7 rounded border border-white/[0.06] bg-white/[0.04] text-foreground/55 hover:text-foreground/85 hover:bg-white/[0.08] transition-colors"
              aria-label="关闭筛选"
            >
              ×
            </button>
          </div>
        )}
        <FilterPanel
          data={data}
          lenses={ATLAS_LENSES}
          selectedLens={selectedLens}
          enabledLabels={enabledLabels}
          enabledEdgeTypes={enabledEdgeTypes}
          showLabels={showLabels}
          onLensChange={setSelectedLens}
          onToggleLabel={toggleLabel}
          onToggleEdgeType={toggleEdgeType}
          onToggleShowLabels={() => setShowLabels((v) => !v)}
          onEnableAll={enableAll}
          onDisableAll={disableAll}
        />
        <Sidebar
          nodes={filteredData.nodes}
          onSelectPath={handleSelectPath}
          onSelectNode={handleNavigateToNode}
          selectedPath={selectedPath}
        />
      </div>
      {!isNarrow && (
        <ResizeHandle
          side="left"
          onResize={(d) => {
            setLeftWidth((w) => {
              const nw = Math.max(150, Math.min(500, w + d));
              saveWidth("atlas-left-w", nw);
              return nw;
            });
          }}
        />
      )}

      {/* Graph area */}
      <div className="flex-1 relative overflow-hidden min-w-0">
        <ErrorBoundary>
          <GraphScene
            data={filteredData}
            highlightedIds={highlightedIds}
            cameraTarget={cameraTarget}
            showLabels={showLabels}
            onNodeClick={handleNodeClick}
          />
        </ErrorBoundary>

        {isNarrow && (
          <div className="absolute top-3 left-3 z-20">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setMobileSidebarOpen(true)}
              aria-label="打开搜索筛选"
              className="bg-[#071218]/85"
            >
              筛选
            </Button>
          </div>
        )}

        {/* HUD */}
        <div className="absolute top-14 left-3 sm:top-4 sm:left-4 text-[10px] sm:text-[11px] text-white/30 pointer-events-none font-mono">
          <p>
            {filteredData.nodes.length.toLocaleString()} 节点 /{" "}
            {filteredData.edges.length.toLocaleString()} 关系
          </p>
          {data.nodes.length > filteredData.nodes.length && (
            <p className="text-white/25 mt-0.5">
              筛选自 {data.nodes.length.toLocaleString()} 节点
            </p>
          )}
          {highlightedIds && highlightedIds.size > 0 && (
            <p className="text-cyan-400/50 mt-0.5">
              已选 {highlightedIds.size}
            </p>
          )}
        </div>

        <div className="absolute top-3 right-3 sm:top-4 sm:right-4 flex gap-1.5 sm:gap-2 z-20">
          {highlightedIds && (
            <Button
              size="sm"
              onClick={() => {
                setHighlightedIds(null);
                setSelectedPath(null);
                setSelectedNode(null);
                setCameraTarget(null);
              }}
            >
              清除
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setHighlightedIds(null);
              setSelectedPath(null);
              setSelectedNode(null);
              setCameraTarget(null);
              fetchOverview(project, selectedLens);
            }}
          >
              刷新
          </Button>
        </div>
      </div>

      {/* Right detail panel — resizable */}
      {selectedNode && filteredData && (
        isNarrow ? (
          <>
            <button
              type="button"
              aria-label="关闭详情背景"
              className="absolute inset-0 z-30 bg-black/50"
              onClick={() => {
                setSelectedNode(null);
                setHighlightedIds(null);
                setSelectedPath(null);
              }}
            />
            <div className="atlas-detail-panel absolute inset-y-0 right-0 z-40 w-full max-w-[420px] border-l border-border bg-[#071218] shadow-2xl shadow-black/45 overflow-hidden">
              <NodeDetailPanel
                node={selectedNode}
                allNodes={filteredData.nodes}
                allEdges={filteredData.edges}
                onClose={() => {
                  setSelectedNode(null);
                  setHighlightedIds(null);
                  setSelectedPath(null);
                }}
                onNavigate={handleNavigateToNode}
              />
            </div>
          </>
        ) : (
          <>
          <ResizeHandle
            side="right"
            className="atlas-detail-resize"
            onResize={(d) => {
              setRightWidth((w) => {
                const nw = Math.max(200, Math.min(500, w + d));
                saveWidth("atlas-right-w", nw);
                return nw;
              });
            }}
          />
          <div
            className="atlas-detail-panel border-l border-border shrink-0 h-full overflow-hidden"
            style={{ width: rightWidth, maxHeight: "100%" }}
          >
            <NodeDetailPanel
              node={selectedNode}
              allNodes={filteredData.nodes}
              allEdges={filteredData.edges}
              onClose={() => {
                setSelectedNode(null);
                setHighlightedIds(null);
                setSelectedPath(null);
              }}
              onNavigate={handleNavigateToNode}
            />
          </div>
        </>
        )
      )}
    </div>
  );
}
