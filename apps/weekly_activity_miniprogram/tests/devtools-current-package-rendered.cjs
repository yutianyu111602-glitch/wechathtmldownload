const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { effectiveFeedCount, effectiveFeedItems } = require("./effective-feed-items.cjs");
const { readPageDataWithFallback } = require("./devtools-page-data.cjs");
const {
  filterItemsByCityKey,
  filterItemsByDateSelection,
} = require("../services/homeFilters.js");

let automator;
try {
  automator = require("miniprogram-automator");
} catch (error) {
  console.error("[devtools-current-package-rendered] miniprogram-automator is required.");
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
const cliArgs = Number.isFinite(idePort) && idePort > 0 ? ["--port", String(idePort)] : [];
const artifactRoot = path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `devtools-current-package-rendered-${stamp}`);
const staticPackageDir = String(process.env.MINIPROGRAM_STATIC_PACKAGE_DIR || "").trim();
const expectedMinItemsRaw = Number(process.env.MINIPROGRAM_EXPECTED_MIN_ITEMS || "4");
const expectedMinItems = Number.isFinite(expectedMinItemsRaw) && expectedMinItemsRaw > 0 ? expectedMinItemsRaw : 4;
const expectPosterFileId = process.env.MINIPROGRAM_EXPECT_POSTER_FILEID !== "0";
const expectedMinPosterImageLoadsRaw = Number(process.env.MINIPROGRAM_EXPECTED_MIN_POSTER_IMAGE_LOADS || "1");
const expectedMinPosterImageLoads = Number.isFinite(expectedMinPosterImageLoadsRaw) && expectedMinPosterImageLoadsRaw >= 0
  ? expectedMinPosterImageLoadsRaw
  : 1;
const interactionCityKey = String(process.env.MINIPROGRAM_INTERACTION_CITY || "shanghai").trim();

fs.mkdirSync(artifactDir, { recursive: true });

function envList(name, fallback) {
  if (!Object.prototype.hasOwnProperty.call(process.env, name)) return fallback;
  return String(process.env[name] || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

const expectedDates = envList("MINIPROGRAM_EXPECTED_DATES", []);
const forbiddenDates = envList("MINIPROGRAM_FORBIDDEN_DATES", []);

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function openHome(miniProgram) {
  await withTimeout(
    miniProgram.evaluate(() => new Promise((resolve) => {
      wx.switchTab({
        url: "/pages/index/index",
        complete: () => {
          const pages = getCurrentPages();
          const page = pages[pages.length - 1];
          resolve({ route: page && page.route });
        },
      });
    })),
    25000,
    "switchTab home",
  );
  const page = await withTimeout(miniProgram.currentPage(), 12000, "currentPage home");
  assert.equal(page.path, "pages/index/index");
  return page;
}

async function waitForIdle(miniProgram, page, label, timeoutMs) {
  const started = Date.now();
  let data = await readPageDataWithFallback(miniProgram, page, { label });
  while (data && data.loading && Date.now() - started < timeoutMs) {
    await page.waitFor(200);
    data = await readPageDataWithFallback(miniProgram, page, { label });
  }
  assert.equal(data.loading, false, `${label}: still loading after ${timeoutMs}ms`);
  assert.equal(data.error || "", "", `${label}: unexpected error ${data.error || ""}`);
  return data;
}

function isIsoDateKey(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || "").trim());
}

function keyFromDate(date) {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateFromKey(key) {
  if (!isIsoDateKey(key)) return null;
  const [year, month, day] = key.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return Number.isNaN(date.getTime()) ? null : date;
}

function addDateRange(keys, startKey, endKey) {
  if (!isIsoDateKey(startKey)) return;
  const start = dateFromKey(startKey);
  const end = dateFromKey(isIsoDateKey(endKey) ? endKey : startKey);
  if (!start || !end || end < start) {
    keys.add(startKey);
    return;
  }
  for (let date = new Date(start); date <= end && keys.size < 400; date.setUTCDate(date.getUTCDate() + 1)) {
    keys.add(keyFromDate(date));
  }
}

function dateSetFromItems(items) {
  const keys = new Set();
  for (const item of items || []) {
    const start = item.event_date_start || item.eventDateStart || item.dateLabel || item.date || "";
    const end = item.event_date_end || item.eventDateEnd || start;
    addDateRange(keys, start, end);
    for (const value of item.event_date_iso_guesses || []) {
      if (isIsoDateKey(value)) keys.add(value);
    }
  }
  return [...keys].sort();
}

function contentTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".json") return "application/json; charset=utf-8";
  if (ext === ".gz") return "application/gzip";
  if (ext === ".txt") return "text/plain; charset=utf-8";
  return "application/octet-stream";
}

function safeStaticPath(root, urlPath) {
  const decoded = decodeURIComponent(String(urlPath || "/").split("?")[0]);
  const relative = path.normalize(decoded).replace(/^[/\\]+/, "");
  const fullPath = path.resolve(root, relative || "current.json");
  const rootWithSep = root.endsWith(path.sep) ? root : `${root}${path.sep}`;
  if (fullPath !== root && !fullPath.startsWith(rootWithSep)) return null;
  return fullPath;
}

async function startStaticPackageServer(packageDir) {
  const root = path.resolve(packageDir);
  const currentPath = path.join(root, "current.json");
  if (!fs.existsSync(currentPath)) {
    throw new Error(`MINIPROGRAM_STATIC_PACKAGE_DIR must contain current.json: ${root}`);
  }

  const server = http.createServer((req, res) => {
    const filePath = safeStaticPath(root, req.url || "/");
    if (!filePath || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      res.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
      res.end(JSON.stringify({ error: "not_found", path: req.url || "" }));
      return;
    }
    res.writeHead(200, {
      "Content-Type": contentTypeFor(filePath),
      "Cache-Control": "no-store",
    });
    fs.createReadStream(filePath).pipe(res);
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;
  return {
    baseUrl,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}

async function waitForPosterImageState(miniProgram, page, minLoadCount, timeoutMs) {
  const started = Date.now();
  let data = await readPageDataWithFallback(miniProgram, page, { label: "poster image state" });
  while (
    Number(data.posterImageLoadCount || 0) < minLoadCount
    && Number(data.posterImageErrorCount || 0) === 0
    && Date.now() - started < timeoutMs
  ) {
    await page.waitFor(300);
    data = await readPageDataWithFallback(miniProgram, page, { label: "poster image state" });
  }
  return {
    posterImageLoadCount: Number(data.posterImageLoadCount || 0),
    posterImageErrorCount: Number(data.posterImageErrorCount || 0),
    posterImageLoadedIds: Array.isArray(data.posterImageLoadedIds) ? data.posterImageLoadedIds : [],
    posterImageErrorUrls: Array.isArray(data.posterImageErrorUrls) ? data.posterImageErrorUrls : [],
  };
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
    staticPackageDir: staticPackageDir || "",
    staticBaseUrl,
    expectedMinItems,
    expectedDates,
    forbiddenDates,
    expectPosterFileId,
    steps: [],
    exceptions: [],
    consoleCount: 0,
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
        timeout: 90000,
      }), 110000, "automator launch")
      : await withTimeout(automator.connect({ wsEndpoint }), 30000, "automator connect");
    miniProgram.on("exception", (payload) => exceptions.push(payload));
    miniProgram.on("console", (payload) => consoleMessages.push(payload));

    const page = await openHome(miniProgram);
    try {
      const initialData = await waitForIdle(miniProgram, page, "initial home before static probe", 30000);
      report.initialHome = {
        itemCount: effectiveFeedCount(initialData),
        totalItems: initialData.totalItems,
        cacheNotice: initialData.cacheNotice || "",
      };
    } catch (error) {
      report.initialHome = {
        error: error && error.stack ? error.stack : String(error),
      };
    }
    await withTimeout(miniProgram.evaluate((injectedStaticBaseUrl) => {
      wx.clearStorageSync();
      const app = getApp();
      const cloud = app.globalData.cloud;
      app.globalData.__currentPackageRenderedProbe = {
        originalCloud: { ...cloud },
      };
      const staticPackageProbe = Boolean(injectedStaticBaseUrl);
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
      cloud.offlineSnapshotFallback = false;
      cloud.fastOfflineSnapshotFallback = false;
      cloud.offlineSnapshotFallbackDelayMs = -1;
      cloud.publicFallbackDelayMs = 0;
      cloud.cacheMaxAgeMs = -1;
      cloud.cacheFallbackDelayMs = 2200;
      if (staticPackageProbe) {
        cloud.useCloudDatabaseFirst = false;
        cloud.publicBaseUrl = "";
        cloud.staticBaseUrl = injectedStaticBaseUrl;
        cloud.cloudClient = staticOnlyClient;
        cloud.cloudInitPromise = null;
        cloud.cloudReady = true;
      } else {
        cloud.useCloudDatabaseFirst = true;
        cloud.staticBaseUrl = "";
      }
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      if (page) {
        page.setData({
          selectedCity: "",
          draftCity: "",
          selectedDate: "",
          draftDate: "",
          dateMode: "all_current",
          selectedDateStart: "",
          selectedDateEnd: "",
        });
        page.isLoadingRequest = false;
        page.pendingLoadOptions = null;
        page.loadSeq = Number(page.loadSeq || 0) + 1;
        if (typeof page.clearLoadingHintTimers === "function") page.clearLoadingHintTimers();
        if (typeof page.clearBackgroundRefreshTimer === "function") page.clearBackgroundRefreshTimer();
      }
    }, staticBaseUrl), 10000, "configure current-package probe");

    const startedAt = Date.now();
    const loadTiming = await withTimeout(miniProgram.evaluate(() => {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      const started = Date.now();
      return page.loadData().then((result) => ({
        pageElapsedMs: Date.now() - started,
        result: result || null,
        isLoadingRequest: Boolean(page.isLoadingRequest),
        loadSeq: Number(page.loadSeq || 0),
      }));
    }), 45000, "load current package");
    const data = await waitForIdle(miniProgram, page, "current-package home", 45000);
    const wallElapsedMs = Date.now() - startedAt;
    const pageElapsedMs = Number(loadTiming && loadTiming.pageElapsedMs);
    const items = effectiveFeedItems(data);
    const effectiveItemCount = effectiveFeedCount(data);
    const popularItems = data.popularItems || [];
    const itemDates = dateSetFromItems(items);
    const dateFilterKeys = (data.dateFilters || [])
      .map((entry) => String(entry && entry.key || "").trim())
      .filter(Boolean)
      .sort();
    const datesToExpect = expectedDates.length
      ? expectedDates
      : itemDates.slice(0, Math.min(2, itemDates.length));
    const posterUrls = popularItems.map((item) => String(item.coverUrl || "").trim()).filter(Boolean);
    const posterFileIds = popularItems.map((item) => String(item.posterFileId || "").trim()).filter(Boolean);
    const posterCount = posterUrls.length;
    const directTencentPosterCount = posterUrls.filter((url) => /^https:\/\/mmbiz\.qpic\.cn\//i.test(url)).length;
    const publicWechatPosterCount = posterUrls.filter((url) => /(?:mmbiz|mmecoa)\.qpic\.cn/i.test(url)).length;
    const internalPosterFileIdCount = posterUrls.filter((url) => /^(?:cloud|cloudbase|wxfile):\/\//i.test(url)).length;
    const internalPosterSourceFileIdCount = posterFileIds.filter((url) => /^(?:cloud|cloudbase|wxfile):\/\//i.test(url)).length;
    const cloudbaseTempPosterCount = posterUrls.filter((url) => /\.tcb\.qcloud\.la\//i.test(url)).length;
    const proxiedPosterUrls = posterUrls.filter((url) => /\/api\/v1\/weekly\/poster\//.test(url));
    report.probeData = {
      loadTiming,
      loading: data.loading,
      error: data.error || "",
      cacheNotice: data.cacheNotice || "",
      itemCount: effectiveItemCount,
      totalItems: data.totalItems,
      dateFilterKeys,
      posterUrlSamples: posterUrls.slice(0, 5),
      posterFileIdSamples: posterFileIds.slice(0, 5),
      internalPosterFileIdCount,
      internalPosterSourceFileIdCount,
      cloudbaseTempPosterCount,
      publicWechatPosterCount,
      proxiedPosterCount: proxiedPosterUrls.length,
    };
    fs.writeFileSync(path.join(artifactDir, "partial-report.json"), JSON.stringify(report, null, 2), "utf8");

    assert.ok(effectiveItemCount >= expectedMinItems, `expected at least ${expectedMinItems} current items, got ${effectiveItemCount}`);
    assert.ok(Number(data.totalItems || 0) >= expectedMinItems, `expected totalItems >= ${expectedMinItems}, got ${data.totalItems}`);
    const cacheNotice = data.cacheNotice || "";
    assert.notEqual(cacheNotice, data.t.loadingCachedNotice, "current package render must not show cached-data notice");
    assert.notEqual(cacheNotice, data.t.loadingOfflineNotice, "current package render must not show bundled-snapshot notice");
    for (const date of forbiddenDates) {
      assert.equal(dateFilterKeys.includes(date), false, `current package date filters must not include ${date}`);
    }
    for (const date of datesToExpect) {
      assert.ok(dateFilterKeys.includes(date), `expected ${date} in rendered date filters, got ${dateFilterKeys.join(",")}`);
    }
    assert.ok(popularItems.length > 0, "expected rendered poster recommendation items");
    assert.ok(posterCount > 0, `expected at least one rendered poster coverUrl, got ${posterCount}/${popularItems.length}`);
    assert.ok(posterCount >= Math.min(8, popularItems.length), `expected rendered poster coverUrl values, got ${posterCount}/${popularItems.length}`);
    assert.equal(proxiedPosterUrls.length, 0, `poster images must not use public proxy: ${proxiedPosterUrls.slice(0, 3).join(",")}`);
    if (expectPosterFileId) {
      assert.equal(publicWechatPosterCount, 0, `poster images must not use public WeChat CDN URLs, got ${publicWechatPosterCount}`);
      assert.ok(
        internalPosterSourceFileIdCount >= Math.min(8, posterCount),
        `expected first-screen posters to retain internal CloudBase file IDs, got ${internalPosterSourceFileIdCount}/${posterCount}`,
      );
    } else {
      assert.ok(
        directTencentPosterCount >= Math.min(8, posterCount),
        `expected first-screen posters to use direct Tencent data package URLs, got ${directTencentPosterCount}/${posterCount}`,
      );
    }
    const imageState = await waitForPosterImageState(miniProgram, page, expectedMinPosterImageLoads, 30000);
    assert.ok(
      imageState.posterImageLoadCount >= expectedMinPosterImageLoads,
      `expected at least ${expectedMinPosterImageLoads} poster image load event(s), got ${imageState.posterImageLoadCount}`,
    );
    assert.equal(
      imageState.posterImageErrorCount,
      0,
      `expected no poster image load errors, got ${imageState.posterImageErrorCount}: ${imageState.posterImageErrorUrls.join(",")}`,
    );

    await withTimeout(miniProgram.evaluate(() => {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      page.chooseThisWeekend();
      return { invoked: true };
    }), 10000, "choose this weekend");
    await page.waitFor(250);
    const weekendData = await waitForIdle(miniProgram, page, "this-weekend home", 45000);
    const weekendItems = effectiveFeedItems(weekendData);
    const weekendSelection = {
      mode: weekendData.dateMode,
      exactDate: weekendData.selectedDate,
      startKey: weekendData.selectedDateStart,
      endKey: weekendData.selectedDateEnd,
    };
    assert.equal(weekendSelection.mode, "this_weekend", "this-weekend handler must retain range mode");
    assert.equal(weekendSelection.exactDate, "", "this-weekend handler must not collapse to scalar Friday");
    assert.match(weekendSelection.startKey, /^\d{4}-\d{2}-\d{2}$/);
    assert.match(weekendSelection.endKey, /^\d{4}-\d{2}-\d{2}$/);
    const weekendStart = dateFromKey(weekendSelection.startKey);
    const weekendEnd = dateFromKey(weekendSelection.endKey);
    assert.equal(weekendStart && weekendStart.getUTCDay(), 5, "weekend range must start on Friday");
    assert.equal(weekendEnd && weekendEnd.getUTCDay(), 0, "weekend range must end on Sunday");
    assert.equal(
      filterItemsByDateSelection(weekendItems, weekendSelection).length,
      weekendItems.length,
      "rendered weekend feed must contain only Friday-through-Sunday items",
    );
    assert.ok(weekendItems.length > 0, "this-weekend feed must render at least one activity");

    const cityFacet = (weekendData.cityFilters || []).find((entry) => entry && entry.key === interactionCityKey);
    assert.ok(cityFacet, `expected ${interactionCityKey} in weekend city facets`);
    const expectedCityCount = filterItemsByCityKey(weekendItems, interactionCityKey).length;
    assert.equal(Number(cityFacet.count), expectedCityCount, "weekend city facet must count the same visible universe");
    assert.ok(expectedCityCount > 0, `expected at least one ${interactionCityKey} weekend activity`);

    await withTimeout(miniProgram.evaluate((cityKey) => {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      page.chooseDraftCity({ currentTarget: { dataset: { key: cityKey } } });
      return { invoked: true };
    }, interactionCityKey), 10000, "choose weekend city");
    await page.waitFor(250);
    const weekendCityData = await waitForIdle(miniProgram, page, "this-weekend city home", 45000);
    const weekendCityItems = effectiveFeedItems(weekendCityData);
    assert.equal(weekendCityData.selectedCity, interactionCityKey);
    assert.equal(weekendCityData.dateMode, weekendSelection.mode, "city switch must preserve weekend mode");
    assert.equal(weekendCityData.selectedDateStart, weekendSelection.startKey, "city switch must preserve Friday");
    assert.equal(weekendCityData.selectedDateEnd, weekendSelection.endKey, "city switch must preserve Sunday");
    assert.equal(weekendCityItems.length, expectedCityCount, "city facet count and rendered city feed must match");
    assert.equal(
      filterItemsByCityKey(weekendCityItems, interactionCityKey).length,
      weekendCityItems.length,
      "rendered city feed must contain only the selected city",
    );
    assert.equal(Number(weekendCityData.totalItems), weekendCityItems.length, "city total and visible feed must match");
    assert.equal(
      filterItemsByCityKey(weekendCityData.popularItems || [], interactionCityKey).length,
      (weekendCityData.popularItems || []).length,
      "poster carousel must use the same selected-city universe",
    );
    report.weekendInteraction = {
      selection: weekendSelection,
      nationwideCount: weekendItems.length,
      cityKey: interactionCityKey,
      cityFacetCount: Number(cityFacet.count),
      cityFeedCount: weekendCityItems.length,
      cityTotalItems: Number(weekendCityData.totalItems),
      cityPosterCount: (weekendCityData.popularItems || []).length,
    };

    report.steps.push({
      name: "current package renders current/future data without snapshot",
      pageElapsedMs,
      wallElapsedMs,
      itemCount: effectiveItemCount,
      totalItems: data.totalItems,
      itemDateCount: itemDates.length,
      itemDates: itemDates.slice(0, 20),
      expectedDatesEffective: datesToExpect,
      dateFilterCount: dateFilterKeys.length,
      dateFilterKeys: dateFilterKeys.slice(0, 40),
      popularItemCount: popularItems.length,
      posterCoverCount: posterCount,
      directTencentPosterCount,
      publicWechatPosterCount,
      internalPosterFileIdCount,
      internalPosterSourceFileIdCount,
      cloudbaseTempPosterCount,
      proxiedPosterCount: proxiedPosterUrls.length,
      posterUrlSamples: posterUrls.slice(0, 5),
      posterFileIdSamples: posterFileIds.slice(0, 5),
      posterImageLoadCount: imageState.posterImageLoadCount,
      posterImageErrorCount: imageState.posterImageErrorCount,
      posterImageLoadedIds: imageState.posterImageLoadedIds,
      posterImageErrorUrls: imageState.posterImageErrorUrls,
      cacheNotice: data.cacheNotice || "",
    });
    report.consoleCount = consoleMessages.length;
    report.exceptions = exceptions;
    assert.deepEqual(exceptions, [], "DevTools reported runtime exceptions");
    fs.writeFileSync(path.join(artifactDir, "report.json"), JSON.stringify(report, null, 2), "utf8");
    console.log(JSON.stringify(report, null, 2));
  } finally {
    if (miniProgram) {
      try {
        await withTimeout(miniProgram.evaluate(() => {
          const app = getApp();
          const probe = app.globalData.__currentPackageRenderedProbe;
          if (probe && probe.originalCloud) {
            const cloud = app.globalData.cloud;
            Object.keys(cloud).forEach((key) => {
              if (!Object.prototype.hasOwnProperty.call(probe.originalCloud, key)) delete cloud[key];
            });
            Object.assign(cloud, probe.originalCloud);
          }
          delete app.globalData.__currentPackageRenderedProbe;
        }), 10000, "restore current-package probe");
        if (noCloseDevTools) {
          miniProgram.disconnect();
        } else {
          await withTimeout(miniProgram.close(), 15000, "miniProgram.close");
        }
      } catch (error) {
        miniProgram.disconnect();
      }
    }
    if (staticServer) {
      await staticServer.close();
    }
  }
}

run().catch((error) => {
  const failure = {
    wsEndpoint,
    launchMode,
    launchPort,
    idePort,
    artifactDir,
    error: error && error.stack ? error.stack : String(error),
  };
  fs.writeFileSync(path.join(artifactDir, "failure.json"), JSON.stringify(failure, null, 2), "utf8");
  console.error(JSON.stringify(failure, null, 2));
  process.exit(1);
});
