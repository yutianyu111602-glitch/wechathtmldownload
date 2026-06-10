import assert from "node:assert/strict";
import { test } from "node:test";
import { DeepSeekClient, createDeepSeekClient } from "../src/deepSeekClient.mjs";

function okJsonResponse(payload) {
  return {
    ok: true,
    async text() {
      return JSON.stringify({
        choices: [{ message: { content: JSON.stringify(payload) } }],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      });
    },
  };
}

test("DeepSeek client disables request timeout when timeoutMs is zero", async () => {
  let request;
  const client = new DeepSeekClient(
    { apiKey: "test-key", timeoutMs: 0 },
    async (_url, init) => {
      request = init;
      return okJsonResponse({ ok: true });
    },
  );

  const status = client.publicStatus();
  assert.equal(status.timeoutMs, null);
  assert.equal(status.timeoutDisabled, true);

  const result = await client.createJsonChat({ messages: [{ role: "user", content: "{}" }] });
  assert.deepEqual(result.json, { ok: true });
  assert.equal(Object.hasOwn(request, "signal"), false);
});

test("DeepSeek client keeps explicit positive timeout", async () => {
  let request;
  const client = new DeepSeekClient(
    { apiKey: "test-key", timeoutMs: 120000 },
    async (_url, init) => {
      request = init;
      return okJsonResponse({ ok: true });
    },
  );

  const status = client.publicStatus();
  assert.equal(status.timeoutMs, 120000);
  assert.equal(status.timeoutDisabled, false);

  await client.createJsonChat({ messages: [{ role: "user", content: "{}" }] });
  assert.equal(Boolean(request.signal), true);
});

test("createDeepSeekClient defaults to no request timeout", () => {
  const client = createDeepSeekClient({ DEEPSEEK_API_KEY: "test-key" }, async () => okJsonResponse({ ok: true }));
  const status = client.publicStatus();
  assert.equal(status.timeoutMs, null);
  assert.equal(status.timeoutDisabled, true);
});
