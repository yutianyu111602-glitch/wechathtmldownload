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
const DEFAULT_OUT_DIR = resolve(
  REPO_ROOT,
  "tools/stage7_rewrite/reports/docker_internal_login_s139_20260602",
);
const DEFAULT_REGISTRY = resolve(
  REPO_ROOT,
  "tools/stage7_rewrite/registries/weekly_accounts_seed.json",
);

function parseArgs(argv) {
  const args = {
    endpoint: DEFAULT_ENDPOINT,
    profileDir: DEFAULT_PROFILE_DIR,
    authCache: DEFAULT_AUTH_CACHE,
    outDir: DEFAULT_OUT_DIR,
    registry: DEFAULT_REGISTRY,
    waitLoginMs: 300000,
    pollMs: 2000,
    headed: false,
    noWriteCache: false,
    skipLogout: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => argv[++index] || "";
    if (arg === "--endpoint") args.endpoint = next();
    else if (arg === "--profile-dir") args.profileDir = resolve(next());
    else if (arg === "--auth-cache") args.authCache = resolve(next());
    else if (arg === "--out-dir") args.outDir = resolve(next());
    else if (arg === "--registry") args.registry = resolve(next());
    else if (arg === "--wait-login-ms") args.waitLoginMs = Number(next()) || 300000;
    else if (arg === "--poll-ms") args.pollMs = Math.max(500, Number(next()) || 2000);
    else if (arg === "--headed") args.headed = true;
    else if (arg === "--no-write-cache") args.noWriteCache = true;
    else if (arg === "--skip-logout") args.skipLogout = true;
    else if (arg === "--help" || arg === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function usage() {
  return [
    "Usage:",
    "  node tools/stage7_rewrite/scripts/mptext_docker_qr_auth_sync.mjs [options]",
    "",
    "Options:",
    "  --endpoint <url>          Local Docker exporter endpoint, default http://127.0.0.1:17300",
    "  --profile-dir <path>      Dedicated Playwright persistent profile",
    "  --auth-cache <path>       Runtime auth cache JSON to write after QR login",
    "  --out-dir <path>          Report directory for QR screenshots and redacted JSON",
    "  --registry <path>         Weekly account registry for article smoke",
    "  --wait-login-ms <ms>      Wait for scan confirmation and auth key",
    "  --poll-ms <ms>            Auth-key poll interval",
    "  --headed                  Show the browser window",
    "  --no-write-cache          Report only; do not write auth cache",
    "  --skip-logout             Do not call local logout endpoint before login",
  ].join("\n");
}

function normalizeEndpoint(value) {
  return (value || DEFAULT_ENDPOINT).replace(/\/+$/, "");
}

function shortHash(value) {
  return createHash("sha256").update(String(value)).digest("hex").slice(0, 12);
}

function nowIso() {
  return new Date().toISOString();
}

function normalizeKey(value) {
  if (typeof value !== "string") return "";
  const key = value.trim();
  return /^[A-Za-z0-9_-]{16,256}$/.test(key) ? key : "";
}

function loadCachedKey(authCache) {
  if (!existsSync(authCache)) return "";
  try {
    const payload = JSON.parse(readFileSync(authCache, "utf8"));
    return normalizeKey(payload.api_key || payload.auth_key || payload.key || "");
  } catch {
    return "";
  }
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

function writeJson(filePath, payload) {
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

async function launchPersistent(profileDir, headed) {
  mkdirSync(profileDir, { recursive: true });
  try {
    return await chromium.launchPersistentContext(profileDir, {
      channel: "chrome",
      headless: !headed,
      viewport: { width: 1440, height: 1000 },
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    });
  } catch (error) {
    if (headed) throw error;
    return chromium.launchPersistentContext(profileDir, {
      headless: true,
      viewport: { width: 1440, height: 1000 },
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    });
  }
}

async function fetchJsonInPage(page, url, authKey = "") {
  return page.evaluate(
    async ({ targetUrl, key }) => {
      const headers = key ? { "X-Auth-Key": key } : {};
      try {
        const response = await fetch(targetUrl, { headers, credentials: "include" });
        const text = await response.text();
        let payload = null;
        try {
          payload = JSON.parse(text);
        } catch {
          payload = { parse_error: text.slice(0, 200) };
        }
        return { status: response.status, ok: response.ok, payload, textLength: text.length };
      } catch (error) {
        return {
          status: 0,
          ok: false,
          payload: { request_error: String(error).slice(0, 300) },
          textLength: 0,
        };
      }
    },
    { targetUrl: url, key: authKey },
  );
}

async function readAuthKey(page, endpoint) {
  const result = await fetchJsonInPage(page, `${endpoint}/api/public/v1/authkey`);
  const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
  const apiKey = normalizeKey(payload.data);
  return {
    http_status: result.status,
    authkey_endpoint_code: payload.code ?? null,
    authkey_endpoint_ok: payload.code === 0,
    authkey_endpoint_msg: firstString(payload.msg, payload.request_error, payload.parse_error),
    api_key: apiKey,
    api_key_hash: apiKey ? shortHash(apiKey) : "",
    api_key_length: apiKey.length,
  };
}

async function articleSmoke(page, endpoint, registryPath, apiKey) {
  const fakeid = loadProbeFakeid(registryPath);
  if (!fakeid) {
    return {
      probe_fakeid_hash: "",
      article_smoke_decision: "exporter_probe_no_fakeid",
      session_ok: false,
      ret: null,
      err_msg: "no fakeid found in registry",
      article_count: 0,
    };
  }
  const query = new URLSearchParams({ fakeid, begin: "0", size: "1" });
  const result = await fetchJsonInPage(
    page,
    `${endpoint}/api/public/v1/article?${query.toString()}`,
    apiKey,
  );
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
    article_smoke_decision: decision,
    session_ok: decision === "exporter_session_ok" || decision === "exporter_session_reachable_empty",
    ret: baseResp.ret ?? null,
    err_msg: errMsg,
    article_count: articles.length,
  };
}

function writeAuthCache(authCache, apiKey, endpoint, profileDir) {
  writeJson(authCache, {
    schema_version: "mptext_runtime_auth_cache.v1",
    updated_at: nowIso(),
    endpoint,
    source: "docker-qr-playwright-profile",
    profile_dir: profileDir,
    api_key: apiKey,
    api_key_hash: shortHash(apiKey),
  });
}

function safeHeaders(headers) {
  const kept = {};
  for (const key of ["content-type", "content-length", "retkey", "logicret"]) {
    if (headers[key]) kept[key] = headers[key];
  }
  if (headers["set-cookie"]) kept["set-cookie"] = "[redacted-set-cookie]";
  return kept;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return 0;
  }

  const endpoint = normalizeEndpoint(args.endpoint);
  mkdirSync(args.outDir, { recursive: true });
  const livePath = resolve(args.outDir, "docker_qr_auth_live.json");
  const finalPath = resolve(args.outDir, "docker_qr_auth_final.json");
  const qrPagePath = resolve(args.outDir, "docker_qr_auth_page.png");
  const qrOnlyPath = resolve(args.outDir, "docker_qr_auth_qr_only.png");

  const report = {
    schema_version: "mptext_docker_qr_auth_sync.v1",
    generated_at: nowIso(),
    endpoint,
    profile_dir: args.profileDir,
    auth_cache: args.authCache,
    out_dir: args.outDir,
    headless: !args.headed,
    wait_login_ms: args.waitLoginMs,
    state: "starting",
    logout: null,
    qr_page_screenshot: qrPagePath,
    qr_only_screenshot: qrOnlyPath,
    network: [],
    scan_events: [],
    auth: null,
    smoke: null,
    cache_written: false,
    decision: "running",
    error: "",
  };

  let context;
  try {
    const cachedKey = loadCachedKey(args.authCache);
    context = await launchPersistent(args.profileDir, args.headed);
    const page = context.pages()[0] || (await context.newPage());
    page.setDefaultTimeout(30000);
    page.on("response", async (response) => {
      const url = response.url();
      if (!url.includes("/api/web/login") && !url.includes("/api/web/mp/logout")) return;
      const headers = response.headers();
      let body = "";
      try {
        body = await response.text();
      } catch {
        body = "";
      }
      const entry = {
        url,
        status: response.status(),
        headers: safeHeaders(headers),
        body_len: body.length,
        body_hash: body ? shortHash(body) : "",
      };
      if (url.includes("/api/web/login/scan")) {
        try {
          const payload = JSON.parse(body);
          entry.scan_status = payload.status ?? null;
          entry.scan_ret = payload.base_resp?.ret ?? null;
          entry.scan_acct_size = payload.acct_size ?? null;
          report.scan_events.push({
            at: nowIso(),
            status: entry.scan_status,
            ret: entry.scan_ret,
            acct_size: entry.scan_acct_size,
          });
        } catch {}
      }
      report.network.push(entry);
    });

    if (!args.skipLogout && cachedKey) {
      let logout;
      try {
        const response = await fetch(`${endpoint}/api/web/mp/logout`, {
          method: "GET",
          headers: { Cookie: `auth-key=${cachedKey}` },
        });
        const text = await response.text();
        logout = {
          attempted: true,
          http_status: response.status,
          text_len: text.length,
          text_hash: text ? shortHash(text) : "",
        };
      } catch (error) {
        logout = { attempted: true, error: String(error).slice(0, 300) };
      }
      report.logout = {
        ...logout,
        cached_key_hash: shortHash(cachedKey),
        cached_key_length: cachedKey.length,
      };
    } else {
      report.logout = {
        attempted: false,
        reason: args.skipLogout ? "skip_logout_requested" : "no_cached_key",
      };
    }

    await page.goto(`${endpoint}/dashboard/account`, {
      waitUntil: "domcontentloaded",
      timeout: 30000,
    });
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const loginButton = page.getByText("登录公众号").first();
    const loginButtonCount = await page.getByText("登录公众号").count().catch(() => 0);
    report.login_button_count = loginButtonCount;
    if (loginButtonCount > 0) {
      await loginButton.click();
    }

    const qrLocator = page.locator('img[src*="/api/web/login/getqrcode"]').first();
    await qrLocator.waitFor({ state: "visible", timeout: 30000 });
    await page.waitForTimeout(1000);
    await page.screenshot({ path: qrPagePath, fullPage: true });
    await qrLocator.screenshot({ path: qrOnlyPath });
    const imgMeta = await qrLocator.evaluate((img) => ({
      src: img.getAttribute("src"),
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
    }));
    report.qr = {
      ready_at: nowIso(),
      src_hash: imgMeta.src ? shortHash(imgMeta.src) : "",
      natural_width: imgMeta.naturalWidth,
      natural_height: imgMeta.naturalHeight,
    };
    report.state = "qr_ready_waiting_scan";
    writeJson(livePath, report);

    const deadline = Date.now() + Math.max(0, args.waitLoginMs);
    let latestAuth = await readAuthKey(page, endpoint);
    while (!latestAuth.api_key && Date.now() < deadline) {
      await page.waitForTimeout(args.pollMs);
      latestAuth = await readAuthKey(page, endpoint);
      report.auth = {
        http_status: latestAuth.http_status,
        authkey_endpoint_code: latestAuth.authkey_endpoint_code,
        authkey_endpoint_ok: latestAuth.authkey_endpoint_ok,
        authkey_endpoint_msg: latestAuth.authkey_endpoint_msg,
        api_key_present: Boolean(latestAuth.api_key),
        api_key_length: latestAuth.api_key_length,
        api_key_hash: latestAuth.api_key_hash,
      };
      writeJson(livePath, report);
    }

    report.auth = {
      http_status: latestAuth.http_status,
      authkey_endpoint_code: latestAuth.authkey_endpoint_code,
      authkey_endpoint_ok: latestAuth.authkey_endpoint_ok,
      authkey_endpoint_msg: latestAuth.authkey_endpoint_msg,
      api_key_present: Boolean(latestAuth.api_key),
      api_key_length: latestAuth.api_key_length,
      api_key_hash: latestAuth.api_key_hash,
    };

    if (latestAuth.api_key) {
      if (!args.noWriteCache) {
        writeAuthCache(args.authCache, latestAuth.api_key, endpoint, args.profileDir);
        report.cache_written = true;
      }
      report.smoke = await articleSmoke(page, endpoint, args.registry, latestAuth.api_key);
      report.state = "completed";
      report.decision = report.smoke?.session_ok
        ? "docker_qr_auth_key_synced_and_smoke_ok"
        : "docker_qr_auth_key_synced_but_article_smoke_not_ok";
    } else {
      report.state = "timeout";
      report.decision = "docker_qr_login_wait_timeout";
    }
  } catch (error) {
    report.state = "error";
    report.decision = "docker_qr_auth_sync_error";
    report.error = String(error).slice(0, 500);
  } finally {
    report.finished_at = nowIso();
    writeJson(livePath, report);
    writeJson(finalPath, report);
    if (context) await context.close().catch(() => {});
  }

  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  return report.state === "completed" ? 0 : 2;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(String(error));
    process.exit(2);
  },
);
