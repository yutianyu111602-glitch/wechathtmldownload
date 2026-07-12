const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");

function read(rel) {
  return fs.readFileSync(path.join(root, rel), "utf8");
}

function loadStarmapPage() {
  const pagePath = path.join(root, "pages/atlas-starmap/atlas-starmap.js");
  const previousPage = global.Page;
  const previousWx = global.wx;
  let captured = null;
  global.Page = (definition) => {
    captured = definition;
  };
  global.wx = {
    showToast() {},
    navigateTo() {},
  };
  delete require.cache[require.resolve(pagePath)];
  require(pagePath);
  global.Page = previousPage;
  global.wx = previousWx;
  assert.ok(captured, "starmap Page definition was captured");
  return captured;
}

test("atlas search page is routed and linked from the saved/atlas entry", () => {
  const app = JSON.parse(read("app.json"));
  assert.ok(app.pages.includes("pages/atlas-search/atlas-search"), "app.json registers atlas-search page");

  const savedJs = read("pages/saved/saved.js");
  const savedWxml = read("pages/saved/saved.wxml");
  assert.match(savedJs, /openAtlasSearch\(\)/, "saved page exposes openAtlasSearch handler");
  assert.match(savedJs, /\/pages\/atlas-search\/atlas-search/, "saved page navigates to search page");
  assert.match(savedWxml, /搜索图鉴/, "saved page has a visible atlas search entry");
});

test("atlas search page calls the global subject search endpoint and routes results", () => {
  const js = read("pages/atlas-search/atlas-search.js");
  const wxml = read("pages/atlas-search/atlas-search.wxml");

  assert.match(js, /\/api\/v1\/weekly\/atlas\/search/, "search page uses the backend global atlas search API");
  assert.match(js, /\/pages\/artist\/artist\?name=/, "DJ results route to DJ detail");
  assert.match(js, /subjectId=\$\{subjectId\}/, "DJ results preserve the canonical subject id");
  assert.match(js, /\/pages\/venue\/venue\?name=/, "venue results route to venue detail");
  assert.match(js, /\/pages\/atlas-starmap\/atlas-starmap\?q=/, "org/series results route to starmap focus");
  assert.match(js, /onShareAppMessage/, "search page supports send-to-friend sharing");
  assert.match(js, /onShareTimeline/, "search page supports timeline sharing");
  assert.match(js, /\{ q, type \}/, "search share payload preserves q/type");
  assert.match(wxml, /bindconfirm="onSearchConfirm"/, "search input supports keyboard search");
  assert.match(wxml, /wx:for="\{\{results\}\}"/, "search page renders a result list");
});

test("starmap bundles and L1 expansion contract are wired locally", () => {
  const overview = JSON.parse(read("data/atlas_starmap.json"));
  const neighbors = JSON.parse(read("data/atlas_starmap_neighbors.json"));
  const overviewJs = read("data/atlas_starmap.js");
  const neighborsJs = read("data/atlas_starmap_neighbors.js");
  const js = read("pages/atlas-starmap/atlas-starmap.js");
  const wxml = read("pages/atlas-starmap/atlas-starmap.wxml");

  assert.ok(Array.isArray(overview.nodes) && overview.nodes.length > 0, "overview bundle has nodes");
  assert.equal(overview.schemaVersion, "atlas.mp.starmap.v2", "overview bundle uses the V2 visual contract");
  assert.ok(overview.nodes.every((node) => ["ec", "rc", "sc", "fs", "ls"].every((key) => key in node)), "overview nodes carry compact V2 metrics");
  assert.ok(overview.edges.every((edge) => edge.length === 4 && Number.isFinite(edge[3])), "overview edges carry numeric weight in the fourth position");
  assert.ok(neighbors.byNode && typeof neighbors.byNode === "object", "neighbor bundle has byNode index");
  assert.match(overviewJs, /module\.exports\s*=/, "overview bundle has a WeChat runtime JS wrapper");
  assert.match(neighborsJs, /module\.exports\s*=/, "neighbor bundle has a WeChat runtime JS wrapper");
  const sample = overview.nodes.find((node) => node.u && Array.isArray(neighbors.byNode[node.u]) && neighbors.byNode[node.u].length);
  assert.ok(sample, "at least one overview node has L1 neighbors");
  assert.ok(neighbors.byNode[sample.u][0].u, "neighbor rows carry subject id");

  assert.match(js, /atlas_starmap_neighbors\.js/, "starmap requires the WeChat runtime neighbor bundle");
  assert.doesNotMatch(js, /require\([^)]*atlas_starmap(?:_neighbors)?\.json/, "starmap does not require raw JSON at runtime");
  assert.match(js, /\/api\/v1\/weekly\/atlas\/neighborhood/, "starmap can fetch server-side full-library neighborhoods");
  assert.match(js, /_expandNodeRemote/, "starmap implements remote expansion fallback");
  assert.match(js, /_loadSelectedInspector/, "starmap loads a DJ inspector for selected nodes");
  assert.match(js, /\/api\/v1\/weekly\/atlas\/artist/, "starmap inspector uses the artist DTO endpoint");
  assert.match(js, /subjectId:\s*id/, "starmap inspector fetches by subjectId, not fuzzy name");
  assert.match(js, /cacheBust:\s*"starmap-inspector-20260624b"/, "starmap inspector avoids stale artist cache entries");
  assert.match(js, /relationTrajectory/, "starmap inspector consumes relation trajectory data when available");
  assert.match(js, /_inspectorFromPayload/, "starmap inspector falls back to payload-derived summary for non-trajectory DJs");
  assert.match(js, /_initCanvas/, "starmap retries native canvas initialization");
  assert.match(js, /canvasError/, "starmap exposes canvas initialization failure instead of permanent loading");
  assert.match(js, /_expandNode/, "starmap implements L1 expansion");
  assert.match(js, /_collapseNode/, "starmap implements collapse");
  assert.match(js, /_hiddenDynamic/, "starmap tracks dynamic node visibility");
  assert.match(js, /_relatedPreview/, "starmap builds a visible next-hop preview for exploration");
  assert.match(js, /_neighborhoodStatus/, "starmap explains whether the selected neighborhood is overview or full-library data");
  assert.match(js, /_relatedScore/, "starmap ranks next-hop rows before previewing them");
  assert.match(js, /rankScore/, "starmap consumes server-side rankScore for remote neighborhoods");
  assert.match(js, /scoreHint/, "starmap exposes a compact reason for stronger next-hop rows");
  assert.match(js, /_relatedFilters/, "starmap builds type filters for next-hop exploration");
  assert.match(js, /onRelatedFilter/, "starmap can filter next-hop rows by entity type");
  assert.match(js, /focusRelatedNode/, "starmap lets users focus a related node from the selected card");
  assert.match(js, /explorationTrail/, "starmap keeps an exploration trail for L2 navigation");
  assert.match(js, /backTrail/, "starmap can return to the previous exploration node");
  assert.match(js, /_shareQueryParts/, "starmap share payload is built through one contract helper");
  assert.match(js, /focusId=.*encodeURIComponent\(selected\.id\)/, "starmap share payload preserves the selected subject id");
  assert.match(js, /ATLAS 星图 · /, "starmap share title names the selected node");
  assert.match(js, /relationLabel/, "starmap labels relation types in the next-hop preview");
  assert.match(js, /selected:\s*\{\s*id:\s*n\.u/, "selected card keeps the subject id");
  assert.match(js, /relatedPreview:\s*this\._relatedPreview\(i,\s*rows,\s*activeFilter\)/, "selected card carries filtered next-hop preview rows");
  assert.match(js, /subjectId=.*encodeURIComponent\(sel\.id\)/, "DJ detail navigation preserves subjectId");
  assert.match(wxml, /ATLAS 速览/, "selected DJ card renders the compact inspector");
  assert.match(wxml, /selected\.inspector\.cityLine/, "inspector renders city trajectory");
  assert.match(wxml, /selected\.inspector\.collaboratorLine/, "inspector renders related DJs");
  assert.match(wxml, /selected\.expandHint/, "selected card explains expansion state");
  assert.match(wxml, /selected\.neighborhoodStatus/, "selected card renders the neighborhood source/scale state");
  assert.match(wxml, /探索下一跳/, "selected card exposes a next-hop exploration section");
  assert.match(wxml, /selected\.relatedFilters/, "selected card renders next-hop type filters");
  assert.match(wxml, /sm-path-filter/, "next-hop filters use compact filter controls");
  assert.match(wxml, /catchtap="onRelatedFilter"/, "next-hop filter taps do not trigger row navigation");
  assert.match(wxml, /selected\.relatedPreview/, "selected card renders preview rows for related nodes");
  assert.match(wxml, /bindtap="focusRelatedNode"/, "related preview rows are tap targets");
  assert.match(wxml, /explorationTrail/, "selected card renders the exploration trail");
  assert.match(wxml, /bindtap="backTrail"/, "exploration trail exposes a previous-hop action");
  assert.match(wxml, /class="sm-card-act sm-card-share"[^>]*open-type="share"/, "selected card exposes a native share button");
  assert.match(wxml, /openAtlasSearch/, "starmap links to global atlas search");
  assert.match(wxml, /class="sm-command/, "starmap uses the compact command bar");
  assert.match(wxml, /class="sm-tool-rail/, "starmap uses the right-side tool rail");
  assert.match(wxml, /sm-sheet-\{\{sheetState\}\}/, "starmap uses the progressive bottom sheet");
  assert.doesNotMatch(wxml, /data-lens="future"|data-lens="dj_traj"/, "unfinished lens placeholders are absent");
  assert.match(js, /this\._scheduleDraw\(\)/, "touch movement uses a coalesced canvas draw");
  const selectNodeBlock = js.slice(js.indexOf("selectNode: function"), js.indexOf("clearSel: function"));
  assert.doesNotMatch(selectNodeBlock, /_startAnim\(/, "selecting a node does not start the retired ambient animation loop");
  // A<->B path-finding
  assert.match(js, /startPathMode/, "starmap arms A<->B path-finding from the selected node");
  assert.match(js, /\/api\/v1\/weekly\/atlas\/path/, "path-finding calls the backend path endpoint");
  assert.match(js, /_pickPathTarget/, "starmap picks a path target on the next node tap");
  assert.match(js, /clearPath/, "starmap can dismiss the path result");
  assert.match(wxml, /catchtap="startPathMode"/, "selected card exposes a find-path action");
  assert.match(wxml, /class="sm-pathchain"/, "path result renders a relation chain");
  assert.match(wxml, /pathResult\.chain/, "path chain iterates resolved nodes");
});

test("starmap share payload preserves the selected node focus", () => {
  const page = loadStarmapPage();

  page.data = {
    viewLens: "structure",
    lens: "entity",
    query: "",
    selected: { id: "dj:knopha", name: "Knopha" },
  };

  const appShare = page.onShareAppMessage();
  assert.equal(appShare.title, "ATLAS 星图 · Knopha");
  assert.match(appShare.path, /^\/pages\/atlas-starmap\/atlas-starmap\?/);
  assert.match(appShare.path, /lens=structure/);
  assert.match(appShare.path, /q=Knopha/);
  assert.match(appShare.path, /focusId=dj%3Aknopha/);

  const timelineShare = page.onShareTimeline();
  assert.equal(timelineShare.title, "ATLAS 星图 · Knopha");
  assert.match(timelineShare.query, /lens=structure/);
  assert.match(timelineShare.query, /q=Knopha/);
  assert.match(timelineShare.query, /focusId=dj%3Aknopha/);

  page.data = {
    viewLens: "city",
    lens: "overview",
    query: "Elevator",
    selected: null,
  };
  const genericShare = page.onShareAppMessage();
  assert.equal(genericShare.title, "ATLAS 全景星图");
  assert.match(genericShare.path, /lens=city/);
  assert.match(genericShare.path, /q=Elevator/);
  assert.doesNotMatch(genericShare.path, /focusId=/);
});

test("starmap can restore the selected node from shared focusId", () => {
  const page = loadStarmapPage();
  page.data = {};
  page.setData = function setData(update) {
    this.data = { ...this.data, ...update };
  };
  page.draw = function draw() {};
  page._flyToNode = function flyToNode(index) {
    this._flewTo = index;
  };
  page._loadSelectedInspector = function loadSelectedInspector() {};
  page._expandNode = function expandNode() { return false; };

  page.onLoad({ lens: "entity", q: "Knopha", focusId: "dj%3Aknopha" });
  assert.equal(page._initialQuery, "Knopha");
  assert.equal(page._initialFocusId, "dj:knopha");
  assert.equal(page.data.viewLens, "structure", "legacy entity lens restores as structure");

  const hit = page._findNode(page._initialFocusId, page._initialQuery);
  assert.ok(hit >= 0, "shared focusId resolves to an overview node");
  assert.equal(page._nodes[hit].u, "dj:knopha");

  page._focusInitial();
  assert.equal(page.data.selected.id, "dj:knopha");
  assert.equal(page.data.selected.name, "Knopha");
  assert.equal(page._flewTo, hit);
});

test("starmap next-hop preview can focus a related node", () => {
  const page = loadStarmapPage();
  page.data = { selected: null, nodeCount: 0, relatedFilter: "all" };
  page.setData = function setData(update) {
    this.data = { ...this.data, ...update };
  };
  page.draw = function draw() {
    this._didDraw = true;
  };
  page._flyToNode = function flyToNode(index) {
    this._flewTo = index;
  };
  page._loadSelectedInspector = function loadSelectedInspector() {};
  page._expandNode = function expandNode() { return false; };

  page._nodes = [
    { i: 0, u: "dj:alpha", n: "Alpha", t: "dj", c: "上海", x: 0, y: 0, s: 1, col: "#7fd4ff" },
    { i: 1, u: "venue:elevator", n: "Elevator", t: "venue", c: "上海", x: 0.2, y: 0.1, s: 1, col: "#ffcf6b" },
    { i: 2, u: "dj:beta", n: "Beta", t: "dj", c: "北京", x: -0.2, y: -0.1, s: 1, col: "#7fd4ff" },
  ];
  page._edges = [[0, 1, "held_at"], [0, 2, "collab"]];
  page._adj = { 0: [1, 2], 1: [0], 2: [0] };
  page._nodeIndexById = { "dj:alpha": 0, "venue:elevator": 1, "dj:beta": 2 };
  page._hidden = {};
  page._hiddenDynamic = {};
  page._expanded = {};
  const rows = [
    { u: "venue:elevator", n: "Elevator", t: "venue", c: "上海", rt: "held_at", w: 420, rs: 5.1 },
    { u: "dj:beta", n: "Beta", t: "dj", c: "北京", rt: "collab", w: 1800, rs: 6.7 },
  ];
  page._remoteRows = { "dj:alpha": rows };
  page._remoteLoading = {};
  page._remoteError = {};
  page._inspectorCache = {};
  page._inspectorLoading = {};
  page._trail = [page._trailItem(0)];

  const preview = page._relatedPreview(0, rows);
  assert.equal(preview.length, 2);
  assert.equal(preview[0].id, "dj:beta", "highest-ranked next hop is shown first even when input rows are unsorted");
  assert.match(preview[0].meta, /强关联/);
  assert.equal(preview[1].id, "venue:elevator");
  assert.match(preview[1].meta, /场地/);
  assert.match(preview[1].meta, /举办/);

  const filterCounts = page._relatedFilters(page._relatedItems(0, rows), "all");
  assert.deepEqual(filterCounts.map((item) => [item.k, item.count]), [["all", 2], ["dj", 1], ["venue", 1]]);

  page._sel = 0;
  page._updateSelected(0);
  assert.equal(page.data.selected.neighborhoodStatus, "全库邻域 2 条");
  assert.deepEqual(page.data.selected.relatedPreview.map((item) => item.id), ["dj:beta", "venue:elevator"]);

  page.onRelatedFilter({ currentTarget: { dataset: { k: "venue" } } });
  assert.equal(page.data.relatedFilter, "venue");
  assert.deepEqual(page.data.selected.relatedPreview.map((item) => item.id), ["venue:elevator"]);

  page.onRelatedFilter({ currentTarget: { dataset: { k: "dj" } } });
  assert.equal(page.data.relatedFilter, "dj");
  assert.deepEqual(page.data.selected.relatedPreview.map((item) => item.id), ["dj:beta"]);

  page._sel = 0;
  page._didDraw = false;
  page.focusRelatedNode({ currentTarget: { dataset: { id: "venue:elevator" } } });
  assert.equal(page._sel, 1);
  assert.equal(page.data.selected.id, "venue:elevator");
  assert.deepEqual(page.data.explorationTrail.map((item) => item.id), ["dj:alpha", "venue:elevator"]);
  assert.equal(page._flewTo, 1);
  assert.equal(page._didDraw, true);

  page.backTrail();
  assert.equal(page._sel, 0);
  assert.equal(page.data.selected.id, "dj:alpha");
  assert.deepEqual(page.data.explorationTrail.map((item) => item.id), ["dj:alpha"]);
});

test("starmap inspector falls back to a payload-derived city footprint for non-trajectory DJs", () => {
  const page = loadStarmapPage();

  // Curated trajectory present -> uses the trajectory lens.
  const withTrajectory = page._artistInspector({
    profile: { relationTrajectory: { cities: [{ city: "上海" }, { city: "北京" }], counts: { cities: 2 } } },
  });
  assert.equal(withTrajectory.status, "ready");
  assert.match(withTrajectory.cityLine, /上海/);

  // No trajectory -> build a summary from the payload's own events/venues/collaborators.
  const fallback = page._artistInspector({
    profile: {},
    events: [
      { title: "E1", city: "成都" }, { title: "E2", city: "成都市" }, { title: "E3", city: "成都" },
      { title: "E4", city: "上海" }, { title: "E5", city: "未知" },
    ],
    venues: [{ venueName: "TAG" }, { venueName: "ALL" }],
    collaborators: [{ displayName: "Beta" }],
  });
  assert.equal(fallback.status, "ready");
  assert.match(fallback.cityLine, /^成都 3/, "成都 (with 成都市 merged) ranks first");
  assert.ok(fallback.cityLine.indexOf("上海 1") >= 0, "上海 included with its count");
  assert.ok(fallback.cityLine.indexOf("未知") < 0, "placeholder city filtered out");
  assert.match(fallback.venueLine, /TAG/);
  assert.match(fallback.collaboratorLine, /Beta/);
  assert.match(fallback.summary, /城/);

  // No events/venues/collaborators -> empty.
  const empty = page._artistInspector({ profile: {}, events: [], venues: [], collaborators: [] });
  assert.equal(empty.status, "empty");
});

test("starmap fallback states preserve local rows, node metrics, selection, and camera", () => {
  const page = loadStarmapPage();
  page.data = { selected: null, relatedFilter: "all", sheetState: "explore" };
  page.setData = function setData(update) { this.data = { ...this.data, ...update }; };
  page._nodes = [{
    i: 0, u: "dj:fallback", n: "Fallback", t: "dj", c: "上海", x: 0, y: 0,
    ec: 12, rc: 34, sc: 8, fs: "2020-01-01", ls: "2026-01-01",
  }];
  page._adj = { 0: [] };
  page._hidden = {};
  page._hiddenDynamic = {};
  page._expanded = {};
  page._remoteRows = {};
  page._remoteLoading = {};
  page._remoteError = { "dj:fallback": true };
  page._inspectorCache = {};
  page._inspectorLoading = {};
  page._neighborRows = function neighborRows() {
    return [{ u: "venue:local", n: "Local", t: "venue", c: "上海", rt: "held_at", w: 20, rs: 2 }];
  };

  page._updateSelected(0);
  assert.equal(page.data.selected.relatedPreview.length, 1, "local next-hop row survives a remote failure state");
  assert.equal(page.data.selected.neighborhoodStatus, "全库邻域暂不可用");
  assert.equal(page.data.selected.eventCount, 12);

  page._setSelectedInspector("dj:fallback", { status: "error", summary: "ATLAS 速览暂不可用" });
  assert.equal(page.data.selected.inspector.status, "error");
  assert.equal(page.data.selected.eventCount, 12, "inspector failure keeps V2 node metrics");

  page._ox = 31; page._oy = 42; page._scale = 1.7;
  page.data.pathResult = { status: "error" };
  page.clearPath();
  assert.equal(page.data.selected.id, "dj:fallback", "path failure dismissal keeps the selected node");
  assert.deepEqual([page._ox, page._oy, page._scale], [31, 42, 1.7], "path failure dismissal keeps the camera");
  assert.equal(page.data.sheetState, "peek");
});

test("starmap path-finding arms from the selected node and dispatches on the next distinct node tap", () => {
  const page = loadStarmapPage();
  const prevWx = global.wx;
  global.wx = { showToast() {}, vibrateShort() {} };
  try {
  page.data = {};
  page.setData = function setData(update) { this.data = { ...this.data, ...update }; };
  page.draw = function draw() {};

  // Arm from the selected node.
  page.data.selected = { id: "dj:alpha", name: "Alpha" };
  page.startPathMode();
  assert.equal(page.data.pathMode, true);
  assert.equal(page._pathFrom, "dj:alpha");
  assert.match(page.data.pathHint, /Alpha/);

  page._nodes = [{ u: "dj:alpha", n: "Alpha" }, { u: "dj:beta", n: "Beta" }];
  let dispatched = null;
  page._fetchPath = function (from, fromName, to, toName) { dispatched = { from, fromName, to, toName }; };

  // Tapping the same node is rejected (stay armed, no dispatch).
  page._pathMode = true;
  page._pickPathTarget(0);
  assert.equal(dispatched, null);

  // Tapping a distinct node dispatches the query and exits path mode.
  page._pickPathTarget(1);
  assert.deepEqual(dispatched, { from: "dj:alpha", fromName: "Alpha", to: "dj:beta", toName: "Beta" });
  assert.equal(page.data.pathMode, false);

  // clearPath wipes any result.
  page.data.pathResult = { status: "ready" };
  page.clearPath();
  assert.equal(page.data.pathResult, null);
  } finally {
    global.wx = prevWx;
  }
});

test("artist detail can request Atlas profile by subjectId", () => {
  const js = read("pages/artist/artist.js");
  assert.match(js, /this\.subjectId\s*=\s*decodeURIComponent\(query\.subjectId/, "artist page reads subjectId from route");
  assert.match(js, /atlasQuery\.subjectId\s*=\s*this\.subjectId/, "artist Atlas API query prefers subjectId");
  assert.match(js, /\/api\/v1\/weekly\/atlas\/artist/, "artist page still uses the Atlas artist endpoint");
});
