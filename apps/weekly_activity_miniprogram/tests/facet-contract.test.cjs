const assert = require("node:assert/strict");
const test = require("node:test");

const { facetPayloadMatchesVisibleSet } = require("../services/facetContract");

const items = [
  { id: "event-a", city_key: "shanghai", event_date_start: "2026-07-19" },
  { id: "event-b", city_keys: ["shanghai", "beijing"], event_date_start: "2026-07-20" },
];
const generatedAt = "2026-07-19T08:00:00Z";

test("facet payload is accepted only for the same visible set generation", () => {
  const payload = {
    generated_at: generatedAt,
    scope: "current",
    item_count: 2,
    cities: [
      { city_key: "shanghai", item_count: 2 },
      { city_key: "beijing", item_count: 1 },
    ],
  };
  assert.equal(facetPayloadMatchesVisibleSet(payload, items, generatedAt, "cities"), true);
  assert.equal(facetPayloadMatchesVisibleSet({ ...payload, generated_at: "2026-07-18T08:00:00Z" }, items, generatedAt, "cities"), false);
  assert.equal(facetPayloadMatchesVisibleSet({ ...payload, item_count: 3 }, items, generatedAt, "cities"), false);
  assert.equal(facetPayloadMatchesVisibleSet({ ...payload, scope: "package" }, items, generatedAt, "cities"), false);
  assert.equal(facetPayloadMatchesVisibleSet({ ...payload, cities: null }, items, generatedAt, "cities"), false);
  assert.equal(facetPayloadMatchesVisibleSet({
    ...payload,
    cities: [{ city_key: "shanghai", item_count: 999 }, { city_key: "beijing", item_count: 1 }],
  }, items, generatedAt, "cities"), false);
  assert.equal(facetPayloadMatchesVisibleSet({
    ...payload,
    cities: [{ city_key: "shanghai", item_count: 2 }],
  }, items, generatedAt, "cities"), false);
});

test("missing generation never constrains local date facets", () => {
  const payload = {
    scope: "current",
    item_count: 2,
    dates: [
      { date: "2026-07-19", item_count: 1 },
      { date: "2026-07-20", item_count: 1 },
    ],
  };
  assert.equal(facetPayloadMatchesVisibleSet(payload, items, generatedAt, "dates"), false);
  assert.equal(facetPayloadMatchesVisibleSet({ ...payload, generated_at: generatedAt }, items, "", "dates"), false);
});

test("date facets reject forged or incomplete buckets even within the same generation", () => {
  const payload = {
    generated_at: generatedAt,
    scope: "current",
    item_count: 2,
    dates: [
      { date: "2026-07-19", item_count: 1 },
      { date: "2026-07-20", item_count: 999 },
    ],
  };
  assert.equal(facetPayloadMatchesVisibleSet(payload, items, generatedAt, "dates"), false);
});

test("exact generationId wins over generatedAt and mixed identity modes fail closed", () => {
  const current = { generationId: "sha256:current", generatedAt };
  const payload = {
    generationId: "sha256:current",
    generated_at: "2026-07-18T08:00:00Z",
    scope: "current",
    item_count: 2,
    cities: [
      { city_key: "shanghai", item_count: 2 },
      { city_key: "beijing", item_count: 1 },
    ],
  };
  assert.equal(facetPayloadMatchesVisibleSet(payload, items, current, "cities"), true);
  assert.equal(facetPayloadMatchesVisibleSet({ ...payload, generationId: "sha256:other" }, items, current, "cities"), false);
  assert.equal(facetPayloadMatchesVisibleSet({ ...payload, generationId: "" }, items, current, "cities"), false);
  assert.equal(facetPayloadMatchesVisibleSet(payload, items, generatedAt, "cities"), false);
});
