import { toDisplayText } from "./pcuiFormat.js";

export function renderInspectorExtraSection({ inspectorExtra, inspectorExtraTitle }, title, groups) {
  if (!inspectorExtra) {
    return;
  }
  if (inspectorExtraTitle) {
    inspectorExtraTitle.textContent = title || "状态分区";
  }
  inspectorExtra.innerHTML = "";
  for (const group of groups.filter(Boolean)) {
    const section = document.createElement("div");
    section.className = "inspector-group";
    const heading = document.createElement("div");
    heading.className = "inspector-group-title";
    heading.textContent = group.title;
    const grid = document.createElement("div");
    grid.className = "property-grid";
    for (const [key, value] of group.rows.filter((row) => Array.isArray(row))) {
      const row = document.createElement("div");
      row.className = "property-row";
      const keyEl = document.createElement("span");
      keyEl.className = "property-key";
      keyEl.textContent = key;
      const valueEl = document.createElement("span");
      valueEl.className = "property-value";
      valueEl.textContent = toDisplayText(value);
      valueEl.title = valueEl.textContent;
      row.append(keyEl, valueEl);
      grid.append(row);
    }
    section.append(heading, grid);
    inspectorExtra.append(section);
  }
}

export function clearInspectorExtraSection(targets) {
  renderInspectorExtraSection(targets, "状态分区", [
    {
      title: "概览",
      rows: [["状态", "未选择对象"], ["说明", "选中表格行后显示对象级投影。"]],
    },
  ]);
}
