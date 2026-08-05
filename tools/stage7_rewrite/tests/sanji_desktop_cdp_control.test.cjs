const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { test } = require("node:test");

const repoRoot = path.resolve(__dirname, "..", "..", "..");
const scriptPath = path.join(repoRoot, "tools", "stage7_rewrite", "scripts", "sanji_desktop_cdp_control.mjs");

function optionsFromExpression(expression) {
  const match = String(expression).match(/const options = (\{[^\n]+\});/);
  return match ? JSON.parse(match[1]) : null;
}

function testPaths(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sanji-ledger-test-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return { dir, ledger: path.join(dir, "cycle.json") };
}

function makeArgs(parseArgs, ledger, fakeids = "account-a,account-b") {
  return parseArgs([
    "--action", "sync-sequential",
    "--fakeids", fakeids,
    "--completion-ledger", ledger,
    "--cycle-id", "test-cycle",
    "--max-client-accounts", "20",
    "--credential-policy", "ready-only",
    "--inter-account-delay-ms", "0",
    "--poll-ms", "1",
  ]);
}

class FakeCdpClient {
  constructor({
    readyFakeids = ["account-a", "account-b"],
    missingCount = 0,
    syncPhases = ["idle"],
    syncErrors = [],
    captureRateLimited = false,
  } = {}) {
    this.readyFakeids = readyFakeids;
    this.missingCount = missingCount;
    this.syncPhases = syncPhases;
    this.syncErrors = syncErrors;
    this.captureRateLimited = captureRateLimited;
    this.syncStarts = [];
    this.resumeCalls = 0;
    this.phaseIndex = 0;
  }

  async send(method, params) {
    assert.equal(method, "Runtime.evaluate");
    const options = optionsFromExpression(params.expression);
    if (options && options.action === "sync-preflight") {
      if (this.captureRateLimited) {
        return {
          exceptionDetails: {
            text: "Uncaught (in promise)",
            exception: { description: "Error: sanji_client_rate_limited_preflight" },
          },
          result: { type: "undefined" },
        };
      }
      return { result: { value: {
        ok: true,
        channel: "client",
        coverage_scope: "broadcast_only",
        capture: { phase: "captured", rate_limited: false, secret_values_exposed: false },
        sync: { phase: "idle" },
        secret_values_exposed: false,
      } } };
    }
    if (options && options.action === "credential-readiness") {
      return { result: { value: {
        ok: true,
        channel: "client",
        coverage_scope: "broadcast_only",
        ready_fakeids: this.readyFakeids,
        credentials: {
          requested_count: this.readyFakeids.length + this.missingCount,
          ready_count: this.readyFakeids.length,
          missing_or_expired_count: this.missingCount,
          selected_count: 0,
          minimum_ttl_minutes: 20,
          secret_values_exposed: false,
        },
      } } };
    }
    if (options && options.action === "resume-sync") {
      this.resumeCalls += 1;
      return { result: { value: { ok: true, resumed: "sync" } } };
    }
    if (options && options.action === "sync") {
      this.syncStarts.push(options.fakeids[0]);
      return { result: { value: {
        ok: true,
        started: "sync",
        selected_fakeid_count: 1,
        channel: "client",
        coverage_scope: "broadcast_only",
      } } };
    }
    const index = Math.min(this.phaseIndex, this.syncPhases.length - 1);
    const phase = this.syncPhases[index] || "idle";
    const lastError = this.syncErrors[index] || (phase === "paused_error" ? "token_expired" : "");
    this.phaseIndex += 1;
    return { result: { value: {
      sync: { phase, ...(lastError ? { lastError } : {}) },
      fetch: { phase: "idle" },
      resource: { phase: "idle" },
    } } };
  }
}

async function loadModule() {
  return import(`${pathToFileURL(scriptPath).href}?test=${Date.now()}-${Math.random()}`);
}

test("sync-sequential writes a complete ordered ledger without secrets", async (t) => {
  const { parseArgs, runSequentialSync } = await loadModule();
  const paths = testPaths(t);
  const client = new FakeCdpClient();
  const report = await runSequentialSync(
    client,
    makeArgs(parseArgs, paths.ledger),
    { title: "公号三刀", url: "file:///sanji" }
  );

  const ledger = JSON.parse(fs.readFileSync(paths.ledger, "utf8"));
  assert.deepEqual(client.syncStarts, ["account-a", "account-b"]);
  assert.equal(report.sequential_sync.completed_count, 2);
  assert.equal(report.sequential_sync.cycle_complete, true);
  assert.equal(ledger.status, "complete");
  assert.deepEqual(ledger.accounts.map((item) => item.fakeid), ["account-a", "account-b"]);
  assert.equal(ledger.secret_values_exposed, false);
  assert.doesNotMatch(JSON.stringify(ledger), /cookie|token_value|license/i);
});

test("sync-sequential retries a paused token once before completing", async (t) => {
  const { parseArgs, runSequentialSync } = await loadModule();
  const paths = testPaths(t);
  const client = new FakeCdpClient({ readyFakeids: ["account-a"], syncPhases: ["paused_error", "idle"] });
  const args = makeArgs(parseArgs, paths.ledger, "account-a");
  args.syncResumeAttempts = 1;

  const report = await runSequentialSync(client, args, { title: "公号三刀", url: "file:///sanji" });

  assert.equal(client.resumeCalls, 1);
  assert.equal(report.sequential_sync.completed_count, 1);
  assert.equal(report.sequential_sync.accounts[0].resume_attempts, 1);
});

test("rate-limit preflight performs no sync request and persists blocker", async (t) => {
  const { parseArgs, runSequentialSync } = await loadModule();
  const paths = testPaths(t);
  const client = new FakeCdpClient({ captureRateLimited: true });

  await assert.rejects(
    runSequentialSync(client, makeArgs(parseArgs, paths.ledger), { title: "公号三刀", url: "file:///sanji" }),
    /sanji_client_rate_limited_preflight/
  );
  assert.deepEqual(client.syncStarts, []);
  const ledger = JSON.parse(fs.readFileSync(paths.ledger, "utf8"));
  assert.equal(ledger.status, "blocked_rate_limited");
  assert.equal(ledger.last_blocker.code, "client_rate_limited");
});

test("completed accounts are skipped when the same cycle resumes", async (t) => {
  const { parseArgs, runSequentialSync } = await loadModule();
  const paths = testPaths(t);
  const client = new FakeCdpClient();
  const target = { title: "公号三刀", url: "file:///sanji" };

  await runSequentialSync(client, makeArgs(parseArgs, paths.ledger), target);
  const second = await runSequentialSync(client, makeArgs(parseArgs, paths.ledger), target);

  assert.deepEqual(client.syncStarts, ["account-a", "account-b"]);
  assert.equal(second.sequential_sync.selected_count, 0);
  assert.equal(second.sequential_sync.cycle_complete, true);
});

test("a changed active-account scope cannot reuse an old cycle ledger", async (t) => {
  const { parseArgs, runSequentialSync } = await loadModule();
  const paths = testPaths(t);
  const client = new FakeCdpClient();
  const target = { title: "公号三刀", url: "file:///sanji" };

  await runSequentialSync(client, makeArgs(parseArgs, paths.ledger, "account-a"), target);
  await assert.rejects(
    runSequentialSync(client, makeArgs(parseArgs, paths.ledger, "account-a,account-b"), target),
    /sanji_completion_ledger_scope_mismatch/
  );
});

test("rate limit returned after start stops the cycle without resume", async (t) => {
  const { parseArgs, runSequentialSync } = await loadModule();
  const paths = testPaths(t);
  const client = new FakeCdpClient({
    readyFakeids: ["account-a"],
    syncPhases: ["paused_error"],
    syncErrors: ["client_rate_limited"],
  });

  await assert.rejects(
    runSequentialSync(
      client,
      makeArgs(parseArgs, paths.ledger, "account-a"),
      { title: "公号三刀", url: "file:///sanji" }
    ),
    /sanji_client_rate_limited/
  );
  assert.equal(client.resumeCalls, 0);
  assert.deepEqual(client.syncStarts, ["account-a"]);
  const ledger = JSON.parse(fs.readFileSync(paths.ledger, "utf8"));
  assert.equal(ledger.accounts[0].status, "rate_limited");
  assert.equal(ledger.status, "blocked_rate_limited");
});
