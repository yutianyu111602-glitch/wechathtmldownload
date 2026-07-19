/**
 * Rendered proof: the richest DJ profile (max-richness sample from the richness audit)
 * renders ALL product-layer sections together, live — atlas history, frequent venues,
 * collaborators, relation trajectory, related columns, accepted outlinks, and radio
 * leads — with the outlink role-gate and no hard_hide/review_only radio surfacing.
 * Safety: read-only; no upload/deploy/review/release/production DB write.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");
const { connectRawDevtools } = require("./devtools-raw-session.cjs");

const wsEndpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "").trim();
const artifactRoot = process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT
  ? path.resolve(process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT)
  : path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `artist-max-richness-rendered-${stamp}`);
const targetName = String(process.env.ATLAS_RENDER_ARTIST_NAME || "SULK").trim();
const targetSubjectId = String(process.env.ATLAS_RENDER_ARTIST_SUBJECT_ID || "dj:sulk").trim();
const atlasDataDir = path.resolve(
  process.env.HUAIDJ_ATLAS_MINIAPP_DATA_DIR
    || path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data"),
);
const steps = [];
let lastFailureContext = {};
const runtimeContext = {};

fs.mkdirSync(artifactDir, { recursive: true });

function withTimeout(promise, ms, label) {
  let t;
  return Promise.race([
    promise,
    new Promise((_, reject) => { t = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms); }),
  ]).finally(() => clearTimeout(t));
}
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
async function listen(s) { await new Promise((r) => s.listen(0, "127.0.0.1", r)); return `http://127.0.0.1:${s.address().port}`; }
function writeJson(name, value) { fs.writeFileSync(path.join(artifactDir, name), JSON.stringify(value, null, 2), "utf8"); }

async function step(label, run) {
  const item = { label, startedAt: new Date().toISOString() };
  steps.push(item);
  try { const r = await run(); item.ok = true; item.finishedAt = new Date().toISOString(); return r; }
  catch (e) { item.ok = false; item.error = e && e.stack ? e.stack : String(e); item.finishedAt = new Date().toISOString(); throw e; }
}
function connectDevtools(endpoint) {
  return connectRawDevtools({ endpoint, timeoutMs: 120000 });
}
function sendProtocol(ws, method, params = {}, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const id = `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
    const t = setTimeout(() => { ws.off("message", onMsg); reject(new Error(`${method} timeout`)); }, timeoutMs);
    function onMsg(raw) {
      let m; try { m = JSON.parse(String(raw)); } catch { return; }
      if (m.id !== id) return;
      clearTimeout(t); ws.off("message", onMsg);
      if (m.error) reject(new Error(`${method} failed: ${JSON.stringify(m.error)}`)); else resolve(m.result || {});
    }
    ws.on("message", onMsg);
    ws.send(JSON.stringify({ id, method, params }));
  });
}
function callApp(ws, fn, args = [], timeoutMs = 30000) {
  return sendProtocol(ws, "App.callFunction", { functionDeclaration: fn.toString(), args }, timeoutMs).then((r) => r.result);
}
async function pollUntil(label, timeoutMs, intervalMs, read, done) {
  const start = Date.now(); let last;
  while (Date.now() - start <= timeoutMs) {
    try { last = await read(); } catch { last = { ok: false }; }
    if (done(last)) return last;
    await sleep(intervalMs);
  }
  throw new Error(`${label} timed out; last=${JSON.stringify(last)}`);
}
function closeSocket(ws) {
  return new Promise((resolve) => {
    if (!ws || ws.readyState === WebSocket.CLOSED) { resolve(); return; }
    ws.once("close", resolve);
    try { ws.close(); } catch { resolve(); }
    setTimeout(resolve, 1000);
  });
}

async function main() {
  process.env.ATLAS_MINIAPP_PRELOAD = "0";
  process.env.ATLAS_MINIAPP_INDEX = path.join(atlasDataDir, "atlas_index.json.gz");
  process.env.ATLAS_DJ_EXTERNAL_LINKS = path.join(atlasDataDir, "dj_external_links_accepted_candidate.json.gz");
  process.env.ATLAS_RADIO_PROGRAMS = path.join(atlasDataDir, "radio_programs_candidate.json.gz");
  process.env.ATLAS_RADIO_PROGRAM_MATCH_REVIEW = path.join(atlasDataDir, "radio_program_match_review.json.gz");
  process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = path.join(atlasDataDir, "dj_relation_trajectory_lens.json.gz");
  process.env.ATLAS_NEIGHBORHOOD_BUNDLE = path.join(atlasDataDir, "atlas_neighborhood.json.gz");

  const { createServer } = await import("../../../services/weekly_activity_cloudrun/src/server.mjs");
  let server, ws;
  try {
    server = createServer({
      store: { getCurrent: async () => ({ schemaVersion: "weekly.current.test.v1", items: [], page: { nextCursor: null } }) },
      stage7Store: {}, llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      soundStore: {}, interviewStore: {},
      env: { ...process.env, ATLAS_REQUIRE_SESSION: "false" },
    });
    const baseUrl = await listen(server);
    runtimeContext.baseUrl = baseUrl;

    ws = await step("connect or launch DevTools", () => withTimeout(connectDevtools(wsEndpoint), 140000, "DevTools session"));

    await step("inject local backend", () => withTimeout(callApp(ws, function inject(base) {
      const c = getApp().globalData.cloud;
      c.useMock = false; c.publicBaseUrl = base; c.staticBaseUrl = "";
      c.useCloudDatabaseFirst = false; c.offlineSnapshotFallback = false; c.fastOfflineSnapshotFallback = false;
      c.publicFallbackDelayMs = 0; c.cacheMaxAgeMs = 0; c.cacheFallbackDelayMs = 60000;
      c.publicRequestTimeoutMs = 20000; c.requestTimeoutMs = 20000;
      c.cloudClient = { callContainer: () => Promise.reject({ error: { code: "LOCAL_ONLY" } }), callFunction: () => Promise.reject({ error: { code: "LOCAL_ONLY" } }) };
      c.cloudReady = true; c.cloudInitPromise = null;
      try { wx.setStorageSync("weeklyActivityDevtoolsApiOverride:v1", { publicBaseUrl: base, createdAt: Date.now() }); } catch (e) {}
      try { const info = wx.getStorageInfoSync(); (info.keys || []).forEach((k) => { if (String(k).indexOf("weeklyActivityApiCache:") === 0) wx.removeStorageSync(k); }); } catch (e) {}
      return { injected: true };
    }, [baseUrl], 60000), 70000, "inject"));

    const artistUrl = `/pages/artist/artist?name=${encodeURIComponent(targetName)}&subjectId=${encodeURIComponent(targetSubjectId)}&lang=zh&renderProofTs=${encodeURIComponent(stamp)}`;
    await step("launch artist page", () => withTimeout(callApp(ws, function launch(url) {
      return new Promise((resolve) => wx.reLaunch({ url, success: () => resolve({ ok: true }), fail: (e) => resolve({ ok: false, e }) }));
    }, [artistUrl], 20000), 25000, "reLaunch"));

    await sleep(5000);

    await step("wait load=false", () => withTimeout(pollUntil(
      "wait load=false", 30000, 700,
      () => callApp(ws, function readLoad() {
        const p = typeof getCurrentPages !== "undefined" ? getCurrentPages()[getCurrentPages().length - 1] : null;
        const d = p && p.data ? p.data : {};
        return { route: p && p.route, loading: Boolean(d.loading) };
      }, [], 8000),
      (s) => s && s.route === "pages/artist/artist" && s.loading === false,
    ), 35000, "load=false"));

    const state = await step("read all rich sections", () => withTimeout(callApp(ws, function readRich() {
      const p = getCurrentPages()[getCurrentPages().length - 1];
      const d = p && p.data ? p.data : {};
      const links = Array.isArray(d.djOutlinks) ? d.djOutlinks : [];
      const radio = Array.isArray(d.radioPrograms) ? d.radioPrograms : [];
      const traj = d.relationTrajectory || null;
      return {
        route: p && p.route,
        loading: Boolean(d.loading),
        atlasEvents: (d.atlasEvents || []).length,
        atlasVenues: (d.atlasVenues || []).length,
        atlasCollaborators: (d.atlasCollaborators || []).length,
        relatedColumns: (d.relatedColumns || []).length,
        outlinks: links.length,
        outlinkRoles: links.map((l) => l && l.role),
        outlinkCandidateFlags: links.map((l) => l && l.candidateOnly),
        radio: radio.length,
        radioReviewDecisions: radio.map((r) => r && r.reviewDecision),
        hasTrajectory: Boolean(traj),
        trajectoryCities: traj && Array.isArray(traj.cities) ? traj.cities.length : 0,
        trajectoryVenues: traj && Array.isArray(traj.venues) ? traj.venues.length : 0,
        trajectoryCollaborators: traj && Array.isArray(traj.collaborators) ? traj.collaborators.length : 0,
      };
    }, [], 15000), 20000, "read rich"));

    // Assertions: the max-richness profile renders every section at once.
    assert.equal(state.route, "pages/artist/artist", "artist page must be current");
    assert.equal(state.loading, false, "page must not be loading");
    assert.ok(state.atlasEvents >= 1, "atlas history must render");
    assert.ok(state.atlasVenues >= 1, "frequent venues must render");
    assert.ok(state.atlasCollaborators >= 1, "collaborators must render");
    assert.ok(state.hasTrajectory, "relation trajectory must render for a max-richness DJ");
    assert.ok(state.trajectoryCities >= 1 || state.trajectoryVenues >= 1 || state.trajectoryCollaborators >= 1, "trajectory must carry data");
    assert.ok(state.relatedColumns >= 1, "related columns must render");
    assert.ok(state.outlinks >= 1, "accepted outlinks must render");
    assert.ok(!state.outlinkRoles.includes("other"), "no other-role outlinks (gate)");
    assert.ok(state.outlinkCandidateFlags.every((f) => f === true), "all outlinks candidateOnly");
    assert.ok(state.radio >= 1, "radio leads must render");
    assert.ok(!state.radioReviewDecisions.includes("hard_hide"), "no hard_hide radio surfaced");
    assert.ok(!state.radioReviewDecisions.includes("review_only"), "no review_only radio surfaced by default");

    const report = {
      schemaVersion: "devtools_artist_max_richness_rendered.v1",
      generatedAt: new Date().toISOString(),
      artifactDir, wsEndpoint, baseUrl, target: { name: targetName, subjectId: targetSubjectId },
      state, steps,
      safety: { miniProgramUploadExecuted: false, cloudRunDeployExecuted: false, previewQrGenerated: false, reviewSubmitted: false, publicReleaseExecuted: false, productionDbWriteExecuted: false },
    };
    writeJson("report.json", report);
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    lastFailureContext = { debugState: "failed", error: error && error.message };
    throw error;
  } finally {
    if (ws) {
      await callApp(ws, function clearOverride() { try { wx.removeStorageSync("weeklyActivityDevtoolsApiOverride:v1"); } catch (e) {} return { cleared: true }; }, [], 5000).catch(() => {});
    }
    await closeSocket(ws);
    if (server) await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  writeJson("failure.json", {
    schemaVersion: "devtools_artist_max_richness_rendered.failure.v1",
    generatedAt: new Date().toISOString(), artifactDir, wsEndpoint, runtimeContext, lastFailureContext, steps,
    error: error && error.stack ? error.stack : String(error),
    safety: { miniProgramUploadExecuted: false, cloudRunDeployExecuted: false, previewQrGenerated: false, reviewSubmitted: false, publicReleaseExecuted: false, productionDbWriteExecuted: false },
  });
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
