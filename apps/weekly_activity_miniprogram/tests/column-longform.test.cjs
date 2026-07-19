const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const repoRoot = path.resolve(root, "..", "..");
const { COLUMN_FALLBACK_ITEMS, COLUMN_STYLE_VERSION } = require("../utils/columnFallbackItems");

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function bodyLength(item) {
  return item.paragraphs.join("").replace(/\s+/g, "").length;
}

function loadColumnPage() {
  const filename = path.join(root, "pages", "column", "column.js");
  const code = fs.readFileSync(filename, "utf8");
  let pageConfig = null;
  const modalCalls = [];
  const storage = { weeklyActivityLang: "zh" };
  const sandbox = {
    console: { ...console, warn() {}, error() {} },
    Page(config) {
      pageConfig = config;
    },
    getApp() {
      return { globalData: { cloud: {} } };
    },
    require(request) {
      if (request.endsWith("/i18n")) {
        return {
          applyLanguageChrome: () => {},
          normalizeLang: (value) => (value === "en" ? "en" : "zh"),
          text: () => ({}),
        };
      }
      if (request.endsWith("/haptics")) {
        return { vibrateLight: () => {} };
      }
      if (request.endsWith("/share")) {
        return {
          buildSimpleShare: (title, page, params) => ({ title, path: page, params }),
          buildSimpleTimeline: (title, query) => ({ title, query }),
          enableShareMenu: () => {},
        };
      }
      if (request.endsWith("/columnFallbackItems")) {
        return { COLUMN_FALLBACK_ITEMS: [], COLUMN_STYLE_VERSION: "test-column.v1" };
      }
      if (request.endsWith("/sourceAction")) {
        return { openSourceByHash: () => true, openSourceUrl: () => true };
      }
      if (request.endsWith("/api")) {
        return { requestApi: () => Promise.resolve({ items: [] }) };
      }
      throw new Error(`unexpected require ${request}`);
    },
    wx: {
      getStorageSync(key) { return storage[key]; },
      setStorageSync(key, value) { storage[key] = value; },
      removeStorageSync(key) { delete storage[key]; },
      stopPullDownRefresh() {},
      request() {},
      showModal(payload) { modalCalls.push(payload); },
      setClipboardData() {},
    },
    setTimeout,
    clearTimeout,
  };
  vm.runInNewContext(code, sandbox, { filename });
  pageConfig.setData = function setData(update) {
    this.data = { ...this.data, ...(update || {}) };
  };
  pageConfig.data = { ...pageConfig.data };
  pageConfig.__modalCalls = modalCalls;
  pageConfig.__storage = storage;
  return pageConfig;
}

const FORBIDDEN_READER_WORDS = /倒推|候选|report-only|report only|数据库|serving|DB2|db2|活动包|武器库|选题|身份定论|元数据|搜索引擎/;
// Anti-AI: telltale LLM-essay phrases. A couple tolerable; several = obviously AI.
const AI_TELL_PHRASES = [
  "不是一个标签", "而是因为", "真正要听的", "真正的", "某种程度上", "与其说",
  "恰恰在于", "值得一提", "归根结底", "让我们", "不妨", "总的来说", "不仅仅是", "这意味着", "这说明",
];
function aiTellCount(text) {
  return AI_TELL_PHRASES.filter((p) => String(text || "").includes(p)).length;
}

test("column items are clean readable club-style copy with verifiable external links", () => {
  assert.ok(COLUMN_FALLBACK_ITEMS.length >= 5);

  for (const item of COLUMN_FALLBACK_ITEMS) {
    assert.equal(item.columnStyleVersion, COLUMN_STYLE_VERSION, item.id);
    assert.ok(Array.isArray(item.paragraphs), item.id);
    const isLiveNote = item.writer === "user_live_notes";
    // 3-5 = template fallback short card, 5-9 = MiMo pseudo-documentary longform.
    const maxParagraphs = isLiveNote ? 60 : 9;
    assert.ok(item.paragraphs.length >= 3 && item.paragraphs.length <= maxParagraphs, item.id);
    const minBodyLength = item.columnStyleVersion === "electronic-column-source-backed-dj-profiles.v1" ? 350 : 450;
    assert.ok(bodyLength(item) >= minBodyLength, item.id);
    assert.ok(bodyLength(item) <= 2600, item.id);
    assert.ok(item.summary.length < bodyLength(item), item.id);
    if (!isLiveNote) {
      assert.ok(item.deck && item.deck.length > 0, item.id);
    }
    if (item.isFeature) {
      // Character feature (DB-sourced profile, no current gig): cite local archive.
      assert.ok(item.references && item.references.length >= 1, item.id);
    } else {
      assert.ok(item.foreignMedia || item.soundcloud || item.bandcamp || item.mixcloud || item.spotify || item.residentAdvisor || item.instagram || item.eventUrl, item.id);
      assert.ok(item.sourceHash || item.sourceDetailId, item.id);
      const hasWeChatEventUrl = item.eventUrl && /^https:\/\/mp\.weixin\.qq\.com\/s\//.test(item.eventUrl);
      const hasVerifiedPublicReference = item.sourceVerified === true && /^https?:\/\//.test(item.eventUrl || "");
      assert.ok(hasWeChatEventUrl || hasVerifiedPublicReference, item.id);
    }
    assert.doesNotMatch(item.body, FORBIDDEN_READER_WORDS, item.id);
    assert.ok(aiTellCount(item.body) < 2, item.id + " reads too AI (" + aiTellCount(item.body) + " tells)");
    assert.equal(item.readTimeLabel, undefined, item.id);
  }
});

test("column page renders paragraph body without forced longform expansion", () => {
  const columnJs = read("pages/column/column.js");
  const columnWxml = read("pages/column/column.wxml");
  const columnWxss = read("pages/column/column.wxss");

  assert.match(columnJs, /COLUMN_FALLBACK_ITEMS/);
  assert.match(columnJs, /normalizeParagraphs/);
  assert.match(columnJs, /hasLongformItems/);
  assert.match(columnJs, /shortform/);
  assert.match(columnJs, /openSourceByHash/);
  assert.match(columnJs, /openEventSource/);
  assert.match(columnJs, /requestColumnViaCloudContainer/);
  assert.match(columnJs, /requestColumnViaPublicApi/);
  assert.match(columnJs, /callContainer/);
  assert.match(columnJs, /X-WX-SERVICE/);
  assert.match(columnJs, /fallback to local cache/);
  assert.match(columnJs, /EXTERNAL_LINK_SPECS/);
  assert.match(columnJs, /sanitizeToneSource/);
  assert.match(columnJs, /primaryLinks/);
  assert.match(columnJs, /evidenceExpanded/);
  assert.match(columnJs, /applyFoldLabels/);
  assert.match(columnJs, /bodyToggleLabel/);
  assert.match(columnJs, /evidenceToggleLabel/);
  assert.match(columnJs, /onBodyToggle/);
  assert.match(columnJs, /onEvidenceToggle/);
  assert.match(columnJs, /relatedDj/);
  assert.doesNotMatch(columnJs, /var HARDCODED_ITEMS = \[/);
  assert.match(columnWxml, /wx:for="{{item\.paragraphs}}"/);
  assert.match(columnWxml, /class="card-paragraph"/);
  assert.match(columnWxml, /先看标题和相关 DJ/);
  assert.match(columnWxml, /item\.relatedDj/);
  assert.match(columnWxml, /class="card-header"[\s\S]*catchtap="onBodyToggle"/);
  assert.match(columnWxml, /onBodyToggle/);
  assert.match(columnWxml, /onEvidenceToggle/);
  assert.match(columnWxml, /wx:if="{{!item\.expanded}}"[\s\S]*item\.bodyToggleLabel/);
  assert.match(columnWxml, /item\.evidenceToggleLabel/);
  assert.match(columnWxml, /wx:if="{{item\.expanded && item\.evidenceExpanded && item\.hasEvidencePanel}}"/);
  assert.match(columnWxml, /item\.primaryLinks/);
  assert.match(columnWxml, /item\.moreLinks/);
  assert.match(columnWxml, /item\.trackPreview/);
  assert.match(columnWxml, /item\.referencePreview/);
  assert.match(columnWxml, /item\.cleanToneSource/);
  assert.match(columnWxml, /item\.sourceHash/);
  assert.doesNotMatch(columnWxml, /item\.readTimeLabel/);
  assert.doesNotMatch(columnWxml, /item\.toneSource/);
  assert.match(columnWxss, /\.card-long-body/);
  assert.match(columnWxss, /\.card-paragraph/);
  assert.match(columnWxss, /\.card-dj-line/);
  assert.match(columnWxss, /\.card-body-toggle/);
  assert.match(columnWxss, /\.evidence-toggle/);
  assert.match(columnWxss, /\.card-evidence/);
  assert.match(columnWxss, /\.card-header-hover/);
  assert.match(columnWxss, /\.timeline-share-tip/);
});

test("column page keeps title, article body, and evidence as separate layers", () => {
  const pageConfig = loadColumnPage();
  const item = {
    id: "column-a",
    expanded: false,
    evidenceExpanded: false,
    evidenceCount: 4,
    bodyToggleLabel: "展开正文",
    evidenceToggleLabel: "展开来源 / 外链 / 采访 / 作品（4）",
  };
  pageConfig.data = {
    ...pageConfig.data,
    lang: "zh",
    items: [item],
    filteredItems: [item],
    lastExpandedItemId: "",
  };

  pageConfig.onBodyToggle.call(pageConfig, { currentTarget: { dataset: { id: "column-a" } } });

  assert.equal(pageConfig.data.items[0].expanded, true);
  assert.equal(pageConfig.data.items[0].evidenceExpanded, false);
  assert.equal(pageConfig.data.items[0].bodyToggleLabel, "收起正文");
  assert.match(pageConfig.data.items[0].evidenceToggleLabel, /^展开来源/);

  pageConfig.onEvidenceToggle.call(pageConfig, { currentTarget: { dataset: { id: "column-a" } } });

  assert.equal(pageConfig.data.items[0].expanded, true);
  assert.equal(pageConfig.data.items[0].evidenceExpanded, true);
  assert.equal(pageConfig.data.items[0].evidenceToggleLabel, "收起资料入口");

  pageConfig.onBodyToggle.call(pageConfig, { currentTarget: { dataset: { id: "column-a" } } });

  assert.equal(pageConfig.data.items[0].expanded, false);
  assert.equal(pageConfig.data.items[0].evidenceExpanded, false);
  assert.equal(pageConfig.data.items[0].bodyToggleLabel, "展开正文");
});

test("column card sharing preserves the highlighted article for friends and timeline", () => {
  const pageConfig = loadColumnPage();
  const item = {
    id: "column-a",
    title: "Knopha · 地下脉冲",
    expanded: true,
    evidenceExpanded: false,
  };
  pageConfig.data = {
    ...pageConfig.data,
    lang: "zh",
    items: [item],
    filteredItems: [item],
    pendingHighlightId: "",
    lastExpandedItemId: "",
  };

  const appMessage = pageConfig.onShareAppMessage.call(pageConfig, {
    target: { dataset: { id: item.id, title: item.title } },
  });

  assert.equal(appMessage.title, item.title);
  assert.equal(appMessage.path, "/pages/column/column");
  assert.equal(appMessage.params.lang, "zh");
  assert.equal(appMessage.params.highlight, item.id);

  pageConfig.showTimelineShareTip.call(pageConfig, {
    currentTarget: { dataset: { id: item.id } },
  });

  assert.equal(pageConfig.data.lastExpandedItemId, item.id);
  assert.equal(pageConfig.__modalCalls.length, 1);
  assert.equal(pageConfig.__modalCalls[0].title, "分享到朋友圈");
  assert.match(pageConfig.__modalCalls[0].content, /右上角/);

  const timeline = pageConfig.onShareTimeline.call(pageConfig);

  assert.equal(timeline.title, item.title);
  assert.equal(timeline.query.lang, "zh");
  assert.equal(timeline.query.highlight, item.id);
});

test("column highlight route opens the target article with synchronized fold labels", async () => {
  const pageConfig = loadColumnPage();

  pageConfig.onLoad.call(pageConfig, { highlight: "col_atlas_plan_preview" });
  await new Promise((resolve) => setTimeout(resolve, 20));

  const highlighted = pageConfig.data.items.find((item) => item.id === "col_atlas_plan_preview");
  assert.ok(highlighted, "expected Atlas preview item to be injected for highlight proof");
  assert.equal(highlighted.expanded, true);
  assert.equal(highlighted.evidenceExpanded, false);
  assert.equal(highlighted.bodyToggleLabel, "收起正文");
  assert.match(highlighted.evidenceToggleLabel, /^展开来源/);
  assert.equal(pageConfig.data.lastExpandedItemId, "col_atlas_plan_preview");
});

test("column tabBar fallback consumes stored highlight once and expands target article", async () => {
  const pageConfig = loadColumnPage();
  pageConfig.__storage["weeklyActivityColumnHighlight:v1"] = {
    highlight: "col_atlas_plan_preview",
    lang: "zh",
    createdAt: Date.now(),
  };

  pageConfig.onLoad.call(pageConfig, {});
  await new Promise((resolve) => setTimeout(resolve, 20));

  const highlighted = pageConfig.data.items.find((item) => item.id === "col_atlas_plan_preview");
  assert.ok(highlighted, "expected stored highlight to select Atlas preview");
  assert.equal(highlighted.expanded, true);
  assert.equal(highlighted.evidenceExpanded, false);
  assert.equal(highlighted.bodyToggleLabel, "收起正文");
  assert.equal(pageConfig.data.activeTag, "all");
  assert.equal(pageConfig.data.lastExpandedItemId, "col_atlas_plan_preview");
  assert.equal(pageConfig.__storage["weeklyActivityColumnHighlight:v1"], undefined);
});

test("CloudRun current column release has a valid reader-facing package contract", () => {
  const currentReleaseDir = path.resolve(
    process.env.HUAIDJ_WEEKLY_CURRENT_RELEASE_DIR
      || path.join(repoRoot, "services", "weekly_activity_cloudrun", "data", "current_release")
  );
  const columnJsonPath = path.join(currentReleaseDir, "column.json");
  const release = JSON.parse(fs.readFileSync(columnJsonPath, "utf8"));

  if (release.backend_only === true) {
    assert.equal(release.frontend_fallback_updated, false);
    assert.equal(release.column_style_version, "electronic-column-source-backed-dj-profiles.v1");
    assert.equal(release.item_count, release.items.length);
    for (const actual of release.items) {
      assert.equal(actual.columnStyleVersion, release.column_style_version, actual.id);
      assert.ok(Array.isArray(actual.paragraphs) && actual.paragraphs.length >= 3, actual.id);
      assert.equal(actual.body, actual.paragraphs.join("\n\n"));
      assert.ok(actual.bodyCharCount >= 350, actual.id);
      assert.ok(actual.bodyCharCount <= 2600, actual.id);
      assert.ok(actual.eventUrl || actual.residentAdvisor, actual.id);
      assert.ok(actual.sourceHash || actual.sourceDetailId, actual.id);
      assert.ok(actual.references && actual.references.length >= 4, actual.id);
      assert.doesNotMatch(actual.body, FORBIDDEN_READER_WORDS, actual.id);
      assert.equal(actual.readTimeLabel, undefined);
    }
    return;
  }

  assert.equal(release.column_style_version, COLUMN_STYLE_VERSION);
  assert.equal(release.item_count, COLUMN_FALLBACK_ITEMS.length);
  assert.equal(release.items.length, COLUMN_FALLBACK_ITEMS.length);

  for (let index = 0; index < COLUMN_FALLBACK_ITEMS.length; index += 1) {
    const expected = COLUMN_FALLBACK_ITEMS[index];
    const actual = release.items[index];
    assert.equal(actual.id, expected.id);
    assert.deepEqual(actual.paragraphs, expected.paragraphs);
    assert.equal(actual.body, expected.paragraphs.join("\n\n"));
    assert.equal(actual.bodyCharCount, expected.bodyCharCount);
    assert.ok(actual.bodyCharCount >= 450, actual.id);
    assert.ok(actual.bodyCharCount <= 2600, actual.id);
    assert.doesNotMatch(actual.body, FORBIDDEN_READER_WORDS, actual.id);
    assert.equal(actual.readTimeLabel, undefined);
  }
});
