const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const WebSocket = require("ws");

const artifactRoot = process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT
  ? path.resolve(process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_ROOT)
  : path.resolve(__dirname, "../test-artifacts");
const artifactKind = String(process.env.MINIPROGRAM_AUTOMATOR_ARTIFACT_KIND || "live").trim() || "live";
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const artifactDir = path.join(artifactRoot, `devtools-automator-live-stop-gate-${stamp}`);
const reportPath = path.join(artifactDir, "report.json");
const smokeScript = path.resolve(__dirname, "devtools-automator-protocol-smoke.cjs");
const expectedVersion = String(process.env.MINIPROGRAM_EXPECT_DEVTOOLS_VERSION || "").trim();
const includeStandardPorts = process.env.MINIPROGRAM_AUTOMATOR_SCAN_STANDARD_PORTS !== "0";
const fullSmokeLimit = Number(process.env.MINIPROGRAM_AUTOMATOR_FULL_SMOKE_LIMIT || "4");

fs.mkdirSync(artifactDir, { recursive: true });

const report = {
  schemaVersion: "devtools_automator_live_stop_gate.v2",
  artifactKind,
  generatedAt: new Date().toISOString(),
  expectedVersion,
  artifactDir,
  candidates: [],
  httpProbeResults: [],
  httpServiceEndpoints: [],
  quickProbeResults: [],
  smokeResults: [],
  selectedEndpoint: "",
  ok: false,
  safety: {
    syntheticFixture: artifactKind === "synthetic_fixture",
    miniProgramUploadExecuted: false,
    cloudRunDeployExecuted: false,
    previewQrGenerated: false,
    reviewSubmitted: false,
    publicReleaseExecuted: false,
    productionDbWriteExecuted: false,
  },
};

function writeReport() {
  report.finishedAt = new Date().toISOString();
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
}

function parseCandidate(value, source) {
  const raw = String(value || "").trim();
  if (!raw) return [];
  return raw
    .split(/[\s,;]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      if (/^wss?:\/\//i.test(item)) return { endpoint: item, source };
      if (/^\d+$/.test(item)) return { endpoint: `ws://127.0.0.1:${item}`, source };
      return null;
    })
    .filter(Boolean);
}

function endpointKey(endpoint) {
  return String(endpoint || "").replace(/\/+$/, "").toLowerCase();
}

function addCandidate(map, endpoint, source, detail = {}) {
  if (!endpoint) return;
  const key = endpointKey(endpoint);
  if (!key || map.has(key)) return;
  map.set(key, { endpoint, source, ...detail });
}

function endpointsForListener(listener) {
  const port = Number(listener.LocalPort || listener.localPort || listener.port);
  if (!Number.isFinite(port) || port <= 0) return [];
  const address = String(listener.LocalAddress || listener.localAddress || "").trim();
  const endpoints = [];
  if (address === "::" || address === "::1") {
    endpoints.push(`ws://[::1]:${port}`);
    endpoints.push(`ws://127.0.0.1:${port}`);
  } else if (address === "0.0.0.0") {
    endpoints.push(`ws://127.0.0.1:${port}`);
  } else if (address === "127.0.0.1" || address === "localhost") {
    endpoints.push(`ws://127.0.0.1:${port}`);
  }
  return endpoints;
}

function discoverDevtoolsListeners() {
  if (process.platform !== "win32") return { listeners: [], error: "windows_only" };
  const command = [
    "$ErrorActionPreference='Stop';",
    "$procs = Get-Process | Where-Object {",
    "$_.ProcessName -like '*微信开发者工具*' -or",
    "$_.ProcessName -like '*wechatdevtools*' -or",
    "$_.Path -like '*微信web开发者工具*'",
    "};",
    "$ids = @($procs | Select-Object -ExpandProperty Id);",
    "if ($ids.Count -eq 0) { @() | ConvertTo-Json -Compress; exit 0 }",
    "Get-NetTCPConnection |",
    "Where-Object { $ids -contains $_.OwningProcess -and $_.State -eq 'Listen' } |",
    "Select-Object LocalAddress,LocalPort,OwningProcess |",
    "Sort-Object LocalPort | ConvertTo-Json -Compress",
  ].join(" ");
  const result = spawnSync("powershell.exe", ["-NoProfile", "-Command", command], {
    encoding: "utf8",
    timeout: 10000,
  });
  if (result.error || result.status !== 0) {
    return {
      listeners: [],
      error: result.error ? String(result.error) : String(result.stderr || `exit ${result.status}`),
    };
  }
  try {
    const parsed = JSON.parse(String(result.stdout || "[]"));
    return { listeners: Array.isArray(parsed) ? parsed : (parsed ? [parsed] : []) };
  } catch (error) {
    return { listeners: [], error: error && error.message ? error.message : String(error), raw: result.stdout };
  }
}

function hostPortFromEndpoint(endpoint) {
  try {
    const url = new URL(endpoint);
    const host = String(url.hostname || "").replace(/^\[|\]$/g, "");
    return { host, port: Number(url.port) };
  } catch {
    return { host: "", port: 0 };
  }
}

function httpServiceUrlFromEndpoint(endpoint) {
  const { host, port } = hostPortFromEndpoint(endpoint);
  if (!host || !Number.isFinite(port) || port <= 0) return "";
  const hostForUrl = host.includes(":") ? `[${host}]` : host;
  return `http://${hostForUrl}:${port}/v2/islogin`;
}

function tcpReachable(endpoint, timeoutMs = 350) {
  const { host, port } = hostPortFromEndpoint(endpoint);
  if (!host || !Number.isFinite(port) || port <= 0) return Promise.resolve(false);
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    const timer = setTimeout(() => {
      socket.destroy();
      resolve(false);
    }, timeoutMs);
    socket.once("connect", () => {
      clearTimeout(timer);
      socket.destroy();
      resolve(true);
    });
    socket.once("error", () => {
      clearTimeout(timer);
      resolve(false);
    });
  });
}

function shouldProbeHttpService(candidate) {
  return candidate.source === "devtools-owned-listener" || String(candidate.source || "").startsWith("env:");
}

function sendProtocol(ws, method, params = {}, timeoutMs = 2500) {
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
      resolve({ method, ok: !message.error, error: message.error || null, result: message.result || null });
    }
    ws.on("message", onMessage);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function probeDevtoolsHttpService(endpoint) {
  const url = httpServiceUrlFromEndpoint(endpoint);
  if (!url) {
    return { endpoint, httpServiceProbeOk: false, isDevtoolsHttpService: false, error: "invalid_endpoint" };
  }
  const reachable = await tcpReachable(endpoint, 250);
  if (!reachable) {
    return { endpoint, httpUrl: url, tcpReachable: false, httpServiceProbeOk: false, isDevtoolsHttpService: false };
  }
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 900 }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        let parsed = null;
        try { parsed = JSON.parse(body); } catch { /* keep raw body */ }
        const isDevtoolsHttpService = res.statusCode === 200 && parsed && typeof parsed.login === "boolean";
        resolve({
          endpoint,
          httpUrl: url,
          tcpReachable: true,
          statusCode: res.statusCode,
          httpServiceProbeOk: res.statusCode === 200,
          isDevtoolsHttpService,
          login: parsed && typeof parsed.login === "boolean" ? parsed.login : null,
          body: isDevtoolsHttpService ? "" : body.slice(0, 240),
        });
      });
    });
    req.on("timeout", () => {
      req.destroy();
      resolve({ endpoint, httpUrl: url, tcpReachable: true, httpServiceProbeOk: false, isDevtoolsHttpService: false, error: "timeout" });
    });
    req.on("error", (error) => {
      resolve({
        endpoint,
        httpUrl: url,
        tcpReachable: true,
        httpServiceProbeOk: false,
        isDevtoolsHttpService: false,
        error: error && error.message ? error.message : String(error),
      });
    });
  });
}

async function quickProbe(endpoint) {
  const reachable = await tcpReachable(endpoint);
  if (!reachable) return { endpoint, tcpReachable: false, toolInfoOk: false };
  return new Promise((resolve) => {
    const ws = new WebSocket(endpoint);
    const timer = setTimeout(() => {
      try { ws.close(); } catch { /* ignore */ }
      resolve({ endpoint, tcpReachable: true, toolInfoOk: false, error: "open_timeout" });
    }, 1800);
    ws.once("open", async () => {
      clearTimeout(timer);
      const toolInfo = await sendProtocol(ws, "Tool.getInfo", {}, 2500);
      try { ws.close(); } catch { /* ignore */ }
      resolve({
        endpoint,
        tcpReachable: true,
        toolInfoOk: Boolean(toolInfo.ok),
        version: toolInfo.result && toolInfo.result.version,
        sdkVersion: toolInfo.result && toolInfo.result.SDKVersion,
        error: toolInfo.ok ? "" : JSON.stringify(toolInfo.error || (toolInfo.timeout ? "timeout" : "not_ok")),
      });
    });
    ws.once("error", (error) => {
      clearTimeout(timer);
      resolve({
        endpoint,
        tcpReachable: true,
        toolInfoOk: false,
        error: error && error.message ? error.message : String(error),
      });
    });
  });
}

function runSmoke(endpoint) {
  return new Promise((resolve) => {
    const env = {
      ...process.env,
      MINIPROGRAM_AUTOMATOR_WS: endpoint,
      MINIPROGRAM_EXPECT_DEVTOOLS_VERSION: expectedVersion,
    };
    const child = spawn(process.execPath, [smokeScript], {
      cwd: path.resolve(__dirname, "../../.."),
      env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("exit", (code) => {
      let parsed = null;
      try { parsed = JSON.parse(stdout); } catch { /* keep raw output */ }
      resolve({
        endpoint,
        exitCode: code,
        ok: code === 0 && parsed && parsed.versionOk && parsed.appCurrentPageOk && parsed.navigationProbeOk,
        report: parsed,
        stdout: parsed ? "" : stdout,
        stderr,
      });
    });
  });
}

async function main() {
  const candidateMap = new Map();
  for (const item of parseCandidate(process.env.MINIPROGRAM_AUTOMATOR_WS, "env:MINIPROGRAM_AUTOMATOR_WS")) {
    addCandidate(candidateMap, item.endpoint, item.source);
  }
  for (const item of parseCandidate(process.env.MINIPROGRAM_AUTOMATOR_CANDIDATES, "env:MINIPROGRAM_AUTOMATOR_CANDIDATES")) {
    addCandidate(candidateMap, item.endpoint, item.source);
  }

  const discovery = discoverDevtoolsListeners();
  report.devtoolsListenerDiscovery = discovery;
  for (const listener of discovery.listeners || []) {
    for (const endpoint of endpointsForListener(listener)) {
      addCandidate(candidateMap, endpoint, "devtools-owned-listener", { listener });
    }
  }

  if (includeStandardPorts) {
    for (let port = 9420; port <= 9450; port += 1) {
      addCandidate(candidateMap, `ws://127.0.0.1:${port}`, "standard-automator-range");
      addCandidate(candidateMap, `ws://[::1]:${port}`, "standard-automator-range");
    }
  }

  report.candidates = [...candidateMap.values()];
  const httpServiceKeys = new Set();
  for (const candidate of report.candidates) {
    if (!shouldProbeHttpService(candidate)) continue;
    const httpProbe = await probeDevtoolsHttpService(candidate.endpoint);
    const result = { ...candidate, ...httpProbe };
    report.httpProbeResults.push(result);
    if (httpProbe.isDevtoolsHttpService) {
      httpServiceKeys.add(endpointKey(candidate.endpoint));
      report.httpServiceEndpoints.push({
        endpoint: candidate.endpoint,
        httpUrl: httpProbe.httpUrl,
        listener: candidate.listener || null,
        login: httpProbe.login,
      });
    }
  }

  for (const candidate of report.candidates) {
    if (httpServiceKeys.has(endpointKey(candidate.endpoint))) {
      report.quickProbeResults.push({
        ...candidate,
        endpoint: candidate.endpoint,
        tcpReachable: true,
        toolInfoOk: false,
        skipped: true,
        skipReason: "devtools_http_service_not_automator",
      });
      continue;
    }
    const quick = await quickProbe(candidate.endpoint);
    report.quickProbeResults.push({ ...candidate, ...quick });
  }

  const smokeCandidates = report.quickProbeResults
    .filter((item) => item.toolInfoOk)
    .sort((a, b) => {
      const aExpected = a.version === expectedVersion ? 0 : 1;
      const bExpected = b.version === expectedVersion ? 0 : 1;
      return aExpected - bExpected;
    })
    .slice(0, Math.max(1, fullSmokeLimit));

  for (const candidate of smokeCandidates) {
    const smoke = await runSmoke(candidate.endpoint);
    report.smokeResults.push(smoke);
    if (smoke.ok && !report.selectedEndpoint) {
      report.selectedEndpoint = candidate.endpoint;
      report.ok = true;
    }
  }

  if (!smokeCandidates.length) {
    report.error = "no_candidate_passed_quick_tool_probe";
  }

  writeReport();
  console.log(JSON.stringify(report, null, 2));
  process.exit(report.ok ? 0 : 1);
}

main().catch((error) => {
  report.error = error && error.stack ? error.stack : String(error);
  writeReport();
  console.log(JSON.stringify(report, null, 2));
  process.exit(1);
});
