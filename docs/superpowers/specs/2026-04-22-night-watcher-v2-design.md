<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Night Watcher v2 Design

Date: 2026-04-22

Workspace: `C:\code\githubstar\wechathtmldownload`

## Source Context

This design was produced from the requested sequence:

1. Ralph / Ouroboros review of the current watcher plan.
2. Superpowers brainstorming to compare upgrade paths.
3. Superpowers writing-plans to create an implementation plan.
4. Ralph PRD conversion to `.omc/ralph/night-watcher-v2/prd.json`.

Documents read:

- `HANDOFF.md`
- `NIGHT_WATCHER_LONGRUN_PLAN_2026-04-22.md`
- `AUTONOMOUS_LONGRUN_QUEUE_HANDOFF_2026-04-22.md`
- `MASTER_HANDOFF_AND_FUTURE_PLAN_2026-04-22.md`
- `FINAL_TODOS_UNDERGROUND_GRAPH_PIPELINE_2026-04-22.md`
- `PIPELINE_NEXT_ACTION_TODOS_2026-04-22.md`
- `.omc/ralph/underground-electronic-music-graph/prd.json`
- `package.json`
- `tools/watchArchiveStatus.mjs`
- `src/orchestrator/pipelineKeeper.ts`
- `tests/pipelineKeeper.test.ts`
- relevant CLI command registration in `src/cli.ts`

Live status was checked read-only. As of the check:

- HTML archive is `completed`: total 93,761; succeeded 66,020; skipped 17,874; deferred 2,624; failed 7,243; queued 0; running 0.
- Final audit exists at `D:\DDownload\_reports\archive-audit-final`.
- Incomplete queue exists with 9,867 rows.
- Dajiala signed repair candidate queue exists with 400 rows.
- Dajiala repair is `completed`: 400 succeeded, 0 failed.
- Repair audit exists at `D:\DDownload\_reports\archive-audit-after-repair`.
- Asset localization is currently running: total 93,761; succeeded 2,266; failed 3; queued 91,491; running 1.
- Export, OCR, final pack, and downstream matrix status files are not present yet.

The current operational next action is not "start assets". Assets are already running. The correct action is to monitor assets and avoid duplicate launch until the asset stage reaches a valid completion state.

## Problem

The existing watcher plan was strongest during the HTML download phase. It correctly prevented killing or restarting `mptext-archive-batch` and defined GREEN/YELLOW/RED signals.

Now the pipeline has moved into post-download stages. The stronger watcher must become a stage orchestrator:

- detect which stage is active from status files and process state;
- never start the same stage twice;
- promote stages only after validation;
- recover only when a stage is safely resumable;
- keep final pack and downstream evaluation isolated;
- stop automatically before the 300-1000 article checkpoint.

## Brainstormed Approaches

### Recommended: Status-file stage orchestrator

Build a small `nightWatcher` orchestrator on top of existing CLI commands and status files. It reads status, process state, and output artifacts, then decides one next action: monitor, start next stage, resume a stalled stage, or stop at checkpoint.

This approach fits the repo because the individual stages already exist and already write status/result logs. It avoids replacing working batch commands.

### Alternative: Expand `pipelineKeeper`

Extend the existing keeper into the live archive pipeline. This reuses job-store patterns, but `pipelineKeeper` currently targets HTML file ingestion and dual-track export, not archive-wide batch stages. It would require a broader refactor before it can safely control assets, export, OCR, final pack, and downstream matrix.

### Alternative: Documentation-only watcher

Keep the watcher as a runbook and rely on manual command execution. This is low-risk but too weak for the requested autonomous stronger watcher because it cannot prevent duplicate launches or enforce checkpoints.

## Recommended Design

Night Watcher v2 is a finite-state supervisor for the production archive pipeline.

It owns orchestration decisions, not stage internals. Stage commands stay in the existing CLI:

```text
html_archive
-> final_audit
-> incomplete_queue
-> dajiala_candidate_filter
-> dajiala_repair
-> repair_audit
-> assets
-> export_llm
-> ocr_poster
-> final_pack
-> downstream_matrix_50
-> checkpoint_stop
```

The watcher keeps durable state in `.omc/state/night-watcher-v2-state.json`:

- current stage
- last decision
- status file summaries
- process matches
- artifact validation results
- command history
- checkpoint state

The watcher supports:

- `--once`: inspect once, print decision, optionally run one start action.
- `--dry-run`: print the command it would run without launching it.
- `--statePath`: write durable state to a custom path.
- `--heartbeat`: write structured status text for human handoff.

## Decision Rules

### Active Stage Rule

If a stage has `runningCount > 0`, `queuedCount > 0`, or a matching process exists, the watcher reports `GREEN` and monitors. It must not launch another copy of that stage.

This applies to the current asset stage.

### Promotion Rule

The watcher promotes from stage N to stage N+1 only when all completion checks for stage N pass.

Examples:

- assets can promote only when `asset-retention-status.json` reports completed, running 0, queued 0, and the results log has parseable rows.
- export can promote only when `export-llm-status.json` reports completed and sample artifacts have `llm_input.md`, `sidecar.json`, `quality_report.json`, and `poster_ocr.json`.
- final pack can promote only when `manifest.json`, `index.jsonl`, and `checksums.sha256` exist and `manifest.copied_articles == index.jsonl` line count.

### Resume Rule

The watcher may resume a stage only if:

- no matching process exists;
- status is not completed;
- the stage command is documented as resume-safe;
- the status or result log is stale beyond the stage threshold;
- the resume command uses the same canonical paths from `HANDOFF.md`.

For live assets, automatic resume is gated by human confirmation after a RED report. A known failure mode is Windows file locking on the result log (`EBUSY` / `EPERM` while appending `asset-retention-results.jsonl`). The watcher should report this clearly, then resume only after confirmation with the same `download-archive-assets-batch --resume` command.

The batch implementation should also be hardened so result-log append uses bounded retry for transient `EBUSY` / `EPERM` without changing JSONL format.

It does not kill live processes.

### Checkpoint Rule

After `downstream_matrix_50` completes, the watcher stops. It does not run the 300-1000 checkpoint, full downstream batch, graph candidate pack, `ignuke`, or `D:\DJ_DATA` registry write without explicit confirmation.

## Status Output

Every heartbeat includes:

- decision: `GREEN | YELLOW | RED | COMPLETED | CHECKPOINT_STOP`
- current stage
- allowed action
- blocked action
- status path
- total / succeeded / failed / skipped / deferred / queued / running
- process matches
- latest result log mtime
- validation summary
- next command if applicable

## Acceptance Criteria

- The current real state is detected as `assets` active, not as "start assets".
- A running asset process prevents duplicate asset launch.
- Missing export/OCR/final pack status files do not cause premature launch while assets are active.
- Completed Dajiala repair remains completed and is not re-run.
- The watcher can print the exact next command after assets completion.
- The watcher stops after 20-50 downstream matrix and reports the 300-1000 checkpoint block.
- `npm run build` and `npm test` pass after implementation.

## Non-Goals

- Do not replace existing batch implementations.
- Do not mutate live archive data during status inspection.
- Do not kill, restart, or cancel running stages.
- Do not write graph candidates or `D:\DJ_DATA` registry during night watcher v2.
- Do not add UI controls in this PRD.

## Spec Self-Review

- Placeholder scan: no unresolved placeholders.
- Consistency check: stage order matches `HANDOFF.md` current route.
- Scope check: implementation is one orchestrator plus tests, not a full pipeline rewrite.
- Ambiguity check: current stage behavior is explicit: assets are running, so monitor and dedupe.
