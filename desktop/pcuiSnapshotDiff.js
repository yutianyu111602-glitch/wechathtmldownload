const EMPTY_ROWS = Object.freeze([]);

function asArray(value) {
  return Array.isArray(value) ? value : EMPTY_ROWS;
}

export function getSnapshotRowKey(row) {
  return row?.inputPath || row?.relativeInputPath || row?.token || row?.articleId || "";
}

export function getSnapshotRowSignature(row = {}) {
  return [
    row.status,
    row.phase,
    row.currentPhase,
    row.message,
    row.errorMessage,
    row.startedAt,
    row.updatedAt,
    row.endedAt,
    row.outDir,
    row.archiveStatus,
    row.assetsStatus,
    row.sidecarStatus,
    row.llmInputStatus,
  ].map((value) => (value === undefined || value === null ? "" : String(value))).join("\u0001");
}

export function diffSnapshotRows(previousRows, nextRows, {
  getRowKey = getSnapshotRowKey,
  getRowSignature = getSnapshotRowSignature,
} = {}) {
  const previousByKey = new Map();
  const nextByKey = new Map();
  const added = [];
  const updated = [];
  const removed = [];
  let unchangedCount = 0;

  for (const row of asArray(previousRows)) {
    const key = getRowKey(row);
    if (!key) {
      continue;
    }
    previousByKey.set(key, { row, signature: getRowSignature(row) });
  }

  for (const row of asArray(nextRows)) {
    const key = getRowKey(row);
    if (!key) {
      continue;
    }
    const signature = getRowSignature(row);
    nextByKey.set(key, { row, signature });
    const previous = previousByKey.get(key);
    if (!previous) {
      added.push({ key, row });
    } else if (previous.signature !== signature) {
      updated.push({ key, previous: previous.row, row });
    } else {
      unchangedCount += 1;
    }
  }

  for (const [key, previous] of previousByKey.entries()) {
    if (!nextByKey.has(key)) {
      removed.push({ key, row: previous.row });
    }
  }

  return {
    added,
    updated,
    removed,
    unchangedCount,
    previousCount: previousByKey.size,
    nextCount: nextByKey.size,
    changed: Boolean(added.length || updated.length || removed.length || previousByKey.size !== nextByKey.size),
    nextByKey,
  };
}

export function preserveSelectedSnapshotKey(selectedKey, diff, fallbackKey = "") {
  if (selectedKey && diff?.nextByKey?.has(selectedKey)) {
    return selectedKey;
  }
  return fallbackKey || diff?.nextByKey?.keys?.().next?.().value || "";
}

export function createPcuiSnapshotDiffController(options = {}) {
  let previousRows = EMPTY_ROWS;
  let hasPrevious = false;

  function diffSnapshot(snapshot = {}) {
    const diff = diffSnapshotRows(previousRows, snapshot.items, options);
    previousRows = asArray(snapshot.items);
    const firstSnapshot = !hasPrevious;
    hasPrevious = true;
    return {
      ...diff,
      firstSnapshot,
      shouldRenderRows: firstSnapshot || diff.changed,
    };
  }

  function reset() {
    previousRows = EMPTY_ROWS;
    hasPrevious = false;
  }

  return {
    diffSnapshot,
    reset,
  };
}
