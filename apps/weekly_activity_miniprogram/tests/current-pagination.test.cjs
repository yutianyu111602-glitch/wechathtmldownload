const assert = require("node:assert/strict");
const test = require("node:test");

global.getApp = () => ({ globalData: { cloud: {} } });
const { fetchAllCurrentItems } = require("../utils/api");

test("fetchAllCurrentItems follows every cursor and deduplicates page overlap", async () => {
  const calls = [];
  const items = await fetchAllCurrentItems({ limit: 100, scope: "current" }, async (path, query) => {
    calls.push({ path, query });
    if (query.cursor === 0) {
      return {
        items: Array.from({ length: 100 }, (_, index) => ({ id: `event-${index}` })),
        page: { nextCursor: "100", total: 151 },
      };
    }
    return {
      items: Array.from({ length: 52 }, (_, index) => ({ id: `event-${99 + index}` })),
      page: { nextCursor: null, total: 151 },
    };
  });

  assert.deepEqual(calls.map((call) => call.query.cursor), [0, 100]);
  assert.ok(calls.every((call) => call.query.scope === "current"));
  assert.equal(items.length, 151);
  assert.equal(new Set(items.map((item) => item.id)).size, 151);
});

test("fetchAllCurrentItems fails closed on a repeated cursor", async () => {
  await assert.rejects(
    fetchAllCurrentItems({}, async () => ({ items: [], page: { nextCursor: "0" } })),
    /INVALID_CURRENT_CURSOR/,
  );
});
