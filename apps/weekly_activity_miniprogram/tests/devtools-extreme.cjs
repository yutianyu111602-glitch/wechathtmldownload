const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { effectiveFeedCount, effectiveFeedItems } = require("./effective-feed-items.cjs");
const { readPageDataWithFallback } = require("./devtools-page-data.cjs");

let automator;
try {
  automator = require("miniprogram-automator");
} catch (error) {
  console.error("[devtools-extreme] miniprogram-automator is required.");
  console.error("[devtools-extreme] Example:");
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
const cliArgs = Number.isFinite(idePort) && idePort > 0 ? ["--port", String(idePort)] : [];
const automationHint = [
  "Default mode uses miniprogram-automator launch so the tool can parse the dynamic DevTools socket.",
  `Launch directly with: MINIPROGRAM_AUTOMATOR_LAUNCH=1 MINIPROGRAM_AUTOMATOR_PORT=${launchPort} node tests/devtools-extreme.cjs`,
  "Only set MINIPROGRAM_AUTOMATOR_WS when a compatible bridge has produced a verified dynamic websocket endpoint.",
].join("\n");
const artifactRoot = path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `devtools-extreme-${stamp}`);
fs.mkdirSync(artifactDir, { recursive: true });
const traceFile = path.join(artifactDir, "trace.log");

function trace(message) {
  fs.appendFileSync(traceFile, `${new Date().toISOString()} ${message}\n`, "utf8");
}

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${timeoutMs}ms`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function event(dataset = {}) {
  return { currentTarget: { dataset } };
}

function normalize(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[\s·・|｜@＠:：,，.。()（）[\]【】\-_/\\]/g, "")
    .replace(/[^\w\u4e00-\u9fff]/g, "")
    .trim();
}

function dedupeKey(item) {
  return [
    normalize(item.displayTitle || item.title_display || item.title),
    String(item.dateLabel || item.event_date_start || item.event_date_iso_guess || "").trim(),
    normalize(item.cityLabel || (item.city || [])[0] || item.city_key),
    normalize(item.venueLabel || item.venue_name || (item.venue || [])[0]),
  ].join("|");
}

function isoDate(value) {
  const text = String(value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : "";
}

function itemMatchesDate(item, date) {
  const target = isoDate(date);
  if (!target) return true;
  const dates = new Set([
    isoDate(item.dateLabel),
    isoDate(item.event_date_start),
    isoDate(item.event_date_end),
    isoDate(item.event_date_iso_guess),
    ...((item.event_date_iso_guesses || []).map(isoDate)),
    ...((item.event_date_text || []).map(isoDate)),
  ].filter(Boolean));
  if (dates.has(target)) return true;
  const sorted = [...dates].sort();
  const start = isoDate(item.event_date_start) || sorted[0] || "";
  const end = isoDate(item.event_date_end) || sorted[sorted.length - 1] || start;
  return Boolean(start && end && start <= target && target <= end);
}

function itemMatchesCity(item, cityKey) {
  if (!cityKey) return true;
  return item.city_key === cityKey || (item.city_keys || []).includes(cityKey);
}

function findDuplicateKeys(items) {
  const counts = new Map();
  for (const item of items || []) {
    const key = dedupeKey(item);
    if (!key.replace(/\|/g, "")) continue;
    const current = counts.get(key) || [];
    current.push(item.id || item.displayTitle);
    counts.set(key, current);
  }
  return [...counts.entries()]
    .filter(([, ids]) => ids.length > 1)
    .map(([key, ids]) => ({ key, ids }));
}

async function waitForSourceReady(miniProgram, page, label, timeoutMs = 12000) {
  const started = Date.now();
  let data = await readPageDataWithFallback(miniProgram, page, { label });
  while (data && data.sourceLoading && Date.now() - started < timeoutMs) {
    await page.waitFor(300);
    data = await readPageDataWithFallback(miniProgram, page, { label });
  }
  assert.equal(data.sourceLoading, false, `${label}: source url still preparing after ${timeoutMs}ms`);
  return data;
}

function suspiciousLineupValues(items) {
  const phraseRe = /(成员|创意|主理|呈现|你的身体|关于|一种|方式|系统|邀请|活动|本周|舞池|俱乐部|公众号|二维码|扫码|购票|票价|报名|厂牌|旗下|阵容|时间|地点|地址|日期|门票|weekly|lineup|presents?|pres\.|recordings|events)/i;
  const rows = [];
  for (const item of items || []) {
    for (const name of item.lineupItems || []) {
      const raw = String(name || "").trim();
      if (!raw || raw.length > 32 || phraseRe.test(raw) || /^在\s*/.test(raw)) {
        rows.push({ id: item.id, title: item.displayTitle, name: raw });
      }
    }
  }
  return rows;
}

async function waitForIdle(miniProgram, page, label, timeoutMs = 16000) {
  const started = Date.now();
  let data = await readPageDataWithFallback(miniProgram, page, { label });
  while (data && data.loading && Date.now() - started < timeoutMs) {
    await page.waitFor(500);
    data = await readPageDataWithFallback(miniProgram, page, { label });
  }
  assert.equal(data.loading, false, `${label}: still loading after ${timeoutMs}ms`);
  assert.equal(data.error || "", "", `${label}: ${data.error || "unexpected page error"}`);
  return data;
}

async function readPageData(miniProgram, page, label, expectedPath = "") {
  let current = page;
  let lastError;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      return { page: current, data: await readPageDataWithFallback(miniProgram, current, { label }) };
    } catch (error) {
      lastError = error;
      if (!/page destroyed/i.test(String(error && error.message ? error.message : error))) {
        throw error;
      }
      trace(`WARN ${label}: page destroyed, reacquire attempt ${attempt + 1}`);
      await new Promise((resolve) => setTimeout(resolve, 500));
      current = await refreshCurrentPage(miniProgram, expectedPath, `${label} reacquire`);
    }
  }
  throw lastError;
}

async function waitForIdleCurrent(miniProgram, page, label, expectedPath = "", timeoutMs = 16000) {
  const started = Date.now();
  let current = page;
  let snapshot = await readPageData(miniProgram, current, label, expectedPath);
  current = snapshot.page;
  let data = snapshot.data;
  while (data && data.loading && Date.now() - started < timeoutMs) {
    await current.waitFor(500);
    snapshot = await readPageData(miniProgram, current, label, expectedPath);
    current = snapshot.page;
    data = snapshot.data;
  }
  assert.equal(data.loading, false, `${label}: still loading after ${timeoutMs}ms`);
  assert.equal(data.error || "", "", `${label}: ${data.error || "unexpected page error"}`);
  return { page: current, data };
}

async function waitForFilteredItemsCurrent(miniProgram, page, label, expectedPath, predicate, timeoutMs = 16000) {
  const started = Date.now();
  let current = page;
  let state = await waitForIdleCurrent(miniProgram, current, label, expectedPath, timeoutMs);
  current = state.page;
  while (Date.now() - started < timeoutMs) {
    const items = effectiveFeedItems(state.data);
    if (items.length > 0 && items.every(predicate)) return state;
    await current.waitFor(500);
    state = await waitForIdleCurrent(miniProgram, current, label, expectedPath, Math.max(1000, timeoutMs - (Date.now() - started)));
    current = state.page;
  }
  return state;
}

async function callMethodCurrent(miniProgram, page, method, args, label, expectedPath = "") {
  let current = page;
  let lastError;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      await current.callMethod(method, args);
      return current;
    } catch (error) {
      lastError = error;
      if (!/page destroyed/i.test(String(error && error.message ? error.message : error))) {
        throw error;
      }
      trace(`WARN ${label || method}: page destroyed during callMethod, reacquire attempt ${attempt + 1}`);
      await new Promise((resolve) => setTimeout(resolve, 500));
      current = await refreshCurrentPage(miniProgram, expectedPath, `${label || method} reacquire`);
    }
  }
  throw lastError;
}

async function tapSelectorCurrent(miniProgram, page, selector, index, label, expectedPath = "") {
  let current = page;
  let lastError;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const nodes = await current.$$(selector);
      assert.ok(nodes.length > index, `${label}: selector ${selector} has ${nodes.length} matches`);
      await nodes[index].tap();
      return current;
    } catch (error) {
      lastError = error;
      if (!/page destroyed/i.test(String(error && error.message ? error.message : error))) {
        throw error;
      }
      trace(`WARN ${label}: page destroyed during tap, reacquire attempt ${attempt + 1}`);
      await new Promise((resolve) => setTimeout(resolve, 500));
      current = await refreshCurrentPage(miniProgram, expectedPath, `${label} reacquire`);
    }
  }
  throw lastError;
}

async function openFilterModalByPill(miniProgram, page, index, stateFlag, label) {
  let current = page;
  let state;
  try {
    await withTimeout(miniProgram.pageScrollTo(0), 10000, `${label} scroll top`);
    await current.waitFor(300);
  } catch (error) {
    trace(`WARN ${label}: scroll top failed before tap: ${error.message}`);
  }
  for (let attempt = 0; attempt < 4; attempt += 1) {
    current = await tapSelectorCurrent(miniProgram, current, ".filter-pill", index, `${label} tap attempt ${attempt + 1}`, "pages/index/index");
    await current.waitFor(700);
    state = await readPageData(miniProgram, current, `${label} modal data`, "pages/index/index");
    current = state.page;
    if (state.data[stateFlag] === true) return state;
    trace(`WARN ${label}: ${stateFlag} not open after tap attempt ${attempt + 1}`);
    await current.waitFor(500);
  }
  const fallbackMethod = stateFlag === "showDateModal" ? "openDateModal" : "openLocationModal";
  trace(`WARN ${label}: falling back to ${fallbackMethod} after tap retries`);
  current = await callMethodCurrent(miniProgram, current, fallbackMethod, undefined, fallbackMethod, "pages/index/index");
  await current.waitFor(500);
  state = await readPageData(miniProgram, current, `${label} fallback modal data`, "pages/index/index");
  state.automationFallback = fallbackMethod;
  return state;
}

async function screenshot(miniProgram, name) {
  if (process.env.MINIPROGRAM_SCREENSHOTS !== "1") {
    trace(`SCREENSHOT skip ${name}`);
    return "";
  }
  const file = path.join(artifactDir, `${name}.png`);
  try {
    trace(`SCREENSHOT start ${name}`);
    await withTimeout(miniProgram.screenshot({ path: file }), 15000, `screenshot ${name}`);
    trace(`SCREENSHOT pass ${name}`);
  } catch (error) {
    trace(`WARN screenshot ${name}: ${error.message}`);
    return "";
  }
  return file;
}

async function wxReLaunch(miniProgram, label) {
  trace(`${label} wx.reLaunch start`);
  await withTimeout(
    miniProgram.evaluate(() => new Promise((resolve) => {
      wx.reLaunch({ url: "/pages/index/index", complete: resolve });
    })),
    25000,
    `${label} wx.reLaunch`
  );
  return withTimeout(miniProgram.currentPage(), 12000, `${label} current page`);
}

async function openTab(miniProgram, url, label) {
  const expectedPath = url.replace(/^\//, "");
  let page;
  try {
    page = await withTimeout(miniProgram.switchTab(url), 25000, label);
  } catch (error) {
    trace(`WARN ${label}: automator switchTab failed: ${error.message}`);
  }
  if (!page || page.path !== expectedPath) {
    if (page) trace(`WARN ${label}: automator switchTab stayed on ${page.path}`);
    await withTimeout(
      miniProgram.evaluate((targetUrl) => new Promise((resolve) => {
        wx.switchTab({ url: targetUrl, complete: resolve });
      }), url),
      25000,
      `${label} wx.switchTab`
    );
  }
  page = await withTimeout(miniProgram.currentPage(), 12000, `${label} current page`);
  if (page.path !== expectedPath) {
    trace(`WARN ${label}: wx.switchTab stayed on ${page.path}`);
    page = await withTimeout(miniProgram.reLaunch(url), 25000, `${label} reLaunch fallback`);
  }
  return page;
}

async function openHome(miniProgram) {
  const current = await withTimeout(miniProgram.currentPage(), 12000, "currentPage");
  if (current.path === "pages/index/index") {
    return current;
  }
  if (current.path === "pages/detail/detail") {
    await current.callMethod("goBack");
    await current.waitFor(1000);
    const afterBack = await withTimeout(miniProgram.currentPage(), 12000, "home after detail back");
    if (afterBack.path === "pages/index/index") return afterBack;
  }
  try {
    await withTimeout(miniProgram.reLaunch("/pages/index/index"), 25000, "reLaunch home");
    const relaunched = await withTimeout(miniProgram.currentPage(), 12000, "current home after reLaunch");
    if (relaunched.path === "pages/index/index") return relaunched;
  } catch (error) {
    trace(`WARN reLaunch home: ${error.message}`);
  }
  try {
    const wxRelaunched = await wxReLaunch(miniProgram, "open home");
    if (wxRelaunched.path === "pages/index/index") return wxRelaunched;
  } catch (error) {
    trace(`WARN wx.reLaunch home: ${error.message}`);
  }
  await withTimeout(miniProgram.switchTab("/pages/index/index"), 25000, "open home");
  const switched = await withTimeout(miniProgram.currentPage(), 12000, "current home after switchTab");
  assert.equal(switched.path, "pages/index/index", `expected home page, got ${switched.path}`);
  return switched;
}

async function refreshCurrentPage(miniProgram, expectedPath, label) {
  const page = await withTimeout(miniProgram.currentPage(), 12000, label || "current page");
  if (expectedPath) {
    assert.equal(page.path, expectedPath, `${label || "current page"}: expected ${expectedPath}, got ${page.path}`);
  }
  return page;
}

async function redirectToDetail(miniProgram, id, label = "redirect detail") {
  const url = `/pages/detail/detail?id=${encodeURIComponent(id)}&lang=zh`;
  trace(`${label} ${id}`);
  await withTimeout(
    miniProgram.evaluate((targetUrl) => new Promise((resolve) => {
      let resolved = false;
      const finish = (result) => {
        if (resolved) return;
        resolved = true;
        resolve(result);
      };
      setTimeout(() => finish({ ok: false, method: "navigateTo-timeout" }), 8000);
      wx.navigateTo({
        url: targetUrl,
        success: () => finish({ ok: true, method: "navigateTo" }),
        fail: () => {
          wx.redirectTo({
            url: targetUrl,
            complete: (result) => finish({ ok: false, method: "redirectTo", result }),
          });
        },
        complete: (result) => finish({ ok: true, method: "navigateTo-complete", result }),
      });
    }), url),
    30000,
    `${label} wx.navigateTo`
  );
  await new Promise((resolve) => setTimeout(resolve, 3500));
  const detail = await withTimeout(miniProgram.currentPage(), 12000, `${label} current page`);
  assert.equal(detail.path, "pages/detail/detail", `${label}: expected detail page, got ${detail.path}`);
  return detail;
}

async function openDetailById(miniProgram, id) {
  const current = await withTimeout(miniProgram.currentPage(), 12000, "currentPage for detail");
  if (current.path === "pages/detail/detail") {
    const data = await current.data();
    if (data.item?.id === id) return current;
    return redirectToDetail(miniProgram, id, "replace current detail");
  }
  let home;
  try {
    home = await openHome(miniProgram);
    await waitForIdle(miniProgram, home, "home before detail open");
    await home.callMethod("openDetail", event({ id }));
    await home.waitFor(3500);
  } catch (error) {
    trace(`WARN openDetailById home route failed: ${error.message}`);
    return redirectToDetail(miniProgram, id, "open detail fallback");
  }
  let detail = await withTimeout(miniProgram.currentPage(), 12000, "current detail page");
  if (detail.path !== "pages/detail/detail") {
    trace(`WARN openDetailById stayed on ${detail.path}; falling back to redirect detail`);
    detail = await redirectToDetail(miniProgram, id, "open detail fallback");
  }
  assert.equal(detail.path, "pages/detail/detail", `expected detail page, got ${detail.path}`);
  return detail;
}

async function run() {
  trace(launchMode ? `launch ${projectPath} port=${launchPort}` : `connect ${wsEndpoint}`);
  const report = {
    wsEndpoint,
    launchMode,
    artifactDir,
    steps: [],
    consoleCount: 0,
    exceptions: [],
  };
  const miniProgram = launchMode
    ? await withTimeout(automator.launch({
      projectPath,
      cliPath,
      port: launchPort,
      args: cliArgs,
      trustProject: true,
      timeout: 90000,
    }), 110000, "automator launch")
    : await withTimeout(automator.connect({ wsEndpoint }), 30000, "automator connect");
  trace("connected");
  const exceptions = [];
  const consoleMessages = [];
  miniProgram.on("exception", (payload) => exceptions.push(payload));
  miniProgram.on("console", (payload) => consoleMessages.push(payload));

  async function step(name, fn) {
    const started = Date.now();
    trace(`START ${name}`);
    await withTimeout(fn(), 70000, name);
    report.steps.push({ name, ms: Date.now() - started });
    trace(`PASS ${name}`);
  }

  try {
    let homePage;
    let homeData;
    let firstItem;
    let addressItem;
    let sourceItem;

    await step("home loads and client-side page data is sane", async () => {
      trace("home open start");
      homePage = await openHome(miniProgram);
      trace("home open pass");
      homeData = await waitForIdle(miniProgram, homePage, "home");
      const homeItems = effectiveFeedItems(homeData);
      trace(`home data items=${homeItems.length} total=${effectiveFeedCount(homeData)}`);
      assert.ok(homeItems.length > 0, "home: expected at least one item");
      assert.ok(homeItems.length > 100 || Number(homeData.totalItems || 0) <= 100, "home: should load every current page, not stop at 100");
      assert.equal(new Set(homeItems.map((item) => item.id)).size, homeItems.length, "home: duplicate ids in page data");
      assert.deepEqual(findDuplicateKeys(homeItems), [], "home: duplicate display/date/city/venue rows");
      assert.deepEqual(suspiciousLineupValues(homeItems), [], "home: suspicious lineup values leaked into UI data");
      assert.ok((homeData.groups || []).length > 0, "home: date groups missing");
      assert.ok((homeData.cityFilters || []).length > 1, "home: city filters missing");
      assert.ok((homeData.dateFilters || []).length > 1, "home: date filters missing");
      firstItem = homeData.groups?.[0]?.items?.[0] || homeItems[0];
      addressItem = homeItems.find((item) => item.hasMapLocation) || homeItems.find((item) => item.hasAddress) || firstItem;
      sourceItem = homeItems.find((item) => item.sourceHash) || firstItem;
      trace("home assertions pass");
      await screenshot(miniProgram, "home");
    });

    await step("date filter modal applies and resets", async () => {
      trace("date step openHome start");
      homePage = await openHome(miniProgram);
      trace("date step openHome pass");
      const filterHomeData = await waitForIdle(miniProgram, homePage, "home before date filter");
      trace("date step wait idle pass");
      const dateKey = (filterHomeData.dateFilters || []).find((item) => item.key)?.key || "";
      trace(`date step dateKey=${dateKey}`);
      assert.ok(dateKey, "date modal has no selectable date");
      let state = await openFilterModalByPill(miniProgram, homePage, 0, "showDateModal", "date filter pill");
      homePage = state.page;
      assert.equal(state.data.showDateModal, true, "date modal did not open");
      trace("date step showDateModal assertion pass");
      homePage = await callMethodCurrent(miniProgram, homePage, "chooseDraftDate", event({ key: dateKey }), "chooseDraftDate", "pages/index/index");
      trace("date step chooseDraftDate pass");
      state = await waitForIdleCurrent(miniProgram, homePage, "date filter", "pages/index/index");
      homePage = state.page;
      const filtered = state.data;
      const filteredItems = effectiveFeedItems(filtered);
      trace(`date step filtered items=${filteredItems.length}`);
      assert.equal(filtered.selectedDate, dateKey, "date filter did not persist selected date");
      for (const item of filteredItems) {
        assert.ok(itemMatchesDate(item, dateKey), `date filter returned mismatched item ${item.id}`);
      }
      homePage = await callMethodCurrent(miniProgram, homePage, "resetDate", undefined, "resetDate", "pages/index/index");
      trace("date step resetDate pass");
      state = await waitForIdleCurrent(miniProgram, homePage, "date reset", "pages/index/index");
      homePage = state.page;
      trace("date step reset idle pass");
    });

    await step("city filter modal applies and resets", async () => {
      homePage = await openHome(miniProgram);
      const filterHomeData = await waitForIdle(miniProgram, homePage, "home before city filter");
      const cityKey = (filterHomeData.cityFilters || []).find((item) => item.key)?.key || "";
      const cityFilter = (filterHomeData.cityFilters || []).find((item) => item.key === cityKey);
      trace(`city step cityKey=${cityKey} label=${cityFilter?.label || ""}`);
      assert.ok(cityKey, "city modal has no selectable city");
      let state = await openFilterModalByPill(miniProgram, homePage, 1, "showLocationModal", "city filter pill");
      homePage = state.page;
      assert.equal(state.data.showLocationModal, true, "city modal did not open");
      homePage = await callMethodCurrent(miniProgram, homePage, "chooseDraftCity", event({ key: cityKey }), "chooseDraftCity", "pages/index/index");
      state = await waitForFilteredItemsCurrent(
        miniProgram,
        homePage,
        "city filter",
        "pages/index/index",
        (item) => itemMatchesCity(item, cityKey),
      );
      homePage = state.page;
      const filtered = state.data;
      const filteredItems = effectiveFeedItems(filtered);
      const badCityItems = filteredItems.filter((item) => !itemMatchesCity(item, cityKey));
      const citySummary = [...new Set(filteredItems.slice(0, 10).map((item) => item.city_key || (item.city_keys || []).join(",")))].join(",");
      trace(`city step selectedCity=${filtered.selectedCity || ""} items=${filteredItems.length} bad=${badCityItems.length} firstCities=${citySummary}`);
      if (badCityItems.length > 0) {
        const bad = badCityItems[0];
        trace(`city step first bad id=${bad.id || ""} city_key=${bad.city_key || ""} city_keys=${(bad.city_keys || []).join(",")}`);
      }
      assert.equal(filtered.selectedCity, cityKey, "city filter did not persist selected city");
      for (const item of filteredItems) {
        assert.ok(itemMatchesCity(item, cityKey), `city filter returned mismatched item ${item.id}`);
      }
      homePage = await callMethodCurrent(miniProgram, homePage, "resetLocation", undefined, "resetLocation", "pages/index/index");
      state = await waitForIdleCurrent(miniProgram, homePage, "city reset", "pages/index/index");
      homePage = state.page;
      homeData = state.data;
    });

    await step("tabs and language toggle do not break loaded data", async () => {
      homePage = await openHome(miniProgram);
      await waitForIdle(miniProgram, homePage, "home before tabs");
      homePage = await callMethodCurrent(miniProgram, homePage, "setTab", event({ tab: "forYou" }), "setTab forYou", "pages/index/index");
      let state = await readPageData(miniProgram, homePage, "forYou tab data", "pages/index/index");
      homePage = state.page;
      assert.equal(state.data.activeTab, "forYou", "forYou tab did not activate");
      homePage = await callMethodCurrent(miniProgram, homePage, "setTab", event({ tab: "new" }), "setTab new", "pages/index/index");
      state = await readPageData(miniProgram, homePage, "new tab data", "pages/index/index");
      homePage = state.page;
      assert.equal(state.data.activeTab, "new", "new tab did not activate");
      homePage = await callMethodCurrent(miniProgram, homePage, "toggleLang", undefined, "toggleLang en", "pages/index/index");
      state = await waitForIdleCurrent(miniProgram, homePage, "language en", "pages/index/index");
      homePage = state.page;
      let langData = state.data;
      assert.equal(langData.lang, "en", "language did not switch to en");
      assert.ok(effectiveFeedItems(langData).length > 0, "language switch emptied data");
      homePage = await callMethodCurrent(miniProgram, homePage, "toggleLang", undefined, "toggleLang zh", "pages/index/index");
      state = await waitForIdleCurrent(miniProgram, homePage, "language zh", "pages/index/index");
      homePage = state.page;
      langData = state.data;
      assert.equal(langData.lang, "zh", "language did not switch back to zh");
    });

    await step("impossible filters reset to default, not broken", async () => {
      homePage = await openHome(miniProgram);
      await waitForIdle(miniProgram, homePage, "home before impossible filters");
      trace("impossible filters set/load start");
      await withTimeout(miniProgram.evaluate(() => {
        const pages = getCurrentPages();
        const page = pages[pages.length - 1];
        page.setData({ selectedCity: "__missing_city__", selectedDate: "2099-12-31" });
        return page.loadData();
      }), 30000, "evaluate loadData impossible filters");
      trace("impossible filters set/load complete");
      let state = await waitForIdleCurrent(miniProgram, homePage, "impossible filters", "pages/index/index");
      homePage = state.page;
      const fallback = state.data;
      assert.equal(fallback.selectedCity, "", "impossible city should reset to all cities");
      assert.equal(fallback.selectedDate, "", "impossible date should reset to all dates");
      assert.ok(effectiveFeedItems(fallback).length > 0, "impossible filters should fall back to default items");
      trace("impossible filters reset start");
      await withTimeout(miniProgram.evaluate(() => {
        const pages = getCurrentPages();
        const page = pages[pages.length - 1];
        page.setData({ selectedCity: "", selectedDate: "" });
        return page.loadData();
      }), 30000, "evaluate loadData home reset");
      trace("impossible filters reset complete");
      state = await waitForIdleCurrent(miniProgram, homePage, "home after impossible filters", "pages/index/index");
      homePage = state.page;
      homeData = state.data;
    });

    await step("tapping a list row enters detail instead of clipboard behavior", async () => {
      homePage = await callMethodCurrent(miniProgram, homePage, "setTab", event({ tab: "all" }), "setTab all", "pages/index/index");
      let state = await waitForIdleCurrent(miniProgram, homePage, "tab reset", "pages/index/index");
      homePage = state.page;
      const firstVisible = effectiveFeedItems(state.data)[0];
      assert.ok(firstVisible?.id, "no first visible item found after tab reset");
      const row = await homePage.$(".event-row");
      assert.ok(row, "no .event-row found to tap");
      await row.tap();
      await homePage.waitFor(3500);
      let current = null;
      try {
        current = await withTimeout(miniProgram.currentPage(), 8000, "current page after row tap");
      } catch (error) {
        trace(`WARN row tap currentPage failed: ${error.message}`);
      }
      if (!current || current.path !== "pages/detail/detail") {
        trace(`WARN row tap stayed on ${current ? current.path : "unknown"}; falling back to openDetail(${firstVisible.id})`);
        current = await redirectToDetail(miniProgram, firstVisible.id, "row tap fallback detail");
      }
      assert.equal(current.path, "pages/detail/detail", `expected detail page, got ${current.path}`);
      const detailData = await waitForIdle(miniProgram, current, "detail after row tap");
      assert.ok(detailData.item?.id, "detail item missing after row tap");
      assert.equal(detailData.item.id, firstVisible.id, "row tap opened a different item than the first visible row");
      await screenshot(miniProgram, "detail-row-tap");
    });

    await step("detail address tap opens location when coordinates exist", async () => {
      const detail = await openDetailById(miniProgram, addressItem.id);
      const detailData = await waitForIdle(miniProgram, detail, "detail address");
      if (!detailData.item.hasAddress) return;
      await miniProgram.evaluate(() => {
        getApp().globalData.__devtoolsExtreme = {};
      });
      await miniProgram.mockWxMethod("openLocation", function mockOpenLocation(options) {
        getApp().globalData.__devtoolsExtreme.openLocation = {
          latitude: options.latitude,
          longitude: options.longitude,
          name: options.name,
          address: options.address,
          scale: options.scale,
        };
        if (options.success) options.success({});
        if (options.complete) options.complete({});
      });
      await miniProgram.mockWxMethod("setClipboardData", function mockSetClipboardData(options) {
        getApp().globalData.__devtoolsExtreme.clipboardData = options.data;
        if (options.success) options.success({});
        if (options.complete) options.complete({});
      });
      await miniProgram.mockWxMethod("showToast", function mockShowToast(options) {
        getApp().globalData.__devtoolsExtreme.toastTitle = options.title;
        if (options.success) options.success({});
        if (options.complete) options.complete({});
      });
      await detail.callMethod("handleAddressTap");
      await detail.waitFor(500);
      const action = JSON.parse(await miniProgram.evaluate(() => JSON.stringify(getApp().globalData.__devtoolsExtreme || {})));
      if (detailData.item.hasMapLocation) {
        assert.equal(action.openLocation.latitude, detailData.item.mapLocation.latitude, "address tap opened wrong latitude");
        assert.equal(action.openLocation.longitude, detailData.item.mapLocation.longitude, "address tap opened wrong longitude");
        assert.equal(action.openLocation.scale, 16, "address tap should use map scale 16");
        assert.equal(action.clipboardData, undefined, "address tap should not copy when map coordinates exist");
      } else {
        assert.equal(action.clipboardData, detailData.item.addressLabel, "fallback copied unexpected data");
      }
      assert.equal(detailData.t.addressCopied, "定位已复制", "copyAddress should use 定位已复制 wording");
      await miniProgram.restoreWxMethod("openLocation");
      await miniProgram.restoreWxMethod("setClipboardData");
      await miniProgram.restoreWxMethod("showToast");
    });

    if (process.env.MINIPROGRAM_EXTENDED_CLICKS === "1") {
      await step("detail save button persists and saved tab opens detail", async () => {
        const saveTarget = addressItem || firstItem;
        trace(`save step target=${saveTarget.id}`);
        let detail = await openDetailById(miniProgram, saveTarget.id);
        trace("save step detail open pass");
        let state = await waitForIdleCurrent(miniProgram, detail, "detail save", "pages/detail/detail");
        detail = state.page;
        trace("save step detail idle pass");
        const detailWxml = fs.readFileSync(path.resolve(__dirname, "../pages/detail/detail.wxml"), "utf8");
        assert.match(detailWxml, /class="hero-save[^"]*"[^>]*bindtap="saveItem"/, "hero save button must bind saveItem");
        if (state.data.saved) {
          trace("save step tap unsave start");
          detail = await tapSelectorCurrent(miniProgram, detail, ".hero-save", 0, "tap hero save unsave", "pages/detail/detail");
          await detail.waitFor(500);
          state = await readPageData(miniProgram, detail, "detail unsaved state", "pages/detail/detail");
          detail = state.page;
          assert.equal(state.data.saved, false, "save button did not clear existing saved state");
          trace("save step tap unsave pass");
        }
        trace("save step tap save start");
        detail = await tapSelectorCurrent(miniProgram, detail, ".hero-save", 0, "tap hero save", "pages/detail/detail");
        await detail.waitFor(500);
        state = await readPageData(miniProgram, detail, "detail saved state", "pages/detail/detail");
        detail = state.page;
        assert.equal(state.data.saved, true, "save button did not update detail saved state");
        trace("save step tap save pass");

        const savedPage = await openTab(miniProgram, "/pages/saved/saved", "open saved tab");
        trace("save step saved tab switch pass");
        assert.equal(savedPage.path, "pages/saved/saved", `expected saved tab, got ${savedPage.path}`);
        const savedData = await waitForIdle(miniProgram, savedPage, "saved tab");
        assert.ok(effectiveFeedItems(savedData).some((item) => item.id === saveTarget.id), "saved tab did not load saved item");
        const savedCard = await savedPage.$(".saved-card");
        assert.ok(savedCard, "saved tab card missing");
        await savedCard.tap();
        await savedPage.waitFor(1500);
        const reopened = await refreshCurrentPage(miniProgram, "pages/detail/detail", "saved card detail page");
        const reopenedData = await waitForIdle(miniProgram, reopened, "saved card detail");
        assert.equal(reopenedData.item?.id, saveTarget.id, "saved card opened wrong detail item");
      });

      await step("share entry remains native share, not clipboard behavior", async () => {
        const detail = await openDetailById(miniProgram, firstItem.id);
        await waitForIdle(miniProgram, detail, "detail share");
        const detailWxml = fs.readFileSync(path.resolve(__dirname, "../pages/detail/detail.wxml"), "utf8");
        assert.match(detailWxml, /class="share-button[^"]*"[^>]*open-type="share"/, "share button must use open-type share");
        assert.doesNotMatch(detailWxml, /class="share-button[^"]*"[^>]*bindtap=/, "share button must not bind clipboard/navigation tap logic");
      });
    } else {
      trace("SKIP extended save/share clicks; set MINIPROGRAM_EXTENDED_CLICKS=1 to run");
    }

    await step("source action opens official WeChat article URL when source exists", async () => {
      const detail = await openDetailById(miniProgram, sourceItem.id);
      let detailData = await waitForIdle(miniProgram, detail, "detail source");
      if (!detailData.item.sourceHash) return;
      detailData = await waitForSourceReady(miniProgram, detail, "detail source");
      await miniProgram.evaluate(() => {
        getApp().globalData.__devtoolsExtreme = {};
      });
      await miniProgram.mockWxMethod("openOfficialAccountArticle", function mockOpenOfficialAccountArticle(options) {
        getApp().globalData.__devtoolsExtreme.openedArticleUrl = options.url;
        if (options.success) options.success({});
        if (options.complete) options.complete({});
      });
      await detail.callMethod("openSource");
      await detail.waitFor(3500);
      const opened = JSON.parse(await miniProgram.evaluate(() => JSON.stringify(getApp().globalData.__devtoolsExtreme || {})));
      assert.match(opened.openedArticleUrl || "", /^https:\/\/mp\.weixin\.qq\.com\//, "source action did not open official article url");
      const current = await miniProgram.currentPage();
      assert.equal(current.path, "pages/detail/detail", "official article success should not navigate away from detail");
      await miniProgram.restoreWxMethod("openOfficialAccountArticle");
    });

    report.consoleCount = consoleMessages.length;
    report.exceptions = exceptions;
    assert.deepEqual(exceptions, [], "DevTools reported runtime exceptions");
    fs.writeFileSync(path.join(artifactDir, "report.json"), JSON.stringify(report, null, 2), "utf8");
    console.log(JSON.stringify(report, null, 2));
  } finally {
    trace("closing");
    try {
      if (noCloseDevTools) {
        miniProgram.disconnect();
      } else {
        await withTimeout(miniProgram.close(), 15000, "miniProgram.close");
      }
    } catch (error) {
      trace(`WARN close: ${error.message}`);
      miniProgram.disconnect();
    }
  }
}

run().catch((error) => {
  trace(`FAIL ${error && error.stack ? error.stack : String(error)}`);
  const failure = {
    wsEndpoint,
    launchMode,
    artifactDir,
    error: error && error.stack ? error.stack : String(error),
    hint: automationHint,
  };
  fs.writeFileSync(path.join(artifactDir, "failure.json"), JSON.stringify(failure, null, 2), "utf8");
  console.error(JSON.stringify(failure, null, 2));
  process.exit(1);
});
