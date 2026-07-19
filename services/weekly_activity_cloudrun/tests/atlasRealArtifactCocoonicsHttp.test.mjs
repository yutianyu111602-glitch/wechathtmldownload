import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../../..");
const dataDir = path.resolve(process.env.HUAIDJ_ATLAS_MINIAPP_DATA_DIR || path.join(repoRoot, "services/weekly_activity_cloudrun/data"));

async function listen(serverInstance) {
  await new Promise((resolve) => serverInstance.listen(0, "127.0.0.1", resolve));
  const address = serverInstance.address();
  return `http://127.0.0.1:${address.port}`;
}

test("real Atlas miniapp HTTP artist route exposes Cocoonics radio programs and relation trajectory", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "atlas-real-cocoonics-http-"));
  const previousEnv = {
    ATLAS_MINIAPP_PRELOAD: process.env.ATLAS_MINIAPP_PRELOAD,
    ATLAS_MINIAPP_INDEX: process.env.ATLAS_MINIAPP_INDEX,
    ATLAS_DJ_RELATION_TRAJECTORY_LENS: process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS,
    ATLAS_RADIO_PROGRAMS: process.env.ATLAS_RADIO_PROGRAMS,
    ATLAS_NEIGHBORHOOD_BUNDLE: process.env.ATLAS_NEIGHBORHOOD_BUNDLE,
    ATLAS_RADIO_PROGRAM_MATCH_REVIEW: process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW,
    ATLAS_REQUIRE_SESSION: process.env.ATLAS_REQUIRE_SESSION,
    CROSS_DB_MERGE_MAP: process.env.CROSS_DB_MERGE_MAP,
  };
  let server;
  try {
    const emptyMergeMap = path.join(dir, "empty-merge-map.json");
    await writeFile(emptyMergeMap, JSON.stringify({ db2_to_db3_map: {}, existing_subject_map: {} }), "utf8");

    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_MINIAPP_INDEX = path.join(dataDir, "atlas_index.json.gz");
    process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = path.join(dataDir, "dj_relation_trajectory_lens.json.gz");
    process.env.ATLAS_RADIO_PROGRAMS = path.join(dataDir, "radio_programs_candidate.json.gz");
    process.env.ATLAS_NEIGHBORHOOD_BUNDLE = path.join(dataDir, "atlas_neighborhood.json.gz");
    process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW = path.join(dataDir, "radio_program_match_review.json.gz");
    process.env.ATLAS_REQUIRE_SESSION = "false";
    process.env.CROSS_DB_MERGE_MAP = emptyMergeMap;

    const api = await import("../src/miniappAtlasApi.mjs");
    api.__resetMiniappAtlasApiCachesForTests();
    const { createServer } = await import(`../src/server.mjs?real-cocoonics-http=${Date.now()}`);
    server = createServer({
      store: {},
      stage7Store: {},
      llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      soundStore: {},
      interviewStore: {},
      env: { ...process.env, ATLAS_REQUIRE_SESSION: "false" },
    });
    const baseUrl = await listen(server);
    const getJson = async (route) => {
      const res = await fetch(`${baseUrl}${route}`);
      assert.equal(res.status, 200, route);
      return res.json();
    };

    const byId = await getJson("/api/v1/weekly/atlas/artist?subjectId=dj%3Acocoonics&eventLimit=100&collaboratorLimit=1500&venueLimit=500");
    const byName = await getJson("/api/v1/weekly/atlas/artist?name=Cocoonics&eventLimit=100&collaboratorLimit=1500&venueLimit=500");

    for (const [label, result] of [["by id", byId], ["by name", byName]]) {
      assert.equal(result.schemaVersion, "atlas_miniapp.artist_response.v1", label);
      assert.equal(result.found, true, label);
      assert.equal(result.profile?.displayName, "Cocoonics", label);
      assert.ok((result.events || []).length >= 90, `Cocoonics ${label} should expose Atlas event history`);
      assert.ok((result.radioPrograms || []).length >= 1, `Cocoonics ${label} should expose radio programs`);
      assert.ok((result.profile?.radioPrograms || []).length >= 1, `Cocoonics ${label} profile should carry radio programs`);
      assert.ok(result.relationTrajectory, `Cocoonics ${label} should expose relation trajectory`);
      assert.ok(result.profile?.relationTrajectory, `Cocoonics ${label} profile should carry relation trajectory`);
      assert.ok((result.relationTrajectory.cities || []).length >= 1, `Cocoonics ${label} should expose city trajectory`);
      assert.ok((result.relationTrajectory.venues || []).length >= 1, `Cocoonics ${label} should expose venues`);
      assert.ok((result.relationTrajectory.collaborators || []).length >= 1, `Cocoonics ${label} should expose collaborators`);
    }

    assert.equal(
      byId.radioPrograms[0].url,
      "https://byyb.live/set/cocoonics-2025-10-19-turbo-x-catnapp-showcase",
    );
    assert.equal(byId.radioPrograms[0].openMode, "external_original_site");
    assert.equal(byId.radioPrograms[0].noHotlink, true);
    assert.equal(byId.profile.radioPrograms[0].url, byId.radioPrograms[0].url);
    assert.deepEqual(byName.radioPrograms.map((program) => program.programId), byId.radioPrograms.map((program) => program.programId));

    const radioPrograms = await getJson("/api/v1/weekly/atlas/radio-programs?djId=dj%3Acocoonics&limit=20");
    assert.equal(radioPrograms.schemaVersion, "atlas_miniapp.radio_programs_response.v1");
    assert.equal(radioPrograms.found, true);
    assert.equal(radioPrograms.candidateOnly, true);
    assert.equal(radioPrograms.productionWriteExecuted, false);
    assert.equal(radioPrograms.oldDatabaseRowsUsed, 0);
    assert.equal(radioPrograms.hotlinkPolicy.mediaEmbedded, false);
    assert.equal(radioPrograms.hotlinkPolicy.uiAction, "click_to_open_original_site");
    assert.equal(radioPrograms.matchReview.available, true);
    assert.equal(radioPrograms.matchReview.defaultPolicy, "safe_display_only_for_dj_detail");
    assert.ok((radioPrograms.programs || []).some((program) => program.url === byId.radioPrograms[0].url));

    const neighborhood = await getJson("/api/v1/weekly/atlas/neighborhood?subjectId=dj%3Acocoonics&depth=1&limit=20");
    assert.equal(neighborhood.schemaVersion, "atlas_miniapp.neighborhood_response.v1");
    assert.equal(neighborhood.found, true);
    assert.equal(neighborhood.center?.id, byId.subjectId);
    assert.equal(neighborhood.query?.requestedSubjectId, "dj:cocoonics");
    assert.equal(neighborhood.center?.requestedSubjectId, "dj:cocoonics");
    assert.ok((neighborhood.neighbors || []).length >= 5, "Cocoonics should expose L1 star-map neighbors over HTTP");
    assert.ok((neighborhood.edges || []).length >= 5, "Cocoonics should expose L1 star-map edges over HTTP");
    assert.ok((neighborhood.generation?.nodeCount || 0) >= 70000, "HTTP neighborhood should use the full-library bundle");
    // See atlasRealArtifactCocoonics.test.mjs — lean hash-aligned bundle (~508k edges).
    assert.ok((neighborhood.generation?.edgeCount || 0) >= 450000, "HTTP neighborhood should expose full-library edges");
    const elevatorNeighbor = neighborhood.neighbors.find((neighbor) => neighbor.graphSubjectId === "venue:elevator" || neighbor.name === "Elevator");
    assert.ok(elevatorNeighbor, "Cocoonics HTTP neighborhood should retain the known Elevator edge");
    assert.equal(elevatorNeighbor.name, "Elevator");
    assert.equal(elevatorNeighbor.type, "venue");
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});
