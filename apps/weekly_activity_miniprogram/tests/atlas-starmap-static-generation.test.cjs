const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const pagePath = path.join(root, "pages/atlas-starmap/atlas-starmap.js");
const apiPath = path.join(root, "utils/api.js");
const starmapJsPath = path.join(root, "data/atlas_starmap.js");
const starmapJsonPath = path.join(root, "data/atlas_starmap.json");
const neighborsJsPath = path.join(root, "data/atlas_starmap_neighbors.js");
const neighborsJsonPath = path.join(root, "data/atlas_starmap_neighbors.json");

const EXPECTED_DATASET_ID = "atlas-miniapp-sha256-10bcede6da38552cb3abc3d6b374ea66b56df4e16f813f9b9e664bc35991772f";
const EXPECTED_STARMAP_JS_SHA256 = "d88c17409363fe71ade88606ef323c7d4f29715fbc3945554fb9e8c3ab278380";
const EXPECTED_STARMAP_JSON_SHA256 = "7246b89f18eefd734913301433557c815eb12b66bca8eb372226d311e19c3a00";

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function loadPage() {
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
    exports: {
      requestApi: () => Promise.resolve(null),
      fetchAllCurrentItems: () => Promise.resolve([]),
    },
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

test("shipped starmap is the verified guarded generation and JS/JSON stay identical", () => {
  delete require.cache[require.resolve(starmapJsPath)];
  const jsBundle = require(starmapJsPath);
  const jsonBundle = JSON.parse(fs.readFileSync(starmapJsonPath, "utf8"));

  assert.equal(sha256(starmapJsPath), EXPECTED_STARMAP_JS_SHA256);
  assert.equal(sha256(starmapJsonPath), EXPECTED_STARMAP_JSON_SHA256);
  assert.equal(jsBundle.datasetId, EXPECTED_DATASET_ID);
  assert.equal(jsonBundle.datasetId, EXPECTED_DATASET_ID);
  assert.deepEqual(jsBundle, jsonBundle);
  assert.equal(jsBundle.nodes.length, 240);
  assert.equal(jsBundle.edges.length, 640);
  assert.ok(jsBundle.nodes.every((node) => /^[^:]+:[0-9a-f]{16}$/.test(String(node.u || ""))));
});

test("legacy slug neighbors are ignored and expansion falls back to same-generation remote rows", () => {
  const starmap = require(starmapJsPath);
  const shippedNeighbors = require(neighborsJsPath);
  const neighborsJson = JSON.parse(fs.readFileSync(neighborsJsonPath, "utf8"));
  const legacyNeighbors = {
    schemaVersion: "atlas.mp.starmap_neighbors.v1",
    byNode: {
      "venue:loopyclub": [{ u: "dj:juanplusone", n: "Juan Plus One", t: "dj" }],
    },
  };
  const legacyId = Object.keys(legacyNeighbors.byNode || {})[0];
  assert.ok(legacyId, "legacy neighbor fixture has a keyed row");
  assert.deepEqual(shippedNeighbors, neighborsJson, "runtime and source neighbor tombstones stay identical");
  assert.equal(shippedNeighbors.datasetId, undefined, "retired legacy neighbors must not be falsely stamped");
  assert.equal(shippedNeighbors.disabledReason, "generation_unbound_legacy_neighbors_removed");
  assert.deepEqual(shippedNeighbors.byNode, {});

  const page = loadPage();
  const remoteRows = [{ u: "dj:0123456789abcdef", n: "Remote", t: "dj", rt: "collab", w: 1, rs: 1 }];
  page._localDatasetId = starmap.datasetId;
  page._remoteRows = { [legacyId]: remoteRows };
  page._remoteLoading = {};
  page._remoteError = {};

  assert.equal(page._neighborBundleMatchesDataset(legacyNeighbors), false);
  assert.strictEqual(page._neighborRows(legacyId), remoteRows);

  page._edges = starmap.edges.map((edge) => [edge[0], edge[1], edge[2], Number(edge[3]) || 1]);
  page._rebuildAdj();
  assert.ok(Object.keys(page._adj).length > 0, "verified base edges remain available without legacy neighbors");
});

test("neighbor generation guard accepts exact identity and rejects missing or tampered identity", () => {
  const page = loadPage();
  page._localDatasetId = EXPECTED_DATASET_ID;

  assert.equal(page._neighborBundleMatchesDataset({ byNode: {} }), false);
  assert.equal(page._neighborBundleMatchesDataset({
    datasetId: EXPECTED_DATASET_ID.replace(/f$/, "e"),
    byNode: {},
  }), false);
  assert.equal(page._neighborBundleMatchesDataset({
    datasetId: EXPECTED_DATASET_ID,
    byNode: {},
  }), true);
});
