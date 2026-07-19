const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");

const wsEndpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "").trim();
const artifactRoot = path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `artist-related-column-rendered-${stamp}`);
const screenshotEnabled = process.env.MINIPROGRAM_SCREENSHOTS === "1";
const targetName = String(process.env.ATLAS_RELATED_COLUMN_ARTIST_NAME || "444theGod").trim() || "444theGod";
const targetSubjectId = String(process.env.ATLAS_RELATED_COLUMN_ARTIST_SUBJECT_ID || "").trim();
const steps = [];
let runtimeContext = {};
let lastFailureContext = null;

fs.mkdirSync(artifactDir, { recursive: true });

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function listen(serverInstance) {
  await new Promise((resolve) => serverInstance.listen(0, "127.0.0.1", resolve));
  const address = serverInstance.address();
  return `http://127.0.0.1:${address.port}`;
}

function writeJson(name, value) {
  fs.writeFileSync(path.join(artifactDir, name), JSON.stringify(value, null, 2), "utf8");
}

function serializableStepResult(value) {
  if (value === undefined) return undefined;
  if (value && value.constructor && value.constructor.name === "WebSocket") {
    return { type: "WebSocket", readyState: value.readyState };
  }
  try {
    JSON.stringify(value);
    return value;
  } catch {
    return { type: typeof value, summary: String(value && value.constructor && value.constructor.name || value) };
  }
}

async function step(label, run) {
  const item = { label, startedAt: new Date().toISOString() };
  steps.push(item);
  try {
    const result = await run();
    item.finishedAt = new Date().toISOString();
    item.ok = true;
    item.result = serializableStepResult(result);
    return result;
  } catch (error) {
    item.finishedAt = new Date().toISOString();
    item.ok = false;
    item.error = error && error.stack ? error.stack : String(error);
    throw error;
  }
}

async function captureScreenshotFile(ws, filename, label) {
  const screenshotPath = path.join(artifactDir, filename);
  const capture = await step(label, async () => {
    let lastError = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        return await withTimeout(sendProtocol(ws, "App.captureScreenshot", {}, 30000), 40000, `${label} attempt ${attempt}`);
      } catch (error) {
        lastError = error;
        if (attempt < 3) await sleep(1200);
      }
    }
    throw lastError;
  });
  fs.writeFileSync(screenshotPath, capture.data || "", "base64");
  const screenshotBytes = fs.statSync(screenshotPath).size;
  assert.ok(screenshotBytes > 1024, `expected ${filename} artifact to be non-empty`);
  return { path: screenshotPath, bytes: screenshotBytes };
}

function connectDevtools(endpoint, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(endpoint);
    const timer = setTimeout(() => {
      try { ws.close(); } catch {}
      reject(new Error(`DevTools websocket open timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    ws.on("open", () => {
      clearTimeout(timer);
      resolve(ws);
    });
    ws.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

function sendProtocol(ws, method, params = {}, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const id = `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
    const timer = setTimeout(() => {
      ws.off("message", onMessage);
      reject(new Error(`${method} timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    function onMessage(raw) {
      let message;
      try {
        message = JSON.parse(String(raw));
      } catch {
        return;
      }
      if (message.id !== id) return;
      clearTimeout(timer);
      ws.off("message", onMessage);
      if (message.error) {
        reject(new Error(`${method} failed: ${JSON.stringify(message.error)}`));
        return;
      }
      resolve(message.result || {});
    }
    ws.on("message", onMessage);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function callAppFunction(ws, fn, args = [], timeoutMs = 30000) {
  const response = await sendProtocol(ws, "App.callFunction", {
    functionDeclaration: fn.toString(),
    args,
  }, timeoutMs);
  return response.result;
}

async function pollUntil(label, timeoutMs, intervalMs, read, done) {
  const started = Date.now();
  let last;
  while (Date.now() - started <= timeoutMs) {
    try {
      last = await read();
    } catch (error) {
      last = { ok: false, reason: error && error.message ? error.message : String(error) };
    }
    if (done(last)) return last;
    await sleep(intervalMs);
  }
  throw new Error(`${label} timed out after ${timeoutMs}ms; last=${JSON.stringify(last)}`);
}

function closeSocket(ws) {
  return new Promise((resolve) => {
    if (!ws || ws.readyState === WebSocket.CLOSED) {
      resolve();
      return;
    }
    ws.once("close", resolve);
    try { ws.close(); } catch { resolve(); }
    setTimeout(resolve, 1000);
  });
}

function buildArtistUrl() {
  let url = `/pages/artist/artist?name=${encodeURIComponent(targetName)}&lang=zh&renderProofTs=${encodeURIComponent(stamp)}`;
  if (targetSubjectId) url += `&subjectId=${encodeURIComponent(targetSubjectId)}`;
  return url;
}

async function readCurrentRoute(ws) {
  return callAppFunction(ws, function readRoute() {
    if (typeof getCurrentPages !== "function") return { path: "", reason: "getCurrentPages_not_ready" };
    const pages = getCurrentPages();
    const page = pages[pages.length - 1];
    return { path: page && page.route, query: page && page.options };
  }, [], 8000);
}

function artistRouteMatches(state, url) {
  if (!state || state.path !== "pages/artist/artist") return false;
  const query = state.query || {};
  const params = new URLSearchParams(String(url || "").split("?")[1] || "");
  const expectedStamp = params.get("renderProofTs") || "";
  const expectedName = params.get("name") || "";
  if (expectedStamp && String(query.renderProofTs || "") !== expectedStamp) return false;
  if (expectedName && decodeURIComponent(String(query.name || "")) !== expectedName) return false;
  return true;
}

async function launchArtistPage(ws, url) {
  let last = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const launch = await callAppFunction(ws, function launchArtistPageOnce(targetUrl) {
      return new Promise((resolve) => {
        wx.reLaunch({
          url: targetUrl,
          success: () => resolve({ ok: true }),
          fail: (err) => resolve({ ok: false, err }),
        });
      });
    }, [url], 20000);
    if (!launch || launch.ok !== true) {
      last = { attempt, launch };
      await sleep(500);
      continue;
    }
    try {
      const route = await pollUntil(
        `wait artist route after launch attempt ${attempt}`,
        6000,
        300,
        () => readCurrentRoute(ws),
        (state) => artistRouteMatches(state, url),
      );
      return { ok: true, attempts: attempt, route };
    } catch (error) {
      last = {
        attempt,
        launch,
        routeError: error && error.message ? error.message : String(error),
        route: await readCurrentRoute(ws).catch((routeReadError) => ({
          path: "",
          error: routeReadError && routeReadError.message ? routeReadError.message : String(routeReadError),
        })),
      };
      await sleep(500);
    }
  }
  return { ok: false, last };
}

function readArtistColumnStateFromPage() {
  if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
  const pages = getCurrentPages();
  const page = pages[pages.length - 1];
  const data = page && page.data ? page.data : {};
  const relatedColumns = Array.isArray(data.relatedColumns) ? data.relatedColumns : [];
  return {
    ok: Boolean(page),
    route: page && page.route,
    loading: Boolean(data.loading),
    error: data.error || "",
    name: data.name || "",
    profileName: data.atlasProfile && data.atlasProfile.displayName,
    atlasEventCount: Array.isArray(data.atlasEvents) ? data.atlasEvents.length : 0,
    relatedColumnCount: relatedColumns.length,
    relatedColumns: relatedColumns.slice(0, 5).map((row) => ({
      id: row && (row.columnId || row.id),
      title: row && row.title,
      summary: row && row.summary,
      metaLabel: row && row.metaLabel,
    })),
    hasOpenRelatedColumn: Boolean(page && page.openRelatedColumn),
  };
}

function readColumnHighlightStateFromPage(expectedHighlight) {
  if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
  const pages = getCurrentPages();
  const page = pages[pages.length - 1];
  const data = page && page.data ? page.data : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const filteredItems = Array.isArray(data.filteredItems) ? data.filteredItems : [];
  const highlighted = items.find((item) => item && item.id === expectedHighlight)
    || filteredItems.find((item) => item && item.id === expectedHighlight)
    || null;
  let storedHighlight = null;
  try {
    storedHighlight = wx.getStorageSync("weeklyActivityColumnHighlight:v1") || null;
  } catch (err) {
    storedHighlight = { error: err && (err.errMsg || err.message || String(err)) };
  }
  return {
    ok: Boolean(page),
    route: page && page.route,
    options: page && page.options,
    loading: Boolean(data.loading),
    loadFailed: Boolean(data.loadFailed),
    activeTag: data.activeTag || "",
    pendingHighlightId: data.pendingHighlightId || "",
    lastExpandedItemId: data.lastExpandedItemId || "",
    itemCount: items.length,
    filteredItemCount: filteredItems.length,
    highlighted: highlighted ? {
      id: highlighted.id,
      title: highlighted.title,
      expanded: Boolean(highlighted.expanded),
      evidenceExpanded: Boolean(highlighted.evidenceExpanded),
      bodyToggleLabel: highlighted.bodyToggleLabel,
      evidenceToggleLabel: highlighted.evidenceToggleLabel,
      paragraphCount: Array.isArray(highlighted.paragraphs) ? highlighted.paragraphs.length : 0,
      bodyLength: String(highlighted.body || "").length,
    } : null,
    storedHighlight,
  };
}

async function readFailureDebugState(ws) {
  if (!ws) return { ok: false, reason: "websocket_missing" };
  try {
    return await callAppFunction(ws, function readRelatedColumnFailureState() {
      const app = typeof getApp === "function" ? getApp() : null;
      const cloud = app && app.globalData ? app.globalData.cloud || {} : {};
      const pages = typeof getCurrentPages === "function" ? getCurrentPages() : [];
      const page = pages[pages.length - 1];
      const data = page && page.data ? page.data : {};
      return {
        ok: true,
        route: page && page.route,
        options: page && page.options,
        loading: Boolean(data.loading),
        error: data.error || "",
        relatedColumnCount: Array.isArray(data.relatedColumns) ? data.relatedColumns.length : null,
        currentHighlight: data.pendingHighlightId || data.lastExpandedItemId || "",
        cloud: {
          publicBaseUrl: cloud.publicBaseUrl || "",
          staticBaseUrl: cloud.staticBaseUrl || "",
          useMock: Boolean(cloud.useMock),
          publicRequestTimeoutMs: cloud.publicRequestTimeoutMs,
          requestTimeoutMs: cloud.requestTimeoutMs,
        },
        requestLog: Array.isArray(wx.__atlasRequestLog) ? wx.__atlasRequestLog : [],
      };
    }, [], 12000);
  } catch (error) {
    return { ok: false, reason: error && error.stack ? error.stack : String(error) };
  }
}

async function main() {
  if (!wsEndpoint) throw new Error("MINIPROGRAM_AUTOMATOR_WS is required for connect mode");

  process.env.ATLAS_MINIAPP_PRELOAD = "0";
  process.env.ATLAS_MINIAPP_INDEX = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/atlas_index.json.gz");
  process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/dj_relation_trajectory_lens.json.gz");
  process.env.ATLAS_RADIO_PROGRAMS = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/radio_programs_candidate.json.gz");
  process.env.ATLAS_REQUIRE_SESSION = "false";

  const { createServer } = await import("../../../services/weekly_activity_cloudrun/src/server.mjs");
  let server;
  let ws;
  try {
    server = createServer({
      store: {
        getCurrent: async () => ({ schemaVersion: "weekly.current.test.v1", items: [], page: { nextCursor: null } }),
      },
      stage7Store: {},
      llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      soundStore: {},
      interviewStore: {},
      env: { ...process.env, ATLAS_REQUIRE_SESSION: "false" },
    });
    const baseUrl = await listen(server);
    runtimeContext.baseUrl = baseUrl;
    ws = await step("connect DevTools websocket", () => withTimeout(connectDevtools(wsEndpoint), 40000, "DevTools websocket connect"));

    await step("inject local readonly backend", () => withTimeout(callAppFunction(ws, function injectLocalBackend(base) {
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
      try {
        wx.setStorageSync("weeklyActivityLang", "zh");
        wx.setStorageSync("weeklyActivityDevtoolsApiOverride:v1", { publicBaseUrl: base, createdAt: Date.now() });
      } catch (err) {}
      try {
        const info = wx.getStorageInfoSync();
        (info.keys || []).forEach((key) => {
          if (
            String(key).indexOf("weeklyActivityApiCache:") === 0
            || String(key) === "weeklyActivityColumnHighlight:v1"
          ) wx.removeStorageSync(key);
        });
      } catch (err) {}
      wx.__atlasRequestLog = [];
      const localBase = String(base || "").replace(/\/+$/, "");
      const originalRequest = wx.__atlasOriginalRequestForRelatedColumnProof || wx.request;
      wx.__atlasOriginalRequestForRelatedColumnProof = originalRequest;
      wx.request = function requestSpy(options) {
        const nextOptions = Object.assign({}, options || {});
        const record = { url: nextOptions.url, method: nextOptions.method, startedAt: Date.now() };
        const url = String(nextOptions.url || "");
        const marker = "/api/v1/weekly/";
        const markerIndex = url.indexOf(marker);
        if (localBase && markerIndex >= 0 && !url.startsWith(localBase)) {
          record.rewrittenFrom = url;
          nextOptions.url = `${localBase}${url.slice(markerIndex)}`;
          record.url = nextOptions.url;
        }
        wx.__atlasRequestLog.push(record);
        const originalSuccess = nextOptions.success;
        const originalFail = nextOptions.fail;
        return originalRequest.call(wx, Object.assign({}, nextOptions, {
          success(res) {
            const data = res && res.data ? res.data : {};
            record.statusCode = res && res.statusCode;
            record.schemaVersion = data.schemaVersion || "";
            record.found = Boolean(data.found);
            record.relatedColumnCount = Array.isArray(data.relatedColumns) ? data.relatedColumns.length : 0;
            record.columnItemCount = Array.isArray(data.items) ? data.items.length : 0;
            if (typeof originalSuccess === "function") originalSuccess(res);
          },
          fail(err) {
            record.fail = err && (err.errMsg || JSON.stringify(err));
            if (typeof originalFail === "function") originalFail(err);
          },
        }));
      };
      return { injected: true, publicBaseUrl: c.publicBaseUrl, requestSpy: true };
    }, [baseUrl], 60000), 70000, "inject local readonly backend"));

    const artistUrl = buildArtistUrl();
    const launch = await step("open artist page", () => withTimeout(launchArtistPage(ws, artistUrl), 50000, "open artist"));
    assert.equal(launch.ok, true, `open artist failed: ${JSON.stringify(launch.last || {})}`);

    const artistReady = await step("wait artist related columns", () => withTimeout(pollUntil(
      "wait artist related columns",
      60000,
      700,
      () => callAppFunction(ws, readArtistColumnStateFromPage, [], 10000),
      (state) => state
        && state.route === "pages/artist/artist"
        && state.loading === false
        && !state.error
        && state.hasOpenRelatedColumn
        && state.relatedColumnCount > 0,
    ), 70000, "wait artist related columns"));

    assert.equal(artistReady.route, "pages/artist/artist");
    assert.ok(artistReady.relatedColumnCount > 0, `expected related columns for ${targetName}`);
    const firstColumn = artistReady.relatedColumns[0] || {};
    assert.ok(firstColumn.id, "first related column must carry columnId/id");

    let artistScreenshot = null;
    if (screenshotEnabled) {
      await step("settle artist related column render", () => sleep(1200));
      artistScreenshot = await captureScreenshotFile(ws, "artist-related-column-entry.png", "capture artist related column entry screenshot");
    }

    const clickResult = await step("tap first related column", () => withTimeout(callAppFunction(ws, function tapFirstRelatedColumn() {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      const data = page && page.data ? page.data : {};
      const first = Array.isArray(data.relatedColumns) ? data.relatedColumns[0] : null;
      if (!page || page.route !== "pages/artist/artist") return { ok: false, reason: "artist_page_not_current", route: page && page.route };
      if (!first) return { ok: false, reason: "related_column_missing" };
      page.openRelatedColumn({ currentTarget: { dataset: { index: 0 } } });
      return {
        ok: true,
        first: {
          id: first.columnId || first.id,
          title: first.title,
          metaLabel: first.metaLabel,
        },
      };
    }, [], 20000), 25000, "tap first related column"));
    assert.equal(clickResult.ok, true, `related column click failed: ${clickResult.reason || ""}`);
    assert.equal(clickResult.first.id, firstColumn.id);

    const columnReady = await step("wait highlighted column page", () => withTimeout(pollUntil(
      "wait highlighted column page",
      60000,
      700,
      () => callAppFunction(ws, readColumnHighlightStateFromPage, [firstColumn.id], 10000),
      (state) => state
        && state.route === "pages/column/column"
        && state.loading === false
        && state.highlighted
        && state.highlighted.expanded === true
        && state.highlighted.evidenceExpanded === false
        && state.lastExpandedItemId === firstColumn.id,
    ), 70000, "wait highlighted column page"));

    assert.equal(columnReady.route, "pages/column/column");
    assert.equal(columnReady.loadFailed, false, "column page should use local readonly API, not local fallback");
    assert.equal(columnReady.activeTag, "all");
    assert.equal(columnReady.highlighted.id, firstColumn.id);
    assert.equal(columnReady.highlighted.expanded, true);
    assert.equal(columnReady.highlighted.evidenceExpanded, false);
    assert.match(String(columnReady.highlighted.bodyToggleLabel || ""), /收起正文|Collapse article/);

    let columnScreenshot = null;
    if (screenshotEnabled) {
      await step("settle highlighted column render", () => sleep(1200));
      columnScreenshot = await captureScreenshotFile(ws, "related-column-highlight.png", "capture highlighted column screenshot");
    }

    const networkTrace = await step("read request trace", () => withTimeout(callAppFunction(ws, function readRequestTrace() {
      return Array.isArray(wx.__atlasRequestLog) ? wx.__atlasRequestLog : [];
    }, [], 12000), 15000, "request trace"));

    const report = {
      schemaVersion: "devtools_artist_related_column_rendered.v1",
      generatedAt: new Date().toISOString(),
      artifactDir,
      wsEndpoint,
      baseUrl,
      target: {
        name: targetName,
        subjectId: targetSubjectId,
      },
      artistReady,
      firstColumn,
      clickResult,
      columnReady,
      networkTrace,
      steps,
      screenshots: {
        artist: artistScreenshot,
        column: columnScreenshot,
      },
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
    lastFailureContext = {
      ...runtimeContext,
      debugState: await readFailureDebugState(ws),
    };
    throw error;
  } finally {
    if (ws) {
      await callAppFunction(ws, function clearRelatedColumnProofState() {
        try { wx.removeStorageSync("weeklyActivityDevtoolsApiOverride:v1"); } catch (err) {}
        try { wx.removeStorageSync("weeklyActivityColumnHighlight:v1"); } catch (err) {}
        return { cleared: true };
      }, [], 5000).catch(() => {});
    }
    await closeSocket(ws);
    if (server) await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  const failure = {
    schemaVersion: "devtools_artist_related_column_rendered.failure.v1",
    generatedAt: new Date().toISOString(),
    artifactDir,
    wsEndpoint,
    runtimeContext,
    failureContext: lastFailureContext,
    safety: {
      miniProgramUploadExecuted: false,
      cloudRunDeployExecuted: false,
      previewQrGenerated: false,
      reviewSubmitted: false,
      publicReleaseExecuted: false,
      productionDbWriteExecuted: false,
    },
    steps,
    error: error && error.stack ? error.stack : String(error),
  };
  writeJson("failure.json", failure);
  console.error(JSON.stringify(failure, null, 2));
  process.exit(1);
});
