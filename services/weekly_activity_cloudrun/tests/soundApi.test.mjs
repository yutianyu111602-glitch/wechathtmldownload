import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createSoundIngressHeaders } from "../src/soundIngress.mjs";
import { createSoundStore } from "../src/soundStore.mjs";
import { createServer } from "../src/server.mjs";

const ENV_ID = "test-env";
const APP_ID = "wx-test-app";
const SECRET = "unit-test-sound-ingress-secret-32-bytes-minimum";
const KEY = "stable_submission_key_api_001";

function fileId(kind, name) {
  return `cloud://${ENV_ID}.bucket/atlas/sound-submissions/${KEY}/${kind}/${name}`;
}

function submission(overrides = {}) {
  return {
    submissionKey: KEY,
    clubName: "DADA Test",
    soundFileIds: [fileId("sound", "equipment-1.jpg")],
    paymentFileIds: [fileId("payment", "private-proof-1.jpg")],
    version: 4,
    ...overrides,
  };
}

function productionEnv(overrides = {}) {
  return {
    NODE_ENV: "production",
    SOUND_SUBMISSIONS_BACKEND: "cloudbase",
    SOUND_SUBMISSIONS_COLLECTION: "weekly_sound_submissions",
    SOUND_SUBMISSIONS_MAX_PER_DAY: "5",
    SOUND_SUBMISSIONS_INGRESS_MODE: "hmac_gateway",
    SOUND_SUBMISSIONS_INGRESS_HMAC_SECRET: SECRET,
    CLOUDBASE_ENV_ID: ENV_ID,
    WECHAT_APP_ID: APP_ID,
    ATLAS_MINIAPP_PRELOAD: "0",
    ...overrides,
  };
}

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  return `http://127.0.0.1:${address.port}`;
}

test("sound review queue stays admin-only and enrichment sends actual sound images through QwenVL before DeepSeek", async () => {
  const soundDir = await mkdtemp(path.join(os.tmpdir(), "sound-api-review-"));
  const soundStore = createSoundStore({
    soundDir,
    env: { CLOUDBASE_ENV_ID: ENV_ID },
    soundEvidenceVerifier: { async verifySubmissionFiles() {} },
  });
  const submitted = await soundStore.submit(submission());
  const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xd9]);
  let visionInput = null;
  let deepSeekInput = null;
  const server = createServer({
    env: {
      ATLAS_MINIAPP_PRELOAD: "0",
      SOUND_REVIEW_ENRICH_ENABLED: "true",
      WEEKLY_REVIEW_ADMIN_TOKEN: "test-review-token",
      CLOUDBASE_ENV_ID: ENV_ID,
    },
    soundStore,
    soundEvidence: {
      async loadSoundImages(fileIds) {
        assert.deepEqual(fileIds, [fileId("sound", "equipment-1.jpg")]);
        return [{ mimeType: "image/jpeg", data: jpeg }];
      },
    },
    soundVisionClient: {
      publicStatus: () => ({ provider: "qwen-vl", configured: true }),
      async analyzeSoundEvidence(value) {
        visionInput = value;
        return { provider: "qwen-vl", vision: { equipment: [{ label: "speaker", confidence: 0.8 }] } };
      },
    },
    llmClient: {
      publicStatus: () => ({ provider: "deepseek", configured: true }),
      async enrichSoundReview(value) {
        deepSeekInput = value;
        return { provider: "deepseek", enrichment: { summary_zh: "ok" } };
      },
    },
  });
  const baseUrl = await listen(server);

  try {
    const statusResponse = await fetch(`${baseUrl}/api/v1/weekly/sounds`);
    assert.equal(statusResponse.status, 200);
    const status = await statusResponse.json();
    assert.equal(status.items, undefined);
    assert.equal(status.safety.paymentFileIdsExposed, false);

    const rejectedQueue = await fetch(`${baseUrl}/api/v1/weekly/sounds/review-queue`);
    assert.equal(rejectedQueue.status, 403);
    assert.equal((await rejectedQueue.json()).error.code, "ADMIN_AUTH_REQUIRED");
    const queueResponse = await fetch(`${baseUrl}/api/v1/weekly/sounds/review-queue?status=new`, {
      headers: { "x-weekly-review-token": "test-review-token" },
    });
    assert.equal(queueResponse.status, 200);
    const queue = await queueResponse.json();
    assert.equal(queue.total, 1);
    assert.deepEqual(queue.items[0].paymentFileIds, [fileId("payment", "private-proof-1.jpg")]);

    const rejectedEnrich = await fetch(`${baseUrl}/api/v1/weekly/sounds/enrich?id=${submitted.id}`, { method: "POST" });
    assert.equal(rejectedEnrich.status, 403);
    const enrichResponse = await fetch(`${baseUrl}/api/v1/weekly/sounds/enrich?id=${submitted.id}`, {
      method: "POST",
      headers: { "x-weekly-review-token": "test-review-token" },
    });
    assert.equal(enrichResponse.status, 200);
    assert.equal(visionInput.clubName, "DADA Test");
    assert.deepEqual(visionInput.images[0].data, jpeg);
    assert.deepEqual(deepSeekInput, {
      clubName: "DADA Test",
      visionEvidence: { equipment: [{ label: "speaker", confidence: 0.8 }] },
    });
    const llmInput = JSON.stringify(deepSeekInput);
    assert.doesNotMatch(llmInput, /cloud:\/\//);
    assert.doesNotMatch(llmInput, /private-proof|payment/i);
    const enriched = await enrichResponse.json();
    assert.equal(enriched.safety.paymentEvidenceSentToModels, false);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("sound enrichment logs only safe vendor metadata and never provider response text", async () => {
  const secretMarker = "customer-secret-provider-response-body";
  const upstreamError = Object.assign(new Error(`Qwen failed: ${secretMarker}`), {
    code: "QWEN_VL_UPSTREAM_ERROR",
    providerStatus: 429,
    requestId: "req-safe-log-789",
  });
  const captured = [];
  const originalConsoleError = console.error;
  console.error = (...args) => captured.push(args);
  const server = createServer({
    env: {
      ATLAS_MINIAPP_PRELOAD: "0",
      SOUND_REVIEW_ENRICH_ENABLED: "true",
      WEEKLY_REVIEW_ADMIN_TOKEN: "test-review-token",
    },
    soundStore: {
      async publicStatus() { return { acceptingSubmissions: true }; },
      async getInternalById() {
        return { clubName: "DADA", soundFileIds: ["private-cloud-file-id"] };
      },
    },
    soundEvidence: {
      async loadSoundImages() {
        return [{ mimeType: "image/jpeg", data: Buffer.from([1]) }];
      },
    },
    soundVisionClient: {
      publicStatus: () => ({ provider: "qwen-vl", configured: true }),
      async analyzeSoundEvidence() { throw upstreamError; },
    },
    llmClient: {
      publicStatus: () => ({ provider: "deepseek", configured: true }),
      async enrichSoundReview() { throw new Error("must not run"); },
    },
  });
  const baseUrl = await listen(server);

  try {
    const response = await fetch(`${baseUrl}/api/v1/weekly/sounds/enrich?id=sound_test`, {
      method: "POST",
      headers: { "x-weekly-review-token": "test-review-token" },
    });
    const payload = await response.json();
    assert.equal(response.status, 502);
    assert.equal(payload.error.code, "SOUND_REVIEW_ENRICH_FAILED");
    const serializedLogs = JSON.stringify(captured.map((args) => args.map((value) => (
      value instanceof Error ? { message: value.message, ...value } : value
    ))));
    assert.doesNotMatch(serializedLogs, new RegExp(secretMarker));
    assert.match(serializedLogs, /QWEN_VL_UPSTREAM_ERROR/);
    assert.match(serializedLogs, /req-safe-log-789/);
  } finally {
    console.error = originalConsoleError;
    await new Promise((resolve) => server.close(resolve));
  }
});

test("event enrichment response and logs discard DeepSeek provider response text", async () => {
  const secretMarker = "deepseek-private-provider-response-body";
  const upstreamError = Object.assign(new Error(`DeepSeek failed: ${secretMarker}`), {
    code: "DEEPSEEK_UPSTREAM_ERROR",
    providerStatus: 503,
    requestId: "req-safe-deepseek-log-321",
  });
  const captured = [];
  const originalConsoleError = console.error;
  console.error = (...args) => captured.push(args);
  const server = createServer({
    env: {
      ATLAS_MINIAPP_PRELOAD: "0",
      DEEPSEEK_ENRICH_ENABLED: "true",
      WEEKLY_REVIEW_ADMIN_TOKEN: "test-review-token",
    },
    store: {
      async getItem(id) { return id === "event-test" ? { id, title: "Test" } : null; },
    },
    soundStore: { async publicStatus() { return { acceptingSubmissions: false }; } },
    soundEvidence: {},
    soundVisionClient: { publicStatus: () => ({ configured: false }) },
    llmClient: {
      publicStatus: () => ({ provider: "deepseek", configured: true }),
      async enrichEvent() { throw upstreamError; },
    },
  });
  const baseUrl = await listen(server);

  try {
    const response = await fetch(`${baseUrl}/api/v1/weekly/llm/enrich?id=event-test`, {
      method: "POST",
      headers: { "x-weekly-review-token": "test-review-token" },
    });
    const payload = await response.json();
    assert.equal(response.status, 500);
    assert.equal(payload.error.code, "LLM_ENRICH_FAILED");
    assert.deepEqual(payload.error.details, {
      code: "DEEPSEEK_UPSTREAM_ERROR",
      status: 503,
      requestId: "req-safe-deepseek-log-321",
    });
    const serialized = JSON.stringify({ payload, captured: captured.map((args) => args.map((value) => (
      value instanceof Error ? { message: value.message, ...value } : value
    ))) });
    assert.doesNotMatch(serialized, new RegExp(secretMarker));
  } finally {
    console.error = originalConsoleError;
    await new Promise((resolve) => server.close(resolve));
  }
});

test("production sound POST rejects forged WeChat headers and accepts only a fresh signed gateway request", async () => {
  const submitted = [];
  const soundStore = {
    async publicStatus() { return { acceptingSubmissions: true }; },
    async submit(record, context) {
      submitted.push({ record, context });
      return { id: "sound_signed_test", duplicate: false };
    },
  };
  const env = productionEnv();
  const server = createServer({
    env,
    soundStore,
    soundEvidence: {},
    soundVisionClient: { publicStatus: () => ({ provider: "qwen-vl", configured: false }) },
    llmClient: { publicStatus: () => ({ provider: "deepseek", configured: false }) },
  });
  const baseUrl = await listen(server);
  const body = submission();

  try {
    const forged = await fetch(`${baseUrl}/api/v1/weekly/sounds`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-wx-openid": "forged-openid-user",
        "x-wx-appid": APP_ID,
      },
      body: JSON.stringify(body),
    });
    assert.equal(forged.status, 401);
    assert.equal((await forged.json()).error.code, "SOUND_SUBMISSION_SIGNATURE_REQUIRED");

    const headers = createSoundIngressHeaders({
      secret: SECRET,
      timestamp: Date.now(),
      nonce: "nonce_1234567890abcdef",
      appId: APP_ID,
      openId: "openid-platform-user-1",
      envId: ENV_ID,
      path: "/api/v1/weekly/sounds",
      body,
    });
    const accepted = await fetch(`${baseUrl}/api/v1/weekly/sounds`, {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(body),
    });
    assert.equal(accepted.status, 201);
    assert.equal(submitted.length, 1);
    assert.match(submitted[0].context.ownerKey, /^[a-f0-9]{64}$/);

    const tampered = await fetch(`${baseUrl}/api/v1/weekly/sounds`, {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify({ ...body, clubName: "Tampered" }),
    });
    assert.equal(tampered.status, 403);
    assert.equal((await tampered.json()).error.code, "SOUND_SUBMISSION_INVALID_SIGNATURE");
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("signed ingress probe verifies the gateway without creating a submission", async () => {
  let writes = 0;
  const env = productionEnv();
  const server = createServer({
    env,
    soundStore: {
      async publicStatus() { return { acceptingSubmissions: true }; },
      async submit() { writes += 1; throw new Error("must not write"); },
    },
    soundEvidence: {},
    soundVisionClient: { publicStatus: () => ({ configured: false }) },
    llmClient: { publicStatus: () => ({ configured: false }) },
  });
  const baseUrl = await listen(server);
  const body = { action: "probe", version: 1 };
  const headers = createSoundIngressHeaders({
    secret: SECRET,
    timestamp: Date.now(),
    nonce: "probe_1234567890abcdef",
    appId: APP_ID,
    openId: "openid-platform-user-1",
    envId: ENV_ID,
    path: "/api/v1/weekly/sounds/ingress-probe",
    body,
  });

  try {
    const response = await fetch(`${baseUrl}/api/v1/weekly/sounds/ingress-probe`, {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(body),
    });
    assert.equal(response.status, 200);
    assert.equal((await response.json()).ok, true);
    assert.equal(writes, 0);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

test("production sound POST reports persistence configuration before ingress when the store is disabled", async () => {
  const server = createServer({
    env: productionEnv(),
    soundStore: {
      async publicStatus() { return { acceptingSubmissions: false }; },
      async submit() { throw new Error("must not submit"); },
    },
    soundEvidence: {},
    soundVisionClient: { publicStatus: () => ({ configured: false }) },
    llmClient: { publicStatus: () => ({ configured: false }) },
  });
  const baseUrl = await listen(server);
  try {
    const response = await fetch(`${baseUrl}/api/v1/weekly/sounds`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    });
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error.code, "SOUND_SUBMISSIONS_NOT_CONFIGURED");
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
