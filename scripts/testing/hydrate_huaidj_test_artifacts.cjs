const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { gunzipSync } = require("node:zlib");

const LIVE_EXTERNAL_FILES = [
  "atlas_index.json.gz",
  "atlas_neighborhood.json.gz",
  "atlas_starmap_lenses.json.gz",
  "dj_external_links_accepted_candidate.json.gz",
  "dj_relation_trajectory_lens.json.gz",
  "radio_external_links_public_seed_candidate.json.gz",
  "radio_programs_candidate.json.gz",
  "scene_clusters_candidate.json.gz",
];

const HISTORICAL_SUPPLEMENTAL_FILES = [
  "bio_snippets_accepted.jsonl",
  "bio_candidates_accepted.jsonl",
  "radio_program_match_review.json.gz",
];

const BROAD_OUTLINK_TARGET = "dj_external_links_accepted_plus_broad_preview_candidate.json.gz";
const ATLAS_TRIPLET_FILES = new Set([
  "atlas_index.json.gz",
  "atlas_neighborhood.json.gz",
]);

function parseArgs(argv) {
  const result = { allowHistoricalSupplemental: false };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--allow-historical-supplemental") {
      result.allowHistoricalSupplemental = true;
      continue;
    }
    if (!token.startsWith("--")) throw new Error(`unexpected argument: ${token}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`missing value for ${token}`);
    const key = token.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    result[key] = value;
    index += 1;
  }
  return result;
}

function canonical(filePath) {
  return path.resolve(filePath).replace(/[\\/]+$/, "").toLowerCase();
}

function isInside(candidatePath, parentPath) {
  const relative = path.relative(canonical(parentPath), canonical(candidatePath));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function requireFile(filePath, label) {
  let stat;
  try {
    stat = fs.statSync(filePath);
  } catch {
    throw new Error(`${label} is missing: ${filePath}`);
  }
  if (!stat.isFile()) throw new Error(`${label} is not a file: ${filePath}`);
  return stat;
}

function requireDirectory(directoryPath, label) {
  let stat;
  try {
    stat = fs.statSync(directoryPath);
  } catch {
    throw new Error(`${label} is missing: ${directoryPath}`);
  }
  if (!stat.isDirectory()) throw new Error(`${label} is not a directory: ${directoryPath}`);
  return stat;
}

function sha256File(filePath) {
  const hash = crypto.createHash("sha256");
  const descriptor = fs.openSync(filePath, "r");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    let bytesRead = 0;
    do {
      bytesRead = fs.readSync(descriptor, buffer, 0, buffer.length, null);
      if (bytesRead > 0) hash.update(buffer.subarray(0, bytesRead));
    } while (bytesRead > 0);
  } finally {
    fs.closeSync(descriptor);
  }
  return hash.digest("hex");
}

function copyIsolated(source, destination) {
  // Test fixtures must never share writable file identity with live SSOT data.
  // A regular copy is intentionally preferred over hard links; filesystems may
  // transparently optimize it with safe copy-on-write semantics.
  fs.copyFileSync(source, destination, fs.constants.COPYFILE_EXCL);
  return "copy";
}

function readJson(filePath, label) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    throw new Error(`${label} is not valid JSON: ${filePath}: ${error.message}`);
  }
}

function verifiedAtlasTriplet(directoryPath) {
  const directory = path.resolve(directoryPath);
  requireDirectory(directory, "Atlas triplet directory");
  const manifestPath = path.join(directory, "atlas_triplet_manifest.json");
  requireFile(manifestPath, "Atlas triplet manifest");
  const manifest = readJson(manifestPath, "Atlas triplet manifest");
  const datasetId = String(manifest?.datasetId || "").trim();
  if (manifest?.schemaVersion !== "atlas.serving.triplet.candidate.v1" || !datasetId) {
    throw new Error(`Atlas triplet manifest has no accepted dataset identity: ${manifestPath}`);
  }
  if (manifest?.decision !== "atlas_serving_triplet_candidate_ready") {
    throw new Error(`Atlas triplet manifest is not ready: ${manifestPath}`);
  }
  const files = {};
  for (const name of ATLAS_TRIPLET_FILES) {
    const source = path.join(directory, name);
    const stat = requireFile(source, `Atlas triplet ${name}`);
    const expected = manifest?.artifacts?.[name];
    const expectedSha256 = String(expected?.sha256 || "").trim().toLowerCase();
    const actualSha256 = sha256File(source);
    if (!/^[a-f0-9]{64}$/.test(expectedSha256) || expectedSha256 !== actualSha256) {
      throw new Error(`Atlas triplet digest mismatch for ${name}`);
    }
    if (Number(expected?.size) !== stat.size) {
      throw new Error(`Atlas triplet size mismatch for ${name}`);
    }
    files[name] = source;
  }
  const handshake = atlasArtifactHandshake(files["atlas_index.json.gz"], files["atlas_neighborhood.json.gz"]);
  if (!handshake.ok || handshake.indexDatasetId !== datasetId) {
    throw new Error(`Atlas triplet artifact identity mismatch: ${handshake.reason || "manifest_dataset_mismatch"}`);
  }
  return { directory, manifestPath, datasetId, files, handshake };
}

function readArtifactJson(filePath) {
  const buffer = fs.readFileSync(filePath);
  const raw = String(filePath).toLowerCase().endsWith(".gz") ? gunzipSync(buffer) : buffer;
  return JSON.parse(raw.toString("utf8"));
}

function atlasArtifactHandshake(indexPath, neighborhoodPath) {
  let index;
  let neighborhood;
  try {
    index = readArtifactJson(indexPath);
    neighborhood = readArtifactJson(neighborhoodPath);
  } catch (error) {
    return {
      ok: false,
      reason: "artifact_parse_failed",
      error: error.message,
      indexDatasetId: "",
      neighborhoodDatasetId: "",
    };
  }
  const indexDatasetId = String(index?.datasetId || "").trim();
  const neighborhoodDatasetId = String(neighborhood?.datasetId || "").trim();
  const neighborhoodGenerationSource = String(neighborhood?.generation?.source || "").trim();
  let reason = "";
  if (!indexDatasetId || !neighborhoodDatasetId) reason = "dataset_id_missing";
  else if (indexDatasetId !== neighborhoodDatasetId) reason = "dataset_mismatch";
  return {
    ok: !reason,
    reason,
    indexDatasetId,
    neighborhoodDatasetId,
    indexVersion: index?.v ?? null,
    indexSubjectCount: Array.isArray(index?.subjects) ? index.subjects.length : null,
    neighborhoodSchemaVersion: String(neighborhood?.schemaVersion || ""),
    neighborhoodSubjectCount: neighborhood?.generation?.subjectCount
      ?? (neighborhood?.byNode && typeof neighborhood.byNode === "object" ? Object.keys(neighborhood.byNode).length : null),
    neighborhoodGenerationSource,
    neighborhoodGenerationSourceLooksTemporary: /(^|[\\/])(?:temp|tmp)(?:[\\/]|$)/i.test(neighborhoodGenerationSource),
  };
}

function currentReleaseIdentity(currentReleaseDir, observedAt) {
  const files = ["manifest.json", "current.json", "column.json"].map((name) => {
    const source = path.join(currentReleaseDir, name);
    const stat = requireFile(source, `current release ${name}`);
    return {
      name,
      source,
      size: stat.size,
      modifiedAt: stat.mtime.toISOString(),
      sha256: sha256File(source),
    };
  });
  const manifest = readJson(path.join(currentReleaseDir, "manifest.json"), "current release manifest");
  const generatedAt = manifest.generated_at || manifest.generatedAt || "";
  const generatedTime = Date.parse(generatedAt);
  const observedTime = Date.parse(observedAt);
  const ageHours = Number.isFinite(generatedTime)
    ? Number(((observedTime - generatedTime) / 3600000).toFixed(3))
    : null;
  return {
    directory: currentReleaseDir,
    identity: {
      schemaVersion: manifest.schema_version || manifest.schemaVersion || "",
      generatedAt,
      itemCount: manifest.item_count ?? manifest.itemCount ?? null,
      windowStart: manifest.window_start || manifest.windowStart || "",
      windowEnd: manifest.window_end || manifest.windowEnd || "",
    },
    freshness: {
      observedAt,
      ageHours,
      generatedAtParseable: Number.isFinite(generatedTime),
      notFutureBeyondFiveMinutes: ageHours === null ? false : ageHours >= -(5 / 60),
      notOlderThan72Hours: ageHours === null ? false : ageHours <= 72,
    },
    files,
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const requiredArgs = ["repoRoot", "liveDataDir", "currentReleaseDir", "outputDir"];
  for (const key of requiredArgs) {
    if (!args[key]) throw new Error(`missing required --${key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`);
  }

  if (!args.allowHistoricalSupplemental) {
    throw new Error(
      "historical supplemental evidence is required by the legacy full-test contract; pass "
      + "--allow-historical-supplemental with explicit supplemental paths after reviewing provenance",
    );
  }
  if (!args.supplementalDataDir || !args.broadOutlinkPreview) {
    throw new Error(
      "historical supplemental evidence requires --supplemental-data-dir and --broad-outlink-preview",
    );
  }

  const repoRoot = path.resolve(args.repoRoot);
  const liveDataDir = path.resolve(args.liveDataDir);
  const currentReleaseDir = path.resolve(args.currentReleaseDir);
  const supplementalDataDir = path.resolve(args.supplementalDataDir);
  const broadOutlinkPreview = path.resolve(args.broadOutlinkPreview);
  const outputDir = path.resolve(args.outputDir);
  const atlasTriplet = args.atlasTripletDir ? verifiedAtlasTriplet(args.atlasTripletDir) : null;
  if (path.dirname(outputDir) === outputDir) throw new Error(`output directory cannot be a filesystem root: ${outputDir}`);
  if (isInside(outputDir, repoRoot)) throw new Error(`output directory must remain outside the Git worktree: ${outputDir}`);
  if (fs.existsSync(outputDir)) throw new Error(`output directory already exists: ${outputDir}`);

  requireDirectory(repoRoot, "repo root");
  requireDirectory(liveDataDir, "live data directory");
  requireDirectory(currentReleaseDir, "current release directory");
  requireDirectory(supplementalDataDir, "historical supplemental directory");
  const observedAt = new Date().toISOString();
  const currentRelease = currentReleaseIdentity(currentReleaseDir, observedAt);

  const inputs = [];
  for (const name of LIVE_EXTERNAL_FILES) {
    const tripletSource = atlasTriplet && ATLAS_TRIPLET_FILES.has(name) ? atlasTriplet.files[name] : "";
    inputs.push({
      name,
      source: tripletSource || path.join(liveDataDir, name),
      authority: tripletSource ? "verified_atlas_triplet_candidate" : "live_external_ssot",
    });
  }
  for (const name of HISTORICAL_SUPPLEMENTAL_FILES) {
    inputs.push({ name, source: path.join(supplementalDataDir, name), authority: "historical_test_supplement" });
  }
  inputs.push({
    name: BROAD_OUTLINK_TARGET,
    source: broadOutlinkPreview,
    authority: "historical_test_supplement",
  });
  for (const input of inputs) {
    const stat = requireFile(input.source, `${input.authority} ${input.name}`);
    input.size = stat.size;
    input.modifiedAt = stat.mtime.toISOString();
    input.sourceSha256 = sha256File(input.source);
  }
  const artifactHandshake = atlasArtifactHandshake(
    inputs.find((item) => item.name === "atlas_index.json.gz").source,
    inputs.find((item) => item.name === "atlas_neighborhood.json.gz").source,
  );

  const partialDir = `${outputDir}.partial-${process.pid}`;
  if (fs.existsSync(partialDir)) throw new Error(`partial output directory already exists: ${partialDir}`);
  const partialDataDir = path.join(partialDir, "hydrated-data");
  const finalDataDir = path.join(outputDir, "hydrated-data");
  let completed = false;
  try {
    fs.mkdirSync(partialDataDir, { recursive: true });
    const files = inputs.map((input) => {
      const partialTarget = path.join(partialDataDir, input.name);
      const finalTarget = path.join(finalDataDir, input.name);
      const materialization = copyIsolated(input.source, partialTarget);
      const hydratedSha256 = sha256File(partialTarget);
      if (hydratedSha256 !== input.sourceSha256) {
        throw new Error(`hydrated hash mismatch for ${input.name}`);
      }
      return {
        name: input.name,
        authority: input.authority,
        source: input.source,
        hydrated: finalTarget,
        materialization,
        size: input.size,
        modifiedAt: input.modifiedAt,
        sourceSha256: input.sourceSha256,
        hydratedSha256,
      };
    });
    const manifest = {
      schemaVersion: "huaidj_external_test_hydration.v1",
      generatedAt: observedAt,
      repoRoot,
      outputDir,
      hydratedDataDir: finalDataDir,
      currentRelease,
      artifactHandshake,
      files,
      provenance: {
        liveExternalSource: liveDataDir,
        atlasTripletSource: atlasTriplet?.directory || "",
        atlasTripletManifest: atlasTriplet?.manifestPath || "",
        atlasTripletDatasetId: atlasTriplet?.datasetId || "",
        historicalSupplementalSource: supplementalDataDir,
        historicalSupplementalExplicitlyAllowed: true,
        historicalSupplementalIsProductionAuthority: false,
      },
      safety: {
        outputOutsideGitWorktree: true,
        sourceArtifactsWritten: false,
        deploymentExecuted: false,
        uploadExecuted: false,
      },
    };
    fs.writeFileSync(
      path.join(partialDir, "hydration-manifest.json"),
      `${JSON.stringify(manifest, null, 2)}\n`,
      "utf8",
    );
    fs.renameSync(partialDir, outputDir);
    completed = true;
    process.stdout.write(`${JSON.stringify({
      ok: true,
      manifestPath: path.join(outputDir, "hydration-manifest.json"),
      hydratedDataDir: finalDataDir,
      broadOutlinkPreviewPath: path.join(finalDataDir, BROAD_OUTLINK_TARGET),
      currentReleaseDir,
    })}\n`);
  } finally {
    if (!completed && fs.existsSync(partialDir)) {
      fs.rmSync(partialDir, { recursive: true, force: true });
    }
  }
}

try {
  main();
} catch (error) {
  process.stderr.write(`external hydration failed: ${error.message}\n`);
  process.exitCode = 1;
}
