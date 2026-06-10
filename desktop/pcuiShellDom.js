import { getWorkspaceModel } from "./pcuiWorkspaceModel.js";
import { resetVirtualListState } from "./pcuiVirtualListDom.js";

export function setShellPresence({ titlebarStateText, titlebarStateDot, statusbarState }, status, text) {
  if (titlebarStateText) {
    titlebarStateText.textContent = text;
  }
  if (titlebarStateDot) {
    titlebarStateDot.dataset.status = status;
  }
  if (statusbarState) {
    statusbarState.textContent = text;
  }
}

export function updateWorkspaceChrome({
  titlebarWorkspace,
  workspaceTitle,
  workspaceSubtitle,
  workspaceObjectName,
  workspaceCounterSummary,
  commandbarActionGroups,
}, workspace) {
  const meta = getWorkspaceModel(workspace);
  if (workspaceTitle) {
    workspaceTitle.textContent = meta.title;
  }
  if (titlebarWorkspace) {
    titlebarWorkspace.textContent = meta.title;
  }
  if (workspaceSubtitle) {
    workspaceSubtitle.textContent = meta.subtitle;
  }
  if (workspaceObjectName) {
    workspaceObjectName.textContent = meta.objectName;
  }
  if (workspaceCounterSummary && !workspaceCounterSummary.textContent.trim()) {
    workspaceCounterSummary.textContent = meta.counterFallback;
  }

  for (const group of commandbarActionGroups || []) {
    const active = group.dataset.commandWorkspace === workspace || group.dataset.commandWorkspace === "all";
    group.hidden = !active;
    group.classList.toggle("is-active", active);
  }
}

export function setWorkspaceCounterText({ activeWorkspace, workspaceCounterSummary }, workspace, text) {
  if (activeWorkspace === workspace && workspaceCounterSummary) {
    workspaceCounterSummary.textContent = text || getWorkspaceModel(workspace).counterFallback;
  }
}

export function syncCommandbarSearchInput(commandbarSearch, placeholder, value) {
  if (!commandbarSearch) {
    return;
  }
  commandbarSearch.placeholder = placeholder;
  commandbarSearch.value = value;
}

export function setRunConsoleSummaryText({ runConsoleSummaryText, runConsoleSummary }, text) {
  if (runConsoleSummaryText) {
    runConsoleSummaryText.textContent = text;
    return;
  }
  if (runConsoleSummary) {
    runConsoleSummary.textContent = text;
  }
}

const EMPTY_STATE_CLASSES = [
  "is-kind-loading",
  "is-kind-projection-missing",
  "is-kind-read-failed",
  "is-kind-no-rows",
  "is-kind-filtered-empty",
];

function normalizeStateKind(kind) {
  const value = String(kind || "").trim();
  return value || "no-rows";
}

function setEmptyListState(list, stateKind) {
  if (!list?.dataset) {
    return;
  }
  list.dataset.virtualState = "empty";
  list.dataset.virtualStateKind = stateKind;
  list.dataset.virtualTotalRows = "0";
  list.dataset.virtualDomRows = "0";
  list.dataset.virtualStart = "0";
  list.dataset.virtualEnd = "0";
}

function setEmptyStateClass(element, stateKind) {
  if (!element) {
    return;
  }
  const existing = String(element.className || "")
    .split(/\s+/)
    .filter(Boolean)
    .filter((token) => !EMPTY_STATE_CLASSES.includes(token));
  element.className = Array.from(new Set([...existing, `is-kind-${stateKind}`])).join(" ");
}

export function replaceListWithEmptyState(list, message, { stateKind = "no-rows" } = {}) {
  if (!list) {
    return;
  }
  const normalizedStateKind = normalizeStateKind(stateKind);
  resetVirtualListState(list);
  list.innerHTML = "";
  setEmptyStateClass(list, normalizedStateKind);
  setEmptyListState(list, normalizedStateKind);
  const emptyItem = document.createElement("li");
  emptyItem.className = `empty-state is-empty is-${normalizedStateKind}`;
  emptyItem.dataset.state = "empty";
  emptyItem.dataset.stateKind = normalizedStateKind;
  emptyItem.setAttribute("role", normalizedStateKind === "read-failed" ? "alert" : "status");
  emptyItem.textContent = message;
  list.append(emptyItem);
}
