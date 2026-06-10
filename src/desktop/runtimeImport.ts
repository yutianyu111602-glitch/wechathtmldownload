import { dirname } from "node:path";

import type { BatchItemPhase, BatchItemSnapshot, BatchSnapshot, ProcessPhase } from "../types.js";

interface MptextStatusItemLike {
  token?: string;
  accountKey?: string;
  account_key?: string;
  sourceUrl?: string;
  source_url?: string;
  outDir?: string;
  out_dir?: string;
  status?: string;
  message?: string;
  errorMessage?: string;
  error_message?: string;
  startedAt?: string;
  started_at?: string;
  endedAt?: string;
  ended_at?: string;
}

interface MptextStatusLike {
  manifestPath?: string;
  manifest_path?: string;
  archiveRoot?: string;
  archive_root?: string;
  statusPath?: string;
  status_path?: string;
  status?: string;
  startedAt?: string;
  started_at?: string;
  endedAt?: string;
  ended_at?: string;
  totalItems?: number;
  total_items?: number;
  queuedCount?: number;
  queued_count?: number;
  runningCount?: number;
  running_count?: number;
  succeededCount?: number;
  succeeded_count?: number;
  failedCount?: number;
  failed_count?: number;
  skippedCount?: number;
  skipped_count?: number;
  items?: MptextStatusItemLike[];
}

interface ArchiveBundleLike {
  token?: string;
  title?: string;
  accountKey?: string;
  account_key?: string;
  sourceUrl?: string;
  source_url?: string;
  outDir?: string;
  out_dir?: string;
  archiveStatus?: string;
  archive_status?: string;
  message?: string;
  errorMessage?: string;
  error_message?: string;
  archivedAt?: string;
  archived_at?: string;
}

function toStringValue(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function toNumberValue(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function firstNonEmpty(...values: unknown[]): string {
  for (const value of values) {
    const text = toStringValue(value);
    if (text) {
      return text;
    }
  }
  return "";
}

function normalizePath(filePath: string): string {
  return filePath.replace(/\//g, "\\").toLowerCase();
}

function deriveDiscoveryRoot(manifestPath: string, archiveRoot: string): string {
  const normalizedManifest = normalizePath(manifestPath);
  if (normalizedManifest.endsWith("\\_queues\\download_ready_queue.jsonl")) {
    return dirname(dirname(manifestPath));
  }

  const normalizedArchive = normalizePath(archiveRoot);
  if (normalizedArchive.endsWith("\\_archive_mptext")) {
    return dirname(archiveRoot);
  }

  return dirname(archiveRoot);
}

function normalizeImportedItemStatus(status: string): BatchItemSnapshot["status"] {
  if (["queued", "running", "succeeded", "failed", "skipped", "deferred", "cancelled"].includes(status)) {
    return status as BatchItemSnapshot["status"];
  }
  return "queued";
}

function normalizeImportedItemPhase(status: BatchItemSnapshot["status"]): BatchItemPhase {
  if (status === "running") {
    return "write_outputs";
  }
  if (["queued", "succeeded", "failed", "skipped", "deferred", "cancelled"].includes(status)) {
    return status as BatchItemPhase;
  }
  return "queued";
}

function normalizeImportedSnapshotStatus(status: string, runningCount: number, queuedCount: number): BatchSnapshot["status"] {
  if (status === "cancelled") {
    return "cancelled";
  }
  if (status === "completed") {
    return "completed";
  }
  if (status === "running" || runningCount > 0 || queuedCount > 0) {
    return "running";
  }
  return "completed";
}

export function isArchiveWorkspaceRoot(filePath: string): boolean {
  const normalized = normalizePath(toStringValue(filePath));
  return normalized.includes("\\rawwechat_archive") || normalized.includes("\\_archive_mptext");
}

export function buildImportedBatchSnapshotFromMptextStatus(
  status: MptextStatusLike,
): BatchSnapshot & { pipeline: string; imported: true } {
  const manifestPath = firstNonEmpty(status.manifestPath, status.manifest_path);
  const archiveRoot = firstNonEmpty(status.archiveRoot, status.archive_root);
  const statusPath = firstNonEmpty(status.statusPath, status.status_path);
  const totalItems = toNumberValue(status.totalItems ?? status.total_items);
  const queuedCount = toNumberValue(status.queuedCount ?? status.queued_count);
  const runningCount = toNumberValue(status.runningCount ?? status.running_count);
  const succeededCount = toNumberValue(status.succeededCount ?? status.succeeded_count);
  const failedCount = toNumberValue(status.failedCount ?? status.failed_count);
  const skippedCount = toNumberValue(status.skippedCount ?? status.skipped_count);
  const completedCount = succeededCount + failedCount + skippedCount;
  const importedItems = Array.isArray(status.items) ? status.items : [];
  const items: BatchItemSnapshot[] = importedItems.map((item) => {
    const normalizedStatus = normalizeImportedItemStatus(toStringValue(item.status) || "queued");
    const token = firstNonEmpty(item.token);
    const accountKey = firstNonEmpty(item.accountKey, item.account_key);
    const sourceUrl = firstNonEmpty(item.sourceUrl, item.source_url);
    return {
      inputPath: sourceUrl,
      relativeInputPath: [accountKey, token].filter(Boolean).join("\\") || token || sourceUrl,
      outDir: firstNonEmpty(item.outDir, item.out_dir),
      status: normalizedStatus,
      phase: normalizeImportedItemPhase(normalizedStatus),
      step: normalizedStatus === "running" ? 1 : 0,
      totalSteps: normalizedStatus === "running" ? 1 : 0,
      message: firstNonEmpty(item.message),
      errorMessage: firstNonEmpty(item.errorMessage, item.error_message),
      startedAt: firstNonEmpty(item.startedAt, item.started_at),
      endedAt: firstNonEmpty(item.endedAt, item.ended_at),
    };
  });
  const runningItem = items.find((item) => item.status === "running") || null;
  const currentPhase: ProcessPhase | "" = runningItem ? "write_outputs" : "";
  const snapshotStatus = normalizeImportedSnapshotStatus(toStringValue(status.status), runningCount, queuedCount);

  return {
    inputRoot: deriveDiscoveryRoot(manifestPath, archiveRoot),
    outRoot: archiveRoot,
    statusPath,
    status: snapshotStatus,
    startedAt: firstNonEmpty(status.startedAt, status.started_at),
    endedAt: firstNonEmpty(status.endedAt, status.ended_at),
    totalItems,
    queuedCount,
    runningCount,
    succeededCount,
    failedCount,
    skippedCount,
    cancelledCount: 0,
    completedCount,
    progressRatio: totalItems > 0 ? completedCount / totalItems : 0,
    currentFile: runningItem?.inputPath || "",
    currentPhase,
    items,
    pipeline: "archive-import",
    imported: true,
  };
}

export function buildPendingProcessItemFromArchiveBundle(bundle: ArchiveBundleLike) {
  const token = firstNonEmpty(bundle.token);
  const archiveStatus = firstNonEmpty(bundle.archiveStatus, bundle.archive_status);
  const failed = archiveStatus === "failed";
  const outDir = firstNonEmpty(bundle.outDir, bundle.out_dir);
  const accountName = firstNonEmpty(bundle.accountKey, bundle.account_key);
  const message = firstNonEmpty(
    bundle.errorMessage,
    bundle.error_message,
    bundle.message,
    failed ? "归档失败，待修复后再处理" : "已归档，待处理",
  );
  const updatedAt = firstNonEmpty(bundle.archivedAt, bundle.archived_at);

  return {
    articleId: token,
    token,
    title: firstNonEmpty(bundle.title, token),
    accountName,
    sourceUrl: firstNonEmpty(bundle.sourceUrl, bundle.source_url),
    inputPath: firstNonEmpty(bundle.sourceUrl, bundle.source_url),
    relativeInputPath: [accountName, token].filter(Boolean).join("\\") || token,
    outDir,
    status: failed ? "failed" : "not-run",
    phase: failed ? "failed" : "not-run",
    qualityStatus: failed ? "error" : "missing",
    sidecarStatus: "missing",
    llmInputStatus: "missing",
    downstreamStatus: "not-run",
    warningCount: failed ? 1 : 0,
    warnings: [],
    errorMessage: failed ? message : "",
    message,
    startedAt: "",
    endedAt: updatedAt,
    updatedAt,
    files: {},
  };
}
