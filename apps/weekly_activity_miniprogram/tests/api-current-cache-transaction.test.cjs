const assert = require("node:assert/strict");
const test = require("node:test");

const API_PATH = require.resolve("../utils/api");

function freshApi() {
  delete require.cache[API_PATH];
  return require(API_PATH);
}

function createStorage(seed = []) {
  const store = new Map(seed);
  return {
    store,
    getStorageSync(key) {
      return store.has(key) ? store.get(key) : "";
    },
    setStorageSync(key, value) {
      store.set(key, value);
    },
    removeStorageSync(key) {
      store.delete(key);
    },
    getStorageInfoSync() {
      return { keys: Array.from(store.keys()) };
    },
  };
}

function currentPage({ generationId, cursor, nextCursor, total, ids }) {
  return {
    schemaVersion: "weekly_activity_api.current_response.v1",
    generatedAt: "2026-07-19T08:00:00Z",
    generationId,
    filters: { scope: "current" },
    page: { cursor, limit: 1, nextCursor, total },
    items: ids.map((id) => ({
      id,
      title: `${id} techno`,
      city_key: "shanghai",
      city_keys: ["shanghai"],
      city: ["上海"],
      venue_name: "TEST",
      event_date_start: "2026-07-24",
      quality_status: "READY",
      music_styles: ["techno"],
    })),
  };
}

function installContainerRuntime(storage, responder, extraCloud = {}) {
  global.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "",
        staticBaseUrl: "",
        offlineSnapshotFallback: false,
        cacheFallbackDelayMs: 0,
        cloudCallTimeoutMs: 100,
        ...extraCloud,
      },
    },
  });
  global.wx = {
    ...storage,
    cloud: {
      callContainer(options) {
        return responder(options);
      },
    },
  };
}

test("failed multi-page refresh never persists a partial current generation", { concurrency: false }, async () => {
  const storage = createStorage();
  installContainerRuntime(storage, ({ path }) => {
    const cursor = Number(new URL(`https://container.test${path}`).searchParams.get("cursor") || 0);
    const page = cursor === 0
      ? currentPage({ generationId: "sha256:new-a", cursor: 0, nextCursor: 1, total: 2, ids: ["new-a-0"] })
      : currentPage({ generationId: "sha256:new-b", cursor: 1, nextCursor: null, total: 2, ids: ["new-b-1"] });
    return Promise.resolve({ statusCode: 200, data: page });
  });
  const api = freshApi();

  await assert.rejects(
    api.fetchAllCurrentResponse({ scope: "current", limit: 1 }),
    /CURRENT_GENERATION_ID_DRIFT/,
  );

  assert.deepEqual(
    Array.from(storage.store.keys()).filter((key) => String(key).startsWith("weeklyActivityApiCache:")),
    [],
    "a paginator-owned refresh must not write ordinary per-page cache entries",
  );
  assert.deepEqual(
    Array.from(storage.store.keys()).filter((key) => String(key).startsWith("weeklyActivityCurrentPage:")),
    [],
    "failed immutable staging must be removed",
  );
});

test("a failed next generation keeps the prior complete generation active", { concurrency: false }, async () => {
  const storage = createStorage();
  let mode = "old";
  installContainerRuntime(storage, ({ path }) => {
    const cursor = Number(new URL(`https://container.test${path}`).searchParams.get("cursor") || 0);
    if (mode === "offline") return Promise.reject(new Error("offline"));
    if (mode === "old") {
      return Promise.resolve({
        statusCode: 200,
        data: currentPage({
          generationId: "sha256:old-complete",
          cursor,
          nextCursor: cursor === 0 ? 1 : null,
          total: 2,
          ids: [`old-${cursor}`],
        }),
      });
    }
    return Promise.resolve({
      statusCode: 200,
      data: currentPage({
        generationId: cursor === 0 ? "sha256:new-partial" : "sha256:new-drift",
        cursor,
        nextCursor: cursor === 0 ? 1 : null,
        total: 2,
        ids: [`new-${cursor}`],
      }),
    });
  });
  const api = freshApi();

  const old = await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  assert.deepEqual(old.items.map((item) => item.id), ["old-0", "old-1"]);

  mode = "partial";
  await assert.rejects(
    api.fetchAllCurrentResponse({ scope: "current", limit: 1 }),
    /CURRENT_GENERATION_ID_DRIFT/,
  );

  mode = "offline";
  const recovered = await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  assert.deepEqual(recovered.items.map((item) => item.id), ["old-0", "old-1"]);
  assert.equal(recovered.generationId, "sha256:old-complete");
  assert.equal(recovered.fromCache, true);
});

test("legacy per-page cache remains a read-only recovery fallback during migration", { concurrency: false }, async () => {
  const storage = createStorage();
  let offline = false;
  installContainerRuntime(storage, ({ path }) => {
    if (offline) return Promise.reject(new Error("offline"));
    const cursor = Number(new URL(`https://container.test${path}`).searchParams.get("cursor") || 0);
    return Promise.resolve({
      statusCode: 200,
      data: currentPage({
        generationId: "sha256:legacy-pages",
        cursor,
        nextCursor: cursor === 0 ? 1 : null,
        total: 2,
        ids: [`legacy-${cursor}`],
      }),
    });
  });
  const api = freshApi();

  await api.requestApi("/api/v1/weekly/current", { scope: "current", limit: 1, cursor: 0 });
  await api.requestApi("/api/v1/weekly/current", { scope: "current", limit: 1, cursor: 1 });
  assert.equal(
    Array.from(storage.store.keys()).filter((key) => String(key).startsWith("weeklyActivityApiCache:")).length,
    2,
  );

  offline = true;
  const recovered = await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  assert.deepEqual(recovered.items.map((item) => item.id), ["legacy-0", "legacy-1"]);
  assert.equal(recovered.fromCache, true);
  assert.equal(
    Array.from(storage.store.keys()).some((key) => String(key).startsWith("weeklyActivityCurrentActive:")),
    false,
    "legacy cache reads must not be promoted as a newly validated live generation",
  );
});

test("storage quota failure leaves the old pointer and its pages recoverable", { concurrency: false }, async () => {
  const storage = createStorage();
  let mode = "old";
  installContainerRuntime(storage, ({ path }) => {
    if (mode === "offline") return Promise.reject(new Error("offline"));
    const cursor = Number(new URL(`https://container.test${path}`).searchParams.get("cursor") || 0);
    const generationId = mode === "old" ? "sha256:quota-old" : "sha256:quota-new";
    return Promise.resolve({
      statusCode: 200,
      data: currentPage({
        generationId,
        cursor,
        nextCursor: cursor === 0 ? 1 : null,
        total: 2,
        ids: [`${mode}-${cursor}`],
      }),
    });
  });
  const api = freshApi();
  await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  const pointerKey = Array.from(storage.store.keys()).find((key) => String(key).startsWith("weeklyActivityCurrentActive:"));
  assert.ok(pointerKey);
  assert.equal(storage.store.get(pointerKey).generationId, "sha256:quota-old");

  const originalSet = global.wx.setStorageSync;
  global.wx.setStorageSync = (key, value) => {
    if (String(key).startsWith("weeklyActivityCurrentPage:")) throw new Error("storage quota exceeded");
    originalSet(key, value);
  };
  mode = "new";
  const fresh = await api.fetchAllCurrentResponse({ scope: "current", limit: 1, __liveRefresh: true });
  assert.equal(fresh.generationId, "sha256:quota-new", "live rendering should not fail merely because cache staging is full");
  assert.equal(storage.store.get(pointerKey).generationId, "sha256:quota-old");
  assert.equal(
    storage.store.get("weeklyActivityCurrentGeneration:v1").generationId,
    "sha256:quota-old",
    "durable detail identity must remain atomic with the active feed pointer",
  );

  mode = "offline";
  const recovered = await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  assert.equal(recovered.generationId, "sha256:quota-old");
  assert.deepEqual(recovered.items.map((item) => item.id), ["old-0", "old-1"]);
});

test("activating a complete replacement removes the previous generation chunks", { concurrency: false }, async () => {
  const storage = createStorage();
  let generation = "first";
  installContainerRuntime(storage, ({ path }) => {
    const cursor = Number(new URL(`https://container.test${path}`).searchParams.get("cursor") || 0);
    return Promise.resolve({
      statusCode: 200,
      data: currentPage({
        generationId: `sha256:${generation}`,
        cursor,
        nextCursor: cursor === 0 ? 1 : null,
        total: 2,
        ids: [`${generation}-${cursor}`],
      }),
    });
  });
  const api = freshApi();
  await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  const firstKeys = Array.from(storage.store.keys()).filter((key) => String(key).startsWith("weeklyActivityCurrentPage:"));
  assert.ok(firstKeys.length > 0);

  generation = "second";
  await api.fetchAllCurrentResponse({ scope: "current", limit: 1, __skipCache: true });
  // Skip-cache is intentionally non-persistent, so activate the replacement
  // with an ordinary validated refresh after proving the live path separately.
  await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  assert.ok(firstKeys.every((key) => !storage.store.has(key)));
  const pointerKey = Array.from(storage.store.keys()).find((key) => String(key).startsWith("weeklyActivityCurrentActive:"));
  assert.equal(storage.store.get(pointerKey).generationId, "sha256:second");
});

test("same-profile concurrent refreshes never delete another live transaction's staged pages", { concurrency: false }, async () => {
  const storage = createStorage();
  global.wx = { ...storage };
  global.getApp = () => ({ globalData: { cloud: {} } });
  const api = freshApi();

  let releaseFirstPageOne;
  const firstPageOneGate = new Promise((resolve) => { releaseFirstPageOne = resolve; });
  let firstReachedPageOne;
  const firstReachedPageOneGate = new Promise((resolve) => { firstReachedPageOne = resolve; });
  const firstRequest = (_path, data) => {
    const cursor = Number(data.cursor || 0);
    if (cursor === 0) {
      return Promise.resolve(currentPage({
        generationId: "sha256:concurrent-first",
        cursor: 0,
        nextCursor: 1,
        total: 2,
        ids: ["first-0"],
      }));
    }
    firstReachedPageOne();
    return firstPageOneGate;
  };

  const firstRefresh = api.fetchAllCurrentResponse({ scope: "current", limit: 1 }, firstRequest);
  await firstReachedPageOneGate;

  await assert.rejects(
    api.fetchAllCurrentResponse(
      { scope: "current", limit: 1 },
      () => Promise.reject(new Error("second refresh failed")),
    ),
    /second refresh failed/,
  );

  releaseFirstPageOne(currentPage({
    generationId: "sha256:concurrent-first",
    cursor: 1,
    nextCursor: null,
    total: 2,
    ids: ["first-1"],
  }));
  const complete = await firstRefresh;
  assert.deepEqual(complete.items.map((item) => item.id), ["first-0", "first-1"]);

  const pointerKey = Array.from(storage.store.keys()).find((key) => (
    String(key).startsWith("weeklyActivityCurrentActive:")
  ));
  assert.ok(pointerKey, "the surviving refresh should activate its complete pointer");
  const pointer = storage.store.get(pointerKey);
  const chunkKeys = pointer.routes.flatMap((route) => route.chunkKeys);
  assert.ok(chunkKeys.length >= 2);
  assert.deepEqual(
    chunkKeys.filter((key) => !storage.store.has(key)),
    [],
    "a failed concurrent refresh must not orphan the surviving pointer",
  );
});

test("abandoned staging cleanup preserves chunks reachable from the active pointer", { concurrency: false }, async () => {
  const storage = createStorage();
  let offline = false;
  installContainerRuntime(storage, ({ path }) => {
    if (offline) return Promise.reject(new Error("offline"));
    const cursor = Number(new URL(`https://container.test${path}`).searchParams.get("cursor") || 0);
    return Promise.resolve({
      statusCode: 200,
      data: currentPage({
        generationId: "sha256:committed-before-crash",
        cursor,
        nextCursor: cursor === 0 ? 1 : null,
        total: 2,
        ids: [`committed-${cursor}`],
      }),
    });
  });
  const api = freshApi();

  await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  const pointerKey = Array.from(storage.store.keys()).find((key) => (
    String(key).startsWith("weeklyActivityCurrentActive:v2:")
  ));
  assert.ok(pointerKey);
  const pointer = storage.store.get(pointerKey);
  const chunkKeys = pointer.routes.flatMap((route) => route.chunkKeys);
  assert.ok(chunkKeys.length >= 2);

  const profileHash = pointerKey.slice("weeklyActivityCurrentActive:v2:".length);
  const staleRegistryKey = `weeklyActivityCurrentStaging:v2:${profileHash}:crashed-after-activation`;
  storage.store.set(staleRegistryKey, {
    transactionId: "crashed-after-activation",
    startedAt: Date.now() - (8 * 60 * 60 * 1000),
    updatedAt: Date.now() - (8 * 60 * 60 * 1000),
    keys: chunkKeys,
  });

  offline = true;
  const recovered = await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });

  assert.deepEqual(recovered.items.map((item) => item.id), ["committed-0", "committed-1"]);
  assert.deepEqual(
    chunkKeys.filter((key) => !storage.store.has(key)),
    [],
    "cleanup after a post-activation crash must not delete the active generation",
  );
  assert.equal(storage.store.has(staleRegistryKey), false, "the stale registry itself should still be removed");
});

test("skip-cache and live-only requests neither read nor write durable API cache", { concurrency: false }, async () => {
  for (const control of ["__skipCache", "__liveOnly"]) {
    const storage = createStorage();
    installContainerRuntime(storage, () => Promise.resolve({
      statusCode: 200,
      data: currentPage({
        generationId: `sha256:${control}`,
        cursor: 0,
        nextCursor: null,
        total: 1,
        ids: [control],
      }),
    }));
    const api = freshApi();
    const result = await api.requestApi("/api/v1/weekly/current", {
      scope: "current",
      limit: 1,
      [control]: true,
    });
    assert.equal(result.items[0].id, control);
    assert.deepEqual(Array.from(storage.store.keys()), [], `${control} must not write storage`);
  }
});

test("live-refresh bypasses reads and atomically activates the validated current generation", { concurrency: false }, async () => {
  const storage = createStorage();
  let generation = "old-live-refresh";
  installContainerRuntime(storage, ({ path }) => {
    const cursor = Number(new URL(`https://container.test${path}`).searchParams.get("cursor") || 0);
    return Promise.resolve({
      statusCode: 200,
      data: currentPage({
        generationId: `sha256:${generation}`,
        cursor,
        nextCursor: cursor === 0 ? 1 : null,
        total: 2,
        ids: [`${generation}-${cursor}`],
      }),
    });
  });
  const api = freshApi();
  await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  const pointerKey = Array.from(storage.store.keys()).find((key) => (
    String(key).startsWith("weeklyActivityCurrentActive:v2:")
  ));
  const oldChunkKeys = storage.store.get(pointerKey).routes.flatMap((route) => route.chunkKeys);

  generation = "new-live-refresh";
  const refreshed = await api.fetchAllCurrentResponse({
    scope: "current",
    limit: 1,
    __liveRefresh: true,
  });

  assert.equal(refreshed.generationId, "sha256:new-live-refresh");
  assert.deepEqual(refreshed.items.map((item) => item.id), ["new-live-refresh-0", "new-live-refresh-1"]);
  assert.equal(storage.store.get(pointerKey).generationId, "sha256:new-live-refresh");
  assert.ok(oldChunkKeys.every((key) => !storage.store.has(key)));
});

function staticPackage() {
  return {
    schema_version: "weekly_activity_miniprogram_current.v1",
    generated_at: "2026-07-19T08:00:00Z",
    generation_id: "sha256:static-one",
    items: ["a", "b"].map((suffix, index) => ({
      id: `static-${suffix}`,
      title: `Static ${suffix} techno`,
      city_key: "shanghai",
      city_keys: ["shanghai"],
      city: ["上海"],
      venue_name: "STATIC",
      event_date_start: `2026-07-${24 + index}`,
      quality_status: "READY",
      music_styles: ["techno"],
    })),
  };
}

function installStaticRuntime(storage, requestHandler, extraCloud = {}) {
  global.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "",
        staticBaseUrl: "https://static.example.test/releases/current",
        offlineSnapshotFallback: false,
        cacheFallbackDelayMs: 0,
        cloudCallTimeoutMs: 100,
        ...extraCloud,
      },
    },
  });
  global.wx = {
    ...storage,
    cloud: { callContainer: () => Promise.reject(new Error("container offline")) },
    request: requestHandler,
  };
}

test("one static generation is downloaded once for pagination, facets and batch", { concurrency: false }, async () => {
  const storage = createStorage();
  const urls = [];
  installStaticRuntime(storage, (options) => {
    urls.push(options.url);
    options.success({ statusCode: 200, data: staticPackage() });
    return { abort() {} };
  });
  const api = freshApi();
  api.__setTodayForTests("2026-07-19");

  const current = await api.fetchAllCurrentResponse({ scope: "current", limit: 1 });
  const cities = await api.requestApi("/api/v1/weekly/cities", { scope: "current" });
  const dates = await api.requestApi("/api/v1/weekly/dates", { scope: "current" });
  const batch = await api.requestApi("/api/v1/weekly/items/batch", {
    ids: "static-a,static-b",
    generationId: "sha256:static-one",
  });

  assert.deepEqual(current.items.map((item) => item.id), ["static-a", "static-b"]);
  assert.equal(cities.item_count, 2);
  assert.equal(dates.item_count, 2);
  assert.deepEqual(batch.items.map((item) => item.id), ["static-a", "static-b"]);
  assert.equal(urls.length, 1, "current.json must not be downloaded once per route/page");
  assert.match(urls[0], /current\.json\?_ts=\d+$/);
});

test("failed shared static download clears inflight state so the next request retries", { concurrency: false }, async () => {
  const storage = createStorage();
  let attempts = 0;
  let shouldFail = true;
  installStaticRuntime(storage, (options) => {
    attempts += 1;
    setTimeout(() => {
      if (shouldFail) options.fail(new Error("static offline"));
      else options.success({ statusCode: 200, data: staticPackage() });
    }, 1);
    return { abort() {} };
  });
  const api = freshApi();
  api.__setTodayForTests("2026-07-19");

  const failed = await Promise.allSettled([
    api.requestApi("/api/v1/weekly/current", { scope: "current", limit: 1 }),
    api.requestApi("/api/v1/weekly/cities", { scope: "current" }),
  ]);
  assert.ok(failed.every((result) => result.status === "rejected"));
  assert.equal(attempts, 1, "concurrent static routes must share the failed inflight download");

  shouldFail = false;
  const dates = await api.requestApi("/api/v1/weekly/dates", { scope: "current" });
  assert.equal(dates.item_count, 2);
  assert.equal(attempts, 2, "a rejected inflight entry must be cleared for retry");
});

test("skip-cache and live-only controls bypass the short-lived static payload cache", { concurrency: false }, async () => {
  const storage = createStorage();
  let attempts = 0;
  installStaticRuntime(storage, (options) => {
    attempts += 1;
    options.success({ statusCode: 200, data: staticPackage() });
    return { abort() {} };
  });
  const api = freshApi();
  api.__setTodayForTests("2026-07-19");

  await api.requestApi("/api/v1/weekly/current", { scope: "current", limit: 1 });
  await api.requestApi("/api/v1/weekly/cities", { scope: "current", __skipCache: true });
  await api.requestApi("/api/v1/weekly/dates", { scope: "current", __liveOnly: true });

  assert.equal(attempts, 3);
});

test("static dedupe preserves every city key and aligned city label", { concurrency: false }, () => {
  global.wx = {};
  global.getApp = () => ({ globalData: { cloud: {} } });
  const api = freshApi();
  api.__setTodayForTests("2026-07-19");
  const shared = {
    title: "Multi-city techno tour",
    venue_name: "SAME VENUE",
    event_date_start: "2026-07-24",
    quality_status: "READY",
    music_styles: ["techno"],
  };
  const response = api.__currentResponseFromStaticForTests({
    generated_at: "2026-07-19T08:00:00Z",
    generation_id: "sha256:multi-city",
    items: [
      {
        ...shared,
        id: "multi-city-event",
        city_key: "shanghai",
        city_keys: ["shanghai", "beijing"],
        cityKeys: ["shanghai", "beijing"],
        city: ["上海", "北京"],
      },
      {
        ...shared,
        id: "multi-city-event",
        city_key: "shanghai",
        city_keys: ["shanghai", "guangzhou"],
        cityKeys: ["shanghai", "guangzhou"],
        city: ["上海", "广州"],
        address: "richer row wins without erasing other cities",
      },
    ],
  }, { scope: "current", limit: 10 });

  assert.equal(response.items.length, 1);
  assert.deepEqual(response.items[0].city_keys, ["shanghai", "guangzhou", "beijing"]);
  assert.deepEqual(response.items[0].cityKeys, ["shanghai", "guangzhou", "beijing"]);
  assert.deepEqual(response.items[0].city, ["上海", "广州", "北京"]);
});
