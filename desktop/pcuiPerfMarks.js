export const PCUI_REQUIRED_PERF_MARK_IDS = Object.freeze([
  "pcui.projection.apply",
  "pcui.workspace.table.render",
  "pcui.virtual-list.update",
]);

function getDefaultNow() {
  const perf = globalThis.performance;
  if (perf && typeof perf.now === "function") {
    return () => perf.now();
  }
  return () => Date.now();
}

function normalizeDuration(value) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? Number(number.toFixed(3)) : 0;
}

function normalizeDetail(detail) {
  if (!detail || typeof detail !== "object") {
    return {};
  }
  return Object.fromEntries(
    Object.entries(detail)
      .filter(([, value]) => value !== undefined)
      .map(([key, value]) => [key, typeof value === "number" ? normalizeDuration(value) : value]),
  );
}

export function summarizePcuiPerfMarks(entries = []) {
  const groups = new Map();
  for (const entry of Array.isArray(entries) ? entries : []) {
    const id = String(entry?.id || "");
    if (!id) {
      continue;
    }
    const durationMs = normalizeDuration(entry.durationMs);
    const group = groups.get(id) || {
      id,
      count: 0,
      totalDurationMs: 0,
      maxDurationMs: 0,
      lastDurationMs: 0,
      errorCount: 0,
    };
    group.count += 1;
    group.totalDurationMs = normalizeDuration(group.totalDurationMs + durationMs);
    group.maxDurationMs = Math.max(group.maxDurationMs, durationMs);
    group.lastDurationMs = durationMs;
    if (entry.ok === false) {
      group.errorCount += 1;
    }
    groups.set(id, group);
  }

  return [...groups.values()]
    .map((group) => ({
      ...group,
      maxDurationMs: normalizeDuration(group.maxDurationMs),
      averageDurationMs: normalizeDuration(group.count ? group.totalDurationMs / group.count : 0),
    }))
    .sort((a, b) => a.id.localeCompare(b.id));
}

export function findMissingPcuiPerfMarkIds(snapshot, requiredIds = PCUI_REQUIRED_PERF_MARK_IDS) {
  const entries = Array.isArray(snapshot) ? snapshot : snapshot?.entries;
  const present = new Set((Array.isArray(entries) ? entries : []).map((entry) => entry?.id).filter(Boolean));
  return requiredIds.filter((id) => !present.has(id));
}

export function createPcuiPerfRecorder({
  now = getDefaultNow(),
  maxEntries = 240,
  requiredMarkIds = PCUI_REQUIRED_PERF_MARK_IDS,
} = {}) {
  const entries = [];

  function push(entry) {
    entries.push(entry);
    while (entries.length > maxEntries) {
      entries.shift();
    }
  }

  function measure(id, detail, callback) {
    const startedAtMs = Number(now());
    try {
      const result = callback();
      const durationMs = normalizeDuration(Number(now()) - startedAtMs);
      push({
        id,
        detail: normalizeDetail(detail),
        startedAtMs: normalizeDuration(startedAtMs),
        durationMs,
        ok: true,
      });
      return result;
    } catch (error) {
      const durationMs = normalizeDuration(Number(now()) - startedAtMs);
      push({
        id,
        detail: normalizeDetail(detail),
        startedAtMs: normalizeDuration(startedAtMs),
        durationMs,
        ok: false,
        errorName: error?.name || "Error",
        errorMessage: error?.message || String(error),
      });
      throw error;
    }
  }

  function reset() {
    entries.length = 0;
  }

  function getEntries() {
    return entries.map((entry) => ({
      ...entry,
      detail: { ...entry.detail },
    }));
  }

  function snapshot() {
    const currentEntries = getEntries();
    const summary = summarizePcuiPerfMarks(currentEntries);
    const missingRequiredMarkIds = findMissingPcuiPerfMarkIds(currentEntries, requiredMarkIds);
    return {
      entries: currentEntries,
      summary,
      requiredMarkIds: [...requiredMarkIds],
      missingRequiredMarkIds,
      pass: missingRequiredMarkIds.length === 0 && summary.every((entry) => entry.errorCount === 0),
    };
  }

  return {
    measure,
    reset,
    getEntries,
    snapshot,
  };
}
