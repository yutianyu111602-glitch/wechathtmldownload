import { isPcuiTextInputTarget } from "./pcuiKeyboardController.js";

function toDatasetValue(value) {
  return value === null || value === undefined ? "" : String(value).trim();
}

export function setPcuiRowMetadata(row, { rowKey = "", rowKind = "", rowObjectId = "" } = {}) {
  if (!row?.dataset) {
    return row;
  }
  const stableRowKey = toDatasetValue(rowKey);
  const stableObjectId = toDatasetValue(rowObjectId) || stableRowKey;
  row.dataset.rowKey = stableRowKey;
  row.dataset.rowKind = toDatasetValue(rowKind);
  row.dataset.rowObjectId = stableObjectId;
  return row;
}

export function getPcuiRowContextTarget(row, fallback = "") {
  if (!row?.dataset) {
    return toDatasetValue(fallback);
  }
  return toDatasetValue(row.dataset.rowObjectId)
    || toDatasetValue(row.dataset.rowKey)
    || toDatasetValue(fallback);
}

export function isPcuiContextMenuOpen(contextMenu) {
  return Boolean(contextMenu && contextMenu.hidden === false);
}

export function consumePcuiContextMenuEscape(event, contextMenu, hideContextMenu) {
  if (event?.key !== "Escape" || !isPcuiContextMenuOpen(contextMenu)) {
    return false;
  }
  if (isPcuiTextInputTarget(event.target)) {
    return false;
  }
  event.preventDefault?.();
  event.stopPropagation?.();
  event.stopImmediatePropagation?.();
  hideContextMenu?.();
  return true;
}
