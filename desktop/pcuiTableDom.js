import { formatStatusLabel, statusClass } from "./pcuiContract.js";
import { toDisplayText } from "./pcuiFormat.js";
import {
  bindPcuiRowActivation,
  isPcuiTextInputTarget,
} from "./pcuiKeyboardController.js";

export { isPcuiTextInputTarget };

export function createTextCell(value, className = "row-main", title = "") {
  const cell = document.createElement("span");
  cell.className = `${className} truncate-cell`;
  cell.textContent = toDisplayText(value);
  cell.title = title || cell.textContent;
  return cell;
}

export function createStackCell(primary, secondary = "", title = "") {
  const wrapper = document.createElement("div");
  wrapper.className = "row-title-stack";
  const main = createTextCell(primary, "row-main", title || primary);
  const sub = createTextCell(secondary || "-", "row-sub", secondary || "");
  wrapper.append(main, sub);
  return wrapper;
}

export function createProgressCell(value) {
  const percent = Math.max(0, Math.min(100, Number(value || 0)));
  const wrapper = document.createElement("span");
  wrapper.className = "micro-progress";
  const label = document.createElement("span");
  label.textContent = `${percent}%`;
  const track = document.createElement("span");
  track.className = "micro-progress-track";
  const bar = document.createElement("span");
  bar.className = "micro-progress-bar";
  bar.style.width = `${percent}%`;
  track.append(bar);
  wrapper.append(label, track);
  return wrapper;
}

export function createFileStateCell(label, ok, warningLabel = "missing") {
  const status = ok ? "ok" : warningLabel;
  const cell = document.createElement("span");
  const classStatus = ok ? "ok" : ["missing", "error", "failed", "blocked"].includes(warningLabel) ? warningLabel : warningLabel === "running" ? "running" : "warning";
  cell.className = `compact-status ${statusClass(classStatus)}`;
  cell.textContent = label || formatStatusLabel(status);
  return cell;
}

export function setRowInteractive(row, selected, activate, label = "") {
  row.tabIndex = selected ? 0 : -1;
  row.setAttribute("role", "button");
  row.setAttribute("aria-selected", selected ? "true" : "false");
  row.setAttribute("data-a11y-row", "true");
  if (label) {
    row.setAttribute("aria-label", label);
  }
  bindPcuiRowActivation(row, activate);
}

export function createStatusBadge(status) {
  const span = document.createElement("span");
  span.className = `item-status ${statusClass(status)}`;
  span.dataset.status = status || "idle";
  span.textContent = formatStatusLabel(status || "idle");
  return span;
}
