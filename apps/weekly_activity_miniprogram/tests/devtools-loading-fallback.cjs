const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { effectiveFeedItems } = require("./effective-feed-items.cjs");
const { readPageDataWithFallback } = require("./devtools-page-data.cjs");
const { startStaticPackageServer } = require("./devtools-static-package.cjs");

let automator;
try {
  automator = require("miniprogram-automator");
} catch (error) {
  console.error("[devtools-loading-fallback] miniprogram-automator is required.");
  process.exit(2);
}

const explicitWsEndpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "").trim();
const wsEndpoint = explicitWsEndpoint;
const explicitLaunchMode = process.env.MINIPROGRAM_AUTOMATOR_LAUNCH === "1";
const explicitConnectMode = Boolean(wsEndpoint);
const launchMode = explicitLaunchMode || !explicitConnectMode;
const noCloseDevTools = explicitConnectMode || process.env.MINIPROGRAM_AUTOMATOR_NO_CLOSE === "1";
const projectPath = process.env.MINIPROGRAM_PROJECT_PATH || path.resolve(__dirname, "..");
const cliPath = process.env.MINIPROGRAM_DEVTOOLS_CLI || "C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat";
const launchPort = Number(process.env.MINIPROGRAM_AUTOMATOR_PORT || "9430");
const idePort = Number(process.env.MINIPROGRAM_DEVTOOLS_IDE_PORT || "9430");
const automationHint = [
  "Default mode uses miniprogram-automator launch so the tool can parse the dynamic DevTools socket.",
  `Launch directly with: MINIPROGRAM_AUTOMATOR_LAUNCH=1 MINIPROGRAM_AUTOMATOR_PORT=${launchPort} MINIPROGRAM_DEVTOOLS_IDE_PORT=${idePort} node tests/devtools-loading-fallback.cjs`,
  "Only set MINIPROGRAM_AUTOMATOR_WS when a compatible bridge has produced a verified dynamic websocket endpoint.",
].join("\n");
const artifactRoot = process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT
  ? path.resolve(process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT)
  : path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `devtools-loading-fallback-${stamp}`);
const staticPackageDir = String(process.env.MINIPROGRAM_STATIC_PACKAGE_DIR || "").trim();
const MAX_PAGE_FALLBACK_MS = Number(process.env.MINIPROGRAM_MAX_PAGE_FALLBACK_MS || "4500");
// App.evaluate/currentPage protocol round-trips are DevTools-host latency, not
// first-screen product latency. Keep a generous harness bound and gate the UI
// itself with pageElapsedMs.
const MAX_WALL_FALLBACK_MS = Number(process.env.MINIPROGRAM_MAX_WALL_FALLBACK_MS || "15000");
fs.mkdirSync(artifactDir, { recursive: true });

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function openHome(miniProgram) {
  let page = await withTimeout(miniProgram.currentPage(), 12000, "currentPage before home");
  if (page.path === "pages/index/index") return page;
  try {
    await withTimeout(miniProgram.reLaunch("/pages/index/index"), 20000, "reLaunch home");
  } catch {
    await withTimeout(
      miniProgram.evaluate(() => new Promise((resolve) => {
        wx.reLaunch({ url: "/pages/index/index", complete: resolve });
      })),
      20000,
      "wx.reLaunch home"
    );
  }
  page = await withTimeout(miniProgram.currentPage(), 12000, "currentPage home");
  assert.equal(page.path, "pages/index/index");
  return page;
}

async function waitForIdle(miniProgram, page, label, timeoutMs) {
  const started = Date.now();
  let data = await readPageDataWithFallback(miniProgram, page, { label });
  while (data && data.loading && Date.now() - started < timeoutMs) {
    await page.waitFor(120);
    data = await readPageDataWithFallback(miniProgram, page, { label });
  }
  assert.equal(data.loading, false, `${label}: still loading after ${timeoutMs}ms`);
  assert.equal(data.error || "", "", `${label}: unexpected error ${data.error || ""}`);
  return data;
}

async function run() {
  const staticServer = staticPackageDir ? await startStaticPackageServer(staticPackageDir) : null;
  const staticBaseUrl = staticServer ? staticServer.baseUrl : "";
  const report = {
    wsEndpoint,
    launchMode,
    launchPort,
    idePort,
    artifactDir,
    staticPackageDir,
    staticBaseUrl,
    steps: [],
    exceptions: [],
    consoleCount: 0,
  };
  const miniProgram = launchMode
    ? await withTimeout(automator.launch({
      projectPath,
      cliPath,
      port: launchPort,
      idePort,
      trustProject: true,
      timeout: 90000,
    }), 110000, "automator launch")
    : await withTimeout(automator.connect({ wsEndpoint }), 30000, "automator connect");

  const exceptions = [];
  const consoleMessages = [];
  miniProgram.on("exception", (payload) => exceptions.push(payload));
  miniProgram.on("console", (payload) => consoleMessages.push(payload));

  try {
    const page = await openHome(miniProgram);
    if (staticBaseUrl) {
      await withTimeout(miniProgram.evaluate((injectedStaticBaseUrl) => {
        wx.clearStorageSync();
        const app = getApp();
        const cloud = app.globalData.cloud;
        const staticOnlyClient = {
          callContainer() {
            return Promise.reject({ error: { code: "DEVTOOLS_STATIC_PACKAGE_ONLY" } });
          },
          callFunction() {
            return Promise.reject({ error: { code: "DEVTOOLS_STATIC_PACKAGE_ONLY" } });
          },
        };
        cloud.useMock = false;
        cloud.devtoolsMockFallback = false;
        cloud.useCloudDatabaseFirst = false;
        cloud.publicBaseUrl = "";
        cloud.staticBaseUrl = injectedStaticBaseUrl;
        cloud.offlineSnapshotFallback = false;
        cloud.fastOfflineSnapshotFallback = false;
        cloud.publicFallbackDelayMs = 0;
        cloud.cloudClient = staticOnlyClient;
        cloud.cloudInitPromise = null;
        cloud.cloudReady = true;
        const pages = getCurrentPages();
        const current = pages[pages.length - 1];
        current.isLoadingRequest = false;
        current.pendingLoadOptions = null;
        // The static-only client already guarantees the exact candidate input.
        // Do not set skipCache here: that flag intentionally forbids writing
        // the last-good generation that the outage phase is meant to prove.
        return current.loadData();
      }, staticBaseUrl), 30000, "warm candidate package cache");
    }
    await waitForIdle(miniProgram, page, "warm home", 16000);
    await page.waitFor(1200);

    await withTimeout(miniProgram.evaluate(() => {
      function apiCacheKeys() {
        const keys = wx.getStorageInfoSync().keys || [];
        return keys.filter((key) => {
          const text = String(key || "");
          return text.indexOf("weeklyActivityApiCache:") === 0
            || text.indexOf("weeklyActivityCurrentActive:v2:") === 0
            || text.indexOf("weeklyActivityCurrentPage:v2:") === 0
            || text === "weeklyActivityCurrentActiveIndex:v2"
            || text === "weeklyActivityCurrentGeneration:v1";
        });
      }
      const preservedApiCache = apiCacheKeys().map((key) => [key, wx.getStorageSync(key)]);
      wx.clearStorageSync();
      preservedApiCache.forEach(([key, value]) => wx.setStorageSync(key, value));
      const app = getApp();
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      if (page && typeof page.clearBackgroundRefreshTimer === "function") {
        page.clearBackgroundRefreshTimer();
        page.backgroundRefreshAttempts = 0;
        page.lastBackgroundRefreshAt = 0;
      }
      app.globalData.__loadingFallbackProbe = {
        requestCount: 0,
        abortCount: 0,
        originalRequest: wx.request,
        originalCloud: { ...app.globalData.cloud },
        preservedCacheKeys: preservedApiCache.map(([key]) => key),
      };
      wx.request = function mockHangingRequest() {
        app.globalData.__loadingFallbackProbe.requestCount += 1;
        return {
          abort() {
            app.globalData.__loadingFallbackProbe.abortCount += 1;
          },
        };
      };
      const cloud = app.globalData.cloud;
      cloud.useMock = false;
      cloud.publicBaseUrl = "https://weekly-api.example.test";
      cloud.staticBaseUrl = "";
      cloud.cloudInitTimeoutMs = 50;
      cloud.cloudCallTimeoutMs = 2000;
      cloud.publicFallbackDelayMs = 5;
      cloud.publicRequestTimeoutMs = 5;
      cloud.cacheFallbackDelayMs = 5;
      // This scenario proves persisted last-good recovery. A zero max age is
      // the explicit product switch that disables cache fallback, so keep the
      // freshly warmed generation eligible for this outage probe.
      cloud.cacheMaxAgeMs = 60 * 60 * 1000;
      cloud.requestTimeoutMs = 50;
      cloud.offlineSnapshotFallback = true;
      cloud.fastOfflineSnapshotFallback = false;
      cloud.cloudClient = {
        callContainer() {
          return new Promise(() => {});
        },
      };
      cloud.cloudInitPromise = Promise.resolve(cloud.cloudClient);
    }), 10000, "install hanging route probe");

    const startedAt = Date.now();
    const loadTiming = await withTimeout(miniProgram.evaluate(() => {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      const started = Date.now();
      return page.loadData().then(() => ({ pageElapsedMs: Date.now() - started }));
    }), 10000, "trigger first-load fallback");
    const data = await waitForIdle(miniProgram, page, "first-load blackhole fallback", 3000);
    const wallElapsedMs = Date.now() - startedAt;
    const pageElapsedMs = Number(loadTiming && loadTiming.pageElapsedMs);
    const probe = JSON.parse(await miniProgram.evaluate(() => {
      const keys = wx.getStorageInfoSync().keys || [];
      const app = getApp();
      return JSON.stringify({
        requestCount: app.globalData.__loadingFallbackProbe.requestCount,
        abortCount: app.globalData.__loadingFallbackProbe.abortCount,
        preservedCacheKeys: app.globalData.__loadingFallbackProbe.preservedCacheKeys,
        apiCacheKeys: keys.filter((key) => {
          const text = String(key || "");
          return text.indexOf("weeklyActivityApiCache:") === 0
            || text.indexOf("weeklyActivityCurrentActive:v2:") === 0
            || text.indexOf("weeklyActivityCurrentPage:v2:") === 0
            || text === "weeklyActivityCurrentActiveIndex:v2"
            || text === "weeklyActivityCurrentGeneration:v1";
        }),
      });
    }));

    const items = effectiveFeedItems(data);
    report.steps.push({
      name: "first-load blackhole renders without hanging",
      pageElapsedMs,
      wallElapsedMs,
      maxPageFallbackMs: MAX_PAGE_FALLBACK_MS,
      maxWallFallbackMs: MAX_WALL_FALLBACK_MS,
      itemCount: items.length,
      requestCount: probe.requestCount,
      abortCount: probe.abortCount,
      preservedCacheKeyCount: probe.preservedCacheKeys.length,
      loadingProgress: data.loadingProgress,
      cacheNotice: data.cacheNotice,
    });
    report.consoleCount = consoleMessages.length;
    report.exceptions = exceptions;
    fs.writeFileSync(path.join(artifactDir, "report.json"), JSON.stringify(report, null, 2), "utf8");
    console.log(JSON.stringify(report, null, 2));

    assert.ok(pageElapsedMs < MAX_PAGE_FALLBACK_MS, `page fallback should finish under ${MAX_PAGE_FALLBACK_MS}ms, got ${pageElapsedMs}ms`);
    assert.ok(wallElapsedMs < MAX_WALL_FALLBACK_MS, `automated fallback check should finish under ${MAX_WALL_FALLBACK_MS}ms, got ${wallElapsedMs}ms`);
    assert.ok(items.length > 0, "persisted last-success cache should render events");
    assert.equal(data.loadingProgress, 100, "loading progress should finish at 100");
    assert.equal(data.cacheNotice, data.t.loadingCachedNotice, "UI should disclose persisted last-success cache");
    assert.ok(probe.preservedCacheKeys.length > 0, "warm load should establish persisted API cache evidence");
    assert.ok(
      probe.abortCount <= probe.requestCount,
      `abort count cannot exceed request count, got ${probe.abortCount}/${probe.requestCount}`,
    );
    assert.ok(probe.apiCacheKeys.length > 0, "last-success API cache should remain available during an outage");
    assert.deepEqual(exceptions, [], "DevTools reported runtime exceptions");
  } finally {
    try {
      await withTimeout(miniProgram.evaluate(() => {
        const app = getApp();
        const probe = app.globalData.__loadingFallbackProbe;
        if (probe && probe.originalRequest) wx.request = probe.originalRequest;
        if (probe && probe.originalCloud) {
          const cloud = app.globalData.cloud;
          Object.keys(cloud).forEach((key) => {
            if (!Object.prototype.hasOwnProperty.call(probe.originalCloud, key)) delete cloud[key];
          });
          Object.assign(cloud, probe.originalCloud);
        }
        delete app.globalData.__loadingFallbackProbe;
      }), 10000, "restore request");
    } catch {}
    try {
      if (noCloseDevTools) {
        miniProgram.disconnect();
      } else {
        await withTimeout(miniProgram.close(), 15000, "miniProgram.close");
      }
    } catch (error) {
      miniProgram.disconnect();
    }
    if (staticServer) await staticServer.close();
  }
}

run().then(() => {
  process.exit(0);
}).catch((error) => {
  const failure = {
    wsEndpoint,
    launchMode,
    launchPort,
    idePort,
    artifactDir,
    error: error && error.stack ? error.stack : String(error),
    hint: automationHint,
  };
  fs.writeFileSync(path.join(artifactDir, "failure.json"), JSON.stringify(failure, null, 2), "utf8");
  console.error(JSON.stringify(failure, null, 2));
  process.exit(1);
});
