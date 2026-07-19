const assert = require("node:assert/strict");
const test = require("node:test");

const {
  filterItemsByPreviewRange,
  itemMatchesDateKey,
  itemMatchesPreviewRange,
  previewRangeBounds,
} = require("../utils/datePreview");

const now = new Date(2026, 4, 28);

test("preview range bounds cover upcoming week and month", () => {
  assert.deepEqual(previewRangeBounds("week", now), { start: "2026-05-28", end: "2026-05-31" });
  assert.deepEqual(previewRangeBounds("month", now), { start: "2026-05-28", end: "2026-05-31" });
});

test("preview filters keep this week and this month distinct at month boundary", () => {
  const source = [
    { id: "thu", dateLabel: "2026-05-28" },
    { id: "sun", dateLabel: "2026-05-31" },
    { id: "next-month", dateLabel: "2026-06-01" },
    { id: "unknown", dateLabel: "" },
  ];

  assert.deepEqual(filterItemsByPreviewRange(source, "week", now).map((item) => item.id), ["thu", "sun"]);
  assert.deepEqual(filterItemsByPreviewRange(source, "month", now).map((item) => item.id), ["thu", "sun"]);
  assert.deepEqual(filterItemsByPreviewRange(source, "all", now).map((item) => item.id), ["thu", "sun", "next-month", "unknown"]);
});

test("preview range reads backend date aliases before projection", () => {
  assert.equal(itemMatchesPreviewRange({ event_date_iso_guess: "2026-05-30" }, "week", now), true);
  assert.equal(itemMatchesPreviewRange({ event_date_iso_guesses: ["2026-06-06"] }, "week", now), false);
});

test("preview range keeps calendar overview items that overlap the selected window", () => {
  const source = [
    { id: "range-overlap", event_date_start: "2026-05-20", event_date_end: "2026-05-30" },
    { id: "range-after", event_date_start: "2026-06-01", event_date_end: "2026-06-07" },
  ];

  assert.equal(itemMatchesPreviewRange(source[0], "week", now), true);
  assert.deepEqual(filterItemsByPreviewRange(source, "week", now).map((item) => item.id), ["range-overlap"]);
});

test("preview range does not turn non-contiguous date guesses into a fake range", () => {
  const item = {
    id: "two-shows",
    event_date_iso_guesses: ["2026-05-20", "2026-06-10"],
  };

  assert.equal(itemMatchesPreviewRange(item, "week", now), false);
});

test("explicit single-day event date ignores extra parser guesses", () => {
  const item = {
    id: "calendar-derived-single",
    event_date_start: "2026-06-05",
    event_date_end: "2026-06-05",
    event_date_iso_guess: "2026-06-05",
    event_date_iso_guesses: ["2026-06-05", "2026-06-12", "2026-06-13"],
  };

  assert.equal(itemMatchesDateKey(item, "2026-06-05"), true);
  assert.equal(itemMatchesDateKey(item, "2026-06-12"), false);
});
