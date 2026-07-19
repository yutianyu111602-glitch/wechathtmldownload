/**
 * Rendered proof: the existing Sound route opens, renders its safe empty form,
 * and rejects an empty submission before any upload or backend call.
 * Safety: local test storage only; no upload/deploy/review/release/DB write.
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
const artifactDir = path.join(artifactRoot, `devtools-sound-rendered-${stamp}`);
const reportPath = path.join(artifactDir, "report.json");
const screenshotEnabled = process.env.MINIPROGRAM_SCREENSHOTS === "1";
const steps = [];

fs.mkdirSync(artifactDir, { recursive: true });

const report = {
  schemaVersion: "devtools_sound_rendered.v1",
  generatedAt: new Date().toISOString(),
  endpoint,
  artifactDir,
  steps,
  safety: {
    miniProgramUploadExecuted: false,
    cloudFunctionCalled: false,
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

function step(label, run) {
  const item = { label, startedAt: new Date().toISOString() };
  steps.push(item);
  return Promise.resolve()
    .then(run)
    .then((result) => {
      item.finishedAt = new Date().toISOString();
      item.ok = true;
      return result;
    }, (error) => {
      item.finishedAt = new Date().toISOString();
      item.ok = false;
      item.error = error && error.stack ? error.stack : String(error);
      throw error;
    });
}

function connectDevtools(url) {
  return connectRawDevtools({ endpoint: url, timeoutMs: 120000 });
}

function send(socket, method, params = {}, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const id = `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
    const timer = setTimeout(() => {
      socket.off("message", onMessage);
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
      socket.off("message", onMessage);
      if (message.error) {
        reject(new Error(`${method} failed: ${JSON.stringify(message.error)}`));
        return;
      }
      resolve(message.result || {});
    }
    socket.on("message", onMessage);
    socket.send(JSON.stringify({ id, method, params }));
  });
}

function callApp(socket, fn, args = [], timeoutMs = 15000) {
  return send(socket, "App.callFunction", {
    functionDeclaration: fn.toString(),
    args,
  }, timeoutMs).then((response) => response.result);
}

async function pollUntil(label, timeoutMs, read, done) {
  const started = Date.now();
  let last;
  while (Date.now() - started <= timeoutMs) {
    last = await read();
    if (done(last)) return last;
    await sleep(300);
  }
  throw new Error(`${label} timed out; last=${JSON.stringify(last)}`);
}

function closeSocket(socket) {
  return new Promise((resolve) => {
    if (!socket || socket.readyState === WebSocket.CLOSED) {
      resolve();
      return;
    }
    socket.once("close", resolve);
    try { socket.close(); } catch { resolve(); }
    setTimeout(resolve, 1000);
  });
}

async function captureScreenshot(socket, name) {
  if (!screenshotEnabled) return null;
  const capture = await send(socket, "App.captureScreenshot", {}, 30000);
  const filePath = path.join(artifactDir, `${name}.png`);
  fs.writeFileSync(filePath, capture.data || "", "base64");
  const bytes = fs.statSync(filePath).size;
  assert.ok(bytes > 1024, `${name} screenshot should be non-empty`);
  return { path: filePath, bytes };
}

function readSoundState() {
  const pages = typeof getCurrentPages === "function" ? getCurrentPages() : [];
  const page = pages[pages.length - 1];
  const data = page && page.data ? page.data : {};
  const form = data.form || {};
  return {
    route: page && page.route,
    title: String(data.t && data.t.title || ""),
    introTitle: String(data.t && data.t.introTitle || ""),
    clubName: String(form.clubName || ""),
    imageCount: Array.isArray(form.images) ? form.images.length : -1,
    paymentImageCount: Array.isArray(form.paymentImages) ? form.paymentImages.length : -1,
    submissionCount: Array.isArray(data.submissions) ? data.submissions.length : -1,
    submitting: Boolean(data.submitting),
    uploadProgress: String(data.uploadProgress || ""),
  };
}

async function main() {
  let socket;
  try {
    socket = await step("connect DevTools", () => connectDevtools(endpoint));
    report.toolInfo = await step("Tool.getInfo", () => send(socket, "Tool.getInfo", {}, 8000));

    await step("launch safe empty Sound route", () => callApp(socket, function launchSound() {
      try { wx.setStorageSync("weeklyActivityLang", "zh"); } catch (e) {}
      try { wx.removeStorageSync("atlasSoundSubmissions:v1"); } catch (e) {}
      return new Promise((resolve) => {
        wx.reLaunch({
          url: "/pages/sound/sound",
          success: () => resolve({ ok: true }),
          fail: (err) => resolve({ ok: false, err }),
        });
      });
    }, [], 20000));

    report.rendered = await step("wait for Sound form", () => pollUntil(
      "Sound form",
      20000,
      () => callApp(socket, readSoundState, [], 10000),
      (state) => state.route === "pages/sound/sound"
        && Boolean(state.title)
        && Boolean(state.introTitle)
        && state.imageCount === 0
        && state.paymentImageCount === 0
        && state.submissionCount === 0
        && state.submitting === false,
    ));
    assert.equal(report.rendered.uploadProgress, "");

    report.emptySubmit = await step("reject empty submit before upload", () => callApp(socket, function probeEmptySubmit() {
      const pages = getCurrentPages();
      const page = pages[pages.length - 1];
      const calls = [];
      const originalShowToast = wx.showToast;
      wx.showToast = function showToast(options) {
        calls.push({ title: options && options.title, icon: options && options.icon });
        if (options && typeof options.success === "function") options.success({ errMsg: "showToast:ok" });
      };
      try {
        const result = page.submitForm();
        return Promise.resolve(result).then(() => ({
          calls,
          submitting: Boolean(page.data.submitting),
          uploadProgress: String(page.data.uploadProgress || ""),
        }));
      } finally {
        wx.showToast = originalShowToast;
      }
    }, [], 10000));
    assert.equal(report.emptySubmit.calls.length, 1);
    assert.ok(report.emptySubmit.calls[0].title, "empty submit should show a validation message");
    assert.equal(report.emptySubmit.submitting, false);
    assert.equal(report.emptySubmit.uploadProgress, "");

    report.screenshot = await step("optional Sound screenshot", () => captureScreenshot(socket, "sound-empty-form"));
    report.ok = true;
    console.log(JSON.stringify(report, null, 2));
  } catch (error) {
    report.ok = false;
    report.error = error && error.stack ? error.stack : String(error);
    console.error(report.error);
    process.exitCode = 1;
  } finally {
    await closeSocket(socket);
    writeReport();
  }
}

main();
