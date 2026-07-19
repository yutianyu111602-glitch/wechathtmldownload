const assert = require("node:assert/strict");
const test = require("node:test");

global.wx = global.wx || {};
const api = require("../utils/api");

test("cached current page records filtered rows while preserving traversal metadata", () => {
  api.__setTodayForTests("2026-07-19");
  const payload = {
    items: [
      { id: "stale", event_date_start: "2026-07-18" },
      { id: "future", event_date_start: "2026-07-24" },
    ],
    page: { cursor: "0", limit: 100, nextCursor: "100", total: 150 },
  };
  const normalized = api.__normalizeStoredCurrentPayloadForTests(
    "/api/v1/weekly/current",
    { lookbackDays: 0, cursor: 0, limit: 100 },
    payload,
  );
  assert.deepEqual(normalized.items.map((item) => item.id), ["future"]);
  assert.equal(normalized.__storedFilteredItemCount, 1);
  assert.equal(normalized.page.nextCursor, "100");
  assert.equal(normalized.page.total, 150);
});

test("a fully expired cached page remains traversable and accounts for every removed row", () => {
  api.__setTodayForTests("2026-07-19");
  const normalized = api.__normalizeStoredCurrentPayloadForTests(
    "/api/v1/weekly/current",
    { cursor: 0, limit: 2 },
    {
      generatedAt: "2026-07-18T08:00:00Z",
      filters: { scope: "current" },
      items: [
        { id: "stale-a", event_date_start: "2026-07-17" },
        { id: "stale-b", event_date_start: "2026-07-18" },
      ],
      page: { cursor: 0, limit: 2, nextCursor: 2, total: 4 },
    },
  );

  assert.ok(normalized);
  assert.deepEqual(normalized.items, []);
  assert.equal(normalized.__storedFilteredItemCount, 2);
  assert.equal(normalized.page.nextCursor, 2);
});
