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
