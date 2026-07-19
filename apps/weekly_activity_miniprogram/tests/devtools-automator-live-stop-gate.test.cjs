const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const http = require("node:http");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const WebSocket = require("ws");

const WebSocketServer = WebSocket.WebSocketServer || WebSocket.Server;
const repoRoot = path.resolve(__dirname, "../../..");
const runner = path.join(__dirname, "devtools-automator-live-stop-gate.cjs");

function listen(server, host = "127.0.0.1") {
  return new Promise((resolve) => {
    server.listen(0, host, () => resolve(server.address().port));
  });
}

function close(server) {
  return new Promise((resolve) => server.close(resolve));
}

function runLiveStopGateOnce(env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [runner], {
      cwd: repoRoot,
      env: { ...process.env, ...env },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("exit", (code) => {
      try {
        resolve({ code, report: JSON.parse(stdout), stderr });
      } catch (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
      }
    });
  });
}

async function runLiveStopGate(env) {
  try {
    return await runLiveStopGateOnce(env);
  } catch (error) {
    if (String(error.stdout || "").trim() || String(error.stderr || "").trim()) throw error;
    return runLiveStopGateOnce(env);
  }
}

test("live stop gate skips IDE HTTP service ports and selects an automator WebSocket", async () => {
  const fixtureArtifactRoot = fs.mkdtempSync(path.join(os.tmpdir(), "huaidj-devtools-fixture-"));
  const httpServer = http.createServer((req, res) => {
    if (req.url === "/v2/islogin") {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ login: true }));
      return;
    }
    res.statusCode = 404;
    res.end("not found");
  });
  const httpPort = await listen(httpServer);

  const wsServer = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  const wsPort = await new Promise((resolve) => {
    wsServer.once("listening", () => resolve(wsServer.address().port));
  });
  wsServer.on("connection", (ws) => {
    ws.on("message", (raw) => {
      const message = JSON.parse(String(raw));
      let result = {};
      if (message.method === "Tool.getInfo") {
        result = { version: "2.02.2606222", SDKVersion: "3.16.0" };
      } else if (message.method === "App.getCurrentPage") {
        result = { path: "pages/index/index", query: {} };
      } else if (message.method === "App.callFunction") {
        const declaration = String(message.params?.functionDeclaration || "");
        result = {
          result: declaration.includes("launchSmoke")
            ? { ok: true }
            : { path: "pages/index/index", query: {} },
        };
      }
      ws.send(JSON.stringify({ id: message.id, result }));
    });
  });

  try {
    const { code, report } = await runLiveStopGate({
      MINIPROGRAM_AUTOMATOR_CANDIDATES: [
        `ws://127.0.0.1:${httpPort}`,
        `ws://127.0.0.1:${wsPort}`,
      ].join(","),
      MINIPROGRAM_AUTOMATOR_SCAN_STANDARD_PORTS: "0",
      MINIPROGRAM_AUTOMATOR_FULL_SMOKE_LIMIT: "2",
      MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT: fixtureArtifactRoot,
      MINIPROGRAM_AUTOMATOR_ARTIFACT_KIND: "synthetic_fixture",
    });

    assert.equal(code, 0);
    assert.equal(report.schemaVersion, "devtools_automator_live_stop_gate.v2");
    assert.equal(report.ok, true);
    assert.equal(report.artifactKind, "synthetic_fixture");
    assert.equal(report.safety.syntheticFixture, true);
    assert.ok(path.resolve(report.artifactDir).startsWith(path.resolve(fixtureArtifactRoot)));
    assert.equal(report.selectedEndpoint, `ws://127.0.0.1:${wsPort}`);
    assert.ok(
      report.httpServiceEndpoints.some((item) => item.httpUrl === `http://127.0.0.1:${httpPort}/v2/islogin`),
      "HTTP service endpoint should be detected before WebSocket probing",
    );
    assert.ok(
      report.quickProbeResults.some((item) => item.endpoint === `ws://127.0.0.1:${httpPort}` && item.skipReason === "devtools_http_service_not_automator"),
      "HTTP service endpoint should be skipped as a non-automator",
    );
    assert.ok(report.smokeResults.some((item) => item.endpoint === `ws://127.0.0.1:${wsPort}` && item.ok));
    for (const smoke of report.smokeResults.filter((item) => item.report)) {
      assert.ok(smoke.report.artifactDir, "nested protocol smoke must report its artifact directory");
      assert.ok(
        path.resolve(smoke.report.artifactDir).startsWith(path.resolve(fixtureArtifactRoot)),
        `nested protocol smoke artifact escaped the configured root: ${smoke.report.artifactDir}`,
      );
    }
  } finally {
    await Promise.all([close(wsServer), close(httpServer)]);
  }
});
