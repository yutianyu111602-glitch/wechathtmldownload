const assert = require("node:assert/strict");
const test = require("node:test");

const { cityKeysForItem, filterItemsByCityKey, filterItemsByDateWindow } = require("../services/homeFilters");

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

test("home date windows use the shared overlap contract for long explicit ranges", () => {
  const items = [{
    id: "long-running-series",
    event_date_start: "2026-01-01",
    event_date_end: "2026-12-31",
  }];

  assert.deepEqual(
    filterItemsByDateWindow(items, "2026-07-24", "2026-07-26").map((item) => item.id),
    ["long-running-series"],
  );
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

test("city key normalization preserves every snake/camel multi-city membership", () => {
  const item = {
    id: "multi-city",
    city_key: "kaifeng",
    cityKey: "legacy-primary",
    city_keys: ["kaifeng", "zhengzhou"],
    cityKeys: ["zhengzhou", "luoyang"],
  };

  assert.deepEqual(cityKeysForItem(item), ["kaifeng", "legacy-primary", "zhengzhou", "luoyang"]);
  assert.equal(filterItemsByCityKey([item], "zhengzhou").length, 1);
  assert.equal(filterItemsByCityKey([item], "luoyang").length, 1);
});
