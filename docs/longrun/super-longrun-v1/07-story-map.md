<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Story Map — Super Long Run v1

**Date:** 2026-04-27

---

## Dependency Graph

```
US-000 (Tooling Audit) ─────────────────────────────────────┐
  ↓                                                          │
US-001 (Baseline Freeze) ────────────────────────────────────┤
  ↓                                                          │
US-001B (Context Gate) ──────────────────────────────────────┤
  ↓                                                          │
US-002 (Dry-run 100) ─── US-008 (Rawwechat Verify) ─────────┤
  ↓                         (independent, parallel)           │
US-003 (Smoke 1000) ────── US-009 (Safety Audit) ────────────┤
  ↓                         (independent, parallel)           │
US-004 (Full Batch) ────── US-010 (GA Monitor) ──────────────┤
  ↓                         (independent, parallel)           │
US-005 (Review Report) ─── US-011 (Cleanup Plan) ────────────┤
  ↓                         (independent, parallel)           │
US-006 (Quality Report)                                       │
  ↓                                                           │
US-007 (Graph Candidate)                                      │
  ↓                                                           │
US-012 (Final Handoff) ←─────────────────────────────────────┘
```

## Story Timeline

| Phase | Story | Name | Est. Duration | Human Gate |
|-------|-------|------|---------------|------------|
| 0 | US-000 | Tooling Audit | 5 min | Yes |
| 1 | US-001 | Baseline Freeze | 5 min | Yes |
| 2 | US-001B | Context Gate | 10 min | Yes |
| 3 | US-002 | Dry-run 100 | 2 hr | Yes |
| 4 | US-003 | Smoke 1000 | 20 hr | Yes |
| 5 | US-004 | Full Ready Batch | 70 days | Yes |
| 6 | US-005 | Review Report | 5 min | Yes |
| 7 | US-006 | Quality Report | 10 min | Yes |
| 8 | US-007 | Graph Candidate | 30 min | Yes |
| 9 | US-008 | Rawwechat Verify | 30 min | Yes |
| 10 | US-009 | Safety Audit | 10 min | Yes |
| 11 | US-010 | GA Monitor | Ongoing | No |
| 12 | US-011 | Cleanup Plan | 10 min | Yes |
| 13 | US-012 | Final Handoff | 30 min | Yes |

Parallel execution possible for: US-008, US-009, US-010, US-011 (with US-002 through US-004).

## Priority Ranking (Execution Order)

1. US-000 — Must pass before anything
2. US-001 — Must pass before US-001B
3. US-001B — Must pass before US-002
4. US-002 — Must pass before US-003
5. US-003 — Must pass before US-004
6. US-004 — Must pass before US-005/006/007
7. US-005 — Must pass before US-007
8. US-006 — Must pass before US-007
9. US-007 — Must pass before US-012
10. US-008 — Independent, parallel
11. US-009 — Independent, parallel
12. US-010 — Independent, ongoing
13. US-011 — Independent, parallel
14. US-012 — Final, after all others
