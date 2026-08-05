#!/usr/bin/env node
// Control Sanji Desktop through Electron renderer DevTools Protocol.
//
// This script does not read Sanji identity/cookie/token/license tables. It only
// calls the renderer-exposed window.api methods when Sanji was started with a
// remote debugging port.

const DEFAULT_PORT = 19333;
const DEFAULT_TIMEOUT_MS = 30 * 60 * 1000;
const fs = await import("node:fs");
const crypto = await import("node:crypto");
const path = await import("node:path");
const { pathToFileURL } = await import("node:url");

function parseArgs(argv) {
  const args = {
    port: DEFAULT_PORT,
    action: "probe",
    fakeids: "all",
    cutoffHours: 168,
    cutoffTs: 0,
    channel: "client",
    maxClientAccounts: 1,
    credentialPolicy: "ready-only",
    syncResumeAttempts: 1,
    fakeidsJson: null,
    registryJson: null,
    registryAccount: null,
    completionLedger: null,
    cycleId: null,
    interAccountDelayMs: 15000,
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
    else if (arg === "--fakeids-json") args.fakeidsJson = String(argv[++i]);
    else if (arg === "--registry-json") args.registryJson = String(argv[++i]);
    else if (arg === "--cutoff-hours") args.cutoffHours = Number(argv[++i]);
    else if (arg === "--cutoff-ts") args.cutoffTs = Number(argv[++i]);
    else if (arg === "--channel") args.channel = String(argv[++i]);
    else if (arg === "--max-client-accounts") args.maxClientAccounts = Number(argv[++i]);
    else if (arg === "--credential-policy") args.credentialPolicy = String(argv[++i]);
    else if (arg === "--sync-resume-attempts") args.syncResumeAttempts = Number(argv[++i]);
    else if (arg === "--completion-ledger") args.completionLedger = String(argv[++i]);
    else if (arg === "--cycle-id") args.cycleId = String(argv[++i]);
    else if (arg === "--inter-account-delay-ms") args.interAccountDelayMs = Number(argv[++i]);
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
  if (args.fakeidsJson) {
    const payload = JSON.parse(fs.readFileSync(args.fakeidsJson, "utf8"));
    const values = Array.isArray(payload) ? payload : payload && payload.eligible_fakeids;
    if (!Array.isArray(values) || values.length === 0) {
      throw new Error("--fakeids-json must be an array or contain a non-empty eligible_fakeids array");
    }
    args.fakeids = values.map((item) => String(item && item.fakeid ? item.fakeid : item)).filter(Boolean);
  }
  if (args.registryJson) {
    const payload = JSON.parse(fs.readFileSync(args.registryJson, "utf8"));
    const accounts = (payload && (payload.accounts || payload.items)) || [];
    const requested = Array.isArray(args.fakeids) ? args.fakeids : String(args.fakeids).split(",");
    if (requested.length !== 1) throw new Error("--registry-json requires exactly one --fakeids value");
    args.registryAccount = accounts.find((item) => item && item.fakeid === requested[0]) || null;
    if (!args.registryAccount) throw new Error("requested fakeid is absent from --registry-json");
  }
  if (args.channel !== "client") {
    throw new Error("Only Sanji 1.1.x WeChat client channel is supported; backend channel is closed");
  }
  if (!Number.isFinite(args.maxClientAccounts) || args.maxClientAccounts < 1) {
    throw new Error("--max-client-accounts must be a positive integer");
  }
  if (!["ready-only", "require-all"].includes(args.credentialPolicy)) {
    throw new Error("--credential-policy must be ready-only or require-all");
  }
  if (!Number.isInteger(args.syncResumeAttempts) || args.syncResumeAttempts < 0) {
    throw new Error("--sync-resume-attempts must be a non-negative integer");
  }
  if (!Number.isFinite(args.interAccountDelayMs) || args.interAccountDelayMs < 0) {
    throw new Error("--inter-account-delay-ms must be a non-negative number");
  }
  if (args.cutoffTs && (!Number.isInteger(args.cutoffTs) || args.cutoffTs < 1)) {
    throw new Error("--cutoff-ts must be a positive Unix timestamp");
  }
  if (args.action === "sync-sequential") {
    if (!args.completionLedger) throw new Error("sync-sequential requires --completion-ledger");
    if (!args.cycleId) throw new Error("sync-sequential requires --cycle-id");
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
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action credential-readiness --fakeids-json account_scope.json
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action credential-capture-start --fakeids <one-fakeid>
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action credential-capture-status
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action credential-open-wechat
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action credential-capture-stop
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action account-add-from-registry --fakeids <one-fakeid> --registry-json weekly_accounts_seed.json
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action sync --fakeids all --cutoff-hours 168 --channel client
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action sync-sequential --fakeids-json account_scope.json --completion-ledger cycle.json --cycle-id 20260805-evening --max-client-accounts 128 --cutoff-hours 168 --channel client
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action fetch --fakeids all
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action fetch --aids-json recent_pending_refs.json
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action cancel-fetch
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action resume-fetch
  node tools/stage7_rewrite/scripts/sanji_desktop_cdp_control.mjs --action sync-fetch --fakeids all --cutoff-hours 168 --channel client

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
  const requestedFakeids = options.fakeids === "all"
    ? accounts.map((account) => account.fakeid).filter(Boolean)
    : Array.isArray(options.fakeids)
      ? options.fakeids.map((item) => String(item).trim()).filter(Boolean)
      : options.fakeids.split(",").map((item) => item.trim()).filter(Boolean);
  const credentialsPayload = await call(window.api.metadata.listCredentials());
  const credentials = Array.isArray(credentialsPayload)
    ? credentialsPayload
    : (credentialsPayload && credentialsPayload.credentials) || [];
  const nowMs = Date.now();
  const credentialByFakeid = new Map(credentials.map((item) => [item.fakeid, item]));
  const readiness = requestedFakeids.map((fakeid) => {
    const credential = credentialByFakeid.get(fakeid);
    const expiresAt = Number(credential && credential.listExpiresAt) || 0;
    return { fakeid, ready: expiresAt > nowMs, expiresAt };
  });
  const ready = readiness.filter((item) => item.ready);
  const missingCount = readiness.length - ready.length;
  const credentialSummary = {
    requested_count: readiness.length,
    ready_count: ready.length,
    missing_or_expired_count: missingCount,
    selected_count: 0,
    minimum_ttl_minutes: ready.length > 0
      ? Math.max(0, Math.floor((Math.min(...ready.map((item) => item.expiresAt)) - nowMs) / 60000))
      : 0,
    secret_values_exposed: false,
  };
  const safeCaptureStatus = (status) => ({
    phase: String((status && status.phase) || "unknown"),
    fakeid: String((status && status.fakeid) || ""),
    rate_limited: Boolean(status && status.rateLimited),
    no_traffic: Boolean(status && status.noTraffic),
    status_keys: status && typeof status === "object" ? Object.keys(status).sort() : [],
    error: String((status && (status.errorMessage || status.message || status.reason || status.error)) || "").slice(0, 500),
    secret_values_exposed: false,
  });
  const syncErrorText = (status) => String(
    (status && (status.lastError || status.last_error || status.errorMessage || status.message)) || ""
  );
  const assertNotRateLimited = async () => {
    const capture = safeCaptureStatus(await call(window.api.metadata.captureStatus()));
    const sync = await call(window.api.sync.status());
    const syncError = syncErrorText(sync);
    if (capture.rate_limited || /client_rate_limited|rate.?limit|ret\\s*[:=]?\\s*-6/i.test(syncError)) {
      throw new Error("sanji_client_rate_limited_preflight: stop all WeChat-channel requests and wait for the account cooldown");
    }
    return { capture, sync };
  };
  if (options.action === "credential-readiness") {
    return {
      ok: ready.length > 0 && (options.credentialPolicy !== "require-all" || missingCount === 0),
      channel: "client",
      coverage_scope: "broadcast_only",
      ready_fakeids: ready.map((item) => item.fakeid),
      credentials: credentialSummary,
    };
  }
  if (options.action === "credential-capture-start") {
    if (requestedFakeids.length !== 1) {
      throw new Error("credential-capture-start requires exactly one --fakeids value");
    }
    const fakeid = requestedFakeids[0];
    if (!accounts.some((account) => account.fakeid === fakeid)) {
      throw new Error("credential-capture-start account is not present in Sanji");
    }
    const currentCapture = safeCaptureStatus(await call(window.api.metadata.captureStatus()));
    if (currentCapture.rate_limited) {
      throw new Error("sanji_client_rate_limited_preflight: credential capture is blocked until cooldown");
    }
    const copied = await call(window.api.metadata.copyArticleLink(fakeid));
    const capture = await call(window.api.metadata.captureStart({ fakeid, debug: false }));
    return {
      ok: true,
      channel: "client",
      coverage_scope: "broadcast_only",
      copied_link_kind: String((copied && copied.kind) || "unknown"),
      capture: safeCaptureStatus(capture),
    };
  }
  if (options.action === "credential-capture-status") {
    return {
      ok: true,
      channel: "client",
      coverage_scope: "broadcast_only",
      capture: safeCaptureStatus(await call(window.api.metadata.captureStatus())),
    };
  }
  if (options.action === "credential-open-wechat") {
    await call(window.api.metadata.openWechat());
    return { ok: true, channel: "client", opened: "wechat", secret_values_exposed: false };
  }
  if (options.action === "credential-capture-stop") {
    await call(window.api.metadata.captureStop());
    return {
      ok: true,
      channel: "client",
      coverage_scope: "broadcast_only",
      capture: { phase: "stopped", secret_values_exposed: false },
    };
  }
  if (options.action === "account-add-from-registry") {
    const item = options.registryAccount;
    if (!item || !item.fakeid || !item.account_name) {
      throw new Error("account-add-from-registry requires a complete registry account");
    }
    if (accounts.some((account) => account.fakeid === item.fakeid)) {
      return { ok: true, account_fakeid: item.fakeid, added: 0, already_present: true, secret_values_exposed: false };
    }
    const result = await call(window.api.accounts.batchAdd({
      accounts: [{
        fakeid: item.fakeid,
        nickname: item.account_name,
        alias: null,
        headImg: item.avatar_url || null,
        serviceType: 0,
        signature: null,
        groupName: null,
        groupColor: null,
      }],
    }));
    return {
      ok: true,
      account_fakeid: item.fakeid,
      added: Number((result && result.added) || 0),
      skipped: Number((result && result.skipped) || 0),
      already_present: false,
      secret_values_exposed: false,
    };
  }
  if (options.action === "sync-preflight") {
    const preflight = await assertNotRateLimited();
    return {
      ok: true,
      channel: "client",
      coverage_scope: "broadcast_only",
      capture: preflight.capture,
      sync: preflight.sync,
      secret_values_exposed: false,
    };
  }
  if (["sync", "sync-fetch"].includes(options.action)) {
    if (ready.length === 0) {
      throw new Error("sanji_client_credential_required: no selected account has a valid list credential");
    }
    if (options.credentialPolicy === "require-all" && missingCount > 0) {
      throw new Error("sanji_client_credential_incomplete: " + missingCount + " selected account credential(s) are missing or expired");
    }
  }
  const fakeids = ["sync", "sync-fetch"].includes(options.action)
    ? ready.slice(0, Math.floor(options.maxClientAccounts)).map((item) => item.fakeid)
    : requestedFakeids;
  credentialSummary.selected_count = fakeids.length;
  const snapshot = async () => ({
    account_count: accounts.length,
    requested_fakeid_count: requestedFakeids.length,
    selected_fakeid_count: fakeids.length,
    channel: "client",
    coverage_scope: "broadcast_only",
    credentials: credentialSummary,
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
    await assertNotRateLimited();
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
    await assertNotRateLimited();
    const cutoffTs = Number(options.cutoffTs) > 0
      ? Math.floor(Number(options.cutoffTs))
      : Math.floor(Date.now() / 1000) - Math.floor(options.cutoffHours * 3600);
    const scopeLabel = "最近 " + options.cutoffHours + " 小时";
    try {
      await call(window.api.sync.start({
        fakeids,
        cutoffTs,
        scopeLabel,
        force: options.force,
        channel: "client",
      }));
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
    const description = result.exceptionDetails.exception && result.exceptionDetails.exception.description;
    const errorText = description || result.exceptionDetails.text || "Runtime exception";
    throw new Error(errorText);
  }
  return result.result?.value;
}

function isRunning(state) {
  return state && state.phase === "running";
}

function stateError(state) {
  return String((state && (state.lastError || state.last_error || state.errorMessage || state.message)) || "");
}

function isRateLimited(value) {
  const text = typeof value === "string" ? value : stateError(value);
  return /client_rate_limited|rate.?limit|ret\s*[:=]?\s*-6/i.test(text);
}

function assertSuccessfulTerminalState(label, state) {
  if (!state) throw new Error(`${label} status is missing`);
  const phase = String(state.phase || "");
  if (["error", "failed"].includes(phase)) {
    throw new Error(`${label} ended in ${phase}: ${stateError(state) || "unknown_error"}`);
  }
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
    if (!active) {
      if (label === "sync") {
        assertSuccessfulTerminalState("sync", state.sync);
      } else {
        assertSuccessfulTerminalState("fetch", state.fetch);
        assertSuccessfulTerminalState("resource", state.resource);
      }
      return state;
    }
    if (Date.now() > deadline) throw new Error(`${label} did not finish before timeout`);
    await wait(pollMs);
  }
}

function normalizedRequestedFakeids(args) {
  const values = Array.isArray(args.fakeids) ? args.fakeids : String(args.fakeids).split(",");
  return values.map((item) => String(item).trim()).filter(Boolean);
}

function accountScopeHash(fakeids) {
  return crypto.createHash("sha256").update(`${fakeids.join("\n")}\n`, "utf8").digest("hex");
}

function ledgerSummary(ledger) {
  const rows = Array.isArray(ledger.accounts) ? ledger.accounts : [];
  const count = (status) => rows.filter((item) => item.status === status).length;
  const completedCount = count("completed");
  const rateLimitedCount = count("rate_limited");
  const failedCount = count("failed");
  const pendingCount = rows.length - completedCount - rateLimitedCount - failedCount;
  return {
    requested_count: rows.length,
    completed_count: completedCount,
    pending_count: pendingCount,
    rate_limited_count: rateLimitedCount,
    failed_count: failedCount,
    cycle_complete: rows.length > 0 && completedCount === rows.length,
  };
}

function writeLedgerAtomic(ledgerPath, ledger) {
  ledger.updated_at = new Date().toISOString();
  const summary = ledgerSummary(ledger);
  ledger.summary = summary;
  const globalRateLimit = ledger.last_blocker && ledger.last_blocker.code === "client_rate_limited";
  ledger.status = summary.cycle_complete
    ? "complete"
    : summary.rate_limited_count > 0 || globalRateLimit
      ? "blocked_rate_limited"
      : summary.failed_count > 0
        ? "blocked_failed"
        : "in_progress";
  ledger.secret_values_exposed = false;
  fs.mkdirSync(path.dirname(ledgerPath), { recursive: true });
  const tmpPath = `${ledgerPath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmpPath, `${JSON.stringify(ledger, null, 2)}\n`, "utf8");
  fs.renameSync(tmpPath, ledgerPath);
}

function loadOrCreateLedger(args, requestedFakeids) {
  const ledgerPath = path.resolve(args.completionLedger);
  const scopeHash = accountScopeHash(requestedFakeids);
  const derivedCutoffTs = Math.floor(Date.now() / 1000) - Math.floor(args.cutoffHours * 3600);
  let ledger;
  if (fs.existsSync(ledgerPath)) {
    ledger = JSON.parse(fs.readFileSync(ledgerPath, "utf8"));
    if (ledger.schema_version !== "sanji_client_sync_cycle.v1") {
      throw new Error("sanji_completion_ledger_schema_mismatch");
    }
    if (ledger.cycle_id !== args.cycleId) {
      throw new Error("sanji_completion_ledger_cycle_mismatch");
    }
    if (ledger.account_scope_sha256 !== scopeHash) {
      throw new Error("sanji_completion_ledger_scope_mismatch");
    }
    if (Number(ledger.cutoff_hours) !== Number(args.cutoffHours)) {
      throw new Error("sanji_completion_ledger_cutoff_mismatch");
    }
  } else {
    ledger = {
      schema_version: "sanji_client_sync_cycle.v1",
      cycle_id: args.cycleId,
      source_contract: "sanji_wechat_client.v1",
      channel: "client",
      coverage_scope: "broadcast_only",
      account_scope_sha256: scopeHash,
      cutoff_hours: Number(args.cutoffHours),
      cutoff_ts: Number(args.cutoffTs) > 0 ? Math.floor(args.cutoffTs) : derivedCutoffTs,
      created_at: new Date().toISOString(),
      accounts: requestedFakeids.map((fakeid, index) => ({
        ordinal: index + 1,
        fakeid,
        status: "pending",
        attempts: 0,
      })),
    };
  }
  if (Number(args.cutoffTs) > 0 && Number(ledger.cutoff_ts) !== Math.floor(args.cutoffTs)) {
    throw new Error("sanji_completion_ledger_cutoff_ts_mismatch");
  }
  args.cutoffTs = Number(ledger.cutoff_ts);
  writeLedgerAtomic(ledgerPath, ledger);
  return { ledger, ledgerPath };
}

function updateLedgerAccount(ledger, ledgerPath, fakeid, fields) {
  const row = ledger.accounts.find((item) => item.fakeid === fakeid);
  if (!row) throw new Error(`sanji_completion_ledger_missing_account: ${fakeid}`);
  Object.assign(row, fields);
  writeLedgerAtomic(ledgerPath, ledger);
}

async function runSequentialSync(client, args, target) {
  const requestedFakeids = normalizedRequestedFakeids(args);
  const { ledger, ledgerPath } = loadOrCreateLedger(args, requestedFakeids);
  let globalPreflight;
  try {
    globalPreflight = await evaluate(client, expressionFor("sync-preflight", args));
    const sync = globalPreflight && globalPreflight.sync;
    if (isRunning(sync)) throw new Error("sanji_sync_busy_preflight: an existing sync is still running");
    if (String((sync && sync.phase) || "") === "paused_error" && isRateLimited(sync)) {
      throw new Error("sanji_client_rate_limited_preflight: paused sync is rate limited");
    }
    if (ledger.last_blocker) {
      delete ledger.last_blocker;
      writeLedgerAtomic(ledgerPath, ledger);
    }
  } catch (err) {
    ledger.last_blocker = {
      code: isRateLimited(err.message) ? "client_rate_limited" : "sync_preflight_failed",
      observed_at: new Date().toISOString(),
      message: String(err.message || err).slice(0, 500),
    };
    writeLedgerAtomic(ledgerPath, ledger);
    throw err;
  }

  const readiness = await evaluate(client, expressionFor("credential-readiness", args));
  const readySet = new Set(
    Array.isArray(readiness && readiness.ready_fakeids)
      ? readiness.ready_fakeids.map((item) => String(item)).filter(Boolean)
      : []
  );
  const missingCount = Number(readiness && readiness.credentials && readiness.credentials.missing_or_expired_count) || 0;
  if (args.credentialPolicy === "require-all" && missingCount > 0) {
    throw new Error(`sanji_client_credential_incomplete: ${missingCount} selected account credential(s) are missing or expired`);
  }

  const completedSet = new Set(
    ledger.accounts.filter((item) => item.status === "completed").map((item) => item.fakeid)
  );
  const selectedFakeids = requestedFakeids
    .filter((fakeid) => readySet.has(fakeid) && !completedSet.has(fakeid))
    .slice(0, Math.floor(args.maxClientAccounts));
  const accounts = [];
  let final = null;
  for (let index = 0; index < selectedFakeids.length; index += 1) {
    const fakeid = selectedFakeids[index];
    const row = ledger.accounts.find((item) => item.fakeid === fakeid);
    if (index > 0 && args.interAccountDelayMs > 0) await wait(args.interAccountDelayMs);
    updateLedgerAccount(ledger, ledgerPath, fakeid, {
      status: "running",
      attempts: Number(row.attempts || 0) + 1,
      started_at: new Date().toISOString(),
      finished_at: null,
      last_error: null,
    });
    const accountArgs = {
      ...args,
      fakeids: [fakeid],
      maxClientAccounts: 1,
      credentialPolicy: "require-all",
    };
    try {
      const preflight = await evaluate(client, expressionFor("sync-preflight", accountArgs));
      if (isRunning(preflight && preflight.sync)) {
        throw new Error("sanji_sync_busy_preflight: an existing sync is still running");
      }
      const start = await evaluate(client, expressionFor("sync", accountArgs));
      final = await waitForIdle(client, "sync", args.timeoutMs, args.pollMs);
      let resumeAttempts = 0;
      while (
        String(final && final.sync && final.sync.phase) === "paused_error" &&
        /(^|,)token_expired(,|$)/.test(stateError(final && final.sync)) &&
        resumeAttempts < args.syncResumeAttempts
      ) {
        resumeAttempts += 1;
        await evaluate(client, expressionFor("resume-sync", accountArgs));
        final = await waitForIdle(client, "sync", args.timeoutMs, args.pollMs);
      }
      if (String(final && final.sync && final.sync.phase) === "paused_error") {
        const lastError = stateError(final.sync) || "unknown_error";
        if (isRateLimited(lastError)) {
          throw new Error(`sanji_client_rate_limited: ${fakeid}: ${lastError}`);
        }
        throw new Error(`sync ended in paused_error for ${fakeid}: ${lastError}`);
      }
      const completedAt = new Date().toISOString();
      updateLedgerAccount(ledger, ledgerPath, fakeid, {
        status: "completed",
        phase: String((final && final.sync && final.sync.phase) || "unknown"),
        started: String((start && (start.started || start.already_running)) || "sync"),
        resume_attempts: resumeAttempts,
        finished_at: completedAt,
        last_error: null,
      });
      accounts.push({ fakeid, phase: String(final.sync.phase || "unknown"), resume_attempts: resumeAttempts });
    } catch (err) {
      const rateLimited = isRateLimited(err.message);
      updateLedgerAccount(ledger, ledgerPath, fakeid, {
        status: rateLimited ? "rate_limited" : "failed",
        finished_at: new Date().toISOString(),
        last_error: String(err.message || err).slice(0, 500),
      });
      throw err;
    }
  }

  const summary = ledgerSummary(ledger);
  const safeReadiness = { ...readiness };
  delete safeReadiness.ready_fakeids;
  return {
    ok: true,
    target: { title: target.title, url: target.url },
    first: safeReadiness,
    sequential_sync: {
      ...summary,
      selected_count: selectedFakeids.length,
      missing_or_expired_count: missingCount,
      accounts,
      cycle_id: ledger.cycle_id,
      cutoff_ts: ledger.cutoff_ts,
      account_scope_sha256: ledger.account_scope_sha256,
      completion_ledger_path: ledgerPath,
      secret_values_exposed: false,
    },
    final,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const target = await findSanjiTarget(args.port);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  try {
    await client.send("Runtime.enable");
    if (args.action === "sync-sequential") {
      console.log(JSON.stringify(await runSequentialSync(client, args, target), null, 2));
      return;
    }
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

const isDirectRun = process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
if (isDirectRun) {
  main()
    .then(() => {
      setTimeout(() => process.exit(0), 0);
    })
    .catch((err) => {
      console.error(JSON.stringify({ ok: false, error: err.message }, null, 2));
      process.exit(1);
    });
}

export {
  accountScopeHash,
  expressionFor,
  ledgerSummary,
  loadOrCreateLedger,
  parseArgs,
  runSequentialSync,
};
