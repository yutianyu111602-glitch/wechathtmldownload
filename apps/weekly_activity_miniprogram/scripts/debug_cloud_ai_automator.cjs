const path = require("path");

const root = path.resolve(__dirname, "..");
const automator = require(path.join(root, "node_modules", "miniprogram-automator"));

const projectPath = process.env.WEEKLY_MINIPROGRAM_PROJECT || root;
const cliPath = process.env.WECHAT_DEVTOOLS_CLI || "C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat";
const automatorPort = Number(process.env.WECHAT_AUTOMATOR_PORT || 9420);
const idePort = Number(process.env.WECHAT_IDE_PORT || 9430);
const targetPage = process.env.WEEKLY_AI_PAGE || "/pages/index/index";
const functionName = process.env.WEEKLY_AI_FUNCTION || "weeklyAiProxy";
const statusPath = process.env.WEEKLY_AI_STATUS_PATH || "/api/v1/weekly/llm/status";
const summaryPath = process.env.WEEKLY_AI_SUMMARY_PATH || "/api/v1/weekly/llm/weekly-summary";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function main() {
  const mini = await automator.launch({
    projectPath,
    cliPath,
    port: automatorPort,
    idePort,
    trustProject: true,
    timeout: 60000,
  });

  try {
    await mini.reLaunch(targetPage);
    await sleep(1500);
    const page = await mini.currentPage();
    const statusResult = await mini.evaluate((name, apiPath) => new Promise((resolve) => {
      wx.cloud.callFunction({
        name,
        data: {
          method: "GET",
          path: apiPath,
          source: "debug-cloud-ai-automator",
        },
        success: (res) => resolve({
          ok: true,
          result: res.result,
        }),
        fail: (err) => resolve({
          ok: false,
          errMsg: err.errMsg,
          code: err.code,
          message: err.message,
        }),
      });
    }), functionName, statusPath);
    const summaryResult = await mini.evaluate((name, apiPath) => new Promise((resolve) => {
      wx.cloud.callFunction({
        name,
        data: {
          method: "GET",
          path: apiPath,
          source: "debug-cloud-ai-automator",
        },
        success: (res) => resolve({
          ok: true,
          result: res.result,
        }),
        fail: (err) => resolve({
          ok: false,
          errMsg: err.errMsg,
          code: err.code,
          message: err.message,
        }),
      });
    }), functionName, summaryPath);

    const summaryPayload = summaryResult && summaryResult.result;
    const summaryError = summaryPayload && summaryPayload.error;
    const summaryFallbackUsed = Boolean(summaryPayload && summaryPayload.cloudFunction && summaryPayload.cloudFunction.fallbackUsed);
    const summary = {
      ok: Boolean(statusResult && statusResult.ok && summaryResult && summaryResult.ok && !summaryError && !summaryFallbackUsed),
      page: page.path,
      targetPage,
      functionName,
      status: {
        schemaVersion: statusResult && statusResult.result && statusResult.result.schemaVersion,
        provider: statusResult && statusResult.result && statusResult.result.llm && statusResult.result.llm.provider,
        model: statusResult && statusResult.result && statusResult.result.llm && statusResult.result.llm.model,
        cloudFunction: statusResult && statusResult.result && statusResult.result.cloudFunction,
      },
      weeklySummary: {
        schemaVersion: summaryPayload && summaryPayload.schemaVersion,
        provider: summaryPayload && summaryPayload.provider,
        model: summaryPayload && summaryPayload.model,
        source: summaryPayload && summaryPayload.source,
        fallbackUsed: summaryFallbackUsed,
        textPreview: String(summaryPayload && (summaryPayload.summary || summaryPayload.generatedSummary || "") || "").slice(0, 120),
        cloudFunction: summaryPayload && summaryPayload.cloudFunction,
        error: summaryError || null,
      },
      error: !statusResult || !statusResult.ok ? statusResult : (!summaryResult || !summaryResult.ok || summaryError || summaryFallbackUsed ? summaryResult : null),
    };

    console.log(JSON.stringify(summary, null, 2));
    if (!summary.ok) process.exitCode = 1;
  } finally {
    if (mini.disconnect) mini.disconnect();
  }
}

main().catch((error) => {
  console.error(JSON.stringify({
    ok: false,
    error: error && error.stack ? error.stack : String(error),
  }, null, 2));
  process.exit(1);
});
