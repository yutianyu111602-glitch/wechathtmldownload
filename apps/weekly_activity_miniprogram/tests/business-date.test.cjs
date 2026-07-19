const assert = require("node:assert/strict");
const test = require("node:test");

const {
  addDaysToDateKey,
  currentShanghaiBusinessDateKey,
  currentShanghaiWeekendDateRange,
  weekendDateRangeFromDateKey,
} = require("../utils/businessDate");

test("Shanghai business date keeps the previous club night before 07:00", () => {
  assert.equal(
    currentShanghaiBusinessDateKey(new Date("2026-07-19T18:30:00.000Z")),
    "2026-07-19",
  );
});

test("Shanghai business date advances to the calendar date after 07:00", () => {
  assert.equal(
    currentShanghaiBusinessDateKey(new Date("2026-07-20T02:00:00.000Z")),
    "2026-07-20",
  );
});

test("date-key arithmetic is timezone-free across month boundaries", () => {
  assert.equal(addDaysToDateKey("2026-07-31", 1), "2026-08-01");
  assert.equal(addDaysToDateKey("not-a-date", 1), "");
});

test("weekend range is the Friday through Sunday of the reference business week", () => {
  assert.deepEqual(weekendDateRangeFromDateKey("2026-07-19"), {
    dateFrom: "2026-07-17",
    dateTo: "2026-07-19",
  });
  assert.deepEqual(weekendDateRangeFromDateKey("2026-07-19", 1), {
    dateFrom: "2026-07-24",
    dateTo: "2026-07-26",
  });
});

test("current Shanghai weekend range stays on Sunday before the Monday cutoff", () => {
  assert.deepEqual(currentShanghaiWeekendDateRange(new Date("2026-07-19T18:00:00.000Z")), {
    dateFrom: "2026-07-17",
    dateTo: "2026-07-19",
  });
});
