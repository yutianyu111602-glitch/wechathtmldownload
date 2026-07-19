const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const filters = require("../services/homeFilters");
const indexJs = fs.readFileSync(path.resolve(__dirname, "../pages/index/index.js"), "utf8");

test("upcoming weekend is represented as Friday through Sunday, never a scalar Friday", () => {
  const selection = filters.weekendDateSelection(0, new Date(2026, 6, 19, 13, 29));
  assert.deepEqual(selection, {
    mode: "this_weekend",
    exactDate: "",
    startKey: "2026-07-24",
    endKey: "2026-07-26",
  });
  assert.deepEqual(filters.dateSelectionQuery(selection), {
    date: "",
    dateStart: "2026-07-24",
    dateEnd: "2026-07-26",
  });
});

test("all dates means the complete current/future set and range filtering is inclusive", () => {
  const items = [
    { id: "expired", event_date_start: "2026-07-18", event_date_end: "2026-07-18" },
    { id: "friday", event_date_start: "2026-07-24", event_date_end: "2026-07-24" },
    { id: "saturday", event_date_start: "2026-07-25", event_date_end: "2026-07-25" },
    { id: "sunday", event_date_start: "2026-07-26", event_date_end: "2026-07-26" },
    { id: "later", event_date_start: "2026-07-31", event_date_end: "2026-07-31" },
  ];
  assert.equal(filters.filterItemsByDateSelection(items, filters.allCurrentDateSelection()).length, 5);
  assert.deepEqual(
    filters.filterItemsByDateSelection(items, filters.weekendDateSelection(0, new Date(2026, 6, 19))).map((item) => item.id),
    ["friday", "saturday", "sunday"],
  );
});

test("home page keeps date mode while changing city and derives posters from visible items", () => {
  const chooseCity = indexJs.slice(indexJs.indexOf("chooseDraftCity(event)"), indexJs.indexOf("resetDate()"));
  const applyLocation = indexJs.slice(indexJs.indexOf("applyLocation()"), indexJs.indexOf("applyLocalCityFilter()"));
  assert.ok(chooseCity);
  assert.ok(applyLocation);
  assert.doesNotMatch(chooseCity, /selectedDate:\s*""/);
  assert.doesNotMatch(applyLocation, /selectedDate:\s*""/);
  assert.match(indexJs, /dateStart:\s*dateQuery\.dateStart/);
  assert.match(indexJs, /dateEnd:\s*dateQuery\.dateEnd/);
  assert.match(indexJs, /posterPoolSourceItems\s*=\s*displayItems/);
  assert.doesNotMatch(indexJs, /applyDefaultHomeDateWindow/);
});
