<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WSL2 Hermes Configuration Guide

**Version:** v1.0
**Date:** 2026-04-28
**Target:** Hermes Agent running in WSL2 Ubuntu

---

## 1. WSL2 Environment Setup

### 1.1 Verify WSL2

```bash
# Windows PowerShell
wsl --status
wsl --list --verbose
# Should show: Ubuntu, State: Running, Version: 2
```

### 1.2 Install Hermes in WSL2

```bash
# In WSL2
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc
hermes --version
```

### 1.3 Path Mapping

| Windows | WSL2 | Usage |
|---------|------|-------|
| `C:\code\Hermes` | `/mnt/c/code/Hermes` | Hermes source code |
| `C:\code\githubstar\wechathtmldownload` | `/mnt/c/code/githubstar/wechathtmldownload` | Pipeline workspace |
| `D:\HTML` | `/mnt/d/HTML` | Capture output |
| `D:\DDownload` | `/mnt/d/DDownload` | Release data (read-only) |
| `D:\models` | `/mnt/d/models` | Local GGUF models |
| `C:\code\loopy-archiver` | `/mnt/c/code/loopy-archiver` | Archive pipeline |
| `C:\code\githubstar\OBSIDIAN` | `/mnt/c/code/githubstar/OBSIDIAN` | Knowledge base |

### 1.4 WSL2 ↔ Windows Interop

```bash
# Run Windows exe from WSL2
powershell.exe -Command "Get-Process WeChat"
cmd.exe /c "dir D:\HTML"

# Convert paths
wslpath -w /mnt/d/HTML    # => D:\HTML
wslpath 'D:\HTML'          # => /mnt/d/HTML
```

---

## 2. Hermes Configuration

### 2.1 Config File: `config/hermes.config.yaml`

```yaml
# Model Configuration
model:
  provider: deepseek
  model: deepseek-v4-pro
  api_key: "${DEEPSEEK_API_KEY}"
  base_url: "https://api.deepseek.com/v1"
  max_tokens: 4096
  temperature: 0.1

# Tool Configuration
tools:
  enabled:
    - file_operations
    - code_execution
    - web_tools
    - memory_tool
    - delegate_tool
    - todo_tool
    - session_search
    - checkpoint_manager
  disabled:
    - browser_tool
    - voice_mode
    - tts_tool
    - image_generation
    - rl_training_tool

# Memory Configuration
memory:
  provider: mem0
  endpoint: "http://127.0.0.1:11434/v1"
  agent_id: "hermes_wechat_pipeline"
  run_id: "hermes-7day-2026-04-28"

# Batch Configuration
batch:
  output_dir: "/mnt/d/HTML/hermes-longrun-2026-04-28"
  checkpoint_interval: 50
  checkpoint_time_min: 30
  max_items_per_run: 100
  resume: true

# Cron Configuration
cron:
  enabled: true
  jobs:
    - name: "wechat_capture_monitor"
      schedule: "*/30 * * * *"
      command: "bash /mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/handoff-pack/scripts/start-hermes-7day.sh monitor"
    - name: "checkpoint_heartbeat"
      schedule: "*/60 * * * *"
      command: "bash /mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/handoff-pack/scripts/start-hermes-7day.sh checkpoint --label auto --state GREEN"

# Safety Configuration
safety:
  forbidden_paths:
    - "/mnt/d/DDownload/_llm_release_v2"
    - "/mnt/d/DDownload/_llm_release"
    - "/mnt/d/aidata"
  max_capture_items: 100
  checkpoint_max_age_min: 60
  disk_free_min_gb: 50
```

### 2.2 Environment Variables

Add to WSL2 `~/.bashrc`:

```bash
# Hermes 7-Day Longrun Environment
export DEEPSEEK_API_KEY="your-key-here"
export HERMES_OUTPUT_DIR="/mnt/d/HTML/hermes-longrun-2026-04-28"
export HERMES_CHECKPOINT_DIR="/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/state"
export HERMES_REPORTS_DIR="/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports"
export HERMES_RUN_ID="hermes-7day-2026-04-28"
export HERMES_AGENT_ID="hermes_wechat_pipeline"

# Local model
export QWEN_ENDPOINT="http://127.0.0.1:11434"
export QWEN_MODEL="Qwen3.6-27B"

# mem0
export MEM0_ENDPOINT="http://127.0.0.1:11434/v1"
export MEM0_MODEL="qwen3.5:4b"
export MEM0_EMBEDDING="bge-m3:latest"
```

---

## 3. Hermes Commands Reference

### 3.1 Basic Commands

```bash
hermes                    # Start interactive CLI
hermes --version          # Check version
hermes doctor             # Diagnose issues
hermes update             # Update to latest
hermes status             # Current status
```

### 3.2 Session Management

```bash
hermes session list       # List sessions
hermes session show <id>  # Show session details
hermes session delete <id> # Delete session
```

### 3.3 Batch Processing

```bash
hermes batch --config config/hermes.config.yaml
hermes batch --input input.jsonl --output output.jsonl
```

### 3.4 Cron Management

```bash
hermes cron list          # List cron jobs
hermes cron add --name "monitor" --schedule "*/30 * * * *" --command "..."
hermes cron remove <name> # Remove cron job
hermes cron start         # Start cron scheduler
hermes cron stop          # Stop cron scheduler
```

### 3.5 Skills

```bash
hermes skills list        # List available skills
hermes skills install <skill> # Install skill
hermes skills remove <skill>  # Remove skill
```

### 3.6 Memory

```bash
# Via mem0 API (not Hermes CLI)
curl -X POST $MEM0_ENDPOINT/memories -H "Content-Type: application/json" \
  -d '{"messages": [...], "agent_id": "hermes_wechat_pipeline"}'

curl -X POST $MEM0_ENDPOINT/memories/search -H "Content-Type: application/json" \
  -d '{"query": "...", "filters": {"agent_id": "hermes_wechat_pipeline"}}'
```

---

## 4. WeChat Capture from WSL2

### 4.1 Prerequisites

```bash
# Verify WeChat is running (from WSL2)
powershell.exe -Command "Get-Process WeChat -ErrorAction SilentlyContinue"

# Verify window title
powershell.exe -Command "(Get-Process WeChat).MainWindowTitle"
# Should contain: "公众号" or "微信"
```

### 4.2 Capture Command

```bash
# From WSL2, call Windows Python
cd /mnt/c/code/Hermes

# Run capture
python tools/windows_wechat_history.py \
  --output-dir /mnt/d/HTML/hermes-longrun-2026-04-28 \
  --html-fallback \
  --page-idle-limit 2 \
  --item-retry-limit 1 \
  --resume \
  --max-items 50
```

### 4.3 Capture Output Verification

```bash
# Check manifest
wc -l /mnt/d/HTML/hermes-longrun-2026-04-28/.hermes_wechat_history/manifest.jsonl

# Check PDFs
ls /mnt/d/HTML/hermes-longrun-2026-04-28/*.pdf | wc -l

# Check failures
grep '"status": "failed"' /mnt/d/HTML/hermes-longrun-2026-04-28/.hermes_wechat_history/manifest.jsonl | wc -l
```

---

## 5. Troubleshooting

### 5.1 WSL2 Not Running

```bash
# Windows PowerShell
wsl --shutdown
wsl
# Verify
wsl --status
```

### 5.2 Hermes Not Found

```bash
# In WSL2
source ~/.bashrc
which hermes
hermes --version
```

### 5.3 Path Issues

```bash
# Test path conversion
wslpath -w /mnt/d/HTML
# Should output: D:\HTML

# Test file access
ls /mnt/d/HTML/
```

### 5.4 Model Unreachable

```bash
# Qwen3.6-27B
curl http://127.0.0.1:11434/api/tags

# deepseek-v4-pro
curl https://api.deepseek.com/v1/models -H "Authorization: Bearer $DEEPSEEK_API_KEY"
```

### 5.5 mem0 Unreachable

```bash
curl http://127.0.0.1:11434/v1/memories -H "Content-Type: application/json" \
  -d '{"query": "test", "top_k": 1}'
```

---

## 6. Performance Tuning

### 6.1 WSL2 Memory

```bash
# Edit %USERPROFILE%\.wslconfig
[wsl2]
memory=32GB
processors=16
swap=8GB
```

### 6.2 Capture Speed

| Setting | Default | Tuned |
|---------|---------|-------|
| `page_idle_limit` | 2 | 3-5 (more articles per scroll) |
| `item_retry_limit` | 1 | 2 (more retries) |
| `max_items` | 50 | 100-200 (batch size) |

### 6.3 Disk I/O

- D drive is 16TB HDD (slow)
- Limit concurrent writes
- Use checkpoint-based resume (not full re-scan)
- Monitor Disk Time < 80%

---

**End of WSL2 Config. Next: `docs/07_RISK_REGISTER.md`**
