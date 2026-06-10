import { createPcuiKeyboardController } from "./pcuiKeyboardController.js";
import { createPcuiThemeController } from "./pcuiThemeController.js";
import { createPcuiPerfRecorder } from "./pcuiPerfMarks.js";

const perfRecorder = createPcuiPerfRecorder();

const inputPathValue = document.querySelector("[data-role='input-path']");
const outputPathValue = document.querySelector("[data-role='output-path']");
const resumeToggle = document.querySelector("[data-role='resume-toggle']");
const startButton = document.querySelector("[data-role='start-button']");
const stopButton = document.querySelector("[data-role='stop-button']");
const openOutputButton = document.querySelector("[data-role='open-output-button']");
const autoMdButton = document.querySelector("[data-role='auto-md-button']");
const activitySummary = document.querySelector("[data-role='activity-summary']");
const recentItems = document.querySelector("[data-role='recent-items']");
const collectSummary = document.querySelector("[data-role='collect-summary']");
const collectSummaryChip = document.querySelector("[data-role='collect-summary-chip']");
const collectItems = document.querySelector("[data-role='collect-items']");
const archiveSummary = document.querySelector("[data-role='archive-summary']");
const archiveSummaryChip = document.querySelector("[data-role='archive-summary-chip']");
const archiveItems = document.querySelector("[data-role='archive-items']");
const processSummary = document.querySelector("[data-role='process-summary']");
const processItems = document.querySelector("[data-role='process-items']");
const artifactSummary = document.querySelector("[data-role='artifact-summary']");
const artifactItems = document.querySelector("[data-role='artifact-items']");
const artifactSearch = document.querySelector("[data-role='artifact-search']");
const artifactFilterButtons = [...document.querySelectorAll("[data-role='artifact-filter']")];
const taskbusSearch = document.querySelector("[data-role='taskbus-search']");
const taskbusFilterButtons = [...document.querySelectorAll("[data-role='taskbus-filter']")];
const processSearch = document.querySelector("[data-role='process-search']");
const processFilterButtons = [...document.querySelectorAll("[data-role='process-filter']")];
const collectSearch = document.querySelector("[data-role='collect-search']");
const collectFilterButtons = [...document.querySelectorAll("[data-role='collect-filter']")];
const archiveSearch = document.querySelector("[data-role='archive-search']");
const archiveFilterButtons = [...document.querySelectorAll("[data-role='archive-filter']")];
const detailLabel1 = document.querySelector("[data-role='detail-label-1']");
const detailLabel2 = document.querySelector("[data-role='detail-label-2']");
const detailLabel3 = document.querySelector("[data-role='detail-label-3']");
const detailLabel4 = document.querySelector("[data-role='detail-label-4']");
const detailLabel5 = document.querySelector("[data-role='detail-label-5']");
const detailInputRoot = document.querySelector("[data-role='detail-input-root']");
const detailOutputRoot = document.querySelector("[data-role='detail-output-root']");
const detailOutDir = document.querySelector("[data-role='detail-out-dir']");
const detailCurrentStatus = document.querySelector("[data-role='detail-current-status']");
const detailCurrentMessage = document.querySelector("[data-role='detail-current-message']");
const inspectorSelectionTitle = document.querySelector("[data-role='inspector-selection-title']");
const inspectorSelectionSubtitle = document.querySelector("[data-role='inspector-selection-subtitle']");
const inspectorActionPrimary = document.querySelector("[data-role='inspector-action-primary']");
const inspectorActionSecondary = document.querySelector("[data-role='inspector-action-secondary']");
const inspectorActionTertiary = document.querySelector("[data-role='inspector-action-tertiary']");
const workspaceContextList = document.querySelector("[data-role='workspace-context-list']");
const failureSummary = document.querySelector("[data-role='failure-summary']");
const failureList = document.querySelector("[data-role='failure-list']");
const statusbarState = document.querySelector("[data-role='statusbar-state']");
const statusbarInput = document.querySelector("[data-role='statusbar-input']");
const statusbarOutput = document.querySelector("[data-role='statusbar-output']");
const statusbarCurrent = document.querySelector("[data-role='statusbar-current']");
const statusbarProgress = document.querySelector("[data-role='statusbar-progress']");
const titlebarStateText = document.querySelector("[data-role='titlebar-state-text']");
const titlebarStateDot = document.querySelector("[data-role='titlebar-state-dot']");
const workspaceTitle = document.querySelector("[data-role='workspace-title']");
const workspaceSubtitle = document.querySelector("[data-role='workspace-subtitle']");
const workspaceCounterSummary = document.querySelector("[data-role='workspace-counter-summary']");
const runConsoleSummary = document.querySelector("[data-role='run-console-summary']");
const runConsoleActivityList = document.querySelector("[data-role='run-console-activity-list']");
const runConsoleSystemList = document.querySelector("[data-role='run-console-system-list']");

const workspaceButtons = [...document.querySelectorAll(".nav-item[data-workspace]")];
const workspacePanels = [...document.querySelectorAll(".workspace-panel[data-workspace]")];
const consoleTabs = [...document.querySelectorAll(".console-tab[data-console]")];
const consolePanels = [...document.querySelectorAll(".console-panel[data-console]")];

let latestSnapshot = null;
let latestCollectState = null;
let latestArchiveState = null;
let isRunning = false;
let activeWorkspace = "task-bus";
let activeConsole = "activity";
let cancellationRequested = false;
let taskBusFilter = "all";
let taskBusSearchText = "";
let processFilter = "all";
let processSearchText = "";
let collectFilter = "all";
let collectSearchText = "";
let archiveFilter = "all";
let archiveSearchText = "";
let artifactFilter = "all";
let artifactSearchText = "";
let selectedArtifactKey = "";
let selectedTaskItemPath = "";
let selectedCollectFakeid = "";
let selectedArchiveToken = "";
let selectedProcessItemId = "";

const DEFAULT_DISCOVERY_ROOT = "D:\\rawwechat";
const DEFAULT_ARCHIVE_ROOT = "D:\\rawwechat_archive";
const DEFAULT_RAWWECHAT_LLM_ARTIFACT_OUTPUT = "D:\\rawwechat_llm_artifacts";
const DEFAULT_RAWWECHAT_LLM_MD_OUTPUT = "D:\\rawwechat_llm_md";

const WORKSPACE_META = {
  "task-bus": {
    title: "任务总线",
    subtitle: "实时批次、筛选、失败和日志的主工作区。",
    context: [
      "这里继续绑定现有 batch snapshot，不改业务协议。",
      "P2 已加入表格筛选、右侧动作区和底部日志视图。",
    ],
  },
  collect: {
    title: "采集与账号",
    subtitle: "账号对象、发现进度、queue 规模和异常诊断的桌面工作区。",
    context: [
      "主表按账号对象组织，不再是一排网页 badge。",
      "支持按状态、异常、queue 非零筛选和搜索。",
      "诊断细节进右侧 inspector，不进主表。",
    ],
  },
  archive: {
    title: "归档与下载",
    subtitle: "bundle 完整度、capture 状态、assets 保留和异常诊断的桌面工作区。",
    context: [
      "主表按 bundle 组织，显示 capture / assets 完整度和异常码。",
      "支持按不完整、冲突筛选和搜索。",
      "文件矩阵和冲突诊断进右侧 inspector。",
    ],
  },
  process: {
    title: "处理与导出",
    subtitle: "按文章 bundle 查看 dual-track、导出与 downstream 状态的文章级工作台。",
    context: [
      "主表行对象是 article bundle，不是 job 或 run。",
      "当前使用 batch snapshot 数据做结构展示，真实 article bundle 数据源待业务层接入。",
    ],
  },
  artifact: {
    title: "产物与审查",
    subtitle: "后续用于 sidecar、llm_input 与质量抽查。",
    context: [
      "本轮只保留桌面壳骨架，不假装已经接入结果审查数据。",
      "旧 artifacts tab 不会再回来了。",
    ],
  },
};

function humanizeToken(value) {
  return String(value || "")
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatStatusLabel(status) {
  const labels = {
    idle: "空闲",
    starting: "启动中",
    running: "运行中",
    cancelling: "停止中",
    cancelled: "已取消",
    completed: "已完成",
    failed: "失败",
    queued: "排队",
    skipped: "已跳过",
    partial: "部分可用",
    missing: "缺失",
    listing: "发现中",
    succeeded: "已成功",
    "not-run": "未运行",
    "cli-only": "CLI 可用",
    unknown: "未知",
    stale: "过期",
    ready: "就绪",
    ok: "正常",
    warning: "警告",
    error: "错误",
  };

  return labels[status] || humanizeToken(status);
}

function formatPhaseLabel(phase) {
  const labels = {
    idle: "空闲",
    queued: "排队",
    parse_html: "解析 HTML",
    rule_extract: "规则提取",
    markitdown_convert: "MarkItDown 转换",
    markdown_clean: "清洗 Markdown",
    write_outputs: "写入输出",
    mirror_llm_md: "镜像 LLM Markdown",
    succeeded: "已完成",
    failed: "失败",
    cancelled: "已取消",
    skipped: "已跳过",
  };

  return labels[phase] || humanizeToken(phase);
}

function parseDate(value) {
  const parsed = Date.parse(value || "");
  return Number.isNaN(parsed) ? 0 : parsed;
}

function detectCollectAnomalies(account) {
  const codes = [];
  if (!account.discoveredCount && account.status !== "listing") {
    codes.push("PREFETCH_MISSING");
  }
  if (account.enqueuedCount !== account.discoveredCount && account.discoveredCount > 0) {
    codes.push("QUEUE_MISMATCH");
  }
  if (account.status === "unknown" || !account.status) {
    codes.push("STATUS_SOURCE_FALLBACK");
  }
  return codes;
}

function detectArchiveAnomalies(item) {
  const codes = [];
  if (!item.captureComplete) {
    codes.push("CAPTURE_PARTIAL");
  }
  if (item.archiveStatus === "succeeded" && !item.captureComplete) {
    codes.push("CAPTURE_JSON_SCAN_CONFLICT");
  }
  if (!item.assetsComplete && item.captureComplete) {
    codes.push("ASSETS_LOCAL_MISSING");
  }
  if (item.assetsComplete && !item.imageCount && item.captureComplete) {
    codes.push("ASSET_STATUS_MISMATCH");
  }
  return codes;
}

function getHighestAnomalySeverity(codes) {
  const severe = ["CAPTURE_PARTIAL", "CAPTURE_JSON_SCAN_CONFLICT", "ASSETS_LOCAL_MISSING", "ASSET_STATUS_MISMATCH"];
  const warning = ["PREFETCH_MISSING", "QUEUE_MISMATCH"];
  const info = ["STATUS_SOURCE_FALLBACK"];
  
  if (codes.some(c => severe.includes(c))) return "error";
  if (codes.some(c => warning.includes(c))) return "warning";
  if (codes.some(c => info.includes(c))) return "idle";
  return null;
}

function formatAnomalyShort(codes) {
  if (!codes.length) return "-";
  const severity = getHighestAnomalySeverity(codes);
  const first = codes[0];
  if (codes.length > 1) {
    return `${first} +${codes.length - 1}`;
  }
  return first;
}

function statusClass(status) {
  if (["running", "starting", "listing"].includes(status)) {
    return "status-running";
  }
  if (["completed", "succeeded", "ready", "ok"].includes(status)) {
    return "status-success";
  }
  if (["failed", "cancelled", "error", "missing"].includes(status)) {
    return "status-error";
  }
  if (["partial", "skipped", "warning", "stale", "cli-only", "not-run", "unknown"].includes(status)) {
    return "status-warning";
  }
  return "status-idle";
}

function formatCountSummary(snapshot) {
  return [
    `队列 ${snapshot.queuedCount}`,
    `运行 ${snapshot.runningCount}`,
    `成功 ${snapshot.succeededCount}`,
    `失败 ${snapshot.failedCount}`,
  ].join(" | ");
}

function setPresence(status, text) {
  titlebarStateText.textContent = text;
  titlebarStateDot.dataset.status = status;
  statusbarState.textContent = text;
}

function inferDiscoveryRoot() {
  return inputPathValue.value.trim() || DEFAULT_DISCOVERY_ROOT;
}

function inferArchiveRoot() {
  const inputPath = inputPathValue.value.trim();
  const outputPath = outputPathValue.value.trim();
  if (inputPath.toLowerCase().includes("rawwechat_archive")) {
    return inputPath;
  }
  if (outputPath.toLowerCase().includes("rawwechat_archive")) {
    return outputPath;
  }
  return DEFAULT_ARCHIVE_ROOT;
}

function setWorkspace(workspace) {
  activeWorkspace = workspace;

  perfRecorder.measure("pcui.projection.apply", { workspace }, () => {
    // projection metadata update
  });

  perfRecorder.measure("pcui.workspace.table.render", { workspace }, () => {
    if (activeWorkspace === "task-bus" && latestSnapshot) {
      renderTaskBus(latestSnapshot);
    } else if (activeWorkspace === "process" && latestSnapshot) {
      renderProcessWorkspace(latestSnapshot);
    } else if (activeWorkspace === "artifact") {
      renderArtifactWorkspace();
    }
    if (latestSnapshot) {
      renderFailures(latestSnapshot);
      renderRunConsole(latestSnapshot);
    }
  });

  void refreshActiveWorkspace();
  updateInspector();
}

function setConsole(consoleName) {
  activeConsole = consoleName;
  for (const tab of consoleTabs) {
    tab.classList.toggle("is-active", tab.dataset.console === consoleName);
  }
  for (const panel of consolePanels) {
    const active = panel.dataset.console === consoleName;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  }
}

function getActiveTaskItem(snapshot) {
  if (!snapshot?.items?.length) {
    return null;
  }

  if (selectedTaskItemPath) {
    const selected = snapshot.items.find((item) => item.inputPath === selectedTaskItemPath);
    if (selected) {
      return selected;
    }
  }

  if (snapshot.currentFile) {
    const current = snapshot.items.find((item) => item.inputPath === snapshot.currentFile);
    if (current) {
      return current;
    }
  }

  const touched = [...snapshot.items]
    .filter((item) => item.status !== "queued")
    .sort((left, right) => {
      if (left.status === "running" && right.status !== "running") {
        return -1;
      }
      if (right.status === "running" && left.status !== "running") {
        return 1;
      }
      return parseDate(right.endedAt || right.startedAt) - parseDate(left.endedAt || left.startedAt);
    });

  return touched[0] || snapshot.items[0] || null;
}

function getSelectedCollectAccount() {
  if (!latestCollectState?.accounts?.length) {
    return null;
  }
  return latestCollectState.accounts.find((item) => item.fakeid === selectedCollectFakeid) || latestCollectState.accounts[0] || null;
}

function getSelectedArchiveItem() {
  if (!latestArchiveState?.items?.length) {
    return null;
  }
  return latestArchiveState.items.find((item) => item.token === selectedArchiveToken) || latestArchiveState.items[0] || null;
}

function getSelectedProcessItem() {
  if (!latestSnapshot?.items?.length) {
    return null;
  }
  return latestSnapshot.items.find((item) => {
    const articleId = item.relativeInputPath || item.inputPath || "";
    return articleId === selectedProcessItemId;
  }) || latestSnapshot.items[0] || null;
}

function buildRunStateText(snapshot) {
  if (!snapshot.totalItems) {
    return "请选择输入目录和输出目录后开始批处理。任务总线继续承接实时 run，采集与归档已转入独立工作区。";
  }

  if (snapshot.pipeline === "llm-export") {
    if (snapshot.status === "running") {
      if (snapshot.currentPhase === "mirror_llm_md") {
        return "正在把已生成的 llm_input.md 镜像成扁平 Markdown 文件树。";
      }
      return "正在运行 dual-track 批处理，并产出可喂 LLM 的结构化结果与 Markdown。";
    }

    if (snapshot.status === "completed") {
      return `LLM 导出已完成。结构化产物位于 ${snapshot.outRoot}，扁平 Markdown 位于 ${snapshot.mirrorRoot || DEFAULT_RAWWECHAT_LLM_MD_OUTPUT}。`;
    }
  }

  if (snapshot.status === "running") {
    return "批处理正在运行。停止操作会中断当前项目，并把仍在排队的项目标记为已取消。";
  }

  if (snapshot.status === "completed") {
    return `批处理已完成。成功 ${snapshot.succeededCount}，失败 ${snapshot.failedCount}，跳过 ${snapshot.skippedCount}。`;
  }

  if (snapshot.status === "cancelled") {
    return `批处理已取消。共有 ${snapshot.cancelledCount} 个项目被标记为取消。`;
  }

  return `当前批次状态：${formatStatusLabel(snapshot.status)}。`;
}

function buildActivitySummary(snapshot) {
  if (!snapshot.totalItems) {
    return "当前还没有批处理活动。";
  }
  if (snapshot.status === "running") {
    return `运行中 ${snapshot.runningCount}，已完成 ${snapshot.completedCount}，仍在排队 ${snapshot.queuedCount}。`;
  }
  if (snapshot.status === "cancelled") {
    return `批处理已停止。完成 ${snapshot.completedCount} 个项目，${snapshot.cancelledCount} 个项目被标记为取消。`;
  }
  if (snapshot.status === "completed") {
    return `批处理结束。成功 ${snapshot.succeededCount}，失败 ${snapshot.failedCount}，跳过 ${snapshot.skippedCount}。`;
  }
  return `当前快照状态：${formatStatusLabel(snapshot.status)}。`;
}

function taskBusItemMatches(item) {
  if (taskBusFilter === "running" && item.status !== "running") {
    return false;
  }
  if (taskBusFilter === "failed" && item.status !== "failed") {
    return false;
  }
  if (taskBusFilter === "done" && !["succeeded", "skipped", "completed"].includes(item.status)) {
    return false;
  }
  if (taskBusSearchText) {
    const haystack = [
      item.relativeInputPath,
      item.inputPath,
      item.message,
      item.errorMessage,
      item.phase,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(taskBusSearchText)) {
      return false;
    }
  }
  return true;
}

function processItemMatches(item) {
  if (processFilter === "failed" && item.status !== "failed") {
    return false;
  }
  if (processFilter === "missing") {
    const hasArtifacts = item.outDir && item.status === "succeeded";
    if (hasArtifacts) {
      return false;
    }
  }
  if (processSearchText) {
    const haystack = [
      item.relativeInputPath,
      item.inputPath,
      item.message,
      item.errorMessage,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(processSearchText)) {
      return false;
    }
  }
  return true;
}

function collectItemMatches(account) {
  const anomalies = detectCollectAnomalies(account);
  if (collectFilter === "failed" && !anomalies.length) {
    return false;
  }
  if (collectFilter === "ready" && !(account.enqueuedCount > 0)) {
    return false;
  }
  if (collectSearchText) {
    const haystack = [
      account.nickname,
      account.fakeid,
      account.status,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(collectSearchText)) {
      return false;
    }
  }
  return true;
}

function archiveItemMatches(item) {
  const anomalies = detectArchiveAnomalies(item);
  if (archiveFilter === "incomplete" && item.captureComplete && item.assetsComplete) {
    return false;
  }
  if (archiveFilter === "conflict" && !anomalies.some(c => c.includes("CONFLICT") || c.includes("MISMATCH"))) {
    return false;
  }
  if (archiveSearchText) {
    const haystack = [
      item.token,
      item.accountKey,
      item.archiveStatus,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(archiveSearchText)) {
      return false;
    }
  }
  return true;
}

function createStatusBadge(status) {
  const span = document.createElement("span");
  span.className = `item-status ${statusClass(status)}`;
  span.dataset.status = status || "idle";
  span.textContent = formatStatusLabel(status || "idle");
  return span;
}

function renderTaskBus(snapshot) {
  const items = [...snapshot.items]
    .filter(taskBusItemMatches)
    .sort((left, right) => {
      if (left.status === "running" && right.status !== "running") {
        return -1;
      }
      if (right.status === "running" && left.status !== "running") {
        return 1;
      }
      return parseDate(right.endedAt || right.startedAt) - parseDate(left.endedAt || left.startedAt);
    })
    .slice(0, 32);

  recentItems.innerHTML = "";
  if (!items.length) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = "当前筛选条件下没有任务。";
    recentItems.append(emptyItem);
    return;
  }

  const activeItem = getActiveTaskItem(snapshot);
  const fragment = document.createDocumentFragment();
  for (const item of items) {
    const row = document.createElement("li");
    row.className = "item-row";
    if (activeItem?.inputPath && activeItem.inputPath === item.inputPath) {
      row.classList.add("is-selected");
    }
    row.addEventListener("click", () => {
      selectedTaskItemPath = item.inputPath || "";
      updateInspector();
      renderTaskBus(snapshot);
      renderRunConsole(snapshot);
    });

    const file = document.createElement("span");
    file.className = "item-file";
    file.textContent = item.relativeInputPath || item.inputPath || "-";
    file.title = file.textContent;

    const phase = document.createElement("span");
    phase.className = "item-file";
    phase.textContent = formatPhaseLabel(item.phase || item.status || "queued");
    phase.title = phase.textContent;

    const message = document.createElement("span");
    message.className = "item-message";
    message.textContent = item.errorMessage || item.message || "-";
    message.title = message.textContent;

    row.append(createStatusBadge(item.status || "queued"), file, phase, message);
    fragment.append(row);
  }
  recentItems.append(fragment);
}

function renderCollectWorkspace(state) {
  collectSummary.textContent = `账号 ${state.summary.totalAccounts} | 已完成 ${state.summary.completedAccounts} | 已发现 ${state.summary.totalDiscovered} | Ready Queue ${state.summary.readyQueueCount}`;
  collectSummaryChip.textContent = `状态: ${formatStatusLabel(state.status)}`;
  collectItems.innerHTML = "";

  if (!state.accounts.length) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = state.warnings[0] || "当前没有可显示的账号状态。";
    collectItems.append(emptyItem);
    return;
  }

  if (!selectedCollectFakeid) {
    selectedCollectFakeid = state.accounts[0]?.fakeid || "";
  }

  const fragment = document.createDocumentFragment();
  for (const account of state.accounts.slice(0, 40)) {
    const row = document.createElement("li");
    row.className = "collect-row";
    if (account.fakeid === selectedCollectFakeid) {
      row.classList.add("is-selected");
    }
    row.addEventListener("click", () => {
      selectedCollectFakeid = account.fakeid;
      updateInspector();
      renderCollectWorkspace(state);
    });

    const title = document.createElement("div");
    title.innerHTML = `<div class="row-main">${account.nickname || account.fakeid}</div><div class="row-sub">${account.fakeid || "-"}</div>`;

    const discovered = document.createElement("span");
    discovered.className = "row-main";
    discovered.textContent = String(account.discoveredCount || 0);

    const enqueued = document.createElement("span");
    enqueued.className = "row-main";
    enqueued.textContent = String(account.enqueuedCount || 0);

    row.append(title, createStatusBadge(account.status || "missing"), discovered, enqueued);
    fragment.append(row);
  }
  collectItems.append(fragment);
}

function renderArchiveWorkspace(state) {
  archiveSummary.textContent = `Bundle ${state.summary.bundles.seen} | Capture 成功 ${state.summary.archive.succeededCount} | Assets 成功 ${state.summary.assets.succeededCount}`;
  archiveSummaryChip.textContent = `状态: ${formatStatusLabel(state.status)}`;
  archiveItems.innerHTML = "";

  if (!state.items.length) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = state.warnings[0] || "当前没有可显示的 bundle 状态。";
    archiveItems.append(emptyItem);
    return;
  }

  if (!selectedArchiveToken) {
    selectedArchiveToken = state.items[0]?.token || "";
  }

  const fragment = document.createDocumentFragment();
  for (const item of state.items.slice(0, 40)) {
    const row = document.createElement("li");
    row.className = "archive-row";
    if (item.token === selectedArchiveToken) {
      row.classList.add("is-selected");
    }
    row.addEventListener("click", () => {
      selectedArchiveToken = item.token;
      updateInspector();
      renderArchiveWorkspace(state);
    });

    const main = document.createElement("div");
    main.innerHTML = `<div class="row-main">${item.token}</div><div class="row-sub">${item.accountKey || "-"}</div>`;

    const capture = document.createElement("span");
    capture.className = `compact-status ${item.captureComplete ? "status-success" : "status-warning"}`;
    capture.textContent = item.captureComplete ? "完整" : "不完整";

    const assets = document.createElement("span");
    assets.className = `compact-status ${item.assetsComplete ? "status-success" : "status-idle"}`;
    assets.textContent = item.assetsComplete ? `图 ${item.imageCount}` : "缺失";

    row.append(createStatusBadge(item.archiveStatus || "missing"), main, capture, assets);
    fragment.append(row);
  }
  archiveItems.append(fragment);
}

function renderProcessWorkspace(snapshot) {
  processItems.innerHTML = "";

  if (!snapshot?.items?.length) {
    processSummary.textContent = "当前没有文章处理记录。";
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = "当前没有文章处理记录。在任务总线启动批处理后会显示在这里。";
    processItems.append(emptyItem);
    return;
  }

  const items = [...snapshot.items]
    .filter(processItemMatches)
    .sort((left, right) => {
      if (left.status === "running" && right.status !== "running") {
        return -1;
      }
      if (right.status === "running" && left.status !== "running") {
        return 1;
      }
      return parseDate(right.endedAt || right.startedAt) - parseDate(left.endedAt || left.startedAt);
    })
    .slice(0, 32);

  if (!items.length) {
    processSummary.textContent = "当前筛选条件下没有文章。";
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = "当前筛选条件下没有文章处理记录。";
    processItems.append(emptyItem);
    return;
  }

  processSummary.textContent = `显示 ${items.length} / ${snapshot.items.length} 篇文章`;

  if (!selectedProcessItemId) {
    selectedProcessItemId = items[0]?.relativeInputPath || items[0]?.inputPath || "";
  }

  const fragment = document.createDocumentFragment();
  for (const item of items) {
    const row = document.createElement("li");
    row.className = "process-row";
    const itemId = item.relativeInputPath || item.inputPath || "";
    if (itemId === selectedProcessItemId) {
      row.classList.add("is-selected");
    }
    row.addEventListener("click", () => {
      selectedProcessItemId = itemId;
      updateInspector();
      renderProcessWorkspace(snapshot);
    });

    const articleId = document.createElement("span");
    articleId.className = "row-main";
    articleId.textContent = item.relativeInputPath || item.inputPath || "-";
    articleId.title = articleId.textContent;

    const account = document.createElement("span");
    account.className = "row-sub";
    account.textContent = "-";

    const phase = document.createElement("span");
    phase.className = "row-main";
    phase.textContent = formatPhaseLabel(item.phase || item.status || "queued");

    const quality = document.createElement("span");
    quality.className = `compact-status ${statusClass(item.status === "succeeded" ? "ok" : item.status === "failed" ? "error" : "unknown")}`;
    quality.textContent = formatStatusLabel(item.status === "succeeded" ? "ok" : item.status === "failed" ? "error" : "unknown");

    const sidecar = document.createElement("span");
    sidecar.className = `compact-status ${item.status === "succeeded" ? "status-success" : "status-idle"}`;
    sidecar.textContent = item.status === "succeeded" ? "ready" : "missing";

    const llmInput = document.createElement("span");
    llmInput.className = `compact-status ${item.status === "succeeded" ? "status-success" : "status-idle"}`;
    llmInput.textContent = item.status === "succeeded" ? "ready" : "missing";

    const downstream = document.createElement("span");
    downstream.className = "compact-status status-warning";
    downstream.textContent = "cli-only";

    const warnings = document.createElement("span");
    warnings.className = "row-sub";
    warnings.textContent = item.errorMessage ? "1" : "-";

    row.append(
      createStatusBadge(item.status || "queued"),
      articleId,
      account,
      phase,
      quality,
      sidecar,
      llmInput,
      downstream,
      warnings
    );
    fragment.append(row);
  }
  processItems.append(fragment);
}

function renderArtifactWorkspace() {
  artifactItems.innerHTML = "";

  const artifacts = [];
  if (latestSnapshot?.items) {
    for (const item of latestSnapshot.items) {
      if (item.status === "succeeded") {
        artifacts.push({ type: "sidecar", key: `${item.relativeInputPath || item.inputPath}-sidecar`, label: item.relativeInputPath || item.inputPath || "-", status: "ready" });
        artifacts.push({ type: "llm-input", key: `${item.relativeInputPath || item.inputPath}-llm`, label: `${item.relativeInputPath || item.inputPath || "-"} (LLM)`, status: "ready" });
      }
    }
  }

  const filtered = artifacts.filter((artifact) => {
    if (artifactFilter !== "all" && artifact.type !== artifactFilter) {
      return false;
    }
    if (artifactSearchText && !artifact.label.toLowerCase().includes(artifactSearchText)) {
      return false;
    }
    return true;
  });

  if (!filtered.length) {
    artifactSummary.textContent = "当前没有产物记录。";
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = artifactFilter !== "all" || artifactSearchText
      ? "当前筛选条件下没有产物。"
      : "当前没有产物记录。在任务总线启动批处理后会显示在这里。";
    artifactItems.append(emptyItem);
    return;
  }

  artifactSummary.textContent = `显示 ${filtered.length} 个产物`;
  const fragment = document.createDocumentFragment();
  for (const artifact of filtered.slice(0, 40)) {
    const row = document.createElement("li");
    row.className = "item-row";
    if (artifact.key === selectedArtifactKey) {
      row.classList.add("is-selected");
    }
    row.addEventListener("click", () => {
      selectedArtifactKey = artifact.key;
      updateInspector();
      renderArtifactWorkspace();
    });

    const type = document.createElement("span");
    type.className = "compact-status status-success";
    type.textContent = artifact.type === "sidecar" ? "Sidecar" : "LLM Input";

    const label = document.createElement("span");
    label.className = "item-file";
    label.textContent = artifact.label;
    label.title = label.textContent;

    const status = document.createElement("span");
    status.className = "compact-status status-success";
    status.textContent = artifact.status;

    const quality = document.createElement("span");
    quality.className = "row-sub";
    quality.textContent = "ok";

    row.append(type, label, status, quality);
    fragment.append(row);
  }
  artifactItems.append(fragment);
}

function renderFailures(snapshot) {
  const failedItems = snapshot.items
    .filter((item) => item.status === "failed")
    .slice(-8)
    .reverse();

  failureList.innerHTML = "";
  if (failedItems.length === 0) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = "当前快照里没有失败项目。";
    failureList.append(emptyItem);
    failureSummary.textContent = snapshot.status === "cancelled"
      ? "已取消批次会把最终项目状态直接写入 batch-status.json。"
      : "当前快照里没有失败项目。";
    return;
  }

  failureSummary.textContent = `显示最近 ${failedItems.length} 个失败项目。`;
  for (const item of failedItems) {
    const row = document.createElement("li");
    const title = document.createElement("strong");
    title.className = "console-item-title";
    title.textContent = item.relativeInputPath || item.inputPath || "未命名项目";
    const copy = document.createElement("span");
    copy.className = "console-item-copy";
    copy.textContent = item.errorMessage || item.message || "失败，但没有显式错误消息。";
    row.append(title, copy);
    failureList.append(row);
  }
}

function renderRunConsole(snapshot) {
  const activeItem = getActiveTaskItem(snapshot);
  const items = [...snapshot.items]
    .filter((item) => item.status !== "queued")
    .sort((left, right) => parseDate(right.endedAt || right.startedAt) - parseDate(left.endedAt || left.startedAt))
    .slice(0, 10);

  runConsoleActivityList.innerHTML = "";
  if (!items.length) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "empty-state";
    emptyItem.textContent = "当前没有活动记录。";
    runConsoleActivityList.append(emptyItem);
  } else {
    for (const item of items) {
      const row = document.createElement("li");
      const title = document.createElement("strong");
      title.className = "console-item-title";
      title.textContent = `${formatStatusLabel(item.status || "queued")} · ${item.relativeInputPath || item.inputPath || "-"}`;
      const copy = document.createElement("span");
      copy.className = "console-item-copy";
      copy.textContent = item.errorMessage || item.message || formatPhaseLabel(item.phase || item.status || "queued");
      row.append(title, copy);
      runConsoleActivityList.append(row);
    }
  }

  runConsoleSystemList.innerHTML = "";
  const systemEntries = [
    `批次状态：${formatStatusLabel(snapshot.status || "idle")}`,
    `工作流：${snapshot.pipeline || "dual-track"}`,
    `输入目录：${snapshot.inputRoot || "-"}`,
    `输出目录：${snapshot.outRoot || "-"}`,
    `当前对象：${activeItem?.relativeInputPath || snapshot.currentFile || "-"}`,
  ];
  for (const entry of systemEntries) {
    const row = document.createElement("li");
    row.textContent = entry;
    runConsoleSystemList.append(row);
  }

  runConsoleSummary.textContent = activeItem
    ? `当前对象：${activeItem.relativeInputPath || activeItem.inputPath || "-"} · ${formatPhaseLabel(activeItem.phase || snapshot.currentPhase || "idle")}`
    : buildRunStateText(snapshot);
}

function updateInspector() {
  perfRecorder.measure("pcui.virtual-list.update", { workspace: activeWorkspace }, () => {
    updateInspectorContent();
  });
}

function updateInspectorContent() {
  if (activeWorkspace === "task-bus" && latestSnapshot) {
    const activeItem = getActiveTaskItem(latestSnapshot);
    inspectorSelectionTitle.textContent = activeItem?.relativeInputPath || latestSnapshot.currentFile || "当前没有活动对象。";
    inspectorSelectionSubtitle.textContent = buildRunStateText(latestSnapshot);
    detailLabel1.textContent = "输入根目录";
    detailLabel2.textContent = "输出根目录";
    detailLabel3.textContent = "当前输出目录";
    detailLabel4.textContent = "当前状态";
    detailLabel5.textContent = "当前消息";
    detailInputRoot.textContent = latestSnapshot.inputRoot || "-";
    detailOutputRoot.textContent = latestSnapshot.outRoot || "-";
    detailOutDir.textContent = activeItem?.outDir || "-";
    detailCurrentStatus.textContent = `${formatStatusLabel(latestSnapshot.status || "idle")} / ${formatPhaseLabel(latestSnapshot.currentPhase || activeItem?.phase || "idle")}`;
    detailCurrentMessage.textContent = activeItem?.errorMessage || activeItem?.message || buildRunStateText(latestSnapshot);
    inspectorActionPrimary.textContent = activeItem?.outDir ? "打开当前输出目录" : "打开输出根目录";
    inspectorActionSecondary.textContent = "刷新任务总线";
    inspectorActionTertiary.textContent = "切到失败流";
    return;
  }

  if (activeWorkspace === "collect") {
    const selected = getSelectedCollectAccount();
    inspectorSelectionTitle.textContent = selected?.nickname || "当前没有账号对象。";
    inspectorSelectionSubtitle.textContent = latestCollectState
      ? `采集状态：${formatStatusLabel(latestCollectState.status)} · Ready Queue ${latestCollectState.summary.readyQueueCount}`
      : "等待读取 discovery 状态。";
    detailLabel1.textContent = "Discovery 根目录";
    detailLabel2.textContent = "Prefetch 状态";
    detailLabel3.textContent = "Ready Queue";
    detailLabel4.textContent = "账号状态";
    detailLabel5.textContent = "账号摘要";
    detailInputRoot.textContent = latestCollectState?.sources?.rootDir?.path || inferDiscoveryRoot();
    detailOutputRoot.textContent = latestCollectState?.sources?.prefetchStatusPath?.path || "-";
    detailOutDir.textContent = latestCollectState?.sources?.queuePath?.path || "-";
    detailCurrentStatus.textContent = selected ? formatStatusLabel(selected.status) : formatStatusLabel(latestCollectState?.status || "missing");
    detailCurrentMessage.textContent = selected
      ? `已发现 ${selected.discoveredCount} / 入队 ${selected.enqueuedCount} / 重复 ${selected.duplicateCount}`
      : (latestCollectState?.warnings?.[0] || "等待读取本地 discovery 状态。");
    inspectorActionPrimary.textContent = "打开 discovery 根目录";
    inspectorActionSecondary.textContent = "刷新采集状态";
    inspectorActionTertiary.textContent = "切到系统消息";
    return;
  }

  if (activeWorkspace === "archive") {
    const selected = getSelectedArchiveItem();
    inspectorSelectionTitle.textContent = selected?.token || "当前没有 bundle 对象。";
    inspectorSelectionSubtitle.textContent = latestArchiveState
      ? `归档状态：${formatStatusLabel(latestArchiveState.status)} · Bundle ${latestArchiveState.summary.bundles.seen}`
      : "等待读取 archive 状态。";
    detailLabel1.textContent = "Archive Root";
    detailLabel2.textContent = "Archive Status";
    detailLabel3.textContent = "Bundle 目录";
    detailLabel4.textContent = "Capture / Assets";
    detailLabel5.textContent = "当前消息";
    detailInputRoot.textContent = latestArchiveState?.sources?.archiveRoot?.path || inferArchiveRoot();
    detailOutputRoot.textContent = latestArchiveState?.sources?.archiveStatusPath?.path || "-";
    detailOutDir.textContent = selected?.outDir || "-";
    detailCurrentStatus.textContent = selected
      ? `${formatStatusLabel(selected.archiveStatus)} / ${selected.captureComplete ? "Capture 完整" : "Capture 不完整"}`
      : formatStatusLabel(latestArchiveState?.status || "missing");
    detailCurrentMessage.textContent = selected
      ? `Assets: ${selected.assetsComplete ? `图 ${selected.imageCount} / 媒体 ${selected.mediaCount}` : "未落 assets_local.json"}`
      : (latestArchiveState?.warnings?.[0] || "等待读取本地 archive 状态。");
    inspectorActionPrimary.textContent = selected?.outDir ? "打开 bundle 目录" : "打开 archive 根目录";
    inspectorActionSecondary.textContent = "刷新归档状态";
    inspectorActionTertiary.textContent = "切到系统消息";
    return;
  }

  if (activeWorkspace === "process") {
    const selected = getSelectedProcessItem();
    inspectorSelectionTitle.textContent = selected?.relativeInputPath || selected?.inputPath || "当前没有文章对象。";
    inspectorSelectionSubtitle.textContent = latestSnapshot
      ? `处理状态：${formatStatusLabel(latestSnapshot.status)} · 共 ${latestSnapshot.items?.length || 0} 篇文章`
      : "等待批处理数据。";
    detailLabel1.textContent = "Article ID";
    detailLabel2.textContent = "当前阶段";
    detailLabel3.textContent = "输出目录";
    detailLabel4.textContent = "Sidecar 状态";
    detailLabel5.textContent = "LLM Input 状态";
    detailInputRoot.textContent = selected?.relativeInputPath || selected?.inputPath || "-";
    detailOutputRoot.textContent = formatPhaseLabel(selected?.phase || selected?.status || "idle");
    detailOutDir.textContent = selected?.outDir || "-";
    detailCurrentStatus.textContent = selected?.status === "succeeded" ? "ready" : (selected?.status || "missing");
    detailCurrentMessage.textContent = selected
      ? `Quality: ${selected.status === "succeeded" ? "ok" : selected.status === "failed" ? "fail" : "unknown"} · Downstream: cli-only`
      : "在任务总线启动批处理后，这里会显示文章级处理详情。";
    inspectorActionPrimary.textContent = selected?.outDir ? "打开 bundle 目录" : "打开输出根目录";
    inspectorActionSecondary.textContent = "刷新处理状态";
    inspectorActionTertiary.textContent = "切到系统消息";
    return;
  }

  inspectorSelectionTitle.textContent = WORKSPACE_META[activeWorkspace].title;
  inspectorSelectionSubtitle.textContent = WORKSPACE_META[activeWorkspace].subtitle;
  detailLabel1.textContent = "说明 1";
  detailLabel2.textContent = "说明 2";
  detailLabel3.textContent = "说明 3";
  detailLabel4.textContent = "当前状态";
  detailLabel5.textContent = "当前消息";
  detailInputRoot.textContent = "-";
  detailOutputRoot.textContent = "-";
  detailOutDir.textContent = "-";
  detailCurrentStatus.textContent = "规划中";
  detailCurrentMessage.textContent = "该工作区保留桌面壳骨架，后续再接真实对象。";
  inspectorActionPrimary.textContent = "打开输出目录";
  inspectorActionSecondary.textContent = "刷新当前工作区";
  inspectorActionTertiary.textContent = "切到活动流";
}

async function refreshCollectWorkspace() {
  try {
    latestCollectState = await window.wechatDesktop.getCollectState({
      rootDir: inferDiscoveryRoot(),
    });
    if (!selectedCollectFakeid && latestCollectState.accounts?.length) {
      selectedCollectFakeid = latestCollectState.accounts[0].fakeid;
    }
    renderCollectWorkspace(latestCollectState);
  } catch (err) {
    console.warn("Failed to refresh collect workspace:", err);
  }
}

async function refreshArchiveWorkspace() {
  try {
    latestArchiveState = await window.wechatDesktop.getArchiveState({
      archiveRoot: inferArchiveRoot(),
    });
    if (!selectedArchiveToken && latestArchiveState.items?.length) {
      selectedArchiveToken = latestArchiveState.items[0].token;
    }
    renderArchiveWorkspace(latestArchiveState);
  } catch (err) {
    console.warn("Failed to refresh archive workspace:", err);
  }
}

async function refreshActiveWorkspace() {
  if (activeWorkspace === "collect") {
    await refreshCollectWorkspace();
  }
  if (activeWorkspace === "archive") {
    await refreshArchiveWorkspace();
  }
  if (activeWorkspace === "process" && latestSnapshot) {
    renderProcessWorkspace(latestSnapshot);
  }
  updateInspector();
}

async function startBatchRun(payload, startingMessage) {
  if (isRunning) {
    return;
  }

  const inputRoot = (payload.inputRoot || "").trim();
  const outRoot = (payload.outRoot || "").trim();
  if (!inputRoot || !outRoot) {
    setPresence("failed", "失败");
    detailCurrentMessage.textContent = "输入目录和输出目录都必须填写。";
    statusbarInput.textContent = `输入: ${inputRoot || "-"}`;
    statusbarOutput.textContent = `输出: ${outRoot || "-"}`;
    return;
  }

  startButton.disabled = true;
  autoMdButton.disabled = true;
  stopButton.disabled = false;
  isRunning = true;
  setPresence("starting", "启动中");
  detailCurrentStatus.textContent = "启动中 / 等待首个阶段";
  detailCurrentMessage.textContent = startingMessage;
  statusbarInput.textContent = `输入: ${inputRoot}`;
  statusbarOutput.textContent = `输出: ${outRoot}`;
  statusbarCurrent.textContent = "当前: 等待首个项目启动";

  const result = await window.wechatDesktop.startBatch(payload);
  if (!result.accepted) {
    isRunning = false;
    startButton.disabled = false;
    autoMdButton.disabled = false;
    stopButton.disabled = true;
    setPresence("failed", "失败");
    detailCurrentMessage.textContent = result.message || "启动批处理失败。";
  }
}

function renderSnapshot(snapshot) {
  latestSnapshot = snapshot;
  const activeItem = getActiveTaskItem(snapshot);
  cancellationRequested = false;

  perfRecorder.measure("pcui.projection.apply", { workspace: activeWorkspace }, () => {
    setPresence(snapshot.status || "idle", formatStatusLabel(snapshot.status || "idle"));
    workspaceCounterSummary.textContent = activeWorkspace === "task-bus"
      ? formatCountSummary(snapshot)
      : workspaceCounterSummary.textContent;
    activitySummary.textContent = buildActivitySummary(snapshot);
    statusbarInput.textContent = `输入: ${snapshot.inputRoot || "-"}`;
    statusbarOutput.textContent = `输出: ${snapshot.outRoot || "-"}`;
    statusbarCurrent.textContent = `当前: ${activeItem?.relativeInputPath || snapshot.currentFile || "-"}`;
    statusbarProgress.textContent = `${snapshot.completedCount}/${snapshot.totalItems} 已完成`;
  });

  perfRecorder.measure("pcui.workspace.table.render", { workspace: activeWorkspace }, () => {
    renderTaskBus(snapshot);
    if (activeWorkspace === "process") {
      renderProcessWorkspace(snapshot);
    } else if (activeWorkspace === "artifact") {
      renderArtifactWorkspace();
    }
    renderFailures(snapshot);
    renderRunConsole(snapshot);
  });

  perfRecorder.measure("pcui.virtual-list.update", { workspace: activeWorkspace }, () => {
    updateInspector();
  });

  if (snapshot.status === "running") {
    isRunning = true;
    startButton.disabled = true;
    autoMdButton.disabled = true;
    stopButton.disabled = false;
  }

  if (["completed", "cancelled", "failed"].includes(snapshot.status)) {
    isRunning = false;
    cancellationRequested = false;
    startButton.disabled = false;
    autoMdButton.disabled = false;
    stopButton.disabled = true;
  }
}

async function pickDirectory(target) {
  const chosen = await window.wechatDesktop.pickDirectory(target.value);
  if (chosen) {
    target.value = chosen;
    if (activeWorkspace === "collect" || activeWorkspace === "archive") {
      await refreshActiveWorkspace();
    }
  }
}

function openSelectedTarget() {
  if (activeWorkspace === "task-bus") {
    const activeItem = latestSnapshot ? getActiveTaskItem(latestSnapshot) : null;
    const targetPath = activeItem?.outDir || latestSnapshot?.outRoot || outputPathValue.value.trim();
    if (targetPath) {
      window.wechatDesktop.openPath(targetPath);
    }
    return;
  }

  if (activeWorkspace === "collect") {
    const targetPath = latestCollectState?.sources?.rootDir?.path || inferDiscoveryRoot();
    if (targetPath) {
      window.wechatDesktop.openPath(targetPath);
    }
    return;
  }

  if (activeWorkspace === "archive") {
    const selected = getSelectedArchiveItem();
    const targetPath = selected?.outDir || latestArchiveState?.sources?.archiveRoot?.path || inferArchiveRoot();
    if (targetPath) {
      window.wechatDesktop.openPath(targetPath);
    }
    return;
  }

  if (activeWorkspace === "process") {
    const selected = getSelectedProcessItem();
    const targetPath = selected?.outDir || latestSnapshot?.outRoot || outputPathValue.value.trim();
    if (targetPath) {
      window.wechatDesktop.openPath(targetPath);
    }
    return;
  }

  if (outputPathValue.value.trim()) {
    window.wechatDesktop.openPath(outputPathValue.value.trim());
  }
}

async function refreshCurrentWorkspace() {
  await refreshActiveWorkspace();
}

function openWorkspaceTertiaryAction() {
  if (activeWorkspace === "task-bus") {
    setConsole("failures");
    return;
  }
  setConsole("system");
}

document.querySelector("[data-role='pick-input']").addEventListener("click", () => {
  void pickDirectory(inputPathValue);
});

document.querySelector("[data-role='pick-output']").addEventListener("click", () => {
  void pickDirectory(outputPathValue);
});

for (const button of workspaceButtons) {
  button.addEventListener("click", () => {
    setWorkspace(button.dataset.workspace);
  });
}

for (const tab of consoleTabs) {
  tab.addEventListener("click", () => {
    setConsole(tab.dataset.console);
  });
}

for (const button of taskbusFilterButtons) {
  button.addEventListener("click", () => {
    taskBusFilter = button.dataset.filter || "all";
    for (const candidate of taskbusFilterButtons) {
      candidate.classList.toggle("is-active", candidate === button);
    }
    if (latestSnapshot) {
      renderTaskBus(latestSnapshot);
    }
  });
}

for (const button of processFilterButtons) {
  button.addEventListener("click", () => {
    processFilter = button.dataset.filter || "all";
    for (const candidate of processFilterButtons) {
      candidate.classList.toggle("is-active", candidate === button);
    }
    if (latestSnapshot) {
      renderProcessWorkspace(latestSnapshot);
    }
  });
}

taskbusSearch.addEventListener("input", () => {
  taskBusSearchText = taskbusSearch.value.trim().toLowerCase();
  if (latestSnapshot) {
    renderTaskBus(latestSnapshot);
  }
});

processSearch.addEventListener("input", () => {
  processSearchText = processSearch.value.trim().toLowerCase();
  if (latestSnapshot) {
    renderProcessWorkspace(latestSnapshot);
  }
});

for (const button of artifactFilterButtons) {
  button.addEventListener("click", () => {
    artifactFilter = button.dataset.filter || "all";
    for (const candidate of artifactFilterButtons) {
      candidate.classList.toggle("is-active", candidate === button);
    }
    renderArtifactWorkspace();
  });
}

artifactSearch.addEventListener("input", () => {
  artifactSearchText = artifactSearch.value.trim().toLowerCase();
  renderArtifactWorkspace();
});

openOutputButton.addEventListener("click", () => {
  if (outputPathValue.value.trim()) {
    window.wechatDesktop.openPath(outputPathValue.value.trim());
  }
});

inspectorActionPrimary.addEventListener("click", openSelectedTarget);
inspectorActionSecondary.addEventListener("click", () => {
  void refreshCurrentWorkspace();
});
inspectorActionTertiary.addEventListener("click", openWorkspaceTertiaryAction);

startButton.addEventListener("click", async () => {
  setWorkspace("task-bus");
  setConsole("activity");
  await startBatchRun({
    inputRoot: inputPathValue.value.trim(),
    outRoot: outputPathValue.value.trim(),
    resume: resumeToggle.checked,
    pipeline: "dual-track",
  }, "正在准备批次快照并枚举 HTML 输入项。");
});

autoMdButton.addEventListener("click", async () => {
  inputPathValue.value = DEFAULT_DISCOVERY_ROOT;
  outputPathValue.value = DEFAULT_RAWWECHAT_LLM_ARTIFACT_OUTPUT;
  resumeToggle.checked = true;
  setWorkspace("task-bus");
  setConsole("activity");

  await startBatchRun({
    inputRoot: DEFAULT_DISCOVERY_ROOT,
    outRoot: DEFAULT_RAWWECHAT_LLM_ARTIFACT_OUTPUT,
    mirrorRoot: DEFAULT_RAWWECHAT_LLM_MD_OUTPUT,
    resume: true,
    pipeline: "llm-export",
  }, "正在将 D:\\rawwechat 批量导出为可喂 LLM 的结构化产物和 Markdown。");
});

stopButton.addEventListener("click", async () => {
  if (!isRunning) {
    return;
  }

  stopButton.disabled = true;
  cancellationRequested = true;
  setConsole("system");
  setPresence("cancelling", "停止中");
  detailCurrentMessage.textContent = "正在等待当前项目响应取消请求。";
  const result = await window.wechatDesktop.cancelBatch();
  if (!result.accepted) {
    cancellationRequested = false;
    stopButton.disabled = false;
    setPresence("failed", "失败");
    detailCurrentMessage.textContent = result.message || "无法取消当前批处理。";
  }
});

window.wechatDesktop.onBatchSnapshot((snapshot) => {
  renderSnapshot(snapshot);
});

window.wechatDesktop.onBatchError((message) => {
  cancellationRequested = false;
  setPresence("failed", "失败");
  detailCurrentMessage.textContent = message;
  runConsoleSummary.textContent = message;
  setConsole("failures");
  isRunning = false;
  startButton.disabled = false;
  autoMdButton.disabled = false;
  stopButton.disabled = true;
});

function syncCompactInspectorAction() {
  const compactInspectorAction = document.querySelector("[data-role='compact-inspector-action']");
  if (!compactInspectorAction) {
    return;
  }
  compactInspectorAction?.addEventListener("click", () => {
    const inspector = document.querySelector(".right-inspector");
    if (inspector) {
      inspector.classList.toggle("is-compact-visible");
    }
  });
}

window.addEventListener("DOMContentLoaded", async () => {
  setWorkspace(activeWorkspace);
  setConsole(activeConsole);

  createPcuiKeyboardController({
    appState: { currentFocusArea: 0 },
    refs: {
      startButton,
      stopButton,
      openOutputButton,
      autoMdButton,
      bottomRunConsole: document.querySelector(".bottom-run-console"),
    },
    actions: {
      start: () => startButton?.click(),
      stop: () => stopButton?.click(),
      openOutput: () => openOutputButton?.click(),
      openMarkdownMirror: () => autoMdButton?.click(),
      switchWorkspaceByIndex: (index) => workspaceButtons[index]?.click(),
      refreshCurrentWorkspace: () => refreshActiveWorkspace(),
      toggleConsoleCollapse: () => {
        const consoleSection = document.querySelector(".bottom-run-console");
        if (consoleSection) {
          consoleSection.hidden = !consoleSection.hidden;
        }
      },
      setConsole: (name) => setConsole(name),
    },
  });

  const themeController = createPcuiThemeController({
    root: document.documentElement,
    themeToggle: document.querySelector("[data-role='theme-toggle']"),
  });

  window.__pcuiApplyThemeForCapture = (theme) => {
    themeController.apply(theme, { persist: false });
  };

  window.__pcuiGetPerformanceMarks = () => perfRecorder.snapshot();
  window.__pcuiResetPerformanceMarks = () => perfRecorder.reset();

  syncCompactInspectorAction();

  const snapshot = await window.wechatDesktop.getLatestSnapshot();
  if (snapshot) {
    renderSnapshot(snapshot);
  } else {
    updateInspector();
  }

  setInterval(() => {
    if (activeWorkspace === "collect" || activeWorkspace === "archive") {
      void refreshActiveWorkspace();
    }
  }, 5000);

  window.addEventListener("keydown", async (event) => {
    if (event.defaultPrevented) {
      return;
    }

    const target = event.target;
    const tag = target && target.tagName ? target.tagName.toLowerCase() : "";
    const typing =
      tag === "input" ||
      tag === "textarea" ||
      tag === "select" ||
      (target && target.isContentEditable);

    if (typing) {
      return;
    }

    const key = event.key;
    const accel = event.ctrlKey || event.metaKey;

    if (accel && key.toLowerCase() === "enter") {
      event.preventDefault();
      startButton.click();
      return;
    }

    if (key === "Escape") {
      event.preventDefault();
      stopButton.click();
      return;
    }

    if (accel && key.toLowerCase() === "o") {
      event.preventDefault();
      openOutputButton.click();
      return;
    }

    if (accel && key.toLowerCase() === "m") {
      event.preventDefault();
      autoMdButton.click();
      return;
    }

    if (accel && /^[1-5]$/.test(key)) {
      event.preventDefault();
      const index = Number(key) - 1;
      const button = workspaceButtons[index];
      if (button) {
        button.click();
      }
    }
  });
});
