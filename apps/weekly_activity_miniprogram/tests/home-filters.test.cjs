const assert = require("node:assert/strict");
const test = require("node:test");

const { filterItemsByCityKey, filterItemsByDateWindow } = require("../services/homeFilters");

test("default home date window keeps only events intersecting today through Sunday", () => {
  const items = [
    {
      id: "stale-0626",
      event_date_start: "2026-06-26",
      event_date_end: "2026-06-26",
    },
    {
      id: "saturday-before-today",
      event_date_start: "2026-07-04",
      event_date_end: "2026-07-04",
    },
    {
      id: "sunday-current",
      event_date_start: "2026-07-05",
      event_date_end: "2026-07-05",
    },
    {
      id: "weekend-range",
      event_date_start: "2026-07-04",
      event_date_end: "2026-07-05",
      event_date_iso_guesses: ["2026-07-04", "2026-07-05"],
      quality_flags: ["calendar_preview"],
    },
    {
      id: "next-week",
      event_date_start: "2026-07-06",
      event_date_end: "2026-07-06",
    },
  ];

  const filtered = filterItemsByDateWindow(items, "2026-07-05", "2026-07-05");

  assert.equal(filtered.map((item) => item.id).join(","), "sunday-current,weekend-range");
});

test("city filtering preserves poster-card camelCase city keys", () => {
  const posterCards = [
    { id: "shanghai-direct", cityKey: "shanghai", cityKeys: ["shanghai"] },
    { id: "shanghai-array", cityKey: "", cityKeys: ["shanghai"] },
    { id: "beijing", cityKey: "beijing", cityKeys: ["beijing"] },
  ];

  assert.deepEqual(
    filterItemsByCityKey(posterCards, "shanghai").map((item) => item.id),
    ["shanghai-direct", "shanghai-array"],
  );
});
