const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function loadAboutPage({ requestApi, copyOriginalExternalLink, navigateTo } = {}) {
  const filename = path.join(root, "pages", "about", "about.js");
  const code = fs.readFileSync(filename, "utf8");
  let pageConfig = null;
  const copyCalls = [];
  const navigateCalls = [];
  const sandbox = {
    console: { ...console, warn() {} },
    Page(config) {
      pageConfig = config;
    },
    require(request) {
      if (request.endsWith("/haptics")) {
        return { HAPTIC: { tabInterval: 1 }, vibrateLight: () => {} };
      }
      if (request.endsWith("/api")) {
        return { requestApi: requestApi || (async () => { throw new Error("network disabled"); }) };
      }
      if (request.endsWith("/externalLinkAction")) {
        return {
          copyOriginalExternalLink: copyOriginalExternalLink || ((url, lang, options) => {
            copyCalls.push({ url, lang, options });
            return { ok: true };
          }),
        };
      }
      if (request.endsWith("/i18n")) {
        return require(path.join(root, "utils", "i18n.js"));
      }
      if (request.endsWith("/share")) {
        return require(path.join(root, "utils", "share.js"));
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      removeStorageSync() {},
      hideTabBarRedDot() {},
      getStorageSync() { return "zh"; },
      setClipboardData() {},
      showToast() {},
      navigateTo(options) {
        navigateCalls.push(options.url);
        if (navigateTo) return navigateTo(options);
        if (options && typeof options.success === "function") options.success({});
        return undefined;
      },
      reLaunch() {},
      showModal() {},
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  pageConfig.setData = function setData(update) {
    this.data = { ...this.data, ...(update || {}) };
  };
  return { pageConfig, copyCalls, navigateCalls };
}

function loadSourcePage() {
  const filename = path.join(root, "pages", "source", "source.js");
  const code = fs.readFileSync(filename, "utf8");
  let pageConfig = null;
  const sandbox = {
    console: { ...console, error() {} },
    Page(config) {
      pageConfig = config;
    },
    require(request) {
      if (request.endsWith("/api")) {
        return { requestApi: async () => { throw new Error("network disabled"); } };
      }
      if (request.endsWith("/externalLinkAction")) {
        return require(path.join(root, "utils", "externalLinkAction.js"));
      }
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome: () => {},
          normalizeLang: (value) => (value === "en" ? "en" : "zh"),
          text: (scope, lang) => require(path.join(root, "utils", "i18n.js")).text(scope, lang),
        };
      }
      if (request.endsWith("/sourceAction")) {
        return { openOfficialArticle: () => false };
      }
      if (request.endsWith("/share")) {
        return require(path.join(root, "utils", "share.js"));
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      getStorageSync() { return "zh"; },
      setClipboardData() {},
      showToast() {},
      navigateBack() {},
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  pageConfig.setData = function setData(update) {
    this.data = { ...this.data, ...(update || {}) };
  };
  return pageConfig;
}

function loadCityPage({ requestApi } = {}) {
  const filename = path.join(root, "pages", "city", "city.js");
  const code = fs.readFileSync(filename, "utf8");
  let pageConfig = null;
  const calls = [];
  const sandbox = {
    console,
    Page(config) {
      pageConfig = config;
    },
    require(request) {
      if (request.endsWith("/api")) return { requestApi: requestApi || (async () => ({ cities: [] })) };
      if (request.endsWith("/cityGuide")) return require(path.join(root, "utils", "cityGuide.js"));
      if (request.endsWith("/format")) return {
        compactItem: (item) => item,
        dedupeItems: (items) => items,
      };
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome: () => {},
          normalizeLang: (value) => (value === "en" ? "en" : "zh"),
          text: () => ({}),
          translateCity: (value) => value,
          localizeItems: (items) => items,
        };
      }
      if (request.endsWith("/share")) {
        return {
          buildSimpleShare: (title, page, query) => ({ title, path: page, query }),
          buildSimpleTimeline: (title, query) => ({ title, query }),
          enableShareMenu: () => {},
        };
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      getStorageSync() { return ""; },
      setStorageSync(key, value) {
        calls.push(["setStorageSync", key, value]);
      },
      removeStorageSync(key) {
        calls.push(["removeStorageSync", key]);
      },
      switchTab(options) {
        calls.push(["switchTab", options.url]);
        if (options.success) options.success();
      },
      navigateTo(options) {
        calls.push(["navigateTo", options.url]);
      },
      navigateBack() {},
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  pageConfig.setData = function setData(update) {
    this.data = { ...this.data, ...(update || {}) };
  };
  return { pageConfig, calls };
}

test("city page selects a guide city without leaving the page", () => {
  const { pageConfig, calls } = loadCityPage();
  pageConfig.cityGuideCities = [{ city_key: "hangzhou", displayCity: "杭州", item_count: 1 }];
  pageConfig.cityGuideItems = [{ id: "evt-1", city_key: "hangzhou", title: "杭州 techno", styleLabel: "Techno" }];

  pageConfig.openCity({ currentTarget: { dataset: { key: "hangzhou" } } });

  assert.deepEqual(calls[0], ["setStorageSync", "weeklyActivityGuideCity", "hangzhou"]);
  assert.equal(pageConfig.data.selectedCityKey, "hangzhou");
  assert.equal(pageConfig.data.guide.hasSelection, true);
  assert.equal(calls.some((call) => call[0] === "switchTab"), false);
  assert.equal(calls.some((call) => call[0] === "navigateTo"), false);
});

test("city page loadGuide derives counts from the exact current item set", async () => {
  const { pageConfig } = loadCityPage({
    requestApi: async (endpoint) => {
      if (endpoint === "/api/v1/weekly/cities") {
        return {
          cities: [
            { city_key: "hangzhou", city: "杭州", count: 2 },
            { city_key: "empty", city: "空城", count: 0 },
          ],
        };
      }
      if (endpoint === "/api/v1/weekly/current") {
        return {
          items: [
            {
              id: "hz-1",
              city_key: "hangzhou",
              title: "杭州 techno",
              date: "2026-06-26",
              venueLabel: "DONG",
              styleLabel: "Techno",
            },
          ],
          page: { nextCursor: null },
        };
      }
      throw new Error(`unexpected endpoint ${endpoint}`);
    },
  });

  await pageConfig.loadGuide("");

  assert.equal(pageConfig.data.loading, false);
  assert.equal(pageConfig.data.cities.length, 1);
  assert.equal(pageConfig.data.cities[0].key, "hangzhou");
  assert.equal(pageConfig.data.cities[0].itemCount, 1);
});

test("city guide all-events action opens the activity tab through pending city storage", () => {
  const { pageConfig, calls } = loadCityPage();
  pageConfig.setData({ selectedCityKey: "hangzhou" });

  pageConfig.openAllEvents();

  assert.deepEqual(calls[0], ["setStorageSync", "weeklyActivityPendingCity", "hangzhou"]);
  assert.deepEqual(calls[1], ["switchTab", "/pages/index/index"]);
  assert.equal(calls.some((call) => call[0] === "navigateTo"), false);
});

test("city guide share payload preserves lang and selected city", () => {
  const { pageConfig } = loadCityPage();
  pageConfig.setData({
    lang: "zh",
    selectedCityKey: "hangzhou",
    guide: { selectedCityLabel: "杭州" },
  });

  const appMessage = pageConfig.onShareAppMessage();
  const timeline = pageConfig.onShareTimeline();

  assert.equal(appMessage.title, "杭州今晚去哪");
  assert.equal(appMessage.path, "/pages/city/city");
  assert.equal(appMessage.query.lang, "zh");
  assert.equal(appMessage.query.city, "hangzhou");
  assert.equal(timeline.query.lang, "zh");
  assert.equal(timeline.query.city, "hangzhou");
});

test("guide tab replaces column tab while column page remains routable", () => {
  const appJson = JSON.parse(read("app.json"));
  const secondTab = appJson.tabBar.list[1];

  assert.equal(secondTab.pagePath, "pages/city/city");
  assert.equal(secondTab.text, "今晚");
  assert.ok(appJson.pages.includes("pages/column/column"));
  assert.equal(appJson.tabBar.list.some((item) => item.pagePath === "pages/column/column"), false);
});

test("detail page has a dedicated merged source article section", () => {
  const detailScript = fs.readFileSync(path.join(root, "pages", "detail", "detail.js"), "utf8");
  const detailWxml = fs.readFileSync(path.join(root, "pages", "detail", "detail.wxml"), "utf8");

  assert.match(detailScript, /buildDetailSourceArticles/);
  assert.match(detailScript, /openSourceArticle/);
  assert.match(detailScript, /preferredSourceHash/);
  assert.match(detailScript, /this\.prefetchSource\(preferredSourceHash\(item\)\)/);
  assert.match(detailScript, /organizerKey/);
  assert.match(detailScript, /\/pages\/venue\/venue\?name=.*&key=/);
  assert.match(detailWxml, /t\.sourceArticles/);
  assert.match(detailWxml, /item\.sourceArticles\.length/);
  assert.match(detailWxml, /binderror="onPosterImageError"/);
});

test("detail poster tap opens source article when trustworthy, else previews", () => {
  const detailScript = fs.readFileSync(path.join(root, "pages", "detail", "detail.js"), "utf8");
  const detailWxml = fs.readFileSync(path.join(root, "pages", "detail", "detail.wxml"), "utf8");
  const openPosterMatch = detailScript.match(/openPoster\(\) \{([\s\S]*?)\n  \},\n\n  onPosterImageLoad/);

  assert.ok(openPosterMatch, "openPoster body must stay directly testable");
  // Product rule 2026-06-13: poster tap routes to source article when one exists.
  assert.match(openPosterMatch[1], /preferredSourceHash/);
  assert.match(openPosterMatch[1], /this\.openSource\(\)/);
  // Still falls back to previewing the poster when there is no source.
  assert.match(openPosterMatch[1], /wx\.previewImage/);
  assert.match(detailWxml, /class="poster-hero" bindtap="openPoster"/);
  assert.match(detailWxml, /class="source-article-row"[\s\S]*bindtap="openSourceArticle"/);
  assert.match(read("utils/i18n.js"), /posterUnavailable:\s*"暂无活动海报"/);
});

test("source routing treats Atlas activity sidecar refs as evidence refs", () => {
  const sourceAction = require(path.join(root, "utils", "sourceAction.js"));
  const sourceArticles = require(path.join(root, "utils", "sourceArticles.js"));
  const sourcePage = fs.readFileSync(path.join(root, "pages", "source", "source.js"), "utf8");

  assert.equal(sourceAction.isAtlasEvidenceRef("activity_src:abc"), true);
  assert.equal(sourceArticles.isAtlasEvidenceRef("activity_src:abc"), true);
  assert.equal(sourceAction.isAtlasEvidenceRef("source_ref:abc"), true);
  assert.equal(sourceArticles.isAtlasEvidenceRef("source_ref:abc"), true);
  assert.match(sourcePage, /activity_src/);
  assert.match(sourcePage, /source_ref/);
});

test("aggregate children never expose parent overview source hashes on the frontend", () => {
  const sourceArticles = require(path.join(root, "utils", "sourceArticles.js"));
  const dirtyAggregateChild = {
    id: "agg-child-dirty",
    title: "子活动",
    sourceHash: "weekly-overview-hash",
    source_action: { available: true, url_hash: "weekly-overview-hash" },
    source_article: { url_hash: "weekly-overview-hash", title: "本周活动一览" },
  };

  assert.equal(sourceArticles.sourceHashOf(dirtyAggregateChild), "");
  assert.deepEqual(sourceArticles.sourceRefsForItem(dirtyAggregateChild), []);
  assert.deepEqual(sourceArticles.buildDetailSourceArticles(dirtyAggregateChild), []);
  assert.deepEqual(sourceArticles.buildVenueSourceArticles([dirtyAggregateChild], { includeSingles: true }), []);
});

test("source hash lookup does not fabricate WeChat URLs from internal hashes", async () => {
  const sourceActionPath = path.join(root, "utils", "sourceAction.js");
  const apiPath = path.join(root, "utils", "api.js");
  const api = require(apiPath);
  const originalRequestApi = api.requestApi;
  try {
    delete require.cache[require.resolve(sourceActionPath)];
    api.requestApi = async () => ({ url: "" });
    let sourceAction = require(sourceActionPath);
    assert.equal(await sourceAction.fetchSourceByHash("74c857fda5f80128"), "");

    delete require.cache[require.resolve(sourceActionPath)];
    api.requestApi = async () => {
      throw new Error("network failed");
    };
    sourceAction = require(sourceActionPath);
    assert.equal(await sourceAction.fetchSourceByHash("74c857fda5f80128"), "");
  } finally {
    api.requestApi = originalRequestApi;
    delete require.cache[require.resolve(sourceActionPath)];
  }
});

test("about page does not expose public radio links", () => {
  const aboutScript = read("pages/about/about.js");
  const aboutWxml = read("pages/about/about.wxml");
  const aboutWxss = read("pages/about/about.wxss");

  assert.doesNotMatch(aboutScript, /RADIO_LINK_API_PATH|radio-external-links|RADIO_FALLBACK_STATIONS/);
  assert.doesNotMatch(aboutScript, /loadRadioExternalLinks|openRadioLink|radioStations|radioSourceLabel/);
  assert.doesNotMatch(aboutScript, /https:\/\/byyb\.live|ShanghaiCommunityRadio|music\.163\.com\/#\/djradio/);
  assert.doesNotMatch(aboutWxml, /radio-panel|radioStations|openRadioLink/);
  assert.doesNotMatch(aboutWxss, /\.radio-panel|\.radio-item|\.radio-grid/);
});

test("artist page exposes radio program leads through source page only", () => {
  const artistScript = read("pages/artist/artist.js");
  const artistWxml = read("pages/artist/artist.wxml");
  const artistWxss = read("pages/artist/artist.wxss");
  const i18n = read("utils/i18n.js");

  assert.match(artistScript, /normalizeRadioPrograms/);
  assert.match(artistScript, /openRadioProgram/);
  assert.match(artistScript, /linkType=radio/);
  assert.match(artistScript, /copyOriginalExternalLink/);
  assert.doesNotMatch(artistScript, /createInnerAudioContext|createVideoContext|downloadFile|web-view/);
  assert.match(artistWxml, /wx:if="\{\{radioPrograms\.length\}\}"/);
  assert.match(artistWxml, /bindtap="openRadioProgram"/);
  assert.match(artistWxss, /\.radio-program-row/);
  assert.match(i18n, /radioPrograms:\s*"电台 \/ 节目线索"/);
  assert.match(i18n, /radioExternalTitle:\s*"电台节目原站"/);
  assert.match(i18n, /radioExternalHint:\s*"这里只保留节目页链接，不内嵌、不下载、不代理音频。复制后用浏览器打开原站。"/);
});

test("artist page exposes Atlas relation trajectory as local detail data", () => {
  const artistScript = read("pages/artist/artist.js");
  const artistWxml = read("pages/artist/artist.wxml");
  const artistWxss = read("pages/artist/artist.wxss");
  const i18n = read("utils/i18n.js");

  assert.match(artistScript, /normalizeRelationTrajectory/);
  assert.match(artistScript, /relationTrajectory/);
  assert.match(artistWxml, /wx:if="\{\{relationTrajectory\}\}"/);
  assert.match(artistWxml, /trajectoryCollaborators/);
  assert.match(artistWxml, /bindtap="openAtlasEventSource"/);
  assert.match(artistWxss, /\.relation-section/);
  assert.match(i18n, /relationTrajectory:\s*"关系 \/ 轨迹"/);
  assert.doesNotMatch(artistWxml, /createInnerAudioContext|createVideoContext|downloadFile|web-view/);
});

test("source page accepts safe external original-site urls and rejects direct media", () => {
  const sourcePage = loadSourcePage();
  sourcePage.onLoad({
    externalUrl: encodeURIComponent("https://music.163.com/#/djradio?id=794482403"),
    linkType: "radio",
    title: encodeURIComponent("HZCR"),
    meta: encodeURIComponent("Hangzhou · 网易云电台"),
    lang: "zh",
  });
  assert.equal(sourcePage.data.loading, false);
  assert.equal(sourcePage.data.externalUrl, "https://music.163.com/#/djradio?id=794482403");
  assert.equal(sourcePage.data.sourceUrl, "https://music.163.com/#/djradio?id=794482403");
  assert.equal(sourcePage.data.evidenceTitle, "HZCR");
  assert.equal(sourcePage.data.evidenceMeta, "Hangzhou · 网易云电台");
  assert.equal(sourcePage.data.sourceExternalTitle, "电台节目原站");
  assert.match(sourcePage.data.sourceExternalHint, /不内嵌、不下载、不代理音频/);

  const mediaPage = loadSourcePage();
  mediaPage.onLoad({
    externalUrl: encodeURIComponent("https://cdn.example.com/audio/raw-set.mp3"),
    linkType: "radio",
    lang: "zh",
  });
  assert.equal(mediaPage.data.externalUrl, "");
  assert.equal(mediaPage.data.loading, false);
  assert.equal(mediaPage.data.error, mediaPage.data.t.failed);
});

test("source page share preserves safe radio external original-site params", () => {
  const sourcePage = loadSourcePage();
  sourcePage.onLoad({
    externalUrl: encodeURIComponent("https://byyb.live/set/cocoonics-2025-10-19-turbo-x-catnapp-showcase"),
    linkType: "radio",
    title: encodeURIComponent("Cocoonics | TURBO x Catnapp Radio Showcase"),
    meta: encodeURIComponent("BYYB · byyb · 2025-10-19"),
    lang: "zh",
  });

  const appMessage = sourcePage.onShareAppMessage();
  const timeline = sourcePage.onShareTimeline();

  assert.equal(appMessage.title, "Cocoonics | TURBO x Catnapp Radio Showcase");
  assert.match(appMessage.path, /^\/pages\/source\/source\?/);
  assert.match(appMessage.path, /externalUrl=https%3A%2F%2Fbyyb\.live%2Fset%2Fcocoonics-2025-10-19-turbo-x-catnapp-showcase/);
  assert.match(appMessage.path, /linkType=radio/);
  assert.match(appMessage.path, /title=Cocoonics%20%7C%20TURBO%20x%20Catnapp%20Radio%20Showcase/);
  assert.match(appMessage.path, /meta=BYYB%20%C2%B7%20byyb%20%C2%B7%202025-10-19/);
  assert.match(appMessage.path, /lang=zh/);
  assert.equal(sourcePage.data.sourceExternalTitle, "电台节目原站");
  assert.match(sourcePage.data.sourceExternalHint, /不内嵌、不下载、不代理音频/);
  assert.match(timeline.query, /externalUrl=https%3A%2F%2Fbyyb\.live%2Fset%2Fcocoonics-2025-10-19-turbo-x-catnapp-showcase/);
  assert.match(timeline.query, /linkType=radio/);
  assert.match(timeline.query, /title=Cocoonics%20%7C%20TURBO%20x%20Catnapp%20Radio%20Showcase/);
  assert.match(timeline.query, /meta=BYYB%20%C2%B7%20byyb%20%C2%B7%202025-10-19/);
});

test("source action normalizes encoded mp links before opening", () => {
  const sourceActionPath = path.join(root, "utils", "sourceAction.js");
  delete require.cache[require.resolve(sourceActionPath)];
  const sourceAction = require(sourceActionPath);
  const calls = [];
  global.wx = {
    openOfficialAccountArticle(options) {
      calls.push(options.url);
      if (options.success) options.success({});
      if (options.complete) options.complete({});
    },
  };
  try {
    const opened = sourceAction.openSourceUrl("http%3A%2F%2Fmp.weixin.qq.com%2Fs%3F__biz%3Dabc&amp;mid=100", "zh");
    assert.equal(opened, true);
    assert.equal(calls.length, 1);
    assert.match(calls[0], /^https:\/\/mp\.weixin\.qq\.com\//);
    assert.match(calls[0], /__biz=abc&mid=100/);
  } finally {
    delete global.wx;
    delete require.cache[require.resolve(sourceActionPath)];
  }
});

test("mini-program package keeps source url map server-side", () => {
  const projectConfig = JSON.parse(fs.readFileSync(path.join(root, "project.config.json"), "utf8"));
  const ignored = projectConfig.packOptions.ignore || [];
  assert.ok(
    ignored.some((item) => item.type === "folder" && item.value === "source_actions"),
    "source_actions must stay out of the mini-program package",
  );
  assert.equal(fs.existsSync(path.join(root, "source_actions", "source_url_map.json")), false);
});

test("detail page exposes club and DJ as profile entry points", () => {
  const detailWxml = fs.readFileSync(path.join(root, "pages", "detail", "detail.wxml"), "utf8");
  const venueWxml = fs.readFileSync(path.join(root, "pages", "venue", "venue.wxml"), "utf8");
  const artistWxml = fs.readFileSync(path.join(root, "pages", "artist", "artist.wxml"), "utf8");

  assert.match(detailWxml, /class="fact-cell club-cell" bindtap="openVenue"/);
  assert.match(detailWxml, /class="lineup-chip"/);
  assert.match(detailWxml, /bindtap="openArtist"/);
  assert.match(detailWxml, /t\.artists/);
  assert.match(venueWxml, /t\.clubSchedule/);
  assert.match(artistWxml, /t\.artistRecords/);
});

test("home and detail pages expose source-backed ticketing fields", () => {
  const indexScript = fs.readFileSync(path.join(root, "pages", "index", "index.js"), "utf8");
  const indexWxml = fs.readFileSync(path.join(root, "pages", "index", "index.wxml"), "utf8");
  const detailWxml = fs.readFileSync(path.join(root, "pages", "detail", "detail.wxml"), "utf8");
  const i18n = fs.readFileSync(path.join(root, "utils", "i18n.js"), "utf8");

  assert.match(indexScript, /priceLabel:\s*item\.priceLabel/);
  assert.match(indexWxml, /class="poster-price"[\s\S]*item\.priceLabel/);
  assert.match(indexWxml, /class="event-price"[\s\S]*event\.priceLabel/);
  assert.match(detailWxml, /t\.ticketing/);
  assert.match(detailWxml, /wx:for="\{\{item\.price\}\}"[\s\S]*class="ticket-line"/);
  assert.match(i18n, /ticketing:\s*"入场"/);
  assert.match(i18n, /ticketing:\s*"Entry"/);
});

test("venue and saved routes preserve key and language context", () => {
  const venueScript = fs.readFileSync(path.join(root, "pages", "venue", "venue.js"), "utf8");
  const savedScript = fs.readFileSync(path.join(root, "pages", "saved", "saved.js"), "utf8");

  assert.match(venueScript, /venueMatches\(item, name, key\)/);
  assert.match(venueScript, /normalizeEntityKey\(key\)/);
  assert.match(venueScript, /fuzzyEntityMatch\(value, target\)/);
  assert.match(venueScript, /key:\s*""/);
  assert.match(venueScript, /key:\s*this\.key/);
  assert.match(venueScript, /buildNamedPageShare\("\/pages\/venue\/venue"[\s\S]*key:\s*this\.data\.key \|\| this\.key \|\| ""/);
  assert.match(venueScript, /buildNamedPageTimeline\(this\.data\.name \|\| this\.name[\s\S]*key:\s*this\.data\.key \|\| this\.key \|\| ""/);
  assert.match(venueScript, /&lang=\$\{this\.lang/);
  assert.match(savedScript, /weeklyActivityLang/);
  assert.match(savedScript, /\/pages\/detail\/detail\?id=.*&lang=/);
});
