const RANGE_ALL = "all";
const RANGE_WEEK = "week";
const RANGE_MONTH = "month";
const dateVisibility = require("./dateVisibility");
const {
  itemDateKeys,
  itemDateProfile,
  itemMatchesDateKey,
} = dateVisibility;
const {
  addDaysToDateKey,
  currentShanghaiBusinessDateKey,
} = require("./businessDate");

function normalizeRange(value) {
  return [RANGE_ALL, RANGE_WEEK, RANGE_MONTH].includes(value) ? value : RANGE_ALL;
}

function localDateKey(date) {
  // Historical export name retained for compatibility. Product previews are
  // anchored to Shanghai calendar time, never the device's local timezone.
  return currentShanghaiBusinessDateKey(date, 0);
}

function itemDateKey(item) {
  if (!item || typeof item !== "object") return "";
  return itemDateKeys(item)[0] || "";
}

function itemDateBounds(item) {
  const profile = itemDateProfile(item);
  return profile.hasDate
    ? { start: profile.start, end: profile.end, keys: profile.keys, isRange: profile.isRange }
    : null;
}

function previewRangeBounds(range, now = new Date()) {
  const key = normalizeRange(range);
  if (key === RANGE_ALL) return null;
  const start = currentShanghaiBusinessDateKey(now, 0);
  if (!start) return null;
  let end = start;
  if (key === RANGE_WEEK) {
    const day = new Date(`${start}T00:00:00Z`).getUTCDay();
    const daysToSunday = day === 0 ? 0 : 7 - day;
    end = addDaysToDateKey(start, daysToSunday);
  } else if (key === RANGE_MONTH) {
    const match = start.match(/^(\d{4})-(\d{2})-/);
    const monthEnd = match
      ? new Date(Date.UTC(Number(match[1]), Number(match[2]), 0))
      : null;
    end = monthEnd ? monthEnd.toISOString().slice(0, 10) : start;
  }
  return { start, end };
}

function itemMatchesPreviewRange(item, range, now = new Date()) {
  const bounds = previewRangeBounds(range, now);
  if (!bounds) return true;
  const itemBounds = itemDateBounds(item);
  if (!itemBounds) return false;
  if (itemBounds.keys.some((key) => key >= bounds.start && key <= bounds.end)) return true;
  return itemBounds.isRange && itemBounds.start <= bounds.end && itemBounds.end >= bounds.start;
}

function filterItemsByPreviewRange(items, range, now = new Date()) {
  const source = Array.isArray(items) ? items : [];
  if (normalizeRange(range) === RANGE_ALL) return source;
  return source.filter((item) => itemMatchesPreviewRange(item, range, now));
}

module.exports = {
  RANGE_ALL,
  RANGE_MONTH,
  RANGE_WEEK,
  filterItemsByPreviewRange,
  itemDateBounds,
  itemDateKey,
  itemDateKeys,
  itemMatchesDateKey,
  itemMatchesPreviewRange,
  localDateKey,
  normalizeRange,
  previewRangeBounds,
};
