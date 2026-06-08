<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Handoff Template — Super Long Run v1

**Use:** When any story completes, hits stop gate, or session ends.
**File:** `docs/longrun/super-longrun-v1/loops/loop-NNN-handoff.md`

---

## Goal
- [Brief 1-sentence goal of current session]

## Constraints & Preferences
- [Key constraints from safety policy]

## Progress
### Done
- [ ] [Story ID] [Description] — [Result]

### In Progress
- [Story ID] [Current step]

### Blocked
- [Blockers with story ID]

## Key Decisions
- [Decision] — [Rationale]

## Next Steps
1. [Next action]
2. [Next action]

## Critical Context
- **Model:** Qwen3.6-27B @ llama-swap:11434
- **Params:** temp=0.1, top_p=0.9, max_tokens=2048, timeout_ms=180000
- **D Drive:** 16T helium HDD, [X] GB free
- **Run State:**
```yaml
mode: [unattended|interactive]
status: [ready|running|blocked|stopped]
current_story: [US-XXX]
failure_count: [N]/3
last_checkpoint: [timestamp]
next_resume_cursor: [US-XXX]
```

## Relevant Files
- [path] — [description]

## HUMAN DECISION REQUIRED
- [ ] [Decision item]
