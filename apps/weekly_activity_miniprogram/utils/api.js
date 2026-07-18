function buildQuery(data) {
  const pairs = Object.keys(data || {})
    .filter((key) => !isRequestControlKey(key) && data[key] !== undefined && data[key] !== null && data[key] !== "")
    .map((key) => `${encodeURIComponent(key)}=${encodeURIComponent(data[key])}`);
  return pairs.length ? `?${pairs.join("&")}` : "";
}

function buildInflightKey(path, data) {
  return `${path}${buildQuery(data || {})}`;
}

const API_CACHE_PREFIX = "weeklyActivityApiCache:v20260704:";
const DEFAULT_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const DEFAULT_CACHE_FALLBACK_DELAY_MS = 2200;
const DEFAULT_REQUEST_TIMEOUT_MS = 8000;
const DEFAULT_OFFLINE_SNAPSHOT_FALLBACK_DELAY_MS = -1;
const DEFAULT_CLOUD_DATABASE_HOT_COOLDOWN_MS = 30 * 60 * 1000;
const DEFAULT_CLOUD_DATABASE_BACKUP_DELAY_MS = 250;
let cloudDatabaseHotDisabledUntil = 0;

const { OFFLINE_SNAPSHOT, OFFLINE_SOURCE_URLS = {} } = require("./offlineSnapshot");
const BUNDLED_CLUB_OVERVIEWS = require("../data/club_overviews");
const { isElectronicMusicRelevantItem } = require("./electronicRelevance");

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

function shouldSkipStoredFallback(data) {
  return Boolean(data && (data.__skipCache === true || data.__liveOnly === true));
}

function shouldRequireLiveResponse(data) {
  return Boolean(data && data.__liveOnly === true);
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
  const date = String((data && data.date) || "").trim();
  if (date && date !== "today") return false;
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
  if (!currentItems.length) return null;
  currentItems.sort((a, b) => {
    const aKey = isoDate(a.event_date_start) || itemDateKeys(a)[0] || "9999-12-31";
    const bKey = isoDate(b.event_date_start) || itemDateKeys(b)[0] || "9999-12-31";
    return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
  });
  return {
    ...payload,
    items: currentItems,
    page: {
      ...(payload.page || {}),
      nextCursor: null,
      total: currentItems.length,
    },
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
    !value ||
    typeof value !== "object" ||
    value.__fromCache ||
    value.__fromSnapshot ||
    !wx.setStorageSync
  ) return;
  try {
    wx.setStorageSync(cacheKey(path, data), {
      cachedAt: Date.now(),
      payload: value,
    });
  } catch {}
}

function withCachedResponse(rawPromise, path, data, cloud) {
  const cached = shouldSkipStoredFallback(data) ? null : readCachedResponse(path, data, cloud);
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
        writeCachedResponse(path, data, value);
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

function isoDate(value) {
  const text = String(value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

function addDateRange(dates, start, end) {
  if (!start || !end || start > end) return;
  const startMs = Date.parse(`${start}T00:00:00Z`);
  const endMs = Date.parse(`${end}T00:00:00Z`);
  const dayMs = 24 * 60 * 60 * 1000;
  const days = Math.round((endMs - startMs) / dayMs);
  if (!Number.isFinite(days) || days < 1 || days > 31) return;
  for (let offset = 1; offset < days; offset += 1) {
    dates.add(new Date(startMs + offset * dayMs).toISOString().slice(0, 10));
  }
}

function itemDateKeys(item) {
  const dates = new Set();
  for (const key of ["event_date_start", "event_date_end", "event_date_iso_guess"]) {
    const value = isoDate(item[key]);
    if (value) dates.add(value);
  }
  for (const key of ["event_date_iso_guesses", "event_date_text"]) {
    const raw = item[key];
    const values = Array.isArray(raw) ? raw : [raw];
    for (const value of values) {
      const date = isoDate(value);
      if (date) dates.add(date);
    }
  }
  addDateRange(dates, isoDate(item.event_date_start), isoDate(item.event_date_end));
  return Array.from(dates).sort();
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

function dedupeItems(items) {
  const output = [];
  const scopeIndexes = new Map();
  for (const item of items || []) {
    const scope = duplicateScopeKey(item);
    const candidateIndexes = scopeIndexes.get(scope) || [];
    let duplicateIndex = -1;
    for (const index of candidateIndexes) {
      if (areLikelyDuplicateItems(output[index], item)) {
        duplicateIndex = index;
        break;
      }
    }
    if (duplicateIndex === -1) {
      output.push(item);
      const outputIndex = output.length - 1;
      if (!scopeIndexes.has(scope)) scopeIndexes.set(scope, []);
      scopeIndexes.get(scope).push(outputIndex);
      continue;
    }
    if (itemQualityScore(item) > itemQualityScore(output[duplicateIndex])) {
      output[duplicateIndex] = item;
    }
  }
  return output;
}

function itemMatchesDate(item, date) {
  const target = isoDate(date);
  if (!target) return true;
  const dates = itemDateKeys(item);
  if (dates.indexOf(target) !== -1) return true;
  const start = isoDate(item.event_date_start) || dates[0] || "";
  const end = isoDate(item.event_date_end) || dates[dates.length - 1] || start;
  return Boolean(start && end && start <= target && target <= end);
}

let todayOverride = "";
const inflightRequests = new Map();

// Product rule: last night's events stay current until 07:00 next morning.
const LATE_NIGHT_CUTOFF_HOUR = 7;

function currentLocalDateKey() {
  if (todayOverride) return todayOverride;
  const now = new Date();
  if (now.getHours() < LATE_NIGHT_CUTOFF_HOUR) {
    now.setDate(now.getDate() - 1);
  }
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function itemIsCurrentOrFuture(item, today) {
  const target = isoDate(today);
  if (!target) return true;
  const dates = itemDateKeys(item);
  const start = isoDate(item.event_date_start) || dates[0] || "";
  const end = isoDate(item.event_date_end) || dates[dates.length - 1] || start;
  if (!start && !end) return true;
  return (end || start) >= target;
}

function filterDateIndexFromStatic(payload) {
  const today = currentLocalDateKey();
  const allDates = payload.dates || [];
  const dates = allDates.filter((entry) => {
    const dateValue = isoDate(entry.date);
    return !today || !dateValue || dateValue >= today;
  });
  return {
    ...payload,
    date_count: dates.length,
    item_count: dates.length,
    dates,
  };
}

function currentResponseFromStatic(payload, data) {
  const filters = {
    cityKey: data.cityKey || "all",
    date: data.date || "today",
  };
  const cursor = normalizeCursor(data.cursor);
  const limit = normalizeLimit(data.limit);
  const allItems = payload.items || [];
  const filterItems = (allowStaleDate) => dedupeItems(allItems.filter((item) => {
    const cityKeys = Array.isArray(item.city_keys) ? item.city_keys : [];
    const cityOk = !filters.cityKey
      || filters.cityKey === "all"
      || item.city_key === filters.cityKey
      || cityKeys.indexOf(filters.cityKey) !== -1;
    const dateOk = allowStaleDate
      ? true
      : (!filters.date || filters.date === "today"
        ? itemIsCurrentOrFuture(item, currentLocalDateKey())
        : itemMatchesDate(item, filters.date));
    const qualityOk = !item.quality_status || item.quality_status === "READY";
    return cityOk && dateOk && qualityOk && isElectronicMusicRelevantItem(item);
  }));
  let items = filterItems(false);
  items.sort((a, b) => {
    const aKey = isoDate(a.event_date_start) || itemDateKeys(a)[0] || "9999-12-31";
    const bKey = isoDate(b.event_date_start) || itemDateKeys(b)[0] || "9999-12-31";
    return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
  });
  const pageItems = items.slice(cursor, cursor + limit);

  return {
    schemaVersion: "weekly_activity_api.current_response.v1",
    generatedAt: payload.generated_at || payload.generatedAt,
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

function staticUrl(baseUrl, filePath) {
  const base = String(baseUrl || "").replace(/\/+$/, "");
  const path = String(filePath || "").replace(/^\/+/, "");
  return `${base}/${path}?_ts=${Date.now()}`;
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
    return requestJson(staticUrl(baseUrl, "current.json")).then((payload) => currentResponseFromStatic(payload, data));
  }

  if (path === "/api/v1/weekly/cities") {
    return requestJson(staticUrl(baseUrl, "by-city/index.json"));
  }

  if (path === "/api/v1/weekly/dates") {
    return requestJson(staticUrl(baseUrl, "by-date/index.json")).then(filterDateIndexFromStatic);
  }

  if (path === "/api/v1/weekly/manifest") {
    return requestJson(staticUrl(baseUrl, "manifest.json"));
  }

  if (path === "/api/v1/weekly/club-overviews") {
    return requestJson(staticUrl(baseUrl, "club_overviews.json"))
      .then((payload) => assertContainerData(path, { statusCode: 200, data: payload }));
  }

  if (path === "/api/v1/weekly/items/batch") {
    const ids = String(data.ids || "")
      .split(",")
      .map((id) => decodePathPart(id).trim())
      .filter(Boolean);
    const idSet = new Set(ids);
    return requestJson(staticUrl(baseUrl, "current.json")).then((payload) => {
      const byId = {};
      for (const item of payload.items || []) {
        if (idSet.has(item.id)) byId[item.id] = item;
      }
      return {
        items: ids.map((id) => byId[id]).filter(Boolean),
      };
    });
  }

  if (path.indexOf("/api/v1/weekly/items/") === 0) {
    const id = storageSlug(path.replace("/api/v1/weekly/items/", ""));
    return requestJson(staticUrl(baseUrl, `by-id/${id}.json`)).then((payload) => payload.item || payload);
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
  if (
    path === "/api/v1/weekly/club-overviews" &&
    (!payload.by_club || typeof payload.by_club !== "object" || Array.isArray(payload.by_club))
  ) {
    return Promise.reject({ error: { code: "CONTAINER_BAD_CLUB_OVERVIEWS", path }, data: payload });
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
  if (path === "/api/v1/weekly/items/batch") return true;
  if (path === "/api/v1/weekly/llm/materialized-summary") return true;
  if (path === "/api/v1/weekly/config") return true;
  if (path.indexOf("/api/v1/weekly/items/") === 0) return true;
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
            query: Object.assign({}, data || {}, { _ts: Date.now(), skipFreshness: "1" }),
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
  const persisted = shouldSkipStoredFallback(data) ? null : readPersistedResponse(path, data);
  if (persisted) return Promise.resolve(persisted);

  if (path === "/api/v1/weekly/current") {
    return Promise.resolve(cloneOfflinePayload(currentResponseFromStatic(OFFLINE_SNAPSHOT, data)));
  }

  if (path === "/api/v1/weekly/cities") {
    return Promise.resolve(cloneOfflinePayload({
      schema_version: "weekly_activity_miniprogram_city_index.v1",
      generated_at: OFFLINE_SNAPSHOT.generatedAt,
      city_count: OFFLINE_SNAPSHOT.cities.length,
      item_count: OFFLINE_SNAPSHOT.cities.length,
      cities: OFFLINE_SNAPSHOT.cities,
    }));
  }

  if (path === "/api/v1/weekly/dates") {
    return Promise.resolve(cloneOfflinePayload(filterDateIndexFromStatic({
      schema_version: "weekly_activity_miniprogram_date_index.v1",
      generated_at: OFFLINE_SNAPSHOT.generatedAt,
      dates: OFFLINE_SNAPSHOT.dates,
    })));
  }

  if (path === "/api/v1/weekly/club-overviews") {
    return Promise.resolve(cloneOfflinePayload(BUNDLED_CLUB_OVERVIEWS));
  }

  if (path === "/api/v1/weekly/items/batch") {
    const ids = String(data.ids || "")
      .split(",")
      .map((id) => decodePathPart(id).trim())
      .filter(Boolean);
    const byId = {};
    for (const item of OFFLINE_SNAPSHOT.items) byId[item.id] = item;
    return Promise.resolve(cloneOfflinePayload({ items: ids.map((id) => byId[id]).filter(Boolean) }));
  }

  if (path.indexOf("/api/v1/weekly/items/") === 0) {
    const id = decodePathPart(path.replace("/api/v1/weekly/items/", "")).trim();
    const item = OFFLINE_SNAPSHOT.items.find((candidate) => candidate.id === id);
    if (item) return Promise.resolve(cloneOfflinePayload(item));
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
  const snapshotDelayMs = Math.max(
    0,
    Number(cloud.offlineSnapshotFallbackDelayMs ?? 0)
  );
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
  const inflightKey = buildInflightKey(path, data);
  const existing = inflightRequests.get(inflightKey);
  if (existing) return existing;

  const query = buildQuery({ ...data, _ts: Date.now() });
  const rawPromise = useMock
    ? requestMock(path, query, cloud)
    : requestContainerOrFallback(path, query, data, cloud);
  const requestPromise = withCachedResponse(rawPromise, path, data, cloud).then(
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

module.exports = {
  __setTodayForTests(value) {
    todayOverride = isoDate(value);
  },
  postApi,
  requestApi,
  requestLlmApi,
};
