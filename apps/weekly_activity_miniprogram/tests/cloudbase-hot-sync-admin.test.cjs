const assert = require("node:assert/strict");
const { configFor, extractFirstJson, invokeResult } = require("../scripts/run_cloudbase_hot_sync_admin.cjs");
const fs = require("node:fs");
const path = require("node:path");

const config = configFor("test-token");
assert.equal(config.functions[0].envVariables.WEEKLY_DATA_SYNC_ADMIN_TOKEN, "test-token");
assert.match(config.functions[0].envVariables.WEEKLY_DATA_SYNC_BASE_URL, /^https:\/\//);
assert.equal(config.functions[0].timeout, 120);
assert.equal(config.functions[0].envVariables.WEEKLY_DATA_SYNC_WRITE_BATCH_SIZE, "5");
assert.equal(config.functions[0].envVariables.WEEKLY_DATA_SYNC_WRITE_BATCH_DELAY_MS, "100");

const parsed = extractFirstJson('noise\n{"data":{"RetMsg":"{\\"ok\\":true}"}}\n- Loading data...');
assert.deepEqual(invokeResult(parsed), { ok: true });

const runnerSource = fs.readFileSync(path.join(__dirname, "../scripts/run_cloudbase_hot_sync_admin.cjs"), "utf8");
assert.equal((runnerSource.match(/\["-y", "config", "update"/g) || []).length, 2);

console.log("cloudbase hot sync admin helpers ok");
