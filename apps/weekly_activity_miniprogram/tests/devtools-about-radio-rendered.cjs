const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { readPageDataWithFallback } = require("./devtools-page-data.cjs");

let automator;
try {
  automator = require("miniprogram-automator");
} catch (error) {
  console.error("[devtools-about-radio-rendered] miniprogram-automator is required.");
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
const launchPort = Number(process.env.MINIPROGRAM_AUTOMATOR_PORT || "9424");
const idePort = Number(process.env.MINIPROGRAM_DEVTOOLS_IDE_PORT || "54272");
const cliArgs = Number.isFinite(idePort) && idePort > 0 ? ["--port", String(idePort)] : [];
const launchTimeoutMs = Number(process.env.MINIPROGRAM_AUTOMATOR_LAUNCH_TIMEOUT_MS || "180000");
const artifactRoot = path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `about-radio-rendered-${stamp}`);
const expectedStationKeys = String(process.env.MINIPROGRAM_EXPECTED_RADIO_KEYS || "byyb,baihui,shcr,cdcr,hoer,hzcr")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const screenshotEnabled = process.env.MINIPROGRAM_SCREENSHOTS === "1";

fs.mkdirSync(artifactDir, { recursive: true });

let failureWritten = false;

function writeFailure(error, failureKind = "run_failure") {
  if (failureWritten) return;
  failureWritten = true;
  const failure = {
    schemaVersion: "devtools_about_radio_rendered.failure.v1",
    generatedAt: new Date().toISOString(),
    artifactDir,
    wsEndpoint,
    launchMode,
    launchPort,
    idePort,
    launchTimeoutMs,
    projectPath,
    failureKind,
    safety: {
      miniProgramUploadExecuted: false,
      cloudRunDeployExecuted: false,
      previewQrGenerated: false,
      reviewSubmitted: false,
      publicReleaseExecuted: false,
      productionDbWriteExecuted: false,
    },
    error: error && error.stack ? error.stack : String(error),
  };
  fs.writeFileSync(path.join(artifactDir, "failure.json"), JSON.stringify(failure, null, 2), "utf8");
  console.error(JSON.stringify(failure, null, 2));
}

process.on("uncaughtException", (error) => {
  writeFailure(error, "uncaughtException");
  process.exit(1);
});

process.on("unhandledRejection", (error) => {
  writeFailure(error, "unhandledRejection");
  process.exit(1);
});

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function openAbout(miniProgram) {
  const url = "/pages/about/about";
  const expectedPath = url.replace(/^\//, "");
  let page;
  try {
    page = await withTimeout(miniProgram.switchTab(url), 25000, "automator switchTab about");
  } catch (error) {
    page = null;
  }
  if (!page || page.path !== expectedPath) {
    await withTimeout(
      miniProgram.evaluate((targetUrl) => new Promise((resolve) => {
        wx.switchTab({ url: targetUrl, complete: resolve });
      }), url),
      25000,
      "wx.switchTab about",
    );
  }
  page = await withTimeout(miniProgram.currentPage(), 12000, "currentPage about");
  if (page.path !== expectedPath) {
    page = await withTimeout(miniProgram.reLaunch(url), 25000, "reLaunch about");
  }
  assert.equal(page.path, "pages/about/about");
  return page;
}

async function waitForRadioIdle(miniProgram, page, timeoutMs) {
  const started = Date.now();
  let data = await readPageDataWithFallback(miniProgram, page, { label: "about radio" });
  while (data && data.radioLoading && Date.now() - started < timeoutMs) {
    await page.waitFor(300);
    data = await readPageDataWithFallback(miniProgram, page, { label: "about radio" });
  }
  assert.equal(Boolean(data.radioLoading), false, `about radio still loading after ${timeoutMs}ms`);
  return data;
}

async function maybeScreenshot(miniProgram, name) {
  if (!screenshotEnabled) return "";
  const file = path.join(artifactDir, `${name}.png`);
  try {
    await withTimeout(miniProgram.screenshot({ path: file }), 15000, `screenshot ${name}`);
    return file;
  } catch (error) {
    return "";
  }
}

async function run() {
  const report = {
    schemaVersion: "devtools_about_radio_rendered.v1",
    generatedAt: new Date().toISOString(),
    artifactDir,
    wsEndpoint,
    launchMode,
    launchPort,
    idePort,
    launchTimeoutMs,
    projectPath,
    expectedStationKeys,
    steps: [],
    exceptions: [],
    consoleCount: 0,
    safety: {
      miniProgramUploadExecuted: false,
      cloudRunDeployExecuted: false,
      previewQrGenerated: false,
      reviewSubmitted: false,
      publicReleaseExecuted: false,
      productionDbWriteExecuted: false,
    },
  };
  let miniProgram;
  const exceptions = [];
  const consoleMessages = [];

  try {
    miniProgram = launchMode
      ? await withTimeout(automator.launch({
        projectPath,
        cliPath,
        port: launchPort,
        args: cliArgs,
        idePort,
        trustProject: true,
        timeout: launchTimeoutMs,
      }), launchTimeoutMs + 20000, "automator launch")
      : await withTimeout(automator.connect({ wsEndpoint }), 30000, "automator connect");
    miniProgram.on("exception", (payload) => exceptions.push(payload));
    miniProgram.on("console", (payload) => consoleMessages.push(payload));

    const page = await openAbout(miniProgram);
    const data = await waitForRadioIdle(miniProgram, page, 45000);
    const stations = Array.isArray(data.radioStations) ? data.radioStations : [];
    const stationKeys = stations.map((station) => station.stationKey).filter(Boolean).sort();
    const primaryUrls = stations.map((station) => station.primaryUrl).filter(Boolean);
    report.steps.push({
      name: "about radio section loaded",
      radioSourceLabel: data.radioSourceLabel || "",
      stationCount: stations.length,
      stationKeys,
      primaryUrls,
    });

    assert.ok(stations.length >= expectedStationKeys.length, `expected at least ${expectedStationKeys.length} radio stations, got ${stations.length}`);
    for (const key of expectedStationKeys) {
      assert.ok(stationKeys.includes(key), `missing radio station ${key}`);
    }
    assert.ok(primaryUrls.every((url) => /^https:\/\//.test(url)), "radio primary urls must be original https pages");
    assert.ok(stations.every((station) => station.primaryUrl && !/\.mp3($|\?)/i.test(station.primaryUrl)), "radio links must not be direct media files");

    const sourceRouteProbe = await withTimeout(miniProgram.evaluate(() => new Promise((resolve) => {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      const first = (page.data.radioStations || [])[0] || {};
      const calls = [];
      const originalNavigateTo = wx.navigateTo;
      const originalSetClipboardData = wx.setClipboardData;
      const originalShowToast = wx.showToast;
      wx.navigateTo = (options) => {
        calls.push({ type: "navigateTo", url: options && options.url });
        if (options && typeof options.success === "function") options.success({});
        if (options && typeof options.complete === "function") options.complete({});
      };
      wx.setClipboardData = (options) => {
        calls.push({ type: "setClipboardData", data: options && options.data });
        if (options && typeof options.success === "function") options.success({});
        if (options && typeof options.complete === "function") options.complete({});
      };
      wx.showToast = (options) => {
        calls.push({ type: "showToast", title: options && options.title });
        if (options && typeof options.success === "function") options.success({});
        if (options && typeof options.complete === "function") options.complete({});
      };
      try {
        page.openRadioLink({
          currentTarget: {
            dataset: {
              url: first.primaryUrl,
              name: first.stationName,
              meta: first.metaLabel,
            },
          },
        });
        resolve({ firstUrl: first.primaryUrl || "", calls });
      } finally {
        wx.navigateTo = originalNavigateTo;
        wx.setClipboardData = originalSetClipboardData;
        wx.showToast = originalShowToast;
      }
    })), 12000, "radio source route action probe");
    report.steps.push({
      name: "radio tap opens source page for original-site link",
      ...sourceRouteProbe,
    });
    assert.equal(sourceRouteProbe.calls[0] && sourceRouteProbe.calls[0].type, "navigateTo");
    assert.match(sourceRouteProbe.calls[0] && sourceRouteProbe.calls[0].url, /^\/pages\/source\/source\?externalUrl=/);
    assert.ok(decodeURIComponent(sourceRouteProbe.calls[0] && sourceRouteProbe.calls[0].url).includes(sourceRouteProbe.firstUrl));
    assert.equal(sourceRouteProbe.calls.some((call) => call.type === "setClipboardData"), false, "radio tap should not copy before source-page fallback");

    const screenshot = await maybeScreenshot(miniProgram, "about-radio");
    if (screenshot) report.steps.push({ name: "screenshot saved", path: screenshot });

    report.consoleCount = consoleMessages.length;
    report.exceptions = exceptions;
    assert.deepEqual(exceptions, [], "DevTools reported runtime exceptions");
    fs.writeFileSync(path.join(artifactDir, "report.json"), JSON.stringify(report, null, 2), "utf8");
    console.log(JSON.stringify(report, null, 2));
  } finally {
    if (miniProgram) {
      try {
        if (noCloseDevTools) {
          miniProgram.disconnect();
        } else {
          await withTimeout(miniProgram.close(), 15000, "miniProgram.close");
        }
      } catch (error) {
        miniProgram.disconnect();
      }
    }
  }
}

run().catch((error) => {
  writeFailure(error);
  process.exit(1);
});
