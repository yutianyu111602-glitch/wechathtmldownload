const assert = require("node:assert/strict");
const test = require("node:test");

global.wx = global.wx || {};
const api = require("../utils/api");

test("cached current page preserves the server cursor while filtering stale rows", () => {
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
  assert.equal(normalized.page.nextCursor, "100");
  assert.equal(normalized.page.total, 150);
});
