import { useMemo } from "react";
import { colorForLabel } from "../lib/colors";
import type { GraphData } from "../lib/types";

interface FilterPanelProps {
  data: GraphData;
  enabledLabels: Set<string>;
  enabledEdgeTypes: Set<string>;
  showLabels: boolean;
  onToggleLabel: (label: string) => void;
  onToggleEdgeType: (type: string) => void;
  onToggleShowLabels: () => void;
  onEnableAll: () => void;
  onDisableAll: () => void;
}

function edgeTypeLabel(type: string): string {
  if (type === "b2b") return "B2B 深度合作";
  if (type === "collab") return "高频同台";
  return type.replace(/_/g, " ").toLowerCase();
}

export function FilterPanel({
  data,
  enabledLabels,
  enabledEdgeTypes,
  showLabels,
  onToggleLabel,
  onToggleEdgeType,
  onToggleShowLabels,
  onEnableAll,
  onDisableAll,
}: FilterPanelProps) {
  const { labelCounts, edgeTypeCounts } = useMemo(() => {
    const lc = new Map<string, number>();
    for (const n of data.nodes) lc.set(n.label, (lc.get(n.label) ?? 0) + 1);
    const ec = new Map<string, number>();
    for (const e of data.edges) ec.set(e.type, (ec.get(e.type) ?? 0) + 1);
    return {
      labelCounts: [...lc.entries()].sort((a, b) => b[1] - a[1]),
      edgeTypeCounts: [...ec.entries()].sort((a, b) => b[1] - a[1]),
    };
  }, [data]);

  return (
    <div className="px-4 py-3 border-b border-border/40 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium text-foreground/55 uppercase tracking-widest">
          筛选
        </span>
        <div className="flex items-center gap-2">
          <button onClick={onEnableAll} className="text-[10px] text-primary/75 hover:text-primary transition-colors">
            全选
          </button>
          <span className="text-foreground/15">|</span>
          <button onClick={onDisableAll} className="text-[10px] text-primary/75 hover:text-primary transition-colors">
            清空
          </button>
        </div>
      </div>

      <div>
        <p className="text-[10px] text-foreground/35 mb-1.5">节点</p>
        <div className="flex flex-wrap gap-1">
          {labelCounts.map(([label, count]) => {
            const on = enabledLabels.has(label);
            const c = colorForLabel(label);
            return (
              <button
                key={label}
                onClick={() => onToggleLabel(label)}
                className={`inline-flex items-center gap-1 px-1.5 py-[3px] rounded text-[10px] font-medium transition-all border ${
                  on ? "border-white/[0.08] bg-white/[0.04]" : "border-transparent opacity-25"
                }`}
              >
                <span className="w-[5px] h-[5px] rounded-full" style={{ backgroundColor: on ? c : "#444" }} />
                <span style={{ color: on ? c : "#555" }}>{label === "dj" ? "DJ" : label}</span>
                <span className="text-foreground/25 tabular-nums">{count.toLocaleString()}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <p className="text-[10px] text-foreground/35 mb-1.5">关系</p>
        <div className="flex flex-wrap gap-1">
          {edgeTypeCounts.map(([type, count]) => {
            const on = enabledEdgeTypes.has(type);
            return (
              <button
                key={type}
                onClick={() => onToggleEdgeType(type)}
                className={`inline-flex items-center gap-1 px-1.5 py-[3px] rounded text-[10px] font-medium transition-all border ${
                  on ? "border-white/[0.06] bg-white/[0.03] text-foreground/70" : "border-transparent opacity-20 text-foreground/35"
                }`}
              >
                {edgeTypeLabel(type)}
                <span className="text-foreground/20 tabular-nums">{count.toLocaleString()}</span>
              </button>
            );
          })}
        </div>
      </div>

      <button
        onClick={onToggleShowLabels}
        className={`inline-flex items-center gap-1.5 text-[11px] font-medium transition-all ${
          showLabels ? "text-primary" : "text-foreground/35"
        }`}
      >
        <span className={`w-3.5 h-3.5 rounded border flex items-center justify-center transition-all ${
          showLabels ? "border-primary bg-primary/20" : "border-foreground/15"
        }`}>
          {showLabels && <span className="text-primary text-[9px]">✓</span>}
        </span>
        显示标签
      </button>
    </div>
  );
}
