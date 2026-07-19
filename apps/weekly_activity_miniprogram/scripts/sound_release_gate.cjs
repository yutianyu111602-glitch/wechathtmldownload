const path = require("node:path");

function gateError(code, message) {
  return Object.assign(new Error(`${code}: ${message}`), { code });
}

async function responseJson(response) {
  try { return await response.json(); } catch (_) { return null; }
}

async function verifySoundReleaseGate({ baseUrl, fetchImpl = globalThis.fetch, callGatewayProbe } = {}) {
  const normalizedBaseUrl = String(baseUrl || "").trim().replace(/\/+$/, "");
  if (!/^https:\/\//i.test(normalizedBaseUrl) || typeof fetchImpl !== "function" || typeof callGatewayProbe !== "function") {
    throw gateError("SOUND_RELEASE_GATE_NOT_CONFIGURED", "HTTPS base URL, fetch, and mini gateway probe are required");
  }

  const forgedResponse = await fetchImpl(`${normalizedBaseUrl}/api/v1/weekly/sounds`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-wx-openid": "forged-release-gate-openid",
      "x-wx-appid": "forged-release-gate-appid",
    },
    body: JSON.stringify({
      submissionKey: "release_gate_must_never_write",
      clubName: "release gate",
      soundFileIds: ["cloud://forged/never-write.jpg"],
      paymentFileIds: ["cloud://forged/never-write.jpg"],
      version: 4,
    }),
  });
  const forgedPayload = await responseJson(forgedResponse);
  const forgedCode = String(forgedPayload && forgedPayload.error && forgedPayload.error.code || "");
  const publicForgeryRejected = (forgedResponse.status === 401 || forgedResponse.status === 403)
    && (forgedCode === "SOUND_SUBMISSION_SIGNATURE_REQUIRED" || forgedCode === "SOUND_SUBMISSION_INVALID_SIGNATURE");
  if (!publicForgeryRejected) {
    throw gateError(
      "SOUND_RELEASE_GATE_PUBLIC_FORGERY_ACCEPTED",
      `Expected signed-ingress rejection, received HTTP ${forgedResponse.status} ${forgedCode || "without error code"}`,
    );
  }

  const probe = await callGatewayProbe();
  const gatewayProbeVerified = Boolean(
    probe
    && probe.ok === true
    && probe.verifiedIngress === true
    && probe.writeExecuted === false,
  );
  if (!gatewayProbeVerified) {
    throw gateError("SOUND_RELEASE_GATE_GATEWAY_PROBE_FAILED", "Signed mini-program gateway probe did not prove a non-writing ingress path");
  }

  return {
    schemaVersion: "weekly_sound_release_gate.v1",
    ok: true,
    publicForgeryRejected,
    publicForgeryStatus: forgedResponse.status,
    publicForgeryCode: forgedCode,
    gatewayProbeVerified,
    gatewayWriteExecuted: false,
  };
}

async function main() {
  const root = path.resolve(__dirname, "..");
  const baseUrl = String(process.env.WEEKLY_SOUND_GATE_BASE_URL || "").trim();
  const functionName = String(process.env.WEEKLY_SOUND_GATEWAY_FUNCTION || "soundSubmissionGateway").trim();
  const automator = require(path.join(root, "node_modules", "miniprogram-automator"));
  const mini = await automator.launch({
    projectPath: process.env.WEEKLY_MINIPROGRAM_PROJECT || root,
    cliPath: process.env.WECHAT_DEVTOOLS_CLI || "C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat",
    port: Number(process.env.WECHAT_AUTOMATOR_PORT || 9420),
    idePort: Number(process.env.WECHAT_IDE_PORT || 9430),
    trustProject: true,
    timeout: 60_000,
  });
  try {
    const result = await verifySoundReleaseGate({
      baseUrl,
      callGatewayProbe: async () => {
        const invocation = await mini.evaluate((name) => new Promise((resolve) => {
          wx.cloud.callFunction({
            name,
            data: { action: "probe" },
            success: (response) => resolve({ transportOk: true, result: response.result }),
            fail: (error) => resolve({
              transportOk: false,
              error: error && (error.code || error.errMsg || error.message) || "callFunction failed",
            }),
          });
        }), functionName);
        if (!invocation || !invocation.transportOk) {
          throw gateError("SOUND_RELEASE_GATE_GATEWAY_CALL_FAILED", "Mini-program could not invoke the signed gateway probe");
        }
        return invocation.result;
      },
    });
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } finally {
    if (typeof mini.disconnect === "function") mini.disconnect();
  }
}

module.exports = { verifySoundReleaseGate };

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${JSON.stringify({
      schemaVersion: "weekly_sound_release_gate.v1",
      ok: false,
      error: { code: error && error.code || "SOUND_RELEASE_GATE_FAILED", message: error && error.message || String(error) },
    }, null, 2)}\n`);
    process.exitCode = 1;
  });
}
