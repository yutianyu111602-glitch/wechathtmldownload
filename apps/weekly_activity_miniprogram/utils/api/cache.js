// utils/api/cache.js
// Extracted from api.js: cache storage, TTL, and withCachedResponse wrapper.
// All wx.* calls target the WeChat mini-program runtime global wx.

const API_CACHE_PREFIX = "weeklyActivityApiCache:v20260719-visibility-v2:";
const DEFAULT_CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const DEFAULT_CACHE_FALLBACK_DELAY_MS = 2200;

function stableData(value) {
  const out = {};
  for (const key of Object.keys(value || {}).sort()) {
    if (value[key] !== undefined && value[key] !== null && value[key] !== "") {
      out[key] = value[key];
    }
  }
  return out;
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

function readCachedResponse(path, data, cloud) {
  if (!canCachePath(path) || !wx.getStorageSync) return null;
  const maxAge = Number(cloud.cacheMaxAgeMs ?? DEFAULT_CACHE_MAX_AGE_MS);
  if (!Number.isFinite(maxAge) || maxAge <= 0) return null;
  try {
    const entry = wx.getStorageSync(cacheKey(path, data));
    const cachedAt = Number(entry && entry.cachedAt);
    if (!entry || !entry.payload || !Number.isFinite(cachedAt)) return null;
    if (Date.now() - cachedAt > maxAge) return null;
    return cloneCachedPayload(entry.payload, cachedAt);
  } catch {
    return null;
  }
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
  const cached = readCachedResponse(path, data, cloud);
  const delay = Math.max(0, Number(cloud.cacheFallbackDelayMs || DEFAULT_CACHE_FALLBACK_DELAY_MS));
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

module.exports = {
  API_CACHE_PREFIX,
  DEFAULT_CACHE_MAX_AGE_MS,
  DEFAULT_CACHE_FALLBACK_DELAY_MS,
  stableData,
  hashText,
  cacheKey,
  canCachePath,
  cloneCachedPayload,
  readCachedResponse,
  writeCachedResponse,
  withCachedResponse,
};
