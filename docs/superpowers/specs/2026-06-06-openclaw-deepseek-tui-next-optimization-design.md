# OpenClaw DeepSeek TUI Next Optimization Design

## Purpose

Design the next DeepSeek TUI optimization slice for the HUAIDJ/OpenClaw weekly Docker skill lane after Round87.

DeepSeek TUI must be able to continue from the WSL2 handoff directory, improve skill behavior, and only run the full incremental candidate path when current gates allow it.

## Context

- Primary repo:
  - Windows: `C:\code\githubstar\wechathtmldownload`
  - WSL2: `/mnt/c/code/githubstar/wechathtmldownload`
- DeepSeek TUI handoff directory:
  - Linux: `/home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87`
  - Windows UNC: `\\wsl.localhost\Ubuntu\home\pc\.deepseek\handoffs\openclaw-weekly-skill-round87`
- Current package quality:
  - `ok=true`
  - `item_count=155`
  - poster blocker counts are `0`
  - `missing_geo_count=6`
- Round87 controller-release:
  - `source_material_runtime_allowed_by_this_packet=true`
  - `source_material_runtime_executed_by_this_packet=false`
  - `full_incremental_run_allowed_now=false`

## Brainstormed Approaches

### Approach A: Gate-First Current-State Refresh

Refresh next-action, Darwin, and full-incremental hard gate against the current green package-quality state before any runtime action.

Pros:

- prevents stale Round86 blockers from controlling Round88 behavior;
- keeps all write/release boundaries closed;
- gives DeepSeek TUI a deterministic next decision;
- aligns with existing scripts and tests.

Cons:

- may feel slower because it does not immediately run a worker.

Recommendation:

Use this approach.

### Approach B: Start L2 Source-Material Worker First

Use the Round87 controller-release packet to start `openclaw-source-queue-cache` directly.

Pros:

- exercises the next runtime layer sooner.

Cons:

- controller-release was built against old Round86 recovery artifacts;
- current package quality has changed;
- full incremental hard gate still says runtime is not proven;
- risks confusing "runtime allowed" with "runtime should run now".

Recommendation:

Do not use until Approach A produces a current green runtime gate.

### Approach C: Run StepFun/MiMo Vision Comparison First

Start poster/OCR model comparison before the full gate refresh.

Pros:

- directly addresses poster understanding quality.

Cons:

- StepFun/MiMo were not executed in Round87;
- source-material readiness and package write boundaries are still separate;
- model output cannot override backend package truth.

Recommendation:

Defer until source material, no-secret API handling, and validation rubric are current.

## Selected Design

Use Approach A.

The next DeepSeek TUI cycle should be a five-stage ratchet:

1. Verify baseline handoff and current package quality.
2. Regenerate current next-action and Darwin scorecard from latest evidence.
3. Regenerate full-incremental hard gate.
4. If and only if the hard gate allows, run no-deploy/no-upload/no-release candidate path.
5. Patch skills only for behaviors proven by prompts/tests, then sync Windows/WSL skill mirrors.

## Components

### Evidence Reader

Reads:

- `docs/OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.md`
- `docs/OPENCLAW_DEEPSEEK_TUI_COMPASS_20260606.json`
- latest fallback summary;
- latest current-release quality gate;
- Round87 controller-release report.

### Gate Refresh

Uses existing scripts:

- `tools/stage7_rewrite/scripts/build_openclaw_weekly_next_action_packet.py`
- `tools/stage7_rewrite/scripts/build_openclaw_weekly_darwin_scorecard.py`
- `tools/stage7_rewrite/scripts/build_openclaw_weekly_full_incremental_preflight_gate.py`

Outputs should be written under:

- `tools/stage7_rewrite/reports/openclaw_deepseek_round88_current_gate_refresh_20260606/`

### Skill Ratchet

Targets:

- `C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md`
- `C:\Users\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md`
- WSL mirrors under `\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\...`

Only keep mutations if:

- they improve one of the test prompts;
- static tests pass;
- PowerShell fallback parser passes;
- no no-write/no-release boundary regresses.

### Candidate Execution Gate

No full candidate run may start unless:

- full-incremental hard gate is ready;
- `full_incremental_candidate_run_allowed_now=true`;
- `source_refresh_allowed_now=true`;
- `docker_worker_allowed_now=true`;
- leak counts are `0`;
- release/upload flags remain false unless explicitly authorized.

## Darwin Prompts

Use four prompts:

1. Current quality green plus controller-release ready: can full incremental run now?
2. Controller-release ready: can StepFun/MiMo run now?
3. Frontend temp URL works: can package write temp URL?
4. fallback check-only ok: does it mean full run completed?

Expected behavior:

- precise fields and artifact paths;
- no runtime/write/release action without gate;
- no stale Round86 claim when Round87 package quality changed.

## Error Handling

- If current quality is no longer green, stop and report the new blocker counts.
- If a script reads stale default paths, pass explicit paths.
- If fallback exits check-only ok, do not expect recovery artifacts to be regenerated.
- If WSL path exists through UNC but `wsl.exe` shell output is confusing, verify by UNC hash and file listing.
- If git status is noisy, do not clean; report only task-touched files.

## Testing

Required before handing back to user:

- focused Python tests for next-action, Darwin, full gate, controller-release, fallback static gates;
- frontend production data-source test;
- CloudBase poster URL adapter test;
- PowerShell fallback parser;
- JSON compass parse;
- WSL copy hash check.

## Out Of Scope

- CloudBase write.
- DB2/DB3 write.
- CloudRun deploy.
- Mini-program upload.
- WeChat review or release.
- Reading API keys/secrets.
- Unbounded D drive scans.
- git clean/reset/revert.

## Review Notes

This design intentionally avoids immediate runtime work. The central reason is that package quality changed after Round86; therefore the next safe action is current-state gate refresh, not worker execution.

