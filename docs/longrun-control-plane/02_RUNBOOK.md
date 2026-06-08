<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Control Plane Runbook

**Created:** 2026-04-27
**Status:** SKELETON

## 1. Daily Startup

```
1. Check D: disk space: (Get-Volume D).SizeRemaining / 1GB
2. Check GPU: nvidia-smi --query-gpu=memory.free --format=csv,noheader
3. Check model service: curl -s http://127.0.0.1:11434/v1/models
4. Check no stale locks: Test-Path D:\DDownload\.wechat-live-stage-lock.json
5. Review last handoff: docs/longrun-control-plane/reports/latest-handoff.md
```

## 2. Status Check

```
Current phase:  from manifest.md run_state.current_phase
Current story:  from manifest.md run_state.current_story_id
Last heartbeat: from manifest.md run_state.last_heartbeat_at
```

## 3. GREEN / AMBER / RED

### GREEN — Continue
- All monitors pass
- Disk > 100GB, GPU OK, model responding
- No suspicious processes
- Checkpoint writing normally

### AMBER — Log + Watch
- GPU VRAM < 2GB free (but not OOM)
- One monitor intermittent failure
- Log rate dropped but no errors
- Model response > 30s but < 90s
- AMBER for > 30min → escalate to Pro

### RED — Stop + Escalate
- GPU OOM
- Model unreachable (3 retries)
- Disk < 50GB
- Process idle > 60min
- checkpoint stops writing
- RED → deepseek-v4-pro analysis → Need Human decision

## 4. Escalation Flow

```
RED detected by flash (watch)
  →
deepseek-v4-pro analyzes root cause (read-only)
  →
Pro writes RED_ANALYSIS.md with:
  - what happened
  - probable cause
  - recommended actions
  - Need Human: YES/NO
  →
Human reviews and decides
```

## 5. Pause

```
1. Note current progress in run log
2. Write checkpoint if available
3. Stop foreground process (Ctrl+C)
4. Update manifest: status=paused, stop_reason=manual
5. Write handoff
```

## 6. Resume

```
1. Read last handoff
2. Verify environment (Step 1 above)
3. Resume from checkpoint (NOT from scratch)
4. Update manifest: status=running
```

## 7. Handoff

Follow `07_HANDOFF_SPEC.md`. Minimum: current goal, completed, blocked, next step, forbidden actions.

## 8. Scan Guard

```
FORBIDDEN:
  find /mnt/d/DDownload
  find /mnt/d/aidata
  Get-ChildItem -Recurse D:\DDownload
  Get-ChildItem -Recurse D:\aidata
  rg D:\DDownload
  rg D:\aidata

ALLOWED:
  Get-ChildItem D:\DDownload\_llm_release_v2 (non-recursive)
  Get-ChildItem D:\models (non-recursive)
  Read specific known files by exact path
```
