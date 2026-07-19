const crypto = require("node:crypto");

const DEFAULT_ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e";
const COLLECTION_NAME = "atlas_player_state";
const SCHEMA_VERSION = "atlas_universe_game_state.v1";
const MAX_STATE_JSON_BYTES = 32 * 1024;

let cloudbaseApp = null;

function nowIso() {
  return new Date().toISOString();
}

function cloneJson(value) {
  if (!value || typeof value !== "object") return {};
  return JSON.parse(JSON.stringify(value));
}

function getCloudBaseApp() {
  if (!cloudbaseApp) {
    const tcb = require("@cloudbase/node-sdk");
    cloudbaseApp = tcb.init({
      env: process.env.TCB_ENV || process.env.ENV_ID || process.env.SCF_NAMESPACE || DEFAULT_ENV_ID,
    });
  }
  return cloudbaseApp;
}

function extractOpenId(event = {}, context = {}) {
  const candidates = [
    event.openid,
    event.openId,
    event.OPENID,
    event.userInfo && event.userInfo.openId,
    event.userInfo && event.userInfo.openid,
    context.OPENID,
    context.openid,
    context.WX_OPENID,
    context.TCB_UUID,
  ];
  return String(candidates.find((item) => item) || "").trim();
}

function normalizePlayerKey(value) {
  const key = String(value || "").trim();
  return key.replace(/[^a-zA-Z0-9:_-]/g, "_").slice(0, 96);
}

function hashOwner(value) {
  return crypto.createHash("sha256").update(String(value || "")).digest("hex").slice(0, 32);
}

function ownerKeyFor(event = {}, context = {}) {
  const openId = extractOpenId(event, context);
  if (openId) return `wx_${hashOwner(openId)}`;
  const playerKey = normalizePlayerKey(event.playerKey);
  if (playerKey) return `local_${hashOwner(playerKey)}`;
  return "";
}

function normalizeState(state = {}) {
  const copy = cloneJson(state);
  const json = JSON.stringify(copy);
  if (Buffer.byteLength(json, "utf8") > MAX_STATE_JSON_BYTES) {
    const error = new Error("state payload too large");
    error.code = "STATE_TOO_LARGE";
    throw error;
  }
  return {
    ...copy,
    schemaVersion: SCHEMA_VERSION,
    updatedAt: copy.updatedAt || nowIso(),
  };
}

function normalizeAction(value) {
  const action = String(value || "").trim().toLowerCase();
  return action === "save" || action === "load" || action === "probe" ? action : "load";
}

async function findStateDoc(collection, ownerKey) {
  const result = await collection
    .where({ schemaVersion: SCHEMA_VERSION, ownerKey })
    .limit(1)
    .get();
  const rows = result && Array.isArray(result.data) ? result.data : [];
  return rows[0] || null;
}

function errorResponse(error) {
  return {
    ok: false,
    error: error && (error.code || error.message) || "ATLAS_PLAYER_STATE_FAILED",
    message: error && error.message || String(error || "unknown error"),
    schemaVersion: SCHEMA_VERSION,
  };
}

async function handle(event = {}, context = {}, deps = {}) {
  const action = normalizeAction(event.action);
  const ownerKey = ownerKeyFor(event, context);
  if (!ownerKey) {
    return {
      ok: false,
      error: "OWNER_MISSING",
      message: "Missing WeChat openid or local player key",
      schemaVersion: SCHEMA_VERSION,
    };
  }

  const db = deps.db || getCloudBaseApp().database();
  const collectionName = event.collectionName === COLLECTION_NAME ? event.collectionName : COLLECTION_NAME;
  const collection = db.collection(collectionName);

  if (action === "probe") {
    return {
      ok: true,
      action,
      collectionName,
      schemaVersion: SCHEMA_VERSION,
      ownerKey,
      openidBound: Boolean(extractOpenId(event, context)),
    };
  }

  const existing = await findStateDoc(collection, ownerKey);
  if (action === "load") {
    return {
      ok: true,
      action,
      collectionName,
      schemaVersion: SCHEMA_VERSION,
      source: existing && existing.state ? "cloud-function" : "cloud-function-empty",
      docId: existing && existing._id || "",
      state: existing && existing.state ? normalizeState(existing.state) : null,
      updatedAt: existing && (existing.updatedAt || existing.state && existing.state.updatedAt) || "",
    };
  }

  const updatedAt = event.meta && event.meta.updatedAt || nowIso();
  const payload = {
    schemaVersion: SCHEMA_VERSION,
    ownerKey,
    playerKey: normalizePlayerKey(event.playerKey),
    lastAction: event.meta && event.meta.action || "",
    updatedAt,
    state: normalizeState(event.state || {}),
  };

  if (existing && existing._id && typeof collection.doc === "function") {
    await collection.doc(existing._id).update({ data: payload });
    return {
      ok: true,
      action,
      collectionName,
      schemaVersion: SCHEMA_VERSION,
      source: "cloud-function",
      docId: existing._id,
      updatedAt,
    };
  }

  const result = await collection.add({ data: payload });
  return {
    ok: true,
    action,
    collectionName,
    schemaVersion: SCHEMA_VERSION,
    source: "cloud-function",
    docId: result && (result._id || result.id) || "",
    updatedAt,
  };
}

exports.main = async (event = {}, context = {}) => {
  try {
    return await handle(event, context);
  } catch (error) {
    return errorResponse(error);
  }
};

exports.__test = {
  COLLECTION_NAME,
  SCHEMA_VERSION,
  extractOpenId,
  handle,
  normalizeState,
  ownerKeyFor,
};
