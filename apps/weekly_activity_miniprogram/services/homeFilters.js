// services/homeFilters.js
// Extracted from pages/index/index.js: city/date filter primitives.
// Pure functions — no wx, no side effects.
// Tries require("../utils/datePreview") first; falls back to inline copies
// when WeChat's sandboxed module system cannot resolve cross-directory requires.

var _dp;
try {
  _dp = require("../utils/datePreview");
} catch (_e) {
  _dp = null;
}

function _isoDate(value) {
  var text = String(value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

function _itemDateKeys(item) {
  if (!item || typeof item !== "object") return [];
  var directCandidates = [
    item.dateLabel, item.event_date_start, item.eventDateStart,
    item.event_date_iso_guess, item.eventDateIso, item.event_date,
    item.date, item.event_date_end, item.eventDateEnd,
  ];
  var directDates = directCandidates.map(_isoDate).filter(Boolean);
  var candidates = directDates.length
    ? directCandidates
    : directCandidates.concat(Array.isArray(item.event_date_iso_guesses) ? item.event_date_iso_guesses : []);
  var out = [];
  var seen = {};
  for (var i = 0; i < candidates.length; i++) {
    var t = _isoDate(candidates[i]);
    if (t && !seen[t]) { seen[t] = true; out.push(t); }
  }
  return out;
}

function _itemDateBounds(item) {
  var keys = _itemDateKeys(item).sort();
  if (!keys.length) return null;
  var explicitEnd = _isoDate((item || {}).event_date_end || (item || {}).eventDateEnd);
  var start = _isoDate((item || {}).event_date_start || (item || {}).eventDateStart || (item || {}).dateLabel) || keys[0];
  var end = explicitEnd || keys[keys.length - 1] || start;
  var flags = Array.isArray((item || {}).quality_flags) ? item.quality_flags : [];
  var isRange = Boolean(explicitEnd || (item || {}).isCalendarPreview || (item || {}).is_calendar_preview || flags.indexOf("calendar_preview") !== -1);
  return { start: start, end: end >= start ? end : start, keys: keys, isRange: isRange };
}

function _itemMatchesDateKey(item, dateKey) {
  var key = _isoDate(dateKey);
  if (!key) return false;
  var bounds = _itemDateBounds(item);
  if (!bounds) return false;
  return bounds.keys.indexOf(key) !== -1 || (bounds.isRange && bounds.start <= key && bounds.end >= key);
}

var itemDateBounds = _dp ? _dp.itemDateBounds : _itemDateBounds;
var itemMatchesDateKey = _dp ? _dp.itemMatchesDateKey : _itemMatchesDateKey;

function normalizeIsoDate(value) {
  var match = String(value || "").trim().match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : "";
}

function dateFromKey(key) {
  var match = String(key || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  var date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
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
  var start = dateFromKey(startKey);
  var end = dateFromKey(endKey);
  if (!start || !end || end < start) return;
  for (var date = new Date(start); date <= end && keys.size < 64; date.setDate(date.getDate() + 1)) {
    keys.add(keyFromDate(date));
  }
}

function dateKeysForFilter(item) {
  var bounds = itemDateBounds(item);
  if (!bounds) return [];
  var keys = new Set((bounds.keys || []).map(normalizeIsoDate).filter(Boolean));
  if (bounds.isRange) {
    addDateRangeKeys(keys, bounds.start, bounds.end);
  }
  return Array.from(keys).sort();
}

function itemMatchesCityKey(item, cityKey) {
  var key = String(cityKey || "").trim();
  if (!key) return true;
  var direct = String((item || {}).city_key || "").trim();
  if (direct === key) return true;
  var keys = Array.isArray((item || {}).city_keys) ? item.city_keys : [];
  for (var i = 0; i < keys.length; i++) {
    if (String(keys[i] || "").trim() === key) return true;
  }
  return false;
}

function filterItemsByCityKey(items, cityKey) {
  var source = Array.isArray(items) ? items : [];
  var key = String(cityKey || "").trim();
  if (!key) return source;
  return source.filter(function (item) { return itemMatchesCityKey(item, key); });
}

function filterItemsByDateKey(items, dateKey) {
  var source = Array.isArray(items) ? items : [];
  var key = normalizeIsoDate(dateKey);
  if (!key) return source;
  return source.filter(function (item) { return itemMatchesDateKey(item, key); });
}

function filterItemsByActiveFilters(items, cityKey, dateKey) {
  return filterItemsByDateKey(filterItemsByCityKey(items, cityKey), dateKey);
}

module.exports = {
  addDateRangeKeys: addDateRangeKeys,
  dateFromKey: dateFromKey,
  dateKeysForFilter: dateKeysForFilter,
  filterItemsByActiveFilters: filterItemsByActiveFilters,
  filterItemsByCityKey: filterItemsByCityKey,
  filterItemsByDateKey: filterItemsByDateKey,
  itemMatchesCityKey: itemMatchesCityKey,
  keyFromDate: keyFromDate,
  normalizeIsoDate: normalizeIsoDate,
};
