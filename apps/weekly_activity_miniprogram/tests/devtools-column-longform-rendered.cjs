const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");

const explicitWsEndpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "").trim();
const wsEndpoint = explicitWsEndpoint;
const explicitLaunchMode = process.env.MINIPROGRAM_AUTOMATOR_LAUNCH === "1";
const explicitConnectMode = Boolean(wsEndpoint);
const launchMode = explicitLaunchMode || !explicitConnectMode;
const projectPath = process.env.MINIPROGRAM_PROJECT_PATH || path.resolve(__dirname, "..");
const cliPath = process.env.MINIPROGRAM_DEVTOOLS_CLI || "C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat";
const launchPort = Number(process.env.MINIPROGRAM_AUTOMATOR_PORT || "9430");
const idePort = Number(process.env.MINIPROGRAM_DEVTOOLS_IDE_PORT || "9430");
const automationHint = [
  "Default mode uses miniprogram-automator launch so the tool can parse the dynamic DevTools socket.",
  `Launch directly with: MINIPROGRAM_AUTOMATOR_LAUNCH=1 MINIPROGRAM_AUTOMATOR_PORT=${launchPort} MINIPROGRAM_DEVTOOLS_IDE_PORT=${idePort} node tests/devtools-column-longform-rendered.cjs`,
  "Only set MINIPROGRAM_AUTOMATOR_WS when a compatible bridge has produced a verified dynamic websocket endpoint.",
].join("\n");
const remoteBaseUrl = String(
  process.env.MINIPROGRAM_COLUMN_REMOTE_BASE_URL
  || "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com",
).replace(/\/+$/, "");
const expectedCount = Number(process.env.MINIPROGRAM_COLUMN_EXPECTED_COUNT || "10");
const expectedMinBodyLen = Number(process.env.MINIPROGRAM_COLUMN_EXPECTED_MIN_BODY_LEN || "250");
const expectedMinParagraphs = Number(process.env.MINIPROGRAM_COLUMN_EXPECTED_MIN_PARAGRAPHS || "4");
const expectedStyle = process.env.MINIPROGRAM_COLUMN_EXPECTED_STYLE || "electronic-column-source-backed-dj-profiles.v1";
const artifactRoot = process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT
  ? path.resolve(process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT)
  : path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `devtools-column-longform-rendered-${stamp}`);
const screenshotEnabled = process.env.MINIPROGRAM_SCREENSHOTS === "1";
const steps = [];

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

function writeJson(name, value) {
  fs.writeFileSync(path.join(artifactDir, name), JSON.stringify(value, null, 2), "utf8");
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

function connectDevtools(endpoint, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(endpoint);
    const timer = setTimeout(() => {
      try { ws.close(); } catch { /* ignore cleanup */ }
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
    last = await read();
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

function itemStats(items) {
  const bodyLengths = items.map((item) => String(item.body || "").length);
  const paragraphCounts = items.map((item) => Array.isArray(item.paragraphs) ? item.paragraphs.length : 0);
  return {
    count: items.length,
    firstId: items[0] ? items[0].id : "",
    ids: items.map((item) => item.id),
    styleVersions: [...new Set(items.map((item) => item.columnStyleVersion || ""))].sort(),
    minBodyLen: bodyLengths.length ? Math.min(...bodyLengths) : 0,
    maxBodyLen: bodyLengths.length ? Math.max(...bodyLengths) : 0,
    minParagraphs: paragraphCounts.length ? Math.min(...paragraphCounts) : 0,
    maxParagraphs: paragraphCounts.length ? Math.max(...paragraphCounts) : 0,
    expandedCount: items.filter((item) => item.expanded).length,
  };
}

function columnStateInApp() {
  const pages = typeof getCurrentPages === "function" ? getCurrentPages() : [];
  const page = pages[pages.length - 1];
  return {
    route: page && page.route,
    data: page && page.data,
  };
}

async function main() {
  if (launchMode && !wsEndpoint) {
    throw new Error([
      "devtools-column-longform-rendered currently needs an explicit verified WebSocket endpoint for raw protocol screenshots.",
      automationHint,
      `Project path: ${projectPath}`,
      `DevTools CLI: ${cliPath}`,
    ].join("\n"));
  }
  if (!wsEndpoint) throw new Error("MINIPROGRAM_AUTOMATOR_WS is required");
  const report = {
    schemaVersion: "devtools_column_longform_rendered.v2",
    generatedAt: new Date().toISOString(),
    artifactDir,
    wsEndpoint,
    launchMode,
    launchPort,
    idePort,
    remoteBaseUrl,
    expectedCount,
    expectedMinBodyLen,
    expectedMinParagraphs,
    expectedStyle,
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
  let ws;
  try {
    ws = await step("connect DevTools websocket", () => withTimeout(connectDevtools(wsEndpoint), 40000, "DevTools websocket connect"));

    await step("configure remote column base url", () => withTimeout(callAppFunction(ws, function configureColumnRemote(baseUrl) {
      wx.clearStorageSync();
      const app = getApp();
      const cloud = app.globalData.cloud;
      cloud.publicBaseUrl = baseUrl;
      cloud.staticBaseUrl = "";
      cloud.useMock = false;
      cloud.devtoolsMockFallback = false;
      cloud.offlineSnapshotFallback = false;
      cloud.fastOfflineSnapshotFallback = false;
      return { publicBaseUrl: cloud.publicBaseUrl };
    }, [remoteBaseUrl], 30000), 40000, "configure remote column base url"));

    await step("open column page", async () => {
      const targetUrl = "/pages/column/column";
      const targetRoute = "pages/column/column";
      let lastOpen = null;
      for (let attempt = 0; attempt < 4; attempt += 1) {
        try {
          lastOpen = await withTimeout(callAppFunction(ws, function openColumnPageInApp(url, attemptNo) {
            const useSwitchTab = attemptNo % 2 === 1;
            const method = useSwitchTab ? wx.switchTab : wx.reLaunch;
            return new Promise((resolve) => {
              method({
                url,
                success: () => resolve({ ok: true, method: useSwitchTab ? "wx.switchTab" : "wx.reLaunch", url, attemptNo }),
                fail: (error) => resolve({ ok: false, method: useSwitchTab ? "wx.switchTab" : "wx.reLaunch", url, attemptNo, error }),
              });
            });
          }, [targetUrl, attempt], 60000), 70000, `open column page attempt ${attempt + 1}`);
        } catch (error) {
          lastOpen = {
            ok: false,
            method: attempt % 2 === 1 ? "wx.switchTab" : "wx.reLaunch",
            attemptNo: attempt,
            error: error && error.stack ? error.stack : String(error),
          };
        }
        await sleep(1200);
        try {
          const state = await callAppFunction(ws, columnStateInApp, [], 15000);
          if (state && state.route === targetRoute) {
            return { ok: true, route: state.route, lastOpen };
          }
          lastOpen = { ...lastOpen, observedRoute: state && state.route };
        } catch (error) {
          lastOpen = { ...lastOpen, routeReadError: error && error.stack ? error.stack : String(error) };
        }
      }
      throw new Error(`open column page failed; last=${JSON.stringify(lastOpen)}`);
    });

    const loadedState = await step("wait column page loaded", () => pollUntil(
      "wait column page loaded",
      45000,
      500,
      () => callAppFunction(ws, columnStateInApp, [], 15000),
      (state) => state && state.route === "pages/column/column" && state.data && state.data.loading === false,
    ));
    const loaded = loadedState.data || {};
    const items = Array.isArray(loaded.filteredItems) ? loaded.filteredItems : [];
    const initialStats = itemStats(items);
    report.steps.push({
      label: "column page loaded remote longform items",
      ok: true,
      loading: loaded.loading,
      loadFailed: loaded.loadFailed,
      activeTag: loaded.activeTag,
      ...initialStats,
    });

    assert.equal(loaded.loadFailed, false, "column page fell back to local cache instead of remote CloudRun data");
    assert.equal(initialStats.count, expectedCount, `expected ${expectedCount} rendered column items, got ${initialStats.count}`);
    assert.ok(initialStats.styleVersions.includes(expectedStyle), `expected style ${expectedStyle}, got ${initialStats.styleVersions.join(",")}`);
    assert.ok(initialStats.minBodyLen >= expectedMinBodyLen, `expected min body length >= ${expectedMinBodyLen}, got ${initialStats.minBodyLen}`);
    assert.ok(initialStats.minParagraphs >= expectedMinParagraphs, `expected min paragraphs >= ${expectedMinParagraphs}, got ${initialStats.minParagraphs}`);

    const expandedItem = await step("expand first column card", () => withTimeout(callAppFunction(ws, function expandFirstColumnCard(itemId) {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      page.onCardTap({ currentTarget: { dataset: { id: itemId } } });
      return page.data.filteredItems.find((item) => item.id === itemId);
    }, [items[0].id], 15000), 25000, "expand first column card"));
    const expandedState = await callAppFunction(ws, columnStateInApp, [], 15000);
    const expandedItems = Array.isArray(expandedState.data && expandedState.data.filteredItems) ? expandedState.data.filteredItems : [];
    report.steps.push({
      label: "first column card expands long body",
      ok: true,
      expandedItem,
      ...itemStats(expandedItems),
    });
    assert.equal(Boolean(expandedItem && expandedItem.expanded), true, "first column card did not expand");

    const shareProof = await step("verify first column share payload", () => withTimeout(callAppFunction(ws, function verifyFirstColumnShare(itemId) {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      const item = page.data.filteredItems.find((candidate) => candidate.id === itemId) || {};
      const appMessage = page.onShareAppMessage({
        target: { dataset: { id: item.id, title: item.title } },
      });
      page.setData({ lastExpandedItemId: item.id });
      const timeline = page.onShareTimeline();
      return {
        itemId: item.id,
        itemTitle: item.title,
        appMessage,
        timeline,
        lastExpandedItemId: page.data.lastExpandedItemId,
      };
    }, [items[0].id], 15000), 25000, "verify first column share payload"));
    assert.equal(shareProof.itemId, items[0].id, "share proof targeted a different column item");
    assert.match(
      String(shareProof.appMessage && shareProof.appMessage.path || ""),
      new RegExp(`(^|[?&])highlight=${encodeURIComponent(items[0].id)}($|&)`),
      "send-to-friend column share path did not preserve highlight",
    );
    assert.match(
      String(shareProof.timeline && shareProof.timeline.query || ""),
      new RegExp(`(^|[?&])highlight=${encodeURIComponent(items[0].id)}($|&)`),
      "timeline column share query did not preserve highlight",
    );
    assert.equal(shareProof.lastExpandedItemId, items[0].id, "timeline focus state did not preserve expanded item");
    report.shareProof = shareProof;

    if (screenshotEnabled) {
      await step("wait for expanded column render", () => sleep(1200));
      report.screenshot = await captureScreenshotFile(ws, "column-longform-expanded.png", "capture expanded column screenshot");
    }

    writeJson("report.json", report);
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    const failure = {
      schemaVersion: "devtools_column_longform_rendered.failure.v2",
      generatedAt: new Date().toISOString(),
      artifactDir,
      wsEndpoint,
      remoteBaseUrl,
      safety: report.safety,
      steps,
      error: error && error.stack ? error.stack : String(error),
    };
    writeJson("failure.json", failure);
    console.error(JSON.stringify(failure, null, 2));
    process.exitCode = 1;
  } finally {
    await closeSocket(ws);
  }
}

main();
