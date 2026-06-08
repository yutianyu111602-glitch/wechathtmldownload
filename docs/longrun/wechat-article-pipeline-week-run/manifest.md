<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat Article Pipeline Week Run — Final Manifest Update

更新时间：2026-04-27 13:40 +08
工作区：`C:\code\githubstar\wechathtmldownload`
状态：MarkItDown 已完成 ✅，L2 部分完成，最终 handoff 已写入

## Run State

```yaml
run_state:
  mode: unattended
  status: paused_for_human_review
  current_phase: markitdown_completed_l2_partial
  current_story_id: US-004
  iteration: 3
  max_iterations: 24
  failure_budget: 3
  last_heartbeat_at: 2026-04-27T13:40:00+08:00
  last_verified_at: 2026-04-27T13:40:00+08:00
  next_resume_cursor: execute US-004 MarkItDown output verification, then US-005 L2 JSONL cleaning
  stop_reason: ""
  artifacts:
    prd: docs/longrun/wechat-article-pipeline-week-run/03-prd.md
    prd_json: .omc/ralph/wechat-article-pipeline-week-run/prd.json
    execution_plan: docs/longrun/wechat-article-pipeline-week-run/05-execution-plan.md
    latest_handoff: docs/longrun/wechat-article-pipeline-week-run/FINAL_HANDOFF_2026-04-27.md
    latest_scorecard: .omc/state/wechat-article-pipeline-week-run-state.json
    markitdown_log: docs/longrun/wechat-article-pipeline-week-run/logs/markitdown-resume-20260427-132302.log
    markitdown_backup: D:/rawwechat_md/markitdown-batch-status.json.bak-20260427-1320
```

## Canonical Read Order

1. `docs/longrun/wechat-article-pipeline-week-run/FINAL_HANDOFF_2026-04-27.md`
2. `docs/longrun/wechat-article-pipeline-week-run/manifest.md`
3. `.omc/ralph/wechat-article-pipeline-week-run/prd.json`
4. `docs/longrun/wechat-article-pipeline-week-run/03-prd.md`
5. `docs/longrun/wechat-article-pipeline-week-run/05-execution-plan.md`

## 关键完成项

- **MarkItDown**: 8095/8095 completed, 0 failed. `D:\rawwechat_md` 有 8095 个 .md 文件。
- **L1**: 67,211 article facts across 2 JSONL parts.
- **L2**: 94/180 unique pilot articles extracted (POTENT 30, Riff Changsha 30, OIL油 30, EchoBay 4).
- **Stale state repair**: Backup created, running item fixed, counters recomputed.

## 下一步

执行 US-004（MarkItDown 输出验证）→ US-005（L2 清洗）→ US-006（继续 L2）→ 后续 story。

## 禁止动作

- 不删除 `D:\rawwechat_md`
- 不启动 `llama-server.exe`
- 不直接消费脏 L2 JSONL
- 不在未备份前修改生产状态
