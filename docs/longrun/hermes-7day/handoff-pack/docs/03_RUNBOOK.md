<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Hermes WSL2 7-Day Runbook / 运维手册

**Version:** v1.0
**Date:** 2026-04-28
**Mode:** Unattended-but-guarded
**Executor:** Hermes Agent (WSL2) + deepseek-v4-pro

---

## 1. Pre-Run Checklist

- [ ] WSL2 running: `wsl --status`
- [ ] Hermes installed: `hermes --version`
- [ ] deepseek-v4-pro API key configured: `hermes model` shows deepseek
- [ ] Qwen3.6-27B loaded: `curl http://127.0.0.1:11434/api/tags`
- [ ] mem0 running: `curl http://127.0.0.1:11434/v1/memories`
- [ ] D drive free > 100GB
- [ ] WeChat PC app running and logged in
- [ ] WeChat window title contains "公众号"
- [ ] No `find /mnt/d/` or recursive scan processes
- [ ] OpenClaw / AG not running as controller
- [ ] Output directory created: `D:\HTML\hermes-longrun-2026-04-28`

---

## 2. Hermes Configuration

### 2.1 Model Setup

```bash
# In WSL2
hermes model
# Select: deepseek-v4-pro (for planning/decision)
# Fallback: local Qwen3.6-27B via llama-swap:11434

# Verify
hermes config get model
```

### 2.2 Hermes Config File (`config/hermes.config.yaml`)

```yaml
model:
  provider: deepseek
  model: deepseek-v4-pro
  api_key: "${DEEPSEEK_API_KEY}"
  base_url: "https://api.deepseek.com/v1"

tools:
  enabled:
    - file_operations
    - code_execution
    - web_tools
    - memory_tool
    - delegate_tool
    - todo_tool
    - session_search
  disabled:
    - browser_tool
    - voice_mode
    - tts_tool
    - image_generation

memory:
  provider: mem0
  endpoint: "http://127.0.0.1:11434/v1"
  agent_id: "hermes_wechat_pipeline"

cron:
  enabled: true
  jobs:
    - name: "wechat_capture_check"
      schedule: "*/30 * * * *"
      command: "bash scripts/start-hermes-7day.sh monitor"

batch:
  output_dir: "/mnt/d/HTML/hermes-longrun-2026-04-28"
  checkpoint_interval: 50
  checkpoint_time_min: 30
  max_items_per_run: 100
  resume: true
```

### 2.3 Environment Variables

```bash
# WSL2 ~/.bashrc or session
export DEEPSEEK_API_KEY="your-key-here"
export HERMES_OUTPUT_DIR="/mnt/d/HTML/hermes-longrun-2026-04-28"
export HERMES_CHECKPOINT_DIR="/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/state"
export HERMES_REPORTS_DIR="/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports"
```

---

## 3. WeChat Capture Operations

### 3.1 Basic Capture Command

```bash
# In WSL2, call Windows Python
cd /mnt/c/code/Hermes
python tools/windows_wechat_history.py \
  --output-dir /mnt/d/HTML/hermes-longrun-2026-04-28 \
  --html-fallback \
  --page-idle-limit 2 \
  --item-retry-limit 1 \
  --resume \
  --max-items 50
```

### 3.2 Capture Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `output_dir` | D:\HTML | Where PDFs + manifest go |
| `html_fallback` | True | Try HTML if PDF fails |
| `page_idle_limit` | 2 | Pages to scroll before idle |
| `item_retry_limit` | 1 | Retry per failed item |
| `resume` | True | Skip already captured |
| `max_items` | 50 | Max items per run |

### 3.3 Capture Output Structure

```
D:\HTML\hermes-longrun-2026-04-28\
├── [hash].pdf              # Captured PDF
├── [hash].url.txt          # Source URL
├── [hash].md               # Fallback HTML
└── .hermes_wechat_history\
    ├── manifest.jsonl       # Capture manifest
    └── runs\                # Per-run logs
```

### 3.4 Capture Status Check

```bash
# Count captured items
wc -l /mnt/d/HTML/hermes-longrun-2026-04-28/.hermes_wechat_history/manifest.jsonl

# Check latest entries
tail -5 /mnt/d/HTML/hermes-longrun-2026-04-28/.hermes_wechat_history/manifest.jsonl

# Count by status
grep -o '"status": "[^"]*"' manifest.jsonl | sort | uniq -c
```

---

## 4. Loopy-Archiver Integration

### 4.1 Trigger New Captures

```bash
# In WSL2
cd /mnt/c/code/loopy-archiver

# Process new PDFs
python pipeline_keeper.py --mode batch_archive \
  --input-dir /mnt/d/HTML/hermes-longrun-2026-04-28 \
  --output-dir /mnt/d/HTML/.loopy_archiver

# Entity extraction
python extract_entities.py --input /mnt/d/HTML/.loopy_archiver/archiver.db

# Relationship extraction
python extract_relationships.py --input /mnt/d/HTML/.loopy_archiver/archiver.db

# Graph build
python graph_builder.py --input /mnt/d/HTML/.loopy_archiver/archiver.db
```

### 4.2 Loopy Status Check

```bash
# Check DB
sqlite3 /mnt/d/HTML/.loopy_archiver/archiver.db "SELECT COUNT(*) FROM entities;"
sqlite3 /mnt/d/HTML/.loopy_archiver/archiver.db "SELECT COUNT(*) FROM graph_nodes;"
```

---

## 5. Checkpoint & Resume

### 5.1 Write Checkpoint

```bash
bash scripts/start-hermes-7day.sh checkpoint \
  --label "day3-smoke-500" \
  --state GREEN \
  --note "500 captured, 450 success, 50 failed"
```

### 5.2 Checkpoint Structure (`state/checkpoints/`)

```json
{
  "label": "day3-smoke-500",
  "state": "GREEN",
  "note": "500 captured, 450 success, 50 failed",
  "timestamp": "2026-05-01T14:30:00+08:00",
  "metrics": {
    "total_captured": 500,
    "success_count": 450,
    "failed_count": 50,
    "duplicate_count": 0,
    "throughput_per_hr": 35,
    "last_processed_url": "https://mp.weixin.qq.com/s/..."
  },
  "manifest_path": "/mnt/d/HTML/hermes-longrun-2026-04-28/.hermes_wechat_history/manifest.jsonl",
  "run_state_path": "/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/state/run-state.json"
}
```

### 5.3 Resume from Checkpoint

```bash
bash scripts/start-hermes-7day.sh resume --checkpoint day3-smoke-500
```

---

## 6. mem0 Operations

### 6.1 Save Learning

```bash
curl -X POST http://127.0.0.1:11434/v1/memories \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "assistant", "content": "Day 3: Capture throughput 35/hr, WeChat popup caused 12 failures, workaround: wait 3s between clicks"}],
    "agent_id": "hermes_wechat_pipeline",
    "run_id": "hermes-7day-2026-04-28",
    "metadata": {"day": "3", "type": "learning"}
  }'
```

### 6.2 Retrieve Learnings

```bash
curl -X POST http://127.0.0.1:11434/v1/memories/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "capture failure workaround",
    "filters": {"agent_id": "hermes_wechat_pipeline"},
    "top_k": 5
  }'
```

---

## 7. Monitoring

### 7.1 Manual Monitor Check

```bash
bash scripts/start-hermes-7day.sh monitor
```

Checks:
- Latest checkpoint timestamp
- manifest.jsonl growth
- D drive I/O
- WeChat window status
- Suspicious processes
- Disk free space

### 7.2 Cron-Based Monitoring

```bash
# Every 30 minutes via Hermes cron
hermes cron add --name "wechat_monitor" --schedule "*/30 * * * *" \
  --command "bash scripts/start-hermes-7day.sh monitor"
```

---

## 8. Error Handling

### 8.1 WeChat Window Lost

```
Symptom: WeChat window not found or minimized
Action:
  1. Try: powershell.exe -Command "(Get-Process WeChat).MainWindowTitle"
  2. Try: powershell.exe -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('%{TAB}')"
  3. If still lost: Write RED report, wait for human
```

### 8.2 Capture Stuck

```
Symptom: No new manifest entries for > 30 min
Action:
  1. Check if WeChat process alive
  2. Check if capture process alive
  3. Kill stuck capture process
  4. Resume from last checkpoint
  5. If 3x stuck: RED, write analysis
```

### 8.3 API Timeout

```
Symptom: deepseek-v4-pro API timeout
Action:
  1. Retry 3x with exponential backoff
  2. If still failing: Switch to local Qwen3.6-27B
  3. Write AMBER report
```

### 8.4 WSL2 Shutdown

```
Symptom: WSL2 not responding
Action (Windows side):
  1. wsl --shutdown
  2. wsl
  3. Resume from latest checkpoint
  4. Check state/run-state.json
```

---

## 9. RED / AMBER / GREEN Protocol

| Level | Condition | Action |
|-------|-----------|--------|
| GREEN | Normal operation | Continue, write checkpoint |
| AMBER | Single issue, non-critical | Pause scale-up, monitor closely |
| RED | Critical failure or boundary violation | Stop new tasks, write evidence, wait for human |

### RED Response Procedure

1. Stop starting new tasks
2. Write `RED_ANALYSIS_YYYYMMDD_HHMM.md`
3. Update `state/run-state.json` to `red`
4. Save mem0 memory
5. Do NOT auto-fix
6. Do NOT kill processes (except stuck capture)
7. Do NOT delete any files

---

## 10. Cleanup (Day 7 Only)

### 10.1 Dry-run Cleanup Plan

```bash
# Generate cleanup plan (DO NOT EXECUTE)
cat > reports/cleanup-dry-run-plan.md << 'EOF'
# Cleanup Dry-run Plan

## Items to Clean
1. Temporary capture directories older than X days
2. Duplicate PDF files
3. Failed capture artifacts

## Commands (DRY RUN - review only)
ls -la /mnt/d/HTML/hermes-longrun-2026-04-28/
find /mnt/d/HTML/hermes-longrun-2026-04-28/ -name "*.pdf" -mtime +7

## DO NOT execute without human approval
EOF
```

---

## 11. Log/Report Directory Convention

| Type | Path |
|------|------|
| Run logs | `D:\HTML\hermes-longrun-2026-04-28\.hermes_wechat_history\runs\` |
| Monitor reports | `docs/longrun/hermes-7day/reports/` |
| Handoff reports | `docs/longrun/hermes-7day/reports/` |
| Checkpoints | `docs/longrun/hermes-7day/state/checkpoints/` |
| Capture output | `D:\HTML\hermes-longrun-2026-04-28\` |
| Loopy artifacts | `D:\HTML\.loopy_archiver\` |

---

## 12. Rollback Procedures

```bash
# Restore from checkpoint
bash scripts/start-hermes-7day.sh resume --checkpoint <label>

# Restore run state
cp state/run-state.json.bak state/run-state.json

# Restore manifest (if corrupted)
# Use .hermes_wechat_history/runs/ to rebuild
```

---

**End of Runbook. Next: `docs/04_MONITOR_PROTOCOL.md`**
