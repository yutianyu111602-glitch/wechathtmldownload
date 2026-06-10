import { getArtifactRowKey } from "./pcuiContract.js";
import { parseDate } from "./pcuiFormat.js";
import {
  detectArchiveAnomalies,
  detectCollectAnomalies,
} from "./pcuiAnomalies.js";
import {
  buildArchiveRowsFromSnapshot,
  buildCollectAccountsFromSnapshot,
} from "./pcuiSnapshotAdapters.js";
import { createPcuiProjectionCache } from "./pcuiProjectionCache.js";
import {
  createPcuiSearchIndex,
  createPcuiSearchQuery,
} from "./pcuiSearchIndex.js";

const EMPTY_ROWS = Object.freeze([]);

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function getSourceRows(value) {
  return Array.isArray(value) ? value : EMPTY_ROWS;
}

function limitRows(rows, limit) {
  return Number.isFinite(limit) ? rows.slice(0, limit) : rows;
}

export function getProcessItemId(item) {
  return item?.articleId || item?.token || item?.relativeInputPath || item?.inputPath || "";
}

function sortTaskBusRows(rows) {
  return rows
    .map((item, index) => ({
      item,
      index,
      running: item.status === "running",
      sortTime: parseDate(item.endedAt || item.startedAt),
    }))
    .sort((left, right) => {
      if (left.running && !right.running) {
        return -1;
      }
      if (right.running && !left.running) {
        return 1;
      }
      return right.sortTime - left.sortTime || left.index - right.index;
    })
    .map((entry) => entry.item);
}

function sortProcessRows(rows) {
  return rows
    .map((item, index) => ({
      item,
      index,
      running: item.status === "running",
      sortTime: parseDate(item.updatedAt || item.endedAt || item.startedAt),
    }))
    .sort((left, right) => {
      if (left.running && !right.running) {
        return -1;
      }
      if (right.running && !left.running) {
        return 1;
      }
      return right.sortTime - left.sortTime || left.index - right.index;
    })
    .map((entry) => entry.item);
}

export function createPcuiWorkspaceControllers({ appState, selectionController } = {}) {
  const projectionCache = createPcuiProjectionCache({ maxEntries: 48 });
  const lookupStats = {
    mapBuildCount: 0,
    mapHitCount: 0,
    fallbackScanCount: 0,
  };
  const taskBusSearchIndex = createPcuiSearchIndex({
    workspace: "task-bus",
    matchesFilter: (item, filter) => {
      if (filter === "running" && item.status !== "running") {
        return false;
      }
      if (filter === "failed" && item.status !== "failed") {
        return false;
      }
      if (filter === "done" && !["succeeded", "skipped", "completed"].includes(item.status)) {
        return false;
      }
      return true;
    },
    getSearchFields: (item) => [
      item.relativeInputPath,
      item.inputPath,
      item.message,
      item.errorMessage,
      item.phase,
    ],
  });
  const collectSearchIndex = createPcuiSearchIndex({
    workspace: "collect",
    matchesFilter: (account, filter) => {
      const anomalies = detectCollectAnomalies(account);
      if (filter === "failed" && !anomalies.length) {
        return false;
      }
      if (filter === "ready" && !(account.enqueuedCount > 0)) {
        return false;
      }
      return true;
    },
    getSearchFields: (account) => [
      account.nickname,
      account.accountName,
      account.fakeid,
      account.biz,
      account.status,
      account.lastTitle,
    ],
  });
  const archiveSearchIndex = createPcuiSearchIndex({
    workspace: "archive",
    matchesFilter: (item, filter) => {
      const anomalies = detectArchiveAnomalies(item);
      if (filter === "incomplete" && item.captureComplete && item.assetsComplete) {
        return false;
      }
      if (filter === "conflict" && !anomalies.some((value) => value.includes("CONFLICT") || value.includes("MISMATCH"))) {
        return false;
      }
      return true;
    },
    getSearchFields: (item) => [
      item.token,
      item.accountKey,
      item.accountName,
      item.archiveStatus,
      item.title,
      item.url,
    ],
  });
  const processSearchIndex = createPcuiSearchIndex({
    workspace: "process",
    matchesFilter: (item, filter) => {
      if (filter === "failed" && item.status !== "failed") {
        return false;
      }
      if (filter === "missing") {
        const hasArtifacts = item.sidecarStatus === "ready" && item.llmInputStatus === "ready";
        return !hasArtifacts;
      }
      return true;
    },
    getSearchFields: (item) => [
      item.articleId,
      item.token,
      item.accountName,
      item.title,
      item.relativeInputPath,
      item.inputPath,
      item.llmInputPath,
      item.markdownMirrorPath,
      item.downstreamStatus,
      item.downstreamProvider,
      item.message,
      item.errorMessage,
      item.status,
      item.phase,
      item.warning,
    ],
  });
  const artifactSearchIndex = createPcuiSearchIndex({
    workspace: "artifact",
    matchesFilter: (item, filter) => {
      if (filter === "ready" && item.quality_grade !== "ready") {
        return false;
      }
      if (filter === "review" && item.quality_grade !== "review") {
        return false;
      }
      if (filter === "blocked" && item.quality_grade !== "blocked") {
        return false;
      }
      return true;
    },
    getSearchFields: (item) => [
      item.token,
      item.account,
      item.account_name,
      item.title,
      item.provenance,
      item.review_reason,
    ],
  });

  function getQuery(workspace, filter, searchText) {
    return createPcuiSearchQuery({ workspace, filter, searchText });
  }

  function getTaskBusQuery() {
    return getQuery("task-bus", appState.taskBusFilter, appState.taskBusSearchText);
  }

  function getCollectQuery() {
    return getQuery("collect", appState.collectFilter, appState.collectSearchText);
  }

  function getArchiveQuery() {
    return getQuery("archive", appState.archiveFilter, appState.archiveSearchText);
  }

  function getProcessQuery() {
    return getQuery("process", appState.processFilter, appState.processSearchText);
  }

  function getArtifactQuery() {
    return getQuery("artifact", appState.artifactFilter, appState.artifactSearchText);
  }

  function buildRowLookupMap(rows, getKey) {
    const map = new Map();
    if (typeof getKey !== "function") {
      return map;
    }
    lookupStats.mapBuildCount += 1;
    for (const row of rows || []) {
      const key = getKey(row);
      if (key) {
        map.set(key, row);
      }
    }
    return map;
  }

  function getMapSelectedItem(rowByKey, key) {
    if (key && rowByKey?.has(key)) {
      lookupStats.mapHitCount += 1;
      return rowByKey.get(key);
    }
    return null;
  }

  function getRowSetSelectedItem(rowSet, key) {
    return getMapSelectedItem(rowSet?.sourceRowByKey, key)
      || getMapSelectedItem(rowSet?.rowByKey, key);
  }

  function getMapSelectedItems(rowByKey, selectedKeys) {
    if (!rowByKey || !selectedKeys?.size) {
      return [];
    }
    const selected = [];
    for (const key of selectedKeys) {
      if (rowByKey.has(key)) {
        lookupStats.mapHitCount += 1;
        selected.push(rowByKey.get(key));
      }
    }
    return selected;
  }

  function findSelectedItemFallback(workspace, rows, getKey) {
    if (appState.getSelection?.(workspace)) {
      lookupStats.fallbackScanCount += 1;
    }
    return selectionController.findSelectedItem(workspace, rows, getKey);
  }

  function getCachedRowSet({ workspace, rootKey = "", source, projection = null, queryKey = "", buildRows, getKey, limit = Infinity }) {
    const result = projectionCache.getOrNormalizeSync({
      workspace,
      rootKey,
      projection,
      rows: source,
      queryKey,
      normalize: () => {
        const rows = buildRows();
        return {
          rows,
          rowByKey: buildRowLookupMap(rows, getKey),
          sourceRowByKey: buildRowLookupMap(source, getKey),
        };
      },
    });
    if (!result.ok) {
      throw result.error;
    }
    return {
      rows: limitRows(result.value.rows, limit),
      rowByKey: result.value.rowByKey,
      sourceRowByKey: result.value.sourceRowByKey,
      allRows: result.value.rows,
    };
  }

  function getCachedView({ workspace, rootKey = "", source, projection = null, queryKey = "", buildView, getKey, limit = Infinity }) {
    const result = projectionCache.getOrNormalizeSync({
      workspace,
      rootKey,
      projection,
      rows: source,
      queryKey,
      normalize: () => {
        const view = buildView();
        const sourceRows = Array.isArray(view.sourceRows) ? view.sourceRows : source;
        return {
          ...view,
          rowByKey: buildRowLookupMap(view.rows || EMPTY_ROWS, getKey),
          sourceRowByKey: buildRowLookupMap(sourceRows, getKey),
        };
      },
    });
    if (!result.ok) {
      throw result.error;
    }
    return {
      ...result.value,
      rows: limitRows(result.value.rows, limit),
    };
  }

  function taskBusItemMatches(item) {
    return taskBusSearchIndex.matches(item, getTaskBusQuery());
  }

  function getTaskBusRowSet(snapshot, { limit = Infinity } = {}) {
    const source = getSourceRows(snapshot?.items);
    const query = getTaskBusQuery();
    return getCachedRowSet({
      workspace: "task-bus",
      projection: snapshot,
      source,
      queryKey: query.key,
      getKey: (item) => item.inputPath,
      limit,
      buildRows: () => sortTaskBusRows(taskBusSearchIndex.filterRows(source, query)),
    });
  }

  function getTaskBusRows(snapshot, { limit = Infinity } = {}) {
    return getTaskBusRowSet(snapshot, { limit }).rows;
  }

  function getActiveTaskItem(snapshot) {
    const items = getSourceRows(snapshot?.items);
    if (!items.length) {
      return null;
    }

    const rowSet = getTaskBusRowSet(snapshot);
    const selected = getRowSetSelectedItem(rowSet, appState.selectedTaskItemPath)
      || findSelectedItemFallback("task-bus", items, (item) => item.inputPath);
    if (selected) {
      return selected;
    }

    if (snapshot.currentFile) {
      const current = items.find((item) => item.inputPath === snapshot.currentFile);
      if (current) {
        selectionController.setSelectedKey("task-bus", current.inputPath);
        return current;
      }
    }

    const fallback = getTaskBusRows(snapshot, { limit: 1 })[0] || items[0] || null;
    if (fallback) {
      selectionController.setSelectedKey("task-bus", fallback.inputPath);
    }
    return fallback;
  }

  function collectItemMatches(account) {
    return collectSearchIndex.matches(account, getCollectQuery());
  }

  function getCollectRowSet(state, { limit = Infinity } = {}) {
    const source = getSourceRows(state?.accounts);
    const query = getCollectQuery();
    return getCachedRowSet({
      workspace: "collect",
      rootKey: state?.sources?.rootDir?.path || "",
      projection: state,
      source,
      queryKey: query.key,
      getKey: (account) => account.fakeid,
      limit,
      buildRows: () => collectSearchIndex.filterRows(source, query),
    });
  }

  function getCollectRows(state, { limit = Infinity } = {}) {
    return getCollectRowSet(state, { limit }).rows;
  }

  function getCollectLiveView(snapshot, { limit = Infinity } = {}) {
    const source = getSourceRows(snapshot?.items);
    const query = getCollectQuery();
    return getCachedView({
      workspace: "collect-live",
      rootKey: snapshot?.inputRoot || "",
      projection: snapshot,
      source,
      queryKey: query.key,
      getKey: (account) => account.fakeid,
      limit,
      buildView: () => {
        const sourceRows = buildCollectAccountsFromSnapshot(snapshot);
        return {
          sourceRows,
          rows: collectSearchIndex.filterRows(sourceRows, query),
        };
      },
    });
  }

  function archiveItemMatches(item) {
    return archiveSearchIndex.matches(item, getArchiveQuery());
  }

  function getArchiveRowSet(state, { limit = Infinity } = {}) {
    const source = getSourceRows(state?.items);
    const query = getArchiveQuery();
    return getCachedRowSet({
      workspace: "archive",
      rootKey: state?.sources?.archiveRoot?.path || "",
      projection: state,
      source,
      queryKey: query.key,
      getKey: (item) => item.token,
      limit,
      buildRows: () => archiveSearchIndex.filterRows(source, query),
    });
  }

  function getArchiveRows(state, { limit = Infinity } = {}) {
    return getArchiveRowSet(state, { limit }).rows;
  }

  function getArchiveLiveView(snapshot, { limit = Infinity } = {}) {
    const source = getSourceRows(snapshot?.items);
    const query = getArchiveQuery();
    return getCachedView({
      workspace: "archive-live",
      rootKey: snapshot?.outRoot || "",
      projection: snapshot,
      source,
      queryKey: query.key,
      getKey: (item) => item.token,
      limit,
      buildView: () => {
        const sourceRows = buildArchiveRowsFromSnapshot(snapshot);
        return {
          sourceRows,
          rows: archiveSearchIndex.filterRows(sourceRows, query),
          failedCount: sourceRows.filter((item) => item.archiveStatus === "failed").length,
          doneCount: sourceRows.filter((item) => item.captureComplete).length,
        };
      },
    });
  }

  function processItemMatches(item) {
    return processSearchIndex.matches(item, getProcessQuery());
  }

  function getProcessRowSet(state = appState.latestProcessState, { limit = Infinity } = {}) {
    const source = getSourceRows(state?.items);
    const query = getProcessQuery();
    return getCachedRowSet({
      workspace: "process",
      rootKey: state?.sources?.outRoot?.path || "",
      projection: state,
      source,
      queryKey: query.key,
      getKey: getProcessItemId,
      limit,
      buildRows: () => sortProcessRows(processSearchIndex.filterRows(source, query)),
    });
  }

  function getProcessRows(state = appState.latestProcessState, { limit = Infinity } = {}) {
    return getProcessRowSet(state, { limit }).rows;
  }

  function artifactItemMatches(item) {
    return artifactSearchIndex.matches(item, getArtifactQuery());
  }

  function getArtifactRowSet(projection, { limit = Infinity } = {}) {
    const source = getSourceRows(projection?.indexRows);
    const query = getArtifactQuery();
    return getCachedRowSet({
      workspace: "artifact",
      rootKey: projection?.releaseRoot || "",
      projection,
      source,
      queryKey: query.key,
      getKey: getArtifactRowKey,
      limit,
      buildRows: () => artifactSearchIndex.filterRows(source, query),
    });
  }

  function getArtifactRows(projection, { limit = Infinity } = {}) {
    return getArtifactRowSet(projection, { limit }).rows;
  }

  function invalidateProjectionCache(options) {
    projectionCache.invalidate(options || {});
  }

  return {
    taskBus: {
      itemMatches: taskBusItemMatches,
      getRows: getTaskBusRows,
      getActiveItem: getActiveTaskItem,
    },
    collect: {
      itemMatches: collectItemMatches,
      getRows: getCollectRows,
      getLiveView: getCollectLiveView,
      getSelectedItem: () => {
        const selectedKey = appState.selectedCollectFakeid;
        if (appState.latestCollectState?.accounts?.length) {
          const hit = getRowSetSelectedItem(getCollectRowSet(appState.latestCollectState), selectedKey);
          if (hit) {
            return hit;
          }
        }
        return findSelectedItemFallback(
          "collect",
          [...asArray(appState.latestCollectState?.accounts), ...asArray(appState.latestCollectLiveAccounts)],
          (item) => item.fakeid,
        );
      },
      getSelectedItems: () => getMapSelectedItems(
        getCollectRowSet(appState.latestCollectState).sourceRowByKey,
        appState.selectedCollectFakeids,
      ),
    },
    archive: {
      itemMatches: archiveItemMatches,
      getRows: getArchiveRows,
      getLiveView: getArchiveLiveView,
      getSelectedItem: () => {
        const selectedKey = appState.selectedArchiveToken;
        if (appState.latestArchiveState?.items?.length) {
          const hit = getRowSetSelectedItem(getArchiveRowSet(appState.latestArchiveState), selectedKey);
          if (hit) {
            return hit;
          }
        }
        return findSelectedItemFallback(
          "archive",
          [...asArray(appState.latestArchiveState?.items), ...asArray(appState.latestArchiveLiveRows)],
          (item) => item.token,
        );
      },
      getSelectedItems: () => getMapSelectedItems(
        getArchiveRowSet(appState.latestArchiveState).sourceRowByKey,
        appState.selectedArchiveTokens,
      ),
    },
    process: {
      itemMatches: processItemMatches,
      getItemId: getProcessItemId,
      getRows: getProcessRows,
      getSelectedItem: () => {
        const hit = getRowSetSelectedItem(getProcessRowSet(), appState.selectedProcessItemId);
        if (hit) {
          return hit;
        }
        return findSelectedItemFallback("process", getProcessRows(), getProcessItemId);
      },
      getSelectedItems: () => getMapSelectedItems(
        getProcessRowSet().sourceRowByKey,
        appState.selectedProcessItemIds,
      ),
    },
    artifact: {
      itemMatches: artifactItemMatches,
      getRows: getArtifactRows,
      getSelectedItem: (projection = appState.latestFinalPackProjection) => {
        const hit = getRowSetSelectedItem(getArtifactRowSet(projection), appState.selectedArtifactRowKey);
        if (hit) {
          return hit;
        }
        return findSelectedItemFallback("artifact", asArray(projection?.indexRows), getArtifactRowKey);
      },
    },
    invalidateProjectionCache,
    getProjectionCacheStats: projectionCache.getStats,
    getLookupStats: () => ({ ...lookupStats }),
  };
}
