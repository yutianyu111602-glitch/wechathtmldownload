import type { ArticleHtmlQuality } from "../archive/articleHtmlQuality.js";

export type ArchiveAuditItemStatus =
  | "archived"
  | "partial"
  | "failed"
  | "skipped"
  | "missing"
  | "unsafe_path";

export type ArchiveAuditIssue =
  | "duplicate_token"
  | "unsafe_account_key"
  | "unsafe_token"
  | "missing_bundle"
  | "missing_raw_html"
  | "empty_raw_html"
  | "invalid_raw_html"
  | "missing_archive_meta"
  | "invalid_archive_meta_json"
  | "archive_status_failed"
  | "archive_status_partial"
  | "archive_status_skipped"
  | "invalid_assets_local_json";

export interface ArchiveAuditItem {
  account_key: string;
  token: string;
  source_url: string;
  title: string;
  bundle_dir: string;
  status: ArchiveAuditItemStatus;
  retry: boolean;
  issues: ArchiveAuditIssue[];
  warnings: string[];
  error_message: string;
  archive_status: string;
  capture_method: string;
  duplicate_token_count: number;
  files: {
    bundle_dir: boolean;
    raw_html: boolean;
    archive_meta_json: boolean;
    assets_local_json: boolean;
    page_mhtml: boolean;
    page_pdf: boolean;
    raw_html_bytes: number;
    local_image_count: number;
    local_media_count: number;
  };
  html_quality: ArticleHtmlQuality | null;
}

export interface ArchiveAuditAccountSummary {
  account_key: string;
  total_records: number;
  archived_count: number;
  retry_count: number;
  failed_count: number;
  missing_count: number;
  warning_count: number;
}

export interface ArchiveAuditSummary {
  version: number;
  generated_at: string;
  manifest_path: string;
  archive_root: string;
  out_dir: string;
  total_records: number;
  archived_count: number;
  retry_queue_count: number;
  duplicate_token_count: number;
  account_count: number;
  status_counts: Record<string, number>;
  issue_counts: Record<string, number>;
  output_paths: {
    summary_json: string;
    items_jsonl: string;
    account_summary_jsonl: string;
    retry_queue_jsonl: string;
    ui_projection_json: string;
  };
}

export type FinalLlmQualityGrade = "ready" | "review" | "blocked";

export interface FinalLlmPackIndexRecord {
  account: string;
  token: string;
  title: string;
  source_url: string;
  post_date: string;
  source_artifact_dir: string;
  source_archive_dir: string;
  markdown_path: string;
  sidecar_path: string;
  quality_report_path: string;
  quality_grade: FinalLlmQualityGrade;
  warning_count: number;
  local_image_count: number;
  main_content_chars: number;
  background_recall_chars: number;
  processed_at: string;
}

export interface FinalLlmPackSubPack {
  pack_index: number;
  articles_dir: string;
  index_jsonl: string;
  manifest_json: string;
  article_count: number;
  size_bytes: number;
}

export interface FinalLlmPackManifest {
  version: number;
  generated_at: string;
  artifact_root: string;
  release_root: string;
  archive_root: string;
  manifest_path: string;
  total_articles: number;
  copied_articles: number;
  quality_counts: Record<FinalLlmQualityGrade, number>;
  copied_file_counts: Record<string, number>;
  excluded: {
    sensitive_path_segments: string[];
    raw_archive_files: string[];
  };
  output_paths: {
    index_jsonl: string;
    manifest_json: string;
    articles_dir: string;
    checksums_sha256?: string;
  };
  partitioned?: boolean;
  max_pack_size_bytes?: number;
  sub_packs?: FinalLlmPackSubPack[];
}
