<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Handoff Template — Hermes 7-Day Longrun

**Time:** [ISO timestamp]
**Workspace:** C:\code\githubstar\wechathtmldownload
**Status:** [completed/paused/red]

## One-Line Summary

[One sentence describing current state]

## Entry Points

1. This file
2. `manifest.md` — SSOT
3. `state/run-state.json` — Current run state
4. Latest checkpoint: `state/checkpoints/[latest].json`

## Completed Stories

| Story | Status | Evidence |
|-------|--------|----------|
| US-000 | [PASS/FAIL] | [path] |
| US-001 | [PASS/FAIL] | [path] |

## Current Facts

### Confirmed
- [fact 1]
- [fact 2]

### Unverified
- [fact 1]

### Blocked
- [blocker 1]

## Module Status

| Module | Status | Notes |
|--------|--------|-------|
| WeChat Capture | [status] | [notes] |
| Loopy-Archiver | [status] | [notes] |
| Qwen3.6 Extract | [status] | [notes] |
| mem0 | [status] | [notes] |

## Files & Artifacts

| Path | Status | Purpose |
|------|--------|---------|
| [path] | [status] | [purpose] |

## Forbidden Actions

- [forbidden 1]
- [forbidden 2]

## Allowed Actions

- [allowed 1]
- [allowed 2]

## Verification Results

- Passed: [list]
- Failed: [list]
- Not run: [list]

## Next Steps

### Immediate
1. [step 1]
2. [step 2]

### Short-term (1-3 days)
1. [step 1]

### Medium-term (1-2 weeks)
1. [step 1]

## Resume Commands

```bash
wsl
cd ~/wechathtmldownload/docs/longrun/hermes-7day/handoff-pack
bash scripts/start-hermes-7day.sh resume --checkpoint [label]
bash scripts/start-hermes-7day.sh monitor
```

## Longrun State

- run_id: hermes-7day-2026-04-28
- current mode: [running/paused/red]
- current phase: [Phase X]
- current story: [US-XXX]
- iteration: [N]
- last heartbeat: [timestamp]
- last verification: [description]
- stop reason: [reason or none]
- next resume cursor: [description]
