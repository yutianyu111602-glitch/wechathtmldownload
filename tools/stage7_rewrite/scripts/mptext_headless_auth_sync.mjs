#!/usr/bin/env node
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, "../../..");
const DEFAULT_ENDPOINT = "http://127.0.0.1:17300";
const DEFAULT_PROFILE_DIR = resolve(REPO_ROOT, ".mptext-data/playwright-profile");
const DEFAULT_AUTH_CACHE = resolve(REPO_ROOT, ".mptext-data/kv/auth-key-current.json");
const DEFAULT_REGISTRY = resolve(REPO_ROOT, "tools/stage7_rewrite/registries/weekly_accounts_seed.json");

function parseArgs(argv) {
  const args = {
    endpoint: DEFAULT_ENDPOINT,
    profileDir: DEFAULT_PROFILE_DIR,
    authCache: DEFAULT_AUTH_CACHE,
    registry: DEFAULT_REGISTRY,
    out: "",
    screenshotOut: "",
    waitLoginMs: 0,
    pollMs: 2000,
    headed: false,
    noWriteCache: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => argv[++index] || "";
    if (arg === "--endpoint") args.endpoint = next();
    else if (arg === "--profile-dir") args.profileDir = resolve(next());
    else if (arg === "--auth-cache") args.authCache = resolve(next());
    else if (arg === "--registry") args.registry = resolve(next());
    else if (arg === "--out") args.out = resolve(next());
    else if (arg === "--screenshot-out") args.screenshotOut = resolve(next());
    else if (arg === "--wait-login-ms") args.waitLoginMs = Number(next()) || 0;
    else if (arg === "--poll-ms") args.pollMs = Math.max(500, Number(next()) || 2000);
    else if (arg === "--headed") args.headed = true;
    else if (arg === "--no-write-cache") args.noWriteCache = true;
    else if (arg === "--help" || arg === "-h") {
      args.help = true;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return args;
}

function usage() {
  return [
    "Usage:",
    "  node tools/stage7_rewrite/scripts/mptext_headless_auth_sync.mjs [options]",
    "",
    "Options:",
    "  --endpoint <url>          mptext exporter endpoint",
    "  --profile-dir <path>      dedicated Playwright persistent profile",
    "  --auth-cache <path>       runtime auth cache JSON to write",
    "  --registry <path>         weekly account registry for article smoke",
    "  --out <path>              redacted report JSON path",
    "  --wait-login-ms <ms>      wait/poll for QR login completion",
    "  --poll-ms <ms>            login poll interval",
    "  --screenshot-out <path>   save a page screenshot for manual QR/login bootstrap",
    "  --headed                  show the browser window for first QR login",
    "  --no-write-cache          report only; do not write auth cache",
  ].join("\n");
}

function normalizeEndpoint(value) {
  return (value || DEFAULT_ENDPOINT).replace(/\/+$/, "");
}

function normalizeKey(value) {
  if (typeof value !== "string") return "";
  const key = value.trim();
  return /^[A-Za-z0-9_-]{16,256}$/.test(key) ? key : "";
}

function shortHash(value) {
  return createHash("sha256").update(value).digest("hex").slice(0, 12);
}

function nowIso() {
  return new Date().toISOString();
}

function firstString(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function loadProbeFakeid(registryPath) {
  if (!existsSync(registryPath)) return "";
  const payload = JSON.parse(readFileSync(registryPath, "utf8"));
  const accounts = Array.isArray(payload) ? payload : payload.accounts;
  if (!Array.isArray(accounts)) return "";
  for (const account of accounts) {
    const fakeid = firstString(account?.fakeid);
    if (fakeid) return fakeid;
  }
  return "";
}

async function launchPersistent(profileDir, headed) {
  mkdirSync(profileDir, { recursive: true });
  try {
    return await chromium.launchPersistentContext(profileDir, {
      channel: "chrome",
      headless: !headed,
      viewport: { width: 1440, height: 1000 },
    });
  } catch (error) {
    if (headed) throw error;
    return chromium.launchPersistentContext(profileDir, {
      headless: true,
      viewport: { width: 1440, height: 1000 },
    });
  }
}

async function fetchJsonInPage(page, url, authKey = "") {
  return page.evaluate(
    async ({ targetUrl, key }) => {
      const headers = key ? { "X-Auth-Key": key } : {};
      try {
        const response = await fetch(targetUrl, {
          headers,
          credentials: "include",
        });
        const text = await response.text();
        let payload = null;
        try {
          payload = JSON.parse(text);
        } catch {
          payload = { parse_error: text.slice(0, 200) };
        }
        return {
          status: response.status,
          ok: response.ok,
          payload,
        };
      } catch (error) {
        return {
          status: 0,
          ok: false,
          payload: { request_error: String(error).slice(0, 300) },
        };
      }
    },
    { targetUrl: url, key: authKey },
  );
}

async function readAuthKey(page, endpoint) {
  const result = await fetchJsonInPage(page, `${endpoint}/api/public/v1/authkey`);
  const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
  return {
    http_status: result.status,
    authkey_endpoint_code: payload.code,
    authkey_endpoint_ok: payload.code === 0,
    authkey_endpoint_msg: payload.msg || payload.request_error || "",
    api_key: normalizeKey(payload.data),
  };
}

async function waitForAuthKey(page, endpoint, waitLoginMs, pollMs) {
  const deadline = Date.now() + Math.max(0, waitLoginMs);
  let latest = await readAuthKey(page, endpoint);
  while (!latest.api_key && Date.now() < deadline) {
    await page.waitForTimeout(pollMs);
    latest = await readAuthKey(page, endpoint);
  }
  return latest;
}

function writeAuthCache(authCache, apiKey, endpoint, profileDir) {
  mkdirSync(dirname(authCache), { recursive: true });
  const payload = {
    schema_version: "mptext_runtime_auth_cache.v1",
    updated_at: nowIso(),
    endpoint,
    source: "playwright-persistent-profile",
    profile_dir: profileDir,
    api_key: apiKey,
    api_key_hash: shortHash(apiKey),
  };
  writeFileSync(authCache, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

async function articleSmoke(page, endpoint, registryPath, apiKey) {
  const fakeid = loadProbeFakeid(registryPath);
  if (!fakeid) {
    return {
      probe_fakeid_hash: "",
      decision: "exporter_probe_no_fakeid",
      session_ok: false,
      ret: null,
      err_msg: "",
      article_count: 0,
      error: "no fakeid found in registry",
    };
  }
  const query = new URLSearchParams({ fakeid, begin: "0", size: "1" });
  const result = await fetchJsonInPage(page, `${endpoint}/api/public/v1/article?${query}`, apiKey);
  const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
  const baseResp = payload.base_resp && typeof payload.base_resp === "object" ? payload.base_resp : {};
  const articles = Array.isArray(payload.articles) ? payload.articles : [];
  const errMsg = firstString(baseResp.err_msg, payload.request_error, payload.parse_error);
  let decision = "exporter_session_error";
  if (String(errMsg).toLowerCase().includes("invalid session")) decision = "exporter_session_invalid";
  else if (articles.length > 0) decision = "exporter_session_ok";
  else if (baseResp.ret === 0 || baseResp.ret === "0") decision = "exporter_session_reachable_empty";
  return {
    probe_fakeid_hash: shortHash(fakeid),
    decision,
    session_ok: decision === "exporter_session_ok",
    ret: baseResp.ret ?? null,
    err_msg: errMsg,
    article_count: articles.length,
    error: result.ok ? "" : errMsg,
  };
}

function redactedReport({ args, endpoint, auth, smoke, cacheWritten, screenshotSaved, error }) {
  const apiKey = auth.api_key || "";
  return {
    schema_version: "mptext_headless_auth_sync.v1",
    generated_at: nowIso(),
    mode: "headless-auth-sync",
    endpoint,
    dashboard_api_url: `${endpoint}/dashboard/api`,
    profile_dir: args.profileDir,
    auth_cache: args.authCache,
    headless: !args.headed,
    wait_login_ms: args.waitLoginMs,
    screenshot_path: screenshotSaved || "",
    api_key_present: Boolean(apiKey),
    api_key_length: apiKey.length,
    api_key_hash: apiKey ? shortHash(apiKey) : "",
    authkey_endpoint_code: auth.authkey_endpoint_code,
    authkey_endpoint_ok: auth.authkey_endpoint_ok,
    authkey_endpoint_msg: auth.authkey_endpoint_msg,
    cache_written: cacheWritten,
    decision: apiKey ? "headless_auth_key_synced" : "headless_auth_key_missing",
    sync_key_ok: Boolean(apiKey),
    error: error || "",
    ...(smoke || {}),
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return 0;
  }
  const endpoint = normalizeEndpoint(args.endpoint);
  let context;
  let report;
  try {
    context = await launchPersistent(args.profileDir, args.headed);
    const page = context.pages()[0] || (await context.newPage());
    await page.goto(`${endpoint}/dashboard/api`, { waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1500);
    let screenshotSaved = "";
    if (args.screenshotOut) {
      mkdirSync(dirname(args.screenshotOut), { recursive: true });
      await page.screenshot({ path: args.screenshotOut, fullPage: false });
      screenshotSaved = args.screenshotOut;
    }
    const auth = await waitForAuthKey(page, endpoint, args.waitLoginMs, args.pollMs);
    let cacheWritten = false;
    let smoke = null;
    if (auth.api_key) {
      if (!args.noWriteCache) {
        writeAuthCache(args.authCache, auth.api_key, endpoint, args.profileDir);
        cacheWritten = true;
      }
      smoke = await articleSmoke(page, endpoint, args.registry, auth.api_key);
    }
    report = redactedReport({ args, endpoint, auth, smoke, cacheWritten, screenshotSaved });
  } catch (error) {
    report = redactedReport({
      args,
      endpoint,
      auth: {
        authkey_endpoint_code: null,
        authkey_endpoint_ok: false,
        authkey_endpoint_msg: "",
        api_key: "",
      },
      smoke: null,
      cacheWritten: false,
      screenshotSaved: "",
      error: String(error).slice(0, 300),
    });
  } finally {
    if (context) await context.close().catch(() => {});
  }
  const text = `${JSON.stringify(report, null, 2)}\n`;
  if (args.out) {
    mkdirSync(dirname(args.out), { recursive: true });
    writeFileSync(args.out, text, "utf8");
  }
  process.stdout.write(text);
  return report.sync_key_ok ? 0 : 2;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(String(error));
    process.exit(2);
  },
);
