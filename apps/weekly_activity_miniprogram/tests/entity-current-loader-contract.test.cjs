const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const { fetchAllCurrentItems } = require("../utils/api");

for (const [pageName, lookbackDays] of [["artist", 45], ["venue", 31]]) {
  test(`${pageName} reuses the shared strict current paginator with lookback ${lookbackDays}`, () => {
    const source = fs.readFileSync(path.join(root, "pages", pageName, `${pageName}.js`), "utf8");
    assert.match(
      source,
      /const\s*\{[^}]*\brequestApi\b[^}]*\bfetchAllCurrentItems\b[^}]*\}\s*=\s*require\("\.\.\/\.\.\/utils\/api"\)/,
    );
    assert.doesNotMatch(source, /async function fetchAllCurrentItems\s*\(/);
    assert.match(source, new RegExp(`fetchAllCurrentItems\\(\\{\\s*lookbackDays:\\s*${lookbackDays}\\s*\\}\\)`));
  });
}

test("the shared paginator carries entity lookback windows across pages and keeps strict contracts", async () => {
  for (const lookbackDays of [45, 31]) {
    const calls = [];
    const items = await fetchAllCurrentItems({ lookbackDays, limit: 1 }, async (_path, query) => {
      calls.push(query);
      return {
        generatedAt: "2026-07-19T08:00:00Z",
        filters: { scope: "current" },
        items: [{ id: `event-${query.cursor}` }],
        page: { cursor: query.cursor, nextCursor: query.cursor === 0 ? 1 : null, total: 2 },
      };
    });
    assert.deepEqual(calls.map((query) => query.lookbackDays), [lookbackDays, lookbackDays]);
    assert.deepEqual(items.map((item) => item.id), ["event-0", "event-1"]);
  }

  await assert.rejects(
    fetchAllCurrentItems({ lookbackDays: 45, limit: 1 }, async (_path, query) => ({
      generatedAt: query.cursor === 0 ? "generation-a" : "generation-b",
      filters: { scope: "current" },
      items: [{ id: "duplicate-id" }],
      page: { cursor: query.cursor, nextCursor: query.cursor === 0 ? 1 : null, total: 2 },
    })),
    /CURRENT_GENERATION_DRIFT|CURRENT_EVENT_ID_DUPLICATE/,
  );

  await assert.rejects(
    fetchAllCurrentItems({ lookbackDays: 31 }, async () => ({
      generatedAt: "generation-a",
      filters: { scope: "current" },
      items: [{ id: "only-one" }],
      page: { cursor: 0, nextCursor: null, total: 2 },
    })),
    /CURRENT_TOTAL_MISMATCH/,
  );
});
