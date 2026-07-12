const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const offlineSnapshotModule = require("../utils/offlineSnapshot");
// Mirrors the production date-ascending sort in currentResponseFromStatic.
const FIRST_OFFLINE_SNAPSHOT_ID = ([...(offlineSnapshotModule.OFFLINE_SNAPSHOT.items || [])]
  .sort((a, b) => {
    const aKey = String(a.event_date_start || "9999-12-31");
    const bKey = String(b.event_date_start || "9999-12-31");
    return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
  })[0] || {}).id || "";

function loadApiModule() {
  const filename = path.resolve(__dirname, "../utils/api.js");
  const code = fs.readFileSync(filename, "utf8");
  const sandbox = { module: { exports: {} }, exports: {}, console, setTimeout, clearTimeout, URL };
  // provide globalThis and a basic wx stub so cache.js can load without crashing
  sandbox.globalThis = sandbox;
  sandbox.wx = sandbox.wx || {};
  // minimal require resolution for the cache extraction
  sandbox.require = function requireCacheOnly(id) {
    if (id === "./api/cache") {
      const cacheCode = fs.readFileSync(path.resolve(__dirname, "../utils/api/cache.js"), "utf8");
      const cacheSandbox = { module: { exports: {} }, exports: {}, console, setTimeout, clearTimeout, Date };
      Object.defineProperty(cacheSandbox, "wx", { get() { return sandbox.wx; }, enumerable: true, configurable: true });
      cacheSandbox.globalThis = cacheSandbox;
      vm.runInNewContext(cacheCode, cacheSandbox, { filename: path.resolve(__dirname, "../utils/api/cache.js") });
      return cacheSandbox.module.exports;
    }
    if (id === "./offlineSnapshot") {
      const snapshotCode = fs.readFileSync(path.resolve(__dirname, "../utils/offlineSnapshot.js"), "utf8");
      const snapSandbox = { module: { exports: {} }, exports: {}, console };
      snapSandbox.globalThis = snapSandbox;
      vm.runInNewContext(snapshotCode, snapSandbox, { filename: path.resolve(__dirname, "../utils/offlineSnapshot.js") });
      return snapSandbox.module.exports;
    }
    throw new Error("unexpected require in api.js test: " + id);
  };
  vm.runInNewContext(code, sandbox, { filename });
  return {
    __setTodayForTests: sandbox.module.exports.__setTodayForTests,
    requestApi: sandbox.module.exports.requestApi,
    sandbox,
  };
}

const currentPayload = {
  generated_at: "2026-05-09T01:00:00Z",
  items: [
    {
      id: "ready-shanghai",
      title: "JACK'N",
      city_key: "shanghai",
      city: ["上海"],
      venue: ["EXIT Shanghai"],
      event_date_iso_guess: "2026-05-09",
      event_date_iso_guesses: ["2026-05-09"],
      quality_status: "READY",
    },
    {
      id: "ready-shanghai-duplicate",
      title: "📌 JACK'N",
      city_key: "shanghai",
      city: ["上海"],
      venue: ["EXIT Shanghai"],
      event_date_iso_guess: "2026-05-09",
      event_date_iso_guesses: ["2026-05-09"],
      quality_status: "READY",
    },
    {
      id: "draft-shanghai",
      city_key: "shanghai",
      event_date_iso_guess: "2026-05-09",
      quality_status: "RED",
    },
    {
      id: "ready-beijing",
      city_key: "beijing",
      event_date_iso_guess: "2026-05-09",
      quality_status: "READY",
    },
    {
      id: "exit_shanghai:7abfce849fee404d",
      title: "EXIT Shanghai",
      city_key: "shanghai",
      event_date_iso_guess: "2026-05-10",
      quality_status: "READY",
    },
    {
      id: "range-week",
      title: "Range Week",
      city_key: "shanghai",
      event_date_iso_guess: "2026-05-18",
      event_date_iso_guesses: ["2026-05-18", "2026-05-24"],
      event_date_start: "2026-05-18",
      event_date_end: "2026-05-24",
      quality_status: "READY",
    },
  ],
};

const atlasSnapshotPayload = {
  schema_version: "weekly_atlas_entity.v1",
  generated_at: "2026-05-20T16:47:43Z",
  publish_package: "TEST",
  artist_profiles: [
    {
      artist_id: "atlas:entity:one",
      canonical_name: "DJ A",
      verified: true,
      source: "atlas_alias_export",
    },
  ],
  lineup_resolved: [
    {
      event_id: "ready-shanghai",
      raw: "DJ A",
      artist_id: "atlas:entity:one",
      canonical_name: "DJ A",
      match_method: "alias_exact",
      match_score: 1,
      verified: true,
      display_tier: "show",
    },
    {
      event_id: "ready-shanghai",
      raw: "KeiKo",
      artist_id: null,
      canonical_name: null,
      match_method: "fuzzy_multiple",
      match_score: 1,
      verified: false,
      display_tier: "show_with_hint",
      candidates: [
        { artist_id: "atlas:entity:hidden-a", canonical_name: "KEIKO", score: 1 },
        { artist_id: "atlas:entity:hidden-b", canonical_name: "KeiKo 惠子", score: 1 },
      ],
    },
  ],
};

function installWechatMock(sandbox) {
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        staticBaseUrl: "https://example.test/weekly/releases/posterocr6-current-20260509",
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return Promise.reject({ errMsg: "cloud.callContainer:fail Error" });
      },
    },
    request(options) {
      const pathname = new URL(options.url).pathname;
      let data;

      if (pathname.endsWith("/current.json")) {
        data = currentPayload;
      } else if (pathname.endsWith("/by-city/index.json")) {
        data = { cities: [{ city_key: "shanghai", count: 1 }] };
      } else if (pathname.endsWith("/by-date/index.json")) {
        data = {
          dates: [
            { date: "2026-05-09", count: 1 },
            { date: "2026-05-20", count: 1 },
            { date: "2026-05-21", count: 1 },
            { date: "2026-05-24", count: 1 },
          ],
        };
      } else if (pathname.endsWith("/by-id/ready-shanghai.json")) {
        data = { item: currentPayload.items[0] };
      } else if (pathname.endsWith("/by-id/exit_shanghaiu3a7abfce849fee404d.json")) {
        data = { item: currentPayload.items[4] };
      } else if (pathname.endsWith("/source_actions/source_url_map.json")) {
        data = {
          sources: {
            hash123: {
              type: "wechat_article",
              url: "https://mp.weixin.qq.com/s/test",
            },
          },
        };
      } else if (pathname.endsWith("/weekly_entity_snapshot.json")) {
        data = atlasSnapshotPayload;
      } else {
        options.fail({ errMsg: `unexpected url ${options.url}` });
        return;
      }

      options.success({ statusCode: 200, data });
    },
  };
}

test("falls back to static current data when cloud container fails", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/current", {
    cityKey: "shanghai",
    date: "2026-05-09",
    limit: 10,
  });

  assert.equal(result.schemaVersion, "weekly_activity_api.current_response.v1");
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].id, "ready-shanghai");
  assert.equal(result.page.total, 1);
});

test("falls back when cloud container resolves with an error payload", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);
  sandbox.wx.cloud.callContainer = () => Promise.resolve({
    statusCode: 403,
    data: { error: { code: "SERVICE_FORBIDDEN" } },
  });

  const result = await requestApi("/api/v1/weekly/cities");

  assert.deepEqual(result.cities, [{ city_key: "shanghai", count: 1 }]);
});

test("static fallback filters multi-day events by inclusive date range", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/current", {
    cityKey: "shanghai",
    date: "2026-05-20",
    limit: 10,
  });

  assert.deepEqual(Array.from(result.items, (item) => item.id), ["range-week"]);
  assert.equal(result.page.total, 1);
});

test("static fallback default feed hides ended past events but keeps active ranges", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-05-21");
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/current", {
    cityKey: "shanghai",
    limit: 10,
  });

  assert.deepEqual(Array.from(result.items, (item) => item.id), ["range-week"]);
  assert.equal(result.page.total, 1);
});

test("static fallback date index hides past date chips", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-05-21");
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/dates");

  assert.deepEqual(Array.from(result.dates, (item) => item.date), ["2026-05-21", "2026-05-24"]);
  assert.equal(result.item_count, 2);
});

test("falls back to static item detail when cloud container fails", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/items/ready-shanghai");

  assert.equal(result.id, "ready-shanghai");
});

test("uses release storage slug for static item ids with punctuation", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/items/exit_shanghai:7abfce849fee404d");

  assert.equal(result.id, "exit_shanghai:7abfce849fee404d");
});

test("decodes encoded item ids before static fallback lookup", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/items/exit_shanghai%3A7abfce849fee404d");

  assert.equal(result.id, "exit_shanghai:7abfce849fee404d");
});

test("falls back to static source map when cloud container fails", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/source/hash123");

  assert.equal(result.url, "https://mp.weixin.qq.com/s/test");
});

test("falls back to static atlas event snapshot without exposing fuzzy candidate ids", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/atlas-events/ready-shanghai");

  assert.equal(result.schemaVersion, "weekly_activity_api.atlas_event.v1");
  assert.equal(result.lineupResolved.length, 2);
  assert.equal(result.lineupResolved[0].artistId, "atlas:entity:one");
  assert.equal(result.lineupResolved[1].artistId, null);
  assert.equal(result.lineupResolved[1].displayTier, "show_with_hint");
  assert.equal(Object.hasOwn(result.lineupResolved[1].candidates[0], "artist_id"), false);
  assert.equal(result.safety.fuzzyCandidateIdsExposed, false);
});

test("falls back to static batch items preserving requested order", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/items/batch", {
    ids: "ready-beijing,exit_shanghai%3A7abfce849fee404d,missing",
  });

  assert.deepEqual(Array.from(result.items, (item) => item.id), [
    "ready-beijing",
    "exit_shanghai:7abfce849fee404d",
  ]);
});

test("uses devtools mock fallback when cloud container hangs and static base is absent", async () => {
  const { requestApi, sandbox } = loadApiModule();
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        staticBaseUrl: "",
        mockBaseUrl: "http://127.0.0.1:8787",
        cloudInitTimeoutMs: 5,
        cloudCallTimeoutMs: 5,
        requestTimeoutMs: 50,
        devtoolsMockFallback: true,
      },
    },
  });

  sandbox.wx = {
    getSystemInfoSync() {
      return { platform: "devtools" };
    },
    cloud: {
      callContainer() {
        return new Promise(() => {});
      },
    },
    request(options) {
      assert.match(options.url, /^http:\/\/127\.0\.0\.1:8787\/api\/v1\/weekly\/current/);
      options.success({
        statusCode: 200,
        data: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          items: [currentPayload.items[0]],
          page: { total: 1, nextCursor: null },
        },
      });
    },
  };

  const result = await requestApi("/api/v1/weekly/current", { limit: 1 });

  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].id, "ready-shanghai");
});

test("falls back to public API when cloud container fails and no static base is configured", async () => {
  const { requestApi, sandbox } = loadApiModule();
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5,
        requestTimeoutMs: 50,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return Promise.reject({ errMsg: "cloud.callContainer:fail Error" });
      },
    },
    request(options) {
      assert.match(options.url, /^https:\/\/weekly-api\.example\.test\/api\/v1\/weekly\/current/);
      options.success({
        statusCode: 200,
        data: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          items: [currentPayload.items[0]],
          page: { total: 1, nextCursor: null },
        },
      });
    },
  };

  const result = await requestApi("/api/v1/weekly/current", { limit: 1 });

  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].id, "ready-shanghai");
});

test("uses CloudBase hot database function for first-screen current and dates", async () => {
  const { requestApi, sandbox } = loadApiModule();
  const calls = [];
  let containerCallCount = 0;
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        databaseFunctionName: "weeklyDataSync",
        useCloudDatabaseFirst: true,
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudInitTimeoutMs: 20,
        databaseFunctionTimeoutMs: 80,
        cloudCallTimeoutMs: 80,
        publicFallbackDelayMs: 5,
        requestTimeoutMs: 50,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callFunction(options) {
        calls.push(options.data);
        if (options.data.path === "/api/v1/weekly/dates") {
          return Promise.resolve({
            result: {
              schema_version: "weekly_activity_miniprogram_date_index.v1",
              dates: [{ date: "2026-06-02", count: 1 }],
            },
          });
        }
        return Promise.resolve({
          result: {
            schemaVersion: "weekly_activity_api.current_response.v1",
            items: [currentPayload.items[0]],
            page: { total: 1, nextCursor: null },
          },
        });
      },
      callContainer() {
        containerCallCount += 1;
        return Promise.reject({ errMsg: "should not use container" });
      },
    },
    request() {
      throw new Error("should not use public request");
    },
  };

  const current = await requestApi("/api/v1/weekly/current", { limit: 1 });
  const dates = await requestApi("/api/v1/weekly/dates");

  assert.equal(current.items[0].id, "ready-shanghai");
  assert.deepEqual(Array.from(dates.dates, (item) => item.date), ["2026-06-02"]);
  assert.deepEqual(Array.from(calls, (item) => item.path), ["/api/v1/weekly/current", "/api/v1/weekly/dates"]);
  assert.equal(calls[0].source, "miniprogram-hot-db");
  assert.equal(containerCallCount, 0);
});

test("starts public fallback before a hanging cloud container timeout", async () => {
  const { requestApi, sandbox } = loadApiModule();
  let publicRequestedAt = 0;
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 5,
        requestTimeoutMs: 50,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return new Promise(() => {});
      },
    },
    request(options) {
      publicRequestedAt = Date.now();
      assert.match(options.url, /^https:\/\/weekly-api\.example\.test\/api\/v1\/weekly\/current/);
      options.success({
        statusCode: 200,
        data: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          items: [currentPayload.items[0]],
          page: { total: 1, nextCursor: null },
        },
      });
    },
  };

  const startedAt = Date.now();
  const result = await requestApi("/api/v1/weekly/current", { limit: 1 });

  assert.equal(result.items[0].id, "ready-shanghai");
  assert.ok(publicRequestedAt - startedAt < 100, `public fallback started too late: ${publicRequestedAt - startedAt}ms`);
});

test("uses last successful cached weekly response when VPN-like routes hang", async () => {
  const { requestApi, sandbox } = loadApiModule();
  const storage = {};
  let mode = "online";
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 5,
        cacheFallbackDelayMs: 5,
        requestTimeoutMs: 50,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return mode === "online" ? Promise.reject({ errMsg: "cloud.callContainer:fail Error" }) : new Promise(() => {});
      },
    },
    getStorageSync(key) {
      return storage[key];
    },
    setStorageSync(key, value) {
      storage[key] = value;
    },
    request(options) {
      assert.match(options.url, /^https:\/\/weekly-api\.example\.test\/api\/v1\/weekly\/current/);
      if (mode !== "online") return;
      options.success({
        statusCode: 200,
        data: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          items: [currentPayload.items[0]],
          page: { total: 1, nextCursor: null },
        },
      });
    },
  };

  const online = await requestApi("/api/v1/weekly/current", { limit: 1 });
  assert.equal(online.items[0].id, "ready-shanghai");

  mode = "vpn-hang";
  const startedAt = Date.now();
  const cached = await requestApi("/api/v1/weekly/current", { limit: 1 });

  assert.equal(cached.items[0].id, "ready-shanghai");
  assert.equal(cached.__fromCache, true);
  assert.ok(Date.now() - startedAt < 100, "cached fallback should win before network timeouts");
});

test("cacheMaxAgeMs zero disables cached fallback during first-load probes", async () => {
  const { requestApi, sandbox } = loadApiModule();
  const cloud = {
    env: "test-env",
    service: "weekly-api",
    useMock: false,
    publicBaseUrl: "",
    staticBaseUrl: "",
    offlineSnapshotFallback: false,
    devtoolsMockFallback: false,
    cacheMaxAgeMs: 0,
    cacheFallbackDelayMs: 0,
    cloudClient: {
      callContainer() {
        return Promise.reject({ error: { code: "NETWORK_DOWN" } });
      },
    },
  };
  sandbox.getApp = () => ({ globalData: { cloud } });
  sandbox.wx = {
    getStorageSync() {
      return {
        cachedAt: Date.now(),
        payload: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          items: [{ id: "cached-row" }],
        },
      };
    },
    setStorageSync() {},
  };

  await assert.rejects(
    () => requestApi("/api/v1/weekly/current", { limit: 1 }),
    (error) => error?.error?.code === "NETWORK_DOWN" || error?.error?.code === "CLOUD_CLIENT_MISSING",
  );
});

test("uses bundled snapshot when VPN-like routes hang before any cache exists", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-05-26");
  let publicAborted = false;
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 5,
        publicRequestTimeoutMs: 5,
        cacheFallbackDelayMs: 5,
        requestTimeoutMs: 50,
        offlineSnapshotFallback: true,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return new Promise(() => {});
      },
    },
    request(options) {
      assert.match(options.url, /^https:\/\/weekly-api\.example\.test\/api\/v1\/weekly\/current/);
      return {
        abort() {
          publicAborted = true;
        },
      };
    },
  };

  const startedAt = Date.now();
  const result = await requestApi("/api/v1/weekly/current", { limit: 3 });

  assert.equal(result.__fromSnapshot, true);
  assert.equal(result.items.length, 3);
  assert.equal(result.items[0].id, FIRST_OFFLINE_SNAPSHOT_ID);
  assert.equal(publicAborted, true);
  assert.ok(Date.now() - startedAt < 500, "bundled snapshot should win before long network timeouts");
});

test("uses bundled snapshots for all first-screen endpoints when every route hangs", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-05-28");
  let publicAbortCount = 0;
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 5,
        publicRequestTimeoutMs: 5,
        cacheFallbackDelayMs: 5,
        requestTimeoutMs: 50,
        offlineSnapshotFallback: true,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return new Promise(() => {});
      },
    },
    request() {
      return {
        abort() {
          publicAbortCount += 1;
        },
      };
    },
  };

  const startedAt = Date.now();
  const [current, cities, dates] = await Promise.all([
    requestApi("/api/v1/weekly/current", { limit: 4 }),
    requestApi("/api/v1/weekly/cities"),
    requestApi("/api/v1/weekly/dates"),
  ]);

  assert.equal(current.__fromSnapshot, true);
  assert.equal(cities.__fromSnapshot, true);
  assert.equal(dates.__fromSnapshot, true);
  assert.ok(current.items.length > 0, "snapshot current should contain first-screen events");
  assert.ok(cities.cities.length > 0, "snapshot cities should contain filters");
  assert.ok(dates.dates.length > 0, "snapshot dates should contain filters");
  assert.equal(publicAbortCount, 3);
  assert.ok(Date.now() - startedAt < 500, "all first-screen snapshot fallbacks should resolve quickly");
});

test("fast bundled snapshot can win before public timeout on no-cache first load", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-05-26");
  let publicRequestCount = 0;
  let publicAbortCount = 0;
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 5,
        publicRequestTimeoutMs: 80,
        offlineSnapshotFallbackDelayMs: 10,
        requestTimeoutMs: 50,
        offlineSnapshotFallback: true,
        fastOfflineSnapshotFallback: true,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return new Promise(() => {});
      },
    },
    request(options) {
      publicRequestCount += 1;
      assert.match(options.url, /^https:\/\/weekly-api\.example\.test\/api\/v1\/weekly\/current/);
      return {
        abort() {
          publicAbortCount += 1;
        },
      };
    },
  };

  const startedAt = Date.now();
  const result = await requestApi("/api/v1/weekly/current", { limit: 3 });
  const elapsed = Date.now() - startedAt;

  assert.equal(result.__fromSnapshot, true);
  assert.equal(result.items[0].id, FIRST_OFFLINE_SNAPSHOT_ID);
  assert.equal(publicRequestCount, 1);
  assert.equal(publicAbortCount, 0);
  assert.ok(elapsed < 220, `fast bundled snapshot should not wait for long network timeouts, got ${elapsed}ms`);
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(publicAbortCount, 1);
});

test("does not let a configured snapshot delay beat a healthy public API without explicit fast-snapshot opt-in", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-06-03");
  let publicRequestCount = 0;
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 5,
        publicRequestTimeoutMs: 80,
        offlineSnapshotFallbackDelayMs: 10,
        requestTimeoutMs: 50,
        offlineSnapshotFallback: true,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return new Promise(() => {});
      },
    },
    request(options) {
      publicRequestCount += 1;
      assert.match(options.url, /^https:\/\/weekly-api\.example\.test\/api\/v1\/weekly\/current/);
      setTimeout(() => options.success({
        statusCode: 200,
        data: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          items: [{ ...currentPayload.items[0], id: "public-latest", event_date_iso_guess: "2026-06-03" }],
          page: { total: 1, nextCursor: null },
        },
      }), 35);
      return { abort() {} };
    },
  };

  const result = await requestApi("/api/v1/weekly/current", { limit: 1 });

  assert.equal(publicRequestCount, 1);
  assert.equal(result.__fromSnapshot, undefined);
  assert.equal(result.items[0].id, "public-latest");
});

test("prefers bundled snapshot before devtools mock after public fallback fails", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-05-28");
  let mockRequestCount = 0;
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        mockBaseUrl: "http://127.0.0.1:8787",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 1,
        publicRequestTimeoutMs: 1,
        requestTimeoutMs: 50,
        devtoolsMockFallback: true,
        offlineSnapshotFallback: true,
      },
    },
  });

  sandbox.wx = {
    getSystemInfoSync() {
      return { platform: "devtools" };
    },
    cloud: {
      callContainer() {
        return new Promise(() => {});
      },
    },
    request(options) {
      if (String(options.url).startsWith("http://127.0.0.1:8787")) {
        mockRequestCount += 1;
      }
      options.fail({ errMsg: "request:fail blackhole" });
      return { abort() {} };
    },
  };

  const result = await requestApi("/api/v1/weekly/current", { limit: 2 });

  assert.equal(result.__fromSnapshot, true);
  assert.equal(result.items.length, 2);
  assert.equal(mockRequestCount, 0);
});

test("does not persist bundled snapshot as the last successful cache", async () => {
  const { requestApi, sandbox } = loadApiModule();
  const storage = {};
  let mode = "vpn-hang";
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 5,
        publicRequestTimeoutMs: 5,
        cacheFallbackDelayMs: 5,
        requestTimeoutMs: 50,
        offlineSnapshotFallback: true,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return mode === "online"
          ? Promise.reject({ errMsg: "cloud.callContainer:fail Error" })
          : new Promise(() => {});
      },
    },
    getStorageSync(key) {
      return storage[key];
    },
    setStorageSync(key, value) {
      storage[key] = value;
    },
    request(options) {
      if (mode !== "online") {
        return { abort() {} };
      }
      options.success({
        statusCode: 200,
        data: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          items: [currentPayload.items[0]],
          page: { total: 1, nextCursor: null },
        },
      });
      return { abort() {} };
    },
  };

  const snapshot = await requestApi("/api/v1/weekly/current", { limit: 1 });
  assert.equal(snapshot.__fromSnapshot, true);
  assert.equal(Object.keys(storage).length, 0, "offline snapshot must not populate durable API cache");

  mode = "online";
  const online = await requestApi("/api/v1/weekly/current", { limit: 1 });
  assert.equal(online.items[0].id, "ready-shanghai");
  assert.equal(Object.keys(storage).length, 1, "real successful response should populate cache");

  mode = "vpn-hang";
  const cached = await requestApi("/api/v1/weekly/current", { limit: 1 });
  assert.equal(cached.__fromCache, true);
  assert.equal(cached.items[0].id, "ready-shanghai");
});

test("ignores late wx.request success after the JS hard timeout chooses snapshot", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-05-26");
  let lateSuccessSent = false;
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 5,
        publicRequestTimeoutMs: 5,
        requestTimeoutMs: 50,
        offlineSnapshotFallback: true,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        return new Promise(() => {});
      },
    },
    request(options) {
      setTimeout(() => {
        lateSuccessSent = true;
        options.success({
          statusCode: 200,
          data: {
            schemaVersion: "weekly_activity_api.current_response.v1",
            items: [currentPayload.items[0]],
            page: { total: 1, nextCursor: null },
          },
        });
      }, 25);
      return { abort() {} };
    },
  };

  const result = await requestApi("/api/v1/weekly/current", { limit: 1 });
  assert.equal(result.__fromSnapshot, true);
  assert.equal(result.items[0].id, FIRST_OFFLINE_SNAPSHOT_ID);
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(lateSuccessSent, true);
});

test("dedupes identical in-flight requests so retry tapping cannot fan out API calls", async () => {
  const { requestApi, sandbox } = loadApiModule();
  let containerCallCount = 0;
  let publicRequestCount = 0;
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 5,
        requestTimeoutMs: 50,
      },
    },
  });

  sandbox.wx = {
    cloud: {
      callContainer() {
        containerCallCount += 1;
        return new Promise(() => {});
      },
    },
    request(options) {
      publicRequestCount += 1;
      assert.match(options.url, /^https:\/\/weekly-api\.example\.test\/api\/v1\/weekly\/current/);
      setTimeout(() => options.success({
        statusCode: 200,
        data: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          items: [currentPayload.items[0]],
          page: { total: 1, nextCursor: null },
        },
      }), 5);
    },
  };

  const first = requestApi("/api/v1/weekly/current", { limit: 1 });
  const second = requestApi("/api/v1/weekly/current", { limit: 1 });
  const [firstResult, secondResult] = await Promise.all([first, second]);

  assert.equal(firstResult.items[0].id, "ready-shanghai");
  assert.equal(secondResult.items[0].id, "ready-shanghai");
  assert.equal(containerCallCount, 1);
  assert.equal(publicRequestCount, 1);
});
