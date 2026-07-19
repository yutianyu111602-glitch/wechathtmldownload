const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadWeeklyDataSyncModule(database = null) {
  const filename = path.resolve(__dirname, "../cloudfunctions/weeklyDataSync/index.js");
  const code = fs.readFileSync(filename, "utf8");
  const module = { exports: {} };
  const fakeDb = database || {
    command: {},
    collection() {
      return {
        doc() {
          return {
            get: async () => ({ data: [] }),
            set: async () => ({ ok: true }),
          };
        },
        where() {
          return this;
        },
        limit() {
          return this;
        },
        get: async () => ({ data: [] }),
      };
    },
  };
  const sandbox = {
    module,
    exports: module.exports,
    console,
    process: { env: {} },
    require(name) {
      if (name === "@cloudbase/node-sdk") {
        return {
          init() {
            return {
              database() {
                return fakeDb;
              },
            };
          },
        };
      }
      return require(name);
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  return sandbox.module.exports;
}

test("weeklyDataSync hot read matches inclusive date ranges", () => {
  const mod = loadWeeklyDataSyncModule();
  const response = mod.__test.currentResponseFromItems({
    generatedAt: "2026-06-01T00:00:00Z",
    items: [
      {
        id: "range-event",
        city_key: "shanghai",
        event_date_start: "2026-06-01",
        event_date_end: "2026-06-03",
        quality_status: "READY",
      },
      {
        id: "other-event",
        city_key: "shanghai",
        event_date_start: "2026-06-04",
        quality_status: "READY",
      },
    ],
  }, { date: "2026-06-02", limit: 100 });

  assert.deepEqual(Array.from(response.items, (item) => item.id), ["range-event"]);
});

test("weeklyDataSync default hot current excludes stable past items", () => {
  const mod = loadWeeklyDataSyncModule();
  const response = mod.__test.currentResponseFromItems({
    generatedAt: "2026-06-01T00:00:00Z",
    items: [
      {
        id: "past-event",
        city_key: "shanghai",
        event_date_start: "2000-01-01",
        event_date_end: "2000-01-01",
        quality_status: "READY",
      },
      {
        id: "future-event",
        city_key: "shanghai",
        event_date_start: "2999-01-01",
        event_date_end: "2999-01-01",
        quality_status: "READY",
      },
    ],
  }, { limit: 100 });

  assert.equal(response.filters.lookbackDays, 0);
  assert.deepEqual(Array.from(response.items, (item) => item.id), ["future-event"]);
});

test("weeklyDataSync sync action is locked to the current-only visibility scope", () => {
  const mod = loadWeeklyDataSyncModule();

  assert.equal(mod.__test.syncLookbackDaysFromEvent({}), 0);
  assert.equal(mod.__test.syncLookbackDaysFromEvent({ lookbackDays: 45 }), 0);
  assert.equal(
    mod.__test.buildCurrentFetchPath("100", { lookbackDays: 45 }),
    "/api/v1/weekly/current?scope=current&limit=100&lookbackDays=0&cursor=100",
  );
});

test("weeklyDataSync pagination accepts one coherent generation and exact total", async () => {
  const mod = loadWeeklyDataSyncModule();
  mod.__test.setTestRequestJson(async (requestPath) => {
    const cursor = new URL(`https://unit.test${requestPath}`).searchParams.get("cursor");
    if (cursor === "0") {
      return {
        schemaVersion: "weekly_activity_api.current_response.v1",
        generatedAt: "2026-07-19T08:00:00Z",
        filters: { scope: "current" },
        page: { cursor: "0", nextCursor: "1", total: 2 },
        items: [{ id: "event-a" }],
      };
    }
    return {
      schemaVersion: "weekly_activity_api.current_response.v1",
      generatedAt: "2026-07-19T08:00:00Z",
      filters: { scope: "current" },
      page: { cursor: "1", nextCursor: null, total: 2 },
      items: [{ id: "event-b" }],
    };
  });
  const result = await mod.__test.fetchAllCurrent();
  assert.deepEqual(Array.from(result.items, (item) => item.id), ["event-a", "event-b"]);
  assert.equal(result.page.total, 2);
});

test("weeklyDataSync pagination rejects cursor loops, duplicate ids, drift, and truncated totals", async (t) => {
  async function expectRejected(payloads, pattern) {
    const mod = loadWeeklyDataSyncModule();
    let index = 0;
    mod.__test.setTestRequestJson(async () => payloads[Math.min(index++, payloads.length - 1)]);
    await assert.rejects(() => mod.__test.fetchAllCurrent(), pattern);
  }
  const base = {
    schemaVersion: "weekly_activity_api.current_response.v1",
    generatedAt: "2026-07-19T08:00:00Z",
    filters: { scope: "current" },
    page: { cursor: "0", nextCursor: null, total: 1 },
    items: [{ id: "event-a" }],
  };
  await t.test("cursor loop", () => expectRejected([
    { ...base, page: { cursor: "0", nextCursor: "0", total: 1 } },
  ], /cursor did not advance/));
  await t.test("duplicate id", () => expectRejected([
    { ...base, page: { cursor: "0", nextCursor: "1", total: 2 } },
    { ...base, page: { cursor: "1", nextCursor: null, total: 2 } },
  ], /duplicate event id/));
  await t.test("generation drift", () => expectRejected([
    { ...base, page: { cursor: "0", nextCursor: "1", total: 2 } },
    { ...base, generatedAt: "2026-07-19T09:00:00Z", page: { cursor: "1", nextCursor: null, total: 2 }, items: [{ id: "event-b" }] },
  ], /generation changed/));
  await t.test("truncated total", () => expectRejected([
    { ...base, page: { cursor: "0", nextCursor: null, total: 2 } },
  ], /total mismatch/));
  await t.test("missing generatedAt", () => expectRejected([
    { ...base, generatedAt: "" },
  ], /generatedAt is missing/));
});

test("weeklyDataSync invalid pagination never switches the active generation", async () => {
  const database = createMemoryDatabase();
  const mod = loadWeeklyDataSyncModule(database);
  database.put("weekly_config", "sync", {
    syncId: "weekly_old",
    generatedAt: "2026-07-18T08:00:00Z",
    currentDocId: "current_old",
    eventDocIdScheme: "sync-prefixed-v1",
  });
  database.put("weekly_current", "current_old", {
    syncId: "weekly_old",
    generatedAt: "2026-07-18T08:00:00Z",
    items: [{ id: "old-event", event_date_start: "2999-07-20", quality_status: "READY" }],
  });
  database.put("weekly_events", mod.__test.generationEventDocId("weekly_old", "old-event"), {
    syncId: "weekly_old",
    eventId: "old-event",
    item: { id: "old-event", event_date_start: "2999-07-20", quality_status: "READY" },
  });
  mod.__test.setTestRequestJson(async () => ({
    schemaVersion: "weekly_activity_api.current_response.v1",
    generatedAt: "2026-07-19T08:00:00Z",
    filters: { scope: "current", lookbackDays: 0 },
    page: { cursor: "0", nextCursor: "0", total: 1 },
    items: [{ id: "new-event" }],
  }));

  await assert.rejects(() => mod.__test.syncData({ source: "unit-test" }), /cursor did not advance/);
  assert.equal(database.get("weekly_config", "sync").syncId, "weekly_old");
  const oldItem = await mod.__test.readData({ path: "/api/v1/weekly/items/old-event", query: {} });
  assert.equal(oldItem.id, "old-event");
});

test("weeklyDataSync hot read derives date index from local package ranges", () => {
  const mod = loadWeeklyDataSyncModule();
  const index = mod.__test.dateIndexFromItems({
    generatedAt: "2026-06-01T00:00:00Z",
    items: [
      {
        id: "range-event",
        event_date_start: "2999-06-01",
        event_date_end: "2999-06-03",
        quality_status: "READY",
      },
      {
        id: "past-event",
        event_date_start: "2000-01-01",
        event_date_end: "2000-01-01",
        quality_status: "READY",
      },
    ],
  });

  assert.deepEqual(Array.from(index.dates, (item) => item.date), ["2999-06-01", "2999-06-02", "2999-06-03"]);
  assert.equal(index.item_count, 1);
});

test("weeklyDataSync derives current, city and date facets from one range projection", () => {
  const mod = loadWeeklyDataSyncModule();
  const currentDoc = {
    generatedAt: "2026-07-18T19:58:51+08:00",
    items: [
      { id: "shanghai-friday", city_key: "shanghai", city: ["上海"], event_date_start: "2999-07-24", quality_status: "READY" },
      { id: "shanghai-saturday", city_key: "shanghai", city: ["上海"], event_date_start: "2999-07-25", quality_status: "READY" },
      { id: "beijing-sunday", city_key: "beijing", city: ["北京"], event_date_start: "2999-07-26", quality_status: "READY" },
      { id: "outside", city_key: "shanghai", city: ["上海"], event_date_start: "2999-07-31", quality_status: "READY" },
    ],
  };
  const query = { dateStart: "2999-07-24", dateEnd: "2999-07-26", limit: 100 };

  const current = mod.__test.currentResponseFromItems(currentDoc, query);
  const cities = mod.__test.cityIndexFromItems(currentDoc, query);
  const dates = mod.__test.dateIndexFromItems(currentDoc, query);

  assert.equal(current.page.total, 3);
  assert.equal(cities.scope, "current");
  assert.equal(cities.item_count, current.page.total);
  assert.deepEqual(
    Array.from(cities.cities, (entry) => [entry.city_key, entry.item_count]),
    [["shanghai", 2], ["beijing", 1]],
  );
  assert.equal(dates.item_count, current.page.total);
  assert.deepEqual(Array.from(dates.dates, (entry) => entry.date), ["2999-07-24", "2999-07-25", "2999-07-26"]);
});

test("weeklyDataSync mini-program hot reads skip slow container freshness probe", () => {
  const mod = loadWeeklyDataSyncModule();

  assert.equal(mod.__test.shouldSkipContainerFreshness({ source: "miniprogram-hot-db" }, {}), true);
  assert.equal(mod.__test.shouldSkipContainerFreshness({}, { skipFreshness: "1" }), true);
  assert.equal(mod.__test.shouldSkipContainerFreshness({}, {}), false);
});

function createMemoryDatabase() {
  const state = new Map();
  let failSet = null;
  let failRemove = null;

  function docs(name) {
    if (!state.has(name)) state.set(name, new Map());
    return state.get(name);
  }

  function collection(name) {
    const rows = docs(name);
    return {
      doc(id) {
        return {
          async get() {
            const value = rows.get(id);
            return { data: value ? [{ _id: id, ...structuredClone(value) }] : [] };
          },
          async set(value) {
            if (failSet && failSet(name, id, value)) throw new Error(`forced set failure: ${name}/${id}`);
            rows.set(id, structuredClone(value));
            return { ok: true };
          },
          async remove() {
            if (failRemove && failRemove(name, id)) throw new Error(`forced remove failure: ${name}/${id}`);
            rows.delete(id);
            return { ok: true };
          },
        };
      },
      where(filter) {
        return {
          limit(max) {
            return {
              async get() {
                const data = [];
                for (const [id, value] of rows.entries()) {
                  if (Object.entries(filter).every(([key, expected]) => value[key] === expected)) {
                    data.push({ _id: id, ...structuredClone(value) });
                  }
                  if (data.length >= max) break;
                }
                return { data };
              },
            };
          },
        };
      },
    };
  }

  return {
    command: {},
    collection,
    put(name, id, value) { docs(name).set(id, structuredClone(value)); },
    get(name, id) { return docs(name).get(id); },
    has(name, id) { return docs(name).has(id); },
    setFailSet(predicate) { failSet = predicate; },
    setFailRemove(predicate) { failRemove = predicate; },
  };
}

function upstreamFixture() {
  const generatedAt = "2026-07-19T08:00:00Z";
  return async (requestPath) => {
    if (requestPath.startsWith("/api/v1/weekly/current?")) {
      assert.match(requestPath, /scope=current/);
      assert.match(requestPath, /lookbackDays=0/);
      return {
        schemaVersion: "weekly_activity_api.current_response.v1",
        generatedAt,
        filters: { scope: "current", lookbackDays: 0 },
        page: { cursor: 0, limit: 100, nextCursor: null, total: 2 },
        items: [
          { id: "new-shanghai", city_key: "shanghai", city: ["上海"], event_date_start: "2999-07-24", quality_status: "READY" },
          { id: "new-beijing", city_key: "beijing", city: ["北京"], event_date_start: "2999-07-25", quality_status: "READY" },
        ],
      };
    }
    if (requestPath === "/api/v1/weekly/manifest") return { generated_at: generatedAt, item_count: 9 };
    if (requestPath === "/api/v1/weekly/llm/materialized-summary") return { generatedAt, summary: "ok" };
    throw new Error(`unexpected upstream path: ${requestPath}`);
  };
}

test("weeklyDataSync commits one active generation, aligns facets, and hides old event documents", async () => {
  const database = createMemoryDatabase();
  const mod = loadWeeklyDataSyncModule(database);
  mod.__test.setTestRequestJson(upstreamFixture());

  database.put("weekly_config", "sync", {
    syncId: "weekly_old",
    generatedAt: "2026-07-18T08:00:00Z",
    currentDocId: "current_old",
    eventDocIdScheme: "sync-prefixed-v1",
  });
  database.put("weekly_current", "current_old", {
    syncId: "weekly_old",
    generatedAt: "2026-07-18T08:00:00Z",
    items: [{ id: "old-event", event_date_start: "2999-07-20", quality_status: "READY" }],
  });
  database.put("weekly_events", mod.__test.generationEventDocId("weekly_old", "old-event"), {
    syncId: "weekly_old",
    eventId: "old-event",
    item: { id: "old-event", event_date_start: "2999-07-20", quality_status: "READY" },
  });

  const result = await mod.__test.syncData({ source: "unit-test" });
  assert.equal(result.ok, true);
  assert.equal(result.cleanup.ok, true);
  assert.equal(result.counts.currentItems, 2);
  const activeConfig = database.get("weekly_config", "sync");
  assert.equal(activeConfig.syncId, result.syncId);
  const activeRoutes = database.get("weekly_config", activeConfig.routesDocId);
  assert.ok(activeRoutes.hotPaths.includes("/api/v1/weekly/config"));
  assert.ok(activeRoutes.hotPaths.includes("/api/v1/weekly/dates"));
  assert.equal(database.has("weekly_current", "current_old"), false);
  assert.equal(database.has("weekly_events", mod.__test.generationEventDocId("weekly_old", "old-event")), false);

  const config = await mod.__test.readData({ path: "/api/v1/weekly/config", query: {} });
  const current = await mod.__test.readData({ path: "/api/v1/weekly/current", query: { scope: "current", lookbackDays: 0, limit: 100 }, source: "miniprogram-hot-db" });
  const cities = await mod.__test.readData({ path: "/api/v1/weekly/cities", query: { scope: "current", lookbackDays: 0 }, source: "miniprogram-hot-db" });
  const dates = await mod.__test.readData({ path: "/api/v1/weekly/dates", query: { scope: "current", lookbackDays: 0 }, source: "miniprogram-hot-db" });
  assert.equal(config.syncId, result.syncId);
  assert.equal(current.syncId, result.syncId);
  assert.equal(cities.syncId, result.syncId);
  assert.equal(dates.syncId, result.syncId);
  assert.equal(current.generatedAt, result.generatedAt);
  assert.equal(cities.generated_at, result.generatedAt);
  assert.equal(dates.generated_at, result.generatedAt);
  assert.equal(current.page.total, 2);
  assert.equal(cities.item_count, 2);
  assert.equal(dates.item_count, 2);

  const oldItem = await mod.__test.readData({ path: "/api/v1/weekly/items/old-event", query: {} });
  assert.equal(oldItem.error.code, "HOT_DB_ITEM_NOT_FOUND");
  const newItem = await mod.__test.readData({ path: "/api/v1/weekly/items/new-shanghai", query: {} });
  assert.equal(newItem.id, "new-shanghai");
  const batch = await mod.__test.readData({ path: "/api/v1/weekly/items/batch", query: { ids: "old-event,new-shanghai" } });
  assert.deepEqual(Array.from(batch.items, (item) => item.id), ["new-shanghai"]);
});

test("weeklyDataSync staging failure leaves the prior active generation readable", async () => {
  const database = createMemoryDatabase();
  const mod = loadWeeklyDataSyncModule(database);
  mod.__test.setTestRequestJson(upstreamFixture());
  database.put("weekly_config", "sync", {
    syncId: "weekly_old",
    generatedAt: "2026-07-18T08:00:00Z",
    currentDocId: "current_old",
    eventDocIdScheme: "sync-prefixed-v1",
  });
  database.put("weekly_current", "current_old", {
    syncId: "weekly_old",
    generatedAt: "2026-07-18T08:00:00Z",
    items: [{ id: "old-event", event_date_start: "2999-07-20", quality_status: "READY" }],
  });
  database.put("weekly_events", mod.__test.generationEventDocId("weekly_old", "old-event"), {
    syncId: "weekly_old",
    eventId: "old-event",
    item: { id: "old-event", event_date_start: "2999-07-20", quality_status: "READY" },
  });
  database.setFailSet((name) => name === "weekly_events");

  await assert.rejects(() => mod.__test.syncData({ source: "unit-test" }), /forced set failure/);
  assert.equal(database.get("weekly_config", "sync").syncId, "weekly_old");
  const oldItem = await mod.__test.readData({ path: "/api/v1/weekly/items/old-event", query: {} });
  assert.equal(oldItem.id, "old-event");
});

test("weeklyDataSync cleanup failure keeps the newly committed generation active", async () => {
  const database = createMemoryDatabase();
  const mod = loadWeeklyDataSyncModule(database);
  mod.__test.setTestRequestJson(upstreamFixture());
  const oldEventDocId = mod.__test.generationEventDocId("weekly_old", "old-event");
  database.put("weekly_config", "sync", {
    syncId: "weekly_old",
    generatedAt: "2026-07-18T08:00:00Z",
    currentDocId: "current_old",
    eventDocIdScheme: "sync-prefixed-v1",
  });
  database.put("weekly_current", "current_old", {
    syncId: "weekly_old",
    generatedAt: "2026-07-18T08:00:00Z",
    items: [{ id: "old-event", event_date_start: "2999-07-20", quality_status: "READY" }],
  });
  database.put("weekly_events", oldEventDocId, {
    syncId: "weekly_old",
    eventId: "old-event",
    item: { id: "old-event", event_date_start: "2999-07-20", quality_status: "READY" },
  });
  database.setFailRemove((name, id) => name === "weekly_events" && id === oldEventDocId);

  const result = await mod.__test.syncData({ source: "unit-test" });
  assert.equal(result.ok, false);
  assert.equal(result.activeGenerationCommitted, true);
  assert.equal(result.cleanup.ok, false);
  assert.equal(database.get("weekly_config", "sync").syncId, result.syncId);
  assert.equal(database.has("weekly_events", oldEventDocId), true);

  const oldItem = await mod.__test.readData({ path: "/api/v1/weekly/items/old-event", query: {} });
  assert.equal(oldItem.error.code, "HOT_DB_ITEM_NOT_FOUND");
  const newItem = await mod.__test.readData({ path: "/api/v1/weekly/items/new-shanghai", query: {} });
  assert.equal(newItem.id, "new-shanghai");
  assert.equal(newItem.syncId, result.syncId);
});
