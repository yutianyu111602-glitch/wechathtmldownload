const RANGE_ALL = "all";
const RANGE_WEEK = "week";
const RANGE_MONTH = "month";

function normalizeRange(value) {
  return [RANGE_ALL, RANGE_WEEK, RANGE_MONTH].includes(value) ? value : RANGE_ALL;
}

function localDateKey(date) {
  const value = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(value.getTime())) return "";
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, "0"),
    String(value.getDate()).padStart(2, "0"),
  ].join("-");
}

function itemDateKey(item) {
  if (!item || typeof item !== "object") return "";
  return itemDateKeys(item)[0] || "";
}

function isoDate(value) {
  const text = String(value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

function itemDateKeys(item) {
  if (!item || typeof item !== "object") return [];
  const directCandidates = [
    item.dateLabel,
    item.event_date_start,
    item.eventDateStart,
    item.event_date_iso_guess,
    item.eventDateIso,
    item.event_date,
    item.date,
    item.event_date_end,
    item.eventDateEnd,
  ];
  const directDates = directCandidates.map(isoDate).filter(Boolean);
  const candidates = directDates.length
    ? directCandidates
    : [
        ...directCandidates,
        ...(Array.isArray(item.event_date_iso_guesses) ? item.event_date_iso_guesses : []),
      ];
  const out = [];
  const seen = new Set();
  for (const value of candidates) {
    const text = isoDate(value);
    if (text && !seen.has(text)) {
      seen.add(text);
      out.push(text);
    }
  }
  return out;
}

function itemDateBounds(item) {
  const keys = itemDateKeys(item).sort();
  if (!keys.length) return null;
  const explicitEnd = isoDate(item?.event_date_end || item?.eventDateEnd);
  const start = isoDate(item?.event_date_start || item?.eventDateStart || item?.dateLabel) || keys[0];
  const end = explicitEnd || keys[keys.length - 1] || start;
  const flags = Array.isArray(item?.quality_flags) ? item.quality_flags : [];
  const isRange = Boolean(
    explicitEnd ||
    item?.isCalendarPreview ||
    item?.is_calendar_preview ||
    flags.includes("calendar_preview")
  );
  return { start, end: end >= start ? end : start, keys, isRange };
}

function previewRangeBounds(range, now = new Date()) {
  const key = normalizeRange(range);
  if (key === RANGE_ALL) return null;
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const end = new Date(start);
  if (key === RANGE_WEEK) {
    const day = start.getDay();
    const daysToSunday = day === 0 ? 0 : 7 - day;
    end.setDate(start.getDate() + daysToSunday);
  } else if (key === RANGE_MONTH) {
    end.setMonth(start.getMonth() + 1, 0);
  }
  return { start: localDateKey(start), end: localDateKey(end) };
}

function itemMatchesPreviewRange(item, range, now = new Date()) {
  const bounds = previewRangeBounds(range, now);
  if (!bounds) return true;
  const itemBounds = itemDateBounds(item);
  if (!itemBounds) return false;
  if (itemBounds.keys.some((key) => key >= bounds.start && key <= bounds.end)) return true;
  return itemBounds.isRange && itemBounds.start <= bounds.end && itemBounds.end >= bounds.start;
}

function itemMatchesDateKey(item, dateKey) {
  const key = isoDate(dateKey);
  if (!key) return false;
  const itemBounds = itemDateBounds(item);
  if (!itemBounds) return false;
  return itemBounds.keys.includes(key) || (itemBounds.isRange && itemBounds.start <= key && itemBounds.end >= key);
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
