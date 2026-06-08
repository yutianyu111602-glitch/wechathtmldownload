<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Loop 001 Handoff — Night Watcher State

**Date:** 2026-04-26 22:40 +08  
**Agent:** opencode  
**Next Agent:** OpenClaw main (via `openclaw agent --local`)  

---

## Current State

| Field | Value |
|-------|-------|
| Mode | Unattended longrun |
| Phase | Phase 0 — Ready to start |
| Current Story | US-001 (Environment Validation) |
| All Stories Status | US-001 through US-006: passes=false |
| System Health | ALL GREEN |
| Blockers | Stage lock file needs cleanup before US-002 |

## What Was Done

1. Full OCR quality validation completed — 34,370 backend=none files are NORMAL
2. final_pack attempted and interrupted at 73.7% (bash 60-min timeout)
3. Complete code analysis of finalize-llm-pack, calibration, and downstream tools
4. All 7 historical documents audited, contradictions identified and resolved
5. Longrun document system established under docs/longrun/night-watcher/
6. Ralph prd.json generated with 6 stories
7. Data inventory: 93,653 raw articles, 93,253 LLM artifacts, 93,000 MD mirrors

## Key Decisions Made

1. Use _llm_release_v2 (not _llm_release) for final_pack restart
2. Allow llama-swap restart for model service recovery (infrastructure exception)
3. Disk: 100GB pre-flight YELLOW, 5GB runtime RED
4. Monitoring: 10 min active, 30 min idle
5. This manifest.md is the single entry point (supersedes all prior docs)

## Files to Read First

1. `docs/longrun/night-watcher/manifest.md` — Entry point
2. `docs/longrun/night-watcher/04-prd.json` — Story status
3. This file — Current state

## Next Action (OpenClaw Commands)

### 1. 启动心跳 cron（每10分钟自动检查）
```bash
openclaw cron add --name "night-watcher-heartbeat" --schedule "cron */10 * * * * @ Asia/Shanghai" --message "执行守夜人心跳：1) 检查当前story状态 2) 统计_llm_release_v2/articles文章数 3) 检查磁盘/内存/GPU健康 4) 追加到NIGHT_WATCHER_LOG 5) 发送Telegram状态通知" --channel telegram --deliver
```

### 2. 启动 US-001（环境检查与锁清理）
```bash
openclaw agent --local --message "执行守夜人 US-001：1) 检查D盘剩余空间>100GB 2) 检查内存空闲>10GB 3) 检查RTX4090显存>10GB空闲 4) curl http://127.0.0.1:11434/v1/models确认Qwen3.6-27B已加载 5) 确认没有pipeline进程在运行，删除D:\DDownload\.wechat-live-stage-lock.json 6) 结果追加到NIGHT_WATCHER_LOG" --deliver
```

### 3. 启动 US-002（final_pack 执行）
```bash
openclaw agent --local --timeout 10800 --message "执行守夜人 US-002：1) 在C:\code\githubstar\wechathtmldownload目录运行finalize-llm-pack到_llm_release_v2 2) 监控进度 3) 完成后验证manifest.json和index.jsonl" --deliver
```

### 4. 后续 US-003~006
每个完成后，继续发送下一个：`openclaw agent --local --timeout [秒数] --message "执行守夜人 US-00X..." --deliver`

## Critical Paths

```
D:/DDownload/_llm_artifacts/          → Input (93,253 articles, 63 clubs)
D:/DDownload/_llm_release_v2/         → Output (to be created)
D:/DDownload/_queues/                  → Logs, PID files, progress
C:/code/githubstar/wechathtmldownload/ → Code and tools
```

## Active Issues

- [ ] Stage lock file at D:\DDownload\.wechat-live-stage-lock.json needs cleanup
- [ ] Partial _llm_release (68,733 articles) exists but should be preserved, not deleted
- [ ] Log gap from 04-24 to 04-26 needs retrospective entry
