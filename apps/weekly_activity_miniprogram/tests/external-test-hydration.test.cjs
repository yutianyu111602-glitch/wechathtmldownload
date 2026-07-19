const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { gzipSync } = require("node:zlib");

const repoRoot = path.resolve(__dirname, "../../..");
const hydrator = path.join(repoRoot, "scripts/testing/hydrate_huaidj_test_artifacts.cjs");
const liveNames = [
  "atlas_index.json.gz",
  "atlas_neighborhood.json.gz",
  "atlas_starmap_lenses.json.gz",
  "dj_external_links_accepted_candidate.json.gz",
  "dj_relation_trajectory_lens.json.gz",
  "radio_external_links_public_seed_candidate.json.gz",
  "radio_programs_candidate.json.gz",
  "scene_clusters_candidate.json.gz",
];
const supplementalNames = [
  "bio_snippets_accepted.jsonl",
  "bio_candidates_accepted.jsonl",
  "radio_program_match_review.json.gz",
];

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "huaidj-hydration-"));
  const live = path.join(root, "live");
  const current = path.join(live, "current_release");
  const supplemental = path.join(root, "historical");
  const output = path.join(root, "external-output");
  fs.mkdirSync(current, { recursive: true });
  fs.mkdirSync(supplemental, { recursive: true });
  for (const name of liveNames) fs.writeFileSync(path.join(live, name), `live:${name}\n`, "utf8");
  const datasetId = "atlas-sha256-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
  fs.writeFileSync(
    path.join(live, "atlas_index.json.gz"),
    gzipSync(Buffer.from(JSON.stringify({ v: 4, datasetId, subjects: [] }), "utf8")),
  );
  fs.writeFileSync(
    path.join(live, "atlas_neighborhood.json.gz"),
    gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.miniapp.neighborhood_bundle.v1",
      datasetId,
      generation: { source: "fixture-generated", subjectCount: 0 },
      byNode: {},
    }), "utf8")),
  );
  for (const name of supplementalNames) fs.writeFileSync(path.join(supplemental, name), `historical:${name}\n`, "utf8");
  fs.writeFileSync(path.join(current, "manifest.json"), JSON.stringify({
    schema_version: "weekly_activity_miniprogram_api.v1",
    generated_at: "2026-07-18T19:58:51+08:00",
    item_count: 626,
    window_start: "2026-06-21",
    window_end: "2026-08-01",
  }), "utf8");
  fs.writeFileSync(path.join(current, "current.json"), JSON.stringify({ items: [{ id: "event-a" }] }), "utf8");
  fs.writeFileSync(path.join(current, "column.json"), JSON.stringify({ schemaVersion: "column.v1" }), "utf8");
  const broad = path.join(root, "historical-broad-preview.json.gz");
  fs.writeFileSync(broad, "historical:broad-preview\n", "utf8");
  return { root, live, current, supplemental, output, broad };
}

function writeAtlasTriplet(root) {
  const triplet = path.join(root, "atlas-triplet");
  fs.mkdirSync(triplet, { recursive: true });
  const datasetId = "atlas-sha256-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
  const artifacts = {
    "atlas_index.json.gz": gzipSync(Buffer.from(JSON.stringify({ v: 5, datasetId, subjects: [] }), "utf8")),
    "atlas_neighborhood.json.gz": gzipSync(Buffer.from(JSON.stringify({
      schemaVersion: "atlas.miniapp.neighborhood_bundle.v1",
      datasetId,
      generation: { source: "verified-triplet-fixture", subjectCount: 0 },
      byNode: {},
    }), "utf8")),
  };
  const manifestArtifacts = {};
  for (const [name, body] of Object.entries(artifacts)) {
    const target = path.join(triplet, name);
    fs.writeFileSync(target, body);
    manifestArtifacts[name] = { size: body.length, sha256: sha256(target) };
  }
  fs.writeFileSync(path.join(triplet, "atlas_triplet_manifest.json"), JSON.stringify({
    schemaVersion: "atlas.serving.triplet.candidate.v1",
    decision: "atlas_serving_triplet_candidate_ready",
    datasetId,
    artifacts: manifestArtifacts,
    productionWriteExecuted: false,
    deployExecuted: false,
  }), "utf8");
  return { triplet, datasetId };
}

test("external hydrator fail-closes when historical-only evidence is not explicitly allowed", (t) => {
  const f = fixture();
  t.after(() => fs.rmSync(f.root, { recursive: true, force: true }));
  const result = spawnSync(process.execPath, [
    hydrator,
    "--repo-root", repoRoot,
    "--live-data-dir", f.live,
    "--current-release-dir", f.current,
    "--output-dir", f.output,
  ], { encoding: "utf8" });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /historical supplemental evidence/i);
  assert.equal(fs.existsSync(f.output), false);
});

test("external hydrator records live and explicitly allowed historical identities outside Git", (t) => {
  const f = fixture();
  t.after(() => fs.rmSync(f.root, { recursive: true, force: true }));
  const result = spawnSync(process.execPath, [
    hydrator,
    "--repo-root", repoRoot,
    "--live-data-dir", f.live,
    "--current-release-dir", f.current,
    "--supplemental-data-dir", f.supplemental,
    "--broad-outlink-preview", f.broad,
    "--output-dir", f.output,
    "--allow-historical-supplemental",
  ], { encoding: "utf8" });

  assert.equal(result.status, 0, result.stderr || result.stdout);
  const resultJson = JSON.parse(result.stdout);
  const manifest = JSON.parse(fs.readFileSync(resultJson.manifestPath, "utf8"));
  assert.equal(path.resolve(f.output).startsWith(repoRoot), false);
  assert.equal(manifest.currentRelease.identity.itemCount, 626);
  assert.equal(manifest.artifactHandshake.ok, true);
  assert.equal(manifest.artifactHandshake.indexDatasetId, manifest.artifactHandshake.neighborhoodDatasetId);
  assert.equal(manifest.artifactHandshake.neighborhoodGenerationSource, "fixture-generated");
  assert.equal(manifest.artifactHandshake.neighborhoodGenerationSourceLooksTemporary, false);
  assert.equal(manifest.files.filter((item) => item.authority === "live_external_ssot").length, liveNames.length);
  assert.equal(manifest.files.filter((item) => item.authority === "historical_test_supplement").length, supplementalNames.length + 1);
  for (const item of manifest.files) {
    assert.equal(item.sourceSha256, item.hydratedSha256);
    assert.equal(item.sourceSha256, sha256(item.source));
    assert.equal(fs.existsSync(item.hydrated), true);
  }
  const isolated = manifest.files.find((item) => item.name === "atlas_starmap_lenses.json.gz");
  const sourceBefore = fs.readFileSync(isolated.source);
  fs.writeFileSync(isolated.hydrated, "mutated hydrated test copy\n", "utf8");
  assert.deepEqual(fs.readFileSync(isolated.source), sourceBefore);
  assert.equal(manifest.files.every((item) => item.materialization === "copy"), true);
});

test("external hydrator overlays only a digest-verified Atlas triplet generation", (t) => {
  const f = fixture();
  const atlas = writeAtlasTriplet(f.root);
  t.after(() => fs.rmSync(f.root, { recursive: true, force: true }));
  const result = spawnSync(process.execPath, [
    hydrator,
    "--repo-root", repoRoot,
    "--live-data-dir", f.live,
    "--current-release-dir", f.current,
    "--supplemental-data-dir", f.supplemental,
    "--broad-outlink-preview", f.broad,
    "--atlas-triplet-dir", atlas.triplet,
    "--output-dir", f.output,
    "--allow-historical-supplemental",
  ], { encoding: "utf8" });

  assert.equal(result.status, 0, result.stderr || result.stdout);
  const resultJson = JSON.parse(result.stdout);
  const manifest = JSON.parse(fs.readFileSync(resultJson.manifestPath, "utf8"));
  assert.equal(manifest.artifactHandshake.ok, true);
  assert.equal(manifest.artifactHandshake.indexDatasetId, atlas.datasetId);
  assert.equal(manifest.provenance.atlasTripletSource, path.resolve(atlas.triplet));
  assert.equal(manifest.provenance.atlasTripletDatasetId, atlas.datasetId);
  assert.equal(
    manifest.files.filter((item) => item.authority === "verified_atlas_triplet_candidate").length,
    2,
  );
  assert.equal(
    manifest.files.filter((item) => item.authority === "live_external_ssot").length,
    liveNames.length - 2,
  );
});

test("external hydrator rejects a tampered Atlas triplet before writing output", (t) => {
  const f = fixture();
  const atlas = writeAtlasTriplet(f.root);
  fs.appendFileSync(path.join(atlas.triplet, "atlas_index.json.gz"), "tampered");
  t.after(() => fs.rmSync(f.root, { recursive: true, force: true }));
  const result = spawnSync(process.execPath, [
    hydrator,
    "--repo-root", repoRoot,
    "--live-data-dir", f.live,
    "--current-release-dir", f.current,
    "--supplemental-data-dir", f.supplemental,
    "--broad-outlink-preview", f.broad,
    "--atlas-triplet-dir", atlas.triplet,
    "--output-dir", f.output,
    "--allow-historical-supplemental",
  ], { encoding: "utf8" });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Atlas triplet digest mismatch/);
  assert.equal(fs.existsSync(f.output), false);
});

test("every DevTools artifact writer honors the external artifact root", () => {
  const writerNames = fs.readdirSync(__dirname)
    .filter((name) => /^devtools.*\.cjs$/.test(name))
    .filter((name) => /const artifactRoot\s*=/.test(fs.readFileSync(path.join(__dirname, name), "utf8")));

  assert.ok(writerNames.length > 0, "expected at least one DevTools artifact writer");
  for (const name of writerNames) {
    const source = fs.readFileSync(path.join(__dirname, name), "utf8");
    assert.match(
      source,
      /process\.env\.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT/,
      `${name} must allow artifacts to be redirected outside the Git worktree`,
    );
  }
});

test("DevTools launch scripts do not pass the IDE HTTP port twice", () => {
  const scriptNames = fs.readdirSync(__dirname).filter((name) => /^devtools.*\.cjs$/.test(name));
  for (const name of scriptNames) {
    const source = fs.readFileSync(path.join(__dirname, name), "utf8");
    assert.doesNotMatch(
      source,
      /const cliArgs\s*=.*\["--port"/,
      `${name} must use automator.launch({ idePort }) without duplicating --port in args`,
    );
  }
});
