const crypto = require("node:crypto");

const SUBMIT_PATH = "/api/v1/weekly/sounds";
const PROBE_PATH = "/api/v1/weekly/sounds/ingress-probe";
const MAX_BODY_BYTES = 64 * 1024;

function errorResult(code, message) {
  return { ok: false, error: { code, message } };
}

function canonicalBody(body = {}) {
  return JSON.stringify({
    submissionKey: String(body && body.submissionKey || ""),
    clubName: String(body && body.clubName || ""),
    soundFileIds: Array.isArray(body && body.soundFileIds) ? body.soundFileIds.map(String) : [],
    paymentFileIds: Array.isArray(body && body.paymentFileIds) ? body.paymentFileIds.map(String) : [],
    version: Number(body && body.version || 0),
  });
}

function signature(secret, { timestamp, nonce, appId, openId, envId, path, body }) {
  const canonical = [
    "HUAIDJ_SOUND_INGRESS_V1",
    "POST",
    path,
    String(timestamp),
    nonce,
    appId,
    openId,
    envId,
    crypto.createHash("sha256").update(canonicalBody(body)).digest("hex"),
  ].join("\n");
  return crypto.createHmac("sha256", secret).update(canonical).digest("hex");
}

function fixedRecord(value = {}) {
  return {
    submissionKey: String(value && value.submissionKey || ""),
    clubName: String(value && value.clubName || ""),
    soundFileIds: Array.isArray(value && value.soundFileIds) ? value.soundFileIds.map(String) : [],
    soundImageCount: Number(value && value.soundImageCount || 0),
    paymentFileIds: Array.isArray(value && value.paymentFileIds) ? value.paymentFileIds.map(String) : [],
    paymentImageCount: Number(value && value.paymentImageCount || 0),
    submittedAt: String(value && value.submittedAt || ""),
    version: Number(value && value.version || 0),
  };
}

function configuration(env) {
  return {
    envId: String(env.TCB_ENV || env.ENV_ID || env.SCF_NAMESPACE || "").trim(),
    expectedAppId: String(env.SOUND_GATEWAY_WECHAT_APP_ID || env.WECHAT_APP_ID || "").trim(),
    service: String(env.SOUND_GATEWAY_CLOUDRUN_SERVICE || "").trim(),
    secret: String(env.SOUND_SUBMISSIONS_INGRESS_HMAC_SECRET || ""),
  };
}

async function trustedIdentity(app) {
  const auth = app && typeof app.auth === "function" ? app.auth() : null;
  const userInfo = auth && typeof auth.getUserInfo === "function" ? await auth.getUserInfo() : null;
  return {
    openId: String(userInfo && (userInfo.openId || userInfo.OPENID) || "").trim(),
    appId: String(userInfo && (userInfo.appId || userInfo.APPID) || "").trim(),
  };
}

function validIdentity(identity) {
  return /^[A-Za-z0-9_-]{3,128}$/.test(identity.openId)
    && /^[A-Za-z0-9_-]{3,128}$/.test(identity.appId);
}

function normalizeContainerData(result) {
  const data = result && (result.data !== undefined ? result.data : result.result);
  if (Buffer.isBuffer(data)) {
    try { return JSON.parse(data.toString("utf8")); } catch (_) { return null; }
  }
  if (typeof data === "string") {
    try { return JSON.parse(data); } catch (_) { return null; }
  }
  return data && typeof data === "object" ? data : null;
}

async function defaultApp(context) {
  const cloudbase = require("@cloudbase/js-sdk");
  return cloudbase.init({ context });
}

async function handle(event = {}, context = {}, deps = {}) {
  const env = deps.env || process.env;
  const config = configuration(env);
  if (
    !config.envId
    || !config.expectedAppId
    || !config.service
    || Buffer.byteLength(config.secret, "utf8") < 32
  ) {
    return errorResult("SOUND_GATEWAY_NOT_CONFIGURED", "Sound submission gateway configuration is incomplete.");
  }

  const app = deps.app || await defaultApp(context);
  const identity = await trustedIdentity(app);
  if (!validIdentity(identity)) {
    return errorResult("SOUND_GATEWAY_IDENTITY_REQUIRED", "A trusted mini-program identity is required.");
  }
  if (identity.appId !== config.expectedAppId) {
    return errorResult("SOUND_GATEWAY_APP_MISMATCH", "The caller mini-program is not allowed.");
  }

  const action = String(event && event.action || "").trim().toLowerCase();
  if (action !== "submit" && action !== "probe") {
    return errorResult("SOUND_GATEWAY_ACTION_NOT_ALLOWED", "Only submit and probe actions are allowed.");
  }
  const path = action === "probe" ? PROBE_PATH : SUBMIT_PATH;
  const body = action === "probe" ? { action: "probe", version: 1 } : fixedRecord(event && event.body);
  if (Buffer.byteLength(JSON.stringify(body), "utf8") > MAX_BODY_BYTES) {
    return errorResult("SOUND_GATEWAY_BODY_TOO_LARGE", "Sound submission exceeds the gateway limit.");
  }
  const timestamp = String((deps.now || Date.now)());
  const nonce = String((deps.nonce || (() => crypto.randomBytes(16).toString("hex")))());
  const header = {
    "content-type": "application/json",
    "x-huaidj-sound-timestamp": timestamp,
    "x-huaidj-sound-nonce": nonce,
    "x-huaidj-sound-appid": identity.appId,
    "x-huaidj-sound-openid": identity.openId,
    "x-huaidj-sound-env": config.envId,
  };
  header["x-huaidj-sound-signature"] = signature(config.secret, {
    timestamp,
    nonce,
    appId: identity.appId,
    openId: identity.openId,
    envId: config.envId,
    path,
    body,
  });

  let upstream;
  try {
    upstream = await app.callContainer({
      name: config.service,
      method: "POST",
      path,
      header,
      data: body,
    }, { timeout: 10_000 });
  } catch (error) {
    return errorResult("SOUND_GATEWAY_UPSTREAM_FAILED", "The sound submission service could not be reached.");
  }
  const statusCode = Number(upstream && upstream.statusCode || 200);
  const data = normalizeContainerData(upstream);
  if (statusCode < 200 || statusCode >= 300 || !data || data.error) {
    return errorResult(
      data && data.error && data.error.code || "SOUND_GATEWAY_UPSTREAM_REJECTED",
      data && data.error && data.error.message || "The sound submission service rejected the request.",
    );
  }
  return data;
}

exports.main = async (event = {}, context = {}) => {
  try {
    return await handle(event, context);
  } catch (_) {
    return errorResult("SOUND_GATEWAY_FAILED", "Sound submission gateway failed closed.");
  }
};

exports.__test = { canonicalBody, fixedRecord, handle, signature, trustedIdentity };
