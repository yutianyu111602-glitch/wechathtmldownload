const assert = require("node:assert/strict");
const test = require("node:test");
const { verifySoundReleaseGate } = require("../scripts/sound_release_gate.cjs");

function jsonResponse(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    async json() { return payload; },
  };
}

test("sound release gate requires both public forged-header rejection and signed mini gateway probe", async () => {
  let forgedRequest = null;
  const result = await verifySoundReleaseGate({
    baseUrl: "https://weekly.example",
    fetchImpl: async (url, request) => {
      forgedRequest = { url, request };
      return jsonResponse(401, { error: { code: "SOUND_SUBMISSION_SIGNATURE_REQUIRED" } });
    },
    callGatewayProbe: async () => ({
      ok: true,
      verifiedIngress: true,
      writeExecuted: false,
    }),
  });
  assert.equal(result.ok, true);
  assert.equal(result.publicForgeryRejected, true);
  assert.equal(result.gatewayProbeVerified, true);
  assert.equal(forgedRequest.request.headers["x-wx-openid"], "forged-release-gate-openid");
});

test("sound release gate fails if public forgery is accepted or gateway probe is not non-writing", async () => {
  await assert.rejects(
    verifySoundReleaseGate({
      baseUrl: "https://weekly.example",
      fetchImpl: async () => jsonResponse(201, { ok: true }),
      callGatewayProbe: async () => ({ ok: true, verifiedIngress: true, writeExecuted: false }),
    }),
    /SOUND_RELEASE_GATE_PUBLIC_FORGERY_ACCEPTED/,
  );
  await assert.rejects(
    verifySoundReleaseGate({
      baseUrl: "https://weekly.example",
      fetchImpl: async () => jsonResponse(401, { error: { code: "SOUND_SUBMISSION_SIGNATURE_REQUIRED" } }),
      callGatewayProbe: async () => ({ ok: true, verifiedIngress: true, writeExecuted: true }),
    }),
    /SOUND_RELEASE_GATE_GATEWAY_PROBE_FAILED/,
  );
});
