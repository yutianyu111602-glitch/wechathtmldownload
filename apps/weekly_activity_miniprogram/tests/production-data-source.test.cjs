const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const appJs = fs.readFileSync(path.resolve(__dirname, "../app.js"), "utf8");
const appJson = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../app.json"), "utf8"));
const indexJs = fs.readFileSync(path.resolve(__dirname, "../pages/index/index.js"), "utf8");
const apiJs = fs.readFileSync(path.resolve(__dirname, "../utils/api.js"), "utf8");
const cacheJs = fs.readFileSync(path.resolve(__dirname, "../utils/api/cache.js"), "utf8");
const currentReleaseDir = path.resolve(
  process.env.HUAIDJ_WEEKLY_CURRENT_RELEASE_DIR
    || path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/current_release"),
);

async function fetchAllStrictCurrentItems(store, options = {}) {
  const items = [];
  let cursor = 0;
  for (let pageIndex = 0; pageIndex < 20; pageIndex += 1) {
    const page = await store.getCurrent({
      lookbackDays: 0,
      limit: 100,
      cursor,
      ...options,
    });
    items.push(...(page.items || []));
    const nextCursor = page.page && page.page.nextCursor;
    if (nextCursor === null || nextCursor === undefined || nextCursor === "") break;
    const parsed = Number(nextCursor);
    if (!Number.isFinite(parsed) || parsed <= cursor) break;
    cursor = parsed;
  }
  return items;
}

function numericConfig(name) {
  const match = appJs.match(new RegExp(`${name}:\\s*(-?\\d+)`));
  assert.ok(match, `missing ${name}`);
  return Number(match[1]);
}

function itemDate(item) {
  return item.event_date_start || item.eventDateStart || item.event_date || item.eventDate || item.date || item.event_date_iso_guess || "";
}

function eventEndDate(item) {
  return item.event_date_end || item.eventDateEnd || item.event_date_start || item.eventDateStart || item.event_date || item.eventDate || item.date || "";
}

function stringValue(item, key) {
  return String((item && item[key]) || "").trim();
}

function isAggregateChild(item) {
  return Boolean(item && item.aggregation_child === true)
    || String((item && (item.id || item.event_id)) || "").startsWith("agg-child-");
}

test("production config keeps offline fallback without letting snapshots race the current feed", () => {
  const publicFallbackDelayMs = numericConfig("publicFallbackDelayMs");
  const publicRequestTimeoutMs = numericConfig("publicRequestTimeoutMs");
  const cacheFallbackDelayMs = numericConfig("cacheFallbackDelayMs");
  const offlineSnapshotFallbackDelayMs = numericConfig("offlineSnapshotFallbackDelayMs");

  assert.match(appJs, /offlineSnapshotFallback:\s*true/);
  assert.match(appJs, /fastOfflineSnapshotFallback:\s*false/);
  assert.ok(offlineSnapshotFallbackDelayMs < 0, "snapshot delay must stay disabled for the online current feed");
  assert.ok(publicRequestTimeoutMs >= 3000, "public request timeout must be >= 3000ms for reliability");
  assert.ok(
    cacheFallbackDelayMs > publicFallbackDelayMs,
    "cache fallback must wait until the public API path has had a chance to return",
  );
  assert.match(apiJs, /weeklyActivityApiCache:v20260719-visibility-v2:/);
  assert.match(cacheJs, /weeklyActivityApiCache:v20260719-visibility-v2:/);
  assert.doesNotMatch(apiJs, /allowStaleWhenEmpty:\s*true/);
});

test("home feed uses all current items unless an explicit date mode is selected", () => {
  assert.match(indexJs, /const currentFetchOptions = \{[\s\S]*cityKey:\s*""[\s\S]*date:\s*""[\s\S]*lookbackDays:\s*0/);
  assert.match(indexJs, /allCurrentDateSelection/);
  assert.match(indexJs, /weekendDateSelection/);
  assert.match(indexJs, /filterItemsByDateSelection/);
  assert.match(indexJs, /const posterPoolSourceItems = displayItems/);
  assert.doesNotMatch(indexJs, /applyDefaultHomeDateWindow/);
  assert.doesNotMatch(indexJs, /lookbackDays:\s*45/);
});

test("home city filters accept API facets only when they match the visible date scope", () => {
  assert.match(indexJs, /function buildCityFiltersFromIndex\(payload, lang, allCitiesLabel\)/);
  assert.match(indexJs, /cityFacetPayloadMatchesItems\(citiesResult\.value, cityFilterSourceItems\)/);
  assert.match(indexJs, /const cityFilters = cityIndexFilters \|\| buildCityFiltersFallback\(cityFilterSourceItems, lang, this\.data\.t\.allCities\)/);
  assert.match(indexJs, /entry\?\.count \?\? entry\?\.item_count \?\? entry\?\.eventCount/);
});

test("current city facets exactly match the strict home feed while package scope preserves history", async () => {
  const { WeeklyActivityDataStore } = await import("../../../services/weekly_activity_cloudrun/src/dataStore.mjs");
  const store = new WeeklyActivityDataStore({
    baseDir: currentReleaseDir,
    today: "2026-07-06",
  });
  const strictItems = await fetchAllStrictCurrentItems(store);
  const cityIndex = await store.getCities();
  const cityIndexCounts = new Map((cityIndex.cities || []).map((entry) => [
    String(entry.city_key || entry.key || "").trim(),
    Number(entry.count ?? entry.item_count ?? entry.eventCount ?? 0),
  ]).filter(([key, count]) => key && Number.isFinite(count) && count > 0));
  const strictCounts = new Map();
  for (const item of strictItems) {
    const key = String(item.city_key || "").trim();
    if (!key) continue;
    strictCounts.set(key, (strictCounts.get(key) || 0) + 1);
  }
  assert.ok(strictItems.length > 0, "strict home feed must have current/future rows");
  assert.equal(cityIndex.scope, "current");
  assert.equal(cityIndex.item_count, strictItems.length);
  assert.deepEqual(cityIndexCounts, strictCounts);

  const packageIndex = await store.getCities({ scope: "package" });
  assert.equal(packageIndex.scope, "package");
  assert.ok(packageIndex.item_count >= cityIndex.item_count, "package scope must retain current rows and any history");
});

test("approved fuzzy location build declares getFuzzyLocation and applies city priority on the home feed", () => {
  assert.deepEqual(appJson.requiredPrivateInfos, ["getFuzzyLocation"]);
  assert.equal(appJson.permission["scope.userFuzzyLocation"].desc, "用于优先推荐你所在城市的活动");
  assert.equal(appJson.permission["scope.userLocation"], undefined);
  assert.match(appJs, /wx\.getFuzzyLocation/);
  assert.doesNotMatch(appJs, /wx\.getLocation/);
  assert.match(appJs, /nearestCityKey/);
  assert.match(appJs, /weeklyActivityUserLocCity/);
  assert.match(appJs, /onLocationReady/);
  assert.match(appJs, /requestLocationCity\(\)/);
  assert.match(indexJs, /const LOCATION_CITY_KEY = "weeklyActivityUserLocCity"/);
  assert.match(indexJs, /const LOCATION_READY_WAIT_MS = 1500/);
  assert.match(indexJs, /readLocatedCityKey\(\)[\s\S]*userLocationCityKey[\s\S]*readStoredString\(LOCATION_CITY_KEY\)/);
  assert.match(indexJs, /const PREFERRED_CITY_KEY = "weeklyActivityPreferredCity"/);
  assert.match(indexJs, /readLocalCityKey\(\)[\s\S]*readLocatedCityKey\(\)[\s\S]*globalData\.preferredCityKey[\s\S]*readStoredString\(PREFERRED_CITY_KEY\)/);
  assert.match(indexJs, /waitForLocationCityBeforeInitialLoad\(selectedCity\)[\s\S]*\.then\(\(\) => this\.loadData\(\)\)/);
  assert.match(indexJs, /app\.requestLocationCity\(\)/);
  assert.match(indexJs, /applyLocatedCityKey\(key\)/);
  assert.match(indexJs, /refreshViewItems\(\)/);
  assert.match(indexJs, /globalData\.preferredCityKey/);
  assert.doesNotMatch(indexJs, /globalData\.userLocationCityKey\s*=\s*key/);
});

test("app launch stores located city separately from manual preferred city", async () => {
  const appModulePath = path.resolve(__dirname, "../app.js");
  const originalWx = global.wx;
  const originalApp = global.App;
  const storage = {
    weeklyActivityLang: "zh",
    weeklyActivityPreferredCity: "shanghai",
  };
  const getFuzzyLocationCalls = [];
  let appConfig = null;
  global.App = (config) => {
    appConfig = config;
  };
  global.wx = {
    getStorageSync(key) {
      return storage[key] || "";
    },
    setStorageSync(key, value) {
      storage[key] = value;
    },
    setNavigationBarTitle() {},
    setTabBarItem() {},
    getFuzzyLocation(options) {
      getFuzzyLocationCalls.push(options);
      options.success({ latitude: 30.572, longitude: 104.066 });
    },
  };
  try {
    delete require.cache[require.resolve(appModulePath)];
    require(appModulePath);
    let readyKey = "";
    appConfig.onLocationReady((key) => {
      readyKey = key;
    });
    appConfig.onLaunch();
    assert.equal(appConfig.globalData.preferredCityKey, "shanghai");
    assert.equal(appConfig.globalData.userLocationCityKey, "chengdu");
    assert.equal(storage.weeklyActivityUserLocCity, "chengdu");
    assert.equal(readyKey, "chengdu");
    assert.equal(getFuzzyLocationCalls.length, 1);
    assert.equal(getFuzzyLocationCalls[0].type, "gcj02");
    assert.equal(await appConfig.requestLocationCity(), "chengdu");
    assert.equal(getFuzzyLocationCalls.length, 1);
  } finally {
    delete require.cache[require.resolve(appModulePath)];
    global.wx = originalWx;
    global.App = originalApp;
  }
});

test("location request promise is reused while permission is pending", async () => {
  const appModulePath = path.resolve(__dirname, "../app.js");
  const originalWx = global.wx;
  const originalApp = global.App;
  const storage = { weeklyActivityLang: "zh" };
  const getFuzzyLocationCalls = [];
  let appConfig = null;
  global.App = (config) => {
    appConfig = config;
  };
  global.wx = {
    getStorageSync(key) {
      return storage[key] || "";
    },
    setStorageSync(key, value) {
      storage[key] = value;
    },
    setNavigationBarTitle() {},
    setTabBarItem() {},
    getFuzzyLocation(options) {
      getFuzzyLocationCalls.push(options);
    },
  };
  try {
    delete require.cache[require.resolve(appModulePath)];
    require(appModulePath);
    appConfig.onLaunch();
    const first = appConfig.requestLocationCity();
    const second = appConfig.requestLocationCity();
    assert.equal(first, second);
    assert.equal(getFuzzyLocationCalls.length, 1);
    getFuzzyLocationCalls[0].success({ latitude: 31.228, longitude: 121.474 });
    assert.equal(await first, "shanghai");
    assert.equal(appConfig.globalData.userLocationCityKey, "shanghai");
    assert.equal(storage.weeklyActivityUserLocCity, "shanghai");
  } finally {
    delete require.cache[require.resolve(appModulePath)];
    global.wx = originalWx;
    global.App = originalApp;
  }
});

test("current release package uses Sanji daily current window with CloudBase poster file IDs", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(currentReleaseDir, "manifest.json"), "utf8"));
  const current = JSON.parse(fs.readFileSync(path.join(currentReleaseDir, "current.json"), "utf8"));
  const items = Array.isArray(current) ? current : current.items || current.events || [];
  const sanjiContract = manifest.sanji_source_contract || {};
  const itemIds = new Set(items.map((item) => String(item.id || item.event_id || "")));
  const dates = items.map(itemDate).filter(Boolean).sort();
  const forbiddenDates = new Set(["2026-05-29"]);
  const outsideWindowItems = items.filter((item) => {
    const start = itemDate(item);
    const end = eventEndDate(item);
    return end < manifest.window_start || start > manifest.window_end;
  });
  const coverKeys = ["coverUrl", "cover_url", "coverImageUrl", "cover_image_url", "poster", "posterUrl", "poster_url", "raw_cover_url"];
  const fileIdKeys = ["poster_file_id", "posterFileId", "cloudFileId", "cloud_file_id", "cover_file_id", "coverFileId"];
  const posterStorageKeys = ["poster_storage", "posterStorage"];
  const runtimePosterStateKeys = [
    "posterTempUrl",
    "poster_temp_url",
    "tempFileURL",
    "tempFileUrl",
    "temp_file_url",
    "posterDownloadFallbackTried",
    "posterFileIdFallbackTried",
    "posterLoadFailed",
  ];
  const aggregateChildren = items.filter(isAggregateChild);
  const itemsWithCloudFileId = items.filter((item) => (
    fileIdKeys.some((key) => /^cloud:\/\/[^/]+\/weekly-posters\/\d{8}\//i.test(stringValue(item, key)))
  ));
  const itemsWithCloudbaseStorage = items.filter((item) => (
    posterStorageKeys.some((key) => /^cloudbase$/i.test(stringValue(item, key)))
  ));
  const publicPosterItems = items.filter((item) => (
    [...coverKeys, ...fileIdKeys].some((key) => /(?:mmbiz|mmecoa)\.qpic\.cn|mp\.weixin\.qq\.com|https?:\/\/|\/api\/v1\/weekly\/poster\/|wxfile:\/\/|blob:/i.test(stringValue(item, key)))
  ));
  const runtimePosterStateItems = items.filter((item) => (
    runtimePosterStateKeys.some((key) => Object.prototype.hasOwnProperty.call(item, key))
  ));
  const aggregateSourceResidue = aggregateChildren.filter((item) => {
    const sourceAction = item.source_action && typeof item.source_action === "object" ? item.source_action : {};
    const sourceArticle = item.source_article && typeof item.source_article === "object" ? item.source_article : {};
    return sourceAction.available === true
      || stringValue(sourceAction, "url_hash")
      || stringValue(sourceArticle, "url_hash")
      || stringValue(item, "sourceHash")
      || stringValue(item, "source_hash");
  });

  assert.ok(Date.parse(manifest.generated_at) >= Date.parse("2026-06-21T00:00:00+08:00"));
  assert.ok(
    manifest.window_start >= "2026-06-21",
    `expected refreshed package window_start >= 2026-06-21, got ${manifest.window_start}`,
  );
  assert.ok(
    Date.parse(manifest.window_end) - Date.parse(manifest.window_start) >= 13 * 86400000,
    `expected window to span >= 14 days, got ${manifest.window_start}..${manifest.window_end}`,
  );
  const sourcePolicyRepair = manifest.source_policy_title_dedupe_repair || {};
  const sourcePolicyMin = Number(sourcePolicyRepair.final_item_count || 0);
  const incrementalMerge = manifest.incremental_merge || {};
  const mergedCount = Number(incrementalMerge.merged_count || 0);
  const hasWindowRepair = Boolean(manifest.emergency_window_repair);
  const expectedMinItems = hasWindowRepair ? 100 : (sourcePolicyMin > 0 ? sourcePolicyMin : 50);
  assert.ok(
    manifest.item_count >= expectedMinItems,
    `expected >= ${expectedMinItems} current-window items, got ${manifest.item_count}`,
  );
  if (mergedCount > 0) {
    assert.ok(
      mergedCount >= manifest.item_count,
      `incremental merged_count ${mergedCount} must be >= final item_count ${manifest.item_count}`,
    );
    if (!hasWindowRepair && sourcePolicyMin > 0) {
      assert.equal(Number(incrementalMerge.base_count || 0), sourcePolicyMin);
    }
  } else if (!hasWindowRepair && sourcePolicyMin > 0) {
    assert.equal(manifest.item_count, sourcePolicyMin);
  }
  assert.equal(items.length, manifest.item_count);
  assert.equal(manifest.source_mode, "sanji_desktop_rss");
  assert.match(String(manifest.source_queue_path || ""), /sanji_source_snapshot[\\/]latest_queue\.jsonl$/);
  assert.equal(manifest.direct_rss_feed_fetch, false);
  assert.equal(manifest.sanji_db_snapshot_export, true);
  assert.equal(manifest.sanji_desktop_refresh_invoked, true);
  assert.equal(sanjiContract.direct_rss_feed_fetch, false);
  assert.equal(sanjiContract.sanji_db_snapshot_export, true);
  assert.equal(sanjiContract.sanji_desktop_refresh_invoked, true);
  assert.match(String(sanjiContract.snapshot_db_path || manifest.sanji_snapshot_db_path || ""), /sanji[\\/]sanji\.db$/i);
  assert.ok(dates.includes(manifest.window_start));
  assert.equal([...forbiddenDates].some((date) => dates.includes(date)), false);
  assert.equal(itemIds.has("loopy_club:2eee2bb226cf7550"), false);
  assert.equal(itemIds.has("abyss_shanghai:ce6995b838e0fa6a"), false);
  assert.equal(itemIds.has("with_bar:9295cbeb1714fba5"), false);
  assert.equal(itemIds.has("agg-child-9b66fa225a0606d8"), false);
  assert.equal(itemIds.has("agg-child-4031b3921f885e8e"), false);
  assert.equal(itemIds.has("agg-child-13e3c9e711931629"), false);
  assert.equal(itemIds.has("pools:fcd7568608a510a4"), false);
  assert.equal(itemIds.has("dada_kunming:01a5754ae510df68"), false);
  assert.equal(itemIds.has("agg-child-d898c5f155dc7b6a"), false);
  assert.equal(items.some((item) => /dj\s*love/i.test(String(item.title || item.title_display || ""))), false);
  assert.equal(outsideWindowItems.length, 0);
  assert.equal(aggregateChildren.length, 0);
  assert.equal(aggregateSourceResidue.length, 0);
  const nonAggCount = items.filter((i) => !String(i.id || "").startsWith("agg-child")).length;
  assert.equal(itemsWithCloudFileId.length, nonAggCount, `expected all non-aggregate items with cloud file ID, got ${itemsWithCloudFileId.length}/${nonAggCount}`);
  assert.equal(itemsWithCloudbaseStorage.length, nonAggCount, `expected all non-aggregate items with cloudbase storage, got ${itemsWithCloudbaseStorage.length}/${nonAggCount}`);
  assert.equal(publicPosterItems.length, 0, `expected zero public poster items, got ${publicPosterItems.length}`);
  assert.equal(runtimePosterStateItems.length, 0);
});
