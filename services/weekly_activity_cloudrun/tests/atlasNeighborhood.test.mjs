import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

async function listen(serverInstance) {
  await new Promise((resolve) => serverInstance.listen(0, "127.0.0.1", resolve));
  const address = serverInstance.address();
  return `http://127.0.0.1:${address.port}`;
}

test("atlas neighborhood: subjectId lookup returns center, neighbors, and edges", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "atlas-neighborhood-"));
  const indexPath = path.join(dir, "atlas_index.json.gz");
  const neighborhoodPath = path.join(dir, "atlas_neighborhood.json.gz");
  const previousEnv = {
    ATLAS_MINIAPP_INDEX: process.env.ATLAS_MINIAPP_INDEX,
    ATLAS_NEIGHBORHOOD_BUNDLE: process.env.ATLAS_NEIGHBORHOOD_BUNDLE,
  };
  try {
    const index = {
      v: 4,
      subjects: [
        { i: "dj:alpha", t: "dj", n: "Alpha", nn: "alpha", a: ["A"], c: "上海", ec: 10 },
        { i: "dj:beta", t: "dj", n: "Beta", nn: "beta", a: [], c: "北京", ec: 4 },
        { i: "venue:room", t: "venue", n: "Room", nn: "room", a: [], c: "上海", ec: 8 },
      ],
      profiles: {}, events: {}, dj_venues: {}, venue_events: {}, venue_by_name: {}, collabs: {}, source_refs: {},
    };
    const neighborhood = {
      schemaVersion: "atlas.miniapp.neighborhood_bundle.v1",
      generation: { nodeCount: 3, relationCount: 2, subjectCount: 1, edgeCount: 2, perSubjectLimit: 60 },
      byNode: {
        "dj:alpha": [
          { u: "venue:room", rt: "resident_at", w: 20, rs: 5 },
          { u: "dj:beta", rt: "b2b", w: 10, rs: 7 },
        ],
      },
    };
    await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify(index), "utf8")));
    await writeFile(neighborhoodPath, gzipSync(Buffer.from(JSON.stringify(neighborhood), "utf8")));
    process.env.ATLAS_MINIAPP_INDEX = indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = neighborhoodPath;

    const api = await import(new URL(`../src/miniappAtlasApi.mjs?neighborhood=${Date.now()}`, import.meta.url).href);
    api.__resetMiniappAtlasApiCachesForTests();

    const result = await api.getNeighborhood({ subjectId: "dj:alpha", limit: 1 });
    assert.equal(result.schemaVersion, "atlas_miniapp.neighborhood_response.v1");
    assert.equal(result.found, true);
    assert.equal(result.center.name, "Alpha");
    assert.equal(result.neighbors.length, 1);
    assert.equal(result.neighbors[0].id, "venue:room");
    assert.equal(result.neighbors[0].relationType, "resident_at");
    assert.deepEqual(result.edges[0], {
      source: "dj:alpha",
      target: "venue:room",
      relationType: "resident_at",
      weight: 20,
    });

    const byQuery = await api.getNeighborhood({ q: "Alpha", limit: 2 });
    assert.equal(byQuery.query.subjectId, "dj:alpha");
    assert.equal(byQuery.neighbors.length, 2);

    const empty = await api.getNeighborhood({ subjectId: "venue:room" });
    assert.equal(empty.found, false);
    assert.equal(empty.reason, "no_neighbors");
  } finally {
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});

test("similar DJs: artist DTO surfaces DJ-typed neighbors only, ranked, self/venue dropped", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "atlas-similar-"));
  const indexPath = path.join(dir, "atlas_index.json.gz");
  const neighborhoodPath = path.join(dir, "atlas_neighborhood.json.gz");
  const previousEnv = {
    ATLAS_MINIAPP_INDEX: process.env.ATLAS_MINIAPP_INDEX,
    ATLAS_NEIGHBORHOOD_BUNDLE: process.env.ATLAS_NEIGHBORHOOD_BUNDLE,
  };
  try {
    const index = {
      v: 4,
      subjects: [
        { i: "dj:alpha", t: "dj", n: "Alpha", nn: "alpha", a: ["A"], c: "上海", ec: 10 },
        { i: "dj:beta", t: "dj", n: "Beta", nn: "beta", a: [], c: "北京", ec: 4 },
        { i: "dj:gamma", t: "dj", n: "Gamma", nn: "gamma", a: [], c: "成都", ec: 2 },
        { i: "venue:room", t: "venue", n: "Room", nn: "room", a: [], c: "上海", ec: 8 },
      ],
      profiles: {}, events: {}, dj_venues: {}, venue_events: {}, venue_by_name: {}, collabs: {}, source_refs: {},
    };
    const neighborhood = {
      schemaVersion: "atlas.miniapp.neighborhood_bundle.v1",
      generation: { nodeCount: 4, relationCount: 4, subjectCount: 1, edgeCount: 4, perSubjectLimit: 60 },
      byNode: {
        // rank-sorted: venue (drop, not dj), dj:beta, self (drop), dj:gamma
        "dj:alpha": [
          { u: "venue:room", rt: "resident_at", w: 20, rs: 9 },
          { u: "dj:beta", rt: "b2b", w: 10, rs: 7 },
          { u: "dj:alpha", rt: "self", w: 99, rs: 6 },
          { u: "dj:gamma", rt: "collab", w: 3, rs: 4 },
        ],
      },
    };
    await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify(index), "utf8")));
    await writeFile(neighborhoodPath, gzipSync(Buffer.from(JSON.stringify(neighborhood), "utf8")));
    process.env.ATLAS_MINIAPP_INDEX = indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = neighborhoodPath;

    const api = await import(new URL(`../src/miniappAtlasApi.mjs?similar=${Date.now()}`, import.meta.url).href);
    api.__resetMiniappAtlasApiCachesForTests();

    for (const result of [
      await api.getArtist({ name: "Alpha" }),
      await api.getArtistById("dj:alpha"),
    ]) {
      assert.equal(result.found, true);
      const similar = result.profile.similarDjs;
      assert.deepEqual(similar.map((d) => d.djId), ["dj:beta", "dj:gamma"]); // venue + self dropped, rank order kept
      assert.deepEqual(similar[0], {
        djId: "dj:beta", displayName: "Beta", city: "北京", eventCount: 4, relationType: "b2b", sharedWeight: 10,
      });
    }

    // DJ with no neighbors → empty array, never throws
    const lonely = await api.getArtistById("dj:gamma");
    assert.equal(lonely.found, true);
    assert.deepEqual(lonely.profile.similarDjs, []);
  } finally {
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});

test("atlas neighborhood HTTP route exposes the same DTO contract", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "atlas-neighborhood-http-"));
  const indexPath = path.join(dir, "atlas_index.json.gz");
  const neighborhoodPath = path.join(dir, "atlas_neighborhood.json.gz");
  const previousEnv = {
    ATLAS_MINIAPP_PRELOAD: process.env.ATLAS_MINIAPP_PRELOAD,
    ATLAS_MINIAPP_INDEX: process.env.ATLAS_MINIAPP_INDEX,
    ATLAS_NEIGHBORHOOD_BUNDLE: process.env.ATLAS_NEIGHBORHOOD_BUNDLE,
    CROSS_DB_MERGE_MAP: process.env.CROSS_DB_MERGE_MAP,
  };
  let server;
  try {
    await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify({
      v: 4,
      subjects: [
        { i: "dj:alpha", t: "dj", n: "Alpha", nn: "alpha", a: ["A"], c: "上海", ec: 10 },
        { i: "venue:room", t: "venue", n: "Room", nn: "room", a: [], c: "上海", ec: 8 },
      ],
      profiles: {}, events: {}, dj_venues: {}, venue_events: {}, venue_by_name: {}, collabs: {}, source_refs: {},
    }), "utf8")));
    await writeFile(neighborhoodPath, gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.miniapp.neighborhood_bundle.v1",
      generation: { nodeCount: 2, relationCount: 1, subjectCount: 1, edgeCount: 1, perSubjectLimit: 60 },
      byNode: {
        "dj:alpha": [{ u: "venue:room", rt: "resident_at", w: 20, rs: 5 }],
      },
    }), "utf8")));

    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = neighborhoodPath;
    process.env.CROSS_DB_MERGE_MAP = path.join(dir, "empty-merge-map.json");

    const { __resetMiniappAtlasApiCachesForTests } = await import("../src/miniappAtlasApi.mjs");
    __resetMiniappAtlasApiCachesForTests();
    const { createServer } = await import(`../src/server.mjs?neighborhood=${Date.now()}`);
    server = createServer({
      store: {},
      stage7Store: {},
      llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      soundStore: {},
      interviewStore: {},
      env: { ...process.env, ATLAS_REQUIRE_SESSION: "false" },
    });
    const baseUrl = await listen(server);
    const res = await fetch(`${baseUrl}/api/v1/weekly/atlas/neighborhood?subjectId=dj%3Aalpha&limit=1`);
    assert.equal(res.status, 200);
    const payload = await res.json();
    assert.equal(payload.schemaVersion, "atlas_miniapp.neighborhood_response.v1");
    assert.equal(payload.found, true);
    assert.equal(payload.center.id, "dj:alpha");
    assert.equal(payload.neighbors[0].id, "venue:room");
    assert.equal(payload.edges[0].relationType, "resident_at");

    const artistRes = await fetch(`${baseUrl}/api/v1/weekly/atlas/artist?subjectId=dj%3Aalpha&eventLimit=1&venueLimit=1&collaboratorLimit=1`);
    assert.equal(artistRes.status, 200);
    const artistPayload = await artistRes.json();
    assert.equal(artistPayload.schemaVersion, "atlas_miniapp.artist_response.v1");
    assert.equal(artistPayload.found, true);
    assert.equal(artistPayload.query, "dj:alpha");
    assert.equal(artistPayload.profile.djId, "dj:alpha");
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});
