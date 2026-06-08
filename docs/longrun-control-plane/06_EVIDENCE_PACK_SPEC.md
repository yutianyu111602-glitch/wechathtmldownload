<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Evidence Pack Specification

**Created:** 2026-04-27
**Status:** SKELETON

## Required Evidence Per Task

Every long-run task must produce a complete evidence pack. No task is "done" without this.

### Mandatory Artifacts

| Artifact | Format | Description |
|----------|--------|-------------|
| checkpoint | JSON | Current story, progress, failures, timestamp |
| run log | Markdown | Timestamped event log, decisions, anomalies |
| final report | Markdown | Summary, results, metrics, next steps |
| config diff | Diff/text | What config changed during this run |
| model/profile snapshot | YAML/JSON | Which profile was active, params |
| command transcript | Text | Exact commands executed (copy-pasteable) |
| failure reason | Text | If failed: root cause, attempts, decision |
| Need Human assessment | Text | Clear YES/NO with reasoning |

### Optional Artifacts

| Artifact | When Required |
|----------|---------------|
| RED analysis | RED events only |
| scorecard | Every 3 stories |
| GA monitor summary | Every monitor cycle |
| handoff | On pause/stop/complete |

## Checkpoint Format

```json
{
  "timestamp": "ISO8601",
  "phase": "string",
  "story_id": "US-XXX",
  "status": "running|paused|completed|failed",
  "progress": { "total": 0, "completed": 0, "failed": 0 },
  "failure_budget_remaining": 3,
  "last_error": "string|null",
  "model_profile": "string",
  "disk_free_gb": 0,
  "gpu_vram_free_mb": 0
}
```

## Run Log Format

```
YYYY-MM-DD HH:mm:ss [LEVEL] message
Levels: INFO, WARN, ERROR, DECISION, CHECKPOINT, HANDOFF
```

## File Naming Convention

```
{artifacts_dir}/
  checkpoint_{story_id}_{timestamp}.json
  run_log_{date}.md
  final_report_{date}.md
  config_diff_{date}.diff
  model_snapshot_{date}.json
  command_transcript_{date}.txt
  failure_{story_id}_{date}.md
  red_analysis_{date}.md
  handoff_{date}.md
```
