export interface ArchiveQueueRecord {
  account_key: string;
  token: string;
  source_url: string;
  title: string;
  author: string;
  cover_url: string;
  post_time: string;
  post_date: string;
  page: number;
  discovered_at: string;
  discovery_source: string;
}

export interface ArchiveMetaJson {
  account_key: string;
  token: string;
  source_url: string;
  final_url: string;
  title: string;
  archived_at: string;
  status: "archived" | "failed" | "partial" | "skipped";
  capture_method?: "playwright" | "mptext-api" | "dajiala-api";
  raw_html_bytes: number;
  mhtml_bytes: number;
  pdf_bytes: number;
  warnings: string[];
}

export interface LocalAssetRecord {
  asset_id: string;
  remote_url: string;
  local_path: string;
  status: "downloaded" | "failed" | "skipped";
  content_type: string;
  file_size: number;
  sha256: string;
  source_token: string;
  source_kind?: "image" | "media";
  error_message?: string;
}

export interface AssetsLocalJson {
  images: LocalAssetRecord[];
  media: LocalAssetRecord[];
  warnings?: string[];
}

export interface ArchiveBatchItemSnapshot {
  token: string;
  accountKey: string;
  sourceUrl: string;
  outDir: string;
  status: "queued" | "running" | "succeeded" | "failed" | "skipped";
  message: string;
  errorMessage: string;
  startedAt: string;
  endedAt: string;
}

export interface ArchiveBatchSnapshot {
  queuePath: string;
  archiveRoot: string;
  statusPath: string;
  status: "running" | "completed";
  startedAt: string;
  endedAt: string;
  totalItems: number;
  queuedCount: number;
  runningCount: number;
  succeededCount: number;
  failedCount: number;
  skippedCount: number;
  itemCount?: number;
  itemLimit?: number;
  itemsTruncated?: boolean;
  items: ArchiveBatchItemSnapshot[];
}

export interface PosterCandidate {
  asset_id: string;
  local_path: string;
  score: number;
}

export interface PosterRecoveredFields {
  venue_name_candidate?: string;
  venue_address_lines?: string[];
  lineup_lines?: string[];
  date_texts?: string[];
}

export interface PosterOcrBlock {
  text: string;
  box?: number[][];
  score?: number;
}

export interface PosterOcrResult {
  backend?: string;
  image_path?: string;
  blocks?: PosterOcrBlock[];
  plain_text?: string;
  imageHeavy: boolean;
  candidates: PosterCandidate[];
  recovered: PosterRecoveredFields;
  warnings: string[];
}

export interface SidecarImageEntry {
  label: string;
  remote_url: string;
  local_path: string;
}

export interface SidecarLinkEntry {
  text: string;
  href: string;
  type: string;
}

export interface SidecarJson {
  version: number;
  input_mode: "html" | "archive";
  meta: import("../types.js").MetaJson;
  footer_info: import("../types.js").FooterInfo;
  archive: ArchiveMetaJson | null;
  main_content: string;
  background_recall: string;
  links: SidecarLinkEntry[];
  images: SidecarImageEntry[];
  warnings: string[];
  provenance: {
    primary_source: string;
    fallback_sources: string[];
  };
  poster_ocr: PosterOcrResult;
}

export interface QualityReportJson {
  input_mode: "html" | "archive";
  used_local_assets: boolean;
  image_count: number;
  link_count: number;
  background_recall_chars: number;
  poster_candidates: number;
  warnings: string[];
}
