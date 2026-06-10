function readString(value) {
  if (typeof value === "string") {
    return value.trim();
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim();
}

function readNumber(...values) {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }
  return 0;
}

export const DEFAULT_BACKGROUND_LOCK_REASON = "后台下载运行中，控制类操作已锁定";

export function formatBackgroundDownloadLockReason({
  status,
  statusText,
  runningCount,
  running_count,
  queuedCount,
  queued_count,
} = {}) {
  const normalizedStatus = readString(statusText || status) || "-";
  const normalizedRunningCount = readNumber(runningCount, running_count);
  const normalizedQueuedCount = readNumber(queuedCount, queued_count);
  return `${DEFAULT_BACKGROUND_LOCK_REASON}: status=${normalizedStatus} running=${normalizedRunningCount} queued=${normalizedQueuedCount}`;
}

export function getBackgroundDownloadLockReason(lock) {
  if (!lock?.isRunning) {
    return "";
  }
  return readString(lock.lockReason) || formatBackgroundDownloadLockReason(lock);
}

export function buildBackgroundDownloadLock(status) {
  if (!status) {
    return {
      isRunning: false,
      lockReason: "",
      message: "未检测到后台下载状态文件",
      runningCount: 0,
      queuedCount: 0,
      currentItem: "",
      lastUpdated: "",
    };
  }

  const statusText = readString(status.status);
  const runningCount = readNumber(status.running_count, status.runningCount);
  const queuedCount = readNumber(status.queued_count, status.queuedCount);
  const currentItem = readString(status.current_item || status.currentItem);
  const lastUpdated = readString(status.last_updated || status.lastUpdated);
  const isRunning = statusText === "running" || runningCount > 0 || queuedCount > 0;
  const lockReason = isRunning
    ? formatBackgroundDownloadLockReason({ statusText, runningCount, queuedCount })
    : "";

  return {
    isRunning,
    lockReason,
    message: isRunning
      ? `后台下载正在运行（${runningCount} 运行中 / ${queuedCount} 排队中）`
      : "后台下载未在运行",
    runningCount,
    queuedCount,
    currentItem,
    lastUpdated,
  };
}
