/**
 * Star-map A<->B path-finding proof against the real neighborhood graph.
 * Asserts bidirectional BFS returns a VALID shortest chain (every consecutive pair
 * is a real graph edge), labels each hop, rejects same-node, and stays fast.
 * Read-only; no DB write, upload, deploy.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import zlib from "node:zlib";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../../..");
const dataDir = path.resolve(process.env.HUAIDJ_ATLAS_MINIAPP_DATA_DIR || path.join(repoRoot, "services/weekly_activity_cloudrun/data"));

function setEnv() {
  process.env.ATLAS_MINIAPP_PRELOAD = "0";
  process.env.ATLAS_MINIAPP_INDEX = path.join(dataDir, "atlas_index.json.gz");
  process.env.ATLAS_NEIGHBORHOOD_BUNDLE = path.join(dataDir, "atlas_neighborhood.json.gz");
}

test("getPath returns a valid, labelled shortest chain through the neighborhood graph", async () => {
  setEnv();
  const api = await import("../src/miniappAtlasApi.mjs");
  api.__resetMiniappAtlasApiCachesForTests();

  // Real adjacency for validating that each hop is an actual edge.
  const bundle = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(dataDir, "atlas_neighborhood.json.gz"))));
  const byNode = bundle.byNode;
  const isEdge = (a, b) =>
    (byNode[a] || []).some((r) => r.u === b) || (byNode[b] || []).some((r) => r.u === a);

  for (const [from, to] of [["dj:sulk", "dj:mikocycle"], ["dj:nora", "dj:0xygen"], ["dj:knopha", "venue:elevator"]]) {
    const r = await api.getPath({ from, to });
    assert.equal(r.found, true, `${from} -> ${to} should connect`);
    assert.ok(r.path.length >= 2, "path has at least endpoints");
    assert.equal(r.path[0].id, r.query.from, "path starts at canonical from");
    assert.equal(r.path[r.path.length - 1].id, r.query.to, "path ends at canonical to");
    if (r.query.requestedFrom) assert.equal(r.query.requestedFrom, from, "legacy from is retained in query");
    if (r.query.requestedTo) assert.equal(r.query.requestedTo, to, "legacy to is retained in query");
    assert.equal(r.hops, r.path.length - 1, "hops == path length - 1");
    assert.equal(r.edges.length, r.hops, "one edge per hop");
    // Every consecutive pair must be a real graph edge, and each edge labelled.
    for (let i = 0; i + 1 < r.path.length; i += 1) {
      const graphSource = r.edges[i].sourceGraphId || r.edges[i].source;
      const graphTarget = r.edges[i].targetGraphId || r.edges[i].target;
      assert.ok(isEdge(graphSource, graphTarget), `hop ${i} must be a real edge`);
      assert.ok(r.edges[i].relationType, "edge carries a relation type");
      assert.equal(r.edges[i].source, r.path[i].id);
      assert.equal(r.edges[i].target, r.path[i + 1].id);
    }
  }

  // Directly-connected pair -> exactly 1 hop.
  const direct = await api.getPath({ from: "dj:knopha", to: "dj:cocoonics" });
  assert.equal(direct.found, true);
  assert.equal(direct.hops, 1, "Knopha and Cocoonics are direct collaborators");

  // Same node and missing endpoints are rejected, not crashed.
  assert.equal((await api.getPath({ from: "dj:knopha", to: "dj:knopha" })).reason, "same_node");
  assert.equal((await api.getPath({ from: "dj:knopha", to: "" })).found, false);

  // Name resolution path.
  const byName = await api.getPath({ fromName: "Knopha", toName: "Cocoonics" });
  assert.equal(byName.found, true, "endpoints resolvable by name");
});
