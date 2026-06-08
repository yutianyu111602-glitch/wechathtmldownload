<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# RED Analysis Request — [timestamp]

**Reason:** [brief description]

## Required Behavior

1. Stop starting new tasks
2. Do NOT kill/delete/restart/fix automatically
3. Preserve all evidence
4. Wait for human intervention

## Last State

```json
[contents of state/run-state.json]
```

## Evidence

| Check | Value | Status |
|-------|-------|--------|
| [check 1] | [value] | RED |
| [check 2] | [value] | [status] |

## Timeline

- `<time>`: `<event>`
- `<time>`: `<event>`
- `<time>`: RED triggered

## Recommended Action

[What human should do to resolve]

## Forbidden Actions

- Do NOT auto-fix
- Do NOT kill processes (except stuck capture)
- Do NOT delete files
- Do NOT change model/provider
