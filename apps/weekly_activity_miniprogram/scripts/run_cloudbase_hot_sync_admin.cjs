const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e";
const FUNCTION_NAME = "weeklyDataSync";
const BASE_URL = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com";

function randomToken() {
  return crypto.randomBytes(32).toString("base64url");
}

function sleep(milliseconds) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
}

function configFor(token) {
  return {
    $schema: "https://static.cloudbase.net/cli/cloudbaserc.schema.json",
    envId: ENV_ID,
    functionRoot: "cloudfunctions",
    functions: [{
      name: FUNCTION_NAME,
      runtime: "Nodejs16.13",
      handler: "index.main",
      timeout: 120,
      memorySize: 256,
      envVariables: {
        WEEKLY_DATA_SYNC_ADMIN_TOKEN: token,
        WEEKLY_DATA_SYNC_BASE_URL: BASE_URL,
        WEEKLY_DATA_SYNC_WRITE_BATCH_SIZE: "5",
        WEEKLY_DATA_SYNC_WRITE_BATCH_DELAY_MS: "100",
        WEEKLY_DATA_SYNC_DB_RETRY_LIMIT: "3",
      },
    }],
  };
}

function extractFirstJson(text) {
  const source = String(text || "");
  const start = source.indexOf("{");
  if (start < 0) throw new Error("TCB output did not contain JSON");
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let index = start; index < source.length; index += 1) {
    const char = source[index];
    if (inString) {
      if (escaped) escaped = false;
      else if (char === "\\") escaped = true;
      else if (char === '"') inString = false;
      continue;
    }
    if (char === '"') inString = true;
    else if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth === 0) return JSON.parse(source.slice(start, index + 1));
    }
  }
  throw new Error("TCB JSON output was incomplete");
}

function runTcb(args, cwd, secrets, { expectJson = true } = {}) {
  const command = process.env.ComSpec || "cmd.exe";
  const result = spawnSync(command, ["/d", "/s", "/c", "tcb", ...args], {
    cwd,
    encoding: "utf8",
    windowsHide: true,
    maxBuffer: 16 * 1024 * 1024,
  });
  if (result.status !== 0) {
    let detail = `${result.stderr || ""}\n${result.stdout || ""}`.trim();
    for (const secret of secrets) {
      if (secret) detail = detail.split(secret).join("[REDACTED]");
    }
    throw new Error(`TCB command failed (${args.slice(0, 3).join(" ")}): ${detail.slice(-1200)}`);
  }
  return expectJson ? extractFirstJson(result.stdout) : null;
}

function invokeResult(cliResult) {
  const retMsg = cliResult && cliResult.data && cliResult.data.RetMsg;
  if (!retMsg) throw new Error("TCB invoke response did not contain RetMsg");
  return JSON.parse(retMsg);
}

function writeConfig(tempDir, token) {
  fs.writeFileSync(
    path.join(tempDir, "cloudbaserc.json"),
    `${JSON.stringify(configFor(token), null, 2)}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
}

function writeEvent(tempDir, name, value) {
  const target = path.join(tempDir, name);
  fs.writeFileSync(target, `${JSON.stringify(value)}\n`, { encoding: "utf8", mode: 0o600 });
  return target;
}

function main() {
  const dryRun = process.argv.includes("--dry-run");
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "weekly-cloudbase-sync-"));
  fs.mkdirSync(path.join(tempDir, "cloudfunctions"));
  const invocationToken = randomToken();
  let rotationToken = "";
  let configured = false;
  try {
    writeConfig(tempDir, invocationToken);
    if (dryRun) {
      console.log(JSON.stringify({ ok: true, dryRun: true, tokenPrinted: false, tempCleanedOnExit: true }));
      return;
    }

    runTcb(
      ["-y", "config", "update", "fn", FUNCTION_NAME, "--json"],
      tempDir,
      [invocationToken],
      { expectJson: false },
    );
    configured = true;
    const syncEvent = writeEvent(tempDir, "sync-event.json", {
      action: "sync",
      baseUrl: BASE_URL,
      syncLookbackDays: 45,
      source: "codex-admin-rotating-token-sync",
      adminToken: invocationToken,
    });
    let sync = null;
    for (let attempt = 1; attempt <= 6; attempt += 1) {
      sync = invokeResult(runTcb(
        ["fn", "invoke", FUNCTION_NAME, "-d", `@${syncEvent}`, "--json"],
        tempDir,
        [invocationToken],
      ));
      if (!(sync && sync.error && sync.error.code === "ADMIN_ACTION_UNAUTHORIZED")) break;
      if (attempt < 6) sleep(10_000);
    }
    if (!sync || sync.ok !== true) throw new Error(`weeklyDataSync sync failed: ${JSON.stringify(sync)}`);

    const readEvent = writeEvent(tempDir, "read-event.json", {
      action: "read",
      path: "/api/v1/weekly/current",
      query: { limit: 3, lookbackDays: 45 },
      source: "codex-post-sync-read",
    });
    const read = invokeResult(runTcb(
      ["fn", "invoke", FUNCTION_NAME, "-d", `@${readEvent}`, "--json"],
      tempDir,
      [invocationToken],
    ));
    if (!read || !Array.isArray(read.items)) throw new Error(`weeklyDataSync readback failed: ${JSON.stringify(read)}`);

    console.log(JSON.stringify({
      ok: true,
      sync: {
        syncId: sync.syncId,
        syncedAt: sync.syncedAt,
        counts: sync.counts,
        aiSummaryError: sync.aiSummaryError || null,
      },
      readback: {
        schemaVersion: read.schemaVersion || read.schema_version,
        generatedAt: read.generatedAt || read.generated_at,
        total: read.page && read.page.total,
        itemCount: read.items.length,
        source: read.source,
      },
      tokenPrinted: false,
    }, null, 2));
  } finally {
    if (configured) {
      rotationToken = randomToken();
      try {
        writeConfig(tempDir, rotationToken);
        runTcb(
          ["-y", "config", "update", "fn", FUNCTION_NAME, "--json"],
          tempDir,
          [invocationToken, rotationToken],
          { expectJson: false },
        );
      } catch (error) {
        process.exitCode = 1;
        console.error(JSON.stringify({ ok: false, stage: "final-token-rotation", error: error.message }));
      }
    }
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(JSON.stringify({ ok: false, error: error.message }));
    process.exitCode = 1;
  }
}

module.exports = { configFor, extractFirstJson, invokeResult };
