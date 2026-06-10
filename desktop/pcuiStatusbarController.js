import { formatStatusLabel } from "./pcuiContract.js";
import { formatShortDateTime } from "./pcuiFormat.js";

function toCount(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number : 0;
}

function toText(value, fallback = "-") {
  if (value === null || value === undefined) {
    return fallback;
  }
  const text = String(value).trim();
  return text || fallback;
}

function buildPresenceModel({ status = "idle", text } = {}) {
  return {
    presenceStatus: status,
    state: toText(text, formatStatusLabel(status)),
  };
}

function buildSnapshotModel(snapshot = {}) {
  const status = snapshot.status || "idle";
  const workerCount = snapshot.workerCount ?? snapshot.runningCount ?? 0;
  return {
    presenceStatus: status,
    state: formatStatusLabel(status),
    input: `Workers ${toCount(workerCount)}`,
    output: `Running ${toCount(snapshot.runningCount)} | Queued ${toCount(snapshot.queuedCount)}`,
    current: `Failed ${toCount(snapshot.failedCount)}`,
    progress: `Last snapshot ${formatShortDateTime(snapshot.updatedAt || snapshot.endedAt || snapshot.startedAt)}`,
  };
}

function buildRootSwitchedModel({ discoveryRoot, artifactRoot } = {}) {
  return {
    presenceStatus: "idle",
    state: "等待刷新",
    input: `Discovery ${toText(discoveryRoot)}`,
    output: `Artifact ${toText(artifactRoot)}`,
    current: "Current -",
    progress: "Waiting for refresh",
  };
}

function buildProjectionReadFailedModel({ workspace } = {}) {
  return {
    presenceStatus: "failed",
    state: "读取失败",
    input: `Workspace ${toText(workspace)}`,
    output: "旧行已清空",
    current: "Current -",
    progress: "Waiting for refresh",
  };
}

function buildInputRequiredModel({ inputRoot, outRoot } = {}) {
  return {
    presenceStatus: "failed",
    state: "失败",
    input: `输入: ${toText(inputRoot)}`,
    output: `输出: ${toText(outRoot)}`,
    current: "当前: -",
    progress: "等待输入目录和输出目录",
  };
}

function buildStartingModel({ inputRoot, outRoot } = {}) {
  return {
    presenceStatus: "starting",
    state: "启动中",
    input: `输入: ${toText(inputRoot)}`,
    output: `输出: ${toText(outRoot)}`,
    current: "当前: 等待首个项目启动",
    progress: "等待 snapshot",
  };
}

function buildMptextBackgroundModel({ status = {}, bgStatus = {} } = {}) {
  const running = Boolean(bgStatus?.isRunning || status?.runningCount);
  return {
    presenceStatus: running ? "running" : "idle",
    state: running ? "后台下载中" : "后台下载空闲",
    input: `下载队列 ${toCount(status.queuedCount)}`,
    output: `运行 ${toCount(status.runningCount)} | 成功 ${toCount(status.succeededCount)}`,
    current: `当前下载: ${toText(status.currentItem)}`,
    progress: `失败 ${toCount(status.failedCount)} | 暂缓 ${toCount(status.deferredCount)}`,
  };
}

export function buildPcuiStatusbarModel(kind, data = {}) {
  switch (kind) {
    case "presence":
      return buildPresenceModel(data);
    case "snapshot":
      return buildSnapshotModel(data.snapshot);
    case "root-switched":
      return buildRootSwitchedModel(data);
    case "projection-read-failed":
      return buildProjectionReadFailedModel(data);
    case "input-required":
      return buildInputRequiredModel(data);
    case "starting":
      return buildStartingModel(data);
    case "mptext-background":
      return buildMptextBackgroundModel(data);
    default:
      return buildPresenceModel({ status: data.status || kind || "idle", text: data.text });
  }
}

function setText(ref, value) {
  if (ref && value !== undefined) {
    ref.textContent = value;
  }
}

export function applyPcuiStatusbarModel({
  titlebarStateText,
  titlebarStateDot,
  statusbarState,
  statusbarInput,
  statusbarOutput,
  statusbarCurrent,
  statusbarProgress,
}, model) {
  if (!model) {
    return;
  }
  const presenceStatus = model.presenceStatus || "idle";
  const stateText = toText(model.state, formatStatusLabel(presenceStatus));
  setText(titlebarStateText, stateText);
  if (titlebarStateDot?.dataset) {
    titlebarStateDot.dataset.status = presenceStatus;
  }
  setText(statusbarState, stateText);
  setText(statusbarInput, model.input);
  setText(statusbarOutput, model.output);
  setText(statusbarCurrent, model.current);
  setText(statusbarProgress, model.progress);
}
