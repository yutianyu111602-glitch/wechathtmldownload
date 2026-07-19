const path = require("path");

const root = path.resolve(__dirname, "..");
const automator = require(path.join(root, "node_modules", "miniprogram-automator"));

const projectPath = process.env.WEEKLY_MINIPROGRAM_PROJECT || root;
const cliPath = process.env.WECHAT_DEVTOOLS_CLI || "C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat";
const automatorPort = Number(process.env.WECHAT_AUTOMATOR_PORT || 9420);
const idePort = Number(process.env.WECHAT_IDE_PORT || 9430);
const functionName = process.env.WEEKLY_DATA_FUNCTION || "weeklyDataSync";
const baseUrl = process.env.WEEKLY_DATA_SYNC_BASE_URL || "";
const adminToken = process.env.WEEKLY_DATA_SYNC_ADMIN_TOKEN || "";

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
    const syncResult = await mini.evaluate((name, sourceBaseUrl, token) => new Promise((resolve) => {
      wx.cloud.callFunction({
        name,
        data: {
          action: "sync",
          baseUrl: sourceBaseUrl || undefined,
          source: "sync-cloudbase-database-script",
          adminToken: token,
        },
        success: (res) => resolve({ ok: true, result: res.result }),
        fail: (err) => resolve({ ok: false, errMsg: err.errMsg, code: err.code, message: err.message }),
      });
    }), functionName, baseUrl, adminToken);

    const readResult = await mini.evaluate((name) => new Promise((resolve) => {
      wx.cloud.callFunction({
        name,
        data: {
          action: "read",
          path: "/api/v1/weekly/current",
          query: { limit: 3 },
          source: "sync-cloudbase-database-script",
        },
        success: (res) => resolve({ ok: true, result: res.result }),
        fail: (err) => resolve({ ok: false, errMsg: err.errMsg, code: err.code, message: err.message }),
      });
    }), functionName);

    const summary = {
      ok: Boolean(syncResult && syncResult.ok && syncResult.result && syncResult.result.ok && readResult && readResult.ok && readResult.result && Array.isArray(readResult.result.items)),
      sync: syncResult,
      readProbe: {
        ok: Boolean(readResult && readResult.ok),
        schemaVersion: readResult && readResult.result && readResult.result.schemaVersion,
        itemCount: readResult && readResult.result && readResult.result.items && readResult.result.items.length,
        total: readResult && readResult.result && readResult.result.page && readResult.result.page.total,
        source: readResult && readResult.result && readResult.result.source,
        error: readResult && readResult.result && readResult.result.error,
      },
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
