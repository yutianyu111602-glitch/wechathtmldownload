"use strict";

// Portable weekly date-visibility contract. This file is intentionally
// dependency-free so the same implementation can ship inside CloudRun,
// the mini-program bundle, and the separately packaged CloudBase function.

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
const START_FIELDS = ["event_date_start", "eventDateStart", "dateLabel"];
const END_FIELDS = ["event_date_end", "eventDateEnd"];
const DIRECT_SINGLE_FIELDS = ["event_date_iso_guess", "eventDateIso", "event_date", "date"];
const PARSER_FIELDS = ["event_date_iso_guesses", "eventDateIsoGuesses", "event_date_text", "eventDateText"];
const MAX_EXPANDED_RANGE_DAYS = 64;

function isoDate(value) {
  const text = String(value || "").trim();
  const match = text.match(ISO_DATE_RE);
  if (!match) return "";
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year
    || date.getUTCMonth() !== month - 1
    || date.getUTCDate() !== day
  ) return "";
  return text;
}

function valuesForFields(item, fields) {
  const output = [];
  for (const field of fields) {
    const raw = item && item[field];
    const values = Array.isArray(raw) ? raw : [raw];
    for (const value of values) {
      const key = isoDate(value);
      if (key) output.push(key);
    }
  }
  return output;
}

function uniqueSorted(values) {
  return Array.from(new Set(values.filter(Boolean))).sort();
}

function itemHasExplicitRangeSignal(item) {
  const flags = []
    .concat(Array.isArray(item && item.quality_flags) ? item.quality_flags : [])
    .concat(Array.isArray(item && item.qualityFlags) ? item.qualityFlags : [])
    .map((value) => String(value || "").trim().toLowerCase());
  const contentType = String(item && (item.content_type || item.contentType) || "").trim().toLowerCase();
  return Boolean(
    item && (
      item.is_calendar_preview
      || item.isCalendarPreview
      || item.event_date_range_explicit
      || item.eventDateRangeExplicit
      || item.date_range_explicit
      || item.dateRangeExplicit
      || item.is_date_range
      || item.isDateRange
    )
  ) || contentType === "calendar_preview" || flags.includes("calendar_preview");
}

function expandedRangeKeys(start, end) {
  if (!start || !end || end < start) return [];
  const startMs = Date.parse(`${start}T00:00:00Z`);
  const endMs = Date.parse(`${end}T00:00:00Z`);
  const dayMs = 24 * 60 * 60 * 1000;
  const days = Math.round((endMs - startMs) / dayMs);
  if (!Number.isFinite(days) || days < 0 || days >= MAX_EXPANDED_RANGE_DAYS) {
    return uniqueSorted([start, end]);
  }
  const keys = [];
  for (let offset = 0; offset <= days; offset += 1) {
    keys.push(new Date(startMs + offset * dayMs).toISOString().slice(0, 10));
  }
  return keys;
}

function itemDateProfile(item = {}) {
  const start = valuesForFields(item, START_FIELDS)[0] || "";
  const end = valuesForFields(item, END_FIELDS)[0] || "";
  const primary = valuesForFields(item, DIRECT_SINGLE_FIELDS)[0] || "";
  const explicitKeys = uniqueSorted([start, end]);
  const directKeys = explicitKeys.length ? explicitKeys : uniqueSorted([primary]);
  const parserKeys = uniqueSorted(valuesForFields(item, PARSER_FIELDS));
  const keys = directKeys.length ? directKeys : parserKeys;
  const explicitRange = Boolean(start && end && start <= end);
  const signaledRange = itemHasExplicitRangeSignal(item) && keys.length >= 2;
  const isRange = explicitRange || signaledRange;
  const rangeStart = isRange ? (start || keys[0] || "") : "";
  const rangeEnd = isRange ? (end || keys[keys.length - 1] || rangeStart) : "";
  const visibleKeys = isRange
    ? uniqueSorted([...keys, ...expandedRangeKeys(rangeStart, rangeEnd)])
    : keys;
  return {
    keys: visibleKeys,
    directKeys,
    parserKeys: directKeys.length ? [] : parserKeys,
    start: rangeStart || keys[0] || "",
    end: rangeEnd || keys[keys.length - 1] || "",
    isRange: Boolean(isRange && rangeStart && rangeEnd && rangeStart <= rangeEnd),
    hasDate: visibleKeys.length > 0,
  };
}

function itemDateKeys(item) {
  return itemDateProfile(item).keys;
}

function itemMatchesDateKey(item, dateKey) {
  const target = isoDate(dateKey);
  if (!target) return true;
  const profile = itemDateProfile(item);
  if (profile.keys.includes(target)) return true;
  return Boolean(profile.isRange && profile.start <= target && target <= profile.end);
}

function normalizeDateWindow(dateStart, dateEnd) {
  const left = isoDate(dateStart);
  const right = isoDate(dateEnd);
  if (!left && !right) return { dateStart: "", dateEnd: "" };
  const start = left || right;
  const end = right || left;
  return start <= end
    ? { dateStart: start, dateEnd: end }
    : { dateStart: end, dateEnd: start };
}

function itemMatchesDateWindow(item, dateStart, dateEnd) {
  const window = normalizeDateWindow(dateStart, dateEnd);
  if (!window.dateStart) return true;
  const profile = itemDateProfile(item);
  if (!profile.hasDate) return false;
  if (profile.keys.some((key) => window.dateStart <= key && key <= window.dateEnd)) return true;
  return Boolean(profile.isRange && profile.start <= window.dateEnd && profile.end >= window.dateStart);
}

function itemIsCurrentOrFuture(item, today) {
  const target = isoDate(today);
  const profile = itemDateProfile(item);
  if (!profile.hasDate) return false;
  if (!target) return true;
  if (profile.isRange) return profile.end >= target;
  return profile.keys.some((key) => key >= target);
}

module.exports = {
  isoDate,
  itemDateKeys,
  itemDateProfile,
  itemHasExplicitRangeSignal,
  itemIsCurrentOrFuture,
  itemMatchesDateKey,
  itemMatchesDateWindow,
  normalizeDateWindow,
};
