const crypto = require("node:crypto");
const https = require("node:https");
const { URL } = require("node:url");
const tcb = require("@cloudbase/node-sdk");
const dateVisibility = require("./dateVisibility");

const {
  isoDate,
  itemDateKeys,
  itemIsCurrentOrFuture,
  itemMatchesDateKey,
  itemMatchesDateWindow,
  normalizeDateWindow,
} = dateVisibility;

const DEFAULT_BASE_URL = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com";
const DEFAULT_ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e";
const COLLECTIONS = {
  current: "weekly_current",
  events: "weekly_events",
  cities: "weekly_cities",
  aiSummary: "weekly_ai_summary",
  config: "weekly_config",
};

const app = tcb.init({
  env: process.env.TCB_ENV || process.env.ENV_ID || process.env.SCF_NAMESPACE || DEFAULT_ENV_ID,
});
const db = app.database();
const _ = db.command;
const DB_WRITE_BATCH_SIZE = Math.max(1, Math.min(10, Number(process.env.WEEKLY_DATA_SYNC_WRITE_BATCH_SIZE || 2)));
const DB_WRITE_BATCH_DELAY_MS = Math.max(0, Math.min(3000, Number(process.env.WEEKLY_DATA_SYNC_WRITE_BATCH_DELAY_MS || 400)));
const DB_RETRY_LIMIT = Math.max(0, Math.min(5, Number(process.env.WEEKLY_DATA_SYNC_DB_RETRY_LIMIT || 3)));
const MAX_BATCH_DETAIL_IDS = 100;
const MAX_BATCH_DETAIL_REQUEST_UTF8_BYTES = 16 * 1024;
const MAX_BATCH_DETAIL_RESPONSE_UTF8_BYTES = 2 * 1024 * 1024;
const ADMIN_ACTIONS = new Set(["sync", "diagnose", "probe"]);
// Warm-container cache for the live container build freshness, so the self-healing read-through
// check costs at most one tiny manifest GET per TTL window instead of one per current-read.
const CONTAINER_FRESHNESS_TTL_MS = Math.max(0, Number(process.env.WEEKLY_DATA_SYNC_FRESHNESS_TTL_MS || 5 * 60 * 1000));
let containerFreshnessCache = { value: null, checkedAt: 0 };
let testRequestJson = null;

function requestJson(pathOrUrl, timeoutMs = 12000) {
  if (testRequestJson) return Promise.resolve().then(() => testRequestJson(pathOrUrl, timeoutMs));
  const target = String(pathOrUrl).startsWith("http")
    ? new URL(pathOrUrl)
    : new URL(`${String(process.env.WEEKLY_DATA_SYNC_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, "")}${pathOrUrl}`);
  return new Promise((resolve, reject) => {
    const req = https.request(target, {
      method: "GET",
      timeout: timeoutMs,
      headers: {
        Accept: "application/json",
      },
    }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        let payload = null;
        try {
          payload = raw ? JSON.parse(raw) : {};
        } catch (error) {
          reject(Object.assign(new Error("Upstream returned non-JSON response"), { code: "UPSTREAM_NON_JSON" }));
          return;
        }
        if (res.statusCode < 200 || res.statusCode >= 300 || payload.error) {
          reject(Object.assign(new Error("Upstream request failed"), {
            code: "UPSTREAM_FAILED",
            statusCode: res.statusCode,
            data: payload,
          }));
          return;
        }
        resolve(payload);
      });
    });
    req.on("timeout", () => req.destroy(Object.assign(new Error("Upstream timed out"), { code: "UPSTREAM_TIMEOUT" })));
    req.on("error", reject);
    req.end();
  });
}

function setTestRequestJson(handler) {
  testRequestJson = typeof handler === "function" ? handler : null;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRequestLimitError(error) {
  const text = [
    error && error.code,
    error && error.errCode,
    error && error.message,
    error && error.errMsg,
  ].filter(Boolean).join(" ");
  return /EXCEED_REQUEST_LIMIT|LimitExceeded\.OutOf(Read|Write)RequestQuota|request overrun|overrun/i.test(text);
}

async function withDbRetry(operation) {
  let lastError = null;
  for (let attempt = 0; attempt <= DB_RETRY_LIMIT; attempt += 1) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (!isRequestLimitError(error) || attempt >= DB_RETRY_LIMIT) break;
      await sleep(800 * (attempt + 1));
    }
  }
  throw lastError;
}

function docId(value, prefix = "doc") {
  const input = String(value || "").trim();
  const safe = input.replace(/[^a-zA-Z0-9_-]/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);
  const hash = crypto.createHash("sha1").update(input || prefix).digest("hex").slice(0, 12);
  return `${prefix}_${safe || "empty"}_${hash}`.slice(0, 96);
}

function normalizeLimit(value) {
  const limit = Math.max(1, Math.min(100, Number(value || 20)));
  return Number.isFinite(limit) ? limit : 20;
}

function normalizeCursor(value) {
  const cursor = Math.max(0, Number(value || 0));
  return Number.isFinite(cursor) ? cursor : 0;
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

function decodeId(value) {
  try {
    return decodeURIComponent(String(value || "")).trim();
  } catch {
    return String(value || "").trim();
  }
}

function batchIdsFromQuery(query = {}) {
  const rawIds = String(query.ids || "");
  const requestBytes = utf8ByteLength(rawIds);
  if (requestBytes > MAX_BATCH_DETAIL_REQUEST_UTF8_BYTES) {
    throw Object.assign(new Error("weekly batch request exceeds the UTF-8 byte budget"), {
      code: "HOT_DB_BATCH_REQUEST_TOO_LARGE",
      requestBytes,
      maxRequestBytes: MAX_BATCH_DETAIL_REQUEST_UTF8_BYTES,
    });
  }
  const ids = rawIds.split(",").map(decodeId).filter(Boolean);
  if (ids.length < 1 || ids.length > MAX_BATCH_DETAIL_IDS) {
    throw Object.assign(new Error(`weekly batch requires 1-${MAX_BATCH_DETAIL_IDS} ids`), {
      code: "HOT_DB_BATCH_ID_LIMIT",
      idCount: ids.length,
      maxIds: MAX_BATCH_DETAIL_IDS,
    });
  }
  return ids;
}

function richDetailUnavailable(path, details = {}) {
  return {
    error: {
      code: "HOT_DB_RICH_DETAIL_UNAVAILABLE",
      message: "CloudBase stores compact list rows only; use the CloudRun rich-detail route.",
      path,
      fallback: "cloudrun",
      maxBatchIds: MAX_BATCH_DETAIL_IDS,
      maxBatchRequestUtf8Bytes: MAX_BATCH_DETAIL_REQUEST_UTF8_BYTES,
      maxBatchResponseUtf8Bytes: MAX_BATCH_DETAIL_RESPONSE_UTF8_BYTES,
      ...details,
    },
  };
}

function generationIdOf(value) {
  return String(value && (value.generationId || value.generation_id) || "").trim();
}

function generatedAtOf(value) {
  return String(value && (value.generatedAt || value.generated_at || value.syncedAt) || "").trim();
}

function assertGenerationHandshake(left, right, code = "GENERATION_HANDSHAKE_FAILED") {
  const leftId = generationIdOf(left);
  const rightId = generationIdOf(right);
  if (leftId || rightId) {
    if (!leftId || !rightId || leftId !== rightId) {
      throw Object.assign(
        new Error(`weekly generationId mismatch: ${leftId || "<missing>"} != ${rightId || "<missing>"}`),
        { code },
      );
    }
    return { mode: "exact", generationId: leftId, generatedAt: generatedAtOf(left) || generatedAtOf(right) || null };
  }
  const leftAt = generatedAtOf(left);
  const rightAt = generatedAtOf(right);
  if (!leftAt || !rightAt || leftAt !== rightAt) {
    throw Object.assign(
      new Error(`weekly legacy generatedAt mismatch: ${leftAt || "<missing>"} != ${rightAt || "<missing>"}`),
      { code },
    );
  }
  return { mode: "legacy", generationId: null, generatedAt: leftAt };
}

function assertRequestedGeneration(config, query = {}) {
  const requested = String(query.generationId || query.generation_id || "").trim();
  const active = generationIdOf(config);
  if (requested && (!active || active !== requested)) {
    throw Object.assign(
      new Error(`weekly requested generation mismatch: ${requested} != ${active || "<legacy>"}`),
      { code: "WEEKLY_REQUEST_GENERATION_MISMATCH" },
    );
  }
  const requestedAt = String(query.generatedAt || query.generated_at || "").trim();
  const activeAt = generatedAtOf(config);
  if (requestedAt && (active || !activeAt || requestedAt !== activeAt)) {
    throw Object.assign(
      new Error(`weekly requested generation mismatch: ${requestedAt} != ${active || activeAt || "<missing>"}`),
      { code: "WEEKLY_REQUEST_GENERATION_MISMATCH" },
    );
  }
}

const itemMatchesDate = itemMatchesDateKey;

function addDays(dateKey, days) {
  const match = String(dateKey || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function normalizeLookbackDays(value, fallback = 0) {
  const parsed = Number.parseInt(value ?? String(fallback), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(45, parsed));
}

function syncLookbackDaysFromEvent(event = {}) {
  void event;
  return 0;
}

function buildCurrentFetchPath(cursor, options = {}) {
  const limit = Math.max(1, Math.min(100, Number.parseInt(options.limit ?? "100", 10) || 100));
  const lookbackDays = normalizeLookbackDays(options.lookbackDays, 0);
  return `/api/v1/weekly/current?scope=current&limit=${limit}&lookbackDays=${lookbackDays}&cursor=${encodeURIComponent(cursor)}`;
}

function itemCityKeys(item = {}) {
  const values = [item.city_key, item.cityKey]
    .concat(Array.isArray(item.city_keys) ? item.city_keys : [])
    .concat(Array.isArray(item.cityKeys) ? item.cityKeys : []);
  return Array.from(new Set(values.map((value) => String(value || "").trim().toLowerCase()).filter(Boolean)));
}

function itemCityLabel(item, key, index) {
  const labels = Array.isArray(item.city) ? item.city : [item.city];
  return String(labels[index] || (index === 0 ? (item.city_name || item.cityName) : "") || key);
}

function todayKey(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const date = `${byType.year}-${byType.month}-${byType.day}`;
  return Number.parseInt(byType.hour || "0", 10) < 7 ? addDays(date, -1) : date;
}

function visibilitySpec(query = {}) {
  const lookbackDays = normalizeLookbackDays(query.lookbackDays);
  const today = todayKey();
  const date = isoDate(query.date);
  const window = date
    ? { dateStart: date, dateEnd: date }
    : normalizeDateWindow(query.dateStart || query.dateFrom, query.dateEnd || query.dateTo);
  const scope = String(query.scope || "").toLowerCase() === "package" ? "package" : "current";
  return {
    scope,
    cityKey: query.cityKey || "all",
    date: date || null,
    dateStart: window.dateStart || null,
    dateEnd: window.dateEnd || null,
    lookbackDays: scope === "current" && !date && !window.dateStart ? lookbackDays : null,
    today,
  };
}

function projectItems(currentDoc, query = {}, options = {}) {
  const filters = visibilitySpec(query);
  const currentThreshold = filters.lookbackDays > 0 ? addDays(filters.today, -filters.lookbackDays) : filters.today;
  const includeCity = options.includeCity !== false;
  const allItems = Array.isArray(currentDoc && currentDoc.items) ? currentDoc.items : [];
  const items = allItems.filter((item) => {
    const cityKeys = itemCityKeys(item);
    const cityOk = !includeCity || !filters.cityKey || filters.cityKey === "all"
      || cityKeys.includes(String(filters.cityKey).trim().toLowerCase());
    const dateOk = filters.date
      ? itemMatchesDate(item, filters.date)
      : filters.dateStart
        ? itemMatchesDateWindow(item, filters.dateStart, filters.dateEnd)
        : filters.scope === "package" || itemIsCurrentOrFuture(item, currentThreshold);
    const qualityOk = !item.quality_status || item.quality_status === "READY";
    return cityOk && dateOk && qualityOk;
  });
  return { filters, items };
}

function currentResponseFromItems(currentDoc, query = {}) {
  const projection = projectItems(currentDoc, query);
  const filters = projection.filters;
  const cursor = normalizeCursor(query.cursor);
  const limit = normalizeLimit(query.limit);
  const items = projection.items;
  const pageItems = items.slice(cursor, cursor + limit);
  return {
    schemaVersion: "weekly_activity_api.current_response.v1",
    generatedAt: currentDoc.generatedAt || currentDoc.generated_at || currentDoc.syncedAt,
    generationId: generationIdOf(currentDoc) || null,
    syncId: currentDoc.syncId || null,
    syncedAt: currentDoc.syncedAt || null,
    filters,
    page: {
      cursor,
      limit,
      nextCursor: cursor + limit < items.length ? String(cursor + limit) : null,
      total: items.length,
    },
    items: pageItems,
    source: "cloudbase-database",
  };
}

function cityIndexFromItems(currentDoc, query = {}) {
  const projection = projectItems(currentDoc, query, { includeCity: false });
  const bucket = new Map();
  for (const item of projection.items) {
    const cityKeys = itemCityKeys(item);
    for (let index = 0; index < cityKeys.length; index += 1) {
      const key = cityKeys[index];
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
  const cities = Array.from(bucket.values()).sort((left, right) => right.item_count - left.item_count || left.city_key.localeCompare(right.city_key));
  return {
    schema_version: "weekly_activity_miniprogram_city_index.v2",
    generated_at: currentDoc && (currentDoc.generatedAt || currentDoc.generated_at || currentDoc.syncedAt) || null,
    generation_id: generationIdOf(currentDoc) || null,
    generationId: generationIdOf(currentDoc) || null,
    syncId: currentDoc && currentDoc.syncId || null,
    syncedAt: currentDoc && currentDoc.syncedAt || null,
    scope: projection.filters.scope,
    filters: projection.filters,
    city_count: cities.length,
    item_count: projection.items.length,
    cities,
    source: "cloudbase-database",
  };
}

function dateIndexFromItems(currentDoc, query = {}) {
  const bucket = new Map();
  const projection = projectItems(currentDoc, query);
  const floor = projection.filters.scope === "current" && !projection.filters.dateStart
    ? (projection.filters.lookbackDays ? addDays(projection.filters.today, -projection.filters.lookbackDays) : projection.filters.today)
    : null;
  for (const item of projection.items) {
    for (const key of itemDateKeys(item || {})) {
      if (projection.filters.dateStart && (key < projection.filters.dateStart || key > projection.filters.dateEnd)) continue;
      if (floor && key < floor) continue;
      const current = bucket.get(key) || { date: key, count: 0, item_count: 0 };
      current.count += 1;
      current.item_count = current.count;
      bucket.set(key, current);
    }
  }
  const dates = Array.from(bucket.values()).sort((left, right) => left.date.localeCompare(right.date));
  return {
    schema_version: "weekly_activity_miniprogram_date_index.v2",
    generated_at: currentDoc && (currentDoc.generatedAt || currentDoc.generated_at || currentDoc.syncedAt) || null,
    generation_id: generationIdOf(currentDoc) || null,
    generationId: generationIdOf(currentDoc) || null,
    syncId: currentDoc && currentDoc.syncId || null,
    syncedAt: currentDoc && currentDoc.syncedAt || null,
    scope: projection.filters.scope,
    filters: projection.filters,
    date_count: dates.length,
    item_count: projection.items.length,
    dates,
    source: "cloudbase-database",
  };
}

function shouldSkipContainerFreshness(event = {}, query = {}) {
  // `event` and `query` are client-controlled cloud-function input. Never let
  // either one bypass the active-generation comparison.
  void event;
  void query;
  return false;
}

async function setDoc(collectionName, id, data) {
  return withDbRetry(() => db.collection(collectionName).doc(id).set(data));
}

async function writeInBatches(items, writer) {
  for (let i = 0; i < items.length; i += DB_WRITE_BATCH_SIZE) {
    const batch = items.slice(i, i + DB_WRITE_BATCH_SIZE);
    await Promise.all(batch.map(writer));
    if (i + DB_WRITE_BATCH_SIZE < items.length && DB_WRITE_BATCH_DELAY_MS > 0) {
      await sleep(DB_WRITE_BATCH_DELAY_MS);
    }
  }
}

function firstDoc(result) {
  if (!result) return null;
  if (Array.isArray(result.data)) return result.data[0] || null;
  return result.data || null;
}

async function getDoc(collectionName, id) {
  const result = await db.collection(collectionName).doc(id).get();
  return firstDoc(result);
}

async function removeDoc(collectionName, id) {
  return withDbRetry(() => db.collection(collectionName).doc(id).remove());
}

function generationDocId(syncId, prefix) {
  return docId(syncId, prefix);
}

function generationEventDocId(syncId, eventId) {
  return docId(`${syncId}:${eventId}`, "event");
}

function generationCityDocId(syncId, cityKey) {
  return docId(`${syncId}:${cityKey}`, "city");
}

async function activeConfig() {
  return getDoc(COLLECTIONS.config, "sync");
}

async function activeCurrentGeneration() {
  const config = await activeConfig();
  if (!config || !config.syncId) return { config, current: null };
  const currentId = config && config.currentDocId || "current";
  const current = await getDoc(COLLECTIONS.current, currentId);
  if (!current) return { config, current: null };
  if (current.syncId !== config.syncId) {
    return { config, current: null };
  }
  return { config, current };
}

function eventDocIdForConfig(config, eventId) {
  return config && config.eventDocIdScheme === "sync-prefixed-v1" && config.syncId
    ? generationEventDocId(config.syncId, eventId)
    : docId(eventId, "event");
}

async function removeGenerationDocuments(collectionName, syncId, activeSyncId) {
  if (!syncId || syncId === activeSyncId) return 0;
  let removed = 0;
  let complete = false;
  for (let guard = 0; guard < 100; guard += 1) {
    const latestConfig = await activeConfig();
    if (!latestConfig || latestConfig.syncId !== activeSyncId) {
      const error = new Error("active generation changed during cleanup");
      error.code = "ACTIVE_GENERATION_CHANGED_DURING_CLEANUP";
      throw error;
    }
    const result = await db.collection(collectionName).where({ syncId }).limit(100).get();
    const rows = Array.isArray(result && result.data) ? result.data : [];
    if (!rows.length) {
      complete = true;
      break;
    }
    const removable = rows.filter((row) => row && row._id);
    if (removable.length !== rows.length) {
      const error = new Error(`old-generation cleanup returned rows without _id in ${collectionName}`);
      error.code = "OLD_GENERATION_ROW_ID_MISSING";
      throw error;
    }
    await writeInBatches(removable, (row) => removeDoc(collectionName, row._id));
    removed += removable.length;
    if (rows.length < 100) {
      complete = true;
      break;
    }
  }
  if (!complete) {
    const error = new Error(`old-generation cleanup scan limit reached in ${collectionName}`);
    error.code = "OLD_GENERATION_CLEANUP_SCAN_LIMIT";
    throw error;
  }
  return removed;
}

async function cleanupPreviousGeneration(previousSyncId, activeSyncId) {
  if (!previousSyncId || previousSyncId === activeSyncId) {
    return { ok: true, previousSyncId: previousSyncId || null, removed: {} };
  }
  const removed = {};
  for (const collectionName of [
    COLLECTIONS.current,
    COLLECTIONS.events,
    COLLECTIONS.cities,
    COLLECTIONS.aiSummary,
    COLLECTIONS.config,
  ]) {
    removed[collectionName] = await removeGenerationDocuments(collectionName, previousSyncId, activeSyncId);
  }
  return { ok: true, previousSyncId, removed };
}

async function fetchAllCurrent(options = {}) {
  const requestedLookbackDays = normalizeLookbackDays(options.lookbackDays, 0);
  const allItems = [];
  const seenCursors = new Set();
  const seenEventIds = new Set();
  let cursor = "0";
  let firstPayload = null;
  let expectedGeneratedAt = null;
  let expectedGenerationId = null;
  let generationMode = null;
  let expectedTotal = null;
  let complete = false;
  for (let guard = 0; guard < 100; guard += 1) {
    if (seenCursors.has(cursor)) {
      throw Object.assign(new Error(`weekly current cursor loop: ${cursor}`), { code: "CURRENT_CURSOR_LOOP" });
    }
    seenCursors.add(cursor);
    const payload = await requestJson(buildCurrentFetchPath(cursor, options));
    if (!payload || !Array.isArray(payload.items) || !payload.page || typeof payload.page !== "object") {
      throw Object.assign(new Error("weekly current page contract is invalid"), { code: "CURRENT_PAGE_INVALID" });
    }
    const generatedAt = String(payload.generatedAt || payload.generated_at || "").trim();
    const generationId = generationIdOf(payload);
    const schemaVersion = String(payload.schemaVersion || payload.schema_version || "").trim();
    const total = Number(payload.page.total);
    const responseCursor = String(payload.page.cursor ?? cursor);
    const responseScope = String(payload.filters && payload.filters.scope || "").toLowerCase();
    const responseLookback = payload.filters && payload.filters.lookbackDays;
    if (!generationId && !generatedAt) {
      throw Object.assign(new Error("weekly current generation identity is missing"), { code: "CURRENT_GENERATION_MISSING" });
    }
    if (
      schemaVersion !== "weekly_activity_api.current_response.v1" ||
      !Number.isSafeInteger(total) ||
      total < 0 ||
      responseCursor !== cursor ||
      responseScope !== "current" ||
      Number(responseLookback ?? 0) !== requestedLookbackDays
    ) {
      throw Object.assign(new Error("weekly current page metadata is inconsistent"), { code: "CURRENT_PAGE_METADATA_MISMATCH" });
    }
    if (!firstPayload) {
      firstPayload = payload;
      expectedGeneratedAt = generatedAt;
      expectedGenerationId = generationId;
      generationMode = generationId ? "exact" : "legacy";
      expectedTotal = total;
    } else if (total !== expectedTotal) {
      throw Object.assign(new Error("weekly current total changed during pagination"), { code: "CURRENT_GENERATION_CHANGED" });
    } else if (generationMode === "exact" && (!generationId || generationId !== expectedGenerationId)) {
      throw Object.assign(new Error("weekly current generationId changed during pagination"), { code: "CURRENT_GENERATION_ID_CHANGED" });
    } else if (generationMode === "legacy" && (generationId || generatedAt !== expectedGeneratedAt)) {
      throw Object.assign(new Error("weekly current generation changed during pagination"), { code: "CURRENT_GENERATION_CHANGED" });
    }
    for (const item of payload.items) {
      const eventId = String(item && (item.id || item.event_id || item.eventId) || "").trim();
      if (!eventId) {
        throw Object.assign(new Error("weekly current item is missing an id"), { code: "CURRENT_EVENT_ID_MISSING" });
      }
      if (seenEventIds.has(eventId)) {
        throw Object.assign(new Error(`weekly current duplicate event id: ${eventId}`), { code: "CURRENT_EVENT_ID_DUPLICATE" });
      }
      seenEventIds.add(eventId);
      allItems.push(item);
    }
    const nextCursor = payload.page.nextCursor;
    if (nextCursor === null || nextCursor === undefined || nextCursor === "") {
      complete = true;
      break;
    }
    const parsedNext = Number(nextCursor);
    const parsedCurrent = Number(cursor);
    if (!Number.isSafeInteger(parsedNext) || parsedNext <= parsedCurrent || String(parsedNext) !== String(nextCursor)) {
      throw Object.assign(new Error(`weekly current cursor did not advance: ${nextCursor}`), { code: "CURRENT_CURSOR_INVALID" });
    }
    cursor = String(parsedNext);
  }
  if (!complete) {
    throw Object.assign(new Error("weekly current pagination did not terminate"), { code: "CURRENT_PAGINATION_LIMIT" });
  }
  if (allItems.length !== expectedTotal) {
    throw Object.assign(
      new Error(`weekly current total mismatch: expected=${expectedTotal} actual=${allItems.length}`),
      { code: "CURRENT_TOTAL_MISMATCH" },
    );
  }
  return {
    ...(firstPayload || {}),
    page: {
      limit: allItems.length,
      cursor: "0",
      nextCursor: null,
      total: allItems.length,
    },
    items: allItems,
  };
}

async function getContainerFreshness() {
  const now = Date.now();
  const cached = containerFreshnessCache;
  if (cached.value && CONTAINER_FRESHNESS_TTL_MS > 0 && now - cached.checkedAt < CONTAINER_FRESHNESS_TTL_MS) {
    return cached.value;
  }
  const manifest = await requestJson("/api/v1/weekly/manifest", 6000);
  // Only `generated_at` is a comparable freshness signal. `item_count` counts ALL items while the
  // hot DB doc stores the READY-filtered `/current` count, so comparing counts is apples-to-oranges
  // and would mark the DB perpetually stale (defeating the DB-first cost guard).
  const value = {
    generatedAt: manifest.generated_at || manifest.generatedAt || null,
    generationId: generationIdOf(manifest) || null,
  };
  containerFreshnessCache = { value, checkedAt: now };
  return value;
}

async function syncData(event = {}) {
  const syncId = `weekly_${Date.now()}_${crypto.randomBytes(4).toString("hex")}`;
  const syncedAt = new Date().toISOString();
  const baseUrl = String(event.baseUrl || process.env.WEEKLY_DATA_SYNC_BASE_URL || DEFAULT_BASE_URL).replace(/\/+$/, "");
  process.env.WEEKLY_DATA_SYNC_BASE_URL = baseUrl;
  const syncLookbackDays = syncLookbackDaysFromEvent(event);
  const previousConfig = await activeConfig();
  const previousSyncId = previousConfig && previousConfig.syncId || null;

  const current = await fetchAllCurrent({ scope: "current", lookbackDays: syncLookbackDays });
  const manifest = await requestJson("/api/v1/weekly/manifest");
  const remoteGeneration = assertGenerationHandshake(current, manifest, "CURRENT_MANIFEST_GENERATION_MISMATCH");
  let aiSummary = null;
  let aiSummaryError = null;
  try {
    aiSummary = await requestJson("/api/v1/weekly/llm/materialized-summary");
  } catch (error) {
    aiSummaryError = {
      code: error.code || "AI_SUMMARY_FETCH_FAILED",
      message: error.message || String(error),
      statusCode: error.statusCode || 0,
    };
  }

  const currentDoc = {
    syncId,
    syncedAt,
    source: "cloudrun-weekly-api",
    sourceBaseUrl: baseUrl,
    schemaVersion: current.schemaVersion || current.schema_version || "weekly_activity_api.current_response.v1",
    generatedAt: current.generatedAt || current.generated_at || null,
    generationId: remoteGeneration.generationId,
    itemCount: (current.items || []).length,
    currentItemCount: (current.items || []).length,
    packageItemCount: Number(manifest && (manifest.item_count ?? manifest.items_total)) || null,
    facetScope: "current",
    items: current.items || [],
    syncLookbackDays,
  };
  const currentDocId = generationDocId(syncId, "current");
  const aiSummaryDocId = generationDocId(syncId, "ai-summary");
  const routesDocId = generationDocId(syncId, "routes");
  await setDoc(COLLECTIONS.current, currentDocId, currentDoc);
  const cities = cityIndexFromItems(currentDoc, { scope: "current", lookbackDays: syncLookbackDays });

  const eventDocs = [];
  for (const item of current.items || []) {
    if (!item || !item.id) continue;
    eventDocs.push({
      id: generationEventDocId(syncId, item.id),
      data: {
        syncId,
        syncedAt,
        generatedAt: currentDoc.generatedAt,
        generationId: remoteGeneration.generationId,
        eventId: item.id,
        cityKey: item.city_key || item.cityKey || "",
        eventDateStart: item.event_date_start || "",
        eventDateEnd: item.event_date_end || "",
        title: item.title || "",
        item,
      },
    });
  }
  await writeInBatches(eventDocs, (doc) => setDoc(COLLECTIONS.events, doc.id, doc.data));

  const cityDocs = [];
  for (const city of cities.cities || []) {
    const cityKey = city.city_key || city.cityKey || city.city || "";
    if (!cityKey) continue;
    cityDocs.push({
      id: generationCityDocId(syncId, cityKey),
      data: {
        syncId,
        syncedAt,
        generationId: remoteGeneration.generationId,
        ...city,
      },
    });
  }
  await writeInBatches(cityDocs, (doc) => setDoc(COLLECTIONS.cities, doc.id, doc.data));

  await setDoc(COLLECTIONS.aiSummary, aiSummaryDocId, {
    syncId,
    syncedAt,
    payload: aiSummary,
    error: aiSummaryError,
  });

  const config = {
    syncId,
    syncedAt,
    sourceBaseUrl: baseUrl,
    collections: COLLECTIONS,
    counts: {
      events: (current.items || []).length,
      cities: (cities.cities || []).length,
      currentItems: (current.items || []).length,
      packageItems: currentDoc.packageItemCount,
      aiSummary: aiSummary ? 1 : 0,
    },
    generatedAt: current.generatedAt || current.generated_at || null,
    generationId: remoteGeneration.generationId,
    syncLookbackDays,
    facetScope: "current",
    currentDocId,
    aiSummaryDocId,
    routesDocId,
    eventDocIdScheme: "sync-prefixed-v1",
    cityDocIdScheme: "sync-prefixed-v1",
    richDetailGenerationComplete: false,
    aiSummaryError,
  };
  await setDoc(COLLECTIONS.config, routesDocId, {
    syncId,
    syncedAt,
    hotPaths: [
      "/api/v1/weekly/config",
      "/api/v1/weekly/current",
      "/api/v1/weekly/cities",
      "/api/v1/weekly/dates",
      "/api/v1/weekly/llm/materialized-summary",
    ],
    deferredPaths: {
      "/api/v1/weekly/items/batch": "cloudrun-rich-detail-required",
      "/api/v1/weekly/items/:id": "cloudrun-rich-detail-required",
    },
  });
  // This singleton write is the atomic generation switch. Every generation
  // artifact above is immutable and fully staged before readers can select it.
  await setDoc(COLLECTIONS.config, "sync", config);

  let cleanup;
  try {
    cleanup = await cleanupPreviousGeneration(previousSyncId, syncId);
  } catch (error) {
    return {
      ok: false,
      status: "active_generation_committed_cleanup_incomplete",
      activeGenerationCommitted: true,
      syncId,
      syncedAt,
      generatedAt: config.generatedAt,
      generationId: config.generationId,
      counts: config.counts,
      collections: COLLECTIONS,
      aiSummaryError,
      cleanup: {
        ok: false,
        previousSyncId,
        error: {
          code: error.code || "OLD_GENERATION_CLEANUP_FAILED",
          message: error.message || String(error),
        },
      },
    };
  }

  return {
    ok: true,
    status: "active_generation_committed",
    syncId,
    syncedAt,
    generatedAt: config.generatedAt,
    generationId: config.generationId,
    counts: config.counts,
    collections: COLLECTIONS,
    aiSummaryError,
    cleanup,
  };
}

async function diagnoseDatabase(event = {}) {
  const id = String(event.id || "runtime_probe");
  const doc = {
    id,
    source: "weeklyDataSync.diagnoseDatabase",
    wroteAt: new Date().toISOString(),
    random: Math.random().toString(16).slice(2),
  };
  const result = {
    ok: false,
    env: process.env.TCB_ENV || process.env.ENV_ID || process.env.SCF_NAMESPACE || DEFAULT_ENV_ID,
    collection: COLLECTIONS.config,
    id,
    write: null,
    read: null,
  };
  try {
    const write = await setDoc(COLLECTIONS.config, id, doc);
    result.write = {
      ok: true,
      raw: write,
    };
  } catch (error) {
    result.write = {
      ok: false,
      code: error.code || error.errCode || "WRITE_FAILED",
      message: error.message || error.errMsg || String(error),
    };
    return result;
  }
  try {
    const read = await getDoc(COLLECTIONS.config, id);
    result.read = {
      ok: Boolean(read),
      doc: read || null,
    };
  } catch (error) {
    result.read = {
      ok: false,
      code: error.code || error.errCode || "READ_FAILED",
      message: error.message || error.errMsg || String(error),
    };
    return result;
  }
  result.ok = Boolean(result.write && result.write.ok && result.read && result.read.ok);
  return result;
}

function adminActionAllowed(event = {}) {
  const expected = String(process.env.WEEKLY_DATA_SYNC_ADMIN_TOKEN || "").trim();
  const actual = String(event.adminToken || "").trim();
  return Boolean(expected && actual && expected === actual);
}

function upstreamPath(path, query = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query || {})) {
    if (key === "skipFreshness" || value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const suffix = params.toString();
  return suffix ? `${path}?${suffix}` : path;
}

async function currentDocForRead(event = {}, query = {}) {
  const active = await activeCurrentGeneration();
  const current = active.current;
  let live = null;
  if (!shouldSkipContainerFreshness(event, query)) {
    try {
      live = await getContainerFreshness();
    } catch (_) {
      live = null;
    }
  }
  let dbBehindContainer = false;
  if (live) {
    try {
      assertGenerationHandshake(current, live, "HOT_DB_CONTAINER_GENERATION_MISMATCH");
    } catch (_) {
      dbBehindContainer = true;
    }
  }
  const requestedLookback = normalizeLookbackDays(query.lookbackDays, 0);
  const storedLookback = normalizeLookbackDays(current && current.syncLookbackDays, 0);
  const dbWindowTooNarrow = requestedLookback > storedLookback;
  if (!current || dbBehindContainer || dbWindowTooNarrow) {
    try {
      const fresh = await fetchAllCurrent({ lookbackDays: requestedLookback });
      if (live) {
        assertGenerationHandshake(fresh, live, "READTHROUGH_MANIFEST_GENERATION_MISMATCH");
      }
      return {
        doc: fresh,
        source: "container-readthrough",
        staleReason: !current ? "db-empty" : dbBehindContainer ? "db-behind-container" : "db-window-too-narrow",
      };
    } catch (error) {
      // Never relabel a narrow persisted window as a wider query result. A
      // stale same-window document may remain useful when the container is
      // temporarily unavailable, but it cannot satisfy historical lookback.
      if (!current || dbWindowTooNarrow) throw error;
    }
  }
  return { doc: current, source: "cloudbase-database", staleReason: null };
}

async function readData(event = {}) {
  const path = String(event.path || "");
  const query = event.query || {};
  if (path === "/api/v1/weekly/config") {
    const config = await activeConfig();
    return config ? { ...config, source: "cloudbase-database" } : null;
  }
  if (path === "/api/v1/weekly/current") {
    if (String(query.scope || "").toLowerCase() === "package") {
      return requestJson(upstreamPath(path, query));
    }
    try {
      const resolved = await currentDocForRead(event, query);
      const response = currentResponseFromItems(resolved.doc, query);
      response.source = resolved.source;
      if (resolved.staleReason) response.staleReason = resolved.staleReason;
      return response;
    } catch (_) {
      return { error: { code: "HOT_DB_EMPTY", path } };
    }
  }
  if (path === "/api/v1/weekly/dates") {
    if (String(query.scope || "").toLowerCase() === "package") {
      return requestJson(upstreamPath(path, query));
    }
    try {
      const resolved = await currentDocForRead(event, query);
      const response = dateIndexFromItems(resolved.doc, query);
      response.source = resolved.source;
      if (resolved.staleReason) response.staleReason = resolved.staleReason;
      return response;
    } catch (_) {
      return { error: { code: "HOT_DB_EMPTY", path } };
    }
  }
  if (path === "/api/v1/weekly/cities") {
    if (String(query.scope || "").toLowerCase() === "package") {
      return requestJson(upstreamPath(path, query));
    }
    try {
      const resolved = await currentDocForRead(event, query);
      const response = cityIndexFromItems(resolved.doc, query);
      response.source = resolved.source;
      if (resolved.staleReason) response.staleReason = resolved.staleReason;
      return response;
    } catch (_) {
      return { error: { code: "HOT_DB_EMPTY", path } };
    }
  }
  if (path === "/api/v1/weekly/llm/materialized-summary") {
    const config = await activeConfig();
    const aiSummaryDocId = config && config.aiSummaryDocId || "materialized-summary";
    const doc = await getDoc(COLLECTIONS.aiSummary, aiSummaryDocId);
    if (!config || !config.syncId || !doc || !doc.payload || doc.syncId !== config.syncId) {
      return { error: doc && doc.error || { code: "HOT_DB_AI_SUMMARY_EMPTY", path } };
    }
    return {
      ...doc.payload,
      source: "cloudbase-database",
      cloudDatabase: {
        collection: COLLECTIONS.aiSummary,
        syncId: doc.syncId,
        syncedAt: doc.syncedAt,
      },
    };
  }
  if (path === "/api/v1/weekly/items/batch") {
    const config = await activeConfig();
    assertRequestedGeneration(config, query);
    const ids = batchIdsFromQuery(query);
    // Deliberately no per-id database reads here. Until a sync generation
    // contains validated rich by-id DTOs, the mini-program performs one
    // bounded CloudRun batch request instead of an N+1 CloudBase loop.
    return richDetailUnavailable(path, { idCount: ids.length });
  }
  if (path.indexOf("/api/v1/weekly/items/") === 0) {
    const config = await activeConfig();
    assertRequestedGeneration(config, query);
    const id = decodeId(path.replace("/api/v1/weekly/items/", ""));
    return richDetailUnavailable(path, { id });
  }
  return {
    error: {
      code: "HOT_DB_PATH_NOT_SUPPORTED",
      path,
    },
  };
}

exports.main = async (event = {}) => {
  const action = String(event.action || "read").toLowerCase();
  try {
    if (ADMIN_ACTIONS.has(action) && !adminActionAllowed(event)) {
      return {
        error: {
          code: "ADMIN_ACTION_UNAUTHORIZED",
          action,
        },
      };
    }
    if (action === "sync") return await syncData(event);
    if (action === "read") return await readData(event);
    if (action === "diagnose" || action === "probe") return await diagnoseDatabase(event);
    return {
      error: {
        code: "ACTION_NOT_SUPPORTED",
        action,
      },
    };
  } catch (error) {
    return {
      error: {
        code: error.code || "WEEKLY_DATA_SYNC_FAILED",
        message: error.message || String(error),
        statusCode: error.statusCode || 0,
        data: error.data || null,
      },
    };
  }
};

exports.__test = {
  fetchAllCurrent,
  generationEventDocId,
  readData,
  setTestRequestJson,
  syncData,
  cityIndexFromItems,
  currentResponseFromItems,
  dateIndexFromItems,
  itemDateKeys,
  itemMatchesDate,
  itemMatchesDateWindow,
  itemCityKeys,
  projectItems,
  shouldSkipContainerFreshness,
  syncLookbackDaysFromEvent,
  buildCurrentFetchPath,
};
