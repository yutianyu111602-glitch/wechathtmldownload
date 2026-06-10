import {
  DEFAULT_MARKDOWN_MIRROR_ROOT as DEFAULT_RAWWECHAT_LLM_MD_OUTPUT,
  formatPhaseLabel,
  formatStatusLabel,
} from "./pcuiContract.js";
import { formatShortDateTime } from "./pcuiFormat.js";
import {
  detectArchiveAnomalies,
  detectCollectAnomalies,
  formatAnomalyShort,
} from "./pcuiAnomalies.js";
import {
  clearInspectorExtraSection,
  renderInspectorExtraSection,
} from "./pcuiInspectorDom.js";

function text(value, fallback = "-") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function applyDetail(refs, labels, values) {
  refs.detailLabel1.textContent = labels[0] || "";
  refs.detailLabel2.textContent = labels[1] || "";
  refs.detailLabel3.textContent = labels[2] || "";
  refs.detailLabel4.textContent = labels[3] || "";
  refs.detailLabel5.textContent = labels[4] || "";
  refs.detailInputRoot.textContent = text(values[0]);
  refs.detailOutputRoot.textContent = text(values[1]);
  refs.detailOutDir.textContent = text(values[2]);
  refs.detailCurrentStatus.textContent = text(values[3]);
  refs.detailCurrentMessage.textContent = text(values[4]);
}

function applyActions(refs, primary, secondary, tertiary) {
  refs.inspectorActionPrimary.textContent = primary;
  refs.inspectorActionSecondary.textContent = secondary;
  refs.inspectorActionTertiary.textContent = tertiary;
}

export function createPcuiInspectorController({
  appState,
  selectionController,
  workspaceControllers,
  refs,
  workspaceMeta,
  getActiveTaskItem,
  getProcessModeMeta,
  buildRunStateText,
  roots,
}) {
  function renderExtra(title, groups) {
    renderInspectorExtraSection({
      inspectorExtra: refs.inspectorExtra,
      inspectorExtraTitle: refs.inspectorExtraTitle,
    }, title, groups);
  }

  function clearExtra() {
    clearInspectorExtraSection({
      inspectorExtra: refs.inspectorExtra,
      inspectorExtraTitle: refs.inspectorExtraTitle,
    });
  }

  function updateMultiSelectInspector(workspace) {
    const count = selectionController.getMultiSelectCount(workspace);
    refs.inspectorSelectionTitle.textContent = `已选择 ${count} 项`;
    refs.inspectorSelectionSubtitle.textContent = `在 ${workspaceMeta[workspace].title} 中选择了 ${count} 个对象`;
    applyDetail(refs, [
      "选择统计",
      "工作区",
      "",
      "",
      "",
    ], [
      `${count} 项已选择`,
      workspaceMeta[workspace].title,
      "-",
      "-",
      "使用 Ctrl/Cmd 或 Shift 进行多选，点击下方按钮执行批量操作。",
    ]);
    applyActions(refs, "批量打开目录", "批量复制标识", "清除选择");
    renderExtra("批量状态", [
      {
        title: "选择",
        rows: [
          ["工作区", workspaceMeta[workspace].title],
          ["对象数", count],
          ["动作", "open / copy / clear"],
        ],
      },
    ]);
  }

  function updateTaskBusInspector() {
    const snapshot = appState.latestSnapshot;
    if (!snapshot) {
      return false;
    }
    const activeItem = getActiveTaskItem(snapshot);
    refs.inspectorSelectionTitle.textContent = activeItem?.relativeInputPath || snapshot.currentFile || "当前没有活动对象。";
    refs.inspectorSelectionSubtitle.textContent = buildRunStateText(snapshot);
    applyDetail(refs, [
      "输入根目录",
      "输出根目录",
      "当前输出目录",
      "当前状态",
      "当前消息",
    ], [
      snapshot.inputRoot || "-",
      snapshot.outRoot || "-",
      activeItem?.outDir || "-",
      `${formatStatusLabel(snapshot.status || "idle")} / ${formatPhaseLabel(snapshot.currentPhase || activeItem?.phase || "idle")}`,
      activeItem?.errorMessage || activeItem?.message || buildRunStateText(snapshot),
    ]);
    applyActions(refs, activeItem?.outDir ? "打开当前输出目录" : "打开输出根目录", "刷新任务总线", "切到失败流");
    renderExtra("运行分区", [
      {
        title: "概览",
        rows: [
          ["Run ID", snapshot.runId || snapshot.id || "-"],
          ["模式", snapshot.pipeline || "dual-track"],
          ["当前阶段", formatPhaseLabel(snapshot.currentPhase || activeItem?.phase || "idle")],
          ["最近活动", activeItem?.message || activeItem?.errorMessage || "-"],
        ],
      },
      {
        title: "统计",
        rows: [
          ["总数", snapshot.totalItems || 0],
          ["已完成", snapshot.completedCount || 0],
          ["失败", snapshot.failedCount || 0],
          ["队列", snapshot.queuedCount || 0],
        ],
      },
    ]);
    return true;
  }

  function updateCollectInspector() {
    if (selectionController.isMultiSelect("collect")) {
      updateMultiSelectInspector("collect");
      return;
    }
    const selected = workspaceControllers.collect.getSelectedItem();
    const anomalies = selected ? detectCollectAnomalies(selected) : [];
    const state = appState.latestCollectState;
    refs.inspectorSelectionTitle.textContent = selected?.nickname || "当前没有账号对象。";
    refs.inspectorSelectionSubtitle.textContent = state
      ? `采集状态：${formatStatusLabel(state.status)} · Ready Queue ${state.summary.readyQueueCount}`
      : "等待读取 discovery 状态。";
    applyDetail(refs, [
      "Discovery 根目录",
      "Prefetch 状态",
      "Queue 诊断",
      "异常码",
      "建议动作",
    ], [
      state?.sources?.rootDir?.path || roots.getDiscoveryRoot(),
      state?.sources?.prefetchStatusPath?.path || "-",
      selected
        ? `已发现 ${selected.discoveredCount} / 入队 ${selected.enqueuedCount}${selected.discoveredCount !== selected.enqueuedCount ? ` (差值 ${selected.discoveredCount - selected.enqueuedCount})` : ""}`
        : (state?.sources?.queuePath?.path || "-"),
      anomalies.length ? formatAnomalyShort(anomalies) : (selected ? formatStatusLabel(selected.status) : formatStatusLabel(state?.status || "missing")),
      selected
        ? (anomalies.length ? `发现 ${anomalies.length} 个异常: ${anomalies.join(", ")}` : "账号状态正常。")
        : (state?.warnings?.[0] || "等待读取本地 discovery 状态。"),
    ]);
    applyActions(refs, "打开 discovery 根目录", "刷新采集状态", anomalies.length ? "查看异常详情" : "切到系统消息");
    renderExtra("账号分区", [
      {
        title: "账号摘要",
        rows: [
          ["fakeid", selected?.fakeid || "-"],
          ["昵称", selected?.nickname || "-"],
          ["Biz", selected?.biz || selected?.accountKey || "-"],
          ["来源", state?.sources?.rootDir?.path || roots.getDiscoveryRoot()],
        ],
      },
      {
        title: "发现进度",
        rows: [
          ["已发现", selected?.discoveredCount || 0],
          ["已入队", selected?.enqueuedCount || 0],
          ["重复", selected?.duplicateCount || 0],
          ["最近发现", formatShortDateTime(selected?.lastDiscoveredAt)],
        ],
      },
      {
        title: "API readiness",
        rows: [
          ["状态", anomalies.length ? "需要处理" : "valid"],
          ["错误", selected?.errorMessage || "-"],
          ["建议", anomalies.length ? "查看异常并重试采集" : "继续入队或刷新发现"],
        ],
      },
    ]);
  }

  function updateArchiveInspector() {
    if (selectionController.isMultiSelect("archive")) {
      updateMultiSelectInspector("archive");
      return;
    }
    const selected = workspaceControllers.archive.getSelectedItem();
    const anomalies = selected ? detectArchiveAnomalies(selected) : [];
    const state = appState.latestArchiveState;
    refs.inspectorSelectionTitle.textContent = selected?.token || "当前没有 bundle 对象。";
    refs.inspectorSelectionSubtitle.textContent = state
      ? `归档状态：${formatStatusLabel(state.status)} · Bundle ${state.summary.bundles.seen}`
      : "等待读取 archive 状态。";
    applyDetail(refs, [
      "Archive Root",
      "Capture 完整度",
      "Assets 保留",
      "异常码",
      "建议动作",
    ], [
      state?.sources?.archiveRoot?.path || roots.getArchiveRoot(),
      selected
        ? `raw.html: ${selected.captureComplete ? "✓" : "✗"} / mhtml: ${selected.mhtmlComplete ? "✓" : "✗"} / pdf: ${selected.pdfComplete ? "✓" : "✗"}`
        : state?.sources?.archiveStatusPath?.path || "-",
      selected
        ? `${selected.assetsComplete ? `图片 ${selected.imageCount} / 媒体 ${selected.mediaCount}` : "未执行资源保留"}${selected.assetsComplete && !selected.imageCount ? " (状态与文件冲突)" : ""}`
        : "-",
      anomalies.length ? formatAnomalyShort(anomalies) : (selected ? formatStatusLabel(selected.archiveStatus) : formatStatusLabel(state?.status || "missing")),
      selected
        ? (anomalies.length ? `发现 ${anomalies.length} 个异常: ${anomalies.join(", ")}` : "Bundle 完整度正常。")
        : (state?.warnings?.[0] || "等待读取本地 archive 状态。"),
    ]);
    applyActions(refs, selected?.outDir ? "打开 bundle 目录" : "打开 archive 根目录", "刷新归档状态", anomalies.length ? "查看异常详情" : "切到系统消息");
    renderExtra("Bundle 分区", [
      {
        title: "概览",
        rows: [
          ["Token", selected?.token || "-"],
          ["账号", selected?.accountKey || "-"],
          ["标题", selected?.title || "-"],
          ["sourceUrl", selected?.sourceUrl || "-"],
        ],
      },
      {
        title: "Capture",
        rows: [
          ["raw.html", selected?.files?.hasRawHtml ? "OK" : "missing"],
          ["page.mhtml", selected?.mhtmlComplete ? "OK" : "missing"],
          ["page.pdf", selected?.pdfComplete ? "OK" : "missing"],
          ["capture", selected?.captureComplete ? "complete" : "partial"],
        ],
      },
      {
        title: "Assets",
        rows: [
          ["assets_local", selected?.files?.hasAssetsLocal ? "OK" : "missing"],
          ["图片数", selected?.imageCount || 0],
          ["媒体数", selected?.mediaCount || 0],
          ["异常", anomalies.length ? anomalies.join(", ") : "-"],
        ],
      },
    ]);
  }

  function updateProcessInspector() {
    if (selectionController.isMultiSelect("process")) {
      updateMultiSelectInspector("process");
      return;
    }
    const selected = workspaceControllers.process.getSelectedItem();
    const state = appState.latestProcessState;
    const modeMeta = getProcessModeMeta();
    refs.inspectorSelectionTitle.textContent = selected?.title || selected?.articleId || selected?.relativeInputPath || selected?.inputPath || "当前没有文章对象。";
    refs.inspectorSelectionSubtitle.textContent = state
      ? `${modeMeta.label}：${formatStatusLabel(state.status)} · Bundle ${state.summary?.totalItems || state.items?.length || 0}`
      : "等待读取 article bundle 状态。";

    if (appState.processMode === "llm") {
      applyDetail(refs, [
        "LLM Input",
        "Markdown Mirror",
        "Downstream",
        "质量 / 警告",
        "最近错误",
      ], [
        selected?.files?.llmInput?.path || selected?.outDir || "-",
        DEFAULT_RAWWECHAT_LLM_MD_OUTPUT,
        selected ? (selected.downstreamStatus || "not-run") : "-",
        selected ? `llm ${selected.llmInputStatus || "missing"} / downstream ${selected.downstreamStatus || "not-run"}` : formatStatusLabel(state?.status || "missing"),
        selected
          ? (selected.errorMessage || `Quality: ${selected.qualityStatus || "unknown"} · Warnings: ${selected.warningCount || 0}`)
          : (state?.warnings?.[0] || "LLM 输入与下游结果会在这里显示。"),
      ]);
    } else if (appState.processMode === "downstream") {
      applyDetail(refs, [
        "Article ID",
        "Downstream Manifest",
        "Downstream Result",
        "Downstream 状态",
        "最近错误",
      ], [
        selected?.articleId || selected?.token || "-",
        selected?.files?.downstreamManifest?.path || "-",
        selected?.files?.downstreamResult?.path || "-",
        selected ? (selected.downstreamStatus || "not-run") : formatStatusLabel(state?.status || "missing"),
        selected
          ? (selected.errorMessage || `LLM Input: ${selected.llmInputStatus || "missing"} · Quality: ${selected.qualityStatus || "unknown"}`)
          : (state?.warnings?.[0] || "下游 LLM manifest/result 会在这里显示。"),
      ]);
    } else {
      applyDetail(refs, [
        "Article ID",
        "当前阶段",
        "输出目录",
        "Sidecar 状态",
        "LLM Input 状态",
      ], [
        selected?.articleId || selected?.token || selected?.relativeInputPath || selected?.inputPath || "-",
        formatPhaseLabel(selected?.phase || selected?.status || "idle"),
        selected?.outDir || "-",
        selected ? `sidecar ${selected.sidecarStatus || "missing"} / llm ${selected.llmInputStatus || "missing"} / quality ${selected.qualityStatus || "unknown"}` : formatStatusLabel(state?.status || "missing"),
        selected
          ? (selected.errorMessage || `Warnings: ${selected.warningCount || 0} · Downstream: ${selected.downstreamStatus || "not-run"}`)
          : (state?.warnings?.[0] || "处理批次写出 article bundle 产物后，这里会显示文章级处理详情。"),
      ]);
    }
    applyActions(refs, selected?.outDir ? "打开 bundle 目录" : "打开输出根目录", "刷新处理状态", "切到系统消息");
    renderExtra(appState.processMode === "llm" ? "LLM 输入分区" : appState.processMode === "downstream" ? "下游分区" : "处理链分区", [
      {
        title: "概览",
        rows: [
          ["Token", selected?.token || selected?.articleId || "-"],
          ["账号", selected?.accountName || "-"],
          ["标题", selected?.title || "-"],
          ["artifact path", selected?.outDir || "-"],
        ],
      },
      {
        title: "处理状态",
        rows: [
          ["normalize HTML", selected?.phase ? formatPhaseLabel(selected.phase) : "-"],
          ["sidecar", selected?.sidecarStatus || "missing"],
          ["质量", selected?.qualityStatus || "unknown"],
          ["更新时间", formatShortDateTime(selected?.updatedAt || selected?.endedAt)],
        ],
      },
      {
        title: "LLM 输入",
        rows: [
          ["llm_input.md", selected?.llmInputStatus || "missing"],
          ["mirror markdown", DEFAULT_RAWWECHAT_LLM_MD_OUTPUT],
          ["字数", selected?.llmCharCount || "-"],
          ["警告", selected?.warningCount || 0],
        ],
      },
      {
        title: "Downstream",
        rows: [
          ["provider", selected?.provider || "openai/local"],
          ["stage", selected?.downstreamStatus || "not-run"],
          ["result path", selected?.files?.downstreamResult?.path || "-"],
          ["最近错误", selected?.errorMessage || "-"],
        ],
      },
    ]);
  }

  function updateArtifactInspector() {
    const selectedKey = selectionController.getSelectedKey("artifact");
    const selected = workspaceControllers.artifact.getSelectedItem(appState.latestFinalPackProjection);
    const projection = appState.latestFinalPackProjection;
    refs.inspectorSelectionTitle.textContent = selected?.title || selectedKey || "当前没有文章对象。";
    refs.inspectorSelectionSubtitle.textContent = projection
      ? `Final Pack: ${projection.copiedArticles || 0} / ${projection.totalArticles || 0} 篇 · Ready ${projection.qualityCounts?.ready || 0}`
      : "等待读取 final pack 状态。";
    applyDetail(refs, [
      "Token",
      "账号",
      "质量等级",
      "警告数",
      "本地图片",
    ], [
      selected?.token || selectedKey || "-",
      selected?.account || "-",
      selected ? formatStatusLabel(selected.quality_grade || "unknown") : "-",
      selected ? String(selected.warning_count || 0) : "-",
      selected
        ? `图片 ${selected.local_image_count || 0} · 正文 ${selected.main_content_chars || 0} 字符 · 背景 ${selected.background_recall_chars || 0} 字符`
        : (projection?.warnings?.[0] || "运行 finalize-llm-pack 后，这里会显示文章级 pack 详情。"),
    ]);
    applyActions(refs, roots.getReleaseRoot() ? "打开 release 根目录" : "打开输出根目录", "刷新 pack 状态", "切到系统消息");
    renderExtra("Pack 分区", [
      {
        title: "质量结论",
        rows: [
          ["quality bucket", selected ? formatStatusLabel(selected.quality_grade || "unknown") : "-"],
          ["ready/review/blocked", projection ? `R ${projection.qualityCounts?.ready || 0} / V ${projection.qualityCounts?.review || 0} / B ${projection.qualityCounts?.blocked || 0}` : "-"],
          ["warning_count", selected?.warning_count || 0],
          ["blocking issues", selected?.blocking_issues?.join?.(", ") || "-"],
        ],
      },
      {
        title: "产物完整度",
        rows: [
          ["llm_input.md", selected?.llm_input_exists === false ? "missing" : "OK"],
          ["result.md", selected?.result_exists === false ? "missing" : "OK"],
          ["images", `${selected?.local_image_count || 0} files`],
          ["final_pack.zip", projection?.copiedArticles ? "OK" : "-"],
        ],
      },
      {
        title: "Provenance",
        rows: [
          ["来源 URL", selected?.source_url || "-"],
          ["archive bundle", selected?.source_archive_dir || "-"],
          ["artifact bundle", selected?.source_artifact_dir || "-"],
          ["生成时间", formatShortDateTime(selected?.processed_at || projection?.generatedAt)],
        ],
      },
    ]);
  }

  function updateFallbackInspector() {
    const activeMeta = workspaceMeta[appState.activeWorkspace];
    refs.inspectorSelectionTitle.textContent = activeMeta.title;
    refs.inspectorSelectionSubtitle.textContent = activeMeta.subtitle;
    applyDetail(refs, [
      "说明 1",
      "说明 2",
      "说明 3",
      "当前状态",
      "当前消息",
    ], [
      "-",
      "-",
      "-",
      "规划中",
      "该工作区保留桌面壳骨架，后续再接真实对象。",
    ]);
    applyActions(refs, "打开输出目录", "刷新当前工作区", "切到活动流");
    clearExtra();
  }

  function update() {
    if (appState.activeWorkspace === "task-bus" && updateTaskBusInspector()) {
      return;
    }
    if (appState.activeWorkspace === "collect") {
      updateCollectInspector();
      return;
    }
    if (appState.activeWorkspace === "archive") {
      updateArchiveInspector();
      return;
    }
    if (appState.activeWorkspace === "process") {
      updateProcessInspector();
      return;
    }
    if (appState.activeWorkspace === "artifact") {
      updateArtifactInspector();
      return;
    }
    updateFallbackInspector();
  }

  return { update };
}
