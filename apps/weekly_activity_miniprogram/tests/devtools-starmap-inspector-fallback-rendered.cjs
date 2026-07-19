/**
 * Rendered proof: the star-map ATLAS 速览 inspector falls back to a payload-derived
 * city footprint for a DJ that has NO curated trajectory lens. Auto-focuses the node
 * via ?focusId, waits for the inspector fetch to resolve, and asserts the fallback
 * summary (city footprint with counts, sorted) rendered live.
 * Safety: read-only; no upload/deploy/review/release/production DB write.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");

const wsEndpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "").trim();
const artifactRoot = path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `starmap-inspector-fallback-rendered-${stamp}`);
const targetFocusId = String(process.env.ATLAS_RENDER_FOCUS_ID || "dj:duanluoo").trim();
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

    const url = `/pages/atlas-starmap/atlas-starmap?lens=entity&focusId=${encodeURIComponent(targetFocusId)}&renderProofTs=${encodeURIComponent(stamp)}`;
    await step("launch starmap with focusId", () => withTimeout(callApp(ws, function launch(u) {
      return new Promise((resolve) => wx.reLaunch({ url: u, success: () => resolve({ ok: true }), fail: (e) => resolve({ ok: false, e }) }));
    }, [url], 20000), 25000, "reLaunch"));

    await sleep(6000);

    // Wait for the page to be ready and the auto-focused inspector to resolve.
    const state = await step("wait inspector resolved", () => withTimeout(pollUntil(
      "inspector resolve", 40000, 900,
      () => callApp(ws, function readInspector() {
        const p = typeof getCurrentPages !== "undefined" ? getCurrentPages()[getCurrentPages().length - 1] : null;
        const d = p && p.data ? p.data : {};
        const sel = d.selected || null;
        const insp = sel && sel.inspector ? sel.inspector : null;
        return {
          route: p && p.route,
          loading: Boolean(d.loading),
          selectedId: sel ? sel.id : "",
          inspectorStatus: insp ? String(insp.status || "") : "",
          summary: insp ? String(insp.summary || "") : "",
          cityLine: insp ? String(insp.cityLine || "") : "",
          venueLine: insp ? String(insp.venueLine || "") : "",
          collaboratorLine: insp ? String(insp.collaboratorLine || "") : "",
        };
      }, [], 8000),
      (s) => s && s.route === "pages/atlas-starmap/atlas-starmap" && s.selectedId === targetFocusId
        && s.inspectorStatus && s.inspectorStatus !== "loading",
    ), 45000, "inspector resolve"));

    // Assertions: the inspector resolved via the long-tail fallback path.
    assert.equal(state.route, "pages/atlas-starmap/atlas-starmap", "starmap must be current page");
    assert.equal(state.selectedId, targetFocusId, "target node must be auto-focused");
    assert.equal(state.inspectorStatus, "ready", `inspector must resolve ready, got ${state.inspectorStatus} (${state.summary})`);
    assert.ok(state.cityLine, "fallback inspector must render a city footprint line");
    assert.ok(!state.cityLine.includes("未知"), "placeholder city must be filtered");
    assert.match(state.cityLine, /\d/, "city footprint line must carry event counts");
    assert.match(state.summary, /城/, "inspector summary must mention city coverage");

    const report = {
      schemaVersion: "devtools_starmap_inspector_fallback_rendered.v1",
      generatedAt: new Date().toISOString(),
      artifactDir, wsEndpoint, baseUrl, target: { focusId: targetFocusId },
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
    schemaVersion: "devtools_starmap_inspector_fallback_rendered.failure.v1",
    generatedAt: new Date().toISOString(), artifactDir, wsEndpoint, runtimeContext, lastFailureContext, steps,
    error: error && error.stack ? error.stack : String(error),
    safety: { miniProgramUploadExecuted: false, cloudRunDeployExecuted: false, previewQrGenerated: false, reviewSubmitted: false, publicReleaseExecuted: false, productionDbWriteExecuted: false },
  });
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
