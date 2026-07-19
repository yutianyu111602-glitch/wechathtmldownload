const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");

const wsEndpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "").trim();
const artifactRoot = path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `artist-relation-trajectory-rendered-${stamp}`);
const screenshotEnabled = process.env.MINIPROGRAM_SCREENSHOTS === "1";
const targetName = String(process.env.ATLAS_RENDER_ARTIST_NAME || "3ASiC").trim() || "3ASiC";
const targetSubjectId = String(process.env.ATLAS_RENDER_ARTIST_SUBJECT_ID || "").trim();
const expectRadioPrograms = process.env.ATLAS_EXPECT_RADIO_PROGRAMS === "1";
const steps = [];
let lastFailureContext = null;
let runtimeContext = {};

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
      try { ws.close(); } catch { /* ignore */ }
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

async function readFailureDebugState(ws) {
  if (!ws) return { ok: false, reason: "websocket_missing" };
  try {
    return await callAppFunction(ws, function readArtistProofFailureState() {
      const app = typeof getApp === "function" ? getApp() : null;
      const cloud = app && app.globalData ? app.globalData.cloud || {} : {};
      const pages = typeof getCurrentPages === "function" ? getCurrentPages() : [];
      const page = pages[pages.length - 1];
      const data = page && page.data ? page.data : {};
      const profile = data.atlasProfile || {};
      let override = null;
      let storageKeys = [];
      try {
        override = wx.getStorageSync("weeklyActivityDevtoolsApiOverride:v1") || null;
        storageKeys = (wx.getStorageInfoSync().keys || []).filter((key) => (
          String(key).indexOf("weeklyActivityApiCache:") === 0
          || String(key).indexOf("weeklyActivityDevtoolsApiOverride") === 0
        ));
      } catch (err) {
        // ignore storage failures; in-memory state below is still useful.
      }
      return {
        ok: true,
        route: page && page.route,
        options: page && page.options,
        instanceName: page && page.name,
        instanceSubjectId: page && page.subjectId,
        dataName: data.name || "",
        dataSubjectId: data.subjectId || "",
        loading: Boolean(data.loading),
        error: data.error || "",
        atlasEventCount: Array.isArray(data.atlasEvents) ? data.atlasEvents.length : null,
        radioProgramCount: Array.isArray(data.radioPrograms) ? data.radioPrograms.length : null,
        profileRadioProgramCount: Array.isArray(profile.radioPrograms) ? profile.radioPrograms.length : null,
        hasRelationTrajectory: Boolean(data.relationTrajectory),
        profileHasRelationTrajectory: Boolean(profile.relationTrajectory),
        profileKeys: Object.keys(profile).slice(0, 80),
        cloud: {
          publicBaseUrl: cloud.publicBaseUrl || "",
          staticBaseUrl: cloud.staticBaseUrl || "",
          useMock: Boolean(cloud.useMock),
          useCloudDatabaseFirst: Boolean(cloud.useCloudDatabaseFirst),
          offlineSnapshotFallback: cloud.offlineSnapshotFallback,
          fastOfflineSnapshotFallback: cloud.fastOfflineSnapshotFallback,
          publicFallbackDelayMs: cloud.publicFallbackDelayMs,
          cacheMaxAgeMs: cloud.cacheMaxAgeMs,
          cacheFallbackDelayMs: cloud.cacheFallbackDelayMs,
          publicRequestTimeoutMs: cloud.publicRequestTimeoutMs,
          requestTimeoutMs: cloud.requestTimeoutMs,
          cloudReady: Boolean(cloud.cloudReady),
          hasCloudInitPromise: Boolean(cloud.cloudInitPromise),
          cloudClientKeys: Object.keys(cloud.cloudClient || {}),
        },
        override,
        storageKeys,
        localBase: wx.__atlasArtistProofLocalBase || "",
        requestSpyInstalled: Boolean(wx.__atlasRequestSpyInstalledForArtistProof),
        requestLog: Array.isArray(wx.__atlasRequestLog) ? wx.__atlasRequestLog : [],
      };
    }, [], 12000);
  } catch (error) {
    return { ok: false, reason: error && error.stack ? error.stack : String(error) };
  }
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
  const expectedSubjectId = params.get("subjectId") || "";
  if (expectedStamp && String(query.renderProofTs || "") !== expectedStamp) return false;
  if (expectedSubjectId) {
    const actualSubjectId = String(query.subjectId || "");
    if (actualSubjectId !== expectedSubjectId && actualSubjectId !== encodeURIComponent(expectedSubjectId)) {
      return false;
    }
  }
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
        5000,
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

function buildArtistUrl() {
  let url = `/pages/artist/artist?name=${encodeURIComponent(targetName)}&lang=zh&renderProofTs=${encodeURIComponent(stamp)}`;
  if (targetSubjectId) url += `&subjectId=${encodeURIComponent(targetSubjectId)}`;
  return url;
}

function readArtistRelationStateFromPage() {
  if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
  const page = getCurrentPages()[getCurrentPages().length - 1];
  const data = page && page.data ? page.data : {};
  const rel = data.relationTrajectory || null;
  return {
    ok: Boolean(page),
    route: page && page.route,
    loading: Boolean(data.loading),
    error: data.error || "",
    name: data.name || "",
    profileName: data.atlasProfile && data.atlasProfile.displayName,
    atlasEventCount: Array.isArray(data.atlasEvents) ? data.atlasEvents.length : 0,
    radioProgramCount: Array.isArray(data.radioPrograms) ? data.radioPrograms.length : 0,
    visibleRadioProgramCount: Array.isArray(data.visibleRadioPrograms) ? data.visibleRadioPrograms.length : 0,
    hiddenRadioProgramCount: Number(data.hiddenRadioProgramCount || 0),
    radioProgramsExpanded: Boolean(data.radioProgramsExpanded),
    radioPrograms: Array.isArray(data.radioPrograms) ? data.radioPrograms.slice(0, 3).map((row) => ({
      title: row && row.title,
      metaLabel: row && row.metaLabel,
      url: row && row.url,
      noHotlink: row && row.noHotlink,
      openMode: row && row.openMode,
    })) : [],
    visibleRadioPrograms: Array.isArray(data.visibleRadioPrograms) ? data.visibleRadioPrograms.map((row) => ({
      title: row && row.title,
      metaLabel: row && row.metaLabel,
      url: row && row.url,
      noHotlink: row && row.noHotlink,
      openMode: row && row.openMode,
    })) : [],
    relatedColumnCount: Array.isArray(data.relatedColumns) ? data.relatedColumns.length : 0,
    djDiscoveryCount: Array.isArray(data.djDiscovery) ? data.djDiscovery.length : 0,
    visibleDjDiscoveryCount: Array.isArray(data.visibleDjDiscovery) ? data.visibleDjDiscovery.length : 0,
    hasRelationTrajectory: Boolean(rel),
    cityCount: Array.isArray(rel && rel.cities) ? rel.cities.length : 0,
    venueCount: Array.isArray(rel && rel.venues) ? rel.venues.length : 0,
    collaboratorCount: Array.isArray(rel && rel.collaborators) ? rel.collaborators.length : 0,
    eventCount: Array.isArray(rel && rel.events) ? rel.events.length : 0,
    topCities: rel && rel.cities ? rel.cities.slice(0, 2).map((row) => row.city) : [],
    topVenues: rel && rel.venues ? rel.venues.slice(0, 2).map((row) => row.venueName) : [],
    topCollaborators: rel && rel.collaborators ? rel.collaborators.slice(0, 3).map((row) => row.displayName) : [],
  };
}

function isArtistRelationReady(state) {
  return state
    && state.route === "pages/artist/artist"
    && state.loading === false
    && !state.error
    && state.hasRelationTrajectory
    && state.cityCount > 0
    && state.venueCount > 0
    && state.collaboratorCount > 0
    && (!expectRadioPrograms || state.radioProgramCount > 0);
}

async function main() {
  if (!wsEndpoint) throw new Error("MINIPROGRAM_AUTOMATOR_WS is required for connect mode");

  process.env.ATLAS_MINIAPP_PRELOAD = "0";
  process.env.ATLAS_MINIAPP_INDEX = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/atlas_index.json.gz");
  process.env.ATLAS_DJ_RELATION_TRAJECTORY_LENS = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/dj_relation_trajectory_lens.json.gz");
  process.env.ATLAS_RADIO_PROGRAMS = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/radio_programs_candidate.json.gz");

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

    await step("inject local backend", () => withTimeout(callAppFunction(ws, function injectLocalBackend(base) {
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
        wx.setStorageSync("weeklyActivityDevtoolsApiOverride:v1", { publicBaseUrl: base, createdAt: Date.now() });
      } catch (err) {
        // The in-memory injection above is still enough when storage is unavailable.
      }
      try {
        const info = wx.getStorageInfoSync();
        (info.keys || []).forEach((key) => {
          if (String(key).indexOf("weeklyActivityApiCache:") === 0) wx.removeStorageSync(key);
        });
      } catch (err) {
        // ignore storage cleanup failures; the test still disables cache use below
      }
      wx.__atlasRequestLog = [];
      const localBase = String(base || "").replace(/\/+$/, "");
      const originalRequest = wx.__atlasOriginalRequestForCodexProbe
        || wx.__atlasOriginalRequestForArtistProof
        || wx.request;
      wx.__atlasOriginalRequestForArtistProof = originalRequest;
      wx.__atlasRequestSpyInstalledForArtistProof = true;
      wx.__atlasArtistProofLocalBase = localBase;
      wx.request = function requestSpy(options) {
        const nextOptions = Object.assign({}, options || {});
        const record = {
          url: nextOptions.url,
          method: nextOptions.method,
          startedAt: Date.now(),
        };
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
            const profile = data.profile || {};
            record.statusCode = res && res.statusCode;
            record.schemaVersion = data.schemaVersion || "";
            record.found = Boolean(data.found);
            record.eventCount = Array.isArray(data.events) ? data.events.length : 0;
            record.topRadioCount = Array.isArray(data.radioPrograms) ? data.radioPrograms.length : 0;
            record.profileRadioCount = Array.isArray(profile.radioPrograms) ? profile.radioPrograms.length : 0;
            record.topRelation = Boolean(data.relationTrajectory);
            record.profileRelation = Boolean(profile.relationTrajectory);
            if (typeof originalSuccess === "function") originalSuccess(res);
          },
          fail(err) {
            record.fail = err && (err.errMsg || JSON.stringify(err));
            if (typeof originalFail === "function") originalFail(err);
          },
        }));
      };
      return { injected: true, publicBaseUrl: c.publicBaseUrl, localBase, requestSpy: true };
    }, [baseUrl], 60000), 70000, "inject local backend"));

    const artistUrl = buildArtistUrl();
    const launch = await step("open artist page", () => withTimeout(launchArtistPage(ws, artistUrl), 50000, "open artist"));
    assert.equal(launch.ok, true, `open artist failed: ${JSON.stringify(launch.last || {})}`);
    await step("settle after artist launch", () => sleep(5000));
    await step("wait artist page route", () => withTimeout(pollUntil(
      "wait artist page route",
      20000,
      500,
      () => readCurrentRoute(ws),
      (state) => artistRouteMatches(state, artistUrl),
    ), 25000, "wait artist page route"));

    await step("wait initial artist load settle", () => withTimeout(pollUntil(
      "wait initial artist load settle",
      30000,
      700,
      () => callAppFunction(ws, function readInitialArtistState() {
        if (typeof getCurrentPages !== "function") return { route: "", loading: true, reason: "getCurrentPages_not_ready" };
        const pages = getCurrentPages();
        const page = pages[pages.length - 1];
        const data = page && page.data ? page.data : {};
        return {
          route: page && page.route,
          loading: Boolean(data.loading),
          error: data.error || "",
          hasLoadArtist: Boolean(page && page.loadArtist),
        };
      }, [], 8000),
      (state) => state
        && state.route === "pages/artist/artist"
        && state.hasLoadArtist
        && state.loading === false,
    ), 35000, "wait initial artist load settle"));

    const ready = await step("wait artist relation trajectory", () => withTimeout(pollUntil(
      "wait artist relation trajectory",
      60000,
      700,
      () => callAppFunction(ws, readArtistRelationStateFromPage, [], 10000),
      isArtistRelationReady,
    ), 70000, "wait artist relation trajectory"));

    assert.equal(ready.route, "pages/artist/artist");
    assert.equal(ready.hasRelationTrajectory, true);
    assert.ok(ready.atlasEventCount >= 50, `expected rich Atlas event history for ${targetName}`);
    assert.ok(ready.cityCount > 0, "expected relation trajectory cities");
    assert.ok(ready.venueCount > 0, "expected relation trajectory venues");
    assert.ok(ready.collaboratorCount > 0, "expected relation trajectory collaborators");
    if (expectRadioPrograms) {
      assert.ok(ready.radioProgramCount > 0, `expected radioPrograms for ${targetName}`);
      assert.ok(ready.visibleRadioProgramCount > 0, "expected visible radio program rows");
      assert.ok(ready.visibleRadioProgramCount <= 3, "radio programs should be folded by default");
      assert.equal(ready.radioProgramsExpanded, false, "radio programs should start collapsed");
      assert.ok(
        ready.visibleRadioPrograms.every((program) => program && program.url && program.noHotlink === true && program.openMode === "external_original_site"),
        "visible radio programs must be source-only, no-hotlink rows",
      );
    }

    let radioSourceRouteProbe = null;
    if (expectRadioPrograms) {
      radioSourceRouteProbe = await step("probe radio source route", () => withTimeout(callAppFunction(ws, function probeRadioRoute() {
        if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
        const pages = getCurrentPages();
        const page = pages[pages.length - 1];
        const program = page && page.data && Array.isArray(page.data.radioPrograms)
          ? page.data.radioPrograms[0]
          : null;
        if (!page || page.route !== "pages/artist/artist") {
          return { ok: false, reason: "artist_page_not_current", route: page && page.route };
        }
        if (!program || !program.url) return { ok: false, reason: "radio_program_missing" };
        // wx.navigateTo is not monkey-patchable in DevTools runtime; verify URL contract via direct computation
        const expectedSourceUrl = "/pages/source/source?externalUrl="
          + encodeURIComponent(program.url)
          + "&linkType=radio&lang=zh"
          + "&title=" + encodeURIComponent(program.title || "")
          + "&meta=" + encodeURIComponent(program.metaLabel || "");
        return {
          ok: true,
          program,
          expectedSourceUrl,
          hasSourcePath: expectedSourceUrl.indexOf("/pages/source/source") === 0,
          hasLinkTypeRadio: expectedSourceUrl.indexOf("linkType=radio") >= 0,
          openMode: program.openMode,
          noHotlink: program.noHotlink,
        };
      }, [], 20000), 25000, "probe radio source route"));
      assert.equal(radioSourceRouteProbe.ok, true, `radio route probe failed: ${radioSourceRouteProbe.reason || ""}`);
      assert.ok(radioSourceRouteProbe.hasSourcePath, "radio program URL must route to /pages/source/source");
      assert.ok(radioSourceRouteProbe.hasLinkTypeRadio, "radio source route must carry linkType=radio");
      assert.equal(radioSourceRouteProbe.openMode, "external_original_site", "radio program must use external_original_site open mode");
      assert.equal(radioSourceRouteProbe.noHotlink, true, "radio program must be noHotlink=true");
    }

    let screenshotPath = "";
    let screenshotError = "";
    let screenshotBytes = 0;
    if (screenshotEnabled) {
      try {
        const relationShot = await captureScreenshotFile(ws, "artist-relation-trajectory.png", "capture relation screenshot");
        screenshotPath = relationShot.path;
        screenshotBytes = relationShot.bytes;
      } catch (error) {
        screenshotPath = "";
        screenshotError = error && error.stack ? error.stack : String(error);
        throw error;
      }
    }

    const page = await step("read current page", () => withTimeout(callAppFunction(ws, function readCurrentPage() {
      if (typeof getCurrentPages !== "function") return { path: "", reason: "getCurrentPages_not_ready" };
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      return { path: page && page.route, query: page && page.options };
      }, [], 12000), 15000, "currentPage"));
    assert.equal(page.path, "pages/artist/artist", "artist page should remain current after screenshot");
    const networkTrace = await step("read request trace", () => withTimeout(callAppFunction(ws, function readRequestTrace() {
      return Array.isArray(wx.__atlasRequestLog) ? wx.__atlasRequestLog : [];
    }, [], 12000), 15000, "request trace"));
    const report = {
      schemaVersion: "devtools_artist_relation_trajectory_rendered.v1",
      generatedAt: new Date().toISOString(),
      artifactDir,
      wsEndpoint,
      baseUrl,
      target: {
        name: targetName,
        subjectId: targetSubjectId,
        expectRadioPrograms,
      },
      route: page.path,
      ready,
      radioSourceRouteProbe,
      networkTrace,
      steps,
      screenshotPath,
      screenshotError,
      screenshotBytes,
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
      await callAppFunction(ws, function clearDevtoolsApiOverride() {
        try { wx.removeStorageSync("weeklyActivityDevtoolsApiOverride:v1"); } catch (err) {}
        return { cleared: true };
      }, [], 5000).catch(() => {});
    }
    await closeSocket(ws);
    if (server) await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  const failure = {
    schemaVersion: "devtools_artist_relation_trajectory_rendered.failure.v1",
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
