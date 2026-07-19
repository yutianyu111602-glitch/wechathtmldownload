function buildQuery(data) {
  const pairs = Object.keys(data || {})
    .filter((key) => !isRequestControlKey(key) && data[key] !== undefined && data[key] !== null && data[key] !== "")
    .map((key) => `${encodeURIComponent(key)}=${encodeURIComponent(data[key])}`);
  return pairs.length ? `?${pairs.join("&")}` : "";
}

function buildInflightKey(path, data) {
  const controls = {};
  for (const key of Object.keys(data || {}).sort()) {
    const value = data[key];
    if (isRequestControlKey(key) && value !== undefined && value !== null && value !== "") {
      controls[key] = value;
    }
  }
  return `${path}${buildQuery(data || {})}|controls=${JSON.stringify(controls)}`;
}

const API_CACHE_PREFIX = "weeklyActivityApiCache:v20260719-visibility-v2:";
const DEFAULT_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const DEFAULT_CACHE_FALLBACK_DELAY_MS = 2200;
const DEFAULT_REQUEST_TIMEOUT_MS = 8000;
const DEFAULT_OFFLINE_SNAPSHOT_FALLBACK_DELAY_MS = -1;
const DEFAULT_CLOUD_DATABASE_HOT_COOLDOWN_MS = 30 * 60 * 1000;
const DEFAULT_CLOUD_DATABASE_BACKUP_DELAY_MS = 250;
const MAX_BATCH_DETAIL_IDS = 100;
const MAX_BATCH_DETAIL_REQUEST_UTF8_BYTES = 16 * 1024;
const MAX_BATCH_DETAIL_RESPONSE_UTF8_BYTES = 2 * 1024 * 1024;
const CURRENT_GENERATION_STORAGE_KEY = "weeklyActivityCurrentGeneration:v1";
const CURRENT_CACHE_POINTER_PREFIX = "weeklyActivityCurrentActive:v2:";
const CURRENT_CACHE_PAGE_PREFIX = "weeklyActivityCurrentPage:v2:";
const CURRENT_CACHE_STAGING_PREFIX = "weeklyActivityCurrentStaging:v2:";
const CURRENT_CACHE_STAGING_MAX_IDLE_MS = 6 * 60 * 60 * 1000;
const CURRENT_CACHE_ACTIVE_INDEX_KEY = "weeklyActivityCurrentActiveIndex:v2";
const CURRENT_CACHE_MAX_ACTIVE_PROFILES = 4;
const CURRENT_CACHE_PAGE_CHUNK_MAX_UTF8_BYTES = 700 * 1024;
const DEFAULT_STATIC_CURRENT_MEMORY_TTL_MS = 30 * 1000;
const STATIC_CURRENT_MEMORY_MAX_RELEASES = 2;
let cloudDatabaseHotDisabledUntil = 0;
let knownCurrentGeneration = null;
let currentCacheTransactionSequence = 0;
let lastStaticCurrentCacheBust = 0;
const staticCurrentPayloadMemory = new Map();
const staticCurrentPayloadInflight = new Map();

const { OFFLINE_SNAPSHOT, OFFLINE_SOURCE_URLS = {} } = require("./offlineSnapshot");
const { isElectronicMusicRelevantItem } = require("./electronicRelevance");
const { currentShanghaiBusinessDateKey } = require("./businessDate");
const { generatedAtOf, generationIdOf } = require("../services/generationContract");
const dateVisibility = require("./dateVisibility");
const {
  isoDate,
  itemDateKeys,
  itemIsCurrentOrFuture,
  itemMatchesDateKey,
  itemMatchesDateWindow,
  normalizeDateWindow,
} = dateVisibility;

function isGenerationScopedItemPath(path) {
  return path === "/api/v1/weekly/items/batch"
    || /^\/api\/v1\/weekly\/items\/[^/]+$/.test(String(path || ""));
}

function batchIdsOf(data = {}) {
  return String(data.ids || "")
    .split(",")
    .map((id) => decodePathPart(id).trim())
    .filter(Boolean);
}

function utf8ByteLength(value) {
  let bytes = 0;
  for (const char of String(value ?? "")) {
    const codePoint = char.codePointAt(0);
    if (codePoint <= 0x7f) bytes += 1;
    else if (codePoint <= 0x7ff) bytes += 2;
    else if (codePoint <= 0xffff) bytes += 3;
    else bytes += 4;
  }
  return bytes;
}

function batchContractError(code, message, details = {}) {
  const error = new Error(message);
  error.code = code;
  Object.assign(error, details);
  return error;
}

function assertBatchRequestBudget(path, data = {}) {
  if (path !== "/api/v1/weekly/items/batch") return;
  const ids = batchIdsOf(data);
  if (ids.length < 1 || ids.length > MAX_BATCH_DETAIL_IDS) {
    throw batchContractError(
      "WEEKLY_BATCH_ID_LIMIT",
      `Provide 1-${MAX_BATCH_DETAIL_IDS} comma-separated ids.`,
      { idCount: ids.length, maxIds: MAX_BATCH_DETAIL_IDS },
    );
  }
  const requestBytes = utf8ByteLength(String(data.ids || ""));
  if (requestBytes > MAX_BATCH_DETAIL_REQUEST_UTF8_BYTES) {
    throw batchContractError(
      "WEEKLY_BATCH_REQUEST_TOO_LARGE",
      "Weekly batch request exceeds the UTF-8 byte budget.",
      { requestBytes, maxRequestBytes: MAX_BATCH_DETAIL_REQUEST_UTF8_BYTES },
    );
  }
}

function generationIdentityOf(value) {
  const generationId = generationIdOf(value);
  if (generationId) return { mode: "exact", generationId, generatedAt: "" };
  const generatedAt = String(generatedAtOf(value) || "").trim();
  return generatedAt ? { mode: "legacy", generationId: "", generatedAt } : null;
}

function readKnownCurrentGeneration() {
  if (knownCurrentGeneration) return knownCurrentGeneration;
  if (typeof wx === "undefined" || !wx.getStorageSync) return null;
  try {
    const identity = generationIdentityOf(wx.getStorageSync(CURRENT_GENERATION_STORAGE_KEY));
    if (identity) knownCurrentGeneration = identity;
  } catch {}
  return knownCurrentGeneration;
}

function rememberCurrentGeneration(value, persist = true) {
  const identity = generationIdentityOf(value);
  if (!identity) return;
  knownCurrentGeneration = identity;
  if (!persist || typeof wx === "undefined" || !wx.setStorageSync) return;
  try {
    wx.setStorageSync(CURRENT_GENERATION_STORAGE_KEY, {
      generationId: identity.generationId || null,
      generatedAt: identity.generatedAt || null,
    });
  } catch {}
}

function withKnownGeneration(path, data) {
  const normalized = { ...(data || {}) };
  if (!isGenerationScopedItemPath(path) || generationIdentityOf(normalized)) return normalized;
  const known = readKnownCurrentGeneration();
  if (!known) return normalized;
  if (known.mode === "exact") normalized.generationId = known.generationId;
  else normalized.generatedAt = known.generatedAt;
  return normalized;
}

function responseCacheData(path, data, value) {
  if (!isGenerationScopedItemPath(path)) return data;
  const identity = generationIdentityOf(data) || generationIdentityOf(value);
  if (!identity) return null;
  if (identity.mode === "exact") {
    return { ...(data || {}), generationId: identity.generationId, generatedAt: undefined };
  }
  return { ...(data || {}), generationId: undefined, generatedAt: identity.generatedAt };
}

function assertResponseGeneration(path, data, value) {
  if (!isGenerationScopedItemPath(path)) return value;
  const requested = generationIdentityOf(data);
  if (!requested) return value;
  const actual = generationIdentityOf(value);
  const exactMatch = requested.mode === "exact"
    && actual && actual.mode === "exact"
    && requested.generationId === actual.generationId;
  const legacyMatch = requested.mode === "legacy"
    && actual && actual.mode === "legacy"
    && requested.generatedAt === actual.generatedAt;
  if (!exactMatch && !legacyMatch) {
    const error = new Error(
      `WEEKLY_DETAIL_GENERATION_MISMATCH:${requested.generationId || requested.generatedAt}->${actual ? (actual.generationId || actual.generatedAt) : "<missing>"}`,
    );
    error.code = "WEEKLY_DETAIL_GENERATION_MISMATCH";
    throw error;
  }
  return value;
}

function withResponseGeneration(value, owner) {
  if (!value || typeof value !== "object") return value;
  const clone = Array.isArray(value) ? value.slice() : { ...value };
  const generationId = generationIdOf(owner);
  const generatedAt = generatedAtOf(owner);
  if (generationId) {
    clone.generationId = generationId;
    clone.generation_id = generationId;
  }
  if (generatedAt) clone.generatedAt = generatedAt;
  return clone;
}

function stableData(value) {
  const out = {};
  for (const key of Object.keys(value || {}).sort()) {
    if (!isRequestControlKey(key) && value[key] !== undefined && value[key] !== null && value[key] !== "") {
      out[key] = value[key];
    }
  }
  return out;
}

function isRequestControlKey(key) {
  return String(key || "").startsWith("__");
}

function shouldBypassStoredRead(data) {
  return Boolean(data && (
    data.__skipCache === true
    || data.__liveOnly === true
    || data.__liveRefresh === true
  ));
}

function shouldSkipStoredWrite(data) {
  return Boolean(data && (data.__skipCache === true || data.__liveOnly === true));
}

function shouldRequireLiveResponse(data) {
  return Boolean(data && (data.__liveOnly === true || data.__liveRefresh === true));
}

function isCurrentCacheTransactionRequest(path, data) {
  return path === "/api/v1/weekly/current" && Boolean(data && data.__currentCacheTransaction === true);
}

function hashText(value) {
  let hash = 2166136261;
  const text = String(value || "");
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function cacheKey(path, data) {
  return `${API_CACHE_PREFIX}${hashText(`${path}?${JSON.stringify(stableData(data))}`)}`;
}

function currentCacheProfileData(data) {
  const profile = stableData(data || {});
  delete profile.cursor;
  return profile;
}

function currentCacheProfileHash(data) {
  return hashText(JSON.stringify(currentCacheProfileData(data)));
}

function currentCachePointerKey(data) {
  return `${CURRENT_CACHE_POINTER_PREFIX}${currentCacheProfileHash(data)}`;
}

function currentCacheStagingPrefix(data) {
  return `${CURRENT_CACHE_STAGING_PREFIX}${currentCacheProfileHash(data)}`;
}

function currentCacheStagingKey(data, transactionId) {
  return `${currentCacheStagingPrefix(data)}:${transactionId}`;
}

function currentCacheStorageAvailable() {
  return typeof wx !== "undefined"
    && typeof wx.getStorageSync === "function"
    && typeof wx.setStorageSync === "function";
}

function removeStorageKeys(keys) {
  if (typeof wx === "undefined" || typeof wx.removeStorageSync !== "function") return;
  for (const key of Array.from(new Set(keys || []))) {
    try {
      wx.removeStorageSync(key);
    } catch {}
  }
}

function currentCachePointerPageKeys(pointer) {
  const keys = [];
  for (const route of Array.isArray(pointer && pointer.routes) ? pointer.routes : []) {
    for (const key of Array.isArray(route && route.chunkKeys) ? route.chunkKeys : []) {
      if (String(key || "").startsWith(CURRENT_CACHE_PAGE_PREFIX)) keys.push(String(key));
    }
  }
  return keys;
}

function cleanupAbandonedCurrentCacheStaging(data) {
  if (!currentCacheStorageAvailable()) return;
  const profilePrefix = currentCacheStagingPrefix(data);
  let activePageKeys = new Set();
  try {
    activePageKeys = new Set(currentCachePointerPageKeys(
      wx.getStorageSync(currentCachePointerKey(data)),
    ));
  } catch {}
  const stagingKeys = [];
  try {
    if (typeof wx.getStorageInfoSync === "function") {
      for (const key of wx.getStorageInfoSync().keys || []) {
        const candidate = String(key || "");
        if (candidate === profilePrefix || candidate.startsWith(`${profilePrefix}:`)) {
          stagingKeys.push(candidate);
        }
      }
    } else {
      // The unscoped key belongs to the pre-concurrency registry format. New
      // transactions never use it, so it is the only safe fallback when a
      // host cannot enumerate storage keys.
      stagingKeys.push(profilePrefix);
    }
  } catch {}
  const now = Date.now();
  for (const stagingKey of Array.from(new Set(stagingKeys))) {
    try {
      const staging = wx.getStorageSync(stagingKey);
      const updatedAt = Number(staging && (staging.updatedAt || staging.startedAt));
      const isAbandoned = !Number.isFinite(updatedAt)
        || now - updatedAt > CURRENT_CACHE_STAGING_MAX_IDLE_MS;
      if (!isAbandoned) continue;
      // A process can die after the pointer activation write but before its
      // staging registry is removed. Such a stale registry is abandoned, but
      // its chunks are now committed data and must remain reachable.
      removeStorageKeys((Array.isArray(staging && staging.keys) ? staging.keys : [])
        .filter((key) => !activePageKeys.has(String(key || ""))));
      if (typeof wx.removeStorageSync === "function") wx.removeStorageSync(stagingKey);
    } catch {}
  }
}

function readCurrentCacheActiveIndex() {
  if (!currentCacheStorageAvailable()) return [];
  try {
    const value = wx.getStorageSync(CURRENT_CACHE_ACTIVE_INDEX_KEY);
    return Array.isArray(value && value.entries) ? value.entries.filter(Boolean) : [];
  } catch {
    return [];
  }
}

function writeCurrentCacheActiveIndex(entries) {
  if (!currentCacheStorageAvailable()) return;
  try {
    wx.setStorageSync(CURRENT_CACHE_ACTIVE_INDEX_KEY, { entries });
  } catch {}
}

function removeCurrentCacheProfile(pointerKey) {
  if (!currentCacheStorageAvailable()) return;
  try {
    const pointer = wx.getStorageSync(pointerKey);
    removeStorageKeys(currentCachePointerPageKeys(pointer));
    if (typeof wx.removeStorageSync === "function") wx.removeStorageSync(pointerKey);
  } catch {}
}

function trimCurrentCacheProfiles(keepPointerKey) {
  const entries = readCurrentCacheActiveIndex()
    .filter((entry) => entry && String(entry.pointerKey || "").startsWith(CURRENT_CACHE_POINTER_PREFIX))
    .sort((left, right) => Number(right.updatedAt || 0) - Number(left.updatedAt || 0));
  const protectedEntry = entries.find((entry) => entry.pointerKey === keepPointerKey);
  const kept = protectedEntry ? [protectedEntry] : [];
  for (const entry of entries) {
    if (entry === protectedEntry) continue;
    if (kept.length < CURRENT_CACHE_MAX_ACTIVE_PROFILES) kept.push(entry);
    else removeCurrentCacheProfile(entry.pointerKey);
  }
  writeCurrentCacheActiveIndex(kept);
}

function updateCurrentCacheActiveIndex(pointerKey, updatedAt) {
  const entries = readCurrentCacheActiveIndex()
    .filter((entry) => entry && entry.pointerKey !== pointerKey);
  entries.unshift({ pointerKey, updatedAt });
  const keep = entries.slice(0, CURRENT_CACHE_MAX_ACTIVE_PROFILES);
  for (const entry of entries.slice(CURRENT_CACHE_MAX_ACTIVE_PROFILES)) {
    removeCurrentCacheProfile(entry.pointerKey);
  }
  writeCurrentCacheActiveIndex(keep);
}

function splitCurrentPageItemsForStorage(items) {
  const chunks = [];
  let current = [];
  let currentBytes = 2;
  for (const item of items || []) {
    const itemBytes = utf8ByteLength(JSON.stringify(item)) + (current.length ? 1 : 0);
    if (itemBytes + 2 > CURRENT_CACHE_PAGE_CHUNK_MAX_UTF8_BYTES) {
      const error = new Error(`CURRENT_CACHE_ITEM_TOO_LARGE:${item && item.id || "<unknown>"}`);
      error.code = "CURRENT_CACHE_ITEM_TOO_LARGE";
      throw error;
    }
    if (current.length && currentBytes + itemBytes > CURRENT_CACHE_PAGE_CHUNK_MAX_UTF8_BYTES) {
      chunks.push(current);
      current = [];
      currentBytes = 2;
    }
    current.push(item);
    currentBytes += itemBytes;
  }
  if (current.length || !chunks.length) chunks.push(current);
  return chunks;
}

function beginCurrentCacheTransaction(data) {
  if (shouldSkipStoredWrite(data) || !currentCacheStorageAvailable()) return null;
  cleanupAbandonedCurrentCacheStaging(data);
  currentCacheTransactionSequence += 1;
  const transactionId = [
    Date.now().toString(36),
    currentCacheTransactionSequence.toString(36),
    Math.random().toString(36).slice(2, 10),
  ].join("-");
  return {
    cacheable: true,
    data: { ...(data || {}) },
    pointerKey: currentCachePointerKey(data),
    stagingKey: currentCacheStagingKey(data, transactionId),
    transactionId,
    startedAt: Date.now(),
    keys: [],
    routes: [],
  };
}

function persistCurrentCacheStagingRegistry(transaction) {
  wx.setStorageSync(transaction.stagingKey, {
    transactionId: transaction.transactionId,
    startedAt: transaction.startedAt,
    updatedAt: Date.now(),
    keys: transaction.keys.slice(),
  });
}

function abortCurrentCacheTransaction(transaction) {
  if (!transaction) return;
  transaction.cacheable = false;
  removeStorageKeys(transaction.keys);
  if (typeof wx !== "undefined" && typeof wx.removeStorageSync === "function") {
    try {
      wx.removeStorageSync(transaction.stagingKey);
    } catch {}
  }
  transaction.keys = [];
  transaction.routes = [];
}

function stageCurrentCachePage(transaction, page, cursor) {
  if (!transaction || !transaction.cacheable) return;
  if (page && ((page.__fromCache && !page.__fromStaticMemory) || page.__fromSnapshot)) {
    abortCurrentCacheTransaction(transaction);
    return;
  }
  const pageBase = { ...(page || {}) };
  delete pageBase.items;
  delete pageBase.__cachedAt;
  delete pageBase.__fromCache;
  delete pageBase.__fromSnapshot;
  const chunks = splitCurrentPageItemsForStorage(Array.isArray(page && page.items) ? page.items : []);
  const generationToken = generationIdOf(page) || String(generatedAtOf(page) || "legacy");
  const route = { cursor, pageBase, chunkKeys: [] };
  try {
    for (let index = 0; index < chunks.length; index += 1) {
      const key = `${CURRENT_CACHE_PAGE_PREFIX}${hashText([
        currentCacheProfileHash(transaction.data),
        generationToken,
        transaction.transactionId,
        cursor,
        index,
      ].join("|"))}`;
      transaction.keys.push(key);
      route.chunkKeys.push(key);
      // Register the intended key before writing it. A process death between
      // these two sync calls is therefore recoverable on the next refresh.
      persistCurrentCacheStagingRegistry(transaction);
      wx.setStorageSync(key, { items: chunks[index] });
    }
    transaction.routes.push(route);
  } catch {
    // Never trade the old active generation for cache availability. Prune
    // unrelated old profiles, then give up caching this refresh if quota still
    // cannot accommodate immutable staging.
    trimCurrentCacheProfiles(transaction.pointerKey);
    abortCurrentCacheTransaction(transaction);
  }
}

function commitCurrentCacheTransaction(transaction, complete) {
  if (!transaction || !transaction.cacheable || !transaction.routes.length) return false;
  const cachedAt = Date.now();
  const pointer = {
    schemaVersion: "weekly_activity_current_cache.v2",
    cachedAt,
    profile: currentCacheProfileData(transaction.data),
    generationId: generationIdOf(complete) || null,
    generatedAt: generatedAtOf(complete) || null,
    scope: complete.scope,
    total: complete.total,
    routes: transaction.routes,
  };
  let previous = null;
  try {
    previous = wx.getStorageSync(transaction.pointerKey);
  } catch {}
  try {
    // This single synchronous write is the only activation point. Until it
    // succeeds every newly written page is unreachable staging data.
    wx.setStorageSync(transaction.pointerKey, pointer);
  } catch {
    abortCurrentCacheTransaction(transaction);
    return false;
  }
  updateCurrentCacheActiveIndex(transaction.pointerKey, cachedAt);
  if (typeof wx.removeStorageSync === "function") {
    try {
      wx.removeStorageSync(transaction.stagingKey);
    } catch {}
  }
  const newKeys = new Set(transaction.keys);
  removeStorageKeys(currentCachePointerPageKeys(previous).filter((key) => !newKeys.has(key)));
  transaction.keys = [];
  trimCurrentCacheProfiles(transaction.pointerKey);
  return true;
}

function readActiveCurrentCachePage(data, cloud, ignoreMaxAge = false) {
  if (!currentCacheStorageAvailable()) return null;
  try {
    const pointer = wx.getStorageSync(currentCachePointerKey(data));
    if (!pointer || pointer.schemaVersion !== "weekly_activity_current_cache.v2") return null;
    const cachedAt = Number(pointer.cachedAt);
    if (!Number.isFinite(cachedAt)) return null;
    if (!ignoreMaxAge) {
      const maxAge = Number(cloud.cacheMaxAgeMs ?? DEFAULT_CACHE_MAX_AGE_MS);
      if (!Number.isFinite(maxAge) || maxAge <= 0 || Date.now() - cachedAt > maxAge) return null;
    }
    const cursor = normalizeCursor(data && data.cursor);
    const route = (pointer.routes || []).find((candidate) => Number(candidate && candidate.cursor) === cursor);
    if (!route || !Array.isArray(route.chunkKeys) || !route.chunkKeys.length) return null;
    const items = [];
    for (const key of route.chunkKeys) {
      const chunk = wx.getStorageSync(key);
      if (!chunk || !Array.isArray(chunk.items)) return null;
      items.push(...chunk.items);
    }
    return cloneCachedPayload({ ...(route.pageBase || {}), items }, cachedAt);
  } catch {
    return null;
  }
}

function canCachePath(path) {
  return String(path || "").startsWith("/api/v1/weekly/");
}

function cloneCachedPayload(payload, cachedAt) {
  if (!payload || typeof payload !== "object") return payload;
  const clone = Array.isArray(payload) ? payload.slice() : { ...payload };
  clone.__fromCache = true;
  clone.__cachedAt = cachedAt || 0;
  return clone;
}

function cloneOfflinePayload(payload) {
  if (!payload || typeof payload !== "object") return payload;
  const clone = Array.isArray(payload) ? payload.slice() : { ...payload };
  clone.__fromSnapshot = true;
  return clone;
}

function isDefaultCurrentFeedRequest(path, data) {
  if (path !== "/api/v1/weekly/current") return false;
  const scope = String((data && data.scope) || "").trim().toLowerCase();
  if (scope && scope !== "current") return false;
  const date = String((data && data.date) || "").trim();
  if (date && date !== "today") return false;
  if (String((data && (data.dateStart || data.dateFrom)) || "").trim()) return false;
  if (String((data && (data.dateEnd || data.dateTo)) || "").trim()) return false;
  const lookback = Number(data && data.lookbackDays);
  return !Number.isFinite(lookback) || lookback <= 0;
}

function normalizeStoredCurrentPayload(path, data, payload) {
  if (!isDefaultCurrentFeedRequest(path, data)) return payload;
  if (!payload || typeof payload !== "object") return payload;
  const items = Array.isArray(payload.items) ? payload.items : [];
  if (!items.length) return payload;
  const today = currentLocalDateKey();
  const currentItems = dedupeItems(items.filter((item) => itemIsCurrentOrFuture(item, today)));
  currentItems.sort((a, b) => {
    const aKey = isoDate(a.event_date_start) || itemDateKeys(a)[0] || "9999-12-31";
    const bKey = isoDate(b.event_date_start) || itemDateKeys(b)[0] || "9999-12-31";
    return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
  });
  return {
    ...payload,
    items: currentItems,
    __storedFilteredItemCount: items.length - currentItems.length,
    // Preserve server pagination metadata. Rewriting nextCursor to null used to
    // stop fetchAllCurrentItems after the first cached page when totals exceeded 100.
    page: { ...(payload.page || {}) },
  };
}

function cloneStoredPayload(path, data, payload, cachedAt) {
  const normalized = normalizeStoredCurrentPayload(path, data, payload);
  if (!normalized) return null;
  return cloneCachedPayload(normalized, cachedAt);
}

function canStartFastOfflineSnapshot(path, data, cloud) {
  if (cloud.offlineSnapshotFallback === false || cloud.fastOfflineSnapshotFallback !== true) return false;
  return !isDefaultCurrentFeedRequest(path, data);
}

function readCachedResponse(path, data, cloud) {
  if (!canCachePath(path) || !wx.getStorageSync) return null;
  if (isGenerationScopedItemPath(path) && !generationIdentityOf(data)) return null;
  if (isCurrentCacheTransactionRequest(path, data)) {
    const active = readActiveCurrentCachePage(data, cloud, false);
    if (active) return active;
  }
  const maxAge = Number(cloud.cacheMaxAgeMs ?? DEFAULT_CACHE_MAX_AGE_MS);
  if (!Number.isFinite(maxAge) || maxAge <= 0) return null;
  try {
    const entry = wx.getStorageSync(cacheKey(path, data));
    const cachedAt = Number(entry && entry.cachedAt);
    if (!entry || !entry.payload || !Number.isFinite(cachedAt)) return null;
    if (Date.now() - cachedAt > maxAge) return null;
    return cloneStoredPayload(path, data, entry.payload, cachedAt);
  } catch {
    return null;
  }
}

// Last successful live response for a path, ignoring maxAge. writeCachedResponse
// persists every online /api/v1/weekly/* success, so this mirrors the deployed
// activity package as of the user's last online open — always fresher than the
// baked OFFLINE_SNAPSHOT seed. Used only on the offline path, so staleness has
// already been accepted; a real (if old) fetch beats the first-launch seed.
function readPersistedResponse(path, data) {
  if (!canCachePath(path) || !wx.getStorageSync) return null;
  if (isGenerationScopedItemPath(path) && !generationIdentityOf(data)) return null;
  if (isCurrentCacheTransactionRequest(path, data)) {
    const active = readActiveCurrentCachePage(data, {}, true);
    if (active) return active;
  }
  try {
    const entry = wx.getStorageSync(cacheKey(path, data));
    if (entry && entry.payload) {
      return cloneStoredPayload(path, data, entry.payload, Number(entry.cachedAt) || 0);
    }
  } catch {}
  return null;
}

function writeCachedResponse(path, data, value) {
  if (
    !canCachePath(path) ||
    shouldSkipStoredWrite(data) ||
    isCurrentCacheTransactionRequest(path, data) ||
    !value ||
    typeof value !== "object" ||
    value.__fromCache ||
    value.__fromSnapshot ||
    !wx.setStorageSync
  ) return;
  const scopedData = responseCacheData(path, data, value);
  if (!scopedData) return;
  try {
    wx.setStorageSync(cacheKey(path, scopedData), {
      cachedAt: Date.now(),
      payload: value,
    });
  } catch {}
}

function withCachedResponse(rawPromise, path, data, cloud) {
  const cached = shouldBypassStoredRead(data) ? null : readCachedResponse(path, data, cloud);
  const delay = Math.max(0, Number(cloud.cacheFallbackDelayMs ?? DEFAULT_CACHE_FALLBACK_DELAY_MS));
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer = null;
    const resolveOnce = (value) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      resolve(value);
    };
    const rejectOnce = (error) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      reject(error);
    };
    if (cached) {
      timer = setTimeout(() => resolveOnce(cached), delay);
    }
    rawPromise.then(
      (value) => {
        if (!shouldSkipStoredWrite(data)) writeCachedResponse(path, data, value);
        resolveOnce(value);
      },
      (error) => {
        if (cached) {
          resolveOnce(cached);
        } else {
          rejectOnce(error);
        }
      }
    );
  });
}

function requestJson(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const ms = Math.max(1, Number(timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS));
    let settled = false;
    let requestTask = null;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try {
        if (requestTask && typeof requestTask.abort === "function") requestTask.abort();
      } catch {}
      reject({ error: { code: "REQUEST_TIMEOUT", timeoutMs: ms, url } });
    }, ms);
    try {
      requestTask = wx.request({
      url,
      method: "GET",
      timeout: ms,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          finish(resolve, res.data);
        } else {
          finish(reject, res.data || { error: { code: "REQUEST_FAILED", statusCode: res.statusCode } });
        }
      },
      fail: (error) => finish(reject, error),
      });
    } catch (error) {
      finish(reject, error);
    }
  });
}

function withTimeout(promise, timeoutMs, code, meta) {
  const ms = Number(timeoutMs || 0);
  if (!ms) return promise;
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject({ error: { code, timeoutMs: ms, ...(meta || {}) } });
    }, ms);
    promise.then(
      (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

function isDevtoolsRuntime() {
  try {
    const info = wx.getSystemInfoSync && wx.getSystemInfoSync();
    if (info && String(info.platform || "").toLowerCase() === "devtools") return true;
  } catch {}
  try {
    return typeof __wxConfig !== "undefined" && String(__wxConfig.platform || "").toLowerCase() === "devtools";
  } catch {}
  return false;
}

function normalizeLimit(value) {
  const limit = Number(value || 100);
  if (!Number.isFinite(limit)) return 100;
  return Math.min(Math.max(Math.floor(limit), 1), 100);
}

function normalizeCursor(value) {
  const cursor = Number(value || 0);
  if (!Number.isFinite(cursor)) return 0;
  return Math.max(Math.floor(cursor), 0);
}

function first(value, fallback = "") {
  return Array.isArray(value) ? value[0] || fallback : value || fallback;
}

function hasValue(value) {
  if (Array.isArray(value)) return value.some((item) => String(item || "").trim());
  return Boolean(String(value || "").trim());
}

function stripEmoji(value) {
  return String(value || "").replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, "").trim();
}

function stripLeadingDateWords(value) {
  return String(value || "")
    .replace(/^\s*[「【\[]?\s*(今晚|今夜|本周|周末)\s*[」】\]]?\s*/i, "")
    .replace(/^\s*(\d{1,2})[./-](\d{1,2})(\s*\([^)]+\))?\s*(周[一二三四五六日天]|星期[一二三四五六日天]|今晚|今夜)?\s*/i, "")
    .replace(/^\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})\s*/, "")
    .replace(/^\s*[｜|·:：,，\-–—]+\s*/, "")
    .trim();
}

function normalizeDedupePart(value) {
  return String(stripLeadingDateWords(stripEmoji(value)) || "")
    .toLowerCase()
    .replace(/[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]/g, "")
    .replace(/[^\w\u4e00-\u9fff]/g, "")
    .trim();
}

function dedupeKeyForItem(item) {
  const title = normalizeDedupePart(item.title_display || item.display_title || item.title);
  const date = dateKey(item);
  const city = cityKey(item);
  const venue = venueKey(item);
  return [title, date, city, venue].join("|");
}

function dateKey(item) {
  return String(item.event_date_start || item.event_date_iso_guess || first(item.event_date_iso_guesses, "") || "").trim();
}

function cityKey(item) {
  return normalizeDedupePart(item.city_key || first(item.city_keys, "") || first(item.city, ""));
}

function venueKey(item) {
  return normalizeDedupePart(item.venue_name || first(item.venue, "") || item.promoter || item.account);
}

function duplicateScopeKey(item) {
  return [dateKey(item), cityKey(item), venueKey(item)].join("|");
}

function sourceHash(item) {
  return String(item.source_action?.url_hash || item.source_article?.url_hash || "").trim();
}

function coverKey(item) {
  return String(item.cover_image_url || item.cover_url || item.coverUrl || "")
    .trim()
    .toLowerCase()
    .replace(/\?.*$/, "");
}

function titleFingerprint(item) {
  let raw = stripLeadingDateWords(stripEmoji(item.title_display || item.display_title || item.title || ""));
  raw = raw
    .replace(/\d{4}[./-]\d{1,2}[./-]\d{1,2}/g, "")
    .replace(/\d{1,2}[./-]\d{1,2}/g, "")
    .replace(/\d{1,2}\s*月\s*\d{1,2}\s*日?/g, "")
    .replace(/周[一二三四五六日天]|星期[一二三四五六日天]|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?/gi, "")
    .replace(/\b(room|support|pres|presents|presented|weekly|party|event|events)\b/gi, "")
    .replace(/(本周|周末|今晚|今夜|活动|预告|呈现|来袭|就在|预热派对|专场|厂牌|派对)/g, "");
  for (const candidate of [item.venue_name, first(item.venue, ""), item.promoter, item.account, first(item.city, "")]) {
    const normalizedCandidate = normalizeDedupePart(candidate);
    if (normalizedCandidate.length >= 3) {
      raw = normalizeDedupePart(raw).replace(new RegExp(normalizedCandidate, "g"), "");
    }
  }
  const fingerprint = normalizeDedupePart(raw);
  return fingerprint.length >= 6 ? fingerprint : "";
}

function bigrams(value) {
  const text = String(value || "");
  const grams = new Set();
  if (text.length < 2) {
    if (text) grams.add(text);
    return grams;
  }
  for (let index = 0; index < text.length - 1; index += 1) {
    grams.add(text.slice(index, index + 2));
  }
  return grams;
}

function overlapRatio(left, right) {
  if (!left || !right) return 0;
  if (left === right) return 1;
  if (left.length >= 8 && right.length >= 8 && (left.includes(right) || right.includes(left))) return 1;
  const leftGrams = bigrams(left);
  const rightGrams = bigrams(right);
  const denominator = Math.min(leftGrams.size, rightGrams.size);
  if (!denominator) return 0;
  let overlap = 0;
  for (const gram of leftGrams) {
    if (rightGrams.has(gram)) overlap += 1;
  }
  return overlap / denominator;
}

function titleSimilarity(left, right) {
  return overlapRatio(titleFingerprint(left), titleFingerprint(right));
}

function areLikelyDuplicateItems(left, right) {
  const scope = duplicateScopeKey(left);
  if (!scope || scope !== duplicateScopeKey(right)) return false;
  const leftCover = coverKey(left);
  const rightCover = coverKey(right);
  if (leftCover && leftCover === rightCover && titleSimilarity(left, right) >= 0.5) return true;
  const leftSource = sourceHash(left);
  const rightSource = sourceHash(right);
  if (leftSource && leftSource === rightSource && titleSimilarity(left, right) >= 0.5) return true;
  if (dedupeKeyForItem(left) === dedupeKeyForItem(right)) return true;
  return titleSimilarity(left, right) >= 0.86;
}

function itemQualityScore(item) {
  const source = String(item.event_time_source || item.running_hours_source || "").trim().toLowerCase();
  const trustedTime = [
    "source_text",
    "article_text",
    "official_text",
    "poster_ocr",
    "poster_text",
    "manual_verified",
  ].indexOf(source) !== -1;
  return (
    (trustedTime && hasValue(item.event_time_text || item.running_hours_text) ? 16 : 0) +
    (hasValue(item.address || item.address_full) ? 8 : 0) +
    (hasValue(item.description_original_lines || item.description) ? 5 : 0) +
    (hasValue(item.source_action?.url_hash || item.source_article?.url_hash) ? 4 : 0) +
    (hasValue(item.lineup_artists || item.lineup) ? 3 : 0) +
    (hasValue(item.music_styles || item.style_tags || item.genres) ? 2 : 0) +
    (hasValue(item.cover_image_url || item.cover_url || item.coverUrl) ? 1 : 0)
  );
}

function stableItemId(item) {
  return String(item && (item.id || item.event_id || item.eventId) || "").trim();
}

function mergedDuplicateCityFields(preferred, other) {
  const entries = new Map();
  for (const source of [preferred, other]) {
    const keys = itemCityKeys(source);
    const rawLabels = Array.isArray(source && source.city)
      ? source.city
      : [source && source.city];
    for (let index = 0; index < keys.length; index += 1) {
      const key = keys[index];
      const label = String(
        rawLabels[index]
        || (index === 0 && (source.city_name || source.cityName))
        || key,
      ).trim() || key;
      if (!entries.has(key) || entries.get(key) === key) entries.set(key, label);
    }
  }
  if (!entries.size) return preferred;
  const keys = Array.from(entries.keys());
  const merged = { ...preferred };
  merged.city_keys = keys;
  merged.cityKeys = keys.slice();
  merged.city = keys.map((key) => entries.get(key) || key);
  if (!String(merged.city_key || "").trim()) merged.city_key = keys[0];
  if (!String(merged.cityKey || "").trim()) merged.cityKey = merged.city_key || keys[0];
  return merged;
}

function dedupeItems(items) {
  const output = [];
  const scopeIndexes = new Map();
  const idIndexes = new Map();
  for (const item of items || []) {
    const itemId = stableItemId(item);
    const scope = duplicateScopeKey(item);
    const candidateIndexes = scopeIndexes.get(scope) || [];
    let duplicateIndex = itemId && idIndexes.has(itemId) ? idIndexes.get(itemId) : -1;
    if (duplicateIndex === -1) {
      for (const index of candidateIndexes) {
        if (areLikelyDuplicateItems(output[index], item)) {
          duplicateIndex = index;
          break;
        }
      }
    }
    if (duplicateIndex === -1) {
      output.push(item);
      const outputIndex = output.length - 1;
      if (itemId) idIndexes.set(itemId, outputIndex);
      if (!scopeIndexes.has(scope)) scopeIndexes.set(scope, []);
      scopeIndexes.get(scope).push(outputIndex);
      continue;
    }
    const existing = output[duplicateIndex];
    const preferred = itemQualityScore(item) > itemQualityScore(existing) ? item : existing;
    const other = preferred === item ? existing : item;
    output[duplicateIndex] = mergedDuplicateCityFields(preferred, other);
    const mergedId = stableItemId(output[duplicateIndex]);
    if (mergedId) idIndexes.set(mergedId, duplicateIndex);
  }
  return output;
}

const itemMatchesDate = itemMatchesDateKey;

let todayOverride = "";
const inflightRequests = new Map();

function currentLocalDateKey() {
  return todayOverride || currentShanghaiBusinessDateKey();
}

function addDays(dateKey, days) {
  const match = String(dateKey || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  date.setUTCDate(date.getUTCDate() + Number(days || 0));
  return date.toISOString().slice(0, 10);
}

function staticVisibilitySpec(data) {
  const input = data || {};
  const rawScope = String(input.scope || "").trim().toLowerCase();
  const scope = rawScope === "package" || rawScope === "package_window" || rawScope === "all" ? "package" : "current";
  const date = isoDate(input.date);
  const window = date
    ? { dateStart: date, dateEnd: date }
    : normalizeDateWindow(input.dateStart || input.dateFrom, input.dateEnd || input.dateTo);
  const parsedLookback = Number.parseInt(input.lookbackDays || 0, 10);
  const lookbackDays = Math.max(0, Math.min(45, Number.isFinite(parsedLookback) ? parsedLookback : 0));
  return {
    scope,
    cityKey: String(input.cityKey || "all").trim().toLowerCase() || "all",
    date: date || null,
    dateStart: window.dateStart || null,
    dateEnd: window.dateEnd || null,
    lookbackDays: scope === "current" && !date && !window.dateStart ? (lookbackDays || null) : null,
    today: currentLocalDateKey() || null,
  };
}

function itemCityKeys(item) {
  const source = item || {};
  return Array.from(new Set(
    [source.city_key, source.cityKey]
      .concat(Array.isArray(source.city_keys) ? source.city_keys : [])
      .concat(Array.isArray(source.cityKeys) ? source.cityKeys : [])
      .map((value) => String(value || "").trim().toLowerCase())
      .filter(Boolean),
  ));
}

function staticVisibleProjection(payload, data) {
  const filters = staticVisibilitySpec(data);
  const allItems = payload.items || [];
  const currentThreshold = filters.lookbackDays ? addDays(filters.today, -filters.lookbackDays) : filters.today;
  const items = dedupeItems(allItems.filter((item) => {
    const cityKeys = itemCityKeys(item);
    const cityOk = !filters.cityKey
      || filters.cityKey === "all"
      || cityKeys.indexOf(filters.cityKey) !== -1;
    const dateOk = filters.date
      ? itemMatchesDate(item, filters.date)
      : filters.dateStart
        ? itemMatchesDateWindow(item, filters.dateStart, filters.dateEnd)
        : filters.scope === "package" || itemIsCurrentOrFuture(item, currentThreshold);
    const qualityOk = !item.quality_status || item.quality_status === "READY";
    return cityOk && dateOk && qualityOk && isElectronicMusicRelevantItem(item);
  }));
  items.sort((a, b) => {
    const aKey = isoDate(a.event_date_start) || itemDateKeys(a)[0] || "9999-12-31";
    const bKey = isoDate(b.event_date_start) || itemDateKeys(b)[0] || "9999-12-31";
    return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
  });
  return { filters, items };
}

function currentResponseFromStatic(payload, data) {
  const projection = staticVisibleProjection(payload, data);
  const filters = projection.filters;
  const items = projection.items;
  const cursor = normalizeCursor(data.cursor);
  const limit = normalizeLimit(data.limit);
  const pageItems = items.slice(cursor, cursor + limit);

  return {
    schemaVersion: "weekly_activity_api.current_response.v1",
    generatedAt: payload.generated_at || payload.generatedAt,
    generationId: generationIdOf(payload) || null,
    filters,
    page: {
      cursor,
      limit,
      nextCursor: cursor + limit < items.length ? cursor + limit : null,
      total: items.length,
    },
    items: pageItems,
  };
}

function itemCityLabel(item, key, index) {
  const labels = Array.isArray(item && item.city) ? item.city : [item && item.city];
  return String(labels[index] || (index === 0 ? (item.city_name || item.cityName) : "") || key);
}

function cityIndexFromStatic(payload, data) {
  const projection = staticVisibleProjection(payload, { ...(data || {}), cityKey: "all" });
  const bucket = new Map();
  for (const item of projection.items) {
    const keys = itemCityKeys(item);
    for (let index = 0; index < keys.length; index += 1) {
      const key = keys[index];
      const current = bucket.get(key) || {
        city_key: key,
        city: itemCityLabel(item, key, index),
        count: 0,
        item_count: 0,
      };
      current.item_count += 1;
      current.count = current.item_count;
      bucket.set(key, current);
    }
  }
  const cities = Array.from(bucket.values())
    .sort((left, right) => right.item_count - left.item_count || left.city_key.localeCompare(right.city_key));
  return {
    schema_version: "weekly_activity_miniprogram_city_index.v2",
    generated_at: payload.generated_at || payload.generatedAt || null,
    generation_id: generationIdOf(payload) || null,
    generationId: generationIdOf(payload) || null,
    scope: projection.filters.scope,
    filters: projection.filters,
    city_count: cities.length,
    item_count: projection.items.length,
    cities,
  };
}

function dateIndexFromStatic(payload, data) {
  const projection = staticVisibleProjection(payload, data || {});
  const bucket = new Map();
  const floor = projection.filters.scope === "current" && !projection.filters.dateStart
    ? (projection.filters.lookbackDays ? addDays(projection.filters.today, -projection.filters.lookbackDays) : projection.filters.today)
    : null;
  for (const item of projection.items) {
    for (const key of itemDateKeys(item)) {
      if (projection.filters.dateStart && (key < projection.filters.dateStart || key > projection.filters.dateEnd)) continue;
      if (floor && key < floor) continue;
      const current = bucket.get(key) || { date: key, count: 0, item_count: 0 };
      current.item_count += 1;
      current.count = current.item_count;
      bucket.set(key, current);
    }
  }
  const dates = Array.from(bucket.values()).sort((left, right) => left.date.localeCompare(right.date));
  return {
    schema_version: "weekly_activity_miniprogram_date_index.v2",
    generated_at: payload.generated_at || payload.generatedAt || null,
    generation_id: generationIdOf(payload) || null,
    generationId: generationIdOf(payload) || null,
    scope: projection.filters.scope,
    filters: projection.filters,
    date_count: dates.length,
    item_count: projection.items.length,
    dates,
  };
}

function staticUrl(baseUrl, filePath) {
  const base = String(baseUrl || "").replace(/\/+$/, "");
  const path = String(filePath || "").replace(/^\/+/, "");
  return `${base}/${path}?_ts=${Date.now()}`;
}

function staticCurrentDownloadUrl(baseUrl) {
  lastStaticCurrentCacheBust = Math.max(Date.now(), lastStaticCurrentCacheBust + 1);
  const base = normalizedStaticBaseUrl(baseUrl);
  return `${base}/current.json?_ts=${lastStaticCurrentCacheBust}`;
}

function normalizedStaticBaseUrl(baseUrl) {
  return String(baseUrl || "").replace(/\/+$/, "");
}

function staticGenerationMatches(payload, requested) {
  if (!requested) return true;
  const actual = generationIdentityOf(payload);
  if (!actual || actual.mode !== requested.mode) return false;
  return requested.mode === "exact"
    ? actual.generationId === requested.generationId
    : actual.generatedAt === requested.generatedAt;
}

function pruneStaticCurrentPayloadMemory(now) {
  for (const [key, entry] of staticCurrentPayloadMemory.entries()) {
    if (!entry || Number(entry.expiresAt || 0) <= now) staticCurrentPayloadMemory.delete(key);
  }
  if (staticCurrentPayloadMemory.size <= STATIC_CURRENT_MEMORY_MAX_RELEASES) return;
  const oldest = Array.from(staticCurrentPayloadMemory.entries())
    .sort((left, right) => Number(left[1] && left[1].loadedAt || 0) - Number(right[1] && right[1].loadedAt || 0));
  for (const [key] of oldest.slice(0, staticCurrentPayloadMemory.size - STATIC_CURRENT_MEMORY_MAX_RELEASES)) {
    staticCurrentPayloadMemory.delete(key);
  }
}

function loadStaticCurrentPayloadOnce(baseUrl, cloud, options = {}) {
  const key = normalizedStaticBaseUrl(baseUrl);
  const now = Date.now();
  const bypassMemory = options.bypassMemory === true;
  const writeMemory = options.writeMemory !== false;
  const ttlValue = Number(cloud.staticPayloadMemoryTtlMs ?? DEFAULT_STATIC_CURRENT_MEMORY_TTL_MS);
  const ttlMs = Number.isFinite(ttlValue) ? Math.max(0, ttlValue) : DEFAULT_STATIC_CURRENT_MEMORY_TTL_MS;
  pruneStaticCurrentPayloadMemory(now);
  const cached = staticCurrentPayloadMemory.get(key);
  if (!bypassMemory && cached && cached.expiresAt > now) {
    return Promise.resolve({ ...cached.payload, __staticMemoryCacheHit: true });
  }
  const existing = staticCurrentPayloadInflight.get(key);
  if (existing) return existing;

  // Cache busting belongs to the physical download, not each logical route.
  // This timestamp is consequently shared by every waiter on this promise.
  const promise = requestJson(staticCurrentDownloadUrl(key), cloud.requestTimeoutMs).then(
    (payload) => {
      if (!payload || typeof payload !== "object" || !Array.isArray(payload.items)) {
        const error = new Error("STATIC_CURRENT_BAD_PAYLOAD");
        error.code = "STATIC_CURRENT_BAD_PAYLOAD";
        throw error;
      }
      if (writeMemory && ttlMs > 0) {
        const loadedAt = Date.now();
        staticCurrentPayloadMemory.set(key, { payload, loadedAt, expiresAt: loadedAt + ttlMs });
        pruneStaticCurrentPayloadMemory(loadedAt);
      }
      return payload;
    },
    (error) => {
      throw error;
    },
  ).finally(() => {
    if (staticCurrentPayloadInflight.get(key) === promise) staticCurrentPayloadInflight.delete(key);
  });
  staticCurrentPayloadInflight.set(key, promise);
  return promise;
}

async function loadStaticCurrentPayload(baseUrl, cloud, data) {
  const key = normalizedStaticBaseUrl(baseUrl);
  const requested = generationIdentityOf(data);
  const bypassMemory = shouldBypassStoredRead(data);
  const writeMemory = !shouldSkipStoredWrite(data);
  let payload = await loadStaticCurrentPayloadOnce(key, cloud, {
    bypassMemory,
    writeMemory,
  });
  if (requested && !staticGenerationMatches(payload, requested)) {
    // A mutable emergency mirror may have advanced while its short-lived
    // in-memory payload was still warm. Evict once and make a real reload;
    // assertResponseGeneration remains the final fail-closed guard.
    staticCurrentPayloadMemory.delete(key);
    payload = await loadStaticCurrentPayloadOnce(key, cloud, {
      bypassMemory: true,
      writeMemory,
    });
  }
  return payload;
}

function withStaticMemoryCacheMetadata(value, payload) {
  if (!payload || payload.__staticMemoryCacheHit !== true || !value || typeof value !== "object") return value;
  return { ...value, __fromCache: true, __fromStaticMemory: true };
}

function safePathPart(value) {
  return String(value || "").replace(/[^a-zA-Z0-9_-]/g, "");
}

function decodePathPart(value) {
  try {
    return decodeURIComponent(String(value || ""));
  } catch {
    return String(value || "");
  }
}

function storageSlug(value) {
  const raw = decodePathPart(value).trim().toLowerCase();
  if (!raw) return "";
  let out = "";
  for (const char of raw) {
    if (/^[a-z0-9_-]$/.test(char)) {
      out += char;
    } else {
      out += `u${char.codePointAt(0).toString(16)}`;
    }
  }
  return out.replace(/-+/g, "-").replace(/^[-_]+|[-_]+$/g, "");
}

function requestStatic(path, data, cloud) {
  const baseUrl = cloud.staticBaseUrl;
  if (!baseUrl) {
    return Promise.reject({ error: { code: "STATIC_BASE_URL_MISSING" } });
  }

  if (path === "/api/v1/weekly/current") {
    return loadStaticCurrentPayload(baseUrl, cloud, data).then((payload) => withStaticMemoryCacheMetadata(
      currentResponseFromStatic(payload, data),
      payload,
    ));
  }

  if (path === "/api/v1/weekly/cities") {
    return loadStaticCurrentPayload(baseUrl, cloud, data).then((payload) => withStaticMemoryCacheMetadata(
      cityIndexFromStatic(payload, data),
      payload,
    ));
  }

  if (path === "/api/v1/weekly/dates") {
    return loadStaticCurrentPayload(baseUrl, cloud, data).then((payload) => withStaticMemoryCacheMetadata(
      dateIndexFromStatic(payload, data),
      payload,
    ));
  }

  if (path === "/api/v1/weekly/manifest") {
    return requestJson(staticUrl(baseUrl, "manifest.json"));
  }

  if (path === "/api/v1/weekly/items/batch") {
    const ids = String(data.ids || "")
      .split(",")
      .map((id) => decodePathPart(id).trim())
      .filter(Boolean);
    const idSet = new Set(ids);
    return loadStaticCurrentPayload(baseUrl, cloud, data).then((payload) => {
      const byId = {};
      for (const item of payload.items || []) {
        if (idSet.has(item.id)) byId[item.id] = item;
      }
      return withStaticMemoryCacheMetadata(withResponseGeneration({
        items: ids.map((id) => byId[id]).filter(Boolean),
      }, payload), payload);
    });
  }

  if (path.indexOf("/api/v1/weekly/items/") === 0) {
    const id = storageSlug(path.replace("/api/v1/weekly/items/", ""));
    return requestJson(staticUrl(baseUrl, `by-id/${id}.json`)).then(
      (payload) => withResponseGeneration(payload.item || payload, payload),
    );
  }

  if (path.indexOf("/api/v1/weekly/source/") === 0) {
    const hash = safePathPart(path.replace("/api/v1/weekly/source/", ""));
    return requestJson(staticUrl(baseUrl, "source_actions/source_url_map.json")).then((payload) => {
      const sources = payload.sources || {};
      return sources[hash] || { url: "" };
    });
  }

  if (path.indexOf("/api/v1/weekly/atlas-events/") === 0) {
    const eventId = decodePathPart(path.replace("/api/v1/weekly/atlas-events/", "")).trim();
    return requestJson(staticUrl(baseUrl, "weekly_entity_snapshot.json")).then((payload) => {
      const rows = (payload.lineup_resolved || []).filter((row) => row.event_id === eventId);
      const profileById = {};
      for (const profile of payload.artist_profiles || []) {
        if (profile.artist_id) profileById[profile.artist_id] = profile;
      }
      const lineupResolved = rows.map((row) => {
        const isVerified = row.match_method === "alias_exact" && row.artist_id && row.verified === true;
        const isHint = row.match_method === "fuzzy_multiple";
        return {
          raw: row.raw || "",
          artistId: isVerified ? row.artist_id : null,
          canonicalName: isVerified ? row.canonical_name || "" : null,
          matchMethod: row.match_method || "no_match",
          matchScore: Number(row.match_score || 0),
          displayTier: isVerified ? "show" : isHint ? "show_with_hint" : "hide",
          candidates: isHint && Array.isArray(row.candidates)
            ? row.candidates.map((candidate) => ({
                canonicalName: candidate.canonical_name || "",
                score: Number(candidate.score || 0),
              }))
            : [],
        };
      });
      const artistProfiles = lineupResolved
        .filter((row) => row.artistId && profileById[row.artistId])
        .map((row) => ({
          artistId: row.artistId,
          canonicalName: profileById[row.artistId].canonical_name || row.canonicalName || "",
          verified: profileById[row.artistId].verified === true,
          source: profileById[row.artistId].source || "atlas_alias_export",
        }));
      return {
        schemaVersion: "weekly_activity_api.atlas_event.v1",
        eventId,
        generatedAt: payload.generated_at || null,
        publishPackage: payload.publish_package || "",
        lineupResolved,
        artistProfiles,
        safety: {
          graphWriteExecuted: false,
          qdrantWriteExecuted: false,
          productionWriteExecuted: false,
          fuzzyCandidateIdsExposed: false,
        },
      };
    });
  }

  return Promise.reject({ error: { code: "STATIC_ROUTE_NOT_FOUND", path } });
}

function requestMock(path, query, cloud) {
  return requestJson(`${cloud.mockBaseUrl}${path}${query}`, cloud.requestTimeoutMs);
}

function requestPublic(path, query, cloud) {
  const baseUrl = String(cloud.publicBaseUrl || "").replace(/\/+$/, "");
  if (!baseUrl) {
    return Promise.reject({ error: { code: "PUBLIC_BASE_URL_MISSING" } });
  }
  return requestJson(`${baseUrl}${path}${query}`, cloud.publicRequestTimeoutMs || cloud.requestTimeoutMs)
    .then((payload) => assertContainerData(path, { statusCode: 200, data: payload }));
}

function getCloudClient(cloud) {
  if (cloud.cloudInitPromise) {
    return cloud.cloudInitPromise;
  }
  if (cloud.cloudClient) {
    return Promise.resolve(cloud.cloudClient);
  }
  if (wx.cloud) {
    return Promise.resolve(wx.cloud);
  }
  return Promise.reject({ error: { code: "CLOUD_CLIENT_MISSING" } });
}

function assertContainerData(path, res) {
  const statusCode = Number(res && res.statusCode);
  if (statusCode && (statusCode < 200 || statusCode >= 300)) {
    return Promise.reject({ error: { code: "CONTAINER_STATUS", statusCode, path }, data: res.data });
  }

  const payload = res && res.data;
  if (!payload || typeof payload !== "object" || payload.error) {
    return Promise.reject({ error: { code: "CONTAINER_BAD_PAYLOAD", path }, data: payload });
  }

  if (path === "/api/v1/weekly/current" && !Array.isArray(payload.items)) {
    return Promise.reject({ error: { code: "CONTAINER_BAD_CURRENT", path }, data: payload });
  }
  if (path === "/api/v1/weekly/cities" && !Array.isArray(payload.cities)) {
    return Promise.reject({ error: { code: "CONTAINER_BAD_CITIES", path }, data: payload });
  }
  if (path === "/api/v1/weekly/dates" && !Array.isArray(payload.dates)) {
    return Promise.reject({ error: { code: "CONTAINER_BAD_DATES", path }, data: payload });
  }
  if (path === "/api/v1/weekly/items/batch") {
    if (!Array.isArray(payload.items)) {
      return Promise.reject({ error: { code: "CONTAINER_BAD_BATCH", path }, data: payload });
    }
    const responseBytes = utf8ByteLength(JSON.stringify(payload));
    if (responseBytes > MAX_BATCH_DETAIL_RESPONSE_UTF8_BYTES) {
      return Promise.reject(batchContractError(
        "WEEKLY_BATCH_RESPONSE_TOO_LARGE",
        "Weekly batch response exceeds the UTF-8 byte budget.",
        { responseBytes, maxResponseBytes: MAX_BATCH_DETAIL_RESPONSE_UTF8_BYTES },
      ));
    }
  }

  return payload;
}

function requestCloudContainer(path, query, cloud) {
  const { env, service } = cloud;
  return withTimeout(
    getCloudClient(cloud),
    cloud.cloudInitTimeoutMs || 3000,
    "CLOUD_INIT_TIMEOUT",
    { path }
  )
    .then((client) => withTimeout(
      client.callContainer({
        config: { env },
        path: `${path}${query}`,
        method: "GET",
        header: {
          "X-WX-SERVICE": service,
        },
      }),
      cloud.cloudCallTimeoutMs || 6000,
      "CONTAINER_TIMEOUT",
      { path }
    ))
    .then((res) => assertContainerData(path, res));
}

function isCloudDatabaseHotPath(path) {
  if (path === "/api/v1/weekly/current") return true;
  if (path === "/api/v1/weekly/cities") return true;
  if (path === "/api/v1/weekly/dates") return true;
  if (path === "/api/v1/weekly/llm/materialized-summary") return true;
  if (path === "/api/v1/weekly/config") return true;
  // weekly_events currently stores the compact list DTO. Until a sync marks a
  // complete rich-detail generation, detail and batch must use CloudRun's
  // generation-validated by-id routes instead of pretending list rows are
  // equivalent detail responses.
  return false;
}

function errorText(error) {
  const payload = error && error.error ? error.error : error;
  return [
    payload && payload.code,
    payload && payload.errCode,
    payload && payload.message,
    payload && payload.errMsg,
    error && error.code,
    error && error.message,
  ].filter(Boolean).join(" ");
}

function isCloudDatabaseQuotaError(error) {
  return /EXCEED_REQUEST_LIMIT|LimitExceeded\.OutOf(Read|Write)RequestQuota|request overrun|read overrun|write overrun/i.test(errorText(error));
}

function getCloudDatabaseHotCooldownMs(cloud) {
  const value = Number(cloud && cloud.databaseCircuitBreakerMs);
  return Number.isFinite(value) && value >= 0 ? value : DEFAULT_CLOUD_DATABASE_HOT_COOLDOWN_MS;
}

function getCloudDatabaseBackupDelayMs(cloud) {
  const explicit = Number(cloud && cloud.databaseBackupDelayMs);
  if (Number.isFinite(explicit) && explicit >= 0) return explicit;
  const publicDelay = Number(cloud && cloud.publicFallbackDelayMs);
  if (Number.isFinite(publicDelay) && publicDelay >= 0) return publicDelay;
  return DEFAULT_CLOUD_DATABASE_BACKUP_DELAY_MS;
}

function isCloudDatabaseHotCircuitOpen(cloud) {
  const until = Math.max(cloudDatabaseHotDisabledUntil, Number(cloud && cloud.cloudDatabaseHotDisabledUntil || 0));
  return until > Date.now();
}

function disableCloudDatabaseHotTemporarily(error, cloud) {
  if (!isCloudDatabaseQuotaError(error)) return;
  const until = Date.now() + getCloudDatabaseHotCooldownMs(cloud);
  cloudDatabaseHotDisabledUntil = until;
  if (cloud) cloud.cloudDatabaseHotDisabledUntil = until;
}

function requestCloudDatabaseHot(path, data, cloud) {
  const fn = String(cloud.databaseFunctionName || "").trim();
  if (!cloud.useCloudDatabaseFirst || !fn || !isCloudDatabaseHotPath(path)) {
    return Promise.reject({ error: { code: "CLOUD_DATABASE_HOT_DISABLED", path } });
  }
  if (isCloudDatabaseHotCircuitOpen(cloud)) {
    return Promise.reject({
      error: {
        code: "CLOUD_DATABASE_HOT_CIRCUIT_OPEN",
        path,
        retryAt: cloudDatabaseHotDisabledUntil,
      },
    });
  }
  return withTimeout(
    getCloudClient(cloud),
    cloud.cloudInitTimeoutMs || 3000,
    "CLOUD_DATABASE_INIT_TIMEOUT",
    { path, source: "cloudDatabase" }
  )
    .then((client) => {
      if (!client || typeof client.callFunction !== "function") {
        return Promise.reject({ error: { code: "CLOUD_DATABASE_FUNCTION_CLIENT_MISSING", path } });
      }
      return withTimeout(
        client.callFunction({
          name: fn,
          data: {
            action: "read",
            path,
            query: Object.assign({}, data || {}, { _ts: Date.now() }),
            source: "miniprogram-hot-db",
          },
        }),
        cloud.databaseFunctionTimeoutMs || 5000,
        "CLOUD_DATABASE_FUNCTION_TIMEOUT",
        { path, source: "cloudDatabase" }
      );
    })
    .then((res) => {
      const payload = normalizeCloudFunctionResult(res);
      if (!payload || typeof payload !== "object" || payload.error) {
        return Promise.reject(payload || { error: { code: "CLOUD_DATABASE_BAD_PAYLOAD", path } });
      }
      return assertContainerData(path, { statusCode: 200, data: payload });
    });
}

function normalizeCloudFunctionResult(raw) {
  if (raw === null || raw === undefined) return raw;
  if (Object.prototype.hasOwnProperty.call(raw, "result")) {
    return raw.result;
  }
  if (Object.prototype.hasOwnProperty.call(raw, "payload")) {
    return raw.payload;
  }
  return raw;
}

function requestCloudFunctionAi(path, query, body, method, cloud) {
  const queryPayload = Object.assign({}, query || {}, { _ts: Date.now() });
  const fn = String(cloud.aiFunctionName || "").trim();
  if (!fn) {
    return Promise.reject({ error: { code: "AI_CLOUD_FUNCTION_MISSING" } });
  }
  if (!cloud.aiUseFunctionFirst) {
    return Promise.reject({ error: { code: "AI_CLOUD_FUNCTION_DISABLED" } });
  }
  return withTimeout(
    getCloudClient(cloud),
    cloud.cloudInitTimeoutMs || 3000,
    "AI_CLOUD_INIT_TIMEOUT",
    { path, source: "cloudFunction" }
  )
    .then((client) => {
      if (!client || typeof client.callFunction !== "function") {
        return Promise.reject({ error: { code: "AI_CLOUD_FUNCTION_CLIENT_MISSING" } });
      }
      return withTimeout(
        client.callFunction({
          name: fn,
          data: {
            method,
            path,
            query: queryPayload,
            body,
            source: "wechat-cloud-ai",
          },
        }),
        cloud.aiFunctionTimeoutMs || 10000,
        "AI_CLOUD_FUNCTION_TIMEOUT",
        { path, source: "cloudFunction" }
      );
    })
    .then((res) => {
      const payload = normalizeCloudFunctionResult(res);
      if (!payload || typeof payload !== "object") {
        return payload;
      }
      if (payload.error) {
        return Promise.reject(payload);
      }
      return payload;
    });
}

function requestLlmApi(path, method, body = {}, data = {}) {
  const app = getApp();
  const cloud = app.globalData.cloud;
  const normalizedMethod = String(method || "GET").toUpperCase();
  const queryObject = data || {};
  const fallbackPayload = normalizedMethod === "POST"
    ? postApi(path, body, queryObject)
    : requestApi(path, queryObject);
  const aiResult = requestCloudFunctionAi(path, queryObject, body, normalizedMethod, cloud)
    .then((payload) => ({
      payload,
      source: "cloudFunction",
      fallbackUsed: false,
    }));

  return aiResult.catch((error) => {
    console.warn("[api] ai cloud function failed, fallback to container API", error);
    return fallbackPayload.then((payload) => ({
      payload,
      source: "container",
      fallbackUsed: true,
    }));
  });
}

function requestOfflineSnapshot(path, data, cloud, originalError) {
  if (cloud.offlineSnapshotFallback === false) return Promise.reject(originalError);
  if (shouldRequireLiveResponse(data)) return Promise.reject(originalError);

  // Prefer the last live response we ever persisted (mirrors the deployed
  // activity package) over the baked seed. This makes the offline view track
  // activity-package updates automatically — no frontend re-upload needed when
  // the weekly package changes. The baked OFFLINE_SNAPSHOT below only ever
  // shows on a first-ever launch that has never reached the network.
  const persisted = shouldBypassStoredRead(data) ? null : readPersistedResponse(path, data);
  if (persisted) return Promise.resolve(persisted);

  if (path === "/api/v1/weekly/current") {
    return Promise.resolve(cloneOfflinePayload(currentResponseFromStatic(OFFLINE_SNAPSHOT, data)));
  }

  if (path === "/api/v1/weekly/cities") {
    return Promise.resolve(cloneOfflinePayload(cityIndexFromStatic(OFFLINE_SNAPSHOT, data)));
  }

  if (path === "/api/v1/weekly/dates") {
    return Promise.resolve(cloneOfflinePayload(dateIndexFromStatic(OFFLINE_SNAPSHOT, data)));
  }

  if (path === "/api/v1/weekly/items/batch") {
    const ids = String(data.ids || "")
      .split(",")
      .map((id) => decodePathPart(id).trim())
      .filter(Boolean);
    const byId = {};
    for (const item of OFFLINE_SNAPSHOT.items) byId[item.id] = item;
    return Promise.resolve(cloneOfflinePayload(withResponseGeneration(
      { items: ids.map((id) => byId[id]).filter(Boolean) },
      OFFLINE_SNAPSHOT,
    )));
  }

  if (path.indexOf("/api/v1/weekly/items/") === 0) {
    const id = decodePathPart(path.replace("/api/v1/weekly/items/", "")).trim();
    const item = OFFLINE_SNAPSHOT.items.find((candidate) => candidate.id === id);
    if (item) return Promise.resolve(cloneOfflinePayload(withResponseGeneration(item, OFFLINE_SNAPSHOT)));
  }

  if (path.indexOf("/api/v1/weekly/source/") === 0) {
    const hash = safePathPart(path.replace("/api/v1/weekly/source/", ""));
    return Promise.resolve(cloneOfflinePayload({ url: OFFLINE_SOURCE_URLS[hash] || "" }));
  }

  if (path.indexOf("/api/v1/weekly/atlas-events/") === 0) {
    return Promise.resolve(cloneOfflinePayload({
      schemaVersion: "weekly_activity_api.atlas_event.v1",
      eventId: decodePathPart(path.replace("/api/v1/weekly/atlas-events/", "")).trim(),
      generatedAt: OFFLINE_SNAPSHOT.generatedAt,
      publishPackage: "offline-snapshot",
      lineupResolved: [],
      artistProfiles: [],
      safety: {
        graphWriteExecuted: false,
        qdrantWriteExecuted: false,
        productionWriteExecuted: false,
        fuzzyCandidateIdsExposed: false,
      },
    }));
  }

  return Promise.reject(originalError);
}

function requestFallback(path, query, data, cloud, originalError) {
  // An over-budget payload is already an unsafe response from a live detail
  // route. Do not disguise it as an offline/cache success; fail closed so it
  // can neither be rendered nor persisted under the requested generation.
  if (originalError && originalError.code === "WEEKLY_BATCH_RESPONSE_TOO_LARGE") {
    return Promise.reject(originalError);
  }
  if (cloud.publicBaseUrl) {
    return requestPublic(path, query, cloud).catch(() => {
      if (cloud.staticBaseUrl) {
        return requestStatic(path, data, cloud)
          .catch((staticError) => requestOfflineSnapshot(path, data, cloud, staticError));
      }
      return requestOfflineSnapshot(path, data, cloud, originalError).catch((snapshotError) => {
        if (cloud.devtoolsMockFallback && isDevtoolsRuntime() && cloud.mockBaseUrl) {
          return requestMock(path, query, cloud)
            .catch((mockError) => Promise.reject(mockError || snapshotError));
        }
        return Promise.reject(snapshotError);
      });
    });
  }
  if (cloud.staticBaseUrl) {
    return requestStatic(path, data, cloud)
      .catch((staticError) => requestOfflineSnapshot(path, data, cloud, staticError));
  }
  if (cloud.devtoolsMockFallback && isDevtoolsRuntime() && cloud.mockBaseUrl) {
    return requestMock(path, query, cloud)
      .catch((mockError) => requestOfflineSnapshot(path, data, cloud, mockError));
  }
  return requestOfflineSnapshot(path, data, cloud, originalError);
}

function requestContainerPublicFallback(path, query, data, cloud) {
  const containerPromise = requestCloudContainer(path, query, cloud);
  if (!cloud.publicBaseUrl) {
    return containerPromise.catch((error) => requestFallback(path, query, data, cloud, error));
  }

  const delayMs = Math.max(0, Number(cloud.publicFallbackDelayMs || 0));
  const snapshotDelayMs = Math.max(
    DEFAULT_OFFLINE_SNAPSHOT_FALLBACK_DELAY_MS,
    Number(cloud.offlineSnapshotFallbackDelayMs ?? DEFAULT_OFFLINE_SNAPSHOT_FALLBACK_DELAY_MS)
  );
  return new Promise((resolve, reject) => {
    let settled = false;
    let fallbackStarted = false;
    let containerError = null;
    let fallbackError = null;
    let fallbackTimer = null;
    let snapshotTimer = null;

    const resolveOnce = (value) => {
      if (settled) return;
      settled = true;
      if (fallbackTimer) clearTimeout(fallbackTimer);
      if (snapshotTimer) clearTimeout(snapshotTimer);
      resolve(value);
    };

    const rejectIfBothFailed = () => {
      if (settled || !fallbackStarted || !containerError || !fallbackError) return;
      settled = true;
      if (fallbackTimer) clearTimeout(fallbackTimer);
      if (snapshotTimer) clearTimeout(snapshotTimer);
      reject(fallbackError || containerError);
    };

    const startFallback = () => {
      if (fallbackStarted || settled) return;
      fallbackStarted = true;
      requestFallback(path, query, data, cloud, containerError)
        .then(resolveOnce, (error) => {
          fallbackError = error;
          rejectIfBothFailed();
        });
    };

    const startFastSnapshot = () => {
      if (settled || !canStartFastOfflineSnapshot(path, data, cloud)) return;
      requestOfflineSnapshot(path, data, cloud, containerError)
        .then(resolveOnce, () => {});
    };

    fallbackTimer = setTimeout(startFallback, delayMs);
    if (snapshotDelayMs >= 0) {
      snapshotTimer = setTimeout(startFastSnapshot, snapshotDelayMs);
    }
    containerPromise.then(resolveOnce, (error) => {
      containerError = error;
      startFallback();
      rejectIfBothFailed();
    });
  });
}

function requestCloudDatabaseWithBackup(path, query, data, cloud) {
  const backupCloud = Object.assign({}, cloud, { useCloudDatabaseFirst: false });
  const backupDelayMs = getCloudDatabaseBackupDelayMs(cloud);
  const configuredSnapshotDelayMs = Number(
    cloud.offlineSnapshotFallbackDelayMs ?? DEFAULT_OFFLINE_SNAPSHOT_FALLBACK_DELAY_MS
  );
  // A negative value is the public contract for disabling speculative
  // snapshot racing. Do not clamp it to zero: doing so lets stale cities,
  // dates and filtered feeds beat a healthy CloudBase/container response.
  const snapshotDelayMs = Number.isFinite(configuredSnapshotDelayMs)
    ? configuredSnapshotDelayMs
    : DEFAULT_OFFLINE_SNAPSHOT_FALLBACK_DELAY_MS;
  return new Promise((resolve, reject) => {
    let settled = false;
    let backupStarted = false;
    let dbError = null;
    let backupError = null;
    let backupTimer = null;
    let snapshotTimer = null;

    const resolveOnce = (value) => {
      if (settled) return;
      settled = true;
      if (backupTimer) clearTimeout(backupTimer);
      if (snapshotTimer) clearTimeout(snapshotTimer);
      resolve(value);
    };

    const rejectIfBothFailed = () => {
      if (settled || !dbError || !backupStarted || !backupError) return;
      settled = true;
      if (backupTimer) clearTimeout(backupTimer);
      if (snapshotTimer) clearTimeout(snapshotTimer);
      reject(backupError || dbError);
    };

    const startSnapshot = () => {
      if (settled || cloud.offlineSnapshotFallback === false || isDefaultCurrentFeedRequest(path, data)) return;
      requestOfflineSnapshot(path, data, cloud, dbError)
        .then(resolveOnce, () => {});
    };

    if (snapshotDelayMs >= 0) {
      snapshotTimer = setTimeout(startSnapshot, snapshotDelayMs);
    }

    const startBackup = () => {
      if (backupStarted || settled) return;
      backupStarted = true;
      requestContainerPublicFallback(path, query, data, backupCloud)
        .then(resolveOnce, (error) => {
          backupError = error;
          rejectIfBothFailed();
        });
    };

    backupTimer = setTimeout(startBackup, backupDelayMs);
    requestCloudDatabaseHot(path, data, cloud).then(resolveOnce, (error) => {
      dbError = error;
      disableCloudDatabaseHotTemporarily(error, cloud);
      if (!settled) {
        console.warn("[api] cloud database hot path failed, fallback to container API", error);
      }
      startBackup();
      rejectIfBothFailed();
    });
  });
}

function requestContainerOrFallback(path, query, data, cloud) {
  if (cloud.useCloudDatabaseFirst && isCloudDatabaseHotPath(path) && !isCloudDatabaseHotCircuitOpen(cloud)) {
    return requestCloudDatabaseWithBackup(path, query, data, cloud);
  }
  return requestContainerPublicFallback(path, query, data, cloud);
}
function postApi(path, body = {}, data = {}) {
  const app = getApp();
  const cloud = app.globalData.cloud;
  const { env, service } = cloud;
  const query = buildQuery({ ...data, _ts: Date.now() });
  return getCloudClient(cloud)
    .then((client) => client.callContainer({
      config: { env },
      path: `${path}${query}`,
      method: "POST",
      header: {
        "X-WX-SERVICE": service,
        "Content-Type": "application/json",
      },
      data: body,
    }))
    .then((res) => {
      const statusCode = Number(res && res.statusCode);
      if (statusCode && (statusCode < 200 || statusCode >= 300)) {
        return Promise.reject({ error: { code: "CONTAINER_STATUS", statusCode, path }, data: res.data });
      }
      return res.data;
    });
}

function requestApi(path, data = {}) {
  const app = getApp();
  const cloud = app.globalData.cloud;
  const { useMock } = cloud;
  const requestData = withKnownGeneration(path, data);
  try {
    assertBatchRequestBudget(path, requestData);
  } catch (error) {
    return Promise.reject(error);
  }
  const inflightKey = buildInflightKey(path, requestData);
  const existing = inflightRequests.get(inflightKey);
  if (existing) return existing;

  const query = buildQuery({ ...requestData, _ts: Date.now() });
  const rawPromise = useMock
    ? requestMock(path, query, cloud)
    : requestContainerOrFallback(path, query, requestData, cloud);
  const validatedPromise = rawPromise.then((value) => assertResponseGeneration(path, requestData, value));
  const requestPromise = withCachedResponse(validatedPromise, path, requestData, cloud).then(
    (value) => {
      if (inflightRequests.get(inflightKey) === requestPromise) {
        inflightRequests.delete(inflightKey);
      }
      return value;
    },
    (error) => {
      if (inflightRequests.get(inflightKey) === requestPromise) {
        inflightRequests.delete(inflightKey);
      }
      throw error;
    }
  );

  inflightRequests.set(inflightKey, requestPromise);
  return requestPromise;
}

async function fetchAllCurrentResponse(data = {}, requestPage = requestApi, onProgress = null) {
  const limit = Math.max(1, Math.min(100, Number(data.limit || 100)));
  const maxPages = Math.max(1, Math.min(200, Number(data.__maxPages || 100)));
  const base = { ...data, limit };
  delete base.__maxPages;
  const requestedScopeRaw = String(base.scope || "current").trim().toLowerCase();
  const requestedScope = requestedScopeRaw === "package" || requestedScopeRaw === "package_window" || requestedScopeRaw === "all"
    ? "package"
    : "current";
  let cursor = Number(base.cursor || 0);
  if (!Number.isFinite(cursor) || cursor < 0 || !Number.isInteger(cursor)) {
    throw new Error(`INVALID_CURRENT_CURSOR:${base.cursor}`);
  }
  const items = [];
  const seenIds = new Set();
  const seenCursors = new Set();
  let expectedTotal = null;
  let generatedAt = "";
  let generationId = "";
  let generationMode = "";
  let scope = "";
  let fromCache = false;
  let fromSnapshot = false;
  let filteredStoredItemCount = 0;
  const cacheTransaction = beginCurrentCacheTransaction(base);
  try {
    for (let pageIndex = 0; pageIndex < maxPages; pageIndex += 1) {
    if (seenCursors.has(cursor)) throw new Error(`CURRENT_CURSOR_LOOP:${cursor}`);
    seenCursors.add(cursor);
    const page = await requestPage("/api/v1/weekly/current", {
      ...base,
      cursor,
      __currentCacheTransaction: true,
    });
    const declaredCursor = page && page.page && page.page.cursor;
    if (declaredCursor !== undefined && declaredCursor !== null && declaredCursor !== "" && Number(declaredCursor) !== cursor) {
      throw new Error(`CURRENT_PAGE_CURSOR_MISMATCH:${declaredCursor}!=${cursor}`);
    }
    const nextCursor = page && page.page && page.page.nextCursor;
    if (nextCursor !== null && nextCursor !== undefined && nextCursor !== "") {
      const parsedNext = Number(nextCursor);
      if (!Number.isFinite(parsedNext) || parsedNext <= cursor || !Number.isInteger(parsedNext)) {
        throw new Error(`INVALID_CURRENT_CURSOR:${nextCursor}`);
      }
    }
    const pageTotal = Number(page && page.page && page.page.total);
    if (!Number.isFinite(pageTotal) || pageTotal < 0 || !Number.isInteger(pageTotal)) {
      throw new Error(`CURRENT_TOTAL_INVALID:${page && page.page && page.page.total}`);
    }
    if (expectedTotal === null) expectedTotal = pageTotal;
    else if (pageTotal !== expectedTotal) throw new Error(`CURRENT_TOTAL_DRIFT:${expectedTotal}->${pageTotal}`);
    const pageGenerationId = generationIdOf(page);
    const pageGeneratedAt = String(page && (page.generatedAt || page.generated_at) || "").trim();
    if (!generationMode) {
      if (pageGenerationId) {
        generationMode = "exact";
        generationId = pageGenerationId;
        generatedAt = pageGeneratedAt;
      } else {
        generationMode = "legacy";
        if (!pageGeneratedAt) throw new Error("CURRENT_GENERATION_MISSING");
        generatedAt = pageGeneratedAt;
      }
    } else if (generationMode === "exact") {
      if (!pageGenerationId) throw new Error("CURRENT_GENERATION_ID_MISSING");
      if (pageGenerationId !== generationId) {
        throw new Error(`CURRENT_GENERATION_ID_DRIFT:${generationId}->${pageGenerationId}`);
      }
    } else {
      if (pageGenerationId) throw new Error(`CURRENT_GENERATION_ID_DRIFT:<legacy>->${pageGenerationId}`);
      if (!pageGeneratedAt) throw new Error("CURRENT_GENERATION_MISSING");
      if (pageGeneratedAt !== generatedAt) {
        throw new Error(`CURRENT_GENERATION_DRIFT:${generatedAt}->${pageGeneratedAt}`);
      }
    }
    const pageScope = String(page && page.filters && page.filters.scope || "").trim().toLowerCase();
    if (!pageScope) throw new Error("CURRENT_SCOPE_MISSING");
    if (pageScope !== requestedScope) throw new Error(`CURRENT_SCOPE_MISMATCH:${pageScope}!=${requestedScope}`);
    if (!scope) scope = pageScope;
    else if (pageScope !== scope) throw new Error(`CURRENT_SCOPE_DRIFT:${scope}->${pageScope}`);
    fromCache = fromCache || Boolean(page && page.__fromCache);
    fromSnapshot = fromSnapshot || Boolean(page && page.__fromSnapshot);
    const pageIsStored = Boolean(page && (page.__fromCache || page.__fromSnapshot));
    const pageFilteredStoredCount = pageIsStored ? Number(page && page.__storedFilteredItemCount || 0) : 0;
    if (!Number.isInteger(pageFilteredStoredCount) || pageFilteredStoredCount < 0) {
      throw new Error(`CURRENT_STORED_FILTER_COUNT_INVALID:${page && page.__storedFilteredItemCount}`);
    }
    filteredStoredItemCount += pageFilteredStoredCount;
    for (const item of Array.isArray(page && page.items) ? page.items : []) {
      const key = String(item && (item.id || item.event_id || item.eventId) || "").trim();
      if (!key) throw new Error("CURRENT_EVENT_ID_MISSING");
      if (seenIds.has(key)) throw new Error(`CURRENT_EVENT_ID_DUPLICATE:${key}`);
      seenIds.add(key);
      items.push(item);
    }
    stageCurrentCachePage(cacheTransaction, page, cursor);
    if (items.length + filteredStoredItemCount > expectedTotal) {
      throw new Error(`CURRENT_TOTAL_OVERFLOW:${items.length}+${filteredStoredItemCount}>${expectedTotal}`);
    }
    if (typeof onProgress === "function") {
      onProgress({ loaded: items.length + filteredStoredItemCount, total: expectedTotal, pageIndex, cursor });
    }
    if (nextCursor === null || nextCursor === undefined || nextCursor === "") {
      if (items.length + filteredStoredItemCount !== expectedTotal) {
        throw new Error(`CURRENT_TOTAL_MISMATCH:${items.length}+${filteredStoredItemCount}!=${expectedTotal}`);
      }
      const complete = {
        items,
        total: items.length,
        generatedAt,
        generationId: generationId || null,
        scope,
        fromCache,
        fromSnapshot,
        filteredStoredItemCount,
      };
      const cacheCommitted = commitCurrentCacheTransaction(cacheTransaction, complete);
      // Keep the in-memory identity aligned with what is currently rendered,
      // but persist it only when the complete current-generation pointer was
      // activated by the same transaction. A quota failure must not leave a
      // new detail-generation token beside an older recoverable feed pointer.
      rememberCurrentGeneration(complete, cacheCommitted);
      return complete;
    }
    const parsedNext = Number(nextCursor);
    if (pageIndex + 1 >= maxPages) throw new Error(`CURRENT_PAGE_LIMIT_EXCEEDED:${maxPages}`);
    cursor = parsedNext;
    }
    throw new Error(`CURRENT_PAGE_LIMIT_EXCEEDED:${maxPages}`);
  } catch (error) {
    abortCurrentCacheTransaction(cacheTransaction);
    throw error;
  }
}

async function fetchAllCurrentItems(data = {}, requestPage = requestApi) {
  return (await fetchAllCurrentResponse(data, requestPage)).items;
}

module.exports = {
  __setTodayForTests(value) {
    todayOverride = isoDate(value);
  },
  __normalizeStoredCurrentPayloadForTests: normalizeStoredCurrentPayload,
  __currentResponseFromStaticForTests: currentResponseFromStatic,
  __cityIndexFromStaticForTests: cityIndexFromStatic,
  __dateIndexFromStaticForTests: dateIndexFromStatic,
  fetchAllCurrentItems,
  fetchAllCurrentResponse,
  postApi,
  requestApi,
  requestLlmApi,
};
