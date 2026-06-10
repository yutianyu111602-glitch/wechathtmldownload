const DEFAULT_ROW_HEIGHT = 32;
const DEFAULT_OVERSCAN = 8;
const DEFAULT_MAX_DOM_ROWS = 300;

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function normalizePositiveInteger(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : fallback;
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function defaultGetRowKey(row, index) {
  return row?.id || row?.key || row?.rowKey || String(index);
}

export function calculateVirtualTableRange({
  totalRows = 0,
  rowHeight = DEFAULT_ROW_HEIGHT,
  viewportHeight = 0,
  scrollTop = 0,
  overscan = DEFAULT_OVERSCAN,
  maxDomRows = DEFAULT_MAX_DOM_ROWS,
} = {}) {
  const total = Math.max(0, Math.floor(totalRows || 0));
  const height = normalizePositiveInteger(rowHeight, DEFAULT_ROW_HEIGHT);
  const viewport = Math.max(0, Math.floor(viewportHeight || 0));
  const scroll = Math.max(0, Math.floor(scrollTop || 0));
  const safeOverscan = Math.max(0, Math.floor(overscan || 0));
  const maxRows = normalizePositiveInteger(maxDomRows, DEFAULT_MAX_DOM_ROWS);

  if (!total) {
    return {
      totalRows: 0,
      rowHeight: height,
      viewportHeight: viewport,
      scrollTop: scroll,
      visibleStart: 0,
      visibleEnd: 0,
      start: 0,
      end: 0,
      offsetTop: 0,
      totalHeight: 0,
      domRowCount: 0,
    };
  }

  const visibleStart = clamp(Math.floor(scroll / height), 0, total - 1);
  const visibleCount = Math.max(1, Math.ceil(viewport / height));
  const visibleEnd = clamp(visibleStart + visibleCount, visibleStart + 1, total);
  let start = Math.max(0, visibleStart - safeOverscan);
  let end = Math.min(total, visibleEnd + safeOverscan);

  if (end - start > maxRows) {
    const maxStart = Math.max(0, total - maxRows);
    start = clamp(visibleStart - Math.floor((maxRows - 1) / 2), 0, maxStart);
    end = Math.min(total, start + maxRows);
  }

  return {
    totalRows: total,
    rowHeight: height,
    viewportHeight: viewport,
    scrollTop: scroll,
    visibleStart,
    visibleEnd,
    start,
    end,
    offsetTop: start * height,
    totalHeight: total * height,
    domRowCount: end - start,
  };
}

export function buildVirtualTableView({
  rows = [],
  rowHeight = DEFAULT_ROW_HEIGHT,
  viewportHeight = 0,
  scrollTop = 0,
  overscan = DEFAULT_OVERSCAN,
  maxDomRows = DEFAULT_MAX_DOM_ROWS,
  getRowKey = defaultGetRowKey,
  selectedKey = "",
  focusedKey = "",
  loading = false,
  error = null,
  loadingMessage = "加载中",
  emptyMessage = "当前没有可显示的行。",
} = {}) {
  const sourceRows = asArray(rows);
  const range = calculateVirtualTableRange({
    totalRows: sourceRows.length,
    rowHeight,
    viewportHeight,
    scrollTop,
    overscan,
    maxDomRows,
  });

  if (loading) {
    return {
      state: "loading",
      message: loadingMessage,
      range,
      virtualRows: [],
      totalHeight: range.totalHeight,
      offsetTop: 0,
      domRowCount: 0,
    };
  }

  if (error) {
    return {
      state: "error",
      message: error instanceof Error ? error.message : String(error),
      range,
      virtualRows: [],
      totalHeight: range.totalHeight,
      offsetTop: 0,
      domRowCount: 0,
    };
  }

  if (!sourceRows.length) {
    return {
      state: "empty",
      message: emptyMessage,
      range,
      virtualRows: [],
      totalHeight: 0,
      offsetTop: 0,
      domRowCount: 0,
    };
  }

  const virtualRows = [];
  for (let sourceIndex = range.start; sourceIndex < range.end; sourceIndex += 1) {
    const row = sourceRows[sourceIndex];
    const key = getRowKey(row, sourceIndex);
    virtualRows.push({
      row,
      sourceIndex,
      key,
      ariaRowIndex: sourceIndex + 1,
      selected: Boolean(selectedKey && key === selectedKey),
      focused: Boolean(focusedKey && key === focusedKey),
    });
  }

  return {
    state: "ready",
    message: "",
    range,
    virtualRows,
    totalHeight: range.totalHeight,
    offsetTop: range.offsetTop,
    domRowCount: virtualRows.length,
  };
}
