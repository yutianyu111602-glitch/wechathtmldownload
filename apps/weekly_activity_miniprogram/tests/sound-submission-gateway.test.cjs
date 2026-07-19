const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { pathToFileURL } = require("node:url");

const gateway = require("../cloudfunctions/soundSubmissionGateway/index.js");

const ENV_ID = "test-env";
const APP_ID = "wx-test-app";
const SECRET = "unit-test-sound-ingress-secret-32-bytes-minimum";
const KEY = "stable_submission_key_gateway_1";

function record() {
  return {
    submissionKey: KEY,
    clubName: "DADA Test",
    soundFileIds: [`cloud://${ENV_ID}.bucket/atlas/sound-submissions/${KEY}/sound/a.jpg`],
    paymentFileIds: [`cloud://${ENV_ID}.bucket/atlas/sound-submissions/${KEY}/payment/b.jpg`],
    version: 4,
  };
}

function environment() {
  return {
    TCB_ENV: ENV_ID,
    SOUND_GATEWAY_WECHAT_APP_ID: APP_ID,
    SOUND_GATEWAY_CLOUDRUN_SERVICE: "weekly-api",
    SOUND_SUBMISSIONS_INGRESS_HMAC_SECRET: SECRET,
  };
}

test("sound gateway signs only platform-derived identity and calls the fixed CloudRun route", async () => {
  const calls = [];
  const app = {
    auth() {
      return { getUserInfo: () => ({ openId: "trusted-openid-user-1", appId: APP_ID }) };
    },
    async callContainer(options) {
      calls.push(options);
      return { statusCode: 201, data: { ok: true, id: "sound_gateway_test" } };
    },
  };
  const now = 1_784_448_000_000;
  const result = await gateway.__test.handle(
    { action: "submit", OPENID: "forged-event-openid", body: record() },
    { OPENID: "ignored-context-field" },
    { app, env: environment(), now: () => now, nonce: () => "nonce_1234567890abcdef" },
  );
  assert.equal(result.ok, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].name, "weekly-api");
  assert.equal(calls[0].path, "/api/v1/weekly/sounds");
  assert.equal(calls[0].method, "POST");

  const serverIngress = await import(pathToFileURL(path.resolve(__dirname, "../../../services/weekly_activity_cloudrun/src/soundIngress.mjs")).href);
  const verified = serverIngress.verifySoundIngress({
    headers: calls[0].header,
    body: calls[0].data,
    env: {
      SOUND_SUBMISSIONS_INGRESS_MODE: "hmac_gateway",
      SOUND_SUBMISSIONS_INGRESS_HMAC_SECRET: SECRET,
      CLOUDBASE_ENV_ID: ENV_ID,
      WECHAT_APP_ID: APP_ID,
    },
    now,
  });
  assert.equal(verified.ok, true);
  assert.equal(calls[0].header["x-huaidj-sound-openid"], "trusted-openid-user-1");
  assert.notEqual(calls[0].header["x-huaidj-sound-openid"], "forged-event-openid");
});

test("sound gateway fails closed when trusted identity or secret is absent", async () => {
  let called = false;
  const app = {
    auth() { return { getUserInfo: () => ({ openId: "", appId: "" }) }; },
    async callContainer() { called = true; },
  };
  const result = await gateway.__test.handle(
    { action: "submit", OPENID: "forged", body: record() },
    { OPENID: "also-not-used" },
    { app, env: environment() },
  );
  assert.equal(result.ok, false);
  assert.equal(result.error.code, "SOUND_GATEWAY_IDENTITY_REQUIRED");
  assert.equal(called, false);

  const noSecretEnv = environment();
  delete noSecretEnv.SOUND_SUBMISSIONS_INGRESS_HMAC_SECRET;
  const configuredApp = {
    auth() { return { getUserInfo: () => ({ openId: "trusted-openid-user-1", appId: APP_ID }) }; },
    async callContainer() { called = true; },
  };
  const noSecret = await gateway.__test.handle(
    { action: "submit", body: record() },
    {},
    { app: configuredApp, env: noSecretEnv },
  );
  assert.equal(noSecret.ok, false);
  assert.equal(noSecret.error.code, "SOUND_GATEWAY_NOT_CONFIGURED");
});

test("sound gateway probe uses a distinct signed route and never submits a record", async () => {
  let call = null;
  const app = {
    auth() { return { getUserInfo: () => ({ openId: "trusted-openid-user-1", appId: APP_ID }) }; },
    async callContainer(options) {
      call = options;
      return { statusCode: 200, data: { ok: true, writeExecuted: false } };
    },
  };
  const result = await gateway.__test.handle(
    { action: "probe", body: record() },
    {},
    { app, env: environment(), nonce: () => "probe_1234567890abcdef" },
  );
  assert.equal(result.ok, true);
  assert.equal(call.path, "/api/v1/weekly/sounds/ingress-probe");
  assert.deepEqual(call.data, { action: "probe", version: 1 });
});
