const assert = require("node:assert/strict");
const test = require("node:test");

global.wx = global.wx || {};
const api = require("../utils/api");

const payload = {
  generated_at: "2026-07-19T08:00:00Z",
  generation_id: "sha256:static-generation",
  items: [
    { id: "past", city_key: "shanghai", event_date_start: "2026-07-10", quality_status: "READY", title: "past techno" },
    { id: "today", city_key: "shanghai", event_date_start: "2026-07-19", quality_status: "READY", title: "today techno" },
    { id: "camel-multi-city", cityKeys: ["beijing", "shanghai"], event_date_start: "2026-07-20", quality_status: "READY", title: "future techno" },
    { id: "range", city_key: "hangzhou", event_date_start: "2026-07-18", event_date_end: "2026-07-21", quality_status: "READY", title: "range techno" },
    { id: "draft", city_key: "shanghai", event_date_start: "2026-07-20", quality_status: "DRAFT", title: "draft techno" },
  ],
};

function ids(query) {
  return api.__currentResponseFromStaticForTests(payload, { limit: 100, ...query }).items.map((item) => item.id);
}

test.beforeEach(() => api.__setTodayForTests("2026-07-19"));

test("static projection matches current and package scope semantics", () => {
  assert.deepEqual(ids({ scope: "current" }), ["range", "today", "camel-multi-city"]);
  assert.deepEqual(ids({ scope: "package" }), ["past", "range", "today", "camel-multi-city"]);
});

test("static projection honors exact date, date window, and lookback", () => {
  assert.deepEqual(ids({ scope: "current", date: "2026-07-18" }), ["range"]);
  assert.deepEqual(ids({ scope: "current", dateStart: "2026-07-20", dateEnd: "2026-07-21" }), ["range", "camel-multi-city"]);
  assert.deepEqual(ids({ scope: "current", lookbackDays: 9 }), ["past", "range", "today", "camel-multi-city"]);
});

test("static projection honors snake and camel multi-city fields and echoes scope", () => {
  const response = api.__currentResponseFromStaticForTests(payload, {
    scope: "current",
    cityKey: "shanghai",
    limit: 1,
    cursor: 1,
  });
  assert.equal(response.filters.scope, "current");
  assert.equal(response.generationId, "sha256:static-generation");
  assert.equal(response.page.total, 2);
  assert.deepEqual(response.items.map((item) => item.id), ["camel-multi-city"]);
});

test("static projection keeps sparse parser dates discrete and excludes undated current rows", () => {
  const source = {
    generated_at: "2026-07-19T08:00:00Z",
    generation_id: "sha256:facet-generation",
    items: [
      {
        id: "sparse-parser-dates",
        event_date_iso_guesses: ["2026-07-24", "2026-07-31"],
        quality_status: "READY",
        title: "sparse techno",
      },
      {
        id: "explicit-range-with-parser-noise",
        event_date_start: "2026-07-24",
        event_date_end: "2026-07-26",
        event_date_iso_guess: "2026-07-24",
        event_date_iso_guesses: ["2026-07-24", "2026-07-31"],
        quality_status: "READY",
        title: "range techno",
      },
      {
        id: "undated-ready",
        quality_status: "READY",
        title: "undated techno",
      },
    ],
  };
  const project = (query) => api.__currentResponseFromStaticForTests(source, { limit: 100, ...query }).items.map((item) => item.id);

  assert.deepEqual(project({ date: "2026-07-27" }), []);
  assert.deepEqual(project({ date: "2026-07-25" }), ["explicit-range-with-parser-noise"]);
  assert.deepEqual(project({ date: "2026-07-31" }), ["sparse-parser-dates"]);
  assert.equal(project({ scope: "current" }).includes("undated-ready"), false);
  assert.equal(project({ scope: "package" }).includes("undated-ready"), true);
});

test("static current, city and date facets derive from the same visible projection", () => {
  const source = {
    generated_at: "2026-07-19T08:00:00Z",
    generation_id: "sha256:facet-generation",
    items: [
      {
        id: "sparse-shanghai",
        city_key: "shanghai",
        city: ["上海"],
        event_date_iso_guesses: ["2026-07-24", "2026-07-31"],
        quality_status: "READY",
        title: "sparse techno",
      },
      {
        id: "range-beijing",
        city_key: "beijing",
        city: ["北京"],
        event_date_start: "2026-07-24",
        event_date_end: "2026-07-26",
        event_date_iso_guesses: ["2026-07-24", "2026-07-31"],
        quality_status: "READY",
        title: "range techno",
      },
      {
        id: "undated-shanghai",
        city_key: "shanghai",
        city: ["上海"],
        quality_status: "READY",
        title: "undated techno",
      },
    ],
  };

  const current = api.__currentResponseFromStaticForTests(source, { scope: "current", limit: 100 });
  const cities = api.__cityIndexFromStaticForTests(source, { scope: "current" });
  const dates = api.__dateIndexFromStaticForTests(source, { scope: "current" });
  const packageCities = api.__cityIndexFromStaticForTests(source, { scope: "package" });

  assert.equal(current.page.total, 2);
  assert.equal(current.generationId, "sha256:facet-generation");
  assert.equal(cities.generationId, current.generationId);
  assert.equal(dates.generationId, current.generationId);
  assert.equal(cities.item_count, current.page.total);
  assert.equal(cities.scope, "current");
  assert.deepEqual(cities.cities.map((entry) => [entry.city_key, entry.item_count]), [["beijing", 1], ["shanghai", 1]]);
  assert.equal(dates.item_count, current.page.total);
  assert.equal(dates.scope, "current");
  assert.equal(dates.dates.some((entry) => entry.date === "2026-07-27"), false);
  assert.equal(dates.dates.some((entry) => entry.date === "2026-07-31"), true);
  assert.equal(packageCities.item_count, 3);
  assert.deepEqual(packageCities.cities.map((entry) => [entry.city_key, entry.item_count]), [["shanghai", 2], ["beijing", 1]]);
});
