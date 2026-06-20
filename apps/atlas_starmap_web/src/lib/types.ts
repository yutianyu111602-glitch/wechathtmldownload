/* Graph data types shared with tools/atlas_rebuild/export_starmap_layout.py */

export interface GraphNode {
  id: number;
  x: number;
  y: number;
  z: number;
  label: string;
  name: string;
  file_path?: string;
  size: number;
  color: string;
  dj_id?: string;
  city?: string;
  event_count?: number;
  community?: number;
  first_seen_at?: string;
  last_seen_at?: string;
}

export interface GraphEdge {
  source: number;
  target: number;
  type: string;
  score?: number;
  same_event?: number;
  label_zh?: string;
  evidence?: Array<{
    title?: string;
    date?: string;
    source_ref_id?: string;
  }>;
}

export interface LinkedProject {
  project: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  offset: { x: number; y: number; z: number };
  cross_edges: GraphEdge[];
}

export interface GraphData {
  version?: number;
  project?: string;
  lens?: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_nodes: number;
  meta?: {
    generated_at?: string;
    source_db?: string;
    node_count?: number;
    edge_count?: number;
    b2b_edges?: number;
    collab_edges?: number;
  };
  linked_projects?: LinkedProject[];
}

export interface Project {
  name: string;
  root_path: string;
  indexed_at: string;
}

export interface SchemaInfo {
  node_labels: { label: string; count: number }[];
  edge_types: { type: string; count: number }[];
  total_nodes: number;
  total_edges: number;
}

export type TabId = "graph";

export interface ProcessInfo {
  pid: number;
  cpu: number;
  rss_mb: number;
  elapsed: string;
  command: string;
  is_self: boolean;
}
