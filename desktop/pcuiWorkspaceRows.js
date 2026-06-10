import {
  formatPhaseLabel,
  formatStatusLabel,
  getArtifactRowKey,
  statusClass,
} from "./pcuiContract.js";
import {
  formatClockTime,
  formatCompactNumber,
  formatDuration,
  formatNumber,
  formatShortDateTime,
  shortText,
} from "./pcuiFormat.js";
import {
  createFileStateCell,
  createProgressCell,
  createStatusBadge,
  createTextCell,
  setRowInteractive,
} from "./pcuiTableDom.js";
import {
  detectArchiveAnomalies,
  detectCollectAnomalies,
  formatAnomalyShort,
  getHighestAnomalySeverity,
} from "./pcuiAnomalies.js";
import { setPcuiRowMetadata } from "./pcuiContextMenuController.js";

export function createTaskBusRow({ item, snapshot, selected, onActivate }) {
  const row = document.createElement("li");
  row.className = "item-row";
  const taskKey = item.inputPath || item.relativeInputPath || snapshot.currentFile || "";
  setPcuiRowMetadata(row, {
    rowKey: taskKey,
    rowKind: "task-bus",
    rowObjectId: taskKey,
  });
  if (selected) {
    row.classList.add("is-selected");
  }

  const taskName = item.relativeInputPath || item.inputPath || snapshot.currentFile || "-";
  const source = item.source || snapshot.pipeline || (snapshot.imported ? "imported" : "batch");
  const phase = formatPhaseLabel(item.phase || item.status || "queued");
  const percent = ["succeeded", "completed", "skipped"].includes(item.status)
    ? 100
    : item.status === "running" && snapshot.totalItems
      ? Math.round((snapshot.completedCount / snapshot.totalItems) * 100)
    : 0;
  const latest = shortText(item.errorMessage || item.message || phase, 36);
  const output = item.outputCount || item.completedCount || (["succeeded", "completed"].includes(item.status) ? 1 : 0);
  setRowInteractive(
    row,
    selected,
    onActivate,
    `任务 ${taskName}，状态 ${formatStatusLabel(item.status || "queued")}，阶段 ${phase}`,
  );

  row.append(
    createStatusBadge(item.status || "queued"),
    createTextCell(taskName, "item-file", taskName),
    createTextCell(source, "row-sub mono-cell"),
    createTextCell(phase, "row-main"),
    createProgressCell(percent),
    createTextCell(item.queue || item.phase || "-", "row-sub mono-cell"),
    createTextCell(latest, "item-message", item.errorMessage || item.message || ""),
    createTextCell(formatDuration(item.startedAt, item.endedAt || snapshot.updatedAt), "row-sub mono-cell"),
    createTextCell(formatNumber(output), "row-main mono-cell"),
    createTextCell(String(item.retryCount || item.retries || 0), "row-main mono-cell"),
  );
  return row;
}

export function createCollectRow({ account, selected, onActivate }) {
  const anomalies = detectCollectAnomalies(account);
  const row = document.createElement("li");
  row.className = "collect-row-v2";
  const accountKey = account.fakeid || account.accountKey || account.nickname || "";
  setPcuiRowMetadata(row, {
    rowKey: accountKey,
    rowKind: "collect",
    rowObjectId: accountKey,
  });
  if (selected) {
    row.classList.add("is-selected");
  }

  const status = createStatusBadge(account.status || "missing");
  const biz = account.biz || account.bizName || account.accountKey || (account.fakeid ? account.fakeid.slice(0, 8) : "-");
  const recentError = account.errorMessage || (anomalies.length ? formatAnomalyShort(anomalies) : "-");
  const errorCell = anomalies.length || account.errorMessage
    ? createTextCell(recentError, `compact-status ${statusClass(getHighestAnomalySeverity(anomalies) || "error")}`, account.errorMessage || anomalies.join(", "))
    : createTextCell("-", "row-sub");
  setRowInteractive(
    row,
    selected,
    onActivate,
    `账号 ${account.nickname || account.fakeid || "-"}，fakeid ${account.fakeid || "-"}，状态 ${formatStatusLabel(account.status || "missing")}`,
  );

  row.append(
    status,
    createTextCell(account.fakeid || "-", "row-main mono-cell"),
    createTextCell(account.nickname || "-", "row-main"),
    createTextCell(biz, "row-sub mono-cell"),
    createTextCell(formatNumber(account.discoveredCount), "row-main mono-cell"),
    createTextCell(formatNumber(account.enqueuedCount), "row-main mono-cell"),
    createTextCell(formatNumber(account.duplicateCount), "row-main mono-cell"),
    createTextCell(formatShortDateTime(account.lastDiscoveredAt), "row-sub mono-cell"),
    errorCell,
    createTextCell(formatShortDateTime(account.updatedAt || account.lastDiscoveredAt), "row-sub mono-cell"),
  );
  return row;
}

export function createCollectLiveRow({ account, selected, onActivate }) {
  const row = document.createElement("li");
  row.className = "collect-row-v2";
  const accountKey = account.fakeid || account.accountKey || account.nickname || "";
  setPcuiRowMetadata(row, {
    rowKey: accountKey,
    rowKind: "collect",
    rowObjectId: accountKey,
  });
  if (selected) {
    row.classList.add("is-selected");
  }

  const recentError = account.failedCount ? `失败 ${account.failedCount}` : "-";
  const errorCell = account.failedCount
    ? createTextCell(recentError, "compact-status status-error")
    : createTextCell("-", "row-sub");
  setRowInteractive(
    row,
    selected,
    onActivate,
    `Live 账号 ${account.nickname || account.fakeid || "-"}，fakeid ${account.fakeid || "-"}，状态 ${formatStatusLabel(account.status || "ready")}`,
  );

  row.append(
    createStatusBadge(account.status || "ready"),
    createTextCell(account.fakeid || "-", "row-main mono-cell"),
    createTextCell(account.nickname || "-", "row-main"),
    createTextCell("live", "row-sub mono-cell"),
    createTextCell(formatNumber(account.discoveredCount), "row-main mono-cell"),
    createTextCell(formatNumber(account.enqueuedCount), "row-main mono-cell"),
    createTextCell(formatNumber(account.duplicateCount), "row-main mono-cell"),
    createTextCell(formatShortDateTime(account.lastDiscoveredAt), "row-sub mono-cell"),
    errorCell,
    createTextCell(formatShortDateTime(account.lastDiscoveredAt), "row-sub mono-cell"),
  );
  return row;
}

export function createArchiveRow({ item, selected, onActivate }) {
  const anomalies = detectArchiveAnomalies(item);
  const row = document.createElement("li");
  row.className = "archive-row-v2";
  const archiveKey = item.token || item.sourceUrl || item.outDir || "";
  setPcuiRowMetadata(row, {
    rowKey: archiveKey,
    rowKind: "archive",
    rowObjectId: archiveKey,
  });
  if (selected) {
    row.classList.add("is-selected");
  }

  const capture = item.captureComplete
    ? createFileStateCell("raw.html OK", true)
    : createFileStateCell("partial", false, "warning");
  const assets = item.assetsComplete
    ? createFileStateCell(`${formatNumber(item.imageCount)} img`, true)
    : createFileStateCell("missing", false);
  const anomaly = anomalies.length
    ? createTextCell(formatAnomalyShort(anomalies), `compact-status ${statusClass(getHighestAnomalySeverity(anomalies))}`, anomalies.join(", "))
    : createTextCell("-", "row-sub");
  setRowInteractive(
    row,
    selected,
    onActivate,
    `归档 ${item.title || item.token || "-"}，token ${item.token || "-"}，状态 ${formatStatusLabel(item.archiveStatus || "missing")}`,
  );

  row.append(
    createStatusBadge(item.archiveStatus || "missing"),
    createTextCell(item.token || "-", "row-main mono-cell"),
    createTextCell(item.accountKey || "-", "row-sub"),
    createTextCell(item.title || item.token || "-", "row-main"),
    createTextCell(shortText(item.sourceUrl, 26), "row-sub", item.sourceUrl || ""),
    capture,
    assets,
    createFileStateCell(item.files?.hasRawHtml ? "OK" : "missing", item.files?.hasRawHtml),
    createFileStateCell(item.mhtmlComplete ? "OK" : "missing", item.mhtmlComplete),
    createFileStateCell(item.pdfComplete ? "OK" : "missing", item.pdfComplete),
    createTextCell(shortText(item.lastError, 24), "row-sub", item.lastError || ""),
    anomaly,
    createTextCell(formatClockTime(item.archivedAt), "row-sub mono-cell"),
  );
  return row;
}

export function createArchiveLiveRow({ item, selected, onActivate }) {
  const row = document.createElement("li");
  row.className = "archive-row-v2";
  const archiveKey = item.token || item.sourceUrl || item.outDir || "";
  setPcuiRowMetadata(row, {
    rowKey: archiveKey,
    rowKind: "archive",
    rowObjectId: archiveKey,
  });
  if (selected) {
    row.classList.add("is-selected");
  }

  const captureLabel = item.archiveStatus === "running" ? "capturing" : item.captureComplete ? "OK" : "queued";
  const anomaly = item.archiveStatus === "failed"
    ? createTextCell("LIVE_FAILED", "compact-status status-error")
    : createTextCell("-", "row-sub");
  setRowInteractive(
    row,
    selected,
    onActivate,
    `Live 归档 ${item.title || item.token || "-"}，token ${item.token || "-"}，状态 ${formatStatusLabel(item.archiveStatus || "queued")}`,
  );

  row.append(
    createStatusBadge(item.archiveStatus || "queued"),
    createTextCell(item.token || "-", "row-main mono-cell", item.sourceUrl || item.token || ""),
    createTextCell(item.accountKey || "-", "row-sub"),
    createTextCell(item.title || item.token || "-", "row-main"),
    createTextCell(shortText(item.sourceUrl, 26), "row-sub", item.sourceUrl || ""),
    createFileStateCell(captureLabel, item.captureComplete, item.archiveStatus === "running" ? "running" : "warning"),
    createFileStateCell("pending", false, "warning"),
    createFileStateCell(item.captureComplete ? "OK" : "missing", item.captureComplete),
    createFileStateCell("pending", false, "warning"),
    createFileStateCell("pending", false, "warning"),
    createTextCell(shortText(item.lastError || formatPhaseLabel(item.livePhase), 24), "row-sub", item.lastError || item.livePhase || ""),
    anomaly,
    createTextCell(formatClockTime(item.endedAt || item.startedAt), "row-sub mono-cell"),
  );
  return row;
}

export function createProcessRow({ item, itemId, selected, onActivate }) {
  const row = document.createElement("li");
  row.className = "process-row";
  row.dataset.itemId = itemId;
  setPcuiRowMetadata(row, {
    rowKey: itemId,
    rowKind: "process",
    rowObjectId: itemId,
  });
  if (selected) {
    row.classList.add("is-selected");
  }

  const phase = formatPhaseLabel(item.phase || item.status || "queued");
  const ocrWarning = (item.warnings || []).some((warning) => String(warning).toLowerCase().includes("ocr"));
  const ocrStatus = item.files?.posterOcr?.exists ? "ok" : ocrWarning ? "missing" : "skipped";
  setRowInteractive(
    row,
    selected,
    onActivate,
    `文章 ${item.title || itemId || "-"}，标识 ${itemId || "-"}，状态 ${formatStatusLabel(item.status || "queued")}，阶段 ${phase}`,
  );

  row.append(
    createStatusBadge(item.status || "queued"),
    createTextCell(item.token || item.articleId || "-", "row-main mono-cell"),
    createTextCell(item.accountName || "-", "row-sub"),
    createTextCell(item.title || item.articleId || item.relativeInputPath || item.inputPath || "-", "row-main", [item.title, item.articleId, item.relativeInputPath].filter(Boolean).join(" | ")),
    createTextCell(phase, "row-main"),
    createFileStateCell(formatStatusLabel(item.qualityStatus || "unknown"), ["ok", "ready"].includes(item.qualityStatus), item.qualityStatus === "warning" ? "warning" : item.qualityStatus || "unknown"),
    createFileStateCell(item.sidecarStatus || "missing", item.sidecarStatus === "ready"),
    createFileStateCell(item.llmInputStatus || "missing", item.llmInputStatus === "ready"),
    createFileStateCell(formatStatusLabel(ocrStatus), ocrStatus === "ok", ocrStatus === "missing" ? "missing" : "skipped"),
    createFileStateCell(item.downstreamStatus || "not-run", ["ready", "done"].includes(item.downstreamStatus), item.downstreamStatus || "pending"),
    createTextCell(item.warningCount ? String(item.warningCount) : item.errorMessage ? "1" : "-", item.warningCount || item.errorMessage ? "compact-status status-warning" : "row-sub"),
    createTextCell(formatClockTime(item.updatedAt || item.endedAt), "row-sub mono-cell"),
  );
  return row;
}

export function createArtifactRow({ item, selected, onActivate, generatedAt }) {
  const row = document.createElement("li");
  row.className = "artifact-row";
  const artifactKey = getArtifactRowKey(item);
  setPcuiRowMetadata(row, {
    rowKey: artifactKey,
    rowKind: "artifact",
    rowObjectId: artifactKey,
  });
  if (selected) {
    row.classList.add("is-selected");
  }

  const missingArtifacts = Array.isArray(item.missing_artifacts)
    ? item.missing_artifacts
    : Array.isArray(item.missing_outputs)
      ? item.missing_outputs
      : [];
  const provenanceReady = item.provenance === "complete" || Boolean(item.source_url || item.source_archive_dir || item.source_artifact_dir);
  const missingText = missingArtifacts.length
    ? missingArtifacts.slice(0, 2).join(", ")
    : item.quality_grade === "blocked" ? "blocked" : "-";
  setRowInteractive(
    row,
    selected,
    onActivate,
    `产物 ${item.title || item.token || "-"}，token ${item.token || "-"}，质量 ${formatStatusLabel(item.quality_grade || "unknown")}`,
  );

  row.append(
    createFileStateCell(formatStatusLabel(item.quality_grade || "unknown"), ["ready", "finalized"].includes(item.quality_grade), item.quality_grade || "unknown"),
    createTextCell(item.token || "-", "row-main mono-cell"),
    createTextCell(item.account || "-", "row-sub"),
    createTextCell(item.title || "-", "row-main"),
    createTextCell(item.release || item.release_version || "final_pack", "row-sub mono-cell"),
    createTextCell(String(item.warning_count || 0), item.warning_count ? "compact-status status-warning" : "row-sub mono-cell"),
    createTextCell(formatNumber(item.local_image_count), "row-main mono-cell"),
    createTextCell(formatCompactNumber(item.main_content_chars), "row-sub mono-cell"),
    createTextCell(formatCompactNumber(item.background_recall_chars), "row-sub mono-cell"),
    createFileStateCell(provenanceReady ? "complete" : "incomplete", provenanceReady, "warning"),
    createTextCell(missingText, missingText === "-" ? "row-sub" : "compact-status status-error", missingText),
    createTextCell(formatClockTime(item.processed_at || item.updated_at || generatedAt), "row-sub mono-cell"),
  );
  return row;
}
