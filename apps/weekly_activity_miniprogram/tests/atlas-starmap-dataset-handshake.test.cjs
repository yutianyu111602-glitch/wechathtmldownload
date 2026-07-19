const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const pagePath = path.join(root, "pages/atlas-starmap/atlas-starmap.js");
const apiPath = path.join(root, "utils/api.js");

function loadPage(requestApi) {
  const previousPage = global.Page;
  const previousWx = global.wx;
  const previousApiCache = require.cache[require.resolve(apiPath)];
  let captured = null;
  global.Page = (definition) => { captured = definition; };
  global.wx = { showToast() {}, navigateTo() {} };
  require.cache[require.resolve(apiPath)] = {
    id: apiPath,
    filename: apiPath,
    loaded: true,
    exports: { requestApi },
    children: [],
    paths: [],
  };
  delete require.cache[require.resolve(pagePath)];
  require(pagePath);
  global.Page = previousPage;
  global.wx = previousWx;
  if (previousApiCache) require.cache[require.resolve(apiPath)] = previousApiCache;
  else delete require.cache[require.resolve(apiPath)];
  assert.ok(captured, "starmap Page definition was captured");
  return captured;
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

test("starmap rejects missing or mismatched online generations and keeps local graph state", async () => {
  const responses = [];
  const page = loadPage(() => Promise.resolve(responses.shift()));
  page.data = { selected: null, relatedFilter: "all" };
  page.setData = function setData(update) { this.data = { ...this.data, ...update }; };
  page.draw = function draw() {};
  page._nodes = [{ i: 0, u: "dj:alpha", n: "Alpha", t: "dj", c: "上海", x: 0, y: 0 }];
  page._remoteRows = {};
  page._remoteLoading = {};
  page._remoteError = {};
  page._inspectorCache = {};
  page._inspectorLoading = {};
  page._sel = -1;
  page._localDatasetId = "atlas-sha256-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
  page._expandRows = function expandRows() { this._mixedOnlineRows = true; };

  responses.push({
    generation: { datasetId: "atlas-sha256-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" },
    neighbors: [{ id: "dj:wrong", name: "Wrong", type: "dj" }],
  });
  page._expandNodeRemote(0);
  await tick();
  assert.deepEqual(page._remoteRows["dj:alpha"], []);
  assert.equal(page._remoteError["dj:alpha"], true);
  assert.equal(page._mixedOnlineRows, undefined, "mismatched rows never enter the local graph");

  delete page._remoteRows["dj:alpha"];
  responses.push({ neighbors: [{ id: "dj:missing", name: "Missing", type: "dj" }] });
  page._expandNodeRemote(0);
  await tick();
  assert.deepEqual(page._remoteRows["dj:alpha"], []);
  assert.equal(page._remoteError["dj:alpha"], true);

  delete page._remoteRows["dj:alpha"];
  responses.push({
    generation: { datasetId: page._localDatasetId },
    neighbors: [{ id: "dj:beta", name: "Beta", type: "dj", relationType: "collab", weight: 2, rankScore: 3 }],
  });
  page._expandNodeRemote(0);
  await tick();
  assert.equal(page._remoteError["dj:alpha"], false);
  assert.equal(page._remoteRows["dj:alpha"][0].u, "dj:beta");
  assert.equal(page._mixedOnlineRows, true, "same-generation rows may extend the local graph");
});

test("starmap online handshake helper rejects a missing local generation", () => {
  const page = loadPage(() => Promise.resolve(null));
  page._localDatasetId = "";
  assert.equal(page._onlinePayloadMatchesDataset({ generation: { datasetId: "atlas-sha256-a" } }), false);
  page._localDatasetId = "atlas-sha256-a";
  assert.equal(page._onlinePayloadMatchesDataset({}), false);
  assert.equal(page._onlinePayloadMatchesDataset({ generation: { datasetId: "atlas-sha256-b" } }), false);
  assert.equal(page._onlinePayloadMatchesDataset({ generation: { datasetId: "atlas-sha256-a" } }), true);
});

test("starmap retries a cached generation mismatch exactly once against the live API", async () => {
  const calls = [];
  const localDatasetId = "atlas-sha256-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
  const page = loadPage((requestPath, data) => {
    calls.push({ requestPath, data: { ...data } });
    if (calls.length === 1) {
      return Promise.resolve({
        generation: { datasetId: "atlas-sha256-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" },
      });
    }
    return Promise.resolve({ generation: { datasetId: localDatasetId }, found: true });
  });
  page._localDatasetId = localDatasetId;

  const payload = await page._requestAtlasDatasetBound("/api/v1/weekly/atlas/artist", {
    subjectId: "dj:alpha",
  });

  assert.equal(payload.found, true);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].data.__skipCache, undefined);
  assert.equal(calls[0].data.__liveOnly, undefined);
  assert.equal(calls[1].data.__skipCache, true);
  assert.equal(calls[1].data.__liveOnly, true);
});

test("starmap rejects a live generation mismatch after the single forced retry", async () => {
  let calls = 0;
  const page = loadPage(() => {
    calls += 1;
    return Promise.resolve({ generation: { datasetId: "atlas-sha256-stale" } });
  });
  page._localDatasetId = "atlas-sha256-current";

  await assert.rejects(
    page._requestAtlasDatasetBound("/api/v1/weekly/atlas/path", { from: "a", to: "b" }),
    (error) => error && error.code === "ATLAS_DATASET_GENERATION_MISMATCH",
  );
  assert.equal(calls, 2);
});

test("starmap A to B to A selection renders the in-flight A inspector when it resolves", async () => {
  let resolveAlpha;
  let resolveBeta;
  const alphaPromise = new Promise((resolve) => { resolveAlpha = resolve; });
  const betaPromise = new Promise((resolve) => { resolveBeta = resolve; });
  const page = loadPage((_requestPath, data) => (
    data.subjectId === "dj:alpha" ? alphaPromise : betaPromise
  ));
  page._localDatasetId = "atlas-sha256-current";
  page.data = { selected: null };
  page.setData = function setData(update) { this.data = { ...this.data, ...update }; };
  page._inspectorCache = {};
  page._inspectorLoading = {};
  page._inspectorSeq = 0;

  const alpha = { u: "dj:alpha", n: "Alpha", t: "dj" };
  const beta = { u: "dj:beta", n: "Beta", t: "dj" };
  page.data.selected = { id: alpha.u, inspector: null };
  page._loadSelectedInspector(alpha);
  page.data.selected = { id: beta.u, inspector: null };
  page._loadSelectedInspector(beta);
  page.data.selected = { id: alpha.u, inspector: { status: "loading" } };
  page._loadSelectedInspector(alpha);

  resolveAlpha({ generation: { datasetId: page._localDatasetId }, found: false });
  await tick();

  assert.equal(page.data.selected.id, alpha.u);
  assert.equal(page.data.selected.inspector.status, "empty");
  resolveBeta({ generation: { datasetId: page._localDatasetId }, found: false });
  await tick();
});
