import { formatPhaseLabel, formatStatusLabel } from "./pcuiContract.js";
import { parseDate } from "./pcuiFormat.js";

export function renderFailureConsole({ failureList, failureSummary }, snapshot) {
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

export function renderRunConsolePanel({ runConsoleActivityList, runConsoleSystemList }, snapshot, activeItem) {
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
}
