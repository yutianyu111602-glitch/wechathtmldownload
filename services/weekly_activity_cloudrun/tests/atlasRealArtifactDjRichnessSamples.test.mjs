/**
 * Multi-sample DJ richness proof — runs the real getArtistById DTO against a
 * diverse slice of the data distribution (max-richness -> sparse long-tail) and
 * asserts each product-layer section appears when the data exists, with the
 * radio review gate and outlink role gate holding for every sample.
 *
 * Samples picked by tools/atlas_rebuild/audit_dj_richness.mjs.
 * Safety: read-only; no DB write, upload, deploy.
 */
import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../../..");
const dataDir = path.resolve(process.env.HUAIDJ_ATLAS_MINIAPP_DATA_DIR || path.join(repoRoot, "services/weekly_activity_cloudrun/data"));

function setEnv() {
  process.env.ATLAS_MINIAPP_PRELOAD = "0";
  process.env.ATLAS_MINIAPP_INDEX = path.join(dataDir, "atlas_index.json.gz");
  process.env.ATLAS_DJ_EXTERNAL_LINKS = path.join(dataDir, "dj_external_links_accepted_candidate.json.gz");
  process.env.ATLAS_RADIO_PROGRAMS = path.join(dataDir, "radio_programs_candidate.json.gz");
  process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW = path.join(dataDir, "radio_program_match_review.json.gz");
  process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = path.join(dataDir, "dj_relation_trajectory_lens.json.gz");
  process.env.ATLAS_DJ_BIO_CANDIDATES = path.join(dataDir, "bio_candidates_accepted.jsonl");
  process.env.ATLAS_DJ_BIO_SNIPPETS = path.join(dataDir, "bio_snippets_accepted.jsonl");
}

// Expectation per sample: which sections MUST be populated (verified against the
// real DTO, not the raw artifact — the backend drops ambiguous/generic radio
// matches, so radio expectations reflect post-gate reality). `false` = don't care.
const SAMPLES = [
  { id: "dj:sulk", outlinks: true, radio: true, trajectory: true }, // legacy ID with sidecar-rich sections
  { id: "dj:cocoonics", radio: true, trajectory: true },   // radio-heavy (8); no identity-safe bio in the current artifact
  { id: "dj:2by2", bioCandidate: true }, // source-backed candidate bio
  { id: "dj:nora", outlinks: true, radio: true, trajectory: true }, // realistic rich
  { id: "dj:dina", outlinks: true, radio: true },    // radio + outlinks, no trajectory in current artifact
  { id: "dj:444thegod", outlinks: true },  // outlinks + events
  { id: "dj:王脏" }, // sparse long-tail: events only in current artifact
];

const DJ_OUTLINK_PUBLIC_ROLES = new Set(["listen", "social", "profile", "interview", "radio", "source", "video"]);

test("multi-sample DJ richness: sections render across the data distribution with gates holding", async () => {
  setEnv();
  const api = await import("../src/miniappAtlasApi.mjs");
  api.__resetMiniappAtlasApiCachesForTests();

  const summary = [];
  for (const s of SAMPLES) {
    const r = await api.getArtistById(s.id);
    assert.equal(r.found, true, `${s.id} must be found`);
    assert.ok(r.profile, `${s.id} must have a profile`);

    // Spine: every DJ has at least one event.
    assert.ok(Array.isArray(r.events) && r.events.length >= 1, `${s.id} must have >= 1 event`);

    const links = r.profile.externalLinks || [];
    const radio = r.radioPrograms || [];
    const traj = r.relationTrajectory;
    const cols = r.relatedColumns || [];
    const hasBio = Boolean(r.profile.bio && r.profile.bio.length);
    const hasBioCandidate = Boolean(r.profile.bioCandidate && r.profile.bioCandidate.length);

    // Expected-section assertions.
    if (s.bio) assert.ok(hasBio, `${s.id} expected a bio`);
    if (s.bioCandidate) assert.ok(hasBioCandidate, `${s.id} expected a source-backed bio candidate`);
    if (s.outlinks) assert.ok(links.length >= 1, `${s.id} expected outlinks`);
    if (s.radio) assert.ok(radio.length >= 1, `${s.id} expected radio programs`);
    if (s.trajectory) {
      assert.ok(traj && (traj.cities?.length || traj.venues?.length || traj.collaborators?.length),
        `${s.id} expected a relation trajectory`);
    }
    if (s.columns) assert.ok(cols.length >= 1, `${s.id} expected related columns`);

    // Gate invariants for EVERY sample regardless of expectation.
    for (const lk of links) {
      assert.notEqual(lk.role, "other", `${s.id}: 'other'-role outlink must be filtered`);
      assert.ok(DJ_OUTLINK_PUBLIC_ROLES.has(lk.role), `${s.id}: outlink role ${lk.role} not public-safe`);
      assert.equal(lk.candidateOnly, true, `${s.id}: outlink must be candidateOnly`);
      assert.ok(/^https?:\/\//.test(lk.url), `${s.id}: outlink url must be http(s): ${lk.url}`);
    }
    for (const pg of radio) {
      assert.notEqual(pg.reviewDecision, "hard_hide", `${s.id}: hard_hide radio must never surface`);
      assert.notEqual(pg.reviewDecision, "review_only", `${s.id}: review_only radio must not surface by default`);
      assert.ok(/^https?:\/\//.test(pg.url), `${s.id}: radio url must be http(s): ${pg.url}`);
    }

    summary.push({
      id: s.id, name: r.profile.displayName, events: r.events.length,
      bio: hasBio, bioCandidate: hasBioCandidate, outlinks: links.length, radio: radio.length,
      trajectory: Boolean(traj), columns: cols.length,
    });
  }

  // Print the matrix for the rendered-proof record.
  console.log("DJ richness multi-sample matrix:");
  for (const row of summary) console.log(`  ${row.id} (${row.name}): ev=${row.events} bio=${row.bio} bioCandidate=${row.bioCandidate} out=${row.outlinks} radio=${row.radio} traj=${row.trajectory} col=${row.columns}`);
});
