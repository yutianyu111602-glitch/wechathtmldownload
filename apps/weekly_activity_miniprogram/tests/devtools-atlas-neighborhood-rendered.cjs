const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");

const wsEndpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "").trim();
const projectPath = process.env.MINIPROGRAM_PROJECT_PATH || path.resolve(__dirname, "..");
const artifactRoot = path.resolve(__dirname, "../test-artifacts");
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `atlas-neighborhood-rendered-${stamp}`);
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

async function listen(serverInstance) {
  await new Promise((resolve) => serverInstance.listen(0, "127.0.0.1", resolve));
  const address = serverInstance.address();
  return `http://127.0.0.1:${address.port}`;
}

function writeJson(name, value) {
  fs.writeFileSync(path.join(artifactDir, name), JSON.stringify(value, null, 2), "utf8");
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
      try {
        ws.close();
      } catch {
        // ignore cleanup errors
      }
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
    try {
      ws.close();
    } catch {
      resolve();
    }
    setTimeout(resolve, 1000);
  });
}

function scoreHintRank(value) {
  const hint = String(value || "");
  if (hint === "强关联") return 3;
  if (hint === "高频") return 2;
  if (hint === "相关") return 1;
  return 0;
}

async function main() {
  if (!wsEndpoint) throw new Error("MINIPROGRAM_AUTOMATOR_WS is required for connect mode");

  process.env.ATLAS_MINIAPP_PRELOAD = "0";
  process.env.ATLAS_MINIAPP_INDEX = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/atlas_index.json.gz");
  process.env.ATLAS_NEIGHBORHOOD_BUNDLE = path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/data/atlas_neighborhood.json.gz");

  const { createServer } = await import("../../../services/weekly_activity_cloudrun/src/server.mjs");
  let server;
  let ws;
  try {
    server = createServer({
      store: {},
      stage7Store: {},
      llmClient: { publicStatus: () => ({ provider: "test", configured: false }) },
      soundStore: {},
      interviewStore: {},
      env: { ...process.env, ATLAS_REQUIRE_SESSION: "false" },
    });
    const baseUrl = await listen(server);
    ws = await step("connect DevTools websocket", () => withTimeout(connectDevtools(wsEndpoint), 40000, "DevTools websocket connect"));

    function configureLocalBackend() {
      return withTimeout(callAppFunction(ws, function injectLocalBackend(base) {
      const c = getApp().globalData.cloud;
      c.useMock = false;
      c.publicBaseUrl = base;
      c.staticBaseUrl = "";
      c.useCloudDatabaseFirst = false;
      c.offlineSnapshotFallback = false;
      c.cloudClient = {
        callContainer: () => Promise.reject({ error: { code: "LOCAL_ONLY" } }),
        callFunction: () => Promise.reject({ error: { code: "LOCAL_ONLY" } }),
      };
      c.cloudReady = true;
      c.cloudInitPromise = null;
      if (typeof wx !== "undefined" && wx.getStorageInfoSync && wx.removeStorageSync) {
        const info = wx.getStorageInfoSync();
        (info.keys || []).forEach((key) => {
          if (String(key).indexOf("weeklyActivityApiCache:") === 0) wx.removeStorageSync(key);
        });
      }
      return { injected: true, publicBaseUrl: c.publicBaseUrl };
      }, [baseUrl], 60000), 70000, "inject local backend");
    }

    await step("inject local backend", configureLocalBackend);

    async function openStarmapPage() {
      const targetUrl = "/pages/atlas-starmap/atlas-starmap";
      let lastOpen = null;
      for (let attempt = 0; attempt < 4; attempt += 1) {
        try {
          lastOpen = await withTimeout(callAppFunction(ws, function openStarmapPageInApp(url, attemptNo) {
        if (typeof wx === "undefined") {
          return { ok: false, method: "wx.switchTab", reason: "wx_not_defined", attemptNo };
        }
        // atlas-starmap is a tabBar page — switchTab is the correct API and is
        // reliable under automation; reLaunch to a tabBar page can silently keep
        // the current tab. Fall back to reLaunch only if switchTab fails.
        return new Promise((resolve) => {
          wx.switchTab({
            url,
            success: () => resolve({ ok: true, method: "wx.switchTab", url, attemptNo }),
            fail: () => wx.reLaunch({
              url,
              success: () => resolve({ ok: true, method: "wx.reLaunch", url, attemptNo }),
              fail: (error) => resolve({ ok: false, method: "wx.reLaunch", url, attemptNo, error: String(error && error.errMsg || error) }),
            }),
          });
        });
          }, [targetUrl, attempt], 60000), 70000, "open starmap");
        } catch (error) {
          lastOpen = {
            ok: false,
            method: "wx.reLaunch",
            reason: "automator_call_failed",
            attemptNo: attempt,
            error: error && error.stack ? error.stack : String(error),
          };
        }
        await sleep(1200 + attempt * 400);
        const state = await readStarmapReadyState().catch(() => null);
        if (state && state.route === "pages/atlas-starmap/atlas-starmap") {
          return { ok: true, primary: lastOpen, state };
        }
      }
      const fallback = await withTimeout(callAppFunction(ws, function retryOpenStarmapPageInApp(url) {
        if (typeof wx === "undefined") return { ok: false, method: "wx.switchTab.retry", reason: "wx_not_defined" };
        return new Promise((resolve) => {
          wx.switchTab({
            url,
            success: () => resolve({ ok: true, method: "wx.switchTab.retry", url }),
            fail: () => wx.reLaunch({
              url,
              success: () => resolve({ ok: true, method: "wx.reLaunch.retry", url }),
              fail: (error) => resolve({ ok: false, method: "wx.reLaunch.retry", url, error: String(error && error.errMsg || error) }),
            }),
          });
        });
      }, [targetUrl], 60000), 70000, "open starmap retry");
      await sleep(1600);
      const state = await readStarmapReadyState().catch(() => null);
      if (!state || state.route !== "pages/atlas-starmap/atlas-starmap") {
        throw new Error(`starmap route did not open; state=${JSON.stringify(state)} primary=${JSON.stringify(lastOpen)} fallback=${JSON.stringify(fallback)}`);
      }
      return { ok: true, primary: lastOpen, fallback, state };
    }

    function readStarmapReadyState() {
      return callAppFunction(ws, function readStarmapReadyStateInApp() {
        if (typeof getCurrentPages !== "function") {
          return { hasGetCurrentPages: false };
        }
        const page = getCurrentPages()[getCurrentPages().length - 1];
        return {
          hasGetCurrentPages: true,
          route: page && page.route,
          loading: page && page.data && page.data.loading,
          canvasError: page && page.data && page.data.canvasError,
          nodeCount: page && page.data && page.data.nodeCount,
          sheetState: page && page.data && page.data.sheetState,
          viewLens: page && page.data && page.data.viewLens,
          zoomTier: page && page.data && page.data.zoomTier,
          toolPanel: page && page.data && page.data.toolPanel,
          typeShapes: page && page._nodes && page._nodeVisual
            ? Array.from(new Set(page._nodes.map(function (node) { return page._nodeVisual(node).shape; }))).sort()
            : [],
          hasSelect: Boolean(page && page.selectNode),
          hasCanvas: Boolean(page && page._canvas),
        };
      }, [], 8000);
    }

    function isStarmapReady(state) {
      return state && state.route === "pages/atlas-starmap/atlas-starmap"
        && state.hasSelect
        && state.loading === false
        && state.hasCanvas === true
        && Number(state.nodeCount) > 0;
    }

    function waitForStarmapReady(label) {
      return withTimeout(pollUntil(
        label,
        35000,
        500,
        readStarmapReadyState,
        isStarmapReady,
      ), 45000, label);
    }

    await step("open starmap page", openStarmapPage);
    await step("reinject local backend after page open", configureLocalBackend);
    await step("settle starmap runtime", () => sleep(6000));
    let ready;
    try {
      ready = await step("wait starmap ready", () => waitForStarmapReady("wait starmap ready"));
    } catch (error) {
      const staleState = await readStarmapReadyState().catch(() => null);
      if (!staleState || staleState.route !== "pages/atlas-starmap/atlas-starmap" || staleState.hasCanvas !== false) {
        throw error;
      }
      await step("retry starmap open after canvas miss", async () => {
        await openStarmapPage();
        await configureLocalBackend();
        await sleep(6000);
        return { previous: staleState };
      });
      ready = await step("wait starmap ready after retry", () => waitForStarmapReady("wait starmap ready after retry"));
    }
    assert.equal(ready.route, "pages/atlas-starmap/atlas-starmap", "starmap page did not become ready");
    assert.equal(ready.viewLens, "structure", "starmap should open in the structure lens");
    assert.equal(ready.sheetState, "hidden", "starmap should open without a selected sheet");
    assert.deepEqual(ready.typeShapes, ["circle", "diamond", "hexagon", "ring"], "base bundle should resolve all four entity shapes");

    const interaction = await step("interact starmap neighborhood", async () => {
      const center = await callAppFunction(ws, function selectLoopy() {
        if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
        const page = getCurrentPages()[getCurrentPages().length - 1];
        const centerIndex = page && page._nodeIndexById ? page._nodeIndexById["venue:loopyclub"] : undefined;
        if (centerIndex === undefined) return { ok: false, reason: "loopy_not_found" };
        page.selectNode(centerIndex);
        return { ok: true, centerIndex, selected: page.data.selected || null };
      }, [], 8000);
      if (!center.ok) return center;

      const child = await pollUntil(
        "wait first L1 child",
        12000,
        500,
        () => callAppFunction(ws, function selectFirstLoopyChild() {
          if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
          const page = getCurrentPages()[getCurrentPages().length - 1];
          const children = ((page && page._expansionChildren) || {})["venue:loopyclub"] || [];
          const childId = children[0];
          const childIndex = childId && page._nodeIndexById ? page._nodeIndexById[childId] : undefined;
          if (childIndex === undefined) {
            return { ok: false, reason: "child_not_found", selected: page && page.data ? page.data.selected || null : null };
          }
          page.selectNode(childIndex);
          return { ok: true, childId, childIndex, selected: page.data.selected || null };
        }, [], 8000),
        (state) => state && state.ok === true && state.childId,
      );

      return await pollUntil(
        "wait remote neighborhood",
        30000,
        700,
        () => callAppFunction(ws, function readSelectedNeighborhoodState(childIdArg, childIndexArg) {
          if (typeof getCurrentPages !== "function") {
            return { ok: false, reason: "getCurrentPages_not_ready", loading: true };
          }
          const page = getCurrentPages()[getCurrentPages().length - 1];
          const selected = page && page.data ? page.data.selected || {} : {};
          const hint = String(selected.expandHint || "");
          const inspector = selected.inspector || null;
          const inspectorStatus = inspector && inspector.status ? String(inspector.status) : "";
          return {
            ok: true,
            center: "venue:loopyclub",
            childId: selected.id || childIdArg,
            childIndex: childIndexArg,
            selected,
            inspectorStatus,
            inspectorSummary: inspector && inspector.summary ? String(inspector.summary) : "",
            visibleNodeCount: page && page.data ? page.data.nodeCount : 0,
            loading: hint.indexOf("正在加载") !== -1 || inspectorStatus === "loading",
          };
        }, [child.childId, child.childIndex], 8000),
        (state) => state && state.loading === false && state.inspectorStatus && state.inspectorStatus !== "loading",
      );
    });

    assert.equal(interaction.ok, true, `starmap interaction failed: ${interaction.reason || ""}`);
    assert.ok(interaction.childId, "expected a dynamic child id");
    assert.ok(!String(interaction.selected?.expandHint || "").includes("正在加载"), "remote neighborhood still loading");
    assert.ok(interaction.inspectorStatus, "expected selected DJ inspector to resolve");
    assert.notEqual(interaction.inspectorStatus, "loading", "selected DJ inspector still loading");

    const richInspector = await step("verify rich DJ inspector", async () => {
      const selected = await callAppFunction(ws, function selectKnownRichDj() {
        if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
        const page = getCurrentPages()[getCurrentPages().length - 1];
        const index = page && page._nodeIndexById ? page._nodeIndexById["dj:knopha"] : undefined;
        if (index === undefined) return { ok: false, reason: "knopha_not_found" };
        page.selectNode(index);
        return { ok: true, index, selected: page.data.selected || null };
      }, [], 8000);
      if (!selected.ok) return selected;
      return await pollUntil(
        "wait rich inspector",
        30000,
        700,
        () => callAppFunction(ws, function readKnownRichDjInspector() {
          if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
          const page = getCurrentPages()[getCurrentPages().length - 1];
          const selected = page && page.data ? page.data.selected || {} : {};
          const inspector = selected.inspector || null;
          const shareAppMessage = page && typeof page.onShareAppMessage === "function" ? page.onShareAppMessage() : null;
          const shareTimeline = page && typeof page.onShareTimeline === "function" ? page.onShareTimeline() : null;
          return {
            ok: true,
            selected,
            shareAppMessage,
            shareTimeline,
            inspectorStatus: inspector && inspector.status ? String(inspector.status) : "",
            inspectorSummary: inspector && inspector.summary ? String(inspector.summary) : "",
            neighborhoodStatus: selected && selected.neighborhoodStatus ? String(selected.neighborhoodStatus) : "",
            sheetState: page && page.data ? page.data.sheetState : "",
            viewLens: page && page.data ? page.data.viewLens : "",
            zoomTier: page && page.data ? page.data.zoomTier : "",
            selectedMetrics: selected ? {
              eventCount: selected.eventCount,
              relationCount: selected.relationCount,
              sourceCount: selected.sourceCount,
            } : null,
            cityLine: inspector && inspector.cityLine ? String(inspector.cityLine) : "",
            venueLine: inspector && inspector.venueLine ? String(inspector.venueLine) : "",
            collaboratorLine: inspector && inspector.collaboratorLine ? String(inspector.collaboratorLine) : "",
          };
        }, [], 8000),
        (state) => state && state.selected && state.selected.id === "dj:knopha"
          && state.inspectorStatus === "ready"
          && Boolean(state.cityLine || state.venueLine || state.collaboratorLine),
      );
    });

    assert.equal(richInspector.ok, true, `rich inspector failed: ${richInspector.reason || ""}`);
    assert.equal(richInspector.inspectorStatus, "ready", "expected rich inspector to be ready");
    assert.equal(richInspector.sheetState, "peek", "selected node should open the compact peek sheet");
    assert.equal(richInspector.viewLens, "structure", "selected node should keep the structure lens");
    for (const [key, value] of Object.entries(richInspector.selectedMetrics || {})) {
      assert.ok(Number.isFinite(value) && value >= 0, `expected selected ${key} to be a finite non-negative V2 metric`);
    }
    assert.match(richInspector.neighborhoodStatus, /^(概览邻域|全库邻域)\s+\d+\s+条$/, "expected selected card to expose neighborhood source/scale status");
    assert.match(String(richInspector.shareAppMessage?.title || ""), /Knopha/, "expected send-to-friend share title to name the selected node");
    assert.match(String(richInspector.shareAppMessage?.path || ""), /focusId=dj%3Aknopha/, "expected send-to-friend share path to preserve selected node focusId");
    assert.match(String(richInspector.shareTimeline?.title || ""), /Knopha/, "expected timeline share title to name the selected node");
    assert.match(String(richInspector.shareTimeline?.query || ""), /focusId=dj%3Aknopha/, "expected timeline share query to preserve selected node focusId");
    assert.ok(Array.isArray(richInspector.selected?.relatedFilters), "expected rich inspector to expose relatedFilters");
    assert.ok(richInspector.selected.relatedFilters.some((item) => item && item.k === "all" && item.on === true), "expected all related filter to be active by default");
    assert.ok(Array.isArray(richInspector.selected?.relatedPreview), "expected rich inspector to expose relatedPreview rows");
    assert.ok(richInspector.selected.relatedPreview.length > 0, "expected rich inspector to show next-hop preview rows");
    assert.ok(richInspector.selected.relatedPreview[0].scoreHint, "expected the top next-hop row to carry scoreHint");
    const hintRanks = richInspector.selected.relatedPreview.map((item) => scoreHintRank(item && item.scoreHint));
    assert.deepEqual(hintRanks, hintRanks.slice().sort((a, b) => b - a), "expected scoreHint ranks to be sorted strongest first");

    const shellProof = await step("verify explore sheet and graph lenses", () => {
      return callAppFunction(ws, function verifyExploreSheetAndLenses() {
        if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
        const page = getCurrentPages()[getCurrentPages().length - 1];
        const before = {
          selectedId: page && page.data && page.data.selected ? page.data.selected.id : "",
          nodeCount: page && page.data ? page.data.nodeCount : 0,
        };
        page.toggleExploreSheet();
        const exploreState = page.data.sheetState;
        page.setViewLens("city");
        const cityState = { lens: page.data.viewLens, selectedId: page.data.selected && page.data.selected.id, nodeCount: page.data.nodeCount };
        page.setViewLens("time");
        const timeState = { lens: page.data.viewLens, selectedId: page.data.selected && page.data.selected.id, nodeCount: page.data.nodeCount };
        page.setViewLens("structure");
        const finalState = { lens: page.data.viewLens, selectedId: page.data.selected && page.data.selected.id, nodeCount: page.data.nodeCount, sheetState: page.data.sheetState };
        return { ok: true, before, exploreState, cityState, timeState, finalState };
      }, [], 8000);
    });
    assert.equal(shellProof.ok, true, `explore shell failed: ${shellProof.reason || ""}`);
    assert.equal(shellProof.exploreState, "explore", "sheet should expand only after an explicit action");
    assert.equal(shellProof.cityState.lens, "city");
    assert.equal(shellProof.timeState.lens, "time");
    assert.equal(shellProof.finalState.lens, "structure", "screenshot should return to the default structure lens");
    assert.equal(shellProof.finalState.sheetState, "explore", "screenshot should retain the explore sheet");
    assert.equal(shellProof.cityState.selectedId, shellProof.before.selectedId, "city lens should preserve selected entity");
    assert.equal(shellProof.timeState.selectedId, shellProof.before.selectedId, "time lens should preserve selected entity");
    assert.equal(shellProof.finalState.nodeCount, shellProof.before.nodeCount, "lens changes should preserve visible node count");

    const filterProof = await step("verify related filter chip", async () => {
      return await callAppFunction(ws, function switchFirstAvailableRelatedFilter() {
        if (typeof getCurrentPages !== "function") return { ok: false, reason: "getCurrentPages_not_ready" };
        const page = getCurrentPages()[getCurrentPages().length - 1];
        const before = page && page.data ? page.data.selected || {} : {};
        const filters = Array.isArray(before.relatedFilters) ? before.relatedFilters : [];
        const chosen = filters.find((item) => item && item.k !== "all" && Number(item.count || 0) > 0);
        if (!chosen) {
          return { ok: false, reason: "no_type_filter", before };
        }
        page.onRelatedFilter({ currentTarget: { dataset: { k: chosen.k } } });
        const after = page && page.data ? page.data.selected || {} : {};
        return {
          ok: true,
          chosen,
          afterFilter: after.relatedFilter || "",
          activeFilter: (after.relatedFilters || []).find((item) => item && item.on) || null,
          rows: after.relatedPreview || [],
        };
      }, [], 8000);
    });
    assert.equal(filterProof.ok, true, `related filter chip failed: ${filterProof.reason || ""}`);
    assert.equal(filterProof.afterFilter, filterProof.chosen.k, "expected selected card to switch relatedFilter");
    assert.equal(filterProof.activeFilter && filterProof.activeFilter.k, filterProof.chosen.k, "expected chosen related filter chip to become active");
    assert.ok(filterProof.rows.length > 0, "expected filtered relatedPreview rows");
    assert.ok(filterProof.rows.every((item) => item && item.filterKey === filterProof.chosen.k), "expected filtered rows to match chosen type");

    let screenshotPath = "";
    let screenshotError = "";
    let screenshotBytes = 0;
    if (screenshotEnabled) {
      screenshotPath = path.join(artifactDir, "starmap-neighborhood.png");
      try {
        const capture = await step("capture screenshot", () => withTimeout(sendProtocol(ws, "App.captureScreenshot", {}, 30000), 40000, "screenshot"));
        fs.writeFileSync(screenshotPath, capture.data || "", "base64");
      } catch (error) {
        screenshotPath = "";
        screenshotError = error && error.stack ? error.stack : String(error);
        throw error;
      }
      screenshotBytes = fs.statSync(screenshotPath).size;
      assert.ok(screenshotBytes > 1024, "expected screenshot artifact to be non-empty");
    }

    const page = await step("read current page", () => withTimeout(sendProtocol(ws, "App.getCurrentPage", {}, 12000), 15000, "currentPage"));
    const report = {
      schemaVersion: "devtools_atlas_neighborhood_rendered.v1",
      generatedAt: new Date().toISOString(),
      artifactDir,
      wsEndpoint,
      baseUrl,
      route: page.path,
      ready,
      interaction,
      richInspector,
      shellProof,
      filterProof,
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
  } finally {
    await closeSocket(ws);
    if (server) await new Promise((resolve) => server.close(resolve));
  }
}

main().catch((error) => {
  const failure = {
    schemaVersion: "devtools_atlas_neighborhood_rendered.failure.v1",
    generatedAt: new Date().toISOString(),
    artifactDir,
    wsEndpoint,
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
