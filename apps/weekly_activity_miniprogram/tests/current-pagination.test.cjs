const assert = require("node:assert/strict");
const test = require("node:test");

global.getApp = () => ({ globalData: { cloud: {} } });
const { fetchAllCurrentItems, fetchAllCurrentResponse } = require("../utils/api");

const TEST_GENERATED_AT = "2026-07-19T08:00:00Z";

function currentPage(payload = {}) {
  return {
    generatedAt: TEST_GENERATED_AT,
    filters: { scope: "current" },
    ...payload,
  };
}

test("fetchAllCurrentItems follows every cursor without overlap", async () => {
  const calls = [];
  const items = await fetchAllCurrentItems({ limit: 100, scope: "current" }, async (path, query) => {
    calls.push({ path, query });
    if (query.cursor === 0) {
      return currentPage({
        items: Array.from({ length: 100 }, (_, index) => ({ id: `event-${index}` })),
        page: { nextCursor: "100", total: 151 },
      });
    }
    return currentPage({
      items: Array.from({ length: 51 }, (_, index) => ({ id: `event-${100 + index}` })),
      page: { nextCursor: null, total: 151 },
    });
  });

  assert.deepEqual(calls.map((call) => call.query.cursor), [0, 100]);
  assert.ok(calls.every((call) => call.query.scope === "current"));
  assert.equal(items.length, 151);
  assert.equal(new Set(items.map((item) => item.id)).size, 151);
});

test("fetchAllCurrentItems fails closed when pages overlap on a stable event id", async () => {
  await assert.rejects(
    fetchAllCurrentItems({}, async (_path, query) => query.cursor === 0
      ? currentPage({
          items: [{ id: "event-0" }],
          page: { nextCursor: "1", total: 2 },
        })
      : currentPage({
          items: [{ id: "event-0" }],
          page: { nextCursor: null, total: 2 },
        })),
    /CURRENT_EVENT_ID_DUPLICATE:event-0/,
  );
});

test("fetchAllCurrentItems fails closed when an item has no stable event id", async () => {
  await assert.rejects(
    fetchAllCurrentItems({}, async () => currentPage({
      items: [{ title: "missing id" }],
      page: { nextCursor: null, total: 1 },
    })),
    /CURRENT_EVENT_ID_MISSING/,
  );
});

test("fetchAllCurrentItems fails closed on a repeated cursor", async () => {
  await assert.rejects(
    fetchAllCurrentItems({}, async () => ({ items: [], page: { nextCursor: "0" } })),
    /INVALID_CURRENT_CURSOR/,
  );
});

test("fetchAllCurrentItems fails closed on a malformed cursor", async () => {
  await assert.rejects(
    fetchAllCurrentItems({}, async () => ({
      items: [{ id: "event-0" }],
      page: { nextCursor: "bad", total: 2 },
    })),
    /INVALID_CURRENT_CURSOR/,
  );
});

test("fetchAllCurrentItems fails closed when a page declares the wrong cursor", async () => {
  await assert.rejects(
    fetchAllCurrentItems({}, async () => ({
      items: [{ id: "event-0" }],
      page: { cursor: "99", nextCursor: null, total: 1 },
    })),
    /CURRENT_PAGE_CURSOR_MISMATCH/,
  );
});

test("fetchAllCurrentItems fails closed when the page safety limit is reached before termination", async () => {
  await assert.rejects(
    fetchAllCurrentItems({ __maxPages: 2 }, async (_path, query) => currentPage({
      items: [{ id: `event-${query.cursor}` }],
      page: { nextCursor: String(Number(query.cursor) + 1), total: 3 },
    })),
    /CURRENT_PAGE_LIMIT_EXCEEDED/,
  );
});

test("fetchAllCurrentItems fails closed when terminal unique items do not match total", async () => {
  await assert.rejects(
    fetchAllCurrentItems({}, async () => currentPage({
      items: [{ id: "event-0" }],
      page: { nextCursor: null, total: 2 },
    })),
    /CURRENT_TOTAL_MISMATCH/,
  );
});

test("fetchAllCurrentResponse preserves release metadata and page progress", async () => {
  const progress = [];
  const response = await fetchAllCurrentResponse({ limit: 100 }, async (_path, query) => ({
    generatedAt: "2026-07-19T08:00:00Z",
    filters: { scope: "current" },
    __fromCache: query.cursor === 0,
    items: [{ id: `event-${query.cursor}` }],
    page: { nextCursor: query.cursor === 0 ? "1" : null, total: 2 },
  }), (state) => progress.push(state.loaded));

  assert.deepEqual(response.items.map((item) => item.id), ["event-0", "event-1"]);
  assert.equal(response.total, 2);
  assert.equal(response.generatedAt, "2026-07-19T08:00:00Z");
  assert.equal(response.fromCache, true);
  assert.deepEqual(progress, [1, 2]);
});

test("fetchAllCurrentResponse uses exact generationId across pages even when timestamps differ", async () => {
  const response = await fetchAllCurrentResponse({ limit: 1 }, async (_path, query) => currentPage({
    generationId: "sha256:exact-generation",
    generatedAt: query.cursor === 0 ? "2026-07-19T08:00:00Z" : "2026-07-19T09:00:00Z",
    items: [{ id: `event-${query.cursor}` }],
    page: { cursor: query.cursor, nextCursor: query.cursor === 0 ? 1 : null, total: 2 },
  }));

  assert.equal(response.generationId, "sha256:exact-generation");
  assert.deepEqual(response.items.map((item) => item.id), ["event-0", "event-1"]);
});

test("fetchAllCurrentResponse fails closed when exact generationId drifts or disappears", async () => {
  await assert.rejects(
    fetchAllCurrentResponse({ limit: 1 }, async (_path, query) => currentPage({
      generationId: query.cursor === 0 ? "sha256:generation-a" : "sha256:generation-b",
      items: [{ id: `event-${query.cursor}` }],
      page: { cursor: query.cursor, nextCursor: query.cursor === 0 ? 1 : null, total: 2 },
    })),
    /CURRENT_GENERATION_ID_DRIFT/,
  );
  await assert.rejects(
    fetchAllCurrentResponse({ limit: 1 }, async (_path, query) => currentPage({
      generationId: query.cursor === 0 ? "sha256:generation-a" : "",
      items: [{ id: `event-${query.cursor}` }],
      page: { cursor: query.cursor, nextCursor: query.cursor === 0 ? 1 : null, total: 2 },
    })),
    /CURRENT_GENERATION_ID_MISSING/,
  );
});

test("fetchAllCurrentResponse reconciles stale rows removed from cached pages", async () => {
  const response = await fetchAllCurrentResponse({ limit: 2 }, async (_path, query) => query.cursor === 0
    ? currentPage({
        __fromCache: true,
        __storedFilteredItemCount: 1,
        items: [{ id: "future-a", event_date_start: "2026-07-19" }],
        page: { cursor: 0, nextCursor: 2, total: 3 },
      })
    : currentPage({
        __fromCache: true,
        __storedFilteredItemCount: 0,
        items: [{ id: "future-b", event_date_start: "2026-07-20" }],
        page: { cursor: 2, nextCursor: null, total: 3 },
      }));

  assert.deepEqual(response.items.map((item) => item.id), ["future-a", "future-b"]);
  assert.equal(response.total, 2);
  assert.equal(response.filteredStoredItemCount, 1);
});

test("fetchAllCurrentResponse traverses a fully expired cached page", async () => {
  const response = await fetchAllCurrentResponse({ limit: 2 }, async (_path, query) => {
    if (query.cursor === 0) return currentPage({
      __fromCache: true,
      __storedFilteredItemCount: 2,
      items: [],
      page: { cursor: 0, nextCursor: 2, total: 4 },
    });
    return currentPage({
      __fromCache: true,
      __storedFilteredItemCount: 0,
      items: [{ id: "future-a" }, { id: "future-b" }],
      page: { cursor: 2, nextCursor: null, total: 4 },
    });
  });

  assert.deepEqual(response.items.map((item) => item.id), ["future-a", "future-b"]);
  assert.equal(response.total, 2);
  assert.equal(response.filteredStoredItemCount, 2);
});

test("fetchAllCurrentResponse rejects cached and static pages from different generations", async () => {
  await assert.rejects(
    fetchAllCurrentResponse({ limit: 1 }, async (_path, query) => query.cursor === 0
      ? currentPage({
          generatedAt: "2026-07-18T08:00:00Z",
          __fromCache: true,
          items: [{ id: "cached" }],
          page: { cursor: 0, nextCursor: 1, total: 2 },
        })
      : currentPage({
          generatedAt: "2026-07-19T08:00:00Z",
          items: [{ id: "static" }],
          page: { cursor: 1, nextCursor: null, total: 2 },
        })),
    /CURRENT_GENERATION_DRIFT/,
  );
});

test("fetchAllCurrentItems fails closed when generatedAt is missing", async () => {
  await assert.rejects(
    fetchAllCurrentItems({}, async () => ({
      filters: { scope: "current" },
      items: [],
      page: { nextCursor: null, total: 0 },
    })),
    /CURRENT_GENERATION_MISSING/,
  );
});

test("fetchAllCurrentItems fails closed when response scope is missing or differs from request", async () => {
  await assert.rejects(
    fetchAllCurrentItems({}, async () => ({
      generatedAt: TEST_GENERATED_AT,
      items: [],
      page: { nextCursor: null, total: 0 },
    })),
    /CURRENT_SCOPE_MISSING/,
  );
  await assert.rejects(
    fetchAllCurrentItems({ scope: "current" }, async () => currentPage({
      filters: { scope: "package" },
      items: [],
      page: { nextCursor: null, total: 0 },
    })),
    /CURRENT_SCOPE_MISMATCH:package!=current/,
  );
});
