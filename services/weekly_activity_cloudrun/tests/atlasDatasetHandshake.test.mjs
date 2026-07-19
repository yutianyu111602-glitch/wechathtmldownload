import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

const MATCHING_DATASET_ID = "atlas-sha256-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const OTHER_DATASET_ID = "atlas-sha256-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

function indexFixture(datasetId) {
  return {
    ...(datasetId ? { datasetId } : {}),
    v: 5,
    subjects: [
      { i: "dj:alpha", t: "dj", n: "Alpha", nn: "alpha", a: [], c: "上海", ec: 10 },
      { i: "dj:beta", t: "dj", n: "Beta", nn: "beta", a: [], c: "北京", ec: 4 },
      { i: "venue:room", t: "venue", n: "Room", nn: "room", a: [], c: "上海", ec: 8 },
    ],
    profiles: { "dj:alpha": { n: "Alpha", c: "上海", ec: 10 } },
    events: { "dj:alpha": [] },
    dj_venues: { "dj:alpha": [] },
    venue_events: {},
    venue_by_name: {},
    collabs: { "dj:alpha": [] },
    source_refs: {},
  };
}

function neighborhoodFixture(datasetId) {
  return {
    ...(datasetId ? { datasetId } : {}),
    schemaVersion: "atlas.miniapp.neighborhood_bundle.v1",
    generation: {
      source: "C:\\Users\\operator\\AppData\\Local\\Temp\\atlas.sqlite",
      nodeCount: 3,
      relationCount: 3,
      subjectCount: 2,
      edgeCount: 3,
      perSubjectLimit: 60,
    },
    byNode: {
      "dj:alpha": [
        { u: "venue:room", rt: "resident_at", w: 20, rs: 5 },
        { u: "dj:beta", rt: "b2b", w: 10, rs: 7 },
      ],
      "dj:beta": [{ u: "dj:alpha", rt: "b2b", w: 10, rs: 8 }],
    },
  };
}

async function runCase(indexDatasetId, neighborhoodDatasetId, label) {
  const dir = await mkdtemp(path.join(os.tmpdir(), `atlas-dataset-${label}-`));
  const indexPath = path.join(dir, "atlas_index.json.gz");
  const neighborhoodPath = path.join(dir, "atlas_neighborhood.json.gz");
  await writeFile(indexPath, gzipSync(Buffer.from(JSON.stringify(indexFixture(indexDatasetId)), "utf8")));
  await writeFile(neighborhoodPath, gzipSync(Buffer.from(JSON.stringify(neighborhoodFixture(neighborhoodDatasetId)), "utf8")));

  const previousEnv = { ...process.env };
  try {
    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = indexPath;
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = neighborhoodPath;
    process.env.ATLAS_STARMAP_LENSES = path.join(dir, "missing-lenses.json.gz");
    process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = path.join(dir, "missing-trajectory.json.gz");
    process.env.ATLAS_RADIO_PROGRAMS = path.join(dir, "missing-radio.json.gz");
    process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW = path.join(dir, "missing-radio-review.json");
    process.env.ATLAS_DJ_EXTERNAL_LINKS = path.join(dir, "missing-links.json.gz");
    process.env.ATLAS_DJ_BIO_CANDIDATES = path.join(dir, "missing-bios.json.gz");
    process.env.ATLAS_DJ_BIO_SNIPPETS = path.join(dir, "missing-snippets.json.gz");
    process.env.ATLAS_SCENE_CLUSTERS = path.join(dir, "missing-scenes.json.gz");

    const api = await import(new URL(`../src/miniappAtlasApi.mjs?dataset=${label}-${Date.now()}`, import.meta.url).href);
    api.__resetMiniappAtlasApiCachesForTests();
    return {
      neighborhood: await api.getNeighborhood({ subjectId: "dj:alpha", limit: 2 }),
      path: await api.getPath({ from: "dj:alpha", to: "dj:beta" }),
      artist: await api.getArtistById("dj:alpha"),
      artistByName: await api.getArtist({ name: "Alpha" }),
    };
  } finally {
    for (const key of Object.keys(process.env)) {
      if (!(key in previousEnv)) delete process.env[key];
    }
    for (const [key, value] of Object.entries(previousEnv)) process.env[key] = value;
    await rm(dir, { recursive: true, force: true });
  }
}

test("Atlas dataset handshake mixes index and neighborhood only for the same public generation", async () => {
  const matched = await runCase(MATCHING_DATASET_ID, MATCHING_DATASET_ID, "match");
  const expectedGeneration = {
    datasetId: MATCHING_DATASET_ID,
    subjectCount: 3,
    profileCount: 1,
    nodeCount: 3,
    relationCount: 3,
    neighborhoodSubjectCount: 2,
    edgeCount: 3,
    perSubjectLimit: 60,
  };
  assert.equal(matched.neighborhood.found, true);
  assert.equal(matched.path.found, true);
  assert.deepEqual(matched.neighborhood.generation, expectedGeneration);
  assert.deepEqual(matched.path.generation, expectedGeneration);
  assert.deepEqual(matched.artist.generation, expectedGeneration);
  assert.deepEqual(matched.artistByName.generation, expectedGeneration);
  assert.equal(matched.artist.profile.similarDjs[0].djId, "dj:beta");
  assert.equal(matched.artist.profile.residentVenues[0].venueId, "venue:room");
  assert.doesNotMatch(JSON.stringify(matched), /(?:[A-Za-z]:\\\\|AppData|Temp|atlas\.sqlite)/i);

  const mismatched = await runCase(MATCHING_DATASET_ID, OTHER_DATASET_ID, "mismatch");
  assert.equal(mismatched.neighborhood.found, false);
  assert.equal(mismatched.neighborhood.reason, "dataset_mismatch");
  assert.equal(mismatched.path.found, false);
  assert.equal(mismatched.path.reason, "dataset_mismatch");
  assert.equal(mismatched.artist.found, true, "index-only artist remains available");
  assert.deepEqual(mismatched.artist.profile.similarDjs, []);
  assert.deepEqual(mismatched.artist.profile.residentVenues, []);
  assert.deepEqual(mismatched.artistByName.profile.similarDjs, []);
  assert.deepEqual(mismatched.artist.generation, {
    datasetId: MATCHING_DATASET_ID,
    subjectCount: 3,
    profileCount: 1,
  });
  assert.deepEqual(mismatched.artistByName.generation, mismatched.artist.generation);

  const missing = await runCase(null, null, "missing");
  assert.equal(missing.neighborhood.found, false);
  assert.equal(missing.neighborhood.reason, "dataset_id_missing");
  assert.equal(missing.path.found, false);
  assert.equal(missing.path.reason, "dataset_id_missing");
  assert.equal(missing.artist.found, true, "legacy index remains usable without graph mixing");
  assert.deepEqual(missing.artist.profile.similarDjs, []);
  assert.deepEqual(missing.artistByName.profile.similarDjs, []);
  assert.deepEqual(missing.artist.generation, { subjectCount: 3, profileCount: 1 });
});
