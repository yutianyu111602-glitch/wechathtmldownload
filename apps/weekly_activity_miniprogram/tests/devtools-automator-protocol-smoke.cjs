const fs = require("node:fs");
const path = require("node:path");
const WebSocket = require("ws");

const endpoint = String(process.env.MINIPROGRAM_AUTOMATOR_WS || "ws://[::1]:9421").trim();
const expectedVersion = String(process.env.MINIPROGRAM_EXPECT_DEVTOOLS_VERSION || "").trim();
const navigationProbeEnabled = process.env.MINIPROGRAM_AUTOMATOR_NAV_PROBE !== "0";
const navigationProbePath = String(process.env.MINIPROGRAM_AUTOMATOR_NAV_PATH || "/pages/index/index").trim() || "/pages/index/index";
const artifactRoot = process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT
  ? path.resolve(process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT)
  : path.resolve(__dirname, "../test-artifacts");
const artifactKind = String(process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_KIND || "live").trim() || "live";
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `devtools-automator-protocol-${stamp}`);
const reportPath = path.join(artifactDir, "report.json");
fs.mkdirSync(artifactDir, { recursive: true });

const report = {
  schemaVersion: "devtools_automator_protocol_smoke.v2",
  artifactKind,
  artifactDir,
  generatedAt: new Date().toISOString(),
  endpoint,
  expectedVersion,
  navigationProbeEnabled,
  navigationProbePath,
  connected: false,
  responses: [],
  safety: {
    miniProgramUploadExecuted: false,
    cloudRunDeployExecuted: false,
    previewQrGenerated: false,
    reviewSubmitted: false,
    publicReleaseExecuted: false,
    productionDbWriteExecuted: false,
  },
};

function writeAndExit(code) {
  report.finishedAt = new Date().toISOString();
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
  process.exit(code);
}

function send(ws, method, params = {}, timeoutMs = 8000) {
  return new Promise((resolve) => {
    const id = `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
    const timer = setTimeout(() => {
      ws.off("message", onMessage);
      resolve({ method, ok: false, timeout: true });
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
      resolve({
        method,
        ok: !message.error,
        error: message.error || null,
        result: message.result || null,
      });
    }
    ws.on("message", onMessage);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

function appCall(ws, fn, args = [], timeoutMs = 8000, label = "App.callFunction") {
  return send(ws, "App.callFunction", {
    functionDeclaration: fn.toString(),
    args,
  }, timeoutMs).then((response) => ({ ...response, label }));
}

function appCallValue(response) {
  if (!response || !response.result || typeof response.result !== "object") return null;
  if (Object.prototype.hasOwnProperty.call(response.result, "result")) {
    return response.result.result;
  }
  return response.result;
}

async function runNavigationProbe(ws) {
  const targetRoute = navigationProbePath.replace(/^\//, "").split("?")[0];
  const separator = navigationProbePath.includes("?") ? "&" : "?";
  const targetUrl = `${navigationProbePath}${separator}protocolSmokeTs=${encodeURIComponent(stamp)}`;

  const readRoute = function readRoute() {
    if (typeof getCurrentPages !== "function") return { path: "", reason: "getCurrentPages_not_ready" };
    const pages = getCurrentPages();
    const page = pages[pages.length - 1];
    return { path: page && page.route, query: page && page.options };
  };

  const before = await appCall(ws, readRoute, [], 8000, "navigationProbe.readBefore");
  report.responses.push(before);
  if (!before.ok) {
    return { ok: false, stage: "read_before", targetUrl, targetRoute, before };
  }
  const beforeValue = appCallValue(before);

  const launch = await appCall(ws, function launchSmoke(target) {
    return new Promise((resolve) => {
      if (typeof wx === "undefined" || typeof wx.reLaunch !== "function") {
        resolve({ ok: false, reason: "wx.reLaunch_not_ready" });
        return;
      }
      wx.reLaunch({
        url: target,
        success: () => resolve({ ok: true }),
        fail: (err) => resolve({ ok: false, err }),
      });
    });
  }, [targetUrl], 12000, "navigationProbe.reLaunch");
  report.responses.push(launch);
  const launchValue = appCallValue(launch);
  if (!launch.ok || launchValue?.ok !== true) {
    return { ok: false, stage: "reLaunch", targetUrl, targetRoute, before: beforeValue, launch };
  }

  let after = null;
  let afterValue = null;
  for (let attempt = 1; attempt <= 10; attempt += 1) {
    after = await appCall(ws, readRoute, [], 5000, `navigationProbe.readAfter.${attempt}`);
    report.responses.push(after);
    afterValue = appCallValue(after);
    if (after.ok && afterValue?.path === targetRoute) {
      return {
        ok: true,
        targetUrl,
        targetRoute,
        attempts: attempt,
        before: beforeValue,
        after: afterValue,
      };
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }

  return {
    ok: false,
    stage: "read_after",
    targetUrl,
    targetRoute,
    before: beforeValue,
    after: afterValue || (after && (after.result || after)),
  };
}

const ws = new WebSocket(endpoint);
const openTimer = setTimeout(() => {
  report.error = "open_timeout";
  writeAndExit(1);
}, 8000);

ws.on("open", async () => {
  clearTimeout(openTimer);
  report.connected = true;
  report.responses.push(await send(ws, "Tool.getInfo"));
  report.responses.push(await send(ws, "App.getCurrentPage"));
  if (navigationProbeEnabled) {
    report.navigationProbe = await runNavigationProbe(ws);
  }
  ws.close();

  const toolInfo = report.responses.find((item) => item.method === "Tool.getInfo");
  const currentPage = report.responses.find((item) => item.method === "App.getCurrentPage");
  report.versionOk = Boolean(toolInfo && toolInfo.ok && (!expectedVersion || toolInfo.result?.version === expectedVersion));
  report.appCurrentPageOk = Boolean(currentPage && currentPage.ok);
  report.navigationProbeOk = !navigationProbeEnabled || Boolean(report.navigationProbe?.ok);
  writeAndExit(report.versionOk && report.appCurrentPageOk && report.navigationProbeOk ? 0 : 1);
});

ws.on("error", (error) => {
  clearTimeout(openTimer);
  report.error = error && error.stack ? error.stack : String(error);
  writeAndExit(1);
});
