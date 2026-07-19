const assert = require("node:assert/strict");
const {
  buildReadbackEvents,
  buildSpawnSpec,
  buildSyncEvent,
  configFor,
  extractFirstJson,
  invokeResult,
  resolveCloudbaseCli,
  validateGenerationReadback,
} = require("../scripts/run_cloudbase_hot_sync_admin.cjs");
const fs = require("node:fs");
const path = require("node:path");

const config = configFor("test-token");
assert.equal(config.functions[0].envVariables.WEEKLY_DATA_SYNC_ADMIN_TOKEN, "test-token");
assert.match(config.functions[0].envVariables.WEEKLY_DATA_SYNC_BASE_URL, /^https:\/\//);
assert.equal(config.functions[0].timeout, 120);
assert.equal(config.functions[0].envVariables.WEEKLY_DATA_SYNC_WRITE_BATCH_SIZE, "5");
assert.equal(config.functions[0].envVariables.WEEKLY_DATA_SYNC_WRITE_BATCH_DELAY_MS, "100");
assert.equal(config.functions[0].envVariables.WEEKLY_DATA_SYNC_LOOKBACK_DAYS, "0");

const pinnedCli = resolveCloudbaseCli({}, "win32", "C:/Program Files/nodejs/node.exe");
assert.equal(pinnedCli.command, "C:/Program Files/nodejs/node.exe");
assert.deepEqual(pinnedCli.argsPrefix, [
  path.normalize("C:/Program Files/nodejs/node_modules/npm/bin/npm-cli.js"),
  "exec", "--yes", "--package", "@cloudbase/cli@3.3.1", "--", "tcb",
]);
assert.equal(pinnedCli.source, "pinned-npm-exec");
assert.equal(pinnedCli.windowsCommandScript, false);

const configuredCli = resolveCloudbaseCli({ WEEKLY_CLOUDBASE_CLI: "F:/tools/tcb.cmd" }, "win32");
assert.equal(configuredCli.command, "F:/tools/tcb.cmd");
assert.deepEqual(configuredCli.argsPrefix, []);
assert.equal(configuredCli.source, "WEEKLY_CLOUDBASE_CLI");
assert.equal(configuredCli.windowsCommandScript, true);
const configuredSpawn = buildSpawnSpec(
  configuredCli,
  ["fn", "invoke", "weeklyDataSync", "-d", "@F:/Temp Dir/event.json"],
  { ComSpec: "C:/Windows/System32/cmd.exe" },
  "win32",
);
assert.equal(configuredSpawn.command, "C:/Windows/System32/cmd.exe");
assert.deepEqual(configuredSpawn.args.slice(0, 3), ["/d", "/s", "/c"]);
assert.match(configuredSpawn.args[3], /^""F:\/tools\/tcb\.cmd" /);
assert.match(configuredSpawn.args[3], /"@F:\/Temp Dir\/event\.json""$/);
assert.equal(configuredSpawn.windowsVerbatimArguments, true);

const syncEvent = buildSyncEvent("test-token");
assert.equal(syncEvent.scope, "current");
assert.equal(syncEvent.syncLookbackDays, 0);
assert.equal(syncEvent.adminToken, "test-token");

const readbackEvents = buildReadbackEvents();
assert.deepEqual(Object.keys(readbackEvents).sort(), ["cities", "config", "current", "dates"]);
for (const name of ["current", "cities", "dates"]) {
  assert.equal(readbackEvents[name].query.scope, "current");
  assert.equal(readbackEvents[name].query.lookbackDays, 0);
}

const readback = validateGenerationReadback(
  {
    ok: true,
    syncId: "weekly_test",
    generatedAt: "2026-07-19T00:00:00Z",
    counts: { currentItems: 3 },
    cleanup: { ok: true },
  },
  {
    config: { syncId: "weekly_test", generatedAt: "2026-07-19T00:00:00Z", counts: { currentItems: 3 } },
    current: { syncId: "weekly_test", generatedAt: "2026-07-19T00:00:00Z", page: { total: 3 }, items: [], source: "cloudbase-database" },
    cities: { syncId: "weekly_test", generated_at: "2026-07-19T00:00:00Z", item_count: 3, cities: [], source: "cloudbase-database" },
    dates: { syncId: "weekly_test", generated_at: "2026-07-19T00:00:00Z", item_count: 3, dates: [], source: "cloudbase-database" },
  },
);
assert.equal(readback.ok, true);
assert.equal(readback.currentTotal, 3);
assert.throws(() => validateGenerationReadback(
  {
    ok: true,
    syncId: "weekly_test",
    generatedAt: "2026-07-19T00:00:00Z",
    counts: { currentItems: 3 },
    cleanup: { ok: true },
  },
  {
    config: { syncId: "weekly_old", generatedAt: "2026-07-19T00:00:00Z", counts: { currentItems: 3 } },
    current: { syncId: "weekly_test", generatedAt: "2026-07-19T00:00:00Z", page: { total: 3 }, source: "cloudbase-database" },
    cities: { syncId: "weekly_test", generated_at: "2026-07-19T00:00:00Z", item_count: 3, source: "cloudbase-database" },
    dates: { syncId: "weekly_test", generated_at: "2026-07-19T00:00:00Z", item_count: 3, source: "cloudbase-database" },
  },
), /syncId mismatch/);

const parsed = extractFirstJson('noise\n{"data":{"RetMsg":"{\\"ok\\":true}"}}\n- Loading data...');
assert.deepEqual(invokeResult(parsed), { ok: true });

const runnerSource = fs.readFileSync(path.join(__dirname, "../scripts/run_cloudbase_hot_sync_admin.cjs"), "utf8");
assert.equal((runnerSource.match(/\["-y", "config", "update"/g) || []).length, 2);
assert.doesNotMatch(runnerSource, /syncLookbackDays:\s*45|lookbackDays:\s*45/);
assert.match(runnerSource, /@cloudbase\/cli@3\.3\.1/);

console.log("cloudbase hot sync admin helpers ok");
