<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Night Watcher v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stronger autonomous watcher that safely supervises the completed HTML archive through assets, export, OCR, final pack, and 20-50 article downstream matrix, then stops at the checkpoint.

**Architecture:** Add a `nightWatcher` orchestrator that reads existing status files, result logs, and process matches, then emits one decision per heartbeat. It reuses existing CLI commands rather than rewriting stage internals.

**Tech Stack:** Node.js 20+, TypeScript, existing `tsx` CLI, node:test, PowerShell process inspection on Windows.

---

## File Structure

- Create: `src/orchestrator/nightWatcher/types.ts`
- Create: `src/orchestrator/nightWatcher/statusReaders.ts`
- Create: `src/orchestrator/nightWatcher/decisionEngine.ts`
- Create: `src/orchestrator/nightWatcher/commandPlanner.ts`
- Create: `src/orchestrator/nightWatcher/nightWatcher.ts`
- Create: `tests/nightWatcherDecision.test.ts`
- Create: `tests/nightWatcherStatusReaders.test.ts`
- Modify: `src/cli.ts`
- Modify: `package.json`
- Update: `NIGHT_WATCHER_LONGRUN_PLAN_2026-04-22.md`

## Task 1: Stage Types And Defaults

**Files:**

- Create: `src/orchestrator/nightWatcher/types.ts`
- Test: `tests/nightWatcherDecision.test.ts`

- [ ] **Step 1: Write the failing type-level behavior test**

```ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { defaultNightWatcherConfig } from "../src/orchestrator/nightWatcher/types.js";

test("night watcher defaults use canonical production paths", () => {
  const config = defaultNightWatcherConfig();
  assert.equal(config.archiveRoot, "D:/DDownload/_archive_mptext");
  assert.equal(config.manifestPath, "D:/DDownload/_queues/download_ready_queue.jsonl");
  assert.equal(config.artifactRoot, "D:/DDownload/_llm_artifacts");
  assert.equal(config.releaseRoot, "D:/DDownload/_llm_release");
  assert.equal(config.stopAfterStage, "downstream_matrix_50");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx tsx --test tests/nightWatcherDecision.test.ts`

Expected: FAIL because `types.ts` does not exist.

- [ ] **Step 3: Add stage and config types**

Implement `NightWatcherStage`, `NightWatcherDecision`, `StageStatusSummary`, `NightWatcherConfig`, and `defaultNightWatcherConfig()` in `types.ts`.

- [ ] **Step 4: Run the test again**

Run: `npx tsx --test tests/nightWatcherDecision.test.ts`

Expected: PASS.

## Task 2: Read Status Files Without Mutating Live Roots

**Files:**

- Create: `src/orchestrator/nightWatcher/statusReaders.ts`
- Test: `tests/nightWatcherStatusReaders.test.ts`

- [ ] **Step 1: Write the status reader test**

```ts
import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { readStageStatus } from "../src/orchestrator/nightWatcher/statusReaders.js";

test("readStageStatus summarizes common batch counters", async () => {
  const root = await mkdtemp(join(tmpdir(), "night-status-"));
  const statusPath = join(root, "status.json");
  await mkdir(root, { recursive: true });
  await writeFile(statusPath, JSON.stringify({
    status: "running",
    totalItems: 10,
    succeededCount: 3,
    failedCount: 1,
    skippedCount: 2,
    deferredCount: 1,
    queuedCount: 3,
    runningCount: 1
  }));

  const summary = await readStageStatus("assets", statusPath);
  assert.equal(summary.exists, true);
  assert.equal(summary.status, "running");
  assert.equal(summary.terminalCount, 7);
  assert.equal(summary.queuedCount, 3);
  assert.equal(summary.runningCount, 1);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx tsx --test tests/nightWatcherStatusReaders.test.ts`

Expected: FAIL because `statusReaders.ts` does not exist.

- [ ] **Step 3: Implement `readStageStatus`**

Use `fs.promises.readFile` and `stat`; tolerate missing files by returning `exists: false` instead of throwing.

- [ ] **Step 4: Run the test again**

Run: `npx tsx --test tests/nightWatcherStatusReaders.test.ts`

Expected: PASS.

## Task 3: Decision Engine

**Files:**

- Create: `src/orchestrator/nightWatcher/decisionEngine.ts`
- Modify: `tests/nightWatcherDecision.test.ts`

- [ ] **Step 1: Add decision tests for the current real stage**

```ts
import { decideNightWatcherAction } from "../src/orchestrator/nightWatcher/decisionEngine.js";

test("assets running means monitor and do not launch duplicate assets", () => {
  const decision = decideNightWatcherAction({
    htmlArchive: { stage: "html_archive", exists: true, status: "completed", totalItems: 93761, queuedCount: 0, runningCount: 0, terminalCount: 93761 },
    dajialaRepair: { stage: "dajiala_repair", exists: true, status: "completed", totalItems: 400, queuedCount: 0, runningCount: 0, terminalCount: 400 },
    assets: { stage: "assets", exists: true, status: "running", totalItems: 93761, queuedCount: 91491, runningCount: 1, terminalCount: 2269 },
    exportLlm: { stage: "export_llm", exists: false, status: "", totalItems: 0, queuedCount: 0, runningCount: 0, terminalCount: 0 },
  });
  assert.equal(decision.stage, "assets");
  assert.equal(decision.kind, "monitor");
  assert.equal(decision.shouldLaunch, false);
});
```

- [ ] **Step 2: Run the decision tests**

Run: `npx tsx --test tests/nightWatcherDecision.test.ts`

Expected: FAIL until the decision engine exists.

- [ ] **Step 3: Implement promotion logic**

Implement ordered rules: active stage monitors; completed stage promotes; missing future stage waits until prior stage validates; downstream matrix completion returns `CHECKPOINT_STOP`.

- [ ] **Step 4: Run tests**

Run: `npx tsx --test tests/nightWatcherDecision.test.ts`

Expected: PASS.

## Task 4: Command Planner And Duplicate Launch Guard

**Files:**

- Create: `src/orchestrator/nightWatcher/commandPlanner.ts`
- Modify: `tests/nightWatcherDecision.test.ts`

- [ ] **Step 1: Add command planner tests**

```ts
import { planStageCommand } from "../src/orchestrator/nightWatcher/commandPlanner.js";

test("export command uses canonical archive-aware paths", () => {
  const command = planStageCommand("export_llm", defaultNightWatcherConfig());
  assert.deepEqual(command.argv.slice(0, 3), ["tsx", "src/cli.ts", "export-llm-batch"]);
  assert.ok(command.argv.includes("--inputMode"));
  assert.ok(command.argv.includes("archive"));
  assert.ok(command.argv.includes("D:/DDownload/_llm_artifacts"));
});
```

- [ ] **Step 2: Run the planner tests**

Run: `npx tsx --test tests/nightWatcherDecision.test.ts`

Expected: FAIL until the planner exists.

- [ ] **Step 3: Implement exact commands**

Implement commands for `assets`, `export_llm`, `ocr_poster`, `final_pack`, and `downstream_matrix_50`. Use the paths and model variables from `HANDOFF.md`.

- [ ] **Step 4: Run tests**

Run: `npx tsx --test tests/nightWatcherDecision.test.ts`

Expected: PASS.

## Task 5: CLI Integration

**Files:**

- Create: `src/orchestrator/nightWatcher/nightWatcher.ts`
- Modify: `src/cli.ts`
- Modify: `package.json`
- Test: `tests/nightWatcherDecision.test.ts`

- [ ] **Step 1: Add CLI behavior test**

Add a test that imports `runNightWatcherOnce()` with fixture status paths and asserts the returned decision is `monitor` for running assets.

- [ ] **Step 2: Implement `runNightWatcherOnce()`**

Read configured status files, optionally check process matches, compute a decision, persist `.omc/state/night-watcher-v2-state.json`, and return a structured decision object.

- [ ] **Step 3: Wire CLI**

Add command usage:

```text
run-night-watcher --once [--dry-run] [--statePath path]
```

Add npm script:

```json
"watch:night": "tsx src/cli.ts run-night-watcher --once --dry-run"
```

- [ ] **Step 4: Verify CLI**

Run: `npm run build`

Expected: TypeScript build passes.

Run: `npm run watch:night`

Expected: prints a structured decision and does not launch a duplicate asset stage while assets are running.

## Task 6: Verification And Documentation

**Files:**

- Update: `NIGHT_WATCHER_LONGRUN_PLAN_2026-04-22.md`
- Update: `.omc/ralph/night-watcher-v2/prd.json` if scope changes during implementation.

- [ ] **Step 1: Run focused tests**

Run: `npx tsx --test tests/nightWatcherDecision.test.ts tests/nightWatcherStatusReaders.test.ts`

Expected: PASS.

- [ ] **Step 2: Run full verification**

Run: `npm run build`

Expected: PASS.

Run: `npm test`

Expected: PASS.

- [ ] **Step 3: Update watcher plan**

Update `NIGHT_WATCHER_LONGRUN_PLAN_2026-04-22.md` with the new stage orchestrator rules:

- active stage dedupe;
- promotion validation;
- resume-only-if-safe;
- checkpoint stop after 20-50 downstream matrix.

- [ ] **Step 4: Commit**

This workspace is currently not a git repo, so no commit can be made here. If the workspace is later restored as a git repo, commit with:

```bash
git add src/orchestrator/nightWatcher tests src/cli.ts package.json NIGHT_WATCHER_LONGRUN_PLAN_2026-04-22.md
git commit -m "feat: add night watcher v2 orchestrator"
```

## Task 7: Harden Assets Result Log Writes

**Files:**

- Modify: `src/archive/runAssetDownloadBatch.ts`
- Add or update focused tests near the archive batch tests.
- Update: `NIGHT_WATCHER_MAINTENANCE_MANUAL_2026-04-22.md`

- [ ] **Step 1: Add append retry helper**

Wrap result log append with bounded retry for transient `EBUSY` / `EPERM`.

Expected behavior:

- retry short file-lock windows;
- preserve JSONL line format;
- preserve append ordering through the existing `resultLogQueue`;
- rethrow non-file-lock errors immediately.

- [ ] **Step 2: Add focused regression test**

Simulate append failing once with `EBUSY` or `EPERM`, then succeeding.

Expected: batch continues and writes exactly one JSONL record.

- [ ] **Step 3: Verify**

Run focused tests and `npm run build`.

- [ ] **Step 4: Recovery runbook**

Document that when assets dies from result log `EBUSY` / `EPERM`, the watcher reports `RED / need_human=true`; after explicit human confirmation, resume with the canonical `download-archive-assets-batch --resume` command.

## Self-Review

- Spec coverage: covers active asset monitoring, stage promotion, no duplicate launch, final pack validation, downstream checkpoint stop.
- Placeholder scan: no TBD/TODO placeholders remain in implementation instructions.
- Type consistency: stage names match the design and PRD.
