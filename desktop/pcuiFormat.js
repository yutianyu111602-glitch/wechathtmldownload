export function parseDate(value) {
  const parsed = Date.parse(value || "");
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function toDisplayText(value, fallback = "-") {
  if (value === null || value === undefined) {
    return fallback;
  }
  const text = String(value).trim();
  return text || fallback;
}

export function formatNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number.toLocaleString("en-US") : "0";
}

export function formatCompactNumber(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) {
    return "-";
  }
  if (number >= 1000000) {
    return `${(number / 1000000).toFixed(1)}M`;
  }
  if (number >= 1000) {
    return `${(number / 1000).toFixed(1)}k`;
  }
  return String(number);
}

export function formatShortDateTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatClockTime(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function formatDuration(startedAt, endedAt) {
  const start = parseDate(startedAt);
  const end = parseDate(endedAt) || Date.now();
  if (!start || end < start) {
    return "-";
  }
  const totalSeconds = Math.floor((end - start) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const hours = Math.floor(minutes / 60);
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function shortText(value, max = 34) {
  const text = toDisplayText(value);
  if (text === "-" || text.length <= max) {
    return text;
  }
  return `${text.slice(0, Math.max(1, max - 1))}…`;
}

export function formatCountSummary(snapshot) {
  return [
    `Running ${snapshot.runningCount || 0}`,
    `Queued ${snapshot.queuedCount || 0}`,
    `Failed ${snapshot.failedCount || 0}`,
    `Locked ${snapshot.lockedCount || 0}`,
  ].join(" | ");
}

export function formatMptextCountSummary(status) {
  return [
    `下载队列 ${status.queuedCount || 0}`,
    `运行 ${status.runningCount || 0}`,
    `暂缓 ${status.deferredCount || 0}`,
    `成功 ${status.succeededCount || 0}`,
    `失败 ${status.failedCount || 0}`,
  ].join(" | ");
}
