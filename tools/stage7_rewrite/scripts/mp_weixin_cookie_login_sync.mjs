#!/usr/bin/env node
import { createHash, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(SCRIPT_DIR, "../../..");
const DEFAULT_ENDPOINT = "http://127.0.0.1:17300";
const DEFAULT_PROFILE_DIR = resolve(REPO_ROOT, ".mptext-data/playwright-profile");
const DEFAULT_AUTH_CACHE = resolve(REPO_ROOT, ".mptext-data/kv/auth-key-current.json");
const DEFAULT_COOKIE_DIR = resolve(REPO_ROOT, ".mptext-data/kv/cookie");
const DEFAULT_REGISTRY = resolve(REPO_ROOT, "tools/stage7_rewrite/registries/weekly_accounts_seed.json");
const DEFAULT_REPORT = resolve(
  REPO_ROOT,
  "tools/stage7_rewrite/reports/mp_weixin_cookie_login_sync_s139_20260601/mp_weixin_cookie_login_sync.json",
);
const DEFAULT_SCREENSHOT = resolve(
  REPO_ROOT,
  "tools/stage7_rewrite/reports/mp_weixin_cookie_login_sync_s139_20260601/mp_weixin_login_qr.png",
);

function parseArgs(argv) {
  const args = {
    endpoint: DEFAULT_ENDPOINT,
    profileDir: DEFAULT_PROFILE_DIR,
    authCache: DEFAULT_AUTH_CACHE,
    cookieDir: DEFAULT_COOKIE_DIR,
    registry: DEFAULT_REGISTRY,
    out: DEFAULT_REPORT,
    screenshotOut: DEFAULT_SCREENSHOT,
    waitLoginMs: 0,
    pollMs: 2000,
    headed: false,
    noWrite: false,
    authKey: "",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = () => argv[++index] || "";
    if (arg === "--endpoint") args.endpoint = next();
    else if (arg === "--profile-dir") args.profileDir = resolve(next());
    else if (arg === "--auth-cache") args.authCache = resolve(next());
    else if (arg === "--cookie-dir") args.cookieDir = resolve(next());
    else if (arg === "--registry") args.registry = resolve(next());
    else if (arg === "--out") args.out = resolve(next());
    else if (arg === "--screenshot-out" || arg === "--qr-out") args.screenshotOut = resolve(next());
    else if (arg === "--wait-login-ms") args.waitLoginMs = Number(next()) || 0;
    else if (arg === "--poll-ms") args.pollMs = Math.max(500, Number(next()) || 2000);
    else if (arg === "--headed") args.headed = true;
    else if (arg === "--no-write") args.noWrite = true;
    else if (arg === "--auth-key") args.authKey = normalizeAuthKey(next());
    else if (arg === "--help" || arg === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  return args;
}

function usage() {
  return [
    "Usage:",
    "  node tools/stage7_rewrite/scripts/mp_weixin_cookie_login_sync.mjs [options]",
    "",
    "Options:",
    "  --profile-dir <path>      dedicated Playwright profile, default .mptext-data/playwright-profile",
    "  --cookie-dir <path>       exporter KV cookie dir, default .mptext-data/kv/cookie",
    "  --registry <path>         weekly account registry for article smoke",
    "  --auth-cache <path>       runtime auth cache JSON to write",
    "  --out <path>              redacted progress/final report JSON path",
    "  --qr-out <path>           screenshot path for the QR/login page",
    "  --wait-login-ms <ms>      keep headless browser alive and poll for scan/login",
    "  --poll-ms <ms>            poll interval while waiting",
    "  --headed                  show browser window, off by default",
    "  --no-write                do not write exporter KV/auth cache",
    "  --auth-key <key>          optional fixed exporter auth key for tests only",
  ].join("\n");
}

function normalizeEndpoint(value) {
  return (value || DEFAULT_ENDPOINT).replace(/\/+$/, "");
}

function normalizeAuthKey(value) {
  if (typeof value !== "string") return "";
  const key = value.trim();
  return /^[A-Za-z0-9_-]{16,256}$/.test(key) ? key : "";
}

function shortHash(value) {
  return value ? createHash("sha256").update(value).digest("hex").slice(0, 12) : "";
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

function ensureParent(file) {
  mkdirSync(dirname(file), { recursive: true });
}

function writeJson(file, payload) {
  ensureParent(file);
  writeFileSync(file, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function redactCookieNames(cookies) {
  return Array.from(new Set(cookies.map((cookie) => cookie.name).filter(Boolean))).sort();
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

function extractTokenFromUrl(value) {
  try {
    const url = new URL(value);
    const token = url.searchParams.get("token") || "";
    return /^\d{3,32}$/.test(token) ? token : "";
  } catch {
    return "";
  }
}

async function extractTokenFromPage(page) {
  const fromUrl = extractTokenFromUrl(page.url());
  if (fromUrl) return fromUrl;
  return page.evaluate(() => {
    const html = document.documentElement?.innerHTML || "";
    const patterns = [
      /[?&]token=(\d{3,32})/i,
      /token["']?\s*[:=]\s*["']?(\d{3,32})/i,
      /window\.wx\s*=\s*window\.wx\s*\|\|\s*\{\};[\s\S]{0,2000}?token["']?\s*[:=]\s*["']?(\d{3,32})/i,
    ];
    for (const pattern of patterns) {
      const match = html.match(pattern);
      if (match?.[1]) return match[1];
    }
    const links = Array.from(document.querySelectorAll("a[href]"))
      .map((link) => link.getAttribute("href") || "")
      .join("\n");
    const linkMatch = links.match(/[?&]token=(\d{3,32})/i);
    return linkMatch?.[1] || "";
  });
}

async function snapshotQr(page, screenshotOut) {
  if (!screenshotOut) return "";
  ensureParent(screenshotOut);
  const candidates = [
    "img[src*='scanloginqrcode']",
    "img[src*='qrcode']",
    "canvas",
    ".login__type__container__scan__qrcode",
    ".weui-desktop-qrcheck__qrcode",
  ];
  for (const selector of candidates) {
    const locator = page.locator(selector).first();
    try {
      if ((await locator.count()) > 0 && (await locator.isVisible({ timeout: 1000 }))) {
        await locator.screenshot({ path: screenshotOut });
        return screenshotOut;
      }
    } catch {
      // Fall back to full-page screenshot below.
    }
  }
  await page.screenshot({ path: screenshotOut, fullPage: false });
  return screenshotOut;
}

async function launchPersistent(profileDir, headed) {
  mkdirSync(profileDir, { recursive: true });
  const common = {
    headless: !headed,
    viewport: { width: 1440, height: 1000 },
    args: ["--disable-dev-shm-usage"],
  };
  try {
    return await chromium.launchPersistentContext(profileDir, {
      ...common,
      channel: "chrome",
    });
  } catch (error) {
    if (headed) throw error;
    return chromium.launchPersistentContext(profileDir, common);
  }
}

async function readLoginState(context, page) {
  let token = await extractTokenFromPage(page);
  if (!token) {
    try {
      await page.goto("https://mp.weixin.qq.com/cgi-bin/home?t=home/index&lang=zh_CN", {
        waitUntil: "domcontentloaded",
        timeout: 30000,
      });
      await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
      token = await extractTokenFromPage(page);
    } catch {
      token = "";
    }
  }
  const cookies = await context.cookies("https://mp.weixin.qq.com");
  const liveCookies = cookies.filter((cookie) => cookie.value && cookie.value !== "EXPIRED");
  const hasSessionCookie = liveCookies.some((cookie) =>
    ["slave_sid", "slave_user", "cert", "ticket", "sig"].includes(cookie.name),
  );
  return {
    token,
    cookies: liveCookies,
    loginDetected: Boolean(token && hasSessionCookie),
  };
}

function cookieExpiresText(expires) {
  if (typeof expires !== "number" || !Number.isFinite(expires) || expires <= 0) return "";
  return new Date(expires * 1000).toUTCString();
}

function toCookieEntity(cookie) {
  const entity = {
    name: cookie.name,
    value: cookie.value,
    path: cookie.path || "/",
  };
  if (cookie.domain) entity.domain = cookie.domain;
  const expires = cookieExpiresText(cookie.expires);
  if (expires) {
    entity.expires = expires;
    entity.expires_timestamp = Math.round(cookie.expires * 1000);
  }
  if (cookie.secure) entity.secure = "true";
  if (cookie.httpOnly) entity.httponly = "true";
  if (cookie.sameSite) entity.samesite = cookie.sameSite;
  return entity;
}

function writeExporterKv({ args, endpoint, token, cookies }) {
  const authKey = normalizeAuthKey(args.authKey) || randomUUID().replace(/-/g, "");
  const cookiePayload = {
    token,
    cookies: cookies.map(toCookieEntity),
  };
  mkdirSync(args.cookieDir, { recursive: true });
  const cookieKvPath = resolve(args.cookieDir, authKey);
  writeJson(cookieKvPath, cookiePayload);
  writeJson(args.authCache, {
    schema_version: "mptext_runtime_auth_cache.v1",
    updated_at: nowIso(),
    endpoint,
    source: "mp-weixin-playwright-cookie-import",
    profile_dir: args.profileDir,
    cookie_kv_path: cookieKvPath,
    api_key: authKey,
    api_key_hash: shortHash(authKey),
  });
  return {
    authKey,
    cookieKvPath,
  };
}

async function fetchJson(url, authKey) {
  const headers = authKey ? { "X-Auth-Key": authKey } : {};
  try {
    const response = await fetch(url, { headers });
    const text = await response.text();
    try {
      return {
        ok: response.ok,
        status: response.status,
        payload: JSON.parse(text),
      };
    } catch {
      return {
        ok: response.ok,
        status: response.status,
        payload: { parse_error: text.slice(0, 200) },
      };
    }
  } catch (error) {
    return {
      ok: false,
      status: 0,
      payload: { request_error: String(error).slice(0, 300) },
    };
  }
}

async function articleSmoke(endpoint, registryPath, authKey) {
  const fakeid = loadProbeFakeid(registryPath);
  if (!fakeid) {
    return {
      probe_fakeid_hash: "",
      article_probe_decision: "exporter_probe_no_fakeid",
      session_ok: false,
      ret: null,
      err_msg: "",
      article_count: 0,
      article_probe_error: "no fakeid found in registry",
    };
  }
  const query = new URLSearchParams({ fakeid, begin: "0", size: "1" });
  const result = await fetchJson(`${endpoint}/api/public/v1/article?${query}`, authKey);
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
    article_probe_decision: decision,
    session_ok: decision === "exporter_session_ok",
    ret: baseResp.ret ?? null,
    err_msg: errMsg,
    article_count: articles.length,
    article_probe_error: result.ok ? "" : errMsg,
  };
}

function buildReport(args, endpoint, fields) {
  const cookies = fields.cookies || [];
  const token = fields.token || "";
  const authKey = fields.authKey || "";
  return {
    schema_version: "mp_weixin_cookie_login_sync.v1",
    generated_at: nowIso(),
    endpoint,
    mode: "mp-weixin-cookie-login-sync",
    profile_dir: args.profileDir,
    headless: !args.headed,
    wait_login_ms: args.waitLoginMs,
    poll_ms: args.pollMs,
    auth_cache: args.authCache,
    cookie_dir: args.cookieDir,
    registry: args.registry,
    screenshot_path: fields.screenshotPath || "",
    token_present: Boolean(token),
    token_length: token.length,
    token_hash: shortHash(token),
    mp_cookie_count: cookies.length,
    mp_cookie_names: redactCookieNames(cookies),
    login_detected: Boolean(fields.loginDetected),
    auth_key_present: Boolean(authKey),
    auth_key_length: authKey.length,
    auth_key_hash: shortHash(authKey),
    cache_written: Boolean(fields.cacheWritten),
    cookie_kv_written: Boolean(fields.cookieKvWritten),
    cookie_kv_path: fields.cookieKvPath || "",
    ...(fields.smoke || {}),
    decision: fields.decision || "mp_weixin_login_pending",
    error: fields.error || "",
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
  let report = buildReport(args, endpoint, {});
  try {
    context = await launchPersistent(args.profileDir, args.headed);
    const page = context.pages()[0] || (await context.newPage());
    await page.goto("https://mp.weixin.qq.com/", { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(1500);

    let screenshotPath = await snapshotQr(page, args.screenshotOut);
    let state = await readLoginState(context, page);
    report = buildReport(args, endpoint, {
      ...state,
      screenshotPath,
      decision: state.loginDetected ? "mp_weixin_login_detected" : "mp_weixin_qr_ready_waiting_scan",
    });
    if (args.out) writeJson(args.out, report);

    const deadline = Date.now() + Math.max(0, args.waitLoginMs);
    while (!state.loginDetected && Date.now() < deadline) {
      await page.waitForTimeout(args.pollMs);
      screenshotPath = await snapshotQr(page, args.screenshotOut);
      state = await readLoginState(context, page);
      report = buildReport(args, endpoint, {
        ...state,
        screenshotPath,
        decision: state.loginDetected ? "mp_weixin_login_detected" : "mp_weixin_qr_waiting_scan",
      });
      if (args.out) writeJson(args.out, report);
    }

    if (!state.loginDetected) {
      report = buildReport(args, endpoint, {
        ...state,
        screenshotPath,
        decision: args.waitLoginMs > 0 ? "mp_weixin_login_wait_timeout" : "mp_weixin_qr_ready_waiting_scan",
      });
      if (args.out) writeJson(args.out, report);
      process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
      return 2;
    }

    let writeResult = { authKey: "", cookieKvPath: "" };
    if (!args.noWrite) {
      writeResult = writeExporterKv({
        args,
        endpoint,
        token: state.token,
        cookies: state.cookies,
      });
    }
    const smoke = writeResult.authKey ? await articleSmoke(endpoint, args.registry, writeResult.authKey) : {};
    report = buildReport(args, endpoint, {
      ...state,
      screenshotPath,
      authKey: writeResult.authKey,
      cookieKvPath: writeResult.cookieKvPath,
      cacheWritten: Boolean(writeResult.authKey),
      cookieKvWritten: Boolean(writeResult.cookieKvPath && existsSync(writeResult.cookieKvPath)),
      smoke,
      decision: args.noWrite
        ? "mp_weixin_login_detected_no_write"
        : smoke.session_ok
          ? "mp_weixin_cookie_imported_and_smoke_ok"
          : "mp_weixin_cookie_imported_smoke_failed",
    });
    if (args.out) writeJson(args.out, report);
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    return 0;
  } catch (error) {
    report = buildReport(args, endpoint, {
      decision: "mp_weixin_cookie_login_sync_error",
      error: String(error).slice(0, 300),
    });
    if (args.out) writeJson(args.out, report);
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    return 2;
  } finally {
    if (context) await context.close().catch(() => {});
  }
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(String(error));
    process.exit(2);
  },
);
