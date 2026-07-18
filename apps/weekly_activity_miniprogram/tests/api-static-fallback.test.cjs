const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const offlineSnapshotModule = require("../utils/offlineSnapshot");
const bundledClubOverviews = require("../data/club_overviews");
// Mirrors the production date-ascending sort in currentResponseFromStatic.
const FIRST_OFFLINE_SNAPSHOT_ITEM = ([...(offlineSnapshotModule.OFFLINE_SNAPSHOT.items || [])]
  .sort((a, b) => {
    const aKey = String(a.event_date_start || "9999-12-31");
    const bKey = String(b.event_date_start || "9999-12-31");
    return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
  })[0] || {});
const FIRST_OFFLINE_SNAPSHOT_ID = FIRST_OFFLINE_SNAPSHOT_ITEM.id || "hakka_bar:8ec6d516a7e2db3a";
const FIRST_OFFLINE_SNAPSHOT_DATE = FIRST_OFFLINE_SNAPSHOT_ITEM.event_date_start || "2026-07-10";

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
    if (id === "./electronicRelevance") {
      return require("../utils/electronicRelevance");
    }
    if (id === "../data/club_overviews") {
      return bundledClubOverviews;
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
      id: "city-keys-only-hangzhou",
      title: "City keys only",
      city_keys: ["hangzhou"],
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
    {
      id: "oil-jasss-techno",
      title: "JASSS industrial techno showcase",
      city_key: "shenzhen",
      city: ["深圳"],
      venue_name: "OIL",
      venue: ["OIL"],
      event_date_start: "2026-07-04",
      event_date_iso_guess: "2026-07-04",
      event_date_iso_guesses: ["2026-07-04"],
      event_time_text: "22:00 - Late",
      event_time_source: "source_text",
      quality_status: "READY",
      source_action: { url_hash: "6666666666666666" },
    },
    {
      id: "oil-silicon-kure-techno",
      title: "Silicon Kure techno anniversary",
      city_key: "shenzhen",
      city: ["深圳"],
      venue_name: "OIL",
      venue: ["OIL"],
      event_date_start: "2026-07-04",
      event_date_iso_guess: "2026-07-04",
      event_date_iso_guesses: ["2026-07-04"],
      event_time_text: "23:55",
      event_time_source: "source_text",
      quality_status: "READY",
      source_action: { url_hash: "7777777777777777" },
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

const clubOverviewsPayload = {
  schema_version: "club_overviews.v1",
  generated_at: "2026-07-18T15:00:00+08:00",
  as_of_date: "2026-07-18",
  source: "online-test-package",
  club_count: 1,
  overview_count: 1,
  kind_counts: { week: 1 },
  by_club: {
    OIL: [{
      club: "OIL",
      title: "OIL 本周活动一览",
      original_url: "https://mp.weixin.qq.com/s/oil-weekly",
      cover_url: "https://mmbiz.qpic.cn/example/oil-weekly.jpg",
      window_kind: "week",
      window_label: "7.18-7.24",
      window_start: "2026-07-18",
      window_end: "2026-07-24",
    }],
  },
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
        data = { item: currentPayload.items.find((item) => item.id === "exit_shanghai:7abfce849fee404d") };
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
      } else if (pathname.endsWith("/club_overviews.json")) {
        data = clubOverviewsPayload;
      } else {
        options.fail({ errMsg: `unexpected url ${options.url}` });
        return;
      }

      options.success({ statusCode: 200, data });
    },
  };
}

function testCacheKey(prefix, requestPath, data) {
  const stable = {};
  for (const key of Object.keys(data || {}).sort()) {
    if (!String(key || "").startsWith("__") && data[key] !== undefined && data[key] !== null && data[key] !== "") {
      stable[key] = data[key];
    }
  }
  let hash = 2166136261;
  const text = `${requestPath}?${JSON.stringify(stable)}`;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `${prefix}${(hash >>> 0).toString(36)}`;
}

test("July activity hotfix ignores the old June current-feed cache namespace", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-07-04");
  const store = new Map();
  const query = { limit: 1 };
  store.set(testCacheKey("weeklyActivityApiCache:v20260604:", "/api/v1/weekly/current", query), {
    cachedAt: Date.now(),
    payload: {
      generated_at: "2026-06-26T12:00:00+08:00",
      items: [{
        id: "stale-0626",
        title: "Stale June Event",
        city_key: "shanghai",
        event_date_start: "2026-06-26",
        event_date_iso_guess: "2026-06-26",
        quality_status: "READY",
      }],
      page: { total: 1, nextCursor: null },
    },
  });

  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        staticBaseUrl: "",
        publicBaseUrl: "",
        cacheMaxAgeMs: 6 * 60 * 60 * 1000,
        cacheFallbackDelayMs: 0,
        requestTimeoutMs: 50,
        offlineSnapshotFallback: true,
      },
    },
  });
  sandbox.wx = {
    cloud: { callContainer: () => Promise.reject({ errMsg: "cloud.callContainer:fail" }) },
    getStorageSync: (key) => (store.has(key) ? store.get(key) : ""),
    setStorageSync: (key, value) => { store.set(key, value); },
  };

  const result = await requestApi("/api/v1/weekly/current", query);
  assert.equal(result.__fromSnapshot, true);
  assert.notEqual(result.items[0]?.id, "stale-0626");
});

test("default current-feed cache filters stale rows from a broad raw payload", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-07-05");
  const store = new Map();
  const query = { limit: 10, lookbackDays: 0 };
  store.set(testCacheKey("weeklyActivityApiCache:v20260704:", "/api/v1/weekly/current", query), {
    cachedAt: Date.now(),
    payload: {
      generated_at: "2026-07-05T12:00:00+08:00",
      items: [
        {
          id: "stale-0626",
          title: "Stale June Event",
          city_key: "shanghai",
          event_date_start: "2026-06-26",
          event_date_end: "2026-06-26",
          event_date_iso_guess: "2026-06-26",
          quality_status: "READY",
        },
        {
          id: "current-weekend",
          title: "Current Weekend Event",
          city_key: "shanghai",
          event_date_start: "2026-07-05",
          event_date_end: "2026-07-05",
          event_date_iso_guess: "2026-07-05",
          quality_status: "READY",
        },
      ],
      page: { total: 2, nextCursor: null },
    },
  });

  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        staticBaseUrl: "",
        publicBaseUrl: "",
        cacheMaxAgeMs: 6 * 60 * 60 * 1000,
        cacheFallbackDelayMs: 0,
        requestTimeoutMs: 50,
        offlineSnapshotFallback: false,
      },
    },
  });
  sandbox.wx = {
    cloud: { callContainer: () => Promise.reject({ errMsg: "cloud.callContainer:fail" }) },
    getStorageSync: (key) => (store.has(key) ? store.get(key) : ""),
    setStorageSync: (key, value) => { store.set(key, value); },
  };

  const result = await requestApi("/api/v1/weekly/current", query);
  assert.equal(result.__fromCache, true);
  assert.equal(result.items.map((item) => item.id).join(","), "current-weekend");
  assert.equal(result.page.total, 1);
});

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

test("loads club overviews from the online release artifact through requestApi", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/club-overviews");
  assert.equal(result.schema_version, "club_overviews.v1");
  assert.equal(result.source, "online-test-package");
  assert.equal(result.by_club.OIL[0].title, "OIL 本周活动一览");
  assert.notEqual(result.__fromSnapshot, true);
});

test("static current fallback filters by city_keys when city_key is absent", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/current", {
    cityKey: "hangzhou",
    date: "2026-05-09",
    limit: 10,
  });

  assert.deepEqual(Array.from(result.items, (item) => item.id), ["city-keys-only-hangzhou"]);
  assert.equal(result.page.total, 1);
});

test("static current fallback excludes clearly non-electronic activities", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);
  const customCurrent = {
    generated_at: "2026-05-09T01:00:00Z",
    items: [
      {
        id: "pure-cocktail",
        title: "重庆首届鸡尾酒节",
        city_key: "chongqing",
        city_keys: ["chongqing"],
        event_date_iso_guess: "2026-05-09",
        quality_status: "READY",
      },
      {
        id: "standup",
        title: "周六脱口秀开放麦",
        city_key: "chongqing",
        city_keys: ["chongqing"],
        event_date_iso_guess: "2026-05-09",
        quality_status: "READY",
      },
      {
        id: "cocktail-dj-room",
        title: "Cocktail room with DJ Acid",
        city_key: "chongqing",
        city_keys: ["chongqing"],
        event_date_iso_guess: "2026-05-09",
        quality_status: "READY",
        lineup: ["DJ Acid"],
        venue: ["Club Room"],
      },
    ],
  };
  const originalRequest = sandbox.wx.request;
  sandbox.wx.request = (options) => {
    const pathname = new URL(options.url).pathname;
    if (pathname.endsWith("/current.json")) {
      options.success({ statusCode: 200, data: customCurrent });
      return;
    }
    originalRequest(options);
  };

  const result = await requestApi("/api/v1/weekly/current", {
    cityKey: "chongqing",
    date: "2026-05-09",
    limit: 10,
  });

  assert.deepEqual(Array.from(result.items, (item) => item.id), ["cocktail-dj-room"]);
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

test("static fallback does not dedupe same-venue events by shared genre words", async () => {
  const { requestApi, sandbox } = loadApiModule();
  installWechatMock(sandbox);

  const result = await requestApi("/api/v1/weekly/current", {
    cityKey: "shenzhen",
    date: "2026-07-04",
    limit: 10,
  });

  assert.deepEqual(
    Array.from(result.items, (item) => item.id).sort(),
    ["oil-jasss-techno", "oil-silicon-kure-techno"],
  );
  assert.equal(result.page.total, 2);
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

test("offline fallback does not fill the homepage with expired bundled seed rows", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2099-01-01");
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        staticBaseUrl: "",
        publicBaseUrl: "",
        cloudCallTimeoutMs: 5,
        requestTimeoutMs: 25,
        offlineSnapshotFallback: true,
      },
    },
  });
  sandbox.wx = {
    cloud: {
      callContainer() {
        return Promise.reject({ errMsg: "cloud.callContainer:fail Error" });
      },
    },
    getStorageSync() {
      return "";
    },
  };

  const current = await requestApi("/api/v1/weekly/current", { limit: 10 });
  const dates = await requestApi("/api/v1/weekly/dates");

  assert.equal(current.__fromSnapshot, true);
  assert.equal(current.items.length, 0);
  assert.equal(current.page.total, 0);
  assert.equal(dates.__fromSnapshot, true);
  assert.equal(dates.dates.length, 0);
  assert.equal(dates.item_count, 0);
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

test("disaster fallback reads the source URL map exported with the bundled seed", async () => {
  const [sourceHash, sourceUrl] = Object.entries(offlineSnapshotModule.OFFLINE_SOURCE_URLS || {})[0] || [];
  assert.ok(sourceHash && sourceUrl, "bundled disaster seed must carry at least one source URL");

  const { requestApi, sandbox } = loadApiModule();
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        staticBaseUrl: "",
        publicBaseUrl: "",
        cacheMaxAgeMs: 0,
        offlineSnapshotFallback: true,
      },
    },
  });
  sandbox.wx = {
    cloud: { callContainer: () => Promise.reject({ errMsg: "cloud.callContainer:fail" }) },
    getStorageSync: () => "",
    setStorageSync() {},
  };

  const result = await requestApi(`/api/v1/weekly/source/${sourceHash}`);
  assert.equal(result.__fromSnapshot, true);
  assert.equal(result.url, sourceUrl);
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
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-05-09");
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

test("cached default current feed drops rows that are already in the past", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-07-02");
  const storage = {};
  let mode = "online";
  const stalePayload = {
    schemaVersion: "weekly_activity_api.current_response.v1",
    generatedAt: "2026-06-26T12:00:00+08:00",
    items: [
      {
        id: "past-0626",
        title: "past techno",
        city_key: "shanghai",
        event_date_start: "2026-06-26",
        event_date_iso_guess: "2026-06-26",
        quality_status: "READY",
      },
      {
        id: "future-0703",
        title: "future techno",
        city_key: "shanghai",
        event_date_start: "2026-07-03",
        event_date_iso_guess: "2026-07-03",
        quality_status: "READY",
      },
    ],
    page: { total: 2, nextCursor: null },
  };
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
        cacheMaxAgeMs: 6 * 60 * 60 * 1000,
        requestTimeoutMs: 80,
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
      options.success({ statusCode: 200, data: stalePayload });
    },
  };

  const query = { limit: 10, lookbackDays: 0 };
  const online = await requestApi("/api/v1/weekly/current", query);
  assert.equal(online.items.length, 2);

  mode = "vpn-hang";
  const cached = await requestApi("/api/v1/weekly/current", query);
  assert.equal(cached.__fromCache, true);
  assert.equal(cached.items.map((item) => item.id).join(","), "future-0703");
  assert.equal(cached.page.total, 1);
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

test("live-only current request bypasses stored cache and bundled snapshot", async () => {
  const { requestApi, sandbox } = loadApiModule();
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "",
        staticBaseUrl: "",
        offlineSnapshotFallback: true,
        cacheFallbackDelayMs: 0,
        cloudClient: {
          callContainer() {
            return Promise.reject({ error: { code: "NETWORK_DOWN" } });
          },
        },
      },
    },
  });
  sandbox.wx = {
    getStorageSync() {
      return {
        cachedAt: Date.now(),
        payload: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          generatedAt: "2026-06-26T12:00:00+08:00",
          items: [{ id: "cached-old-row", event_date_start: "2026-06-26" }],
          page: { total: 1, nextCursor: null },
        },
      };
    },
    setStorageSync() {},
  };

  await assert.rejects(
    () => requestApi("/api/v1/weekly/current", { limit: 1, __skipCache: true, __liveOnly: true }),
    (error) => error?.error?.code === "NETWORK_DOWN",
  );
});

test("request control flags are not sent to the public API query", async () => {
  const { requestApi, sandbox } = loadApiModule();
  let requestedUrl = "";
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        publicBaseUrl: "https://weekly-api.example.test",
        staticBaseUrl: "",
        cloudCallTimeoutMs: 5000,
        publicFallbackDelayMs: 0,
        publicRequestTimeoutMs: 80,
        requestTimeoutMs: 80,
        offlineSnapshotFallback: false,
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
      requestedUrl = options.url;
      options.success({
        statusCode: 200,
        data: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          generatedAt: "2026-07-02T14:15:36+08:00",
          items: [currentPayload.items[0]],
          page: { total: 1, nextCursor: null },
        },
      });
      return { abort() {} };
    },
  };

  const result = await requestApi("/api/v1/weekly/current", { limit: 1, __skipCache: true, __liveOnly: true });
  assert.equal(result.items[0].id, "ready-shanghai");
  assert.equal(requestedUrl.includes("__skipCache"), false);
  assert.equal(requestedUrl.includes("__liveOnly"), false);
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
  assert.ok(Date.now() - startedAt < 220, "bundled snapshot should win before long network timeouts");
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

test("fast bundled snapshot does not beat a healthy public current feed", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-07-02");
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
      setTimeout(() => options.success({
        statusCode: 200,
        data: {
          schemaVersion: "weekly_activity_api.current_response.v1",
          items: [{
            ...currentPayload.items[0],
            id: "public-latest",
            title: "public latest techno",
            event_date_start: "2026-07-02",
            event_date_iso_guess: "2026-07-02",
          }],
          page: { total: 1, nextCursor: null },
        },
      }), 35);
      return {
        abort() {
          publicAbortCount += 1;
        },
      };
    },
  };

  const result = await requestApi("/api/v1/weekly/current", { limit: 1, lookbackDays: 0 });

  assert.equal(result.__fromSnapshot, undefined);
  assert.equal(result.items[0].id, "public-latest");
  assert.equal(publicRequestCount, 1);
  assert.equal(publicAbortCount, 0);
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
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  __setTodayForTests("2026-05-09");
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

test("offline fallback prefers the persisted last-good package over the baked seed", async () => {
  const { requestApi, sandbox } = loadApiModule();
  // Map-backed storage so writeCachedResponse persists between the two phases.
  const store = new Map();
  const cloud = {
    env: "test-env",
    service: "weekly-api",
    useMock: false,
    staticBaseUrl: "https://example.test/weekly/releases/persisted-mirror",
    cacheMaxAgeMs: 0, // disable the maxAge cache so ONLY the persisted mirror can supply offline data
  };
  sandbox.getApp = () => ({ globalData: { cloud } });
  sandbox.wx = {
    cloud: { callContainer: () => Promise.reject({ errMsg: "cloud.callContainer:fail" }) },
    getStorageSync: (key) => (store.has(key) ? store.get(key) : ""),
    setStorageSync: (key, value) => { store.set(key, value); },
    request: (options) => {
      const pathname = new URL(options.url).pathname;
      if (pathname.endsWith("/current.json")) {
        options.success({ statusCode: 200, data: currentPayload });
      } else {
        options.fail({ errMsg: "offline" });
      }
    },
  };

  const query = { cityKey: "shanghai", date: "2026-05-09", limit: 10 };

  // Phase 1 (online): container fails, static current.json succeeds -> persisted.
  const online = await requestApi("/api/v1/weekly/current", query);
  assert.equal(online.items[0].id, "ready-shanghai");
  assert.notEqual(online.__fromCache, true); // fresh from static, not cache

  // Phase 2 (fully offline): break static too. Must serve the persisted mirror
  // of the last-good package, NOT the baked OFFLINE_SNAPSHOT (whose ids differ).
  sandbox.wx.request = (options) => options.fail({ errMsg: "offline" });
  const offline = await requestApi("/api/v1/weekly/current", query);
  assert.equal(offline.items[0].id, "ready-shanghai");
  assert.equal(offline.__fromCache, true); // came from persisted mirror
  assert.notEqual(offline.__fromSnapshot, true); // did NOT fall through to baked seed
});

test("offline fallback uses the baked seed only when nothing was ever persisted", async () => {
  const { __setTodayForTests, requestApi, sandbox } = loadApiModule();
  // Activity releases no longer rewrite the bundled seed. Pin the clock to
  // the seed's own window so this test verifies fallback routing instead of
  // becoming a wall-clock expiry test weeks after the mini-program release.
  __setTodayForTests(FIRST_OFFLINE_SNAPSHOT_DATE);
  const store = new Map();
  const cloud = {
    env: "test-env",
    service: "weekly-api",
    useMock: false,
    staticBaseUrl: "https://example.test/weekly/releases/no-mirror",
    cacheMaxAgeMs: 0,
  };
  sandbox.getApp = () => ({ globalData: { cloud } });
  sandbox.wx = {
    cloud: { callContainer: () => Promise.reject({ errMsg: "cloud.callContainer:fail" }) },
    getStorageSync: (key) => (store.has(key) ? store.get(key) : ""),
    setStorageSync: (key, value) => { store.set(key, value); },
    request: (options) => options.fail({ errMsg: "offline" }), // never reached the network
  };

  const result = await requestApi("/api/v1/weekly/current", { limit: 50 });
  // No persisted mirror -> baked OFFLINE_SNAPSHOT seed.
  assert.equal(result.__fromSnapshot, true);
  assert.ok(result.items.length > 0);
});

test("club overview offline fallback prefers last-good online data over the bundled seed", async () => {
  const { requestApi, sandbox } = loadApiModule();
  const store = new Map();
  const cloud = {
    env: "test-env",
    service: "weekly-api",
    useMock: false,
    staticBaseUrl: "https://example.test/weekly/releases/club-overviews-current",
    cacheMaxAgeMs: 0,
  };
  sandbox.getApp = () => ({ globalData: { cloud } });
  sandbox.wx = {
    cloud: { callContainer: () => Promise.reject({ errMsg: "cloud.callContainer:fail" }) },
    getStorageSync: (key) => (store.has(key) ? store.get(key) : ""),
    setStorageSync: (key, value) => { store.set(key, value); },
    request(options) {
      options.success({ statusCode: 200, data: clubOverviewsPayload });
    },
  };

  const online = await requestApi("/api/v1/weekly/club-overviews");
  assert.equal(online.source, "online-test-package");
  assert.notEqual(online.__fromCache, true);

  sandbox.wx.request = (options) => options.fail({ errMsg: "offline" });
  const offline = await requestApi("/api/v1/weekly/club-overviews");
  assert.equal(offline.source, "online-test-package");
  assert.equal(offline.__fromCache, true);
  assert.notEqual(offline.__fromSnapshot, true);
});

test("club overview bundled seed is only used on a first-install offline path", async () => {
  const { requestApi, sandbox } = loadApiModule();
  sandbox.getApp = () => ({
    globalData: {
      cloud: {
        env: "test-env",
        service: "weekly-api",
        useMock: false,
        staticBaseUrl: "",
        publicBaseUrl: "",
        cacheMaxAgeMs: 0,
        offlineSnapshotFallback: true,
      },
    },
  });
  sandbox.wx = {
    cloud: { callContainer: () => Promise.reject({ errMsg: "cloud.callContainer:fail" }) },
    getStorageSync: () => "",
    setStorageSync() {},
  };

  const result = await requestApi("/api/v1/weekly/club-overviews");
  assert.equal(result.__fromSnapshot, true);
  assert.equal(result.schema_version, bundledClubOverviews.schema_version);
  assert.deepEqual(Object.keys(result.by_club), Object.keys(bundledClubOverviews.by_club));
});
