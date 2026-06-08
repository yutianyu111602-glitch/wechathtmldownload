<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# GA Monitor Spec — Super Long Run v1

**Date:** 2026-04-27
**Role:** GA Agent (Read-Only Monitor)
**Frequency:** Every 10 minutes during active run

---

## 1. Allowed GA Actions

### Read-Only Checks (9 items)
| # | Check | Method | RED Condition |
|---|-------|--------|---------------|
| 1 | Checkpoint age | stat progress.json | > 30 min since last update |
| 2 | Run log growth | stat run.log | No growth in 20 min |
| 3 | D drive I/O | Get-Volume D, Get-Process | I/O busy > 80% sustained 5 min |
| 4 | Suspicious processes | Get-Process | find/rg/grep scanning D:\ |
| 5 | final_pack | Get-Process final_pack* | Process found |
| 6 | OpenClaw/AG/Hermes | Get-Process | Process found |
| 7 | OCR env | $env:WECHAT_OCR_COMMAND | Not = tools/ocr-image-paddle.ps1 |
| 8 | Disk free space | Get-Volume D | < 50 GB |
| 9 | Error count | wc -l errors.jsonl | Growth > 100 in 10 min |

### GA Output
```
C:\Users\pc\.openclaw\reports\GA_MONITOR_SUMMARY_YYYYMMDD_HHMM.md
```

Template:
```markdown
# GA Monitor Summary — 2026-04-27 18:00

## State: GREEN | AMBER | RED

### Checklist
- [ ] Checkpoint age: <X> min (OK|WARN)
- [ ] Run log growth: <Y> lines (OK|WARN)
- [ ] D drive I/O: <Z>% (OK|WARN)
- [ ] Suspicious processes: <N> (OK|WARN)
- [ ] final_pack: (not found|FOUND)
- [ ] OpenClaw/AG/Hermes: (not found|FOUND)
- [ ] OCR env: (PaddleOCR|WRONG)
- [ ] Disk free: <X> GB (OK|LOW)
- [ ] Error count: <N> (OK|SPIKE)

### Alerts
(None | List of alerts)

### Recommendation
(Continue | Human review needed | STOP)
```

## 2. Forbidden GA Actions

| Action | Ban |
|--------|-----|
| Kill process | FORBIDDEN |
| Start task | FORBIDDEN |
| Modify config | FORBIDDEN |
| Delete file | FORBIDDEN |
| Clean lock | FORBIDDEN |
| Scan D large dirs | FORBIDDEN |
| Auto-fix anything | FORBIDDEN |
| Auto-switch model | FORBIDDEN |
| Call OpenClaw/AG/Hermes | FORBIDDEN |
| Write to production DB | FORBIDDEN |
| Modify any data file | FORBIDDEN |

## 3. RED Protocol

When GA detects RED:
1. Write GA_MONITOR_SUMMARY with state=RED
2. Log exact evidence (which check, what value)
3. Do NOT attempt fix
4. Notify human (or wait for next OpenCode session)
5. Do NOT auto-escalate to any agent

## 4. Summary Format Rules
- One file per summary (timestamp in filename)
- Old summaries retained (append-only)
- No overwriting
- No aggregating into a single file
