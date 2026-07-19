const { cityKeysForItem, dateKeysForFilter } = require("./homeFilters");
const { generatedAtOf, generationIdOf } = require("./generationContract");

function normalizedCount(entry) {
  const value = Number(entry && (entry.item_count ?? entry.count ?? entry.eventCount));
  return Number.isInteger(value) && value >= 0 ? value : null;
}

function addDays(dateKey, days) {
  const match = String(dateKey || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return "";
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  date.setUTCDate(date.getUTCDate() + Number(days || 0));
  return date.toISOString().slice(0, 10);
}

function dateAllowedByFacetFilters(dateKey, payload) {
  const filters = payload && payload.filters || {};
  const start = String(filters.dateStart || filters.date_start || "").trim();
  const end = String(filters.dateEnd || filters.date_end || start).trim();
  if (start) return dateKey >= start && dateKey <= (end || start);
  if (String(payload && payload.scope || "").trim().toLowerCase() !== "current") return true;
  const today = String(filters.today || "").trim();
  if (!today) return true;
  const lookback = Math.max(0, Math.min(45, Number.parseInt(filters.lookbackDays || 0, 10) || 0));
  return dateKey >= (lookback ? addDays(today, -lookback) : today);
}

function expectedBuckets(items, payload, collectionKey) {
  const buckets = new Map();
  for (const item of Array.isArray(items) ? items : []) {
    const keys = collectionKey === "cities" ? cityKeysForItem(item) : dateKeysForFilter(item);
    for (const rawKey of keys) {
      const key = String(rawKey || "").trim().toLowerCase();
      if (!key) continue;
      if (collectionKey === "dates" && !dateAllowedByFacetFilters(key, payload)) continue;
      buckets.set(key, (buckets.get(key) || 0) + 1);
    }
  }
  return buckets;
}

function actualBuckets(payload, collectionKey) {
  const buckets = new Map();
  for (const entry of payload[collectionKey]) {
    const rawKey = collectionKey === "cities"
      ? entry && (entry.city_key || entry.cityKey || entry.key)
      : entry && (entry.date || entry.key);
    const key = String(rawKey || "").trim().toLowerCase();
    const count = normalizedCount(entry);
    if (!key || count === null || buckets.has(key)) return null;
    buckets.set(key, count);
  }
  return buckets;
}

function bucketMapsEqual(expected, actual) {
  if (!actual || expected.size !== actual.size) return false;
  for (const [key, count] of expected) {
    if (actual.get(key) !== count) return false;
  }
  return true;
}

function facetPayloadMatchesVisibleSet(payload, items, expectedGeneration, collectionKey) {
  if (!payload || String(payload.scope || "").trim().toLowerCase() !== "current") return false;
  if (!Array.isArray(payload[collectionKey])) return false;
  const expectedItems = Array.isArray(items) ? items.length : 0;
  if (Number(payload.item_count) !== expectedItems) return false;
  const expectedIsObject = Boolean(expectedGeneration && typeof expectedGeneration === "object");
  const expectedGenerationId = expectedIsObject ? generationIdOf(expectedGeneration) : "";
  const actualGenerationId = generationIdOf(payload);
  if (expectedGenerationId || actualGenerationId) {
    if (!expectedGenerationId || !actualGenerationId || actualGenerationId !== expectedGenerationId) return false;
  } else {
    const expectedGeneratedAt = expectedIsObject
      ? generatedAtOf(expectedGeneration)
      : String(expectedGeneration || "").trim();
    const actualGeneratedAt = generatedAtOf(payload);
    if (!expectedGeneratedAt || !actualGeneratedAt || actualGeneratedAt !== expectedGeneratedAt) return false;
  }
  return bucketMapsEqual(
    expectedBuckets(items, payload, collectionKey),
    actualBuckets(payload, collectionKey),
  );
}

module.exports = {
  facetPayloadMatchesVisibleSet,
  generatedAtOf,
  generationIdOf,
};
