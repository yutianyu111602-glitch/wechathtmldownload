const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const homeFilters = require("../services/homeFilters");

function createClock(initialIso) {
  let nowMs = new Date(initialIso).getTime();
  class ClockDate extends Date {
    constructor(...args) {
      super(...(args.length ? args : [nowMs]));
    }

    static now() {
      return nowMs;
    }
  }
  return {
    Date: ClockDate,
    set(iso) {
      nowMs = new Date(iso).getTime();
    },
  };
}

function loadHomePage(clock) {
  const filename = path.join(root, "pages", "index", "index.js");
  const code = fs.readFileSync(filename, "utf8");
  const storage = new Map();
  const timers = [];
  let page = null;

  function scheduleTimer(callback, ms) {
    const timer = { callback, ms: Number(ms) || 0, cancelled: false };
    timers.push(timer);
    return timer;
  }

  function cancelTimer(timer) {
    if (timer && typeof timer === "object") timer.cancelled = true;
  }

  const labels = {
    allCities: "全部城市",
    allDates: "全部日期",
    china: "全国",
    heroTitle: "活动查询",
    loadingStart: "连接活动源",
    loadingStartHint: "连接中",
    loadingEvents: "读取活动",
    loadingClean: "整理活动",
    loadingCleanHint: "整理中",
    loadingReady: "加载完成",
    loadingRefreshing: "刷新活动包",
    loadingRefreshingHint: "刷新中",
    loadingRetrying: "重试中",
    loadingRetryHint: "稍后重试",
    loadingCachedNotice: "缓存",
    loadingOfflineNotice: "离线",
    loadingFallbackHint: "筛选回退",
    loadFailed: "加载失败",
    loadFailedHint: "请重试",
    retryBusy: "加载中",
  };

  const sandbox = {
    Date: clock.Date,
    Promise,
    clearTimeout: cancelTimer,
    console: { ...console, error() {} },
    getApp() {
      return { globalData: {} };
    },
    Page(config) {
      page = config;
    },
    require(request) {
      if (request.endsWith("/api")) {
        return {
          fetchAllCurrentResponse: async () => ({ items: [], total: 0 }),
          requestApi: async (endpoint) => {
            if (endpoint.endsWith("/manifest")) return {};
            if (endpoint.endsWith("/cities")) return { scope: "current", item_count: 0, cities: [] };
            if (endpoint.endsWith("/dates")) return { scope: "current", item_count: 0, dates: [] };
            throw new Error(`unexpected endpoint ${endpoint}`);
          },
        };
      }
      if (request.endsWith("/format")) return { compactItem: (item) => item, dedupeItems: (items) => items };
      if (request.endsWith("/facetContract")) return { facetPayloadMatchesVisibleSet: () => false };
      if (request.endsWith("/generationContract")) return { currentFeedBehindManifest: () => false };
      if (request.endsWith("/haptics")) {
        return {
          HAPTIC: { refreshInterval: 1, tabInterval: 1, poster: {}, feed: {} },
          createScrollHapticState: () => ({}),
          nextScrollHaptic: () => ({ shouldPulse: false }),
          vibrateLight() {},
        };
      }
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome() {},
          compactDate: (value) => value,
          dateDisplay: (value) => value,
          localizeItems: (items) => items,
          normalizeLang: (value) => (value === "en" ? "en" : "zh"),
          text: () => labels,
          translateCity: (value, _lang, key) => value || key || "全国",
          weekdayLabel: () => "",
        };
      }
      if (request.endsWith("/posterPool")) return { buildPosterPool: () => [] };
      if (request.endsWith("/sourceAction")) return { openSourceByHash() {} };
      if (request.endsWith("/listDisplay")) return { withListLocationLabels: (items) => items };
      if (request.endsWith("/datePreview")) {
        return {
          filterItemsByPreviewRange: (items) => items,
          itemDateBounds: () => ({ start: "", end: "" }),
          itemMatchesDateKey: () => false,
          normalizeRange: (value) => value || "all",
        };
      }
      if (request.endsWith("/homeFilters")) return homeFilters;
      if (request.endsWith("/businessDate")) return require("../utils/businessDate");
      if (request.endsWith("/genreFilter")) return { filterItemsByElectronic: (items) => items };
      if (request.endsWith("/share")) {
        return {
          buildIndexShare: () => ({}),
          buildIndexTimeline: () => ({}),
          enableShareMenu() {},
        };
      }
      if (request.endsWith("/cloudPosterUrls")) {
        return {
          posterFallbackState: (item) => item,
          posterImageErrorFallback: async () => null,
          resolvePosterUrlsForItems: async (items) => items,
        };
      }
      throw new Error(`unexpected require ${request}`);
    },
    setTimeout: scheduleTimer,
    wx: {
      getStorageSync(key) { return storage.get(key) || ""; },
      removeStorageSync(key) { storage.delete(key); },
      setStorageSync(key, value) { storage.set(key, value); },
      showToast() {},
    },
  };

  vm.runInNewContext(code, sandbox, { filename });
  page.setData = function setData(update) {
    this.data = { ...this.data, ...(update || {}) };
  };
  page.fetchAllCurrentItems = async () => ({
    items: [],
    total: 0,
    fromCache: false,
    fromSnapshot: false,
    generatedAt: "",
  });
  page.__timers = timers;
  return page;
}

async function establishSuccessfulLoad(page, dateSelection) {
  if (dateSelection) {
    page.setData({
      selectedDate: dateSelection.exactDate,
      dateMode: dateSelection.mode,
      selectedDateStart: dateSelection.startKey,
      selectedDateEnd: dateSelection.endKey,
    });
  }
  await page.loadData(dateSelection ? { dateSelection } : {});
}

test("home onShow refreshes the current feed when the Shanghai business day advances", async () => {
  const clock = createClock("2026-07-19T14:00:00+08:00");
  const page = loadHomePage(clock);
  await establishSuccessfulLoad(page);

  const calls = [];
  page.loadData = (options) => {
    calls.push(options || {});
    return Promise.resolve();
  };
  clock.set("2026-07-20T07:01:00+08:00");

  page.onShow();

  assert.equal(calls.length, 1);
  assert.equal(calls[0].skipCache, true);
  assert.deepEqual(calls[0].dateSelection, homeFilters.allCurrentDateSelection());
});

test("home onShow rebases a weekend selection after its Shanghai business week changes", async () => {
  const clock = createClock("2026-07-19T14:00:00+08:00");
  const page = loadHomePage(clock);
  const thisWeekend = homeFilters.weekendDateSelection(0, new clock.Date());
  await establishSuccessfulLoad(page, thisWeekend);

  const calls = [];
  page.loadData = (options) => {
    calls.push(options || {});
    return Promise.resolve();
  };
  clock.set("2026-07-20T07:01:00+08:00");

  page.onShow();

  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].dateSelection, {
    mode: "this_weekend",
    exactDate: "",
    startKey: "2026-07-24",
    endKey: "2026-07-26",
  });
  assert.equal(page.data.selectedDateStart, "2026-07-24");
  assert.equal(page.data.selectedDateEnd, "2026-07-26");
});

test("a failed background refresh queues the next bounded retry inside the 120 second throttle window", async () => {
  const clock = createClock("2026-07-19T14:00:00+08:00");
  const page = loadHomePage(clock);
  page.fetchAllCurrentItems = async () => {
    throw new Error("temporary upstream failure");
  };
  page.backgroundRefreshAttempts = 1;
  page.lastBackgroundRefreshAt = clock.Date.now();

  await page.loadData({ backgroundRefresh: true });

  assert.equal(page.backgroundRefreshAttempts, 2);
  assert.ok(page.backgroundRefreshTimer, "the second bounded retry must be queued");
  assert.equal(page.backgroundRefreshTimer.ms, 2600);
});

test("a load that crosses the 07:00 boundary keeps its request-time lifecycle identity", async () => {
  const clock = createClock("2026-07-20T06:59:00+08:00");
  const page = loadHomePage(clock);
  const oldWeekend = homeFilters.weekendDateSelection(0, new clock.Date());
  page.setData({
    selectedDate: oldWeekend.exactDate,
    dateMode: oldWeekend.mode,
    selectedDateStart: oldWeekend.startKey,
    selectedDateEnd: oldWeekend.endKey,
  });
  page.fetchAllCurrentItems = async () => {
    clock.set("2026-07-20T07:01:00+08:00");
    return { items: [], total: 0, fromCache: false, fromSnapshot: false, generatedAt: "" };
  };
  await page.loadData({ dateSelection: oldWeekend });

  const calls = [];
  page.loadData = (options) => {
    calls.push(options || {});
    return Promise.resolve();
  };
  page.onShow();

  assert.equal(calls.length, 1);
  assert.equal(calls[0].dateSelection.startKey, "2026-07-24");
  assert.equal(calls[0].dateSelection.endKey, "2026-07-26");
});

test("an in-flight load cannot overwrite a newer queued weekend selection", async () => {
  const clock = createClock("2026-07-19T14:00:00+08:00");
  const page = loadHomePage(clock);
  let releaseCurrent;
  page.fetchAllCurrentItems = () => new Promise((resolve) => { releaseCurrent = resolve; });

  const oldLoad = page.loadData();
  const weekend = homeFilters.weekendDateSelection(0, new clock.Date());
  page.setData({
    selectedDate: weekend.exactDate,
    dateMode: weekend.mode,
    selectedDateStart: weekend.startKey,
    selectedDateEnd: weekend.endKey,
  });
  await page.loadData({ dateSelection: weekend });

  releaseCurrent({ items: [], total: 0, fromCache: false, fromSnapshot: false, generatedAt: "" });
  await oldLoad;

  assert.equal(page.data.dateMode, "this_weekend");
  assert.equal(page.data.selectedDateStart, "2026-07-17");
  assert.equal(page.data.selectedDateEnd, "2026-07-19");
  assert.ok(page.__timers.some((timer) => timer.ms === 0 && !timer.cancelled), "newer queued selection must run next");
});

test("home unload invalidates an in-flight load before it can mutate page state", async () => {
  const clock = createClock("2026-07-19T14:00:00+08:00");
  const page = loadHomePage(clock);
  let releaseCurrent;
  page.fetchAllCurrentItems = () => new Promise((resolve) => { releaseCurrent = resolve; });
  const load = page.loadData();
  const previousSeq = page.loadSeq;
  page.onUnload();
  const postUnloadPatches = [];
  const originalSetData = page.setData;
  page.setData = function setDataAfterUnload(patch) {
    postUnloadPatches.push(patch);
    originalSetData.call(this, patch);
  };
  releaseCurrent({ items: [], total: 0, fromCache: false, fromSnapshot: false, generatedAt: "" });
  await load;

  assert.equal(page.destroyed, true);
  assert.ok(page.loadSeq > previousSeq);
  assert.deepEqual(postUnloadPatches, []);
});

test("home background timer remains harmless even if its callback races unload", () => {
  const clock = createClock("2026-07-19T14:00:00+08:00");
  const page = loadHomePage(clock);
  const calls = [];
  page.loadData = (options) => calls.push(options);
  page.scheduleBackgroundRefresh();
  const timer = page.backgroundRefreshTimer;

  page.onUnload();
  timer.callback();

  assert.equal(timer.cancelled, true);
  assert.deepEqual(calls, []);
});
