const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function nextTurn() {
  return new Promise((resolve) => setImmediate(resolve));
}

function bindPage(pageConfig) {
  pageConfig.data = { ...pageConfig.data };
  pageConfig.setData = function setData(update) {
    this.data = { ...this.data, ...(update || {}) };
  };
  return pageConfig;
}

function loadArtistPage({ profile, fetchAllCurrentItems }) {
  const filename = path.join(root, "pages", "artist", "artist.js");
  const code = fs.readFileSync(filename, "utf8");
  let pageConfig;
  const sandbox = {
    console: { ...console, warn() {}, error() {} },
    Page(config) { pageConfig = config; },
    require(request) {
      if (request.endsWith("/api")) {
        return {
          requestApi: async (route) => route === "/api/v1/weekly/atlas/artist" ? profile : { found: false },
          fetchAllCurrentItems,
        };
      }
      if (request.endsWith("/format")) return { compactItem: (item) => item };
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome() {},
          localizeItems: (items) => items,
          normalizeLang: (value) => value || "zh",
          text: () => ({ loadFailed: "加载失败", relatedEvents: "相关活动" }),
        };
      }
      if (request.endsWith("/atlasContract")) {
        return { mergeVenues: (rows) => rows || [], mergeCollaborators: (rows) => rows || [] };
      }
      if (request.endsWith("/sourceAction")) return { openSourceByHash() {} };
      if (request.endsWith("/publicExternalLinks")) return { normalizeDjDiscoverySectionsForDisplay: () => [] };
      if (request.endsWith("/externalLinkAction")) return { copyOriginalExternalLink: () => ({ ok: true }) };
      if (request.endsWith("/djLinks")) return { socialToLinkItems: () => [] };
      if (request.endsWith("/share")) {
        return { buildNamedPageShare: () => ({}), buildNamedPageTimeline: () => ({}), enableShareMenu() {} };
      }
      if (request.endsWith("/cityFootprint")) {
        return { cityFootprint: () => ({ order: [], counts: {}, ranges: {} }), normalizeCityName: (value) => value };
      }
      if (request.endsWith("/groupOutlinks")) return { groupOutlinks: () => [] };
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      getStorageSync() { return "zh"; },
      setStorageSync() {},
      navigateBack() {},
      navigateTo() {},
      switchTab() {},
      reLaunch() {},
      showToast() {},
      vibrateShort() {},
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  return bindPage(pageConfig);
}

function loadDetailPage({ raw, atlasResult, posterResolver, sourceResolver = async () => "" }) {
  const filename = path.join(root, "pages", "detail", "detail.js");
  const code = fs.readFileSync(filename, "utf8");
  let pageConfig;
  const sandbox = {
    console: { ...console, warn() {}, error() {} },
    Page(config) { pageConfig = config; },
    getCurrentPages: () => [],
    require(request) {
      if (request.endsWith("/api")) {
        return {
          requestApi: async (route) => route.includes("/atlas-events/") ? atlasResult() : raw,
        };
      }
      if (request.endsWith("/format")) {
        return { compactItem: (item) => ({ ...item }), joinList: (items) => Array.isArray(items) ? items.join(" / ") : "" };
      }
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome() {},
          localizeItem: (item) => item,
          localizedSourceArticles: (items) => items,
          normalizeLang: (value) => value || "zh",
          text: () => ({ loading: "加载中", sourcePreparing: "准备来源", loadFailed: "加载失败" }),
        };
      }
      if (request.endsWith("/sourceAction")) {
        return { buildSourcePageUrl: () => "", fetchSourceByHash: sourceResolver, openSourceUrl() {} };
      }
      if (request.endsWith("/sourceArticles")) return { buildDetailSourceArticles: () => [] };
      if (request.endsWith("/share")) {
        return { buildDetailShare: () => ({}), buildDetailTimeline: () => ({}), enableShareMenu() {} };
      }
      if (request.endsWith("/cloudPosterUrls")) {
        return {
          posterFallbackState: (item, coverUrl) => ({ ...item, coverUrl }),
          posterImageErrorFallback: async () => "",
          resolvePosterUrlForItem: posterResolver,
        };
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      getStorageSync(key) { return key === "savedActivityIds" ? [] : "zh"; },
      setStorageSync() {},
      navigateTo() {},
      switchTab() {},
      reLaunch() {},
      navigateBack() {},
      showToast() {},
      vibrateShort() {},
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  return bindPage(pageConfig);
}

test("artist renders the core profile before the optional 45-day history paginator settles", async () => {
  const history = deferred();
  const page = loadArtistPage({
    profile: {
      found: true,
      profile: { displayName: "Fast Profile" },
      events: [],
      venues: [],
      collaborators: [],
    },
    fetchAllCurrentItems: () => history.promise,
  });
  page.name = "Fast Profile";
  page.lang = "zh";

  const loading = page.loadArtist.call(page);
  try {
    await nextTurn();
    assert.equal(page.data.loading, false);
    assert.equal(page.data.error, "");
    assert.equal(page.data.atlasProfile.displayName, "Fast Profile");
  } finally {
    history.resolve([]);
    await loading;
    await nextTurn();
  }
});

test("artist keeps the core profile usable when optional history pagination fails", async () => {
  const page = loadArtistPage({
    profile: {
      found: true,
      profile: { displayName: "Resilient Profile" },
      events: [],
      venues: [],
      collaborators: [],
    },
    fetchAllCurrentItems: async () => { throw new Error("history unavailable"); },
  });
  page.name = "Resilient Profile";
  page.lang = "zh";

  await page.loadArtist.call(page);
  await nextTurn();

  assert.equal(page.data.loading, false);
  assert.equal(page.data.error, "");
  assert.equal(page.data.atlasProfile.displayName, "Resilient Profile");
  assert.equal(page.data.events.length, 0);
});

test("detail renders the core activity before optional Atlas enrichment settles", async () => {
  const atlas = deferred();
  const page = loadDetailPage({
    raw: { id: "event-core", title: "Core Event", price: [] },
    atlasResult: () => atlas.promise,
    posterResolver: async (item) => item,
  });
  page.itemId = "event-core";

  const loading = page.loadDetail.call(page);
  try {
    await nextTurn();
    assert.equal(page.data.loading, false);
    assert.equal(page.data.error, "");
    assert.equal(page.data.item.title, "Core Event");
  } finally {
    atlas.resolve({ lineupResolved: [] });
    await loading;
    await nextTurn();
  }
});

test("detail renders the core activity before poster URL resolution settles", async () => {
  const poster = deferred();
  const page = loadDetailPage({
    raw: { id: "event-poster", title: "Poster Event", coverUrl: "cloud://poster", price: [] },
    atlasResult: async () => null,
    posterResolver: () => poster.promise,
  });
  page.itemId = "event-poster";

  const loading = page.loadDetail.call(page);
  try {
    await nextTurn();
    assert.equal(page.data.loading, false);
    assert.equal(page.data.error, "");
    assert.equal(page.data.item.title, "Poster Event");
  } finally {
    poster.resolve({ id: "event-poster", title: "Poster Event", coverUrl: "https://poster.example/event.jpg", price: [] });
    await loading;
    await nextTurn();
  }
});

test("detail keeps the core activity usable when poster URL resolution fails", async () => {
  const page = loadDetailPage({
    raw: { id: "event-poster-fail", title: "Poster Fallback Event", coverUrl: "cloud://poster", price: [] },
    atlasResult: async () => null,
    posterResolver: async () => { throw new Error("poster unavailable"); },
  });
  page.itemId = "event-poster-fail";

  await page.loadDetail.call(page);
  await nextTurn();

  assert.equal(page.data.loading, false);
  assert.equal(page.data.error, "");
  assert.equal(page.data.item.title, "Poster Fallback Event");
});
