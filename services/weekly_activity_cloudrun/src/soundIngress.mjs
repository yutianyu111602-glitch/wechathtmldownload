import { createHash, createHmac, timingSafeEqual } from "node:crypto";

const DEFAULT_PATH = "/api/v1/weekly/sounds";
const DEFAULT_MAX_SKEW_MS = 300_000;
const SIGNATURE_HEADER = "x-huaidj-sound-signature";
const TIMESTAMP_HEADER = "x-huaidj-sound-timestamp";
const NONCE_HEADER = "x-huaidj-sound-nonce";
const APP_ID_HEADER = "x-huaidj-sound-appid";
const OPEN_ID_HEADER = "x-huaidj-sound-openid";
const ENV_ID_HEADER = "x-huaidj-sound-env";
const HEX_64_RE = /^[a-f0-9]{64}$/;
const ID_RE = /^[A-Za-z0-9_-]{3,128}$/;
const NONCE_RE = /^[A-Za-z0-9_-]{16,128}$/;

function headerValue(headers, name) {
  const direct = headers?.[name] ?? headers?.[name.toLowerCase()];
  if (Array.isArray(direct)) return String(direct[0] || "").trim();
  return String(direct || "").trim();
}

function canonicalBody(body = {}) {
  return JSON.stringify({
    submissionKey: String(body?.submissionKey || ""),
    clubName: String(body?.clubName || ""),
    soundFileIds: Array.isArray(body?.soundFileIds) ? body.soundFileIds.map(String) : [],
    paymentFileIds: Array.isArray(body?.paymentFileIds) ? body.paymentFileIds.map(String) : [],
    version: Number(body?.version || 0),
  });
}

function canonicalRequest({ timestamp, nonce, appId, openId, envId, path = DEFAULT_PATH, body }) {
  return [
    "HUAIDJ_SOUND_INGRESS_V1",
    "POST",
    String(path || DEFAULT_PATH),
    String(timestamp),
    String(nonce),
    String(appId),
    String(openId),
    String(envId),
    createHash("sha256").update(canonicalBody(body)).digest("hex"),
  ].join("\n");
}

function signatureFor(secret, values) {
  return createHmac("sha256", secret).update(canonicalRequest(values)).digest("hex");
}

function safeEqualHex(left, right) {
  if (!HEX_64_RE.test(left) || !HEX_64_RE.test(right)) return false;
  return timingSafeEqual(Buffer.from(left, "hex"), Buffer.from(right, "hex"));
}

export function createSoundIngressHeaders({
  secret,
  timestamp = Date.now(),
  nonce,
  appId,
  openId,
  envId,
  path = DEFAULT_PATH,
  body,
} = {}) {
  const normalizedSecret = String(secret || "");
  if (Buffer.byteLength(normalizedSecret, "utf8") < 32) {
    throw new Error("SOUND_INGRESS_SECRET_TOO_SHORT");
  }
  const values = {
    timestamp: String(timestamp),
    nonce: String(nonce || ""),
    appId: String(appId || ""),
    openId: String(openId || ""),
    envId: String(envId || ""),
    path,
    body,
  };
  return {
    [TIMESTAMP_HEADER]: values.timestamp,
    [NONCE_HEADER]: values.nonce,
    [APP_ID_HEADER]: values.appId,
    [OPEN_ID_HEADER]: values.openId,
    [ENV_ID_HEADER]: values.envId,
    [SIGNATURE_HEADER]: signatureFor(normalizedSecret, values),
  };
}

export function verifySoundIngress({
  headers = {},
  body = {},
  env = process.env,
  now = Date.now(),
  path = DEFAULT_PATH,
  maxSkewMs = DEFAULT_MAX_SKEW_MS,
} = {}) {
  const mode = String(env.SOUND_SUBMISSIONS_INGRESS_MODE || "").trim().toLowerCase();
  const secret = String(env.SOUND_SUBMISSIONS_INGRESS_HMAC_SECRET || "");
  const expectedAppId = String(env.WECHAT_APP_ID || "").trim();
  const expectedEnvId = String(env.CLOUDBASE_ENV_ID || "").trim();
  const configured = mode === "hmac_gateway"
    && Buffer.byteLength(secret, "utf8") >= 32
    && Boolean(expectedAppId)
    && Boolean(expectedEnvId);
  if (!configured) return { ok: false, configured: false, reason: "not_configured", ownerKey: "" };

  const signature = headerValue(headers, SIGNATURE_HEADER).toLowerCase();
  if (!signature) return { ok: false, configured: true, reason: "signature_required", ownerKey: "" };

  const timestamp = headerValue(headers, TIMESTAMP_HEADER);
  const nonce = headerValue(headers, NONCE_HEADER);
  const appId = headerValue(headers, APP_ID_HEADER);
  const openId = headerValue(headers, OPEN_ID_HEADER);
  const envId = headerValue(headers, ENV_ID_HEADER);
  const numericTimestamp = Number(timestamp);
  if (!Number.isSafeInteger(numericTimestamp)) {
    return { ok: false, configured: true, reason: "invalid_timestamp", ownerKey: "" };
  }
  if (Math.abs(Number(now) - numericTimestamp) > maxSkewMs) {
    return { ok: false, configured: true, reason: "expired", ownerKey: "" };
  }
  if (!NONCE_RE.test(nonce) || !ID_RE.test(appId) || !ID_RE.test(openId) || !ID_RE.test(envId)) {
    return { ok: false, configured: true, reason: "invalid_identity", ownerKey: "" };
  }
  if (appId !== expectedAppId) {
    return { ok: false, configured: true, reason: "app_mismatch", ownerKey: "" };
  }
  if (envId !== expectedEnvId) {
    return { ok: false, configured: true, reason: "env_mismatch", ownerKey: "" };
  }

  const expected = signatureFor(secret, {
    timestamp,
    nonce,
    appId,
    openId,
    envId,
    path,
    body,
  });
  if (!safeEqualHex(signature, expected)) {
    return { ok: false, configured: true, reason: "invalid_signature", ownerKey: "" };
  }

  return {
    ok: true,
    configured: true,
    reason: "verified",
    ownerKey: createHmac("sha256", secret).update(`${appId}\0${openId}`).digest("hex"),
    appId,
    envId,
  };
}

export const SOUND_INGRESS_HEADER_NAMES = Object.freeze({
  signature: SIGNATURE_HEADER,
  timestamp: TIMESTAMP_HEADER,
  nonce: NONCE_HEADER,
  appId: APP_ID_HEADER,
  openId: OPEN_ID_HEADER,
  envId: ENV_ID_HEADER,
});
