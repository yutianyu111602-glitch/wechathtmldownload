import { useMemo } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { colorForLabel } from "../lib/colors";
import type { GraphNode, GraphEdge } from "../lib/types";

interface Connection {
  node: GraphNode;
  edge: GraphEdge;
}

interface EvidenceItem {
  title: string;
  date: string;
  sourceRefId: string;
}

interface NodeDetailPanelProps {
  node: GraphNode;
  allNodes: GraphNode[];
  allEdges: GraphEdge[];
  onClose: () => void;
  onNavigate: (node: GraphNode) => void;
}

function edgeTypeLabel(type: string): string {
  if (type === "b2b") return "B2B 深度合作";
  if (type === "collab") return "高频同台";
  if (type === "resident_at") return "驻场 / 常演";
  if (type === "signed_to") return "厂牌 / 主办";
  if (type === "held_at") return "系列场地";
  if (type === "presented_by") return "系列主办";
  return type.replace(/_/g, " ").toLowerCase();
}

function nodeTypeLabel(type: string): string {
  if (type === "venue") return "场地";
  if (type === "org") return "厂牌";
  if (type === "series") return "系列";
  return "DJ";
}

function formatDate(value?: string): string {
  if (!value) return "未知";
  return value.slice(0, 10);
}

function edgeWeight(edge: GraphEdge): number {
  return edge.same_event ?? edge.weight ?? edge.score ?? 0;
}

export function NodeDetailPanel({ node, allNodes, allEdges, onClose, onNavigate }: NodeDetailPanelProps) {
  const { connections, evidence } = useMemo(() => {
    const nodeMap = new Map<number, GraphNode>();
    for (const n of allNodes) nodeMap.set(n.id, n);

    const conns: Connection[] = [];
    const ev = new Map<string, EvidenceItem>();
    for (const edge of allEdges) {
      const sourceMatch = edge.source === node.id;
      const targetMatch = edge.target === node.id;
      if (!sourceMatch && !targetMatch) continue;

      const peer = nodeMap.get(sourceMatch ? edge.target : edge.source);
      if (peer) conns.push({ node: peer, edge });

      for (const item of edge.evidence ?? []) {
        const title = String(item.title || "").trim();
        const date = String(item.date || "").trim();
        const sourceRefId = String(item.source_ref_id || "").trim();
        if (!title && !sourceRefId) continue;
        const key = `${sourceRefId}|${date}|${title}`;
        if (!ev.has(key)) {
          ev.set(key, {
            title: title || sourceRefId,
            date: date || "日期未知",
            sourceRefId,
          });
        }
      }
    }
    conns.sort((a, b) => edgeWeight(b.edge) - edgeWeight(a.edge));
    return { connections: conns, evidence: [...ev.values()].slice(0, 12) };
  }, [node, allNodes, allEdges]);

  const b2bCount = connections.filter((c) => c.edge.type === "b2b").length;
  const collabCount = connections.filter((c) => c.edge.type === "collab").length;
  const groups = useMemo(() => {
    const map = new Map<string, Connection[]>();
    for (const c of connections) map.set(c.edge.type, [...(map.get(c.edge.type) ?? []), c]);
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [connections]);

  return (
    <div className="w-full bg-[#071218]/98 flex flex-col h-full min-h-0 overflow-hidden">
      <div className="px-4 pt-4 pb-3 border-b border-border/30">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1.5">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: colorForLabel(node.label) }} />
              <h3 className="text-[14px] font-semibold text-foreground truncate">{node.name}</h3>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className="inline-block px-2 py-0.5 rounded text-[10px] font-medium"
                style={{ backgroundColor: colorForLabel(node.label) + "18", color: colorForLabel(node.label) }}
              >
                {nodeTypeLabel(node.label)}
              </span>
              <span className="inline-block px-2 py-0.5 rounded border border-white/[0.06] bg-white/[0.03] text-[10px] text-foreground/55">
                {node.city || "城市未知"}
              </span>
            </div>
          </div>
          <button onClick={onClose} className="text-foreground/25 hover:text-foreground/60 transition-colors text-[16px] leading-none p-1">×</button>
        </div>

        <div className="grid grid-cols-3 gap-3 mt-3">
          {(node.label === "venue"
            ? [
                { label: "演出", value: node.event_count ?? 0, color: "text-primary" },
                { label: "驻场DJ", value: connections.length, color: "text-[#ffcf6b]" },
                { label: "城市", value: node.city || "未知", color: "text-accent" },
              ]
            : node.label === "org"
            ? [
                { label: "关联DJ", value: connections.length, color: "text-[#b794f6]" },
                { label: "类型", value: node.org_type || "厂牌", color: "text-accent" },
                { label: "证据", value: evidence.length, color: "text-primary" },
              ]
            : node.label === "series"
            ? [
                { label: "期数", value: node.event_count ?? 0, color: "text-[#2dd4bf]" },
                { label: "连接", value: connections.length, color: "text-accent" },
                { label: "概念", value: node.concept || "系列", color: "text-primary" },
              ]
            : [
                { label: "演出", value: node.event_count ?? 0, color: "text-primary" },
                { label: "B2B", value: b2bCount, color: "text-[#f8c56a]" },
                { label: "同台", value: collabCount, color: "text-accent" },
              ]
          ).map((s) => (
            <div key={s.label} className="rounded border border-white/[0.05] bg-white/[0.025] px-2 py-1.5">
              <p className="text-[9px] text-foreground/30 uppercase tracking-widest">{s.label}</p>
              <p className={`text-[18px] font-semibold tabular-nums ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>

        <div className="mt-3 text-[11px] text-foreground/40 leading-relaxed">
          <span>{formatDate(node.first_seen_at)}</span>
          <span className="mx-1.5 text-foreground/20">→</span>
          <span>{formatDate(node.last_seen_at)}</span>
          {node.community !== undefined && (
            <span className="ml-2 text-foreground/25">分组 {node.community}</span>
          )}
        </div>
        {node.styles && node.styles.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {node.styles.slice(0, 6).map((style) => (
              <span key={style} className="px-1.5 py-0.5 rounded border border-white/[0.05] bg-white/[0.025] text-[10px] text-foreground/40">
                {style}
              </span>
            ))}
          </div>
        )}
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="px-4 py-3 space-y-5">
          {(node.bio || (node.social && Object.keys(node.social).length > 0)) && (
            <section>
              {node.bio && (
                <p className="text-[12px] text-foreground/65 leading-relaxed mb-2">{node.bio}</p>
              )}
              {node.social && Object.keys(node.social).length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(node.social)
                    .filter(([, v]) => v)
                    .map(([k, v]) => (
                      <a
                        key={k}
                        href={/^https?:\/\//i.test(String(v)) ? String(v) : `https://${v}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-2 py-0.5 rounded border border-white/[0.08] bg-white/[0.03] text-[10px] text-[#7eb8da] hover:bg-white/[0.06] transition-colors"
                      >
                        {k}
                      </a>
                    ))}
                </div>
              )}
            </section>
          )}
          <section>
            <p className="text-[11px] font-medium text-foreground/45 mb-2">
              直接关系 <span className="text-foreground/18">({connections.length})</span>
            </p>
            {groups.length === 0 ? (
              <p className="text-[12px] text-foreground/25 text-center py-8">暂无关系</p>
            ) : (
              groups.map(([type, conns]) => (
                <ConnectionGroup key={type} type={type} connections={conns} onNavigate={onNavigate} />
              ))
            )}
          </section>

          <section>
            <p className="text-[11px] font-medium text-foreground/45 mb-2">
              证据 <span className="text-foreground/18">({evidence.length})</span>
            </p>
            {evidence.length === 0 ? (
              <p className="text-[12px] text-foreground/20">暂无可展示证据</p>
            ) : (
              <div className="space-y-2">
                {evidence.map((item) => (
                  <div key={`${item.sourceRefId}|${item.date}|${item.title}`} className="rounded border border-white/[0.05] bg-white/[0.025] px-2.5 py-2">
                    <p className="text-[11px] text-foreground/70 leading-snug">{item.title}</p>
                    <p className="mt-1 text-[10px] text-foreground/30 font-mono">
                      {item.date}{item.sourceRefId ? ` · ${item.sourceRefId}` : ""}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </ScrollArea>
    </div>
  );
}

function ConnectionGroup({
  type,
  connections,
  onNavigate,
}: {
  type: string;
  connections: Connection[];
  onNavigate: (n: GraphNode) => void;
}) {
  return (
    <div className="mb-3">
      <p className="text-[9px] text-foreground/25 uppercase tracking-wider mb-1 font-medium">
        {edgeTypeLabel(type)}
      </p>
      <div className="space-y-px">
        {connections.slice(0, 30).map((c, i) => (
          <button
            key={`${c.node.id}-${c.edge.type}-${i}`}
            onClick={() => onNavigate(c.node)}
            className="flex items-center gap-1.5 w-full text-left px-2 py-[5px] rounded hover:bg-white/[0.04] text-[11px] transition-colors group"
          >
            <span className="w-[5px] h-[5px] rounded-full shrink-0" style={{ backgroundColor: c.node.color }} />
            <span className="text-foreground/60 group-hover:text-foreground/85 truncate">{c.node.name}</span>
            <span className="text-foreground/18 ml-auto text-[10px] shrink-0 tabular-nums">
              {edgeWeight(c.edge)}
            </span>
          </button>
        ))}
        {connections.length > 30 && (
          <p className="text-[10px] text-foreground/18 px-2 py-1">+{connections.length - 30} more</p>
        )}
      </div>
    </div>
  );
}
