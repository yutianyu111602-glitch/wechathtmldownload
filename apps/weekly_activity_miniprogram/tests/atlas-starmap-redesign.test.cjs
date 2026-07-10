const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");

function loadPage() {
  const pagePath = path.join(root, "pages/atlas-starmap/atlas-starmap.js");
  const previousPage = global.Page;
  const previousWx = global.wx;
  let captured = null;
  global.Page = (definition) => {
    captured = definition;
  };
  global.wx = {
    getStorageSync() { return null; },
    navigateTo() {},
    setStorageSync() {},
    showToast() {},
  };
  delete require.cache[require.resolve(pagePath)];
  require(pagePath);
  global.Page = previousPage;
  global.wx = previousWx;
  assert.ok(captured, "starmap Page definition was captured");
  captured.data = { ...captured.data };
  captured.setData = function setData(next) {
    Object.assign(this.data, next || {});
  };
  return captured;
}

test("ATLAS V2 metric scores are logarithmic and capped at the P99 anchors", () => {
  const page = loadPage();
  assert.equal(page._metricScore(0, 115), 0);
  assert.equal(page._metricScore(115, 115), 1);
  assert.equal(page._metricScore(4308, 115), 1);
});

test("semantic zoom resolves overview, neighborhood, and detail tiers", () => {
  const page = loadPage();
  assert.equal(page._zoomTierForScale(0.8), "overview");
  assert.equal(page._zoomTierForScale(1.5), "neighborhood");
  assert.equal(page._zoomTierForScale(2.6), "detail");
});

test("node visuals encode entity shape, events, relations, and evidence", () => {
  const page = loadPage();
  const dj = page._nodeVisual({ t: "dj", ec: 115, rc: 284, sc: 101, s: 1 });
  assert.equal(dj.shape, "circle");
  assert.equal(dj.color, "#7FD4FF");
  assert.equal(dj.radius, 9);
  assert.equal(dj.haloGap, 7);
  assert.equal(dj.haloRings, 3);
  assert.equal(dj.evidenceTicks, 8);

  assert.equal(page._nodeVisual({ t: "venue", ec: 1, rc: 1, sc: 1 }).shape, "hexagon");
  assert.equal(page._nodeVisual({ t: "org", ec: 1, rc: 1, sc: 1 }).shape, "diamond");
  assert.equal(page._nodeVisual({ t: "series", ec: 1, rc: 1, sc: 1 }).shape, "ring");
});

test("legacy nodes without V2 counts retain a bounded visible radius", () => {
  const page = loadPage();
  const visual = page._nodeVisual({ t: "dj", s: 2.25 });
  assert.ok(Number.isFinite(visual.radius));
  assert.ok(visual.radius >= 3.5 && visual.radius <= 9);
});

test("edge visuals encode relation semantics and logarithmic weight", () => {
  const page = loadPage();
  const edge = page._edgeVisual([0, 1, "collab", 585], true);
  assert.equal(edge.lineWidth, 2.45);
  assert.equal(edge.color, "rgba(127,212,255,0.68)");
  assert.deepEqual(edge.dash, []);
  assert.deepEqual(page._edgeVisual([0, 1, "signed_to", 10], true).dash, [3, 2]);
  assert.equal(page._edgeVisual([0, 1, "b2b", 7759], true).color, "rgba(255,207,107,0.76)");
});

test("overview label ranking uses both event and relation strength", () => {
  const page = loadPage();
  const eventHeavy = page._labelRank({ ec: 115, rc: 0 });
  const relationHeavy = page._labelRank({ ec: 0, rc: 284 });
  assert.ok(eventHeavy > 0);
  assert.ok(relationHeavy > 0);
  assert.notEqual(eventHeavy, relationHeavy);
});

test("cross-type duplicate names include the entity type in labels", () => {
  const page = loadPage();
  page._duplicateNames = { oil: true };
  assert.equal(page._nodeLabel({ n: "OIL", t: "dj" }), "OIL · DJ");
  assert.equal(page._nodeLabel({ n: "OIL", t: "venue" }), "OIL · 场地");
  assert.equal(page._nodeLabel({ n: "Knopha", t: "dj" }), "Knopha");
});

test("canvas runtime preserves weighted edges and uses the visual helpers", () => {
  const source = fs.readFileSync(path.join(root, "pages/atlas-starmap/atlas-starmap.js"), "utf8");
  assert.match(source, /Number\(edge\[3\]\)\s*\|\|\s*1/);
  assert.match(source, /_appendEdge:\s*function\s*\(a,\s*b,\s*t,\s*weight\)/);
  assert.match(source, /this\._edgeVisual\(/);
  assert.match(source, /this\._nodeVisual\(/);
  assert.match(source, /_drawNodeShape/);
  assert.match(source, /_drawLabel/);
  assert.match(source, /_scheduleDraw/);
});

test("progressive exploration state starts hidden and has bounded transitions", () => {
  const page = loadPage();
  assert.equal(page.data.sheetState, "hidden");
  assert.equal(page.data.viewLens, "structure");
  assert.equal(page.data.zoomTier, "overview");
  assert.equal(page.data.toolPanel, "");

  page.setSheetState("peek");
  assert.equal(page.data.sheetState, "peek");
  page.toggleExploreSheet();
  assert.equal(page.data.sheetState, "explore");
  page.toggleExploreSheet();
  assert.equal(page.data.sheetState, "peek");
  page.setSheetState("invalid");
  assert.equal(page.data.sheetState, "hidden");
});

test("selected view model exposes V2 metrics only when the node carries them", () => {
  const page = loadPage();
  page._hidden = {};
  page._hiddenDynamic = {};
  page._expanded = {};
  page._expansionChildren = {};
  page._remoteRows = {};
  page._remoteLoading = {};
  page._remoteError = {};
  page._inspectorCache = {};
  page._inspectorLoading = {};
  page._adj = { 0: [] };
  page._nodes = [{
    u: "dj:knopha", n: "Knopha", t: "dj", c: "上海",
    ec: 619, rc: 1780, sc: 826, fs: "2016-01-01", ls: "2026-06-20",
  }];
  page._updateSelected(0);
  assert.equal(page.data.selected.eventCount, 619);
  assert.equal(page.data.selected.relationCount, 1780);
  assert.equal(page.data.selected.sourceCount, 826);
  assert.equal(page.data.selected.firstSeen, "2016-01-01");
  assert.equal(page.data.selected.lastSeen, "2026-06-20");
  assert.equal(page.data.selected.hasEventCount, true);
  assert.equal(page.data.selected.hasRelationCount, true);
  assert.equal(page.data.selected.hasSourceCount, true);
  assert.equal(page.data.selected.hasTimeRange, true);

  page._nodes = [{ u: "dj:dynamic", n: "Dynamic", t: "dj", c: "", s: 1 }];
  page._updateSelected(0);
  assert.equal(page.data.selected.hasEventCount, false);
  assert.equal(page.data.selected.hasRelationCount, false);
  assert.equal(page.data.selected.hasSourceCount, false);
  assert.equal(page.data.selected.hasTimeRange, false);
});

test("page shell is a full-screen command surface with a 45vh exploration sheet", () => {
  const wxml = fs.readFileSync(path.join(root, "pages/atlas-starmap/atlas-starmap.wxml"), "utf8");
  const wxss = fs.readFileSync(path.join(root, "pages/atlas-starmap/atlas-starmap.wxss"), "utf8");
  assert.match(wxml, /class="sm-command/);
  assert.match(wxml, /class="sm-tool-rail/);
  assert.match(wxml, /class="sm-hud/);
  assert.match(wxml, /sm-sheet-\{\{sheetState\}\}/);
  assert.doesNotMatch(wxml, /data-lens="future"/);
  assert.doesNotMatch(wxml, /data-lens="dj_traj"/);
  assert.match(wxss, /\.sm-sheet-explore\s*\{[^}]*max-height:\s*45vh/s);
});

test("view lenses normalize to structure, city, or time", () => {
  const page = loadPage();
  assert.equal(page._normalizeViewLens("structure"), "structure");
  assert.equal(page._normalizeViewLens("city"), "city");
  assert.equal(page._normalizeViewLens("time"), "time");
  assert.equal(page._normalizeViewLens("entity"), "structure");
  assert.equal(page._normalizeViewLens("future"), "structure");

  page.setViewLens({ currentTarget: { dataset: { lens: "city" } } });
  assert.equal(page.data.viewLens, "city");
  page.setViewLens({ currentTarget: { dataset: { lens: "invalid" } } });
  assert.equal(page.data.viewLens, "structure");
});

test("city lens never treats missing or placeholder cities as evidence", () => {
  const page = loadPage();
  page.data.viewLens = "city";
  assert.equal(page._cityHaloVisible({ c: "上海" }), true);
  assert.equal(page._cityHaloVisible({ c: "" }), false);
  assert.equal(page._cityHaloVisible({ c: "未知" }), false);
  assert.equal(page._cityHaloVisible({ c: "unknown" }), false);
  page.data.viewLens = "structure";
  assert.equal(page._cityHaloVisible({ c: "上海" }), false);
});

test("time lens returns bounded opacity and evidence-backed year ranges", () => {
  const page = loadPage();
  assert.equal(page._timeRangeLabel({ fs: "", ls: "" }), "");
  assert.equal(page._timeRangeLabel({ fs: "2016-01-01", ls: "2026-06-20" }), "2016—2026");
  assert.equal(page._timeRangeLabel({ fs: "2024-02-03", ls: "2024-02-03" }), "2024");
  page.data.viewLens = "time";
  for (const node of [{ ls: "2026-06-20" }, { ls: "2016-01-01" }, { ls: "" }]) {
    const alpha = page._nodeAlphaForLens(node);
    assert.ok(Number.isFinite(alpha));
    assert.ok(alpha >= 0.25 && alpha <= 1);
  }
});

test("share query keeps the lens URL key while reading internal viewLens", () => {
  const page = loadPage();
  page.data = {
    viewLens: "time",
    lens: "entity",
    query: "",
    selected: { id: "dj:knopha", name: "Knopha" },
  };
  const query = page._shareQueryParts().join("&");
  assert.match(query, /lens=time/);
  assert.match(query, /q=Knopha/);
  assert.match(query, /focusId=dj%3Aknopha/);
  assert.doesNotMatch(query, /lens=entity/);
});

test("onLoad restores current and legacy shared lens values", () => {
  const cityPage = loadPage();
  cityPage.onLoad({ lens: "city" });
  cityPage._stopLoadingCycle();
  assert.equal(cityPage.data.viewLens, "city");

  const legacyPage = loadPage();
  legacyPage.onLoad({ lens: "entity" });
  legacyPage._stopLoadingCycle();
  assert.equal(legacyPage.data.viewLens, "structure");
});

test("lens rendering is static and omits missing city or time metadata", () => {
  const source = fs.readFileSync(path.join(root, "pages/atlas-starmap/atlas-starmap.js"), "utf8");
  const wxml = fs.readFileSync(path.join(root, "pages/atlas-starmap/atlas-starmap.wxml"), "utf8");
  const selectNodeBlock = source.slice(source.indexOf("selectNode: function"), source.indexOf("clearSel: function"));
  assert.doesNotMatch(selectNodeBlock, /_startAnim\(/);
  assert.match(source, /this\._nodeAlphaForLens\(node\)/);
  assert.match(wxml, /wx:if="\{\{selected\.city\}\}"/);
  assert.match(wxml, /wx:if="\{\{selected\.hasTimeRange\}\}"/);
  assert.doesNotMatch(wxml, /未知城市/);
});
