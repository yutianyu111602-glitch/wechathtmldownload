import assert from "node:assert/strict";
import test from "node:test";
import { ReadableStream } from "node:stream/web";
import { QwenVlClient } from "../src/qwenVlClient.mjs";

test("Qwen VL receives actual bounded image data and never cloud file IDs or payment evidence", async () => {
  let requestBody = null;
  const client = new QwenVlClient({
    apiKey: "test-key",
    baseUrl: "https://dashscope.example/compatible-mode/v1",
    model: "qwen3-vl-plus",
    timeoutMs: 5000,
  }, async (_url, request) => {
    requestBody = JSON.parse(request.body);
    return {
      ok: true,
      async text() {
        return JSON.stringify({
          model: "qwen3-vl-plus",
          choices: [{ message: { content: JSON.stringify({
            equipment: [{ label: "speaker", brand: "", model: "", confidence: 0.8, evidence: "visible cabinet" }],
            observations: ["one cabinet is visible"],
            uncertainty: [],
          }) } }],
          usage: { total_tokens: 12 },
        });
      },
    };
  });

  const result = await client.analyzeSoundEvidence({
    clubName: "DADA Test",
    images: [{ mimeType: "image/jpeg", data: Buffer.from([0xff, 0xd8, 0xff, 0xd9]) }],
  });

  const serialized = JSON.stringify(requestBody);
  assert.match(serialized, /data:image\/jpeg;base64/);
  assert.doesNotMatch(serialized, /cloud:\/\//);
  assert.doesNotMatch(serialized, /payment/i);
  assert.equal(requestBody.max_tokens, 1600);
  assert.equal(result.provider, "qwen-vl");
  assert.equal(result.vision.equipment[0].label, "speaker");
});

test("Qwen VL fails closed on missing configuration and oversized or non-image evidence", async () => {
  const unconfigured = new QwenVlClient({ apiKey: "" }, async () => {
    throw new Error("must not fetch");
  });
  await assert.rejects(
    unconfigured.analyzeSoundEvidence({ clubName: "DADA", images: [{ mimeType: "image/jpeg", data: Buffer.from([1]) }] }),
    /QWEN_VL_NOT_CONFIGURED/,
  );

  const configured = new QwenVlClient({ apiKey: "test-key" }, async () => {
    throw new Error("must not fetch");
  });
  await assert.rejects(
    configured.analyzeSoundEvidence({ clubName: "DADA", images: [{ mimeType: "text/plain", data: Buffer.from("x") }] }),
    /SOUND_VISION_INVALID_IMAGE/,
  );
  await assert.rejects(
    configured.analyzeSoundEvidence({
      clubName: "DADA",
      images: [{ mimeType: "image/jpeg", data: Buffer.alloc(1024 * 1024 + 1) }],
    }),
    /SOUND_VISION_IMAGE_TOO_LARGE/,
  );
});

test("Qwen VL never includes an upstream response body in errors and keeps only safe metadata", async () => {
  const secretBody = "provider diagnostic body with customer-secret-marker";
  const client = new QwenVlClient({ apiKey: "test-key" }, async () => ({
    ok: false,
    status: 429,
    headers: { get: (name) => name.toLowerCase() === "x-request-id" ? "req-qwen-123" : null },
    async text() {
      return JSON.stringify({ code: "Throttled", message: secretBody });
    },
  }));

  await assert.rejects(
    client.analyzeSoundEvidence({
      clubName: "DADA",
      images: [{ mimeType: "image/jpeg", data: Buffer.from([1]) }],
    }),
    (error) => {
      assert.equal(error?.code, "QWEN_VL_UPSTREAM_ERROR");
      assert.equal(error?.providerStatus, 429);
      assert.equal(error?.requestId, "req-qwen-123");
      assert.doesNotMatch(String(error?.message), /customer-secret-marker|diagnostic body/);
      assert.doesNotMatch(JSON.stringify(error), /customer-secret-marker|diagnostic body/);
      return true;
    },
  );
});

test("Qwen VL bounds response bodies and rejects schema drift or overlong fields", async () => {
  let streamCancelled = false;
  let emittedChunks = 0;
  const body = new ReadableStream({
    pull(controller) {
      controller.enqueue(new Uint8Array(emittedChunks === 0 ? 700 : 400));
      emittedChunks += 1;
    },
    cancel() {
      streamCancelled = true;
    },
  });
  const oversized = new QwenVlClient({ apiKey: "test-key", responseMaxBytes: 1024 }, async () => ({
    ok: true,
    status: 200,
    headers: { get: () => null },
    body,
    async text() { throw new Error("stream reader should enforce the bound"); },
  }));
  await assert.rejects(
    oversized.analyzeSoundEvidence({
      clubName: "DADA",
      images: [{ mimeType: "image/jpeg", data: Buffer.from([1]) }],
    }),
    (error) => error?.code === "QWEN_VL_RESPONSE_TOO_LARGE",
  );
  assert.equal(streamCancelled, true);

  const invalidSchema = new QwenVlClient({ apiKey: "test-key" }, async () => ({
    ok: true,
    status: 200,
    headers: { get: () => null },
    async text() {
      return JSON.stringify({
        choices: [{ message: { content: JSON.stringify({
          equipment: [{ label: "x".repeat(161), brand: "", model: "", confidence: 0.8, evidence: "visible" }],
          observations: [],
          uncertainty: [],
        }) } }],
      });
    },
  }));
  await assert.rejects(
    invalidSchema.analyzeSoundEvidence({
      clubName: "DADA",
      images: [{ mimeType: "image/jpeg", data: Buffer.from([1]) }],
    }),
    (error) => error?.code === "QWEN_VL_INVALID_SCHEMA",
  );
});
