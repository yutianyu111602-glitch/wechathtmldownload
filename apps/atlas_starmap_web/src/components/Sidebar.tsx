import { useMemo, useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { GraphNode } from "../lib/types";

interface SidebarProps {
  nodes: GraphNode[];
  onSelectPath: (path: string, nodeIds: Set<number>) => void;
  onSelectNode: (node: GraphNode) => void;
  selectedPath: string | null;
}

interface GroupRow {
  key: string;
  label: string;
  nodeIds: Set<number>;
  nodes: GraphNode[];
}

function buildCityGroups(nodes: GraphNode[]): GroupRow[] {
  const groups = new Map<string, GroupRow>();
  for (const node of nodes) {
    const label = node.city || "城市未知";
    const key = `city:${label}`;
    const row = groups.get(key) ?? { key, label, nodeIds: new Set<number>(), nodes: [] };
    row.nodeIds.add(node.id);
    row.nodes.push(node);
    groups.set(key, row);
  }
  return [...groups.values()]
    .map((row) => ({
      ...row,
      nodes: row.nodes.sort((a, b) => (b.event_count ?? 0) - (a.event_count ?? 0)),
    }))
    .sort((a, b) => b.nodeIds.size - a.nodeIds.size || a.label.localeCompare(b.label));
}

export function Sidebar({ nodes, onSelectPath, onSelectNode, selectedPath }: SidebarProps) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const groups = useMemo(() => buildCityGroups(nodes), [nodes]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return null;
    return nodes
      .filter((n) =>
        n.name.toLowerCase().includes(q) ||
        (n.city || "").toLowerCase().includes(q) ||
        String(n.community ?? "").includes(q)
      )
      .sort((a, b) => (b.event_count ?? 0) - (a.event_count ?? 0))
      .slice(0, 80);
  }, [nodes, search]);

  const toggleGroup = (row: GroupRow) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(row.key)) next.delete(row.key);
      else next.add(row.key);
      return next;
    });
    onSelectPath(row.key, row.nodeIds);
  };

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="px-3 py-2.5 border-b border-border/30">
        <input
          type="text"
          placeholder="搜索 DJ / 城市 / 星座"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full bg-white/[0.04] border border-white/[0.06] rounded px-3 py-1.5 text-[12px] text-foreground placeholder-foreground/28 outline-none focus:border-primary/45 focus:bg-white/[0.06] transition-all"
        />
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="py-1">
          {filtered ? (
            filtered.length === 0 ? (
              <p className="text-foreground/22 text-[12px] px-4 py-6 text-center">没有匹配</p>
            ) : (
              filtered.map((node) => (
                <NodeRow key={node.id} node={node} onClick={() => onSelectNode(node)} />
              ))
            )
          ) : (
            groups.map((row) => {
              const open = expanded.has(row.key);
              const isSelected = selectedPath === row.key;
              return (
                <div key={row.key}>
                  <button
                    onClick={() => toggleGroup(row)}
                    className={`flex items-center gap-1.5 w-full text-left px-3 py-[6px] text-[12px] transition-colors ${
                      isSelected ? "bg-primary/10 text-primary" : "text-foreground/62 hover:text-foreground/85 hover:bg-white/[0.03]"
                    }`}
                  >
                    <span className="text-foreground/25 w-3 text-center text-[10px] shrink-0">{open ? "▾" : "▸"}</span>
                    <span className="truncate font-medium">{row.label}</span>
                    <span className="text-foreground/18 ml-auto text-[10px] tabular-nums shrink-0">{row.nodeIds.size}</span>
                  </button>
                  {open && row.nodes.slice(0, 40).map((node) => (
                    <NodeRow
                      key={node.id}
                      node={node}
                      nested
                      onClick={() => onSelectNode(node)}
                    />
                  ))}
                </div>
              );
            })
          )}
        </div>
      </ScrollArea>

      {selectedPath && (
        <div className="px-3 py-2 border-t border-border/30">
          <button
            onClick={() => onSelectPath("", new Set())}
            className="w-full px-3 py-1.5 rounded bg-white/[0.04] hover:bg-white/[0.07] text-[11px] text-foreground/45 font-medium transition-all"
          >
            清除选择
          </button>
        </div>
      )}
    </div>
  );
}

function NodeRow({
  node,
  nested = false,
  onClick,
}: {
  node: GraphNode;
  nested?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 w-full text-left py-[4px] pr-3 text-[11px] text-foreground/48 hover:text-foreground/75 hover:bg-white/[0.025] transition-colors"
      style={{ paddingLeft: nested ? 30 : 16 }}
    >
      <span className="w-[5px] h-[5px] rounded-full shrink-0" style={{ backgroundColor: node.color }} />
      <span className="truncate">{node.name}</span>
      <span className="text-foreground/16 ml-auto text-[10px] shrink-0 tabular-nums">{node.event_count ?? 0}</span>
    </button>
  );
}
