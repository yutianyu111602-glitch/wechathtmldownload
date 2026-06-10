import { buildVirtualTableView } from "./pcuiVirtualTable.js";

const DEFAULT_VIEWPORT_HEIGHT = 320;
const DEFAULT_ROW_HEIGHT = 32;
const DEFAULT_OVERSCAN = 12;
const DEFAULT_MAX_DOM_ROWS = 300;
const VIRTUAL_STATE_CLASSES = [
  "is-state-ready",
  "is-state-loading",
  "is-state-empty",
  "is-state-error",
];
const VIRTUAL_STATE_KIND_CLASSES = [
  "is-kind-loading",
  "is-kind-projection-missing",
  "is-kind-read-failed",
  "is-kind-no-rows",
  "is-kind-filtered-empty",
];
const virtualListRenderState = new WeakMap();
const virtualRowsIdentity = new WeakMap();
const viewportHeightCache = new WeakMap();
let nextVirtualRowsIdentity = 1;

function getViewportHeight(list, explicitViewportHeight, fallback = DEFAULT_VIEWPORT_HEIGHT) {
  if (explicitViewportHeight !== undefined) {
    return explicitViewportHeight;
  }
  const cached = viewportHeightCache.get(list);
  if (cached) {
    return cached.height;
  }
  const currentRaw = Number(list?.clientHeight || list?.offsetHeight || 0);
  const currentHeight = Number.isFinite(currentRaw) && currentRaw > 0
    ? Math.floor(currentRaw)
    : 0;
  if (currentHeight === 0) {
    return fallback;
  }
  viewportHeightCache.set(list, { height: currentHeight });
  return currentHeight;
}

function getScrollTop(list) {
  const scrollTop = Number(list?.scrollTop || 0);
  return Number.isFinite(scrollTop) && scrollTop > 0 ? Math.floor(scrollTop) : 0;
}

function normalizeStateKind(kind, fallback) {
  const value = String(kind || "").trim();
  return value || fallback;
}

function getVirtualStateKind(viewState, { emptyStateKind, loadingStateKind, errorStateKind }) {
  if (viewState === "loading") {
    return normalizeStateKind(loadingStateKind, "loading");
  }
  if (viewState === "error") {
    return normalizeStateKind(errorStateKind, "read-failed");
  }
  if (viewState === "empty") {
    return normalizeStateKind(emptyStateKind, "no-rows");
  }
  return "";
}

function setStateClass(element, state, stateKind) {
  if (!element) {
    return;
  }
  const existing = String(element.className || "")
    .split(/\s+/)
    .filter(Boolean)
    .filter((token) => !VIRTUAL_STATE_CLASSES.includes(token) && !VIRTUAL_STATE_KIND_CLASSES.includes(token));
  const next = [...existing, `is-state-${state}`];
  if (stateKind) {
    next.push(`is-kind-${stateKind}`);
  }
  element.className = Array.from(new Set(next)).join(" ");
}

function setVirtualMetrics(list, view, stateKind = "") {
  if (!list?.dataset) {
    return;
  }
  list.dataset.virtualState = view.state;
  list.dataset.virtualStateKind = stateKind;
  list.dataset.virtualTotalRows = String(view.range.totalRows);
  list.dataset.virtualDomRows = String(view.domRowCount);
  list.dataset.virtualStart = String(view.range.start);
  list.dataset.virtualEnd = String(view.range.end);
}

function setVirtualRenderMetrics(list, metrics) {
  if (!list?.dataset) {
    return;
  }
  list.dataset.virtualRebuildSkipped = metrics.skipped ? "true" : "false";
  list.dataset.virtualRebuildCount = String(metrics.rebuildCount);
  list.dataset.virtualSkipCount = String(metrics.skipCount);
}

function normalizeSignaturePart(value) {
  if (value === undefined || value === null) {
    return "";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(normalizeSignaturePart).join(",")}]`;
  }
  if (typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${key}:${normalizeSignaturePart(value[key])}`).join(",")}}`;
  }
  return String(value);
}

function getRowsIdentitySignature(rows, versionKey) {
  if (versionKey || !rows || typeof rows !== "object") {
    return "";
  }
  if (!virtualRowsIdentity.has(rows)) {
    virtualRowsIdentity.set(rows, nextVirtualRowsIdentity++);
  }
  return `rows:${virtualRowsIdentity.get(rows)}`;
}

function buildVirtualListSignature(view, stateKind, options) {
  const rowKeys = view.virtualRows
    .map((virtualRow) => [
      normalizeSignaturePart(virtualRow.key),
      virtualRow.selected ? "s" : "",
      virtualRow.focused ? "f" : "",
    ].join(":"))
    .join("\x1f");
  return [
    view.state,
    stateKind,
    view.message || "",
    view.range.totalRows,
    view.range.start,
    view.range.end,
    view.range.rowHeight,
    view.range.visibleStart,
    view.range.visibleEnd,
    view.range.viewportHeight,
    view.range.totalHeight,
    view.offsetTop,
    view.domRowCount,
    normalizeSignaturePart(options.selectedKey),
    normalizeSignaturePart(options.focusedKey),
    normalizeSignaturePart(options.queryKey),
    normalizeSignaturePart(options.versionKey),
    normalizeSignaturePart(options.rowsIdentity),
    normalizeSignaturePart(options.signatureContext),
    rowKeys,
  ].join("\x1e");
}

function createRenderMetrics(previous, { signature, skipped }) {
  return {
    signature,
    skipped,
    rebuilt: !skipped,
    rebuildCount: (previous?.rebuildCount || 0) + (skipped ? 0 : 1),
    skipCount: (previous?.skipCount || 0) + (skipped ? 1 : 0),
  };
}

function appendRowsInBatch(list, rowElements) {
  if (!rowElements.length) {
    return;
  }
  const doc = globalThis.document;
  if (typeof doc?.createDocumentFragment === "function") {
    const fragment = doc.createDocumentFragment();
    for (const rowElement of rowElements) {
      fragment.append(rowElement);
    }
    list.append(fragment);
    return;
  }
  list.append(...rowElements);
}

function measureVirtualListPhase(measurePhase, phase, detail, callback) {
  if (typeof measurePhase !== "function") {
    return callback();
  }
  return measurePhase(phase, detail, callback);
}

export function resetVirtualListState(list) {
  if (!list) {
    return;
  }
  virtualListRenderState.delete(list);
  viewportHeightCache.delete(list);
  list.style.paddingTop = "";
  list.style.paddingBottom = "";
  if (list.dataset) {
    list.dataset.virtualState = "";
    list.dataset.virtualStateKind = "";
    list.dataset.virtualTotalRows = "0";
    list.dataset.virtualDomRows = "0";
    list.dataset.virtualStart = "0";
    list.dataset.virtualEnd = "0";
    list.dataset.virtualRebuildSkipped = "false";
    list.dataset.virtualRebuildCount = "0";
    list.dataset.virtualSkipCount = "0";
  }
}

export function getVirtualListMetrics(list) {
  return {
    state: list?.dataset?.virtualState || "",
    stateKind: list?.dataset?.virtualStateKind || "",
    totalRows: Number(list?.dataset?.virtualTotalRows || 0),
    domRows: Number(list?.dataset?.virtualDomRows || 0),
    start: Number(list?.dataset?.virtualStart || 0),
    end: Number(list?.dataset?.virtualEnd || 0),
    rebuildSkipped: list?.dataset?.virtualRebuildSkipped === "true",
    rebuildCount: Number(list?.dataset?.virtualRebuildCount || 0),
    skipCount: Number(list?.dataset?.virtualSkipCount || 0),
  };
}

export function renderVirtualList({
  list,
  rows = [],
  rowHeight = DEFAULT_ROW_HEIGHT,
  viewportHeight,
  scrollTop,
  overscan = DEFAULT_OVERSCAN,
  maxDomRows = DEFAULT_MAX_DOM_ROWS,
  getRowKey,
  selectedKey = "",
  focusedKey = "",
  loading = false,
  error = null,
  loadingMessage = "加载中",
  loadingStateKind = "loading",
  errorStateKind = "read-failed",
  emptyStateKind = "no-rows",
  emptyMessage = "当前没有可显示的行。",
  queryKey = "",
  versionKey = "",
  signatureContext = "",
  measurePhase,
  createRow,
} = {}) {
  if (!list || typeof createRow !== "function") {
    return null;
  }

  const sourceRowCount = Array.isArray(rows) ? rows.length : 0;
  const view = measureVirtualListPhase(measurePhase, "build-view", {
    sourceRowCount,
  }, () => buildVirtualTableView({
    rows,
    rowHeight,
    viewportHeight: getViewportHeight(list, viewportHeight),
    scrollTop: scrollTop ?? getScrollTop(list),
    overscan,
    maxDomRows,
    getRowKey,
    selectedKey,
    focusedKey,
    loading,
    error,
    loadingMessage,
    emptyMessage,
  }));

  list.classList?.add?.("is-virtualized");
  const stateKind = getVirtualStateKind(view.state, { emptyStateKind, loadingStateKind, errorStateKind });
  setStateClass(list, view.state, stateKind);
  setVirtualMetrics(list, view, stateKind);
  list.setAttribute?.("aria-busy", view.state === "loading" ? "true" : "false");

  const previousRenderState = virtualListRenderState.get(list);
  const signature = measureVirtualListPhase(measurePhase, "signature", {
    state: view.state,
    domRowCount: view.domRowCount,
  }, () => buildVirtualListSignature(view, stateKind, {
    selectedKey,
    focusedKey,
    queryKey,
    versionKey,
    rowsIdentity: getRowsIdentitySignature(rows, versionKey),
    signatureContext,
  }));

  if (view.state === "ready" && previousRenderState?.signature === signature) {
    const renderMetrics = createRenderMetrics(previousRenderState, { signature, skipped: true });
    virtualListRenderState.set(list, renderMetrics);
    setVirtualRenderMetrics(list, renderMetrics);
    return {
      ...view,
      renderMetrics,
      domRebuildSkipped: true,
    };
  }

  measureVirtualListPhase(measurePhase, "clear-dom", {
    state: view.state,
    domRowCount: view.domRowCount,
  }, () => {
    list.innerHTML = "";
  });

  if (view.state !== "ready") {
  virtualListRenderState.delete(list);
  viewportHeightCache.delete(list);
    resetVirtualListState(list);
    setStateClass(list, view.state, stateKind);
    setVirtualMetrics(list, view, stateKind);
    const renderMetrics = createRenderMetrics(null, { signature, skipped: false });
    setVirtualRenderMetrics(list, renderMetrics);
    measureVirtualListPhase(measurePhase, "state-row", {
      state: view.state,
      stateKind,
    }, () => {
      const emptyItem = document.createElement("li");
      emptyItem.className = `empty-state is-${view.state} is-${stateKind}`;
      emptyItem.dataset.state = view.state;
      emptyItem.dataset.stateKind = stateKind;
      emptyItem.setAttribute("role", view.state === "error" ? "alert" : "status");
      emptyItem.textContent = view.message || emptyMessage;
      list.append(emptyItem);
    });
    return {
      ...view,
      renderMetrics,
      domRebuildSkipped: false,
    };
  }

  measureVirtualListPhase(measurePhase, "layout-padding", {
    domRowCount: view.domRowCount,
    offsetTop: view.offsetTop,
  }, () => {
    list.style.paddingTop = `${view.offsetTop}px`;
    const renderedHeight = view.domRowCount * view.range.rowHeight;
    const bottomPadding = Math.max(0, view.totalHeight - view.offsetTop - renderedHeight);
    list.style.paddingBottom = `${bottomPadding}px`;
  });

  const rowElements = measureVirtualListPhase(measurePhase, "create-rows", {
    domRowCount: view.domRowCount,
  }, () => {
    const nextRowElements = [];
    for (const virtualRow of view.virtualRows) {
      const rowElement = createRow(virtualRow);
      if (!rowElement) {
        continue;
      }
      rowElement.dataset.virtualIndex = String(virtualRow.sourceIndex);
      rowElement.setAttribute("aria-rowindex", String(virtualRow.ariaRowIndex));
      rowElement.setAttribute("aria-setsize", String(view.range.totalRows));
      rowElement.style.height = `${view.range.rowHeight}px`;
      rowElement.style.minHeight = `${view.range.rowHeight}px`;
      nextRowElements.push(rowElement);
    }
    return nextRowElements;
  });
  measureVirtualListPhase(measurePhase, "append-rows", {
    domRowCount: rowElements.length,
  }, () => appendRowsInBatch(list, rowElements));

  setVirtualMetrics(list, view, stateKind);
  const renderMetrics = createRenderMetrics(previousRenderState, { signature, skipped: false });
  virtualListRenderState.set(list, renderMetrics);
  setVirtualRenderMetrics(list, renderMetrics);
  return {
    ...view,
    renderMetrics,
    domRebuildSkipped: false,
  };
}
