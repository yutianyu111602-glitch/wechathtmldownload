const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function loadCityPage() {
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
      if (request.endsWith("/api")) return { requestApi: async () => ({ cities: [] }) };
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome: () => {},
          normalizeLang: (value) => (value === "en" ? "en" : "zh"),
          text: () => ({}),
          translateCity: (value) => value,
        };
      }
      if (request.endsWith("/share")) {
        return {
          buildSimpleShare: () => ({}),
          buildSimpleTimeline: () => ({}),
          enableShareMenu: () => {},
        };
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      setStorageSync(key, value) {
        calls.push(["setStorageSync", key, value]);
      },
      switchTab(options) {
        calls.push(["switchTab", options.url]);
        if (options.success) options.success();
      },
      navigateTo(options) {
        calls.push(["navigateTo", options.url]);
      },
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  return { pageConfig, calls };
}

test("city page opens index tab through pending city storage instead of navigateTo", () => {
  const { pageConfig, calls } = loadCityPage();

  pageConfig.openCity({ currentTarget: { dataset: { key: "hangzhou" } } });

  assert.deepEqual(calls[0], ["setStorageSync", "weeklyActivityPendingCity", "hangzhou"]);
  assert.deepEqual(calls[1], ["switchTab", "/pages/index/index"]);
  assert.equal(calls.some((call) => call[0] === "navigateTo"), false);
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

test("detail poster tap previews the poster and does not open source article", () => {
  const detailScript = fs.readFileSync(path.join(root, "pages", "detail", "detail.js"), "utf8");
  const detailWxml = fs.readFileSync(path.join(root, "pages", "detail", "detail.wxml"), "utf8");
  const openPosterMatch = detailScript.match(/openPoster\(\) \{([\s\S]*?)\n  \},\n\n  onPosterImageLoad/);

  assert.ok(openPosterMatch, "openPoster body must stay directly testable");
  assert.match(openPosterMatch[1], /wx\.previewImage/);
  assert.doesNotMatch(openPosterMatch[1], /openSourceUrl|buildSourcePageUrl|navigateTo|preferredSourceHash/);
  assert.match(detailWxml, /class="poster-hero" bindtap="openPoster"/);
  assert.match(detailWxml, /wx:if="\{\{item\.hasSource\}\}" class="tap-hint" catchtap="openSource"/);
  assert.match(detailWxml, /class="source-article-row"[\s\S]*bindtap="openSourceArticle"/);
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

test("venue and saved routes preserve key and language context", () => {
  const venueScript = fs.readFileSync(path.join(root, "pages", "venue", "venue.js"), "utf8");
  const savedScript = fs.readFileSync(path.join(root, "pages", "saved", "saved.js"), "utf8");

  assert.match(venueScript, /venueMatches\(item, name, key\)/);
  assert.match(venueScript, /normalizeEntityKey\(key\)/);
  assert.match(venueScript, /fuzzyEntityMatch\(value, target\)/);
  assert.match(venueScript, /&lang=\$\{this\.lang/);
  assert.match(savedScript, /weeklyActivityLang/);
  assert.match(savedScript, /\/pages\/detail\/detail\?id=.*&lang=/);
});
