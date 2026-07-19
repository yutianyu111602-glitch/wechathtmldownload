import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../../..");
const dataDir = path.resolve(process.env.HUAIDJ_ATLAS_MINIAPP_DATA_DIR || path.join(repoRoot, "services/weekly_activity_cloudrun/data"));

test("real Atlas miniapp artifacts expose Cocoonics radio programs and relation trajectory", async () => {
  process.env.ATLAS_MINIAPP_PRELOAD = "0";
  process.env.ATLAS_MINIAPP_INDEX = path.join(dataDir, "atlas_index.json.gz");
  process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = path.join(dataDir, "dj_relation_trajectory_lens.json.gz");
  process.env.ATLAS_RADIO_PROGRAMS = path.join(dataDir, "radio_programs_candidate.json.gz");
  process.env.ATLAS_NEIGHBORHOOD_BUNDLE = path.join(dataDir, "atlas_neighborhood.json.gz");

  const api = await import("../src/miniappAtlasApi.mjs");
  api.__resetMiniappAtlasApiCachesForTests();

  const options = { eventLimit: 100, collaboratorLimit: 1500, venueLimit: 500 };
  const byId = await api.getArtistById("dj:cocoonics", options);
  const byName = await api.getArtist({ name: "Cocoonics", ...options });

  for (const [label, result] of [["by id", byId], ["by name", byName]]) {
    assert.equal(result.found, true, `Cocoonics ${label} should be found`);
    assert.equal(result.profile?.displayName, "Cocoonics");
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

  const neighborhood = await api.getNeighborhood({ subjectId: "dj:cocoonics", depth: 1, limit: 20 });
  assert.equal(neighborhood.schemaVersion, "atlas_miniapp.neighborhood_response.v1");
  assert.equal(neighborhood.found, true);
  assert.equal(neighborhood.center?.id, byId.subjectId);
  assert.equal(neighborhood.query?.requestedSubjectId, "dj:cocoonics");
  assert.equal(neighborhood.center?.requestedSubjectId, "dj:cocoonics");
  assert.ok((neighborhood.neighbors || []).length >= 5, "Cocoonics should expose L1 star-map neighbors");
  assert.ok((neighborhood.edges || []).length >= 5, "Cocoonics should expose L1 star-map edges");
  assert.ok((neighborhood.generation?.nodeCount || 0) >= 70000, "real neighborhood bundle should be full-library scale");
  // Edge floor for the hash-aligned lean bundle (miniapp dj_collaborator + dj_venue
  // + bounded co-venue projection, ~508k). Lower than the old ~1M name-slug bundle,
  // which double-counted redundant frequency resident_at edges; the floor still
  // catches a build that drops most edges. See handoff 116 audit.
  assert.ok((neighborhood.generation?.edgeCount || 0) >= 450000, "real neighborhood bundle should include full-library edges");
  const elevatorNeighbor = neighborhood.neighbors.find((neighbor) => neighbor.graphSubjectId === "venue:elevator" || neighbor.name === "Elevator");
  assert.ok(elevatorNeighbor, "Cocoonics should retain the known Elevator neighborhood edge");
  assert.equal(elevatorNeighbor.name, "Elevator");
  assert.equal(elevatorNeighbor.type, "venue");
});
