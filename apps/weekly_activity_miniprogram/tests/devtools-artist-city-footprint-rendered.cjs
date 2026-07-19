/**
 * Rendered proof: DJ detail page shows a computed city footprint for a multi-city
 * DJ that has NO curated trajectory lens (the long-tail geographic-reach feature).
 * Asserts: cityFootprint.length >= 2, each row has a city + metaLabel, no "未知"
 * placeholder, sorted by event count (first >= last).
 * Safety: read-only; no upload/deploy/review/release/production DB write.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");

const wsEndpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "").trim();
const artifactRoot = path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `artist-city-footprint-rendered-${stamp}`);
const targetName = String(process.env.ATLAS_RENDER_ARTIST_NAME || "0xygen").trim();
const targetSubjectId = String(process.env.ATLAS_RENDER_ARTIST_SUBJECT_ID || "dj:0xygen").trim();
const steps = [];
let lastFailureContext = {};
let runtimeContext = {};

fs.mkdirSync(artifactDir, { recursive: true });

function withTimeout(promise, ms, label) {
  let t;
  return Promise.race([
    promise,
    new Promise((_, reject) => { t = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms); }),
  ]).finally(() => clearTimeout(t));
}

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

async function listen(serverInstance) {
  await new Promise((resolve) => serverInstance.listen(0, "127.0.0.1", resolve));
  return `http://127.0.0.1:${serverInstance.address().port}`;
}

function writeJson(name, value) {
  fs.writeFileSync(path.join(artifactDir, name), JSON.stringify(value, null, 2), "utf8");
}

async function step(label, run) {
  const item = { label, startedAt: new Date().toISOString() };
  steps.push(item);
  try {
    const result = await run();
    item.finishedAt = new Date().toISOString();
    item.ok = true;
    return result;
  } catch (error) {
    item.finishedAt = new Date().toISOString();
    item.ok = false;
    item.error = error && error.stack ? error.stack : String(error);
    throw error;
  }
}

function connectDevtools(endpoint) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(endpoint);
    const t = setTimeout(() => { ws.close(); reject(new Error("DevTools connect timeout")); }, 30000);
    ws.on("open", () => { clearTimeout(t); resolve(ws); });
    ws.on("error", (e) => { clearTimeout(t); reject(e); });
  });
}

function sendProtocol(ws, method, params = {}, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const id = `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
    const t = setTimeout(() => { ws.off("message", onMsg); reject(new Error(`${method} timeout`)); }, timeoutMs);
    function onMsg(raw) {
      let m;
      try { m = JSON.parse(String(raw)); } catch { return; }
      if (m.id !== id) return;
      clearTimeout(t);
      ws.off("message", onMsg);
      if (m.error) reject(new Error(`${method} failed: ${JSON.stringify(m.error)}`));
      else resolve(m.result || {});
    }
    ws.on("message", onMsg);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

function callApp(ws, fn, args = [], timeoutMs = 30000) {
  return sendProtocol(ws, "App.callFunction", { functionDeclaration: fn.toString(), args }, timeoutMs)
    .then((r) => r.result);
}

async function pollUntil(label, timeoutMs, intervalMs, read, done) {
  const start = Date.now();
  let last;
  while (Date.now() - start <= timeoutMs) {
    try { last = await read(); } catch (e) { last = { ok: false }; }
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
  if (!wsEndpoint) throw new Error("MINIPROGRAM_AUTOMATOR_WS required");

  process.env.ATLAS_MINIAPP_PRELOAD = "0";
  process.env.ATLAS_MINIAPP_INDEX = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/atlas_index.json.gz");
  process.env.ATLAS_DJ_EXTERNAL_LINKS = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/dj_external_links_accepted_candidate.json.gz");
  process.env.ATLAS_RADIO_PROGRAMS = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/radio_programs_candidate.json.gz");
  process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/dj_relation_trajectory_lens.json.gz");
  process.env.ATLAS_NEIGHBORHOOD_BUNDLE = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/atlas_neighborhood.json.gz");

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

    ws = await step("connect DevTools", () => withTimeout(connectDevtools(wsEndpoint), 40000, "connect"));

    await step("inject local backend", () => withTimeout(callApp(ws, function inject(base) {
      const c = getApp().globalData.cloud;
      c.useMock = false;
      c.publicBaseUrl = base;
      c.staticBaseUrl = "";
      c.useCloudDatabaseFirst = false;
      c.offlineSnapshotFallback = false;
      c.fastOfflineSnapshotFallback = false;
      c.publicFallbackDelayMs = 0;
      c.cacheMaxAgeMs = 0;
      c.cacheFallbackDelayMs = 60000;
      c.publicRequestTimeoutMs = 20000;
      c.requestTimeoutMs = 20000;
      c.cloudClient = {
        callContainer: () => Promise.reject({ error: { code: "LOCAL_ONLY" } }),
        callFunction: () => Promise.reject({ error: { code: "LOCAL_ONLY" } }),
      };
      c.cloudReady = true;
      c.cloudInitPromise = null;
      try { wx.setStorageSync("weeklyActivityDevtoolsApiOverride:v1", { publicBaseUrl: base, createdAt: Date.now() }); } catch (e) {}
      try {
        const info = wx.getStorageInfoSync();
        (info.keys || []).forEach((k) => { if (String(k).indexOf("weeklyActivityApiCache:") === 0) wx.removeStorageSync(k); });
      } catch (e) {}
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

    const state = await step("read city footprint state", () => withTimeout(callApp(ws, function readFootprint() {
      const p = getCurrentPages()[getCurrentPages().length - 1];
      const d = p && p.data ? p.data : {};
      const fp = Array.isArray(d.cityFootprint) ? d.cityFootprint : [];
      return {
        route: p && p.route,
        loading: Boolean(d.loading),
        hasTrajectory: Boolean(d.relationTrajectory),
        cityFootprintCount: fp.length,
        cities: fp.map((c) => c && c.city),
        eventCounts: fp.map((c) => Number(c && c.eventCount)),
        metaLabels: fp.map((c) => c && c.metaLabel),
      };
    }, [], 15000), 20000, "read footprint"));

    // Assertions
    assert.equal(state.route, "pages/artist/artist", "artist page must be current");
    assert.equal(state.loading, false, "page must not be loading");
    assert.equal(state.hasTrajectory, false, "target must NOT have a curated trajectory (footprint is the long-tail feature)");
    assert.ok(state.cityFootprintCount >= 2, `expected cityFootprint >= 2 for ${targetName}, got ${state.cityFootprintCount}`);
    assert.ok(state.cities.every((c) => c && c.length), "every footprint row must have a city name");
    assert.ok(!state.cities.includes("未知"), "placeholder city 未知 must be filtered out");
    assert.ok(state.metaLabels.every((m) => m && m.length), "every footprint row must have a meta label");
    // Sorted by event count descending.
    for (let i = 1; i < state.eventCounts.length; i += 1) {
      assert.ok(state.eventCounts[i - 1] >= state.eventCounts[i], "footprint must be sorted by event count desc");
    }

    const report = {
      schemaVersion: "devtools_artist_city_footprint_rendered.v1",
      generatedAt: new Date().toISOString(),
      artifactDir,
      wsEndpoint,
      baseUrl,
      target: { name: targetName, subjectId: targetSubjectId },
      state,
      steps,
      safety: {
        miniProgramUploadExecuted: false,
        cloudRunDeployExecuted: false,
        previewQrGenerated: false,
        reviewSubmitted: false,
        publicReleaseExecuted: false,
        productionDbWriteExecuted: false,
      },
    };
    writeJson("report.json", report);
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    lastFailureContext = { debugState: "failed", error: error && error.message };
    throw error;
  } finally {
    if (ws) {
      await callApp(ws, function clearOverride() {
        try { wx.removeStorageSync("weeklyActivityDevtoolsApiOverride:v1"); } catch (e) {}
        return { cleared: true };
      }, [], 5000).catch(() => {});
    }
    await closeSocket(ws);
    if (server) await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  const failure = {
    schemaVersion: "devtools_artist_city_footprint_rendered.failure.v1",
    generatedAt: new Date().toISOString(),
    artifactDir,
    wsEndpoint,
    runtimeContext,
    lastFailureContext,
    steps,
    error: error && error.stack ? error.stack : String(error),
    safety: {
      miniProgramUploadExecuted: false,
      cloudRunDeployExecuted: false,
      previewQrGenerated: false,
      reviewSubmitted: false,
      publicReleaseExecuted: false,
      productionDbWriteExecuted: false,
    },
  };
  writeJson("failure.json", failure);
  console.error(JSON.stringify(failure, null, 2));
  process.exit(1);
});
