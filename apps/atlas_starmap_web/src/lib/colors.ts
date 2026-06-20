/* Node label → color mapping for sidebar/tooltips (structural meaning) */

const LABEL_COLORS: Record<string, string> = {
  DJ: "#38bdf8",
  dj: "#38bdf8",
  Artist: "#a7f3d0",
  Project: "#e11d48",
  Package: "#f97316",
  Module: "#f97316",
  Folder: "#22c55e",
  File: "#3b82f6",
  Class: "#a855f7",
  Interface: "#a855f7",
  Function: "#06b6d4",
  Method: "#06b6d4",
  Route: "#eab308",
  Variable: "#64748b",
};

const DEFAULT_COLOR = "#8fb6d9";

export function colorForLabel(label: string): string {
  return LABEL_COLORS[label] ?? DEFAULT_COLOR;
}

/* Stellar spectral type legend (for the graph view) */
export const STELLAR_LEGEND = [
  { type: "核心节点", color: "#80a0ff", description: "50+ 连接" },
  { type: "高活跃", color: "#c0d0ff", description: "26-50 连接" },
  { type: "稳定活跃", color: "#e8e8ff", description: "13-25 连接" },
  { type: "区域连接", color: "#fff0c0", description: "7-12 连接" },
  { type: "普通节点", color: "#ffe080", description: "4-6 连接" },
  { type: "低频连接", color: "#ffa060", description: "2-3 连接" },
  { type: "新出现/孤点", color: "#ff6050", description: "0-1 连接" },
];
