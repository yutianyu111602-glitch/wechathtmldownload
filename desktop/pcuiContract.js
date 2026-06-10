export const DEFAULT_DISCOVERY_ROOT = "D:\\rawwechat";
export const DEFAULT_ARCHIVE_ROOT = "D:\\rawwechat_archive";
export const DEFAULT_ARTIFACT_ROOT = "D:\\rawwechat_llm_artifacts";
export const DEFAULT_MARKDOWN_MIRROR_ROOT = "D:\\rawwechat_llm_md";
export const DEFAULT_IMPORTED_DISCOVERY_ROOT = "D:\\DDownload";
export const DEFAULT_IMPORTED_MPTEXT_ROOT = "D:\\DDownload\\_archive_mptext";

const STATUS_LABELS = Object.freeze({
  idle: "空闲",
  queued: "排队",
  waiting: "等待中",
  starting: "启动中",
  discovering: "发现中",
  listing: "发现中",
  archiving: "归档中",
  "downloading-assets": "资源下载中",
  processing: "处理中",
  exporting: "导出中",
  "downstream-running": "下游处理中",
  running: "运行中",
  cancelling: "停止中",
  cancelled: "已取消",
  completed: "已完成",
  succeeded: "已成功",
  success: "成功",
  failed: "失败",
  error: "错误",
  warning: "警告",
  skipped: "已跳过",
  deferred: "已暂缓",
  partial: "部分可用",
  archived: "已归档",
  downloaded: "已下载",
  missing: "缺失",
  pending: "待处理",
  waiting_batch: "等待批次",
  done: "已完成",
  unavailable: "不可用",
  unsafe_path: "路径风险",
  "not-run": "未运行",
  "cli-only": "CLI 可用",
  unknown: "未知",
  stale: "过期",
  ready: "就绪",
  "llm-ready": "LLM Ready",
  "provider-ready": "Provider Ready",
  "provider-missing": "Provider 缺失",
  "input-missing": "输入缺失",
  "mirror-stale": "Mirror 过期",
  "rate-limited": "限流",
  capturing: "捕获中",
  "assets-failed": "资源失败",
  incomplete: "不完整",
  finalized: "已定稿",
  "audit-failed": "审计失败",
  ok: "正常",
  review: "待审查",
  blocked: "阻塞",
  "keeper-owned": "Keeper 接管",
  parse_html: "解析 HTML",
  rule_extract: "规则提取",
  markitdown_convert: "MarkItDown 转换",
  markdown_clean: "清洗 Markdown",
  write_outputs: "写入输出",
  mirror_llm_md: "镜像 LLM Markdown",
});

function toText(value) {
  if (typeof value === "string") {
    return value.trim();
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function firstNonEmpty(...values) {
  for (const value of values) {
    const text = toText(value);
    if (text) {
      return text;
    }
  }
  return "";
}

function humanizeToken(value) {
  return toText(value)
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function joinPath(basePath, child) {
  const base = toText(basePath).replace(/[\\/]+$/, "");
  if (!base) {
    return child;
  }
  const separator = base.includes("\\") || !base.includes("/") ? "\\" : "/";
  return `${base}${separator}${child}`;
}

export function formatStatusLabel(status) {
  const key = toText(status).toLowerCase();
  return STATUS_LABELS[key] || humanizeToken(status);
}

export function formatPhaseLabel(phase) {
  const key = toText(phase).toLowerCase();
  return STATUS_LABELS[key] || humanizeToken(phase);
}

export function statusClass(status) {
  const key = toText(status).toLowerCase();
  if (["running", "starting", "discovering", "listing", "archiving", "downloading-assets", "processing", "exporting", "downstream-running", "capturing"].includes(key)) {
    return "status-running";
  }
  if (["completed", "succeeded", "success", "ready", "ok", "archived", "downloaded", "done", "llm-ready", "provider-ready", "finalized"].includes(key)) {
    return "status-success";
  }
  if (["failed", "cancelled", "error", "missing", "blocked", "unsafe_path", "unavailable", "provider-missing", "input-missing", "assets-failed", "audit-failed"].includes(key)) {
    return "status-error";
  }
  if (["partial", "skipped", "deferred", "warning", "stale", "cli-only", "not-run", "unknown", "review", "pending", "waiting_batch", "mirror-stale", "rate-limited", "incomplete"].includes(key)) {
    return "status-warning";
  }
  return "status-idle";
}

export function isArchiveWorkspaceRoot(filePath) {
  const normalized = toText(filePath).replace(/\//g, "\\").toLowerCase();
  return normalized.includes("\\rawwechat_archive") || normalized.includes("\\_archive_mptext");
}

export function resolveDiscoveryRoot({ inputPath = "", sourceRoot = "", fallback = DEFAULT_DISCOVERY_ROOT } = {}) {
  return firstNonEmpty(inputPath, sourceRoot, fallback);
}

export function resolveArchiveRoot({
  inputPath = "",
  sourceRoot = "",
  projectionRoot = "",
  finalPackArchiveRoot = "",
  fallback = DEFAULT_ARCHIVE_ROOT,
} = {}) {
  const explicitInput = toText(inputPath);
  if (isArchiveWorkspaceRoot(explicitInput)) {
    return explicitInput;
  }
  return firstNonEmpty(sourceRoot, projectionRoot, finalPackArchiveRoot, fallback);
}

export function resolveArtifactRoot({ outputPath = "", sourceRoot = "", fallback = DEFAULT_ARTIFACT_ROOT } = {}) {
  return firstNonEmpty(outputPath, sourceRoot, fallback);
}

export function buildReleaseRoot(artifactRoot) {
  return joinPath(firstNonEmpty(artifactRoot, DEFAULT_ARTIFACT_ROOT), "_release");
}

export function resolveReleaseRoot({ releaseRoot = "", artifactRoot = "", fallbackArtifactRoot = DEFAULT_ARTIFACT_ROOT } = {}) {
  return firstNonEmpty(releaseRoot) || buildReleaseRoot(firstNonEmpty(artifactRoot, fallbackArtifactRoot));
}

export function resolveMptextArchiveRoot({ archiveRoot = "", fallback = DEFAULT_IMPORTED_MPTEXT_ROOT } = {}) {
  const explicitArchiveRoot = toText(archiveRoot);
  if (explicitArchiveRoot.toLowerCase().includes("_archive_mptext")) {
    return explicitArchiveRoot;
  }
  return fallback;
}

export function getArtifactRowKey(item) {
  const explicitRowKey = firstNonEmpty(item?.rowKey, item?.row_id, item?.rowId, item?.source_artifact_dir);
  if (explicitRowKey) {
    return explicitRowKey;
  }
  const composite = [firstNonEmpty(item?.account), firstNonEmpty(item?.token)].filter(Boolean).join("/");
  return composite || firstNonEmpty(item?.token);
}

export function withArtifactRowKeys(rows) {
  return (Array.isArray(rows) ? rows : []).map((row) => ({
    ...row,
    rowKey: getArtifactRowKey(row),
  }));
}
