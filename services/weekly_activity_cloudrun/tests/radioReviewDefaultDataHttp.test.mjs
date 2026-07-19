import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../../..");
const dataDir = path.resolve(process.env.HUAIDJ_ATLAS_MINIAPP_DATA_DIR || path.join(repoRoot, "services/weekly_activity_cloudrun/data"));

const FETCH_BLOCKED_PORTS = new Set([
  1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79,
  87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137,
  139, 143, 161, 179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532,
  540, 548, 554, 556, 563, 587, 601, 636, 989, 990, 993, 995, 1719, 1720,
  1723, 2049, 3659, 4045, 5060, 5061, 6000, 6566, 6665, 6666, 6667, 6668,
  6669, 6697, 10080,
]);

async function listen(serverInstance) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await new Promise((resolve, reject) => {
      const onError = (error) => {
        serverInstance.off("listening", onListening);
        reject(error);
      };
      const onListening = () => {
        serverInstance.off("error", onError);
        resolve();
      };
      serverInstance.once("error", onError);
      serverInstance.once("listening", onListening);
      serverInstance.listen(0, "127.0.0.1");
    });
    const address = serverInstance.address();
    if (!FETCH_BLOCKED_PORTS.has(address.port)) {
      return `http://127.0.0.1:${address.port}`;
    }
    await new Promise((resolve) => serverInstance.close(resolve));
  }
  throw new Error("Could not allocate a fetch-compatible local test port");
}

test("radio review service data pack drives default HTTP filtering", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "radio-review-default-data-"));
  const previousEnv = {
    ATLAS_MINIAPP_PRELOAD: process.env.ATLAS_MINIAPP_PRELOAD,
    ATLAS_RADIO_PROGRAMS: process.env.ATLAS_RADIO_PROGRAMS,
    ATLAS_RADIO_PROGRAM_MATCH_REVIEW: process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW,
    ATLAS_REQUIRE_SESSION: process.env.ATLAS_REQUIRE_SESSION,
    CROSS_DB_MERGE_MAP: process.env.CROSS_DB_MERGE_MAP,
  };
  let server;
  try {
    const emptyMergeMap = path.join(dir, "empty-merge-map.json");
    await writeFile(emptyMergeMap, JSON.stringify({ db2_to_db3_map: {}, existing_subject_map: {} }), "utf8");

    const reviewRaw = gunzipSync(
      await readFile(path.join(dataDir, "radio_program_match_review.json.gz"))
    ).toString("utf8");
    const review = JSON.parse(reviewRaw);
    assert.equal(review.schemaVersion, "atlas.radio_program_match_review.v1");
    assert.equal(review.candidateOnly, true);
    assert.equal(review.productionWriteExecuted, false);

    const hard = review.rows.find((row) => row.decision === "hard_hide" && row.djId && row.programId);
    const reviewOnly = review.rows.find((row) => row.decision === "review_only" && row.djId && row.programId);
    assert.ok(hard, "expected at least one hard_hide review row");
    assert.ok(reviewOnly, "expected at least one review_only review row");

    process.env.ATLAS_MINIAPP_PRELOAD = "0";
    process.env.ATLAS_RADIO_PROGRAMS = path.join(dataDir, "radio_programs_candidate.json.gz");
    process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW = path.join(dataDir, "radio_program_match_review.json.gz");
    process.env.ATLAS_REQUIRE_SESSION = "false";
    process.env.CROSS_DB_MERGE_MAP = emptyMergeMap;

    const { createServer } = await import(`../src/server.mjs?radio-review-default-data=${Date.now()}`);
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

    const hardDefault = await getJson(`/api/v1/weekly/atlas/radio-programs?djId=${encodeURIComponent(hard.djId)}&limit=500`);
    const hardInclude = await getJson(`/api/v1/weekly/atlas/radio-programs?djId=${encodeURIComponent(hard.djId)}&includeReviewOnly=1&limit=500`);
    const reviewDefault = await getJson(`/api/v1/weekly/atlas/radio-programs?djId=${encodeURIComponent(reviewOnly.djId)}&limit=500`);
    const reviewInclude = await getJson(`/api/v1/weekly/atlas/radio-programs?djId=${encodeURIComponent(reviewOnly.djId)}&includeReviewOnly=1&limit=500`);
    const hasProgram = (payload, programId) => (payload.programs || []).some((program) => program.programId === programId);

    assert.equal(hardDefault.matchReview.available, true);
    assert.equal(hardDefault.matchReview.defaultPolicy, "safe_display_only_for_dj_detail");
    assert.equal(hardDefault.matchReview.counts.decision_hard_hide, 1978);
    assert.equal(hasProgram(hardDefault, hard.programId), false);
    assert.equal(hasProgram(hardInclude, hard.programId), false);
    assert.equal(hasProgram(reviewDefault, reviewOnly.programId), false);
    assert.equal(hasProgram(reviewInclude, reviewOnly.programId), true);
  } finally {
    if (server) await new Promise((resolve) => server.close(resolve));
    for (const [key, value] of Object.entries(previousEnv)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await rm(dir, { recursive: true, force: true });
  }
});
