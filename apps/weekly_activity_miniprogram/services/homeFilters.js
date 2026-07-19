// services/homeFilters.js
// Extracted from pages/index/index.js: city/date filter primitives.
// Pure functions — no wx, no side effects.
// Date membership is owned by the portable dateVisibility contract used by
// CloudRun, CloudBase sync, static fallback and home filtering.
var _dateVisibility = require("../utils/dateVisibility");
var _businessDate = require("../utils/businessDate");
var itemMatchesDateKey = _dateVisibility.itemMatchesDateKey;
var itemMatchesDateWindow = _dateVisibility.itemMatchesDateWindow;

function normalizeIsoDate(value) {
  return _dateVisibility.isoDate(value);
}

function dateKeysForFilter(item) {
  return _dateVisibility.itemDateKeys(item);
}

function normalizeCityKey(value) {
  return String(value || "").trim().toLowerCase();
}

function cityKeysForItem(item) {
  var source = item || {};
  var values = [source.city_key, source.cityKey]
    .concat(Array.isArray(source.city_keys) ? source.city_keys : [])
    .concat(Array.isArray(source.cityKeys) ? source.cityKeys : []);
  var output = [];
  var seen = {};
  for (var i = 0; i < values.length; i++) {
    var key = normalizeCityKey(values[i]);
    if (!key || seen[key]) continue;
    seen[key] = true;
    output.push(key);
  }
  return output;
}

function itemMatchesCityKey(item, cityKey) {
  var key = normalizeCityKey(cityKey);
  if (!key) return true;
  return cityKeysForItem(item).indexOf(key) !== -1;
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

function filterItemsByDateWindow(items, startKey, endKey) {
  var source = Array.isArray(items) ? items : [];
  var start = normalizeIsoDate(startKey);
  var end = normalizeIsoDate(endKey);
  if (!start && !end) return source;
  var min = start || end;
  var max = end || start;
  if (max < min) return [];
  return source.filter(function (item) { return itemMatchesDateWindow(item, min, max); });
}

function allCurrentDateSelection() {
  return { mode: "all_current", exactDate: "", startKey: "", endKey: "" };
}

function exactDateSelection(dateKey) {
  var key = normalizeIsoDate(dateKey);
  return key
    ? { mode: "exact", exactDate: key, startKey: key, endKey: key }
    : allCurrentDateSelection();
}

function weekendDateSelection(offsetWeeks, now) {
  var weeks = Math.max(0, Number.parseInt(offsetWeeks || 0, 10) || 0);
  var range = _businessDate.currentShanghaiWeekendDateRange(now, weeks);
  return {
    mode: weeks === 0 ? "this_weekend" : "next_weekend",
    exactDate: "",
    startKey: range.dateFrom,
    endKey: range.dateTo,
  };
}

function normalizeDateSelection(value) {
  var input = value && typeof value === "object" ? value : {};
  var mode = String(input.mode || "all_current");
  if (mode === "exact") return exactDateSelection(input.exactDate || input.startKey);
  if (mode === "this_weekend" || mode === "next_weekend") {
    var start = normalizeIsoDate(input.startKey);
    var end = normalizeIsoDate(input.endKey);
    if (start && end) {
      return {
        mode: mode,
        exactDate: "",
        startKey: start <= end ? start : end,
        endKey: start <= end ? end : start,
      };
    }
  }
  return allCurrentDateSelection();
}

function dateSelectionQuery(value) {
  var selection = normalizeDateSelection(value);
  return {
    date: selection.mode === "exact" ? selection.exactDate : "",
    dateStart: selection.mode === "this_weekend" || selection.mode === "next_weekend" ? selection.startKey : "",
    dateEnd: selection.mode === "this_weekend" || selection.mode === "next_weekend" ? selection.endKey : "",
  };
}

function filterItemsByDateSelection(items, value) {
  var selection = normalizeDateSelection(value);
  if (selection.mode === "exact") return filterItemsByDateKey(items, selection.exactDate);
  if (selection.mode === "this_weekend" || selection.mode === "next_weekend") {
    return filterItemsByDateWindow(items, selection.startKey, selection.endKey);
  }
  return Array.isArray(items) ? items : [];
}

function filterItemsByActiveFilters(items, cityKey, dateKey) {
  return filterItemsByDateKey(filterItemsByCityKey(items, cityKey), dateKey);
}

module.exports = {
  allCurrentDateSelection: allCurrentDateSelection,
  cityKeysForItem: cityKeysForItem,
  dateSelectionQuery: dateSelectionQuery,
  dateKeysForFilter: dateKeysForFilter,
  exactDateSelection: exactDateSelection,
  filterItemsByActiveFilters: filterItemsByActiveFilters,
  filterItemsByCityKey: filterItemsByCityKey,
  filterItemsByDateKey: filterItemsByDateKey,
  filterItemsByDateSelection: filterItemsByDateSelection,
  filterItemsByDateWindow: filterItemsByDateWindow,
  itemMatchesCityKey: itemMatchesCityKey,
  normalizeDateSelection: normalizeDateSelection,
  normalizeIsoDate: normalizeIsoDate,
  weekendDateSelection: weekendDateSelection,
};
