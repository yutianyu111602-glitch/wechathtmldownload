/* Graph data types shared with tools/atlas_rebuild/export_starmap_layout.py */

export interface GraphNode {
  id: number;
  urn?: string;
  subject_id?: string;
  type?: string;
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
  relation_count?: number;
  community?: number | string;
  org_type?: string;
  concept?: string;
  styles?: string[];
  social?: Record<string, string>;
  bio?: string;
  geo?: { lat: number; lng: number } | null;
  first_seen_at?: string;
  last_seen_at?: string;
}

export interface GraphEdge {
  source: number;
  target: number;
  type: string;
  score?: number;
  weight?: number;
  same_event?: number;
  b2b_count?: number;
  label_zh?: string;
  first_seen_at?: string;
  last_seen_at?: string;
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
  version?: number | string;
  schemaVersion?: string;
  project?: string;
  lens?: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_nodes: number;
  facets?: {
    cities?: string[];
    styles?: string[];
    types?: string[];
  };
  meta?: {
    generated_at?: string;
    source_db?: string;
    node_count?: number;
    edge_count?: number;
    edge_type_counts?: Record<string, number>;
    group_count?: number;
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
