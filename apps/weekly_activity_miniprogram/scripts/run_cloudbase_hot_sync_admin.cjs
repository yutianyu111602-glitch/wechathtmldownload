const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e";
const FUNCTION_NAME = "weeklyDataSync";
const BASE_URL = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com";
const CLOUDBASE_CLI_PACKAGE = "@cloudbase/cli@3.3.1";

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
        WEEKLY_DATA_SYNC_LOOKBACK_DAYS: "0",
      },
    }],
  };
}

function resolveCloudbaseCli(env = process.env, platform = process.platform, execPath = process.execPath) {
  const configured = String(env.WEEKLY_CLOUDBASE_CLI || "").trim();
  if (configured) {
    return {
      command: configured,
      argsPrefix: [],
      source: "WEEKLY_CLOUDBASE_CLI",
      windowsCommandScript: platform === "win32" && /\.(?:cmd|bat)$/i.test(configured),
    };
  }
  if (platform === "win32") {
    return {
      command: execPath,
      argsPrefix: [
        path.join(path.dirname(execPath), "node_modules", "npm", "bin", "npm-cli.js"),
        "exec", "--yes", "--package", CLOUDBASE_CLI_PACKAGE, "--", "tcb",
      ],
      source: "pinned-npm-exec",
      windowsCommandScript: false,
    };
  }
  return {
    command: "npm",
    argsPrefix: ["exec", "--yes", "--package", CLOUDBASE_CLI_PACKAGE, "--", "tcb"],
    source: "pinned-npm-exec",
    windowsCommandScript: false,
  };
}

function quoteWindowsCommandToken(value) {
  const token = String(value);
  if (/[\u0000\r\n]/.test(token)) throw new Error("Windows command token contains a forbidden control character");
  return `"${token.replace(/"/g, '""')}"`;
}

function buildSpawnSpec(cli, args, env = process.env, platform = process.platform) {
  const allArgs = [...cli.argsPrefix, ...args];
  if (platform === "win32" && cli.windowsCommandScript) {
    const commandLine = [cli.command, ...allArgs].map(quoteWindowsCommandToken).join(" ");
    return {
      command: env.ComSpec || "cmd.exe",
      args: ["/d", "/s", "/c", `"${commandLine}"`],
      windowsVerbatimArguments: true,
    };
  }
  return {
    command: cli.command,
    args: allArgs,
    windowsVerbatimArguments: false,
  };
}

function buildSyncEvent(adminToken) {
  return {
    action: "sync",
    baseUrl: BASE_URL,
    scope: "current",
    syncLookbackDays: 0,
    source: "codex-admin-rotating-token-sync",
    adminToken,
  };
}

function buildReadbackEvents() {
  const currentQuery = { scope: "current", lookbackDays: 0 };
  return {
    config: {
      action: "read",
      path: "/api/v1/weekly/config",
      query: {},
      source: "codex-post-sync-read",
    },
    current: {
      action: "read",
      path: "/api/v1/weekly/current",
      query: { ...currentQuery, limit: 100 },
      source: "codex-post-sync-read",
    },
    cities: {
      action: "read",
      path: "/api/v1/weekly/cities",
      query: { ...currentQuery },
      source: "codex-post-sync-read",
    },
    dates: {
      action: "read",
      path: "/api/v1/weekly/dates",
      query: { ...currentQuery },
      source: "codex-post-sync-read",
    },
  };
}

function generatedAtOf(value) {
  return value && (value.generatedAt || value.generated_at) || null;
}

function validateGenerationReadback(sync, readback) {
  if (!sync || sync.ok !== true || !sync.syncId || !generatedAtOf(sync)) {
    throw new Error("weeklyDataSync sync did not commit an active generation");
  }
  if (!sync.cleanup || sync.cleanup.ok !== true) {
    throw new Error("weeklyDataSync active generation committed but old-generation cleanup is incomplete");
  }
  const names = ["config", "current", "cities", "dates"];
  for (const name of names) {
    const value = readback && readback[name];
    if (!value || value.error) throw new Error(`weeklyDataSync ${name} readback failed`);
    if (value.syncId !== sync.syncId) {
      throw new Error(`weeklyDataSync ${name} syncId mismatch: ${value.syncId || "<missing>"} != ${sync.syncId}`);
    }
    if (generatedAtOf(value) !== sync.generatedAt) {
      throw new Error(`weeklyDataSync ${name} generatedAt mismatch`);
    }
  }
  const expected = Number(sync.counts && sync.counts.currentItems);
  const configCount = Number(readback.config.counts && readback.config.counts.currentItems);
  const currentTotal = Number(readback.current.page && readback.current.page.total);
  const citiesTotal = Number(readback.cities.item_count);
  const datesTotal = Number(readback.dates.item_count);
  const counts = [configCount, currentTotal, citiesTotal, datesTotal];
  if (!Number.isFinite(expected) || counts.some((value) => value !== expected)) {
    throw new Error(`weeklyDataSync readback count mismatch: expected=${expected} values=${counts.join(",")}`);
  }
  for (const name of ["current", "cities", "dates"]) {
    if (readback[name].source !== "cloudbase-database") {
      throw new Error(`weeklyDataSync ${name} did not read from cloudbase-database`);
    }
  }
  return {
    ok: true,
    syncId: sync.syncId,
    generatedAt: sync.generatedAt,
    currentTotal,
    cityCount: Array.isArray(readback.cities.cities) ? readback.cities.cities.length : 0,
    dateCount: Array.isArray(readback.dates.dates) ? readback.dates.dates.length : 0,
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

function runTcb(args, cwd, secrets, { expectJson = true, cli = resolveCloudbaseCli() } = {}) {
  const spawnSpec = buildSpawnSpec(cli, args);
  const result = spawnSync(spawnSpec.command, spawnSpec.args, {
    cwd,
    encoding: "utf8",
    windowsHide: true,
    windowsVerbatimArguments: spawnSpec.windowsVerbatimArguments,
    maxBuffer: 16 * 1024 * 1024,
  });
  if (result.status !== 0) {
    let detail = `${result.error && result.error.message || ""}\n${result.stderr || ""}\n${result.stdout || ""}`.trim();
    for (const secret of secrets) {
      if (secret) detail = detail.split(secret).join("[REDACTED]");
    }
    throw new Error(`TCB command failed (${cli.source}; ${args.slice(0, 3).join(" ")}): ${detail.slice(-1200)}`);
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
  const cli = resolveCloudbaseCli();
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "weekly-cloudbase-sync-"));
  fs.mkdirSync(path.join(tempDir, "cloudfunctions"));
  const invocationToken = randomToken();
  let rotationToken = "";
  let configured = false;
  try {
    writeConfig(tempDir, invocationToken);
    if (dryRun) {
      console.log(JSON.stringify({
        ok: true,
        dryRun: true,
        cloudbaseCliSource: cli.source,
        cloudbaseCliPackage: cli.source === "pinned-npm-exec" ? CLOUDBASE_CLI_PACKAGE : null,
        scope: "current",
        syncLookbackDays: 0,
        tokenPrinted: false,
        tempCleanedOnExit: true,
      }));
      return;
    }

    runTcb(
      ["-y", "config", "update", "fn", FUNCTION_NAME, "--json"],
      tempDir,
      [invocationToken],
      { expectJson: false, cli },
    );
    configured = true;
    const syncEvent = writeEvent(tempDir, "sync-event.json", buildSyncEvent(invocationToken));
    let sync = null;
    for (let attempt = 1; attempt <= 6; attempt += 1) {
      sync = invokeResult(runTcb(
        ["fn", "invoke", FUNCTION_NAME, "-d", `@${syncEvent}`, "--json"],
        tempDir,
        [invocationToken],
        { cli },
      ));
      if (!(sync && sync.error && sync.error.code === "ADMIN_ACTION_UNAUTHORIZED")) break;
      if (attempt < 6) sleep(10_000);
    }
    if (!sync || sync.ok !== true) throw new Error(`weeklyDataSync sync failed: ${JSON.stringify(sync)}`);

    const readback = {};
    for (const [name, event] of Object.entries(buildReadbackEvents())) {
      const eventPath = writeEvent(tempDir, `read-${name}-event.json`, event);
      readback[name] = invokeResult(runTcb(
        ["fn", "invoke", FUNCTION_NAME, "-d", `@${eventPath}`, "--json"],
        tempDir,
        [invocationToken],
        { cli },
      ));
    }
    const verified = validateGenerationReadback(sync, readback);

    console.log(JSON.stringify({
      ok: true,
      sync: {
        syncId: sync.syncId,
        syncedAt: sync.syncedAt,
        counts: sync.counts,
        cleanup: sync.cleanup,
        aiSummaryError: sync.aiSummaryError || null,
      },
      readback: verified,
      cloudbaseCliSource: cli.source,
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
          { expectJson: false, cli },
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

module.exports = {
  buildReadbackEvents,
  buildSpawnSpec,
  buildSyncEvent,
  configFor,
  extractFirstJson,
  invokeResult,
  resolveCloudbaseCli,
  validateGenerationReadback,
};
