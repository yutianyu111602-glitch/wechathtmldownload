const assert = require("node:assert/strict");
const fs = require("node:fs");
const { mkdtemp, rm, writeFile } = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { pathToFileURL } = require("node:url");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function atlasDataPath(repoRoot, filename) {
  const dataDir = process.env.HUAIDJ_ATLAS_MINIAPP_DATA_DIR
    || path.join(repoRoot, "services", "weekly_activity_cloudrun", "data");
  return path.join(path.resolve(dataDir), filename);
}

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

async function listen(serverInstance) {
  await new Promise((resolve) => serverInstance.listen(0, "127.0.0.1", resolve));
  const address = serverInstance.address();
  return `http://127.0.0.1:${address.port}`;
}

function loadArtistPage({ requestApi, fetchAllCurrentItems, navigateMode = "success", reLaunchMode = "success", switchTabMode = "success", discoverySections = [] } = {}) {
  const filename = path.join(root, "pages", "artist", "artist.js");
  const code = fs.readFileSync(filename, "utf8");
  let pageConfig = null;
  const apiCalls = [];
  const navigateCalls = [];
  const reLaunchCalls = [];
  const switchTabCalls = [];
  const copyCalls = [];
  const toastCalls = [];
  const storage = { weeklyActivityLang: "zh" };
  const sandbox = {
    console: { ...console, warn() {}, error() {} },
    Page(config) {
      pageConfig = config;
    },
    require(request) {
      if (request.endsWith("/api")) {
        return {
          requestApi: async (route, params) => {
            apiCalls.push({ route, params });
            if (requestApi) return requestApi(route, params);
            return { found: false };
          },
          fetchAllCurrentItems: async (params) => {
            if (fetchAllCurrentItems) return fetchAllCurrentItems(params);
            apiCalls.push({ route: "/api/v1/weekly/current", params });
            if (!requestApi) return [];
            const response = await requestApi("/api/v1/weekly/current", params);
            return Array.isArray(response && response.items) ? response.items : [];
          },
        };
      }
      if (request.endsWith("/format")) {
        return { compactItem: (item) => item };
      }
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome: () => {},
          localizeItems: (items) => items,
          normalizeLang: (value) => (value === "en" ? "en" : "zh"),
          text: () => ({
            loadFailed: "加载失败",
            sourceLinkCopied: "已复制",
            openOriginal: "打开原文",
            relatedEvents: "相关活动",
            relatedColumns: "相关专栏",
            openColumnArticle: "进入专栏阅读全文",
            externalMediaHint: "折叠展示，保留来源线索",
            radioProgramsHint: "打开原站节目页，不内嵌音频",
          }),
        };
      }
      if (request.endsWith("/atlasContract")) {
        return {
          mergeVenues: (venues) => venues || [],
          mergeCollaborators: (collaborators) => collaborators || [],
        };
      }
      if (request.endsWith("/sourceAction")) {
        return { openSourceByHash: () => true };
      }
      if (request.endsWith("/publicExternalLinks")) {
        return { normalizeDjDiscoverySectionsForDisplay: () => discoverySections };
      }
      if (request.endsWith("/externalLinkAction")) {
        return {
          copyOriginalExternalLink: (url, lang, options) => {
            copyCalls.push({ url, lang, options });
            return { ok: true };
          },
        };
      }
      if (request.endsWith("/djLinks")) {
        return { socialToLinkItems: () => [] };
      }
      if (request.endsWith("/cityFootprint")) {
        return require(path.join(root, "utils", "cityFootprint.js"));
      }
      if (request.endsWith("/groupOutlinks")) {
        return require(path.join(root, "utils", "groupOutlinks.js"));
      }
      if (request.endsWith("/share")) {
        return require(path.join(root, "utils", "share.js"));
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      getStorageSync(key) { return storage[key]; },
      vibrateShort() {},
      navigateBack() {},
      navigateTo(options) {
        navigateCalls.push(options.url);
        if (navigateMode === "fail" && typeof options.fail === "function") {
          options.fail(new Error("navigation failed"));
          return undefined;
        }
        if (typeof options.success === "function") options.success({});
        return undefined;
      },
      showToast(options) {
        toastCalls.push(options);
      },
      switchTab(options) {
        switchTabCalls.push(options.url);
        if (switchTabMode === "fail" && typeof options.fail === "function") {
          options.fail(new Error("switchTab failed"));
          return undefined;
        }
        if (typeof options.success === "function") options.success({});
        return undefined;
      },
      reLaunch(options) {
        reLaunchCalls.push(options.url);
        if (reLaunchMode === "fail" && typeof options.fail === "function") {
          options.fail(new Error("reLaunch failed"));
          return undefined;
        }
        if (typeof options.success === "function") options.success({});
        return undefined;
      },
      setStorageSync(key, value) {
        storage[key] = value;
      },
      removeStorageSync(key) {
        delete storage[key];
      },
    },
  };
  vm.runInNewContext(code, sandbox, { filename });
  pageConfig.setData = function setData(update) {
    this.data = { ...this.data, ...(update || {}) };
  };
  pageConfig.data = { ...pageConfig.data };
  return { pageConfig, apiCalls, navigateCalls, reLaunchCalls, switchTabCalls, copyCalls, toastCalls, storage };
}

test("artist page prefers subjectId Atlas lookup with bounded relation pages", async () => {
  const { pageConfig, apiCalls } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? { found: true, profile: { displayName: "Cocoonics" }, events: [], venues: [], collaborators: [] }
      : { items: [], page: { nextCursor: null } },
  });
  pageConfig.subjectId = "dj:cocoonics";
  pageConfig.name = "Cocoonics";

  const result = await pageConfig.fetchDjProfile.call(pageConfig);

  assert.equal(result.found, true);
  assert.equal(apiCalls[0].route, "/api/v1/weekly/atlas/artist");
  assert.equal(apiCalls[0].params.subjectId, "dj:cocoonics");
  assert.equal(apiCalls[0].params.eventLimit, 100);
  assert.equal(apiCalls[0].params.collaboratorLimit, 200);
  assert.equal(apiCalls[0].params.venueLimit, 100);
  assert.equal(apiCalls.some((call) => call.route.includes("/dj-profile/")), false);
});

test("artist page uses server pagination totals instead of truncated array lengths", async () => {
  const { pageConfig } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? {
        found: true,
        profile: { displayName: "Cocoonics" },
        events: [{ eventId: "e1", title: "One" }],
        venues: [{ venueName: "V1", eventCount: 1 }],
        collaborators: [{ djId: "d1", displayName: "D1", sameEventCount: 1 }],
        pagination: {
          events: { total: 1435, availableTotal: 100, truncated: true },
          venues: { total: 71, availableTotal: 20, truncated: true },
          collaborators: { total: 691, availableTotal: 30, truncated: true },
        },
      }
      : { items: [], page: { nextCursor: null } },
  });
  pageConfig.name = "Cocoonics";
  pageConfig.lang = "zh";
  pageConfig.data = { ...pageConfig.data, t: { loadFailed: "加载失败" } };

  await pageConfig.loadArtist.call(pageConfig);

  assert.equal(pageConfig.data.atlasProfile.eventCount, 1435);
  assert.equal(pageConfig.data.atlasProfile.venueCount, 71);
  assert.equal(pageConfig.data.atlasProfile.collaboratorCount, 691);
});

test("artist page share preserves subjectId for direct profile reopen", () => {
  const { pageConfig } = loadArtistPage();
  pageConfig.name = "Cocoonics";
  pageConfig.subjectId = "dj:cocoonics";
  pageConfig.lang = "zh";
  pageConfig.data = {
    ...pageConfig.data,
    name: "Cocoonics",
    subjectId: "dj:cocoonics",
    t: { relatedEvents: "相关活动" },
  };

  const appMessage = pageConfig.onShareAppMessage.call(pageConfig);
  const timeline = pageConfig.onShareTimeline.call(pageConfig);

  assert.equal(appMessage.path, "/pages/artist/artist?name=Cocoonics&subjectId=dj%3Acocoonics&lang=zh");
  assert.equal(timeline.query, "name=Cocoonics&subjectId=dj%3Acocoonics&lang=zh");
});

test("artist page surfaces related columns from Atlas response and opens highlighted tabBar column", async () => {
  const { pageConfig, navigateCalls, reLaunchCalls, switchTabCalls, storage } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? {
        found: true,
        profile: { displayName: "Cocoonics" },
        events: [],
        venues: [],
        collaborators: [],
        relatedColumns: [
          {
            columnId: "col:cocoonics",
            title: "Cocoonics 专栏",
            summary: "在深圳和上海之间移动的声音线索。",
            sourceTitle: "HUAIDJ 专栏",
            publishedAt: "2026-06-23",
          },
          {
            columnId: "col:cocoonics",
            title: "duplicate should collapse",
          },
          {
            columnId: "col:other",
            title: "另一个入口",
            summary: "补充阅读。",
          },
        ],
      }
      : { items: [], page: { nextCursor: null } },
  });
  pageConfig.name = "Cocoonics";
  pageConfig.lang = "zh";
  pageConfig.data = { ...pageConfig.data, t: { loadFailed: "加载失败" } };

  await pageConfig.loadArtist.call(pageConfig);

  assert.equal(pageConfig.data.relatedColumns.length, 2);
  assert.equal(pageConfig.data.relatedColumns[0].title, "Cocoonics 专栏");
  assert.equal(pageConfig.data.relatedColumns[0].metaLabel, "2026-06-23 · HUAIDJ 专栏");
  assert.equal(pageConfig.data.atlasProfile.relatedColumns.length, 2);

  pageConfig.openRelatedColumn.call(pageConfig, { currentTarget: { dataset: { index: 0 } } });

  assert.equal(navigateCalls.length, 0);
  assert.equal(reLaunchCalls.length, 0);
  assert.equal(switchTabCalls.length, 1);
  assert.equal(switchTabCalls[0], "/pages/column/column");
  assert.equal(storage["weeklyActivityColumnHighlight:v1"].highlight, "col:cocoonics");
  assert.equal(storage["weeklyActivityColumnHighlight:v1"].lang, "zh");
});

test("artist related column keeps highlight and does not reLaunch tabBar on switchTab failure", async () => {
  const { pageConfig, reLaunchCalls, switchTabCalls, toastCalls, storage } = loadArtistPage({
    switchTabMode: "fail",
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? {
        found: true,
        profile: { displayName: "Cocoonics" },
        events: [],
        venues: [],
        collaborators: [],
        relatedColumns: [{ columnId: "col:cocoonics", title: "Cocoonics 专栏" }],
      }
      : { items: [], page: { nextCursor: null } },
  });
  pageConfig.name = "Cocoonics";
  pageConfig.lang = "zh";

  await pageConfig.loadArtist.call(pageConfig);
  pageConfig.openRelatedColumn.call(pageConfig, { currentTarget: { dataset: { index: 0 } } });

  assert.equal(switchTabCalls[0], "/pages/column/column");
  assert.equal(reLaunchCalls.length, 0);
  assert.equal(toastCalls.length, 1);
  assert.match(toastCalls[0].title, /专栏|Columns/);
  assert.equal(storage["weeklyActivityColumnHighlight:v1"].highlight, "col:cocoonics");
  assert.equal(storage["weeklyActivityColumnHighlight:v1"].lang, "zh");
  assert.ok(storage["weeklyActivityColumnHighlight:v1"].createdAt > 0);
});

test("artist radio program tap opens source page with radio metadata before clipboard fallback", () => {
  const { pageConfig, navigateCalls, copyCalls } = loadArtistPage();
  pageConfig.lang = "zh";
  pageConfig.data = {
    ...pageConfig.data,
    t: { sourceLinkCopied: "已复制", openOriginal: "打开原文" },
    radioPrograms: [{
      url: "https://byyb.live/set/cocoonics-2025-10-19-turbo-x-catnapp-showcase",
      title: "Cocoonics | TURBO x Catnapp Radio Showcase",
      metaLabel: "BYYB · byyb · 2025-10-19",
    }],
  };

  pageConfig.openRadioProgram.call(pageConfig, { currentTarget: { dataset: { index: 0 } } });

  assert.equal(copyCalls.length, 0);
  assert.equal(navigateCalls.length, 1);
  assert.match(navigateCalls[0], /^\/pages\/source\/source\?externalUrl=/);
  assert.match(navigateCalls[0], /linkType=radio/);
  assert.match(navigateCalls[0], /lang=zh/);
  assert.match(decodeURIComponent(navigateCalls[0]), /Cocoonics \| TURBO x Catnapp Radio Showcase/);
  assert.match(decodeURIComponent(navigateCalls[0]), /BYYB · byyb · 2025-10-19/);
});

test("artist radio program navigation failure copies original radio link with radio type", () => {
  const { pageConfig, navigateCalls, copyCalls } = loadArtistPage({ navigateMode: "fail" });
  pageConfig.lang = "zh";
  pageConfig.data = {
    ...pageConfig.data,
    t: { sourceLinkCopied: "已复制", openOriginal: "打开原文" },
    radioPrograms: [{
      url: "https://byyb.live/set/cocoonics-2025-10-19-turbo-x-catnapp-showcase",
      title: "Cocoonics | TURBO x Catnapp Radio Showcase",
      metaLabel: "BYYB · byyb · 2025-10-19",
    }],
  };

  pageConfig.openRadioProgram.call(pageConfig, { currentTarget: { dataset: { index: 0 } } });

  assert.equal(navigateCalls.length, 1);
  assert.equal(copyCalls.length, 1);
  assert.equal(copyCalls[0].url, "https://byyb.live/set/cocoonics-2025-10-19-turbo-x-catnapp-showcase");
  assert.equal(copyCalls[0].lang, "zh");
  assert.equal(copyCalls[0].options.linkType, "radio");
});

test("artist detail keeps relation first and external/radio leads at the bottom, not About", () => {
  const artistWxml = read("pages/artist/artist.wxml");
  const aboutScript = read("pages/about/about.js");
  const aboutWxml = read("pages/about/about.wxml");

  const relationIndex = artistWxml.indexOf("relationTrajectory");
  const columnIndex = artistWxml.indexOf("relatedColumns");
  const externalIndex = artistWxml.indexOf("djDiscovery");
  const radioIndex = artistWxml.indexOf("radioPrograms");

  assert.ok(relationIndex >= 0, "artist page must render relation trajectory");
  assert.ok(columnIndex > relationIndex, "related columns should stay below core relation/history modules");
  assert.ok(externalIndex > columnIndex, "external media should stay below column reading entry");
  assert.ok(radioIndex > externalIndex, "radio leads should stay at the bottom after external media");
  assert.match(artistWxml, /bindtap="openRelatedColumn"/);
  assert.match(artistWxml, /visibleDjDiscovery/);
  assert.match(artistWxml, /{{t\.externalMediaHint}}/);
  assert.match(artistWxml, /bindtap="toggleDjDiscovery"/);
  assert.match(artistWxml, /visibleRadioPrograms/);
  assert.match(artistWxml, /{{t\.radioProgramsHint}}/);
  assert.match(artistWxml, /bindtap="toggleRadioPrograms"/);
  assert.match(artistWxml, /bindtap="openRadioProgram"/);
  assert.doesNotMatch(aboutScript, /radio-external-links|radio-programs|radioStations|loadRadioExternalLinks|openRadioLink/);
  assert.doesNotMatch(aboutWxml, /radioStations|openRadioLink|radio-panel/);
});

test("artist support links are collapsed by default and expanded on demand", async () => {
  const discoverySections = [{
    nameKey: "cocoonics",
    entityName: "Cocoonics",
    links: [
      { url: "https://example.com/1", displayLabel: "RA", platform: "Resident Advisor" },
      { url: "https://example.com/2", displayLabel: "SoundCloud", platform: "SoundCloud" },
      { url: "https://example.com/3", displayLabel: "Mixcloud", platform: "Mixcloud" },
      { url: "https://example.com/4", displayLabel: "Instagram", platform: "Instagram" },
      { url: "https://example.com/5", displayLabel: "Interview", platform: "Interview" },
    ],
    bioAtoms: [
      { text: "first atom" },
      { text: "second atom" },
      { text: "third atom" },
    ],
  }];
  const { pageConfig } = loadArtistPage({
    discoverySections,
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? {
        found: true,
        profile: { displayName: "Cocoonics" },
        events: [],
        venues: [],
        collaborators: [],
        radioPrograms: [],
      }
      : { items: [], page: { nextCursor: null } },
  });
  pageConfig.name = "Cocoonics";
  pageConfig.lang = "zh";
  pageConfig.data = { ...pageConfig.data, t: { loadFailed: "加载失败" } };

  await pageConfig.loadArtist.call(pageConfig);

  assert.equal(pageConfig.data.djDiscoveryExpanded, false);
  assert.equal(pageConfig.data.visibleDjDiscovery.length, 1);
  assert.equal(pageConfig.data.visibleDjDiscovery[0].links.length, 3);
  assert.equal(pageConfig.data.visibleDjDiscovery[0].bioAtoms.length, 0);
  assert.equal(pageConfig.data.hiddenDiscoveryCount, 5);
  assert.match(pageConfig.data.discoveryToggleLabel, /展开全部资料/);

  pageConfig.toggleDjDiscovery.call(pageConfig);

  assert.equal(pageConfig.data.djDiscoveryExpanded, true);
  assert.equal(pageConfig.data.visibleDjDiscovery[0].links.length, 5);
  assert.equal(pageConfig.data.visibleDjDiscovery[0].bioAtoms.length, 3);
  assert.equal(pageConfig.data.hiddenDiscoveryCount, 0);
  assert.match(pageConfig.data.discoveryToggleLabel, /收起资料/);
});

test("artist page computes city footprint for multi-city DJ, skips single-city and curated-trajectory", async () => {
  const multiCityEvents = [
    { eventId: "e1", title: "A", date: "2025-01-10", venueName: "V1", city: "上海" },
    { eventId: "e2", title: "B", date: "2025-03-12", venueName: "V2", city: "上海市" }, // merges with 上海
    { eventId: "e3", title: "C", date: "2025-05-20", venueName: "V3", city: "北京" },
    { eventId: "e4", title: "D", date: "2025-06-01", venueName: "V4", city: "成都" },
    { eventId: "e5", title: "E", date: "2025-06-15", venueName: "V5", city: "未知" }, // placeholder, filtered
  ];
  const makePage = (profileExtra, events) => loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? { found: true, profile: { displayName: "Tourer", ...profileExtra }, events, venues: [], collaborators: [] }
      : { items: [], page: { nextCursor: null } },
  });

  // 1) Multi-city, no trajectory -> footprint computed, sorted by event count, with date range.
  const a = makePage({}, multiCityEvents);
  a.pageConfig.name = "Tourer";
  a.pageConfig.lang = "zh";
  a.pageConfig.data = { ...a.pageConfig.data, t: { loadFailed: "加载失败" } };
  await a.pageConfig.loadArtist.call(a.pageConfig);
  const fp = a.pageConfig.data.cityFootprint;
  assert.equal(fp.length, 3);
  assert.equal(fp[0].city, "上海");
  assert.equal(fp[0].eventCount, 2);
  assert.match(fp[0].metaLabel, /2场/);
  assert.match(fp[0].metaLabel, /2025-01-10 - 2025-03-12/);

  // 2) Single-city -> no footprint (header already shows the one city).
  const b = makePage({}, multiCityEvents.map((e) => ({ ...e, city: "上海" })));
  b.pageConfig.name = "Tourer";
  b.pageConfig.lang = "zh";
  b.pageConfig.data = { ...b.pageConfig.data, t: { loadFailed: "加载失败" } };
  await b.pageConfig.loadArtist.call(b.pageConfig);
  assert.equal(b.pageConfig.data.cityFootprint.length, 0);

  // 3) Curated trajectory present -> footprint suppressed (trajectory has its own cities strip).
  const c = makePage({ relationTrajectory: { cities: [{ city: "上海", eventCount: 5 }] } }, multiCityEvents);
  c.pageConfig.name = "Tourer";
  c.pageConfig.lang = "zh";
  c.pageConfig.data = { ...c.pageConfig.data, t: { loadFailed: "加载失败" } };
  await c.pageConfig.loadArtist.call(c.pageConfig);
  assert.equal(c.pageConfig.data.cityFootprint.length, 0);
});

test("artist page surfaces similar DJs from profile.similarDjs, empty when absent (plan 101 #1)", async () => {
  const { pageConfig } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? { found: true, profile: { displayName: "Tourer", similarDjs: [
          { djId: "dj:beta", displayName: "Beta", city: "北京", relationType: "b2b", sharedWeight: 10 },
          { djId: "dj:gamma", displayName: "Gamma", city: "成都", relationType: "collab", sharedWeight: 3 },
        ] }, events: [], venues: [], collaborators: [] }
      : { items: [], page: { nextCursor: null } },
  });
  pageConfig.name = "Tourer";
  pageConfig.lang = "zh";
  pageConfig.data = { ...pageConfig.data, t: { loadFailed: "加载失败" } };
  await pageConfig.loadArtist.call(pageConfig);
  assert.deepEqual(pageConfig.data.similarDjs.map((d) => d.djId), ["dj:beta", "dj:gamma"]);
  assert.equal(pageConfig.data.similarDjs[0].displayName, "Beta");

  // Missing similarDjs -> empty array, never undefined (wx:if guards the section).
  const { pageConfig: bare } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? { found: true, profile: { displayName: "Solo" }, events: [], venues: [], collaborators: [] }
      : { items: [], page: { nextCursor: null } },
  });
  bare.name = "Solo";
  bare.lang = "zh";
  bare.data = { ...bare.data, t: { loadFailed: "加载失败" } };
  await bare.loadArtist.call(bare);
  assert.equal(bare.data.similarDjs.length, 0); // realm-safe: [] is built inside the VM context
});

test("artist page surfaces bioCandidate draft when DJ has no confirmed bio (plan 101 #6-D)", async () => {
  const draft = "HEIMU 是一位 DJ，演出场次超过 93 场。常驻 44KW、All俱乐部。演出足迹遍及上海、深圳、长沙。";
  const { pageConfig } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? { found: true, profile: { displayName: "HEIMU", bio: null, bioCandidate: draft }, events: [], venues: [], collaborators: [] }
      : { items: [], page: { nextCursor: null } },
  });
  pageConfig.name = "HEIMU";
  pageConfig.lang = "zh";
  pageConfig.data = { ...pageConfig.data, t: { loadFailed: "加载失败" } };
  await pageConfig.loadArtist.call(pageConfig);
  assert.equal(pageConfig.data.atlasProfile.bioCandidate, draft,
    "bioCandidate should pass through to atlasProfile when bio is null");
  assert.ok(!pageConfig.data.atlasProfile.bio, "confirmed bio should remain null");

  // bioCandidate still present in data when confirmed bio also exists (wxml hides it via !atlasProfile.bio)
  const { pageConfig: withBio } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? { found: true, profile: { displayName: "HEIMU", bio: "已有正式简介。", bioCandidate: draft }, events: [], venues: [], collaborators: [] }
      : { items: [], page: { nextCursor: null } },
  });
  withBio.name = "HEIMU";
  withBio.lang = "zh";
  withBio.data = { ...withBio.data, t: { loadFailed: "加载失败" } };
  await withBio.loadArtist.call(withBio);
  assert.equal(withBio.data.atlasProfile.bio, "已有正式简介。");
  assert.equal(withBio.data.atlasProfile.bioCandidate, draft, "candidate data present; wxml hides it when bio exists");
});

test("artist page surfaces sceneCluster when backend returns one (scene cluster feature)", async () => {
  const cluster = {
    label: "上海 · All俱乐部",
    city: "上海",
    members: [
      { djId: "dj:jaya", displayName: "JAYA", city: "上海", eventCount: 331 },
      { djId: "dj:nakin", displayName: "NAKIN", city: "上海", eventCount: 321 },
    ],
  };
  const { pageConfig } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? { found: true, profile: { displayName: "HEIMU", sceneCluster: cluster }, events: [], venues: [], collaborators: [] }
      : { items: [], page: { nextCursor: null } },
  });
  pageConfig.name = "HEIMU";
  pageConfig.lang = "zh";
  pageConfig.data = { ...pageConfig.data, t: { loadFailed: "加载失败" } };
  await pageConfig.loadArtist.call(pageConfig);
  const sc = pageConfig.data.atlasProfile.sceneCluster;
  assert.ok(sc, "sceneCluster should be present");
  assert.equal(sc.label, "上海 · All俱乐部");
  assert.equal(sc.members.length, 2);
  assert.equal(sc.members[0].eventCount, 331);

  // null when backend omits it
  const { pageConfig: bare } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? { found: true, profile: { displayName: "Nobody", sceneCluster: null }, events: [], venues: [], collaborators: [] }
      : { items: [], page: { nextCursor: null } },
  });
  bare.name = "Nobody";
  bare.lang = "zh";
  bare.data = { ...bare.data, t: { loadFailed: "加载失败" } };
  await bare.loadArtist.call(bare);
  assert.equal(bare.data.atlasProfile.sceneCluster, null);
});

test("artist page city footprint tap filters performance history to that city and toggles off", async () => {
  const events = [
    { eventId: "e1", title: "A", date: "2025-01-10", venueName: "V1", city: "上海" },
    { eventId: "e2", title: "B", date: "2025-03-12", venueName: "V2", city: "上海市" }, // normalizes to 上海
    { eventId: "e3", title: "C", date: "2025-05-20", venueName: "V3", city: "北京" },
    { eventId: "e4", title: "D", date: "2025-06-01", venueName: "V4", city: "成都" },
  ];
  const { pageConfig } = loadArtistPage({
    requestApi: async (route) => route === "/api/v1/weekly/atlas/artist"
      ? { found: true, profile: { displayName: "Tourer" }, events, venues: [], collaborators: [] }
      : { items: [], page: { nextCursor: null } },
  });
  pageConfig.name = "Tourer";
  pageConfig.lang = "zh";
  pageConfig.data = { ...pageConfig.data, t: { loadFailed: "加载失败" } };
  await pageConfig.loadArtist.call(pageConfig);

  assert.equal(pageConfig.data.cityFilter, "");
  assert.equal(pageConfig.data.visibleAtlasEvents.length, 4, "all history visible by default");

  // Tap 上海 -> 2 events (上海 + 上海市 merge).
  pageConfig.onCityFilter.call(pageConfig, { currentTarget: { dataset: { city: "上海" } } });
  assert.equal(pageConfig.data.cityFilter, "上海");
  assert.equal(pageConfig.data.visibleAtlasEvents.length, 2);
  assert.ok(pageConfig.data.visibleAtlasEvents.every((e) => e.city === "上海" || e.city === "上海市"));

  // Tap 北京 -> switch filter to 1 event.
  pageConfig.onCityFilter.call(pageConfig, { currentTarget: { dataset: { city: "北京" } } });
  assert.equal(pageConfig.data.cityFilter, "北京");
  assert.equal(pageConfig.data.visibleAtlasEvents.length, 1);

  // Tap 北京 again -> clear filter, all visible.
  pageConfig.onCityFilter.call(pageConfig, { currentTarget: { dataset: { city: "北京" } } });
  assert.equal(pageConfig.data.cityFilter, "");
  assert.equal(pageConfig.data.visibleAtlasEvents.length, 4);
});

test("artist page loadArtist consumes real local Atlas HTTP data for Cocoonics", async () => {
  const repoRoot = path.resolve(root, "../..");
  const dir = await mkdtemp(path.join(os.tmpdir(), "artist-page-real-http-"));
  const previousEnv = {
    ATLAS_MINIAPP_PRELOAD: process.env.ATLAS_MINIAPP_PRELOAD,
    ATLAS_MINIAPP_INDEX: process.env.ATLAS_MINIAPP_INDEX,
    ATLAS_DJ_RELATION_TRAJECTORY_LENS: process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS,
    ATLAS_RADIO_PROGRAMS: process.env.ATLAS_RADIO_PROGRAMS,
    ATLAS_RADIO_PROGRAM_MATCH_REVIEW: process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW,
    ATLAS_REQUIRE_SESSION: process.env.ATLAS_REQUIRE_SESSION,
    CROSS_DB_MERGE_MAP: process.env.CROSS_DB_MERGE_MAP,
  };
  let server;
  try {
    const emptyMergeMap = path.join(dir, "empty-merge-map.json");
    await writeFile(emptyMergeMap, JSON.stringify({ db2_to_db3_map: {}, existing_subject_map: {} }), "utf8");

    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = atlasDataPath(repoRoot, "atlas_index.json.gz");
    process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = atlasDataPath(repoRoot, "dj_relation_trajectory_lens.json.gz");
    process.env.ATLAS_RADIO_PROGRAMS = atlasDataPath(repoRoot, "radio_programs_candidate.json.gz");
    delete process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW;
    process.env.ATLAS_REQUIRE_SESSION = "false";
    process.env.CROSS_DB_MERGE_MAP = emptyMergeMap;

    const api = await import(pathToFileURL(path.join(repoRoot, "services/weekly_activity_cloudrun/src/miniappAtlasApi.mjs")).href);
    api.__resetMiniappAtlasApiCachesForTests();
    const serverUrl = pathToFileURL(path.join(repoRoot, "services/weekly_activity_cloudrun/src/server.mjs")).href;
    const { createServer } = await import(`${serverUrl}?artist-page-real-http=${Date.now()}`);
    server = createServer({
      store: {},
      stage7Store: {},
      llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      soundStore: {},
      interviewStore: {},
      env: { ...process.env, ATLAS_REQUIRE_SESSION: "false" },
    });
    const baseUrl = await listen(server);
    const { pageConfig, apiCalls } = loadArtistPage({
      requestApi: async (route, params = {}) => {
        if (route === "/api/v1/weekly/current") return { items: [], page: { nextCursor: null } };
        const url = new URL(route, baseUrl);
        for (const [key, value] of Object.entries(params || {})) {
          if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
        }
        const res = await fetch(url);
        assert.equal(res.status, 200, `${route} should return 200`);
        return res.json();
      },
    });

    pageConfig.name = "Cocoonics";
    pageConfig.subjectId = "dj:cocoonics";
    pageConfig.lang = "zh";
    pageConfig.data = { ...pageConfig.data, t: { loadFailed: "加载失败", sourceLinkCopied: "已复制", openOriginal: "打开原文" } };

    await pageConfig.loadArtist.call(pageConfig);

    assert.equal(pageConfig.data.loading, false);
    assert.equal(pageConfig.data.error, "");
    assert.equal(pageConfig.data.atlasProfile.displayName, "Cocoonics");
    assert.ok(pageConfig.data.atlasEvents.length >= 80);
    assert.ok(pageConfig.data.radioPrograms.length >= 1);
    assert.ok(pageConfig.data.visibleRadioPrograms.length >= 1);
    assert.ok(pageConfig.data.visibleRadioPrograms.length <= 3);
    assert.ok(pageConfig.data.hiddenRadioProgramCount >= 1);
    assert.match(pageConfig.data.radioToggleLabel, /展开全部节目/);
    const visibleRadioBefore = pageConfig.data.visibleRadioPrograms.length;
    pageConfig.toggleRadioPrograms.call(pageConfig);
    assert.equal(pageConfig.data.radioProgramsExpanded, true);
    assert.ok(pageConfig.data.visibleRadioPrograms.length > visibleRadioBefore);
    assert.match(pageConfig.data.radioToggleLabel, /收起节目/);
    assert.equal(
      pageConfig.data.radioPrograms[0].url,
      "https://byyb.live/set/cocoonics-2025-10-19-turbo-x-catnapp-showcase",
    );
    assert.ok(pageConfig.data.relationTrajectory.cities.length >= 1);
    assert.ok(pageConfig.data.relationTrajectory.venues.length >= 1);
    assert.ok(pageConfig.data.relationTrajectory.collaborators.length >= 1);
    assert.equal(apiCalls[0].route, "/api/v1/weekly/atlas/artist");
    assert.equal(apiCalls[0].params.subjectId, "dj:cocoonics");
    assert.equal(apiCalls[1].route, "/api/v1/weekly/current");
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});

test("bio snippet: legacy slug returns real-text bioCandidate with bioCandidateSource when no confirmed bio exists", async () => {
  const repoRoot = path.resolve(root, "../..");
  const dir = await mkdtemp(path.join(os.tmpdir(), "bio-snippet-nisip1d-"));
  const previousEnv = {
    ATLAS_MINIAPP_PRELOAD: process.env.ATLAS_MINIAPP_PRELOAD,
    ATLAS_MINIAPP_INDEX: process.env.ATLAS_MINIAPP_INDEX,
    ATLAS_DJ_BIO_SNIPPETS: process.env.ATLAS_DJ_BIO_SNIPPETS,
    ATLAS_DJ_BIO_CANDIDATES: process.env.ATLAS_DJ_BIO_CANDIDATES,
    CROSS_DB_MERGE_MAP: process.env.CROSS_DB_MERGE_MAP,
  };
  try {
    const emptyMergeMap = path.join(dir, "empty-merge-map.json");
    await writeFile(emptyMergeMap, JSON.stringify({ db2_to_db3_map: {}, existing_subject_map: {} }), "utf8");
    const emptyBioCands = path.join(dir, "empty-bio-cands.jsonl");
    await writeFile(emptyBioCands, "", "utf8");

    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = atlasDataPath(repoRoot, "atlas_index.json.gz");
    process.env.ATLAS_DJ_BIO_SNIPPETS = atlasDataPath(repoRoot, "bio_snippets_accepted.jsonl");
    process.env.ATLAS_DJ_BIO_CANDIDATES = emptyBioCands;
    process.env.CROSS_DB_MERGE_MAP = emptyMergeMap;

    const api = await import(pathToFileURL(path.join(repoRoot, "services/weekly_activity_cloudrun/src/miniappAtlasApi.mjs")).href);
    api.__resetMiniappAtlasApiCachesForTests();

    const result = await api.getArtistById("dj:0159group");
    assert.equal(result.found, true, "0159group must be found");
    assert.equal(result.subjectId, "dj:14d4cb3fda07d37c");
    assert.ok(!result.profile.bio, "0159group has no confirmed bio");
    assert.ok(result.profile.bioCandidate, "0159group should have bioCandidate from snippet file");
    assert.ok(result.profile.bioCandidateSource, "snippet should carry bioCandidateSource");
    assert.ok(result.profile.bioCandidate.includes("Uploading"), "bioCandidate should contain real bio text");
  } finally {
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
    const api = await import(pathToFileURL(path.join(repoRoot, "services/weekly_activity_cloudrun/src/miniappAtlasApi.mjs")).href);
    api.__resetMiniappAtlasApiCachesForTests();
  }
});
