const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const {
  buildDetailShare,
  buildDetailTimeline,
  buildIndexShare,
  buildIndexTimeline,
  buildNamedPageShare,
  buildNamedPageTimeline,
  enableShareMenu,
} = require("../utils/share");

function readPageScript(page) {
  return fs.readFileSync(path.join(root, "pages", page, `${page}.js`), "utf8");
}

function pageNameFromPath(pagePath) {
  const parts = pagePath.split("/");
  return parts[parts.length - 1];
}

test("all visible pages expose native WeChat share handlers", () => {
  const appJson = JSON.parse(fs.readFileSync(path.join(root, "app.json"), "utf8"));
  const pages = appJson.pages.map(pageNameFromPath);
  for (const page of pages) {
    if (page === "admin") continue;
    const script = readPageScript(page);
    assert.match(script, /onShareAppMessage\b/, `${page} must enable send-to-friend sharing`);
    assert.match(script, /onShareTimeline\b/, `${page} must enable timeline sharing`);
  }
});

test("detail native share button is backed by page share handler", () => {
  const detailWxml = fs.readFileSync(path.join(root, "pages", "detail", "detail.wxml"), "utf8");
  const detailScript = readPageScript("detail");
  assert.match(detailWxml, /class="share-button[^"]*"[^>]*open-type="share"/);
  assert.doesNotMatch(detailWxml, /class="share-button[^"]*"[^>]*bindtap=/);
  assert.match(detailScript, /buildDetailShare/);
});

test("starmap selected node has a native share button backed by focus payload", () => {
  const starmapWxml = fs.readFileSync(path.join(root, "pages", "atlas-starmap", "atlas-starmap.wxml"), "utf8");
  const starmapScript = fs.readFileSync(path.join(root, "pages", "atlas-starmap", "atlas-starmap.js"), "utf8");
  assert.match(starmapWxml, /class="sm-card-act sm-card-share"[^>]*open-type="share"/);
  assert.doesNotMatch(starmapWxml, /class="sm-card-act sm-card-share"[^>]*bindtap=/);
  assert.match(starmapScript, /_shareQueryParts/);
  assert.match(starmapScript, /focusId=.*encodeURIComponent\(selected\.id\)/);
});

test("column separates send-to-friend button from timeline menu guidance", () => {
  const columnWxml = fs.readFileSync(path.join(root, "pages", "column", "column.wxml"), "utf8");
  const columnScript = readPageScript("column");
  assert.match(columnWxml, /wx:if="{{item\.expanded}}" class="card-share-row"/);
  assert.match(columnWxml, /class="card-share-btn"[^>]*open-type="share"/);
  assert.match(columnWxml, /class="card-share-btn"[^>]*data-id="{{item\.id}}"/);
  assert.match(columnWxml, /class="card-timeline-btn"[^>]*showTimelineShareTip/);
  assert.match(columnWxml, /class="card-timeline-btn"[^>]*data-id="{{item\.id}}"/);
  assert.match(columnWxml, /朋友圈入口在右上角/);
  assert.match(columnScript, /enableShareMenu\(\)/);
  assert.match(columnScript, /onShareTimeline\b/);
  assert.match(columnScript, /highlight: itemId/);
  assert.match(columnScript, /lastExpandedItemId/);
});

test("share menu explicitly enables Moments timeline sharing", () => {
  const calls = [];
  const previousWx = global.wx;
  global.wx = {
    showShareMenu: (payload) => {
      calls.push(payload);
    },
  };

  try {
    enableShareMenu();
  } finally {
    if (previousWx === undefined) {
      delete global.wx;
    } else {
      global.wx = previousWx;
    }
  }

  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].menus, ["shareAppMessage", "shareTimeline"]);
});

test("detail share payload preserves item id, language, title, and poster", () => {
  const item = {
    id: "agg-child loopy 0529",
    displayTitle: "TOMO 高速鼓点",
    dateCompact: "05.29",
    cityLabel: "杭州",
    coverUrl: "https://example.test/poster.jpg",
  };
  const appMessage = buildDetailShare(item, "en");
  const timeline = buildDetailTimeline(item, "en");

  assert.equal(appMessage.title, "TOMO 高速鼓点 · 05.29 杭州");
  assert.equal(appMessage.path, "/pages/detail/detail?id=agg-child%20loopy%200529&lang=en");
  assert.equal(appMessage.imageUrl, "https://example.test/poster.jpg");
  assert.equal(timeline.query, "id=agg-child%20loopy%200529&lang=en");
});

test("index share payload preserves active city and date filters", () => {
  const data = {
    lang: "zh",
    selectedCity: "hangzhou",
    selectedDate: "2026-05-29",
    cityTitle: "杭州",
    datePillLabel: "05.29",
    popularItems: [{ coverUrl: "https://example.test/cover.jpg" }],
  };
  const appMessage = buildIndexShare(data);
  const timeline = buildIndexTimeline(data);

  assert.equal(appMessage.title, "坏DJclub 杭州 05.29 电音活动");
  assert.equal(appMessage.path, "/pages/index/index?lang=zh&city=hangzhou&date=2026-05-29");
  assert.equal(appMessage.imageUrl, "https://example.test/cover.jpg");
  assert.equal(timeline.query, "lang=zh&city=hangzhou&date=2026-05-29");
});

test("named page share payload can preserve stable entity ids", () => {
  const appMessage = buildNamedPageShare(
    "/pages/artist/artist",
    "Cocoonics",
    "zh",
    "相关活动",
    { subjectId: "dj:cocoonics" }
  );
  const timeline = buildNamedPageTimeline(
    "Cocoonics",
    "zh",
    "相关活动",
    { subjectId: "dj:cocoonics" }
  );

  assert.equal(appMessage.title, "Cocoonics 相关活动 - 坏DJclub");
  assert.equal(appMessage.path, "/pages/artist/artist?name=Cocoonics&subjectId=dj%3Acocoonics&lang=zh");
  assert.equal(timeline.query, "name=Cocoonics&subjectId=dj%3Acocoonics&lang=zh");
});
