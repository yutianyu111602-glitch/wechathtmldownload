import http from "node:http";
import crypto from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { URL } from "node:url";
import { gzipSync } from "node:zlib";
import { createDeepSeekClient } from "./deepSeekClient.mjs";
import { createDjInterviewStore } from "./interviewStore.mjs";
import { createSoundStore } from "./soundStore.mjs";
import { renderAtlasDetailPage } from "./atlasDetailPage.mjs";
import { renderAtlasGraphPage } from "./atlasGraphPage.mjs";
import { renderAtlasIdentityPage } from "./atlasIdentityPage.mjs";
import { renderAtlasLocalPage } from "./atlasLocalPage.mjs";
import { renderAtlasPage } from "./atlasPage.mjs";
import { WeeklyActivityDataStore } from "./dataStore.mjs";
import { renderItemPage, renderLandingPage, renderPreviewPage } from "./previewPage.mjs";
import { Stage7AtlasStore } from "./stage7AtlasStore.mjs";
import { Stage7AtlasSqliteStore } from "./stage7AtlasSqliteStore.mjs";
import { getArtist, getArtistById, getVenue, getSearch, getNeighborhood, getPath, getEntity, getSourceEvidence, getStarmapLens, getRadioExternalLinks, getRadioPrograms, resolveCrossDbEntity, getMergeMapStats } from "./miniappAtlasApi.mjs";

const modulePath = fileURLToPath(import.meta.url);
const moduleDir = path.dirname(modulePath);
const huaidjLogoPath = path.resolve(moduleDir, "../assets/huaidj-logo-nav-512x128.png");
const ATLAS_STARMAP_DIR = path.resolve(moduleDir, "../data/atlas_starmap");
const ATLAS_SESSION_COOKIE = "atlas_session";
const ATLAS_SESSION_TTL_MS = 4 * 60 * 60 * 1000;
const ATLAS_FALLBACK_CHALLENGE_TTL_MS = 5 * 60 * 1000;
const ATLAS_HONEY_RE = /(?:^|\/)(?:atlas|graph)\.(?:sqlite|db|json|dump|bak|old|log)$|\/(?:export|dump|bulk|full-graph)(?:\/|$)|^\/api\/v1\/stage7\/(?:export|full-graph|bulk)(?:\/|$)/i;
const ATLAS_ASSET_TYPES = new Map([
  [".avif", "image/avif"],
  [".gif", "image/gif"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".png", "image/png"],
  [".webp", "image/webp"],
]);
const ATLAS_STARMAP_ASSET_TYPES = new Map([
  [".js", "text/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".webp", "image/webp"],
]);
const WEEKLY_JSON_CACHE_TTL_MS = 300_000; // 5 min (data refreshes weekly, aggressive TTL is safe)
const WEEKLY_JSON_CACHE_MAX_ENTRIES = 200;
const weeklyJsonCache = new Map();
const weeklyJsonPending = new Map();

// Miniapp Atlas API uses in-memory JSON index (no native modules needed)

function securityHeaders(extra = {}) {
  return {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    ...extra,
  };
}

function htmlSecurityHeaders(extra = {}) {
  return securityHeaders({
    "Content-Security-Policy":
      "default-src 'self'; script-src 'self' 'unsafe-inline' https://esm.sh https://cdn.jsdelivr.net https://challenges.cloudflare.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
    ...extra,
  });
}

function normalizeFilterParam(value) {
  const raw = String(value || "").trim();
  return raw.toLowerCase() === "unknown" ? "" : raw;
}

function sendJson(res, statusCode, payload, extraHeaders = {}, { req, gzip = true, cacheMaxAge = 0 } = {}) {
  const raw = Buffer.from(JSON.stringify(payload), "utf8");
  const baseHeaders = {
    ...securityHeaders(),
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    ...(cacheMaxAge > 0
      ? { "Cache-Control": `public, max-age=${cacheMaxAge}, s-maxage=${Math.max(cacheMaxAge, 120)}`, "CDN-Cache-Control": `max-age=${Math.max(cacheMaxAge, 120)}` }
      : { "Cache-Control": "no-store", Pragma: "no-cache" }),
    ...extraHeaders,
  };
  const wantsGzip = gzip && req && /\bgzip\b/i.test(String(req.headers?.["accept-encoding"] || ""));
  if (wantsGzip && raw.length > 1024) {
    const gzipped = gzipSync(raw);
    res.writeHead(statusCode, {
      ...baseHeaders,
      "Content-Encoding": "gzip",
      Vary: "Accept-Encoding",
      "Content-Length": String(gzipped.length),
    });
    res.end(gzipped);
    return;
  }
  res.writeHead(statusCode, {
    ...baseHeaders,
    "Content-Length": String(raw.length),
  });
  res.end(raw);
}

function pruneWeeklyJsonCache(now = Date.now()) {
  for (const [key, value] of weeklyJsonCache) {
    if (value.expiresAt <= now) weeklyJsonCache.delete(key);
  }
  while (weeklyJsonCache.size > WEEKLY_JSON_CACHE_MAX_ENTRIES) {
    let oldestKey = null;
    let oldestExp = Infinity;
    for (const [key, value] of weeklyJsonCache) {
      if (value.expiresAt < oldestExp) {
        oldestExp = value.expiresAt;
        oldestKey = key;
      }
    }
    if (oldestKey) {
      weeklyJsonCache.delete(oldestKey);
    } else {
      break;
    }
  }
}

async function weeklyJsonBody(cacheKey, ttlMs, producer) {
  const now = Date.now();
  const cached = weeklyJsonCache.get(cacheKey);
  if (cached && cached.expiresAt > now) {
    return { body: cached.body, cacheStatus: "HIT" };
  }

  const coalesce = weeklyJsonPending.get(cacheKey);
  if (coalesce) {
    try {
      const body = await coalesce;
      return { body, cacheStatus: "COALESCED" };
    } catch {
      // pending promise failed — fall through to retry
    }
  }

  const pending = (async () => {
    const payload = await producer();
    const body = JSON.stringify(payload);
    weeklyJsonCache.set(cacheKey, {
      body,
      expiresAt: Date.now() + ttlMs,
    });
    pruneWeeklyJsonCache();
    return body;
  })();
  weeklyJsonPending.set(cacheKey, pending);
  try {
    const body = await pending;
    return { body, cacheStatus: "MISS" };
  } finally {
    if (weeklyJsonPending.get(cacheKey) === pending) {
      weeklyJsonPending.delete(cacheKey);
    }
  }
}

function sendJsonBody(req, res, statusCode, body, extraHeaders = {}, cacheMaxAge = 0) {
  const raw = Buffer.from(body, "utf8");
  const wantsGzip = /\bgzip\b/i.test(String(req.headers["accept-encoding"] || ""));
  const isCloudContainerCall = Boolean(req.headers["x-wx-service"]);
  const cacheHeaders = cacheMaxAge > 0
    ? { "Cache-Control": `public, max-age=${cacheMaxAge}, s-maxage=${Math.max(cacheMaxAge, 120)}`, "CDN-Cache-Control": `max-age=${Math.max(cacheMaxAge, 120)}` }
    : {};
  const baseHeaders = {
    ...securityHeaders(),
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    ...cacheHeaders,
    ...extraHeaders,
  };
  if (wantsGzip && !isCloudContainerCall && raw.length > 1024) {
    const gzipped = gzipSync(raw);
    res.writeHead(statusCode, {
      ...baseHeaders,
      "Content-Encoding": "gzip",
      Vary: "Accept-Encoding",
      "Content-Length": String(gzipped.length),
    });
    res.end(gzipped);
    return;
  }
  res.writeHead(statusCode, {
    ...baseHeaders,
    "Content-Length": String(raw.length),
  });
  res.end(raw);
}

function weeklyCacheKey(pathname, searchParams, acceptedParams) {
  const pairs = [];
  for (const name of acceptedParams) {
    const value = canonicalWeeklyCacheValue(name, searchParams.get(name));
    if (value !== null && value !== "") pairs.push(`${name}=${value}`);
  }
  return `${pathname}?${pairs.join("&")}`;
}

function normalizeCacheInt(value, { fallback, min, max }) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
}

function canonicalWeeklyCacheValue(name, rawValue) {
  if (rawValue === null || rawValue === "") return "";
  if (name === "limit") {
    const value = normalizeCacheInt(rawValue, { fallback: 100, min: 1, max: 100 });
    return value === 100 ? "" : String(value);
  }
  if (name === "cursor") {
    const value = normalizeCacheInt(rawValue, { fallback: 0, min: 0, max: Number.MAX_SAFE_INTEGER });
    return value === 0 ? "" : String(value);
  }
  if (name === "lookbackDays") {
    const value = normalizeCacheInt(rawValue, { fallback: 0, min: 0, max: 45 });
    return value === 0 ? "" : String(value);
  }
  return String(rawValue);
}

async function sendCachedWeeklyJson(req, res, cacheKey, producer, ttlMs = WEEKLY_JSON_CACHE_TTL_MS) {
  const result = await weeklyJsonBody(cacheKey, ttlMs, producer);
  const cacheAge = Math.floor(ttlMs / 1000);
  sendJsonBody(req, res, 200, result.body, {
    "Cache-Control": `public, max-age=${Math.floor(cacheAge / 4)}, stale-while-revalidate=${cacheAge}`,
    "CDN-Cache-Control": `max-age=${Math.max(cacheAge, 120)}`,
    "X-Weekly-Cache": result.cacheStatus,
  }, cacheAge);
}

function sendError(res, statusCode, code, message, details = {}, extraHeaders = {}) {
  sendJson(res, statusCode, {
    error: {
      code,
      message,
      details,
    },
  }, extraHeaders);
}

function sendHtml(res, statusCode, body) {
  res.writeHead(statusCode, {
    ...htmlSecurityHeaders(),
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "public, max-age=60",
  });
  res.end(body);
}

function createStage7Store(options, env) {
  if (options.stage7Store) return options.stage7Store;
  if (options.stage7SqliteDbPath || env.STAGE7_ATLAS_SQLITE_DB || env.ATLAS_CORE_SQLITE_DB || env.ATLAS_SERVING_SQLITE_DB || env.ATLAS_USE_SERVING_READ_MODEL) {
    return new Stage7AtlasSqliteStore({ ...options, env });
  }
  return new Stage7AtlasStore({ ...options, env });
}

function hasMethod(target, methodName) {
  return target && typeof target[methodName] === "function";
}

const MAX_JSON_BODY_BYTES = 5 * 1024 * 1024; // 5MB

async function readJsonBody(req) {
  const contentLength = parseInt(String(req.headers["content-length"] || "0"), 10);
  if (contentLength > MAX_JSON_BODY_BYTES) {
    throw Object.assign(new Error("Request body too large"), {
      statusCode: 413,
      code: "BODY_TOO_LARGE",
    });
  }
  const chunks = [];
  let totalBytes = 0;
  for await (const chunk of req) {
    totalBytes += chunk.length;
    if (totalBytes > MAX_JSON_BODY_BYTES) {
      throw Object.assign(new Error("Request body too large"), {
        statusCode: 413,
        code: "BODY_TOO_LARGE",
      });
    }
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  return raw ? JSON.parse(raw) : {};
}

function getClientIp(req) {
  const forwarded = String(req.headers["cf-connecting-ip"] || req.headers["x-forwarded-for"] || "").split(",")[0].trim();
  return forwarded || req.socket.remoteAddress || "";
}

function cookieValue(req, name) {
  const raw = String(req.headers.cookie || "");
  for (const part of raw.split(";")) {
    const index = part.indexOf("=");
    if (index === -1) continue;
    const key = part.slice(0, index).trim();
    if (key === name) return decodeURIComponent(part.slice(index + 1).trim());
  }
  return "";
}

function b64url(input) {
  return Buffer.from(input).toString("base64url");
}

function signSessionPayload(payload, secret) {
  return crypto.createHmac("sha256", secret).update(payload).digest("base64url");
}

function coarseIp(ip) {
  const raw = String(ip || "");
  if (raw.includes(".")) return raw.split(".").slice(0, 3).join(".");
  if (raw.includes(":")) return raw.split(":").slice(0, 4).join(":");
  return raw;
}

function userAgentHash(req) {
  return crypto.createHash("sha256").update(String(req.headers["user-agent"] || "")).digest("base64url").slice(0, 16);
}

function fallbackClientBinding(req) {
  return crypto.createHash("sha256").update(`${coarseIp(getClientIp(req))}|${userAgentHash(req)}`).digest("base64url").slice(0, 24);
}

function fallbackProofHash(payload, signature, proof) {
  return crypto.createHash("sha256").update(`${payload}.${signature}.${String(proof)}`).digest("hex");
}

function leadingZeroBits(hex) {
  let count = 0;
  for (const char of String(hex || "")) {
    const value = Number.parseInt(char, 16);
    if (!Number.isFinite(value)) return -1;
    if (value === 0) {
      count += 4;
      continue;
    }
    return count + (4 - value.toString(2).length);
  }
  return count;
}

function createAtlasSecurity(env) {
  const requireSession = String(env.ATLAS_REQUIRE_SESSION || env.ATLAS_PUBLIC_REQUIRE_SESSION || "").trim() === "1";
  const turnstileSecret = String(env.ATLAS_TURNSTILE_SECRET_KEY || env.TURNSTILE_SECRET_KEY || "").trim();
  const siteKey = String(env.ATLAS_TURNSTILE_SITE_KEY || env.TURNSTILE_SITE_KEY || "").trim();
  const sessionSecret = String(env.ATLAS_SESSION_SECRET || turnstileSecret || "").trim();
  const cookieSecure = String(env.ATLAS_COOKIE_SECURE || "1").trim() !== "0";
  const fallbackEnabled = String(env.ATLAS_FALLBACK_VERIFICATION || "1").trim() !== "0";
  const fallbackDifficulty = Math.min(Math.max(Number.parseInt(String(env.ATLAS_FALLBACK_POW_DIFFICULTY || "12"), 10) || 12, 8), 20);
  const fallbackConfigured = Boolean(fallbackEnabled && sessionSecret);
  const testMode = String(env.NODE_ENV || "").trim() === "test" && String(env.ATLAS_TURNSTILE_TEST_MODE || "").trim() === "pass";
  const buckets = new Map();

  function issue(req) {
    const now = Date.now();
    const data = {
      v: 1,
      iat: now,
      exp: now + ATLAS_SESSION_TTL_MS,
      nonce: crypto.randomBytes(16).toString("base64url"),
      ua: userAgentHash(req),
      ip: coarseIp(getClientIp(req)),
    };
    const payload = b64url(JSON.stringify(data));
    return `${payload}.${signSessionPayload(payload, sessionSecret)}`;
  }

  function verify(req) {
    if (!requireSession) return { ok: true, reason: "disabled" };
    if (!sessionSecret) return { ok: false, reason: "server_not_configured" };
    const token = cookieValue(req, ATLAS_SESSION_COOKIE);
    if (!token || !token.includes(".")) return { ok: false, reason: "missing" };
    const [payload, signature] = token.split(".", 2);
    const expected = signSessionPayload(payload, sessionSecret);
    const sigBuf = Buffer.from(signature || "");
    const expectedBuf = Buffer.from(expected);
    if (sigBuf.length !== expectedBuf.length || !crypto.timingSafeEqual(sigBuf, expectedBuf)) {
      return { ok: false, reason: "bad_signature" };
    }
    let data;
    try {
      data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    } catch {
      return { ok: false, reason: "bad_payload" };
    }
    if (!data?.exp || Date.now() > Number(data.exp)) return { ok: false, reason: "expired" };
    if (data.ua !== userAgentHash(req)) return { ok: false, reason: "ua_changed" };
    if (data.ip && data.ip !== coarseIp(getClientIp(req))) return { ok: false, reason: "ip_changed" };
    return { ok: true, reason: "valid", sessionHash: crypto.createHash("sha256").update(token).digest("hex").slice(0, 16) };
  }

  function checkRate(req, pathname, sessionHash = "") {
    const now = Date.now();
    const windowMs = 60_000;
    const limit = pathname.includes("/random-walk")
      ? 5
      : pathname.includes("/graph/mobile-profile")
        ? 30
        : pathname.includes("/graph/profile")
        ? 10
        : pathname.includes("/graph/subgraph") || pathname.includes("/graph/expand")
          ? 20
          : pathname.includes("/graph/seed") || pathname.endsWith("/search")
            ? 30
            : 60;
    const key = `${sessionHash || getClientIp(req)}:${pathname.split("?")[0]}`;
    const bucket = buckets.get(key) || { start: now, count: 0 };
    if (now - bucket.start > windowMs) {
      bucket.start = now;
      bucket.count = 0;
    }
    bucket.count += 1;
    buckets.set(key, bucket);
    if (buckets.size > 5000 || now % 300_000 < windowMs) {
      for (const [candidateKey, value] of buckets) {
        if (now - value.start > windowMs * 2) buckets.delete(candidateKey);
      }
    }
    return bucket.count <= limit ? { ok: true, limit, remaining: Math.max(0, limit - bucket.count) } : { ok: false, limit, remaining: 0 };
  }

  async function verifyTurnstile(token, remoteIp) {
    if (testMode && token === "test-pass") return { ok: true, mode: "test" };
    if (!turnstileSecret) return { ok: false, reason: "missing_secret" };
    if (!String(token || "").trim()) return { ok: false, reason: "missing_token" };
    const form = new URLSearchParams();
    form.set("secret", turnstileSecret);
    form.set("response", String(token));
    if (remoteIp) form.set("remoteip", remoteIp);
    const response = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
      method: "POST",
      body: form,
    });
    const result = await response.json();
    return { ok: Boolean(result.success), reason: result["error-codes"] || [] };
  }

  function fallbackChallenge(req) {
    if (!fallbackConfigured) return { ok: false, reason: "fallback_not_configured" };
    const now = Date.now();
    const data = {
      v: 1,
      iat: now,
      exp: now + ATLAS_FALLBACK_CHALLENGE_TTL_MS,
      nonce: crypto.randomBytes(18).toString("base64url"),
      bind: fallbackClientBinding(req),
    };
    const payload = b64url(JSON.stringify(data));
    return {
      ok: true,
      payload,
      signature: signSessionPayload(payload, sessionSecret),
      difficulty: fallbackDifficulty,
      expiresInSeconds: Math.floor(ATLAS_FALLBACK_CHALLENGE_TTL_MS / 1000),
    };
  }

  function verifyFallback(req, body) {
    if (!fallbackConfigured) return { ok: false, reason: "fallback_not_configured" };
    const payload = String(body?.payload || "");
    const signature = String(body?.signature || "");
    const proof = String(body?.proof || "");
    if (!payload || !signature || !proof || proof.length > 96) return { ok: false, reason: "bad_request" };

    const expected = signSessionPayload(payload, sessionSecret);
    const sigBuf = Buffer.from(signature);
    const expectedBuf = Buffer.from(expected);
    if (sigBuf.length !== expectedBuf.length || !crypto.timingSafeEqual(sigBuf, expectedBuf)) {
      return { ok: false, reason: "bad_signature" };
    }

    let data;
    try {
      data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    } catch {
      return { ok: false, reason: "bad_payload" };
    }
    if (data?.v !== 1 || !data?.exp || Date.now() > Number(data.exp)) return { ok: false, reason: "expired" };
    if (data.bind !== fallbackClientBinding(req)) return { ok: false, reason: "client_changed" };
    const bits = leadingZeroBits(fallbackProofHash(payload, signature, proof));
    if (bits < fallbackDifficulty) return { ok: false, reason: "bad_proof", difficulty: fallbackDifficulty };
    return { ok: true, reason: "valid", difficulty: fallbackDifficulty };
  }

  return {
    requireSession,
    siteKey,
    configured: !requireSession || Boolean(sessionSecret && (turnstileSecret || testMode || fallbackConfigured)),
    cookieSecure,
    fallbackConfigured,
    fallbackDifficulty,
    issue,
    verify,
    checkRate,
    verifyTurnstile,
    fallbackChallenge,
    verifyFallback,
  };
}

function isAtlasProtectedApi(pathname) {
  return (
    pathname.startsWith("/api/v1/stage7/") ||
    pathname.startsWith("/api/v1/atlas/family/") ||
    pathname.startsWith("/api/v1/atlas/evidence/")
  );
}

function atlasSessionCookie(value, security) {
  const secure = security.cookieSecure ? "; Secure" : "";
  return `${ATLAS_SESSION_COOKIE}=${encodeURIComponent(value)}; Max-Age=${Math.floor(ATLAS_SESSION_TTL_MS / 1000)}; Path=/; HttpOnly; SameSite=Lax${secure}`;
}

async function sendPng(res, filePath) {
  const body = await readFile(filePath);
  res.writeHead(200, {
    ...securityHeaders(),
    "Content-Type": "image/png",
    "Cache-Control": "public, max-age=86400",
  });
  res.end(body);
}

const ASSETS_DIR = path.resolve(moduleDir, "../assets");

async function sendAsset(reqPath, res) {
  let relativePath = "";
  try {
    relativePath = decodeURIComponent(reqPath.replace(/^\/assets\/?/, ""));
    if (/%[0-9a-fA-F]{2}/.test(relativePath)) {
      try { relativePath = decodeURIComponent(relativePath); } catch {}
    }
  } catch {
    sendError(res, 400, "ASSET_BAD_PATH", "Asset path is invalid.");
    return;
  }
  if (!relativePath || relativePath.includes("\0")) {
    sendError(res, 404, "ASSET_NOT_FOUND", "Asset was not found.");
    return;
  }
  const resolved = path.resolve(ASSETS_DIR, relativePath);
  if (resolved !== ASSETS_DIR && !resolved.startsWith(ASSETS_DIR + path.sep)) {
    sendError(res, 403, "ASSET_FORBIDDEN", "Asset path is outside the assets directory.");
    return;
  }
  const ext = path.extname(resolved).toLowerCase();
  const contentType = ATLAS_ASSET_TYPES.get(ext);
  if (!contentType) {
    sendError(res, 403, "ASSET_TYPE_FORBIDDEN", "Asset type is not allowed.");
    return;
  }
  try {
    const body = await readFile(resolved);
    res.writeHead(200, {
      ...securityHeaders(),
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=86400, immutable",
    });
    res.end(body);
  } catch {
    sendError(res, 404, "ASSET_NOT_FOUND", "Asset was not found.");
  }
}

async function sendAtlasAsset(reqPath, res, env) {
  const rootRaw = String(env.ATLAS_PUBLIC_ASSET_DIR || env.ATLAS_GRAPH_PUBLIC_ASSET_DIR || "").trim();
  if (!rootRaw) {
    sendError(res, 404, "ATLAS_ASSET_DIR_DISABLED", "Atlas public asset directory is not configured.");
    return;
  }
  let relativePath = "";
  try {
    relativePath = decodeURIComponent(reqPath.replace(/^\/atlas-assets\/?/, ""));
    if (/%[0-9a-fA-F]{2}/.test(relativePath)) {
      try { relativePath = decodeURIComponent(relativePath); } catch {}
    }
  } catch {
    sendError(res, 400, "ATLAS_ASSET_BAD_PATH", "Atlas asset path is invalid.");
    return;
  }
  if (!relativePath || relativePath.includes("\0")) {
    sendError(res, 404, "ATLAS_ASSET_NOT_FOUND", "Atlas asset was not found.");
    return;
  }
  const root = path.resolve(rootRaw);
  const resolved = path.resolve(root, relativePath);
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    sendError(res, 403, "ATLAS_ASSET_FORBIDDEN", "Atlas asset path is outside the public asset directory.");
    return;
  }
  const contentType = ATLAS_ASSET_TYPES.get(path.extname(resolved).toLowerCase());
  if (!contentType) {
    sendError(res, 403, "ATLAS_ASSET_TYPE_FORBIDDEN", "Atlas asset type is not public.");
    return;
  }
  try {
    const body = await readFile(resolved);
    res.writeHead(200, {
      ...securityHeaders(),
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=86400, immutable",
      "X-Robots-Tag": "noindex, noarchive",
    });
    res.end(body);
  } catch {
    sendError(res, 404, "ATLAS_ASSET_NOT_FOUND", "Atlas asset was not found.");
  }
}

function atlasStarmapRoot(env) {
  return path.resolve(String(env.ATLAS_STARMAP_ASSET_DIR || ATLAS_STARMAP_DIR).trim());
}

async function sendAtlasStarmapPage(res, env) {
  const root = atlasStarmapRoot(env);
  const indexPath = path.join(root, "index.html");
  try {
    const body = await readFile(indexPath, "utf8");
    res.writeHead(200, {
      ...htmlSecurityHeaders(),
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "public, max-age=60",
    });
    res.end(body);
  } catch {
    sendError(res, 503, "ATLAS_STARMAP_NOT_BAKED", "Atlas starmap web build is not available.");
  }
}

async function sendAtlasStarmapAsset(reqPath, res, env) {
  let relativePath = "";
  try {
    relativePath = decodeURIComponent(reqPath.replace(/^\/atlas-starmap-assets\/?/, ""));
    if (/%[0-9a-fA-F]{2}/.test(relativePath)) {
      try { relativePath = decodeURIComponent(relativePath); } catch {}
    }
  } catch {
    sendError(res, 400, "ATLAS_STARMAP_BAD_PATH", "Atlas starmap asset path is invalid.");
    return;
  }
  if (!relativePath || relativePath.includes("\0")) {
    sendError(res, 404, "ATLAS_STARMAP_ASSET_NOT_FOUND", "Atlas starmap asset was not found.");
    return;
  }

  const root = atlasStarmapRoot(env);
  const resolved = path.resolve(root, relativePath);
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    sendError(res, 403, "ATLAS_STARMAP_ASSET_FORBIDDEN", "Atlas starmap asset path is outside the public asset directory.");
    return;
  }

  const contentType = ATLAS_STARMAP_ASSET_TYPES.get(path.extname(resolved).toLowerCase());
  if (!contentType) {
    sendError(res, 403, "ATLAS_STARMAP_ASSET_TYPE_FORBIDDEN", "Atlas starmap asset type is not public.");
    return;
  }

  try {
    const body = await readFile(resolved);
    const cacheHeader = path.basename(resolved) === "atlas_layout.json"
      ? "public, max-age=300"
      : "public, max-age=86400, immutable";
    res.writeHead(200, {
      ...securityHeaders(),
      "Content-Type": contentType,
      "Cache-Control": cacheHeader,
      "X-Robots-Tag": "noindex, noarchive",
    });
    res.end(body);
  } catch {
    sendError(res, 404, "ATLAS_STARMAP_ASSET_NOT_FOUND", "Atlas starmap asset was not found.");
  }
}

const POSTER_ALLOWED_DOMAINS = new Set([
  "mmbiz.qpic.cn",
  "mmbiz.qlogo.cn",
  "mmecoa.qpic.cn",
  "static.zhihu.com",
  "pic1.zhimg.com",
  "pic2.zhimg.com",
  "pic3.zhimg.com",
  "pic4.zhimg.com",
  "sns-webpic-qc.xhscdn.com",
  "ci.xiaohongshu.com",
  "s3-us-west-2.amazonaws.com",
  "weekly-api-255880-4-1371956557.sh.run.tcloudbase.com",
]);
const POSTER_MAX_BYTES = 5 * 1024 * 1024; // 5MB
const POSTER_FETCH_TIMEOUT_MS = 15000;

async function sendPosterProxy(res, sourceUrl) {
  let host;
  let fetchUrl = sourceUrl;
  try {
    const parsed = new URL(sourceUrl);
    host = parsed.hostname;
    // WeChat/qpic CDNs reject or fail plain-http hotlinking server-side; upgrade to https.
    if (parsed.protocol === "http:") {
      parsed.protocol = "https:";
      fetchUrl = parsed.toString();
    }
  } catch {
    sendError(res, 400, "POSTER_BAD_URL", "Poster URL is invalid.");
    return;
  }
  if (!POSTER_ALLOWED_DOMAINS.has(host)) {
    sendError(res, 403, "POSTER_DOMAIN_BLOCKED", `Poster domain "${host}" is not allowed.`);
    return;
  }

  const upstream = await fetch(fetchUrl, {
    headers: {
      "User-Agent": "HUAIDJ-Weekly-PosterProxy/1.0",
      Accept: "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    },
    signal: AbortSignal.timeout(POSTER_FETCH_TIMEOUT_MS),
    redirect: "follow",
  });

  if (!upstream.ok || !upstream.body) {
    sendError(res, upstream.status || 502, "POSTER_FETCH_FAILED", "Poster image could not be loaded.");
    return;
  }

  const body = Buffer.from(await upstream.arrayBuffer());
  if (body.length > POSTER_MAX_BYTES) {
    sendError(res, 413, "POSTER_TOO_LARGE", "Poster image exceeds maximum size.");
    return;
  }

  const contentType = upstream.headers.get("content-type") || "image/jpeg";
  res.writeHead(200, {
    "Content-Type": contentType,
    "Cache-Control": "public, max-age=3600",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(body);
}

export function createServer(options = {}) {
  const env = options.env || process.env;
  const store = options.store || new WeeklyActivityDataStore(options);
  const stage7Store = createStage7Store(options, env);
  const atlasSecurity = createAtlasSecurity(env);
  const llmClient = options.llmClient || createDeepSeekClient(env);
  const soundStore = options.soundStore || createSoundStore({ env });
  const interviewStore = options.interviewStore || createDjInterviewStore({ env });
  const isLlmEnrichEnabled = () => String(env.DEEPSEEK_ENRICH_ENABLED || "false").toLowerCase() === "true";
  const llmStatus = () =>
    typeof llmClient.publicStatus === "function"
      ? llmClient.publicStatus()
      : { provider: "deepseek", configured: false };

  return http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
      const pathname = url.pathname;

      if (req.method === "OPTIONS") {
        res.writeHead(204, {
          ...securityHeaders(),
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, X-WX-SERVICE",
        });
        res.end();
        return;
      }

      const isAllowedPost =
        req.method === "POST" &&
        (pathname === "/api/v1/atlas/session" ||
          pathname === "/api/v1/atlas/session/fallback" ||
          pathname === "/api/v1/stage7/local/adjudication" ||
          pathname === "/api/v1/stage7/local/geocode-review" ||
          pathname === "/api/v1/atlas/dj-interviews" ||
          pathname === "/api/v1/weekly/sounds" ||
          pathname === "/api/v1/weekly/sounds/enrich");
      if (req.method !== "GET" && !isAllowedPost) {
        sendError(res, 405, "METHOD_NOT_ALLOWED", "Only GET is enabled for the public MVP.");
        return;
      }

      if (ATLAS_HONEY_RE.test(pathname)) {
        sendError(res, 403, "ATLAS_HONEY_ENDPOINT", "This Atlas endpoint is not public.");
        return;
      }

      if (pathname === "/healthz") {
        sendJson(res, 200, { ok: true, service: "weekly-api", llm: llmStatus() });
        return;
      }

      if (pathname === "/api/v1/atlas/session/status") {
        const session = atlasSecurity.verify(req);
        sendJson(res, 200, {
          schemaVersion: "stage7_atlas_api.session_status.v1",
          requireSession: atlasSecurity.requireSession,
          configured: atlasSecurity.configured,
          hasSession: Boolean(session.ok && atlasSecurity.requireSession),
          siteKey: atlasSecurity.siteKey,
          fallbackChallengeEnabled: atlasSecurity.fallbackConfigured,
          fallbackDifficulty: atlasSecurity.fallbackDifficulty,
          safety: {
            turnstileSecretExposed: false,
            darkDatabaseExposed: false,
            bulkExportEnabled: false,
          },
        });
        return;
      }

      if (pathname === "/api/v1/atlas/session/fallback-challenge") {
        if (!atlasSecurity.requireSession) {
          sendJson(res, 200, {
            schemaVersion: "stage7_atlas_api.fallback_challenge.v1",
            ok: true,
            requireSession: false,
            safety: { darkDatabaseExposed: false, bulkExportEnabled: false },
          });
          return;
        }
        const challenge = atlasSecurity.fallbackChallenge(req);
        if (!challenge.ok) {
          sendError(res, 503, "ATLAS_FALLBACK_NOT_CONFIGURED", "Atlas fallback verification is not configured.", { reason: challenge.reason });
          return;
        }
        sendJson(res, 200, {
          schemaVersion: "stage7_atlas_api.fallback_challenge.v1",
          ok: true,
          algorithm: "sha256-leading-zero-bits",
          payload: challenge.payload,
          signature: challenge.signature,
          difficulty: challenge.difficulty,
          expiresInSeconds: challenge.expiresInSeconds,
          safety: {
            turnstileSecretExposed: false,
            darkDatabaseExposed: false,
            bulkExportEnabled: false,
          },
        });
        return;
      }

      if (pathname === "/api/v1/atlas/session/fallback") {
        if (!atlasSecurity.requireSession) {
          sendJson(res, 200, {
            schemaVersion: "stage7_atlas_api.session_result.v1",
            ok: true,
            requireSession: false,
            safety: { turnstileSecretExposed: false, darkDatabaseExposed: false },
          });
          return;
        }
        if (!atlasSecurity.fallbackConfigured) {
          sendError(res, 503, "ATLAS_FALLBACK_NOT_CONFIGURED", "Atlas fallback verification is not configured.");
          return;
        }
        const body = await readJsonBody(req);
        const result = atlasSecurity.verifyFallback(req, body);
        if (!result.ok) {
          sendError(res, 403, "ATLAS_FALLBACK_FAILED", "Atlas fallback verification failed.", { reason: result.reason });
          return;
        }
        sendJson(
          res,
          200,
          {
            schemaVersion: "stage7_atlas_api.session_result.v1",
            ok: true,
            expiresInSeconds: Math.floor(ATLAS_SESSION_TTL_MS / 1000),
            safety: {
              turnstileSecretExposed: false,
              darkDatabaseExposed: false,
            },
          },
          { "Set-Cookie": atlasSessionCookie(atlasSecurity.issue(req), atlasSecurity) },
        );
        return;
      }

      if (pathname === "/api/v1/atlas/session") {
        if (!atlasSecurity.requireSession) {
          sendJson(res, 200, {
            schemaVersion: "stage7_atlas_api.session_result.v1",
            ok: true,
            requireSession: false,
            safety: { turnstileSecretExposed: false },
          });
          return;
        }
        if (!atlasSecurity.configured) {
          sendError(res, 503, "ATLAS_SESSION_NOT_CONFIGURED", "Atlas session gate is enabled but server-side Turnstile/session secrets are not configured.");
          return;
        }
        const body = await readJsonBody(req);
        const result = await atlasSecurity.verifyTurnstile(body.token, getClientIp(req));
        if (!result.ok) {
          sendError(res, 403, "TURNSTILE_FAILED", "Atlas verification failed.", { reason: result.reason });
          return;
        }
        sendJson(
          res,
          200,
          {
            schemaVersion: "stage7_atlas_api.session_result.v1",
            ok: true,
            expiresInSeconds: Math.floor(ATLAS_SESSION_TTL_MS / 1000),
            safety: {
              turnstileSecretExposed: false,
              darkDatabaseExposed: false,
            },
          },
          { "Set-Cookie": atlasSessionCookie(atlasSecurity.issue(req), atlasSecurity) },
        );
        return;
      }

      if (isAtlasProtectedApi(pathname) && atlasSecurity.requireSession) {
        const session = atlasSecurity.verify(req);
        if (!session.ok) {
          sendError(res, 403, "ATLAS_SESSION_REQUIRED", "Atlas data APIs require a verified session.", {
            reason: session.reason,
            siteKey: atlasSecurity.siteKey,
          });
          return;
        }
        const rate = atlasSecurity.checkRate(req, pathname, session.sessionHash);
        if (!rate.ok) {
          sendError(res, 429, "ATLAS_RATE_LIMITED", "Atlas API rate limit exceeded.", { limit: rate.limit, retryAfterSeconds: 60 }, { "Retry-After": "60" });
          return;
        }
      }

      if (pathname.startsWith("/assets/")) {
        await sendAsset(pathname, res);
        return;
      }

      if (pathname.startsWith("/atlas-assets/")) {
        await sendAtlasAsset(pathname, res, env);
        return;
      }

      if (pathname.startsWith("/atlas-starmap-assets/")) {
        await sendAtlasStarmapAsset(pathname, res, env);
        return;
      }

      if (pathname === "/") {
        sendHtml(res, 200, renderLandingPage());
        return;
      }

      if (pathname === "/preview") {
        const selectedCity = normalizeFilterParam(url.searchParams.get("cityKey"));
        const selectedDate = normalizeFilterParam(url.searchParams.get("date"));
        const lang = url.searchParams.get("lang") || "";
        const [current, cities, dates, dateScope] = await Promise.all([
          store.getCurrent({
            cityKey: selectedCity || undefined,
            date: selectedDate || undefined,
            limit: 50,
          }),
          store.getCities(),
          store.getDates(),
          selectedCity
            ? store.getCurrent({
                cityKey: selectedCity,
                limit: 50,
              })
            : Promise.resolve(null),
        ]);
        sendHtml(
          res,
          200,
          renderPreviewPage({
            current,
            cities,
            dates,
            dateScope,
            selectedCity,
            selectedDate,
            lang,
          }),
        );
        return;
      }

      if (pathname === "/atlas") {
        sendHtml(res, 200, renderAtlasPage());
        return;
      }

      if (pathname === "/atlas/graph") {
        sendHtml(res, 200, renderAtlasGraphPage());
        return;
      }

      if (pathname === "/atlas/starmap") {
        await sendAtlasStarmapPage(res, env);
        return;
      }

      if (pathname === "/atlas/identity") {
        sendHtml(res, 200, renderAtlasIdentityPage());
        return;
      }

      if (pathname === "/atlas/local") {
        sendHtml(res, 200, renderAtlasLocalPage());
        return;
      }

      const atlasDetailMatch = pathname.match(/^\/atlas\/(articles|entities|events)\/(.+)$/);
      if (atlasDetailMatch) {
        sendHtml(res, 200, renderAtlasDetailPage(atlasDetailMatch[1], decodeURIComponent(atlasDetailMatch[2])));
        return;
      }

      const previewItemMatch = pathname.match(/^\/preview\/items\/([^/]+)$/);
      if (previewItemMatch) {
        const item = await store.getItem(decodeURIComponent(previewItemMatch[1]));
        if (!item) {
          sendError(res, 404, "ITEM_NOT_FOUND", "Weekly activity item was not found.");
          return;
        }
        sendHtml(res, 200, renderItemPage(item, { lang: url.searchParams.get("lang") || "" }));
        return;
      }

      if (pathname === "/api/v1/weekly/manifest") {
        await sendCachedWeeklyJson(
          req,
          res,
          weeklyCacheKey(pathname, url.searchParams, []),
          () => store.getManifest(),
          60_000,
        );
        return;
      }

      if (pathname === "/api/v1/weekly/club-overviews") {
        await sendCachedWeeklyJson(
          req,
          res,
          weeklyCacheKey(pathname, url.searchParams, []),
          () => store.getClubOverviews(),
          60_000,
        );
        return;
      }

      if (pathname === "/api/v1/weekly/column") {
        const columnData = await store.getColumnItems({
          tag: url.searchParams.get("tag") || undefined,
          lang: url.searchParams.get("lang") || "zh",
        });
        sendJson(res, 200, columnData, {}, { req, cacheMaxAge: 300 });
        return;
      }

      if (pathname === "/api/v1/stage7/manifest") {
        sendJson(res, 200, await stage7Store.getManifest());
        return;
      }

      if (pathname === "/api/v1/stage7/search") {
        sendJson(
          res,
          200,
        await stage7Store.search({
          q: url.searchParams.get("q") || "",
          limit: url.searchParams.get("limit") || undefined,
          kind: url.searchParams.get("kind") || undefined,
        }),
      );
      return;
      }

      if (pathname === "/api/v1/stage7/local/status") {
        if (!hasMethod(stage7Store, "getLocalDbStatus")) {
          sendError(res, 404, "LOCAL_SQLITE_DISABLED", "Local SQLite atlas store is not enabled.");
          return;
        }
        sendJson(res, 200, await stage7Store.getLocalDbStatus());
        return;
      }

      if (pathname === "/api/v1/stage7/local/map") {
        if (!hasMethod(stage7Store, "getMap")) {
          sendError(res, 404, "LOCAL_SQLITE_DISABLED", "Local SQLite atlas store is not enabled.");
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getMap({
            limit: url.searchParams.get("limit") || undefined,
            status: url.searchParams.get("status") || undefined,
            city: url.searchParams.get("city") || undefined,
            q: url.searchParams.get("q") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/stage7/local/geocode-review") {
        if (!hasMethod(stage7Store, "getGeocodeReview")) {
          sendError(res, 404, "LOCAL_SQLITE_DISABLED", "Local SQLite atlas store is not enabled.");
          return;
        }
        if (req.method === "POST") {
          if (!hasMethod(stage7Store, "recordGeocodeReviewAction")) {
            sendError(res, 404, "LOCAL_SQLITE_DISABLED", "Local SQLite atlas store is not enabled.");
            return;
          }
          const body = await readJsonBody(req);
          sendJson(res, 200, await stage7Store.recordGeocodeReviewAction(body));
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getGeocodeReview({
            limit: url.searchParams.get("limit") || undefined,
            bucket: url.searchParams.get("bucket") || undefined,
            q: url.searchParams.get("q") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/stage7/local/adjudication-ledger") {
        if (!hasMethod(stage7Store, "getAdjudicationLedger")) {
          sendError(res, 404, "LOCAL_SQLITE_DISABLED", "Local SQLite atlas store is not enabled.");
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getAdjudicationLedger({
            limit: url.searchParams.get("limit") || undefined,
            itemId: url.searchParams.get("itemId") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/stage7/local/adjudication") {
        if (!hasMethod(stage7Store, "recordAdjudicationAction")) {
          sendError(res, 404, "LOCAL_SQLITE_DISABLED", "Local SQLite atlas store is not enabled.");
          return;
        }
        const body = await readJsonBody(req);
        sendJson(res, 200, await stage7Store.recordAdjudicationAction(body));
        return;
      }

      if (pathname === "/api/v1/stage7/overview") {
        sendJson(res, 200, await stage7Store.getOverview({ sampleLimit: url.searchParams.get("sampleLimit") || undefined }));
        return;
      }

      if (pathname === "/api/v1/stage7/identity-review") {
        sendJson(
          res,
          200,
          await stage7Store.getIdentityReview({
            limit: url.searchParams.get("limit") || undefined,
            queue: url.searchParams.get("queue") || undefined,
            bucket: url.searchParams.get("bucket") || undefined,
            domain: url.searchParams.get("domain") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/atlas/family/profile") {
        if (!hasMethod(stage7Store, "getAtlasFamilyProfile")) {
          sendError(res, 404, "ATLAS_FAMILY_API_DISABLED", "Atlas family profile API is not enabled for this store.");
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getAtlasFamilyProfile({
            q: url.searchParams.get("q") || "",
            id: url.searchParams.get("id") || "",
            limit: url.searchParams.get("limit") || undefined,
            eventLimit: url.searchParams.get("eventLimit") || undefined,
            collaboratorLimit: url.searchParams.get("collaboratorLimit") || undefined,
            venueLimit: url.searchParams.get("venueLimit") || undefined,
            articleLimit: url.searchParams.get("articleLimit") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/atlas/family/relationships") {
        if (!hasMethod(stage7Store, "getAtlasFamilyRelationships")) {
          sendError(res, 404, "ATLAS_FAMILY_RELATIONSHIPS_DISABLED", "Atlas family relationships API is not enabled for this store.");
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getAtlasFamilyRelationships({
            q: url.searchParams.get("q") || "",
            id: url.searchParams.get("id") || "",
            limit: url.searchParams.get("limit") || undefined,
          }),
        );
        return;
      }

      const atlasEvidenceMatch = pathname.match(/^\/api\/v1\/atlas\/evidence\/(.+)$/);
      if (atlasEvidenceMatch) {
        const evidenceId = decodeURIComponent(atlasEvidenceMatch[1]);
        const evidence = hasMethod(stage7Store, "getAtlasEvidence")
          ? await stage7Store.getAtlasEvidence(evidenceId)
          : await getSourceEvidence(evidenceId);
        const fallbackEvidence = evidence || await getSourceEvidence(evidenceId);
        if (!evidence) {
          if (!fallbackEvidence) {
            sendError(res, 404, "ATLAS_EVIDENCE_NOT_FOUND", "Atlas public evidence was not found.");
            return;
          }
          sendJson(res, 200, fallbackEvidence, {}, { req, cacheMaxAge: 300 });
          return;
        }
        sendJson(res, 200, evidence, {}, { req, cacheMaxAge: 300 });
        return;
      }

      const stage7DetailMatch = pathname.match(/^\/api\/v1\/stage7\/(articles|entities|events)\/(.+)$/);
      if (stage7DetailMatch) {
        const detail = await stage7Store.getDetail(stage7DetailMatch[1], decodeURIComponent(stage7DetailMatch[2]), {
          relatedLimit: url.searchParams.get("relatedLimit") || undefined,
        });
        if (!detail) {
          sendError(res, 404, "STAGE7_DETAIL_NOT_FOUND", "Stage7 atlas detail row was not found.", {
            kind: stage7DetailMatch[1],
          });
          return;
        }
        sendJson(res, 200, detail);
        return;
      }

      if (pathname === "/api/v1/stage7/recommendations") {
        sendJson(res, 200, await stage7Store.getRecommendations({ limit: url.searchParams.get("limit") || undefined }));
        return;
      }

      if (pathname === "/api/v1/stage7/vector-router/status") {
        sendJson(res, 200, await stage7Store.getVectorRouterStatus());
        return;
      }

      if (pathname === "/api/v1/stage7/graph-rag/answers") {
        sendJson(res, 200, await stage7Store.getGraphRagAnswers({ limit: url.searchParams.get("limit") || undefined }));
        return;
      }

      if (pathname === "/api/v1/stage7/graph/seed") {
        if (!hasMethod(stage7Store, "getGraphSeed")) {
          sendError(res, 404, "GRAPH_API_DISABLED", "Read-only Atlas graph API is not enabled for this store.");
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getGraphSeed({
            q: url.searchParams.get("q") || "",
            kind: url.searchParams.get("kind") || undefined,
            limit: url.searchParams.get("limit") || undefined,
            lod: url.searchParams.get("lod") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/stage7/graph/profile") {
        if (!hasMethod(stage7Store, "getGraphEntityProfile")) {
          sendError(res, 404, "GRAPH_PROFILE_API_DISABLED", "Read-only Atlas graph profile API is not enabled for this store.");
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getGraphEntityProfile({
            q: url.searchParams.get("q") || "",
            id: url.searchParams.get("id") || "",
            limit: url.searchParams.get("limit") || undefined,
            sourceLimit: url.searchParams.get("sourceLimit") || undefined,
            eventLimit: url.searchParams.get("eventLimit") || undefined,
            collaboratorLimit: url.searchParams.get("collaboratorLimit") || undefined,
            venueLimit: url.searchParams.get("venueLimit") || undefined,
            articleLimit: url.searchParams.get("articleLimit") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/stage7/graph/mobile-profile") {
        if (!hasMethod(stage7Store, "getGraphMobileProfile")) {
          sendError(res, 404, "GRAPH_MOBILE_PROFILE_API_DISABLED", "Read-only Atlas graph mobile profile API is not enabled for this store.");
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getGraphMobileProfile({
            q: url.searchParams.get("q") || "",
            id: url.searchParams.get("id") || "",
            limit: url.searchParams.get("limit") || undefined,
            eventLimit: url.searchParams.get("eventLimit") || undefined,
            collaboratorLimit: url.searchParams.get("collaboratorLimit") || undefined,
            venueLimit: url.searchParams.get("venueLimit") || undefined,
            articleLimit: url.searchParams.get("articleLimit") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/stage7/graph/subgraph" || pathname === "/api/v1/stage7/graph/expand") {
        if (!hasMethod(stage7Store, "getGraphSubgraph")) {
          sendError(res, 404, "GRAPH_API_DISABLED", "Read-only Atlas graph API is not enabled for this store.");
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getGraphSubgraph({
            nodeId: url.searchParams.get("nodeId") || "",
            kind: url.searchParams.get("kind") || undefined,
            id: url.searchParams.get("id") || undefined,
            depth: url.searchParams.get("depth") || undefined,
            limit: url.searchParams.get("limit") || undefined,
            lod: url.searchParams.get("lod") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/stage7/graph/random-walk") {
        if (!hasMethod(stage7Store, "getGraphRandomWalk")) {
          sendError(res, 404, "GRAPH_API_DISABLED", "Read-only Atlas graph API is not enabled for this store.");
          return;
        }
        sendJson(
          res,
          200,
          await stage7Store.getGraphRandomWalk({
            nodeId: url.searchParams.get("nodeId") || "",
            kind: url.searchParams.get("kind") || undefined,
            id: url.searchParams.get("id") || undefined,
            steps: url.searchParams.get("steps") || undefined,
            fanout: url.searchParams.get("fanout") || undefined,
            limit: url.searchParams.get("limit") || undefined,
            lod: url.searchParams.get("lod") || undefined,
          }),
        );
        return;
      }

      const stage7ListMatch = pathname.match(/^\/api\/v1\/stage7\/(articles|entities|events)$/);
      if (stage7ListMatch) {
        sendJson(
          res,
          200,
          await stage7Store.listKind(stage7ListMatch[1], {
            q: url.searchParams.get("q") || "",
            limit: url.searchParams.get("limit") || undefined,
            cursor: url.searchParams.get("cursor") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/weekly/llm/status") {
        sendJson(res, 200, {
          schemaVersion: "weekly_activity_api.llm_status.v1",
          llm: llmStatus(),
        });
        return;
      }

      if (pathname === "/api/v1/weekly/llm/materialized-summary") {
        const summary = await store.getLlmSummary();
        if (!summary) {
          sendError(res, 404, "LLM_SUMMARY_NOT_FOUND", "Materialized LLM summary was not found.");
          return;
        }
        sendJson(res, 200, summary);
        return;
      }

      if (pathname === "/api/v1/weekly/llm/materialized-enrichments") {
        const index = await store.getLlmEnrichmentIndex();
        if (!index) {
          sendError(res, 404, "LLM_ENRICHMENTS_NOT_FOUND", "Materialized LLM enrichment index was not found.");
          return;
        }
        sendJson(res, 200, index);
        return;
      }

      const materializedEnrichmentMatch = pathname.match(/^\/api\/v1\/weekly\/llm\/materialized-enrichments\/([^/]+)$/);
      if (materializedEnrichmentMatch) {
        const enrichment = await store.getLlmEnrichment(decodeURIComponent(materializedEnrichmentMatch[1]));
        if (!enrichment) {
          sendError(res, 404, "LLM_ENRICHMENT_NOT_FOUND", "Materialized LLM enrichment was not found.");
          return;
        }
        sendJson(res, 200, enrichment);
        return;
      }

      if (pathname === "/api/v1/weekly/llm/enrich") {
        if (!isLlmEnrichEnabled()) {
          sendError(res, 403, "LLM_DISABLED", "LLM enrichment is not enabled. Set DEEPSEEK_ENRICH_ENABLED=true.");
          return;
        }
        const id = url.searchParams.get("id") || "";
        if (!id) {
          sendError(res, 400, "MISSING_ID", "Provide ?id= for the event to enrich.");
          return;
        }
        try {
          const item = await store.getItem(id);
          if (!item) {
            sendError(res, 404, "ITEM_NOT_FOUND", "Event not found.");
            return;
          }
          const enriched = await llmClient.enrichEvent(item);
          sendJson(res, 200, { schemaVersion: "weekly_activity_api.llm_enrich.v1", enriched });
        } catch (err) {
          console.error("[llm] enrich failed", err);
          sendError(res, 500, "LLM_ENRICH_FAILED", "LLM enrichment failed.", {
            message: err instanceof Error ? err.message : String(err),
          });
        }
        return;
      }

      if (pathname === "/api/v1/weekly/llm/weekly-summary") {
        if (!isLlmEnrichEnabled()) {
          sendError(res, 403, "LLM_DISABLED", "LLM enrichment is not enabled.");
          return;
        }
        try {
          const current = await store.getCurrent({ limit: 30 });
          const summary = await llmClient.generateWeeklySummary(current.items);
          sendJson(res, 200, { schemaVersion: "weekly_activity_api.llm_summary.v1", summary });
        } catch (err) {
          console.error("[llm] weekly-summary failed", err);
          const fallbackSummary = await store.getLlmSummary();
          if (fallbackSummary?.summary) {
            sendJson(res, 200, {
              schemaVersion: "weekly_activity_api.llm_summary.v1",
              summary: fallbackSummary.summary,
              generatedAt: fallbackSummary.generatedAt || fallbackSummary.generated_at || null,
              provider: fallbackSummary.provider || null,
              model: fallbackSummary.model || null,
              source: "materialized-summary-fallback",
              fallbackUsed: true,
              fallbackReason: err instanceof Error ? err.message : String(err),
            });
            return;
          }
          sendError(res, 500, "LLM_SUMMARY_FAILED", "Weekly summary generation failed.", {
            message: err instanceof Error ? err.message : String(err),
          });
        }
        return;
      }

      if (pathname === "/api/v1/weekly/current") {
        await sendCachedWeeklyJson(
          req,
          res,
          weeklyCacheKey(pathname, url.searchParams, ["cityKey", "date", "limit", "cursor", "lookbackDays"]),
          () => store.getCurrent({
            cityKey: url.searchParams.get("cityKey") || undefined,
            date: url.searchParams.get("date") || undefined,
            limit: url.searchParams.get("limit") || undefined,
            cursor: url.searchParams.get("cursor") || undefined,
            lookbackDays: url.searchParams.get("lookbackDays") || undefined,
          }),
        );
        return;
      }

      if (pathname === "/api/v1/weekly/cities") {
        await sendCachedWeeklyJson(
          req,
          res,
          weeklyCacheKey(pathname, url.searchParams, []),
          () => store.getCities(),
          60_000,
        );
        return;
      }

      if (pathname === "/api/v1/weekly/dates") {
        await sendCachedWeeklyJson(
          req,
          res,
          weeklyCacheKey(pathname, url.searchParams, []),
          () => store.getDates(),
          60_000,
        );
        return;
      }

      const atlasEventMatch = pathname.match(/^\/api\/v1\/weekly\/atlas-events\/([^/]+)$/);
      if (atlasEventMatch) {
        const atlasEvent = await store.getAtlasEvent(decodeURIComponent(atlasEventMatch[1]));
        if (!atlasEvent) {
          sendError(res, 404, "ATLAS_EVENT_NOT_FOUND", "Weekly atlas event snapshot was not found.");
          return;
        }
        sendJson(res, 200, atlasEvent);
        return;
      }

      const posterMatch = pathname.match(/^\/api\/v1\/weekly\/poster\/([^/]+)$/);
      if (posterMatch) {
        const sourceUrl = await store.getPosterSource(decodeURIComponent(posterMatch[1]));
        if (!sourceUrl) {
          sendError(res, 404, "POSTER_NOT_FOUND", "Poster image was not found.");
          return;
        }
        await sendPosterProxy(res, sourceUrl);
        return;
      }

      if (pathname === "/api/v1/weekly/items/batch") {
        const idsParam = url.searchParams.get("ids") || "";
        const ids = idsParam.split(",").map((s) => s.trim()).filter(Boolean);
        if (ids.length === 0 || ids.length > 100) {
          sendError(res, 400, "INVALID_IDS", "Provide 1-100 comma-separated ids.");
          return;
        }
        sendJson(res, 200, { items: await store.getItemsByIds(ids) });
        return;
      }

      const itemMatch = pathname.match(/^\/api\/v1\/weekly\/items\/([^/]+)$/);
      if (itemMatch) {
        const item = await store.getItem(decodeURIComponent(itemMatch[1]));
        if (!item) {
          sendError(res, 404, "ITEM_NOT_FOUND", "Weekly activity item was not found.");
          return;
        }
        sendJson(res, 200, item);
        return;
      }

      const sourceMatch = pathname.match(/^\/api\/v1\/weekly\/source\/([^/]+)$/);
      if (sourceMatch) {
        const source = await store.getSourceAction(decodeURIComponent(sourceMatch[1]));
        if (!source) {
          sendError(res, 404, "SOURCE_NOT_FOUND", "Source article was not found.");
          return;
        }
        sendJson(res, 200, source);
        return;
      }

      if (pathname === "/api/v1/weekly/sounds") {
        if (req.method === "POST") {
          const body = await readJsonBody(req);
          const result = await soundStore.submit(body);
          sendJson(res, 201, result);
          return;
        }
        const list = await soundStore.list({
          limit: url.searchParams.get("limit") || undefined,
        });
        sendJson(res, 200, list);
        return;
      }

      if (pathname === "/api/v1/weekly/sounds/enrich") {
        if (!isLlmEnrichEnabled()) {
          sendError(res, 403, "LLM_DISABLED", "LLM enrichment is not enabled. Set DEEPSEEK_ENRICH_ENABLED=true.");
          return;
        }
        const submissionId = url.searchParams.get("id") || "";
        if (!submissionId) {
          sendError(res, 400, "MISSING_ID", "Provide ?id= for the submission to enrich.");
          return;
        }
        const list = await soundStore.list({ limit: 200 });
        const submission = list.items.find((s) => s.id === submissionId);
        if (!submission) {
          sendError(res, 404, "SUBMISSION_NOT_FOUND", "Sound submission was not found.");
          return;
        }
        try {
          const prompt = [
            "Analyze this club sound system submission for Atlas:",
            `Club: ${submission.clubName}`,
            `Sound equipment photos (cloud file IDs): ${submission.soundFileIds.join(", ")}`,
            `Payment screenshots (cloud file IDs): ${submission.paymentFileIds.join(", ")}`,
            "Identify equipment models, assess completeness, and summarize findings in JSON.",
          ].join("\n");
          const enriched = await llmClient.enrichEvent({ title: submission.clubName, description: prompt });
          sendJson(res, 200, {
            submissionId,
            enriched,
            safety: { graphWriteExecuted: false, productionWriteExecuted: false },
          });
        } catch (err) {
          console.error("[sounds] enrich failed", err);
          sendError(res, 500, "LLM_ENRICH_FAILED", "Sound submission LLM enrichment failed.", {
            message: err instanceof Error ? err.message : String(err),
          });
        }
        return;
      }

      if (pathname === "/api/v1/atlas/dj-interviews/review-queue") {
        const queue = await interviewStore.reviewQueue({
          limit: url.searchParams.get("limit") || undefined,
        });
        sendJson(res, 200, queue);
        return;
      }

      if (pathname === "/api/v1/atlas/dj-interviews") {
        if (req.method === "POST") {
          const body = await readJsonBody(req);
          const result = await interviewStore.submit(body);
          sendJson(res, 201, {
            schemaVersion: "atlas_dj_interview_submission_result.v1",
            ...result,
          });
          return;
        }
        const list = await interviewStore.list({
          limit: url.searchParams.get("limit") || undefined,
        });
        sendJson(res, 200, list);
        return;
      }

      // ── Miniapp Atlas API (in-memory JSON, no native deps) ──
      if (pathname === "/api/v1/weekly/atlas/artist") {
        const artistOptions = {
          eventLimit: url.searchParams.get("eventLimit") || undefined,
          collaboratorLimit: url.searchParams.get("collaboratorLimit") || undefined,
          venueLimit: url.searchParams.get("venueLimit") || undefined,
        };
        const subjectId = url.searchParams.get("subjectId") || "";
        const payload = subjectId
          ? await getArtistById(subjectId, artistOptions)
          : await getArtist({
            name: url.searchParams.get("name") || "",
            ...artistOptions,
          });
        sendJson(res, 200, payload, {}, { req, cacheMaxAge: 300 });
        return;
      }

      if (pathname === "/api/v1/weekly/atlas/venue") {
        sendJson(res, 200, await getVenue({
          name: url.searchParams.get("name") || "",
          eventLimit: url.searchParams.get("eventLimit") || undefined,
        }), {}, { req, cacheMaxAge: 300 });
        return;
      }

      if (pathname === "/api/v1/weekly/atlas/search") {
        sendJson(res, 200, await getSearch({
          q: url.searchParams.get("q") || "",
          type: url.searchParams.get("type") || "",
          limit: url.searchParams.get("limit") || undefined,
        }), {}, { req, cacheMaxAge: 120 });
        return;
      }

      if (pathname === "/api/v1/weekly/atlas/neighborhood") {
        sendJson(res, 200, await getNeighborhood({
          subjectId: url.searchParams.get("subjectId") || "",
          q: url.searchParams.get("q") || "",
          depth: url.searchParams.get("depth") || undefined,
          limit: url.searchParams.get("limit") || undefined,
        }), {}, { req, cacheMaxAge: 300 });
        return;
      }

      if (pathname === "/api/v1/weekly/atlas/path") {
        sendJson(res, 200, await getPath({
          from: url.searchParams.get("from") || "",
          to: url.searchParams.get("to") || "",
          fromName: url.searchParams.get("fromName") || "",
          toName: url.searchParams.get("toName") || "",
          maxDepth: url.searchParams.get("maxDepth") || undefined,
        }), {}, { req, cacheMaxAge: 300 });
        return;
      }

      const atlasEntityMatch = pathname.match(/^\/api\/v1\/weekly\/atlas\/entity\/([^/]+)$/);
      if (atlasEntityMatch) {
        sendJson(res, 200, await getEntity(decodeURIComponent(atlasEntityMatch[1])));
        return;
      }

      if (pathname === "/api/v1/weekly/atlas/starmap/lens") {
        sendJson(res, 200, await getStarmapLens({
          name: url.searchParams.get("name") || "future",
          subjectId: url.searchParams.get("subjectId") || "",
        }), {}, { req, cacheMaxAge: 300 });
        return;
      }

      if (pathname === "/api/v1/weekly/atlas/radio-external-links") {
        sendJson(res, 200, await getRadioExternalLinks({
          stationKey: url.searchParams.get("stationKey") || "",
        }), {}, { req, cacheMaxAge: 300 });
        return;
      }

      if (pathname === "/api/v1/weekly/atlas/radio-programs") {
        sendJson(res, 200, await getRadioPrograms({
          stationKey: url.searchParams.get("stationKey") || "",
          djId: url.searchParams.get("djId") || "",
          limit: url.searchParams.get("limit") || undefined,
          includeReviewOnly: url.searchParams.get("includeReviewOnly") || "",
        }), {}, { req, cacheMaxAge: 300 });
        return;
      }

      // ── Cross-DB Entity Resolution (DB2 eid → DB3 entity) ──
      if (pathname === "/api/v1/weekly/atlas/cross-db/resolve") {
        const eid = url.searchParams.get("eid") || "";
        if (!eid) {
          sendError(res, 400, "MISSING_PARAM", "Query parameter 'eid' is required.");
          return;
        }
        sendJson(res, 200, await resolveCrossDbEntity(eid));
        return;
      }

      if (pathname === "/api/v1/weekly/atlas/cross-db/stats") {
        sendJson(res, 200, await getMergeMapStats());
        return;
      }
      // ── DJ Profile by ID (direct subject ID lookup, not name search) ──
      const djIdProfileMatch = pathname.match(/^\/api\/v1\/weekly\/atlas\/dj\/([^/]+)\/profile$/);
      if (djIdProfileMatch) {
        const rawId = decodeURIComponent(djIdProfileMatch[1]);
        let artistResult = await getArtistById(rawId, { eventLimit: 50, collaboratorLimit: 20, venueLimit: 15 });
        let mergeResult = null;

        // Resolve cross-DB mapping (DB2 eid → DB3 entity)
        mergeResult = await resolveCrossDbEntity(rawId).catch(() => null);

        // If artist not found by direct ID but merge resolves, try the canonical ID
        if (!artistResult.found && mergeResult?.resolved && mergeResult.canonicalId) {
          artistResult = await getArtistById(mergeResult.canonicalId, { eventLimit: 50, collaboratorLimit: 20, venueLimit: 15 });
        }

        // Get yuanbao enrichment from current_release items
        let enrichment = { items: [], bios: [], profiles: [] };
        if (artistResult.found) {
          const profile = artistResult.profile || {};
          const aliases = Array.isArray(profile.aliases) ? profile.aliases : [];
          try {
            enrichment = await store.getDjEnrichmentFromCurrent({
              djName: profile.displayName || rawId,
              djAliases: aliases,
              limit: 30,
            });
          } catch {
            // enrichment is optional; continue with empty
          }
        }

        sendJson(res, 200, {
          schemaVersion: "atlas_miniapp.dj_id_profile_response.v1",
          query: rawId,
          found: artistResult.found,
          profile: artistResult.found ? artistResult.profile : null,
          events: artistResult.found ? artistResult.events : [],
          collaborators: artistResult.found ? artistResult.collaborators : [],
          venues: artistResult.found ? artistResult.venues : [],
          alternatives: artistResult.found ? artistResult.alternatives : [],
          crossDb: mergeResult?.resolved ? {
            resolved: true,
            eid: mergeResult.eid,
            db3Id: mergeResult.db3Id,
            canonicalId: mergeResult.canonicalId,
            entity: mergeResult.entity,
          } : null,
          yuanbaoEnrichment: {
            itemCount: enrichment.items.length,
            bios: enrichment.bios || [],
            profiles: enrichment.profiles || [],
          },
          relatedEvents: enrichment.items || [],
        }, {}, { req, cacheMaxAge: 300 });
        return;
      }


      // ── DJ Profile endpoint: DB3 atlas + yuanbao enrichment + cross-DB merge ──
      const djProfileMatch = pathname.match(/^\/api\/v1\/weekly\/atlas\/dj-profile\/([^/]+)$/);
      if (djProfileMatch) {
        const rawId = decodeURIComponent(djProfileMatch[1]);
        let artistResult;
        let mergeResult = null;

        // If it looks like an entity ID (contains colon), resolve first
        if (rawId.includes(":")) {
          const entity = await getEntity(rawId);
          const displayName = entity.found ? entity.entity?.n || entity.entity?.displayName : rawId;
          [artistResult, mergeResult] = await Promise.all([
            displayName !== rawId ? getArtist({ name: displayName, eventLimit: 50, collaboratorLimit: 20, venueLimit: 15 }) : { found: false, query: rawId, reason: "entity_not_found" },
            resolveCrossDbEntity(rawId).catch(() => null),
          ]);
          // If entity found but artist search by name failed, attach entity as profile
          if (!artistResult.found && entity.found) {
            artistResult = {
              schemaVersion: "atlas_miniapp.artist_response.v1",
              query: rawId,
              found: true,
              profile: {
                djId: entity.entity?.i || rawId,
                displayName: entity.entity?.n || displayName,
                aliases: entity.entity?.a || [],
                city: entity.entity?.c || null,
                subjectType: entity.entity?.t || "dj",
              },
              events: [],
              collaborators: [],
              venues: [],
              alternatives: [],
            };
          }
        } else {
          [artistResult, mergeResult] = await Promise.all([
            getArtist({ name: rawId, eventLimit: 50, collaboratorLimit: 20, venueLimit: 15 }),
            resolveCrossDbEntity(rawId).catch(() => null),
          ]);
        }

        // Search for yuanbao enrichment in current_release items
        let enrichment = { items: [], bios: [], profiles: [] };
        if (artistResult.found) {
          const profile = artistResult.profile || {};
          const aliases = Array.isArray(profile.aliases) ? profile.aliases : [];
          try {
            enrichment = await store.getDjEnrichmentFromCurrent({
              djName: profile.displayName || rawId,
              djAliases: aliases,
              limit: 30,
            });
          } catch {
            // enrichment is optional; continue with empty
          }
        }

        sendJson(res, 200, {
          schemaVersion: "atlas_miniapp.dj_profile_response.v1",
          query: rawId,
          found: artistResult.found,
          profile: artistResult.found ? artistResult.profile : null,
          events: artistResult.found ? artistResult.events : [],
          collaborators: artistResult.found ? artistResult.collaborators : [],
          venues: artistResult.found ? artistResult.venues : [],
          alternatives: artistResult.found ? artistResult.alternatives : [],
          crossDb: mergeResult?.resolved ? {
            resolved: true,
            eid: mergeResult.eid,
            db3Id: mergeResult.db3Id,
            canonicalId: mergeResult.canonicalId,
            entity: mergeResult.entity,
          } : null,
          yuanbaoEnrichment: {
            itemCount: enrichment.items.length,
            bios: enrichment.bios || [],
            profiles: enrichment.profiles || [],
          },
          relatedEvents: enrichment.items || [],
        }, {}, { req, cacheMaxAge: 300 });
        return;
      }

      sendError(res, 404, "ROUTE_NOT_FOUND", "Route was not found.");
    } catch (error) {
      const statusCode = Number.isInteger(error?.statusCode) ? error.statusCode : 500;
      sendError(res, statusCode, statusCode === 500 ? "INTERNAL_ERROR" : "REQUEST_FAILED", "Weekly API failed to handle the request.", {
        message: error instanceof Error ? error.message : String(error),
      });
    }
  });
}

if (process.argv[1] && modulePath === process.argv[1]) {
  const port = Number.parseInt(process.env.PORT || "8787", 10);
  const host = String(process.env.HOST || "0.0.0.0").trim() || "0.0.0.0";

  // Prevent unhandled rejections from crashing the process silently
  process.on("unhandledRejection", (reason) => {
    console.error("[fatal] unhandledRejection:", reason instanceof Error ? reason.message : String(reason));
  });
  process.on("uncaughtException", (err) => {
    console.error("[fatal] uncaughtException:", err.message);
    // Exit after logging — uncaught exceptions leave the process in an unknown state
    process.exitCode = 1;
    setTimeout(() => process.exit(1), 1000).unref();
  });

  const server = createServer();
  server.on("error", (err) => {
    if (err.code === "EADDRINUSE") {
      console.error(`[startup] Port ${port} is already in use. Kill the existing process first:`);
      console.error(`  Windows: netstat -ano | findstr :${port}  then  taskkill /PID <pid> /F`);
      console.error(`  Linux:   fuser -k ${port}/tcp`);
      process.exit(1);
    } else {
      throw err;
    }
  });
  server.listen(port, host, () => {
    console.log(`weekly-api listening on ${host}:${port}`);
  });

  // Warm up in-memory cache: self-request to populate weeklyJsonCache
  setImmediate(async () => {
    const base = `http://${host === "0.0.0.0" ? "127.0.0.1" : host}:${port}`;
    const endpoints = ["/api/v1/weekly/manifest", "/api/v1/weekly/cities", "/api/v1/weekly/dates"];
    for (const path of endpoints) {
      try {
        await new Promise((resolve, reject) => {
          const req = http.get(`${base}${path}`, (res) => {
            res.resume();
            res.on("end", resolve);
          });
          req.on("error", reject);
          req.setTimeout(5000, () => { req.destroy(); resolve(); });
        });
        console.log(`[warmup] ${path} OK`);
      } catch (err) {
        console.warn(`[warmup] ${path} FAILED (non-fatal):`, err.message);
      }
    }
  });
}
