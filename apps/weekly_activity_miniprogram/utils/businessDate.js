const SHANGHAI_UTC_OFFSET_MS = 8 * 60 * 60 * 1000;
const DEFAULT_LATE_NIGHT_CUTOFF_HOUR = 7;

function dateKeyFromShiftedUtc(value) {
  return [
    value.getUTCFullYear(),
    String(value.getUTCMonth() + 1).padStart(2, "0"),
    String(value.getUTCDate()).padStart(2, "0"),
  ].join("-");
}

function currentShanghaiBusinessDateKey(now = new Date(), cutoffHour = DEFAULT_LATE_NIGHT_CUTOFF_HOUR) {
  const value = now instanceof Date ? new Date(now.getTime()) : new Date(now);
  if (Number.isNaN(value.getTime())) return "";
  const cutoff = Math.max(0, Math.min(12, Number.parseInt(cutoffHour, 10) || 0));
  const shanghai = new Date(value.getTime() + SHANGHAI_UTC_OFFSET_MS);
  if (cutoff > 0 && shanghai.getUTCHours() < cutoff) shanghai.setUTCDate(shanghai.getUTCDate() - 1);
  return dateKeyFromShiftedUtc(shanghai);
}

function utcDateFromDateKey(dateKey) {
  const text = String(dateKey || "").trim();
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const value = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return dateKeyFromShiftedUtc(value) === text ? value : null;
}

function addDaysToDateKey(dateKey, days) {
  const value = utcDateFromDateKey(dateKey);
  if (!value) return "";
  const offset = Number.parseInt(days, 10);
  value.setUTCDate(value.getUTCDate() + (Number.isFinite(offset) ? offset : 0));
  return dateKeyFromShiftedUtc(value);
}

function weekendDateRangeFromDateKey(referenceDateKey, offsetWeeks = 0) {
  const base = utcDateFromDateKey(referenceDateKey);
  if (!base) return { dateFrom: "", dateTo: "" };
  const parsedWeeks = Number.parseInt(offsetWeeks, 10);
  const weeks = Math.max(0, Number.isFinite(parsedWeeks) ? parsedWeeks : 0);
  const daysSinceMonday = (base.getUTCDay() + 6) % 7;
  const friday = new Date(base.getTime());
  friday.setUTCDate(base.getUTCDate() - daysSinceMonday + 4 + weeks * 7);
  const dateFrom = dateKeyFromShiftedUtc(friday);
  return { dateFrom, dateTo: addDaysToDateKey(dateFrom, 2) };
}

function currentShanghaiWeekendDateRange(now = new Date(), offsetWeeks = 0, cutoffHour = DEFAULT_LATE_NIGHT_CUTOFF_HOUR) {
  return weekendDateRangeFromDateKey(currentShanghaiBusinessDateKey(now, cutoffHour), offsetWeeks);
}

module.exports = {
  DEFAULT_LATE_NIGHT_CUTOFF_HOUR,
  addDaysToDateKey,
  currentShanghaiBusinessDateKey,
  currentShanghaiWeekendDateRange,
  weekendDateRangeFromDateKey,
};
