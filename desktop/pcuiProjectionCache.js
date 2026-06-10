const DEFAULT_MAX_ENTRIES = 32;
const DEFAULT_CHUNK_SIZE = 5_000;
const EMPTY_ROWS = Object.freeze([]);

function asArray(value) {
  return Array.isArray(value) ? value : EMPTY_ROWS;
}

function toText(value) {
  return value === undefined || value === null ? "" : String(value);
}

function normalizeScope(workspace = "workspace", rootKey = "", profileKey = "") {
  return `${toText(workspace)}\u0000${toText(rootKey)}\u0000${toText(profileKey)}`;
}

function splitScope(scope) {
  const [workspace = "", rootKey = "", profileKey = ""] = String(scope || "").split("\u0000");
  return { workspace, rootKey, profileKey };
}

function compactVersionParts(parts) {
  return parts.map(toText).filter(Boolean);
}

function getStableProjectionParts(source) {
  return compactVersionParts([
    source.version,
    source.revision,
    source.generatedAt,
    source.generated_at,
    source.updatedAt,
    source.updated_at,
    source.mtime,
    source.mtimeMs,
    source.mtime_ms,
    source.fileMtime,
    source.file_mtime,
    source.fileMtimeMs,
    source.file_mtime_ms,
    source.sourceMtimeMs,
    source.source_mtime_ms,
    source.projectionMtimeMs,
    source.projection_mtime_ms,
    source.projectionFileMtimeMs,
    source.projection_file_mtime_ms,
    source.itemCount,
    source.item_count,
    source.indexTotal,
    source.index_total,
    source.totalItems,
    source.total_items,
  ]);
}

function inferProjectionVersion({
  projection,
  rows = EMPTY_ROWS,
  versionKey = "",
  identityKey = "",
} = {}) {
  if (versionKey) {
    return `explicit:${String(versionKey)}`;
  }

  const source = projection || {};
  const stableParts = getStableProjectionParts(source);

  if (stableParts.length) {
    const supportingParts = compactVersionParts([
      source.status,
      source.archiveRoot,
      source.archive_root,
      source.artifactRoot,
      source.artifact_root,
      source.releaseRoot,
      source.release_root,
      asArray(rows).length,
    ]);
    return `stable:${[...stableParts, ...supportingParts].join("\u0001")}`;
  }

  return `identity:${toText(identityKey)}:${asArray(rows).length}`;
}

function makeEntry({ scope, key, version, value, rowCount }) {
  return {
    scope,
    key,
    version,
    value,
    rowCount,
    createdAt: Date.now(),
  };
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

function createAbortError() {
  const error = new Error("Projection normalization aborted");
  error.name = "AbortError";
  return error;
}

async function yieldToMainThread() {
  await new Promise((resolve) => {
    setTimeout(resolve, 0);
  });
}

export async function normalizeRowsBounded(rows, normalizeRow = (row) => row, {
  chunkSize = DEFAULT_CHUNK_SIZE,
  signal = null,
} = {}) {
  const sourceRows = asArray(rows);
  const safeChunkSize = Math.max(1, Math.floor(Number(chunkSize) || DEFAULT_CHUNK_SIZE));
  const out = [];

  for (let start = 0; start < sourceRows.length; start += safeChunkSize) {
    if (signal?.aborted) {
      throw createAbortError();
    }
    const end = Math.min(sourceRows.length, start + safeChunkSize);
    for (let index = start; index < end; index += 1) {
      out.push(normalizeRow(sourceRows[index], index));
    }
    if (end < sourceRows.length) {
      await yieldToMainThread();
    }
  }

  return out;
}

export function createPcuiProjectionCache({ maxEntries = DEFAULT_MAX_ENTRIES } = {}) {
  const entries = new Map();
  const lastValidByScope = new Map();
  const objectIds = new WeakMap();
  let nextObjectId = 1;

  function getObjectId(value) {
    if (!value || (typeof value !== "object" && typeof value !== "function")) {
      return toText(value);
    }
    if (!objectIds.has(value)) {
      objectIds.set(value, nextObjectId);
      nextObjectId += 1;
    }
    return objectIds.get(value);
  }

  function getSourceVersionKey(source, label = "source") {
    return `${label}:${getObjectId(source)}:${asArray(source).length}`;
  }

  function buildKey({
    workspace,
    rootKey = "",
    profileKey = "",
    projection = null,
    rows = EMPTY_ROWS,
    versionKey = "",
    queryKey = "",
  } = {}) {
    const scope = normalizeScope(workspace, rootKey, profileKey);
    const version = inferProjectionVersion({
      projection,
      rows,
      versionKey,
      identityKey: getSourceVersionKey(projection || rows, "identity"),
    });
    return {
      scope,
      version,
      key: `${scope}\u0000${version}\u0000${toText(queryKey)}`,
      rowCount: asArray(rows).length,
    };
  }

  function remember(entry) {
    entries.set(entry.key, entry);
    lastValidByScope.set(entry.scope, entry);
    while (entries.size > maxEntries) {
      const oldestKey = entries.keys().next().value;
      entries.delete(oldestKey);
    }
  }

  function getLastValid(workspace, rootKey = "", profileKey = "") {
    return lastValidByScope.get(normalizeScope(workspace, rootKey, profileKey)) || null;
  }

  function invalidate({ workspace = "", rootKey = "", profileKey = "" } = {}) {
    const workspaceText = toText(workspace);
    const rootText = toText(rootKey);
    const profileText = toText(profileKey);
    for (const [key, entry] of [...entries.entries()]) {
      const scope = splitScope(entry.scope);
      const workspaceMatches = !workspaceText || scope.workspace === workspaceText;
      const rootMatches = !rootText || scope.rootKey === rootText;
      const profileMatches = !profileText || scope.profileKey === profileText;
      if (workspaceMatches && rootMatches && profileMatches) {
        entries.delete(key);
      }
    }
    for (const [scope] of [...lastValidByScope.entries()]) {
      const entryScope = splitScope(scope);
      const workspaceMatches = !workspaceText || entryScope.workspace === workspaceText;
      const rootMatches = !rootText || entryScope.rootKey === rootText;
      const profileMatches = !profileText || entryScope.profileKey === profileText;
      if (workspaceMatches && rootMatches && profileMatches) {
        lastValidByScope.delete(scope);
      }
    }
  }

  function invalidateAll() {
    entries.clear();
    lastValidByScope.clear();
  }

  function getStats() {
    return {
      entryCount: entries.size,
      validScopeCount: lastValidByScope.size,
      maxEntries,
    };
  }

  function getOrNormalizeSync(options = {}) {
    const { scope, version, key, rowCount } = buildKey(options);
    const cached = entries.get(key);
    if (cached) {
      return { ok: true, hit: true, value: cached.value, entry: cached };
    }

    try {
      const value = options.normalize({
        rows: asArray(options.rows),
        projection: options.projection || null,
      });
      const entry = makeEntry({ scope, key, version, value, rowCount });
      remember(entry);
      return { ok: true, hit: false, value, entry };
    } catch (error) {
      return {
        ok: false,
        hit: false,
        error,
        aborted: isAbortError(error),
        previous: lastValidByScope.get(scope) || null,
      };
    }
  }

  async function getOrNormalize(options = {}) {
    const { scope, version, key, rowCount } = buildKey(options);
    const cached = entries.get(key);
    if (cached) {
      return { ok: true, hit: true, value: cached.value, entry: cached };
    }

    try {
      const value = await options.normalize({
        rows: asArray(options.rows),
        projection: options.projection || null,
        signal: options.signal || null,
        chunkSize: options.chunkSize || DEFAULT_CHUNK_SIZE,
      });
      const entry = makeEntry({ scope, key, version, value, rowCount });
      remember(entry);
      return { ok: true, hit: false, value, entry };
    } catch (error) {
      return {
        ok: false,
        hit: false,
        error,
        aborted: isAbortError(error),
        previous: lastValidByScope.get(scope) || null,
      };
    }
  }

  return {
    buildKey,
    getSourceVersionKey,
    getLastValid,
    getOrNormalize,
    getOrNormalizeSync,
    invalidate,
    invalidateAll,
    getStats,
  };
}
