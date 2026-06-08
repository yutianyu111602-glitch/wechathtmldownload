<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Checkpoint Template

**Label:** [checkpoint-label]
**Time:** [ISO timestamp]
**State:** GREEN / AMBER / RED

## Metrics

| Metric | Value |
|--------|-------|
| Manifest lines | [count] |
| Success count | [count] |
| Failed count | [count] |
| Throughput/hr | [number] |
| Last processed URL | [url] |

## Context

- Current story: [US-XXX]
- Current phase: [Phase X]
- Run state: [initialized/running/paused/red]

## Evidence

- Manifest path: [path]
- Report path: [path]
- Previous checkpoint: [path]

## Recovery

```bash
bash scripts/start-hermes-7day.sh resume --checkpoint [label]
```

## Notes

[Any additional context for the next agent]
