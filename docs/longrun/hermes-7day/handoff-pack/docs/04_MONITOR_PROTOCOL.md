<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Hermes Monitor Protocol — Read-Only

**Version:** v1.0
**Date:** 2026-04-28
**Mode:** Read-only observation, no auto-fix

---

## 1. Core Principle

Hermes Monitor is a **read-only observer**. It checks system state and writes GREEN/AMBER/RED summaries. It does NOT:
- Kill processes
- Start tasks
- Delete files
- Fix errors
- Change configuration

---

## 2. Monitor Check Items

### 2.1 Checkpoint Health

```bash
# WSL2
LATEST_CHECKPOINT=$(ls -t state/checkpoints/*.json 2>/dev/null | head -1)
if [ -n "$LATEST_CHECKPOINT" ]; then
  CHECKPOINT_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_CHECKPOINT")) / 60 ))
  echo "Latest checkpoint: $LATEST_CHECKPOINT (${CHECKPOINT_AGE} min ago)"
else
  echo "No checkpoints found"
fi
```

| Age | Status |
|-----|--------|
| < 30 min | GREEN |
| 30-60 min | AMBER |
| > 60 min | RED |

### 2.2 Manifest Growth

```bash
MANIFEST="/mnt/d/HTML/hermes-longrun-2026-04-28/.hermes_wechat_history/manifest.jsonl"
if [ -f "$MANIFEST" ]; then
  LINES=$(wc -l < "$MANIFEST")
  MOD_TIME=$(stat -c %Y "$MANIFEST")
  echo "Manifest: $LINES lines, last modified $(date -d @$MOD_TIME)"
fi
```

### 2.3 D Drive I/O

```bash
# From WSL2, check Windows disk
powershell.exe -Command "Get-Counter '\PhysicalDisk(*)\% Disk Time' -SampleInterval 2 -MaxSamples 3 | Select-Object -ExpandProperty CounterSamples | Format-Table"
```

| Disk Time | Status |
|-----------|--------|
| < 60% | GREEN |
| 60-80% | AMBER |
| > 80% | RED |

### 2.4 Disk Free Space

```bash
# From WSL2
df -h /mnt/d | tail -1 | awk '{print $4}'
```

| Free | Status |
|------|--------|
| > 100GB | GREEN |
| 50-100GB | AMBER |
| < 50GB | RED |

### 2.5 WeChat Window Status

```bash
# From WSL2, check Windows process
powershell.exe -Command "Get-Process WeChat -ErrorAction SilentlyContinue | Select-Object Id, MainWindowTitle, Responding"
```

| Status | Condition |
|--------|-----------|
| GREEN | Process exists, Responding=True |
| AMBER | Process exists, MainWindowTitle empty |
| RED | Process not found |

### 2.6 Suspicious Processes

```bash
# Check for dangerous scans
powershell.exe -Command "Get-Process | Where-Object { \$_.ProcessName -match 'find|scandisk|final_pack|openclaw|genericagent' } | Select-Object ProcessName, Id"
```

| Count | Status |
|-------|--------|
| 0 | GREEN |
| > 0 | RED |

### 2.7 Model Health

```bash
# Qwen3.6-27B
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import sys,json; d=json.load(sys.stdin); print([m['name'] for m in d.get('models',[])])"

# deepseek-v4-pro
curl -s https://api.deepseek.com/v1/models -H "Authorization: Bearer $DEEPSEEK_API_KEY"
```

### 2.8 mem0 Health

```bash
curl -s http://127.0.0.1:11434/v1/memories -H "Content-Type: application/json" \
  -d '{"query": "test", "top_k": 1}'
```

---

## 3. Monitor Schedule

| Frequency | When | Checks |
|-----------|------|--------|
| Every 10 min | Active capture running | All 8 checks |
| Every 30 min | Idle/between runs | Checkpoint, disk, WeChat |
| Every 2 hours | Overnight | Checkpoint, disk |
| Daily | Day start | Full check + report |

---

## 4. Monitor Output Format

```markdown
# Hermes Monitor Summary — [timestamp] +08

## Status: GREEN / AMBER / RED

| Check | Value | Status |
|-------|-------|--------|
| Checkpoint age | X min | ✅/⚠️/❌ |
| Manifest lines | X | ✅/⚠️/❌ |
| D Disk I/O | X% | ✅/⚠️/❌ |
| D Free space | X GB | ✅/⚠️/❌ |
| WeChat window | [status] | ✅/⚠️/❌ |
| Suspicious procs | [count] | ✅/⚠️/❌ |
| Qwen3.6 model | [status] | ✅/⚠️/❌ |
| deepseek API | [status] | ✅/⚠️/❌ |
| mem0 | [status] | ✅/⚠️/❌ |

## Notes
- [anomaly description]
- [recommended action]
```

---

## 5. RED Protocol

When ANY check returns RED:

1. **Stop** starting new tasks
2. **Write** `reports/RED_ANALYSIS_YYYYMMDD_HHMM.md`
3. **Update** `state/run-state.json` to `red`
4. **Save** mem0 memory
5. **Do NOT**:
   - Auto-fix
   - Kill processes (except stuck capture)
   - Delete files
   - Change model/provider
   - Start OpenClaw/AG

---

## 6. Monitor Script Location

`scripts/monitor-hermes-7day.sh` — Called by cron or manually

---

**End of Monitor Protocol. Next: `docs/05_SAFETY_POLICY.md`**
