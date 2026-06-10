// services/homeFilters.js
// Extracted from pages/index/index.js: city/date filter primitives.
// Pure functions — no wx, no side effects.
// Inlined datePreview helpers to avoid WeChat cross-dir require failure.

// --- Inlined from utils/datePreview.js ---
function _isoDate(value) {
  const text = String(value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

function _itemDateKeys(item) {
  if (!item || typeof item !== "object") return [];
  const directCandidates = [
    item.dateLabel, item.event_date_start, item.eventDateStart,
    item.event_date_iso_guess, item.eventDateIso, item.event_date,
    item.date, item.event_date_end, item.eventDateEnd,
  ];
  const directDates = directCandidates.map(_isoDate).filter(Boolean);
  const candidates = directDates.length
    ? directCandidates
    : [...directCandidates, ...(Array.isArray(item.event_date_iso_guesses) ? item.event_date_iso_guesses : [])];
  const out = [];
  const seen = new Set();
  for (const value of candidates) {
    const text = _isoDate(value);
    if (text && !seen.has(text)) { seen.add(text); out.push(text); }
  }
  return out;
}

function itemDateBounds(item) {
  const keys = _itemDateKeys(item).sort();
  if (!keys.length) return null;
  const explicitEnd = _isoDate((item || {}).event_date_end || (item || {}).eventDateEnd);
  const start = _isoDate((item || {}).event_date_start || (item || {}).eventDateStart || (item || {}).dateLabel) || keys[0];
  const end = explicitEnd || keys[keys.length - 1] || start;
  const flags = Array.isArray((item || {}).quality_flags) ? item.quality_flags : [];
  const isRange = Boolean(explicitEnd || (item || {}).isCalendarPreview || (item || {}).is_calendar_preview || flags.includes("calendar_preview"));
  return { start, end: end >= start ? end : start, keys, isRange };
}

function itemMatchesDateKey(item, dateKey) {
  const key = _isoDate(dateKey);
  if (!key) return false;
  const bounds = itemDateBounds(item);
  if (!bounds) return false;
  return bounds.keys.includes(key) || (bounds.isRange && bounds.start <= key && bounds.end >= key);
}
// --- End inlined datePreview ---

function normalizeIsoDate(value) {
  const textValue = String(value || "").trim();
  const match = textValue.match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : "";
}

function dateFromKey(key) {
  const match = String(key || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function keyFromDate(date) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function addDateRangeKeys(keys, startKey, endKey) {
  const start = dateFromKey(startKey);
  const end = dateFromKey(endKey);
  if (!start || !end || end < start) return;
  for (let date = new Date(start); date <= end && keys.size < 64; date.setDate(date.getDate() + 1)) {
    keys.add(keyFromDate(date));
  }
}

function dateKeysForFilter(item) {
  const bounds = itemDateBounds(item);
  if (!bounds) return [];
  const keys = new Set((bounds.keys || []).map(normalizeIsoDate).filter(Boolean));
  if (bounds.isRange) {
    addDateRangeKeys(keys, bounds.start, bounds.end);
  }
  return Array.from(keys).sort();
}

function itemMatchesCityKey(item, cityKey) {
  const key = String(cityKey || "").trim();
  if (!key) return true;
  const direct = String(item?.city_key || "").trim();
  if (direct === key) return true;
  const keys = Array.isArray(item?.city_keys) ? item.city_keys : [];
  return keys.map((value) => String(value || "").trim()).includes(key);
}

function filterItemsByCityKey(items, cityKey) {
  const source = Array.isArray(items) ? items : [];
  const key = String(cityKey || "").trim();
  if (!key) return source;
  return source.filter((item) => itemMatchesCityKey(item, key));
}

function filterItemsByDateKey(items, dateKey) {
  const source = Array.isArray(items) ? items : [];
  const key = normalizeIsoDate(dateKey);
  if (!key) return source;
  return source.filter((item) => itemMatchesDateKey(item, key));
}

function filterItemsByActiveFilters(items, cityKey, dateKey) {
  return filterItemsByDateKey(filterItemsByCityKey(items, cityKey), dateKey);
}

module.exports = {
  addDateRangeKeys,
  dateFromKey,
  dateKeysForFilter,
  filterItemsByActiveFilters,
  filterItemsByCityKey,
  filterItemsByDateKey,
  itemMatchesCityKey,
  keyFromDate,
  normalizeIsoDate,
};
