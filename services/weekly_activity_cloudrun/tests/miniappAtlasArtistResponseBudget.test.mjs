import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

const DATASET_ID = `atlas-sha256-${"a".repeat(64)}`;

async function createArtistFixture({ bio = "Source-backed profile", knownTotals = {} } = {}) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "atlas-artist-budget-"));
  const indexPath = path.join(dir, "atlas_index.json.gz");
  const neighborhoodPath = path.join(dir, "atlas_neighborhood.json.gz");
  const events = Array.from({ length: 130 }, (_, index) => ({
    eid: `event:${index}`,
    t: `地下电子之夜 ${index}`,
    d: "2026-07-19",
    v: `Venue ${index % 20}`,
    ci: "上海",
  }));
  const venues = Array.from({ length: 140 }, (_, index) => ({
    vn: `Venue ${index}`,
    ec: 140 - index,
  }));
  const collaborators = Array.from({ length: 250 }, (_, index) => ({
    di: `dj:collaborator-${index}`,
    n: `Collaborator ${index}`,
    ec: 250 - index,
  }));

  await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify({
    v: 4,
    datasetId: DATASET_ID,
    subjects: [{ i: "dj:alpha", t: "dj", n: "Alpha", nn: "alpha", a: [], c: "上海", ec: knownTotals.events ?? events.length }],
    profiles: {
      "dj:alpha": {
        n: "Alpha",
        b: bio,
        vc: knownTotals.venues ?? venues.length,
        cc: knownTotals.collaborators ?? collaborators.length,
      },
    },
    events: { "dj:alpha": events },
    dj_venues: { "dj:alpha": venues },
    collabs: { "dj:alpha": collaborators },
    source_refs: {},
  }), "utf8")));
  await writeFile(neighborhoodPath, gzipSync(Buffer.from(JSON.stringify({
    schemaVersion: "atlas.miniapp.neighborhood_bundle.v1",
    datasetId: DATASET_ID,
    generation: { subjectCount: 1, nodeCount: 1, edgeCount: 0 },
    byNode: { "dj:alpha": [] },
  }), "utf8")));

  return { dir, indexPath, neighborhoodPath };
}

function captureEnv(names) {
  return Object.fromEntries(names.map((name) => [name, process.env[name]]));
}

function restoreEnv(previous) {
  for (const [name, value] of Object.entries(previous)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
}

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return `http://127.0.0.1:${address.port}`;
}

test("artist lists enforce hard page limits and expose resumable totals", async () => {
  const fixture = await createArtistFixture();
  const envNames = ["ATLAS_MINIAPP_PRELOAD", "ATLAS_MINIAPP_INDEX", "ATLAS_NEIGHBORHOOD_BUNDLE"];
  const previousEnv = captureEnv(envNames);
  try {
    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = fixture.indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = fixture.neighborhoodPath;
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();

    const payload = await api.getArtistById("dj:alpha", {
      eventLimit: "999999999999",
      venueLimit: "999999999999",
      collaboratorLimit: "999999999999",
    });

    assert.equal(payload.events.length, 100);
    assert.equal(payload.venues.length, 100);
    assert.equal(payload.collaborators.length, 200);
    assert.deepEqual(payload.pagination.events, {
      offset: 0,
      limit: 100,
      hardLimit: 100,
      total: 130,
      availableTotal: 130,
      returned: 100,
      truncated: true,
      sourceTruncated: false,
      hasMore: true,
      nextOffset: 100,
    });
    assert.equal(payload.pagination.venues.total, 140);
    assert.equal(payload.pagination.venues.nextOffset, 100);
    assert.equal(payload.pagination.collaborators.total, 250);
    assert.equal(payload.pagination.collaborators.nextOffset, 200);
  } finally {
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();
    restoreEnv(previousEnv);
    await rm(fixture.dir, { recursive: true, force: true });
  }
});

test("artist list pages resume independently without dropping the core profile", async () => {
  const fixture = await createArtistFixture();
  const envNames = ["ATLAS_MINIAPP_PRELOAD", "ATLAS_MINIAPP_INDEX", "ATLAS_NEIGHBORHOOD_BUNDLE"];
  const previousEnv = captureEnv(envNames);
  try {
    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = fixture.indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = fixture.neighborhoodPath;
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();

    const payload = await api.getArtist({
      name: "Alpha",
      eventLimit: "20",
      eventOffset: "100",
      venueLimit: "25",
      venueOffset: "125",
      collaboratorLimit: "50",
      collaboratorOffset: "200",
    });

    assert.equal(payload.profile.displayName, "Alpha");
    assert.equal(payload.events.length, 20);
    assert.equal(payload.events[0].eventId, "event:100");
    assert.deepEqual(payload.pagination.events, {
      offset: 100,
      limit: 20,
      hardLimit: 100,
      total: 130,
      availableTotal: 130,
      returned: 20,
      truncated: true,
      sourceTruncated: false,
      hasMore: true,
      nextOffset: 120,
    });
    assert.equal(payload.venues.length, 15);
    assert.equal(payload.venues[0].venueName, "Venue 125");
    assert.equal(payload.pagination.venues.nextOffset, null);
    assert.equal(payload.pagination.venues.truncated, true);
    assert.equal(payload.collaborators.length, 50);
    assert.equal(payload.collaborators[0].djId, "dj:collaborator-200");
    assert.equal(payload.pagination.collaborators.nextOffset, null);
  } finally {
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();
    restoreEnv(previousEnv);
    await rm(fixture.dir, { recursive: true, force: true });
  }
});

test("artist pagination distinguishes known totals from rows available in the compact index", async () => {
  const fixture = await createArtistFixture({
    knownTotals: { events: 1_300, venues: 1_400, collaborators: 2_500 },
  });
  const envNames = ["ATLAS_MINIAPP_PRELOAD", "ATLAS_MINIAPP_INDEX", "ATLAS_NEIGHBORHOOD_BUNDLE"];
  const previousEnv = captureEnv(envNames);
  try {
    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = fixture.indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = fixture.neighborhoodPath;
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();

    const payload = await api.getArtistById("dj:alpha", {
      eventLimit: 100,
      eventOffset: 100,
      venueLimit: 100,
      venueOffset: 100,
      collaboratorLimit: 200,
      collaboratorOffset: 200,
    });

    assert.equal(payload.pagination.events.total, 1_300);
    assert.equal(payload.pagination.events.availableTotal, 130);
    assert.equal(payload.pagination.events.returned, 30);
    assert.equal(payload.pagination.events.hasMore, false);
    assert.equal(payload.pagination.events.nextOffset, null);
    assert.equal(payload.pagination.events.sourceTruncated, true);
    assert.equal(payload.pagination.events.truncated, true);
    assert.equal(payload.pagination.venues.total, 1_400);
    assert.equal(payload.pagination.venues.availableTotal, 140);
    assert.equal(payload.pagination.collaborators.total, 2_500);
    assert.equal(payload.pagination.collaborators.availableTotal, 250);
  } finally {
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();
    restoreEnv(previousEnv);
    await rm(fixture.dir, { recursive: true, force: true });
  }
});

test("artist HTTP route forwards independent page offsets", async () => {
  const fixture = await createArtistFixture();
  const envNames = ["ATLAS_MINIAPP_PRELOAD", "ATLAS_MINIAPP_INDEX", "ATLAS_NEIGHBORHOOD_BUNDLE"];
  const previousEnv = captureEnv(envNames);
  let server;
  try {
    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = fixture.indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = fixture.neighborhoodPath;
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();
    const { createServer } = await import(`../src/server.mjs?artist-pagination=${Date.now()}`);
    server = createServer({
      store: {},
      stage7Store: {},
      soundStore: {},
      interviewStore: {},
      llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      env: { ...process.env, ATLAS_REQUIRE_SESSION: "false" },
    });
    const baseUrl = await listen(server);

    const response = await fetch(`${baseUrl}/api/v1/weekly/atlas/artist?subjectId=dj%3Aalpha&eventLimit=10&eventOffset=120&venueLimit=10&venueOffset=130&collaboratorLimit=25&collaboratorOffset=225`);
    assert.equal(response.status, 200);
    const rawBody = await response.text();
    assert.equal(Number(response.headers.get("x-atlas-response-bytes")), Buffer.byteLength(rawBody, "utf8"));
    assert.equal(Number(response.headers.get("x-atlas-response-max-bytes")), 512 * 1024);
    const payload = JSON.parse(rawBody);
    assert.equal(payload.profile.displayName, "Alpha");
    assert.equal(payload.events[0].eventId, "event:120");
    assert.equal(payload.pagination.events.offset, 120);
    assert.equal(payload.venues[0].venueName, "Venue 130");
    assert.equal(payload.pagination.venues.offset, 130);
    assert.equal(payload.collaborators[0].djId, "dj:collaborator-225");
    assert.equal(payload.pagination.collaborators.offset, 225);
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();
    restoreEnv(previousEnv);
    await rm(fixture.dir, { recursive: true, force: true });
  }
});

test("invalid artist limits and offsets use the same safe defaults", async () => {
  const fixture = await createArtistFixture();
  const envNames = ["ATLAS_MINIAPP_PRELOAD", "ATLAS_MINIAPP_INDEX", "ATLAS_NEIGHBORHOOD_BUNDLE"];
  const previousEnv = captureEnv(envNames);
  try {
    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = fixture.indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = fixture.neighborhoodPath;
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();

    const invalid = await api.getArtistById("dj:alpha", {
      eventLimit: "-1",
      eventOffset: "-10",
      venueLimit: "NaN",
      venueOffset: "not-a-number",
      collaboratorLimit: "0",
      collaboratorOffset: "Infinity",
    });
    assert.equal(invalid.events.length, 50);
    assert.equal(invalid.venues.length, 10);
    assert.equal(invalid.collaborators.length, 15);
    assert.equal(invalid.pagination.events.offset, 0);
    assert.equal(invalid.pagination.venues.offset, 0);
    assert.equal(invalid.pagination.collaborators.offset, 0);

    const beyondEnd = await api.getArtistById("dj:alpha", {
      eventLimit: "1e99",
      eventOffset: "999999999999999999",
    });
    assert.equal(beyondEnd.events.length, 0);
    assert.equal(beyondEnd.pagination.events.limit, 100);
    assert.equal(beyondEnd.pagination.events.offset, 130);
    assert.equal(beyondEnd.pagination.events.total, 130);
    assert.equal(beyondEnd.pagination.events.truncated, true);
    assert.equal(beyondEnd.pagination.events.nextOffset, null);
  } finally {
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();
    restoreEnv(previousEnv);
    await rm(fixture.dir, { recursive: true, force: true });
  }
});

test("artist HTTP response budget rejects an oversized core profile without slicing it", async () => {
  const fixture = await createArtistFixture({ bio: "资".repeat(20_000) });
  const envNames = ["ATLAS_MINIAPP_PRELOAD", "ATLAS_MINIAPP_INDEX", "ATLAS_NEIGHBORHOOD_BUNDLE"];
  const previousEnv = captureEnv(envNames);
  let server;
  try {
    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = fixture.indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = fixture.neighborhoodPath;
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();
    const { createServer } = await import(`../src/server.mjs?artist-budget=${Date.now()}`);
    server = createServer({
      store: {},
      stage7Store: {},
      soundStore: {},
      interviewStore: {},
      llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      env: {
        ...process.env,
        ATLAS_REQUIRE_SESSION: "false",
        ATLAS_ARTIST_RESPONSE_MAX_BYTES: "16384",
      },
    });
    const baseUrl = await listen(server);

    const routes = [
      "/api/v1/weekly/atlas/artist?subjectId=dj%3Aalpha&eventLimit=1&venueLimit=1&collaboratorLimit=1",
      "/api/v1/weekly/atlas/dj/dj%3Aalpha/profile",
      "/api/v1/weekly/atlas/dj-profile/Alpha",
    ];
    for (const route of routes) {
      const response = await fetch(`${baseUrl}${route}`);
      assert.equal(response.status, 507, route);
      assert.match(response.headers.get("cache-control") || "", /no-store/);
      const payload = await response.json();
      assert.equal(payload.error.code, "ATLAS_ARTIST_PROFILE_TOO_LARGE");
      assert.equal(payload.error.details.maxBytes, 16_384);
      assert.ok(payload.error.details.responseBytes > payload.error.details.maxBytes);
      assert.ok(payload.error.details.coreProfileBytes > payload.error.details.maxBytes);
      assert.equal(Object.hasOwn(payload, "profile"), false);
    }
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();
    restoreEnv(previousEnv);
    await rm(fixture.dir, { recursive: true, force: true });
  }
});
