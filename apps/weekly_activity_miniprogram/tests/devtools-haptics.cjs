const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { effectiveFeedItems } = require("./effective-feed-items.cjs");
const { readPageDataWithFallback } = require("./devtools-page-data.cjs");
const { activateStaticPackage, startStaticPackageServer } = require("./devtools-static-package.cjs");

let automator;
try {
  automator = require("miniprogram-automator");
} catch (error) {
  console.error("[devtools-haptics] miniprogram-automator is required.");
  console.error("[devtools-haptics] Example:");
  console.error("  npm --prefix %TEMP%\\huaidj-miniprogram-automator install miniprogram-automator@0.12.1");
  console.error("  set NODE_PATH=%TEMP%\\huaidj-miniprogram-automator\\node_modules");
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
  `Launch directly with: MINIPROGRAM_AUTOMATOR_LAUNCH=1 MINIPROGRAM_AUTOMATOR_PORT=${launchPort} node tests/devtools-haptics.cjs`,
  "Only set MINIPROGRAM_AUTOMATOR_WS when a compatible bridge has produced a verified dynamic websocket endpoint.",
].join("\n");
const artifactRoot = process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT
  ? path.resolve(process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT)
  : path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `devtools-haptics-${stamp}`);
const staticPackageDir = String(process.env.MINIPROGRAM_STATIC_PACKAGE_DIR || "").trim();
const reportFile = path.join(artifactDir, "report.json");
fs.mkdirSync(artifactDir, { recursive: true });

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function connectMiniProgram() {
  try {
    if (launchMode) {
      return await withTimeout(automator.launch({
        projectPath,
        cliPath,
        port: launchPort,
        idePort,
        trustProject: true,
        timeout: 90000,
      }), 110000, "automator launch");
    }
    return await withTimeout(automator.connect({ wsEndpoint }), 30000, "automator connect");
  } catch (error) {
    const message = error && error.stack ? error.stack : String(error);
    throw new Error(`${message}\n\n${automationHint}`);
  }
}

async function openHome(miniProgram) {
  let page = await withTimeout(miniProgram.currentPage(), 12000, "current page");
  if (page.path !== "pages/index/index") {
    try {
      await withTimeout(miniProgram.reLaunch("/pages/index/index"), 16000, "reLaunch home");
      page = await withTimeout(miniProgram.currentPage(), 12000, "current home");
    } catch {
      await withTimeout(
        miniProgram.evaluate(() => new Promise((resolve) => {
          wx.reLaunch({ url: "/pages/index/index", complete: resolve });
        })),
        16000,
        "wx.reLaunch home"
      );
      page = await withTimeout(miniProgram.currentPage(), 12000, "current home after wx.reLaunch");
    }
  }
  assert.equal(page.path, "pages/index/index", `expected home page, got ${page.path}`);
  return page;
}

async function waitForIdle(miniProgram, page, label, timeoutMs = 18000) {
  const started = Date.now();
  let data = await readPageDataWithFallback(miniProgram, page, { label });
  while (data.loading && Date.now() - started < timeoutMs) {
    await page.waitFor(400);
    data = await readPageDataWithFallback(miniProgram, page, { label });
  }
  assert.equal(data.loading, false, `${label}: still loading after ${timeoutMs}ms`);
  assert.equal(data.error || "", "", `${label}: ${data.error || "unexpected page error"}`);
  assert.ok(effectiveFeedItems(data).length > 0, `${label}: no feed items loaded`);
  assert.ok((data.popularItems || []).length > 1, `${label}: no poster strip items loaded`);
  return data;
}

async function installHapticProbe(miniProgram) {
  await miniProgram.evaluate(() => {
    getApp().globalData.__hapticCli = { calls: [] };
  });
}

async function resetProbe(miniProgram) {
  await miniProgram.evaluate(() => {
    getApp().globalData.__hapticCli = { calls: [] };
  });
}

async function readProbe(miniProgram) {
  const raw = await miniProgram.evaluate(() => JSON.stringify(getApp().globalData.__hapticCli || { calls: [] }));
  return JSON.parse(raw);
}

async function resetPageHaptics(miniProgram, options = {}) {
  const feedLastAtAgo = Number(options.feedLastAtAgo || 0);
  const posterLastAtAgo = Number(options.posterLastAtAgo || 0);
  await miniProgram.evaluate((feedAgo, posterAgo) => {
    const pages = getCurrentPages();
    const page = pages[pages.length - 1];
    const now = Date.now();
    if (!page) return;
    page.lastHapticAt = 0;
    page.feedHapticState = {
      lastPosition: 0,
      lastAt: feedAgo ? now - feedAgo : now,
      lastPulsePosition: 0,
      lastPulseAt: 0,
      travelSincePulse: 0,
    };
    page.feedTouchHapticState = {
      lastPosition: 0,
      lastAt: feedAgo ? now - feedAgo : now,
      lastPulsePosition: 0,
      lastPulseAt: 0,
      travelSincePulse: 0,
    };
    page.posterHapticState = {
      lastPosition: 0,
      lastAt: posterAgo ? now - posterAgo : now,
      lastPulsePosition: 0,
      lastPulseAt: 0,
      travelSincePulse: 0,
    };
  }, feedLastAtAgo, posterLastAtAgo);
}

async function countAfter(label, miniProgram, action) {
  await sleep(250);
  await resetProbe(miniProgram);
  await action();
  await sleep(600);
  const probe = await readProbe(miniProgram);
  const types = {};
  for (const call of probe.calls || []) {
    const type = call.type || "unknown";
    types[type] = (types[type] || 0) + 1;
  }
  return { label, count: probe.calls.length, types, calls: probe.calls };
}

async function run() {
  const staticServer = staticPackageDir ? await startStaticPackageServer(staticPackageDir) : null;
  const report = {
    artifactDir,
    projectPath,
    wsEndpoint,
    launch: launchMode,
    staticPackageDir,
    staticBaseUrl: staticServer ? staticServer.baseUrl : "",
    checks: {},
    selectedProfile: {
      feed: "145-280ms interval, 64-140px cumulative travel",
      poster: "145-280ms interval, 64-140px cumulative travel (same as feed)",
      tab: "220ms interval",
      refresh: "320ms interval",
      vibration: "medium short pulse",
    },
  };
  const miniProgram = await connectMiniProgram();
  const exceptions = [];
  const consoleMessages = [];
  miniProgram.on("exception", (payload) => exceptions.push(payload));
  miniProgram.on("console", (payload) => consoleMessages.push(payload));

  try {
    await installHapticProbe(miniProgram);
    const home = await openHome(miniProgram);
    if (staticServer) {
      await withTimeout(activateStaticPackage(miniProgram, staticServer.baseUrl), 30000, "activate static package");
    }
    const data = await waitForIdle(miniProgram, home, "home");
    report.itemCount = effectiveFeedItems(data).length;
    report.posterCount = data.popularItems.length;

    report.checks.actualPageScroll = await countAfter("actualPageScroll", miniProgram, async () => {
      await resetPageHaptics(miniProgram, { feedLastAtAgo: 520 });
      await withTimeout(miniProgram.pageScrollTo(0), 10000, "pageScrollTo 0");
      await sleep(250);
      await withTimeout(miniProgram.pageScrollTo(760), 10000, "pageScrollTo 760");
    });

    report.checks.actualPosterScroll = await countAfter("actualPosterScroll", miniProgram, async () => {
      const current = await miniProgram.currentPage();
      await resetPageHaptics(miniProgram, { posterLastAtAgo: 420 });
      const poster = await current.$(".poster-strip");
      assert.ok(poster, "poster strip not found");
      await poster.scrollTo(0, 0);
      await sleep(260);
      await poster.scrollTo(180, 0);
    });

    report.checks.feedSlow = await countAfter("feedSlow", miniProgram, async () => {
      const current = await miniProgram.currentPage();
      await resetPageHaptics(miniProgram, { feedLastAtAgo: 540 });
      await current.callMethod("onPageScroll", { scrollTop: 310 });
      await sleep(80);
      await current.callMethod("onPageScroll", { scrollTop: 380 });
    });

    report.checks.feedTouchMove = await countAfter("feedTouchMove", miniProgram, async () => {
      const current = await miniProgram.currentPage();
      await resetPageHaptics(miniProgram, { feedLastAtAgo: 540 });
      await current.callMethod("onFeedTouchStart", { touches: [{ clientY: 520 }] });
      await sleep(90);
      await current.callMethod("onFeedTouchMove", { touches: [{ clientY: 445 }] });
      await sleep(90);
      await current.callMethod("onFeedTouchMove", { touches: [{ clientY: 370 }] });
    });

    report.checks.feedFast = await countAfter("feedFast", miniProgram, async () => {
      const current = await miniProgram.currentPage();
      await resetPageHaptics(miniProgram, { feedLastAtAgo: 260 });
      await current.callMethod("onPageScroll", { scrollTop: 170 });
      await sleep(80);
      await current.callMethod("onPageScroll", { scrollTop: 340 });
    });

    report.checks.feedBackAndForth = await countAfter("feedBackAndForth", miniProgram, async () => {
      const current = await miniProgram.currentPage();
      await resetPageHaptics(miniProgram, { feedLastAtAgo: 120 });
      await current.callMethod("onPageScroll", { scrollTop: 70 });
      await sleep(170);
      await current.callMethod("onPageScroll", { scrollTop: 0 });
    });

    report.checks.posterFast = await countAfter("posterFast", miniProgram, async () => {
      const current = await miniProgram.currentPage();
      await resetPageHaptics(miniProgram, { posterLastAtAgo: 220 });
      await current.callMethod("onPosterStripScroll", { detail: { scrollLeft: 132 } });
      await sleep(70);
      await current.callMethod("onPosterStripScroll", { detail: { scrollLeft: 260 } });
    });

    report.checks.topTab = await countAfter("topTab", miniProgram, async () => {
      const current = await miniProgram.currentPage();
      await resetPageHaptics(miniProgram);
      await current.callMethod("setTab", { currentTarget: { dataset: { tab: "forYou" } } });
      await sleep(340);
      await current.callMethod("setTab", { currentTarget: { dataset: { tab: "new" } } });
    });

    report.checks.bottomTabSwitchApi = await countAfter("bottomTabSwitchApi", miniProgram, async () => {
      await resetPageHaptics(miniProgram);
      await withTimeout(miniProgram.switchTab("/pages/about/about"), 30000, "switchTab about");
      await sleep(800);
    });

    report.checks.bottomTabHook = await countAfter("bottomTabHook", miniProgram, async () => {
      const about = await miniProgram.currentPage();
      assert.equal(about.path, "pages/about/about", `expected about page, got ${about.path}`);
      await about.callMethod("onTabItemTap");
    });

    report.checks.actualPageScroll.automationNote = "automator pageScrollTo may not emit Page.onPageScroll";
    assert.ok(
      report.checks.actualPageScroll.count >= 1 || report.checks.feedTouchMove.count >= 1,
      "vertical feed touch movement did not trigger haptic"
    );
    report.checks.actualPosterScroll.automationNote = "automator scroll-view.scrollTo may not emit bindscroll";
    assert.equal(report.checks.feedSlow.count, 1, "slow feed should pulse once");
    assert.equal(report.checks.feedTouchMove.count, 1, "touch-driven feed movement should pulse once");
    assert.equal(report.checks.feedFast.count, 1, "fast feed should pulse once and suppress immediate follow-up");
    assert.equal(report.checks.feedBackAndForth.count, 1, "back-and-forth feed scroll should pulse from cumulative travel");
    assert.equal(report.checks.posterFast.count, 1, "poster fast scroll should use feed-like pulse and suppress immediate follow-up");
    assert.equal(report.checks.topTab.count, 2, "top tabs should pulse once per spaced tab change");
    assert.ok(
      report.checks.bottomTabSwitchApi.count >= 1 || report.checks.bottomTabHook.count >= 1,
      "bottom tab hook did not trigger haptic"
    );

    report.exceptions = exceptions;
    report.consoleMessages = consoleMessages;
    fs.writeFileSync(reportFile, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    console.log(JSON.stringify({
      ok: true,
      artifactDir,
      itemCount: report.itemCount,
      checks: Object.fromEntries(Object.entries(report.checks).map(([key, value]) => [key, value.count])),
      exceptions: exceptions.length,
      consoleMessages: consoleMessages.length,
    }, null, 2));
  } catch (error) {
    report.error = error && error.stack ? error.stack : String(error);
    report.exceptions = exceptions;
    report.consoleMessages = consoleMessages;
    fs.writeFileSync(reportFile, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    throw error;
  } finally {
    try {
      if (noCloseDevTools) {
        miniProgram.disconnect();
      } else {
        await withTimeout(miniProgram.close(), 15000, "miniProgram.close");
      }
    } catch {
      miniProgram.disconnect();
    }
    if (staticServer) await staticServer.close();
  }
}

run().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
