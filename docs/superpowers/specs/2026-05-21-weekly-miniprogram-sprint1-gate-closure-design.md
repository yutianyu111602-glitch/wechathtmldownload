# Weekly Miniprogram Sprint 1 Gate Closure Design

Updated: 2026-05-21
Status: approved-design, implementation-plan pending
Scope: HUAIDJ weekly mini-program Phase II Sprint 1 only

## Source Of Truth

The execution SSOT is:

- `docs/weekly-miniprogram-handoff-20260519/PLAN_WEEKLY_MINIPROGRAM_UNIFIED.md`

Current-state evidence must be verified before execution from:

- `docs/weekly-miniprogram-handoff-20260519/HANDOFF_CHECKPOINT_20260519.md`
- `apps/weekly_activity_miniprogram/OPENCLAW_AUTOMATION.md` top current section
- `docs/current-runtime.md`
- `C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1`
- Public CloudRun weekly API smoke endpoints

Historical counts such as 28, 51, 74, 103, and 107 are not current runtime truth unless a current-state file or live probe promotes them again.

## Goal

Close Phase II Sprint 1 as a bounded, verifiable gate loop: the current `feature/weekly-integrated-bridge` branch is protected, current weekly package truth is re-verified, release gates pass, Golden baseline has at least 20 verified rows, and maintained checkpoint docs reflect the result.

## Recommended Approach

Use the "gate first, patch only on failure" approach.

1. Run all Sprint 1 gates before changing business code.
2. If a gate fails, patch only the minimal file directly responsible for that Sprint 1 failure.
3. Re-run the failed gate and its nearest dependent gate.
4. Do not expand into Sprint 2 dedupe spec, Sprint 3 Club Profile, Sprint 4 Atlas rollout, deployment, upload, or review submission.

## Boundaries

In scope:

- Preserve the dirty worktree with a non-destructive backup.
- Verify current branch, current package count, and current CloudRun truth.
- Run release guardian, strict duplicate/conflict audit, lineup audit, weekly Golden/bridge Python tests, and mini-program Node tests.
- Confirm `tools/stage7_rewrite/golden/golden_set_v1.jsonl` still has 88 rows.
- Promote at least 20 Golden rows from pending to verified using existing evidence fields only.
- Re-run `evaluate_weekly_golden_baseline.py`.
- Update `P0_BASELINE_REPORT` and `HANDOFF_CHECKPOINT_20260519.md` with absolute-date Sprint 1 results.
- Write a compact Sprint 1 evidence report if existing maintained docs need a single evidence anchor.

Out of scope:

- CloudRun deploy.
- Mini-program upload.
- WeChat review submission.
- Neo4j or Qdrant production writes.
- Atlas production graph acceptance.
- New LLM, OCR, Dajiala, or paid extraction runs.
- Sprint 2 `weekly_dedup_spec.v1.json` implementation.
- Sprint 3 Club Profile implementation.
- Sprint 4 upload preparation beyond read-only verification.

## Architecture And Flow

Sprint 1 is a verification-and-evidence layer over the existing weekly pipeline. It does not introduce a new runtime component.

The flow is:

```text
Git backup
  -> current-state readback
  -> live weekly API smoke
  -> guardian / strict audit / lineup audit
  -> Python and Node tests
  -> Golden verification and baseline
  -> checkpoint and evidence docs
```

The release package remains authoritative for publishability. The mini-program frontend should only be tested against the current package; it should not broaden release truth or merge records more aggressively than the Python L2 repair/audit layer.

## Components

### Git Safety

Use the existing workspace automation under `C:\code\scripts`:

- `git-workspace-backup.ps1` before file edits.
- No reset, clean, branch deletion, force push, or default-branch merge.
- Continue on `feature/weekly-integrated-bridge` because Sprint 1 explicitly verifies that branch.

### Current Truth Verification

Treat `OPENCLAW_AUTOMATION.md` top section and live API probes as current runtime truth. The previously observed live state on 2026-05-21 was `weekly-api-039`, 158 items, dev version `2026.05.21.1`, and no review submission. Execution must verify this again before updating docs.

### Gate Commands

Run these gate classes:

- Release guardian with the current release directory when known.
- `audit_weekly_cross_source_conflicts.py --strict --fail-on-raw-duplicates`.
- `audit_weekly_lineup_address_time.py --strict`.
- Weekly Golden and Atlas bridge unit tests.
- Mini-program Node tests.
- Optional public API smoke for current/manifest/healthz when network is reachable.

### Golden Baseline

Golden work is limited to the existing seed file. A row can be marked verified only when its expected outcome is supported by source fields already present in the Golden row or adjacent maintained baseline artifacts. If 20 safe verified rows cannot be established, stop with a partial result and document the blocker instead of inventing labels.

### Documentation

Update only maintained current-state surfaces:

- `docs/weekly-miniprogram-handoff-20260519/HANDOFF_CHECKPOINT_20260519.md`
- `docs/weekly-miniprogram-handoff-20260519/P0_BASELINE_REPORT_20260519.md` or a dated successor if the existing file format expects dated evidence
- A compact Sprint 1 closeout report if needed for gate output paths

Do not edit archived `PLAN_*` files except if a maintained index explicitly requires a pointer update.

## Error Handling

If a gate fails:

- Capture the exact command and failing assertion.
- Classify it as release data, Python bridge, mini-program frontend, Golden data, or docs drift.
- Patch only the smallest relevant file.
- Re-run the failing command and one adjacent confidence command.

If live network probes fail while local artifacts pass:

- Do not call the Sprint complete.
- Record local-pass and remote-unverified separately.

If Golden verification cannot safely reach 20 rows:

- Leave the count honest.
- Update the checkpoint with the verified count and blocker.
- Do not synthesize labels.

## Testing Strategy

Sprint 1 is complete only when these are true or explicitly documented as blocked:

- Guardian returns `ok=true` and `backendRawHits=0`.
- Strict duplicate/conflict audit returns duplicate/conflict counts of 0.
- Lineup audit returns `hard_fail_count=0`.
- Python weekly Golden/bridge tests pass.
- Mini-program Node tests pass.
- Golden baseline report is regenerated with at least 20 verified rows.
- Checkpoint docs separate local code state, backend package state, CloudRun remote-effective state, mini-program uploaded state, and WeChat review state.

## Approval State

User approved this Sprint 1 scope and selected the recommended "gate first, patch only on failure" design on 2026-05-21.

Implementation must still be driven from a separate detailed plan before code or docs beyond this spec are changed.
