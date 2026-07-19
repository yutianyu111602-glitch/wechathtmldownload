/**
 * Rendered proof: Guide tab opens pages/city/city, builds a city guide from
 * current weekly data, and keeps secondary routes wired.
 * Safety: read-only; no upload/deploy/review/release/production DB write.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");
const { connectRawDevtools } = require("./devtools-raw-session.cjs");

const endpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "").trim();
const artifactRoot = process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT
  ? path.resolve(process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT)
  : path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `devtools-city-guide-rendered-${stamp}`);
const reportPath = path.join(artifactDir, "report.json");
const screenshotEnabled = process.env.MINIPROGRAM_SCREENSHOTS === "1";
const steps = [];

fs.mkdirSync(artifactDir, { recursive: true });

const report = {
  schemaVersion: "devtools_city_guide_rendered.v1",
  generatedAt: new Date().toISOString(),
  endpoint,
  artifactDir,
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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function writeReport() {
  report.finishedAt = new Date().toISOString();
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
}

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
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

function connectDevtools(url) {
  return connectRawDevtools({ endpoint: url, timeoutMs: 120000 });
}

function send(ws, method, params = {}, timeoutMs = 15000) {
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

function callApp(ws, fn, args = [], timeoutMs = 15000) {
  return send(ws, "App.callFunction", {
    functionDeclaration: fn.toString(),
    args,
  }, timeoutMs).then((response) => response.result);
}

async function pollUntil(label, timeoutMs, intervalMs, read, done) {
  const started = Date.now();
  let last;
  while (Date.now() - started <= timeoutMs) {
    last = await read();
    if (done(last)) return last;
    await sleep(intervalMs);
  }
  throw new Error(`${label} timed out; last=${JSON.stringify(last)}`);
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

async function captureScreenshot(ws, name) {
  if (!screenshotEnabled) return null;
  const capture = await send(ws, "App.captureScreenshot", {}, 30000);
  const filePath = path.join(artifactDir, `${name}.png`);
  fs.writeFileSync(filePath, capture.data || "", "base64");
  const bytes = fs.statSync(filePath).size;
  assert.ok(bytes > 1024, `${name} screenshot should be non-empty`);
  return { path: filePath, bytes };
}

function readCityState() {
  const pages = typeof getCurrentPages === "function" ? getCurrentPages() : [];
  const page = pages[pages.length - 1];
  const data = page && page.data ? page.data : {};
  const guide = data.guide || {};
  return {
    route: page && page.route,
    loading: Boolean(data.loading),
    error: String(data.error || ""),
    selectedCityKey: String(data.selectedCityKey || ""),
    citiesCount: Array.isArray(data.cities) ? data.cities.length : 0,
    firstCityKey: Array.isArray(data.cities) && data.cities[0] ? data.cities[0].key : "",
    hasSelection: Boolean(guide.hasSelection),
    selectedCityLabel: String(guide.selectedCityLabel || ""),
    eventCount: Number(guide.eventCount || 0),
    activeDateCount: Number(guide.activeDateCount || 0),
    decisionCount: Array.isArray(guide.decisionCards) ? guide.decisionCards.length : 0,
    venueLeadCount: Array.isArray(guide.venueLeads) ? guide.venueLeads.length : 0,
    firstDecisionId: Array.isArray(guide.decisionCards) && guide.decisionCards[0] && guide.decisionCards[0].item
      ? String(guide.decisionCards[0].item.id || "")
      : "",
    firstVenueName: Array.isArray(guide.venueLeads) && guide.venueLeads[0]
      ? String(guide.venueLeads[0].name || "")
      : "",
  };
}

async function main() {
  let ws;
  try {
    ws = await step("connect DevTools", () => connectDevtools(endpoint));

    report.toolInfo = await step("Tool.getInfo", () => send(ws, "Tool.getInfo", {}, 8000));

    await step("launch guide tab", () => callApp(ws, function launchGuide() {
      try { wx.setStorageSync("weeklyActivityLang", "zh"); } catch (e) {}
      try { wx.removeStorageSync("weeklyActivityGuideCity"); } catch (e) {}
      return new Promise((resolve) => {
        wx.reLaunch({
          url: "/pages/city/city",
          success: () => resolve({ ok: true }),
          fail: (err) => resolve({ ok: false, err }),
        });
      });
    }, [], 20000));

    const unselected = await step("wait guide city candidates", () => pollUntil(
      "guide city candidates",
      45000,
      700,
      () => callApp(ws, readCityState, [], 10000),
      (state) => state.route === "pages/city/city" && state.loading === false && !state.error && state.citiesCount > 0 && state.hasSelection === false,
    ));
    report.unselected = unselected;
    report.unselectedScreenshot = await step("optional screenshot unselected", () => captureScreenshot(ws, "guide-unselected"));

    const cityKey = unselected.firstCityKey;
    assert.ok(cityKey, "first city key is required for guide selection");

    await step("select first city", () => callApp(ws, function selectCity(key) {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      page.openCity({ currentTarget: { dataset: { key } } });
      return { ok: true, key };
    }, [cityKey], 10000));

    const selected = await step("wait selected guide", () => pollUntil(
      "selected guide",
      20000,
      500,
      () => callApp(ws, readCityState, [], 10000),
      (state) => state.route === "pages/city/city" && state.loading === false && state.hasSelection === true && state.eventCount > 0,
    ));
    report.selected = selected;
    assert.ok(selected.decisionCount > 0, "selected guide should expose decision cards");
    assert.ok(selected.venueLeadCount > 0, "selected guide should expose venue leads");
    report.selectedScreenshot = await step("optional screenshot selected", () => captureScreenshot(ws, "guide-selected"));

    report.actionRouting = await step("verify guide action routing without leaving page", () => callApp(ws, function verifyActions() {
      const page = getCurrentPages()[getCurrentPages().length - 1];
      const guide = page && page.data && page.data.guide;
      const firstCard = guide && guide.decisionCards && guide.decisionCards[0];
      const firstVenue = guide && guide.venueLeads && guide.venueLeads[0];
      const calls = [];
      const oldNavigateTo = wx.navigateTo;
      const oldSwitchTab = wx.switchTab;
      wx.navigateTo = function spyNavigateTo(options) {
        calls.push({ method: "navigateTo", url: options && options.url });
        if (options && typeof options.success === "function") options.success({ errMsg: "navigateTo:ok" });
      };
      wx.switchTab = function spySwitchTab(options) {
        calls.push({ method: "switchTab", url: options && options.url });
        if (options && typeof options.success === "function") options.success({ errMsg: "switchTab:ok" });
      };
      try {
        page.openDecisionDetail({ currentTarget: { dataset: { id: firstCard.item.id } } });
        page.openVenueGuide({ currentTarget: { dataset: { name: firstVenue.name } } });
        page.openMap();
        page.openColumn();
        page.openAllEvents();
        let pendingCity = "";
        try { pendingCity = wx.getStorageSync("weeklyActivityPendingCity"); } catch (e) {}
        return {
          route: page.route,
          calls,
          pendingCity,
          firstDecisionId: firstCard && firstCard.item && firstCard.item.id,
          firstVenueName: firstVenue && firstVenue.name,
        };
      } finally {
        wx.navigateTo = oldNavigateTo;
        wx.switchTab = oldSwitchTab;
      }
    }, [], 15000));

    const urls = report.actionRouting.calls.map((call) => call.url || "");
    assert.ok(urls.some((url) => url.indexOf("/pages/detail/detail?id=") === 0), "detail action route missing");
    assert.ok(urls.some((url) => url.indexOf("/pages/venue/venue?name=") === 0), "venue action route missing");
    assert.ok(urls.includes("/pages/map/map?lang=zh"), "map action route missing");
    assert.ok(urls.includes("/pages/column/column?lang=zh"), "column action route missing");
    assert.ok(report.actionRouting.calls.some((call) => call.method === "switchTab" && call.url === "/pages/index/index"), "all events switchTab route missing");
    assert.equal(report.actionRouting.pendingCity, cityKey, "all events action should write pending city");

    report.ok = true;
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    report.ok = false;
    report.error = error && error.stack ? error.stack : String(error);
    console.error(report.error);
    process.exitCode = 1;
  } finally {
    await closeSocket(ws);
    writeReport();
  }
}

main();
