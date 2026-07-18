#!/usr/bin/env node
// Control Sanji Desktop through Electron renderer DevTools Protocol.
//
// This script does not read Sanji identity/cookie/token/license tables. It only
// calls the renderer-exposed window.api methods when Sanji was started with a
// remote debugging port.

const DEFAULT_PORT = 19333;
const DEFAULT_TIMEOUT_MS = 30 * 60 * 1000;
const fs = await import("node:fs");

function parseArgs(argv) {
  const args = {
    port: DEFAULT_PORT,
    action: "probe",
    fakeids: "all",
    cutoffHours: 48,
    force: false,
    aidsJson: null,
    aids: null,
    timeoutMs: DEFAULT_TIMEOUT_MS,
    pollMs: 1500,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--port") args.port = Number(argv[++i]);
    else if (arg === "--action") args.action = String(argv[++i]);
    else if (arg === "--fakeids") args.fakeids = String(argv[++i]);
    else if (arg === "--cutoff-hours") args.cutoffHours = Number(argv[++i]);
    else if (arg === "--force") args.force = true;
    else if (arg === "--aids-json") args.aidsJson = String(argv[++i]);
    else if (arg === "--timeout-ms") args.timeoutMs = Number(argv[++i]);
    else if (arg === "--poll-ms") args.pollMs = Number(argv[++i]);
    else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  if (args.aidsJson) {
    args.aids = normalizeAidRefs(JSON.parse(fs.readFileSync(args.aidsJson, "utf8")));
  }
  return args;
}

function normalizeAidRefs(raw) {
  if (!Array.isArray(raw)) throw new Error("--aids-json must contain an array");
  return raw.map((item, index) => {
    if (item && typeof item === "object" && typeof item.fakeid === "string" && typeof item.aid === "string") {
      return { fakeid: item.fakeid, aid: item.aid };
    }
    if (typeof item === "string" && item.includes(":")) {
      const [fakeid, ...aidParts] = item.split(":");
      const aid = aidParts.join(":");
      if (fakeid && aid) return { fakeid, aid };
    }
    throw new Error(
      `--aids-json entry ${index} must be {"fakeid":"...","aid":"..."} or "fakeid:aid"; raw aid strings are ambiguous`
    );
  });
}

function printHelp() {
  console.log(`Usage:
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action probe --port 19333
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action wait-sync --port 19333
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action sync --fakeids all --cutoff-hours 48
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action fetch --fakeids all
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action fetch --aids-json recent_pending_refs.json
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action cancel-fetch
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action resume-fetch
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action sync-fetch --fakeids all --cutoff-hours 48

Sanji must be launched with a Chromium remote debugging port, for example:
  "C:\\Program Files\\sanji\\sanji.exe" --remote-debugging-port=19333
`);
}

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status} from ${url}`);
  return res.json();
}

async function findSanjiTarget(port) {
  const targets = await getJson(`http://127.0.0.1:${port}/json/list`);
  const pages = targets.filter((target) => target.type === "page" && target.webSocketDebuggerUrl);
  const preferred = pages.find((target) =>
    String(target.title || "").includes("公号三刀") ||
    String(target.url || "").includes("/out/renderer/") ||
    String(target.url || "").startsWith("file:")
  );
  if (!preferred) {
    throw new Error(`No Sanji renderer target found on port ${port}; pages=${pages.length}`);
  }
  return preferred;
}

class CdpClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.opened = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP websocket open timeout")), 10000);
      this.ws.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      });
      this.ws.addEventListener("error", () => reject(new Error("CDP websocket error")));
    });
    this.ws.addEventListener("message", (event) => {
      const msg = JSON.parse(String(event.data));
      if (!msg.id || !this.pending.has(msg.id)) return;
      const { resolve, reject } = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
      else resolve(msg.result);
    });
  }

  async send(method, params = {}) {
    await this.opened;
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    const promise = new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`CDP command timeout: ${method}`));
        }
      }, 30000);
    });
    this.ws.send(payload);
    return promise;
  }

  close() {
    this.ws.close();
  }
}

function expressionFor(action, options) {
  const optionsJson = JSON.stringify({ ...options, action });
  return `
(async () => {
  const options = ${optionsJson};
  const call = async (promise) => {
    const res = await promise;
    if (!res || res.ok !== true) throw new Error(res && res.message ? res.message : "Sanji API call failed");
    return res.value;
  };
  const isExistingTaskError = (err) => /已有.*任务/.test(String((err && err.message) || err || ""));
  if (!window.api) return { ok: false, reason: "window.api missing" };
  const accountsPayload = await call(window.api.accounts.list());
  const accounts = accountsPayload.accounts || [];
  const fakeids = options.fakeids === "all"
    ? accounts.map((account) => account.fakeid).filter(Boolean)
    : options.fakeids.split(",").map((item) => item.trim()).filter(Boolean);
  const snapshot = async () => ({
    account_count: accounts.length,
    fakeid_count: fakeids.length,
    sync: await call(window.api.sync.status()),
    fetch: await call(window.api.fetch.status()),
    resource: await call(window.api.fetch.resourceStatus()),
  });
  if (options.action === "probe") return { ok: true, ...(await snapshot()) };
  if (options.action === "wait-sync" || options.action === "wait-fetch") return { ok: true, ...(await snapshot()) };
  if (options.action === "cancel-sync") {
    await call(window.api.sync.cancel());
    return { ok: true, cancelled: "sync", ...(await snapshot()) };
  }
  if (options.action === "resume-sync") {
    await call(window.api.sync.resume());
    return { ok: true, resumed: "sync", ...(await snapshot()) };
  }
  if (options.action === "cancel-fetch") {
    await call(window.api.fetch.cancel());
    return { ok: true, cancelled: "fetch", ...(await snapshot()) };
  }
  if (options.action === "resume-fetch") {
    await call(window.api.fetch.resume());
    return { ok: true, resumed: "fetch", ...(await snapshot()) };
  }
  if (options.action === "sync" || options.action === "sync-fetch") {
    const cutoffTs = Math.floor(Date.now() / 1000) - Math.floor(options.cutoffHours * 3600);
    try {
      await call(window.api.sync.start({ fakeids, cutoffTs }));
    } catch (err) {
      if (!isExistingTaskError(err)) throw err;
      return { ok: true, already_running: "sync", ...(await snapshot()) };
    }
    return { ok: true, started: "sync", ...(await snapshot()) };
  }
  if (options.action === "fetch") {
    const body = options.aids && options.aids.length > 0
      ? { aids: options.aids, force: options.force }
      : { fakeids, force: options.force };
    try {
      await call(window.api.fetch.start(body));
    } catch (err) {
      if (!isExistingTaskError(err)) throw err;
      return { ok: true, already_running: "fetch", ...(await snapshot()) };
    }
    return { ok: true, started: "fetch", ...(await snapshot()) };
  }
  throw new Error("Unsupported action " + options.action);
})()
`;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function evaluate(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    const text = result.exceptionDetails.text || "Runtime exception";
    throw new Error(text);
  }
  return result.result?.value;
}

function isRunning(state) {
  return state && state.phase === "running";
}

async function waitForIdle(client, label, timeoutMs, pollMs) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const state = await evaluate(client, `
(async () => {
  const call = async (promise) => {
    const res = await promise;
    if (!res || res.ok !== true) throw new Error(res && res.message ? res.message : "Sanji API call failed");
    return res.value;
  };
  return {
    sync: await call(window.api.sync.status()),
    fetch: await call(window.api.fetch.status()),
    resource: await call(window.api.fetch.resourceStatus()),
  };
})()
`);
    const active = label === "sync" ? isRunning(state.sync) : isRunning(state.fetch) || isRunning(state.resource);
    if (!active) return state;
    if (Date.now() > deadline) throw new Error(`${label} did not finish before timeout`);
    await wait(pollMs);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const target = await findSanjiTarget(args.port);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.send("Runtime.enable");
    const first = await evaluate(client, expressionFor(args.action, args));
    const output = { ok: true, target: { title: target.title, url: target.url }, first };
    if (args.action === "sync") output.final = await waitForIdle(client, "sync", args.timeoutMs, args.pollMs);
    if (args.action === "resume-sync") output.final = await waitForIdle(client, "sync", args.timeoutMs, args.pollMs);
    if (args.action === "fetch") output.final = await waitForIdle(client, "fetch", args.timeoutMs, args.pollMs);
    if (args.action === "wait-sync") output.final = await waitForIdle(client, "sync", args.timeoutMs, args.pollMs);
    if (args.action === "wait-fetch") output.final = await waitForIdle(client, "fetch", args.timeoutMs, args.pollMs);
    if (args.action === "sync-fetch") {
      output.after_sync = await waitForIdle(client, "sync", args.timeoutMs, args.pollMs);
      const fetchStart = await evaluate(client, expressionFor("fetch", args));
      output.fetch_start = fetchStart;
      output.final = await waitForIdle(client, "fetch", args.timeoutMs, args.pollMs);
    }
    console.log(JSON.stringify(output, null, 2));
  } finally {
    client.close();
  }
}

main()
  .then(() => {
    setTimeout(() => process.exit(0), 0);
  })
  .catch((err) => {
    console.error(JSON.stringify({ ok: false, error: err.message }, null, 2));
    process.exit(1);
  });
