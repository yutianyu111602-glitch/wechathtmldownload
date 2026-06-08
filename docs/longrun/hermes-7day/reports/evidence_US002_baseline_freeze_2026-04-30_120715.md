<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Evidence Pack — US-002 Baseline Freeze

- 命令: `python3 /tmp/hermes_us002_execute.py`
- 开始: 2026-04-30T12:07:15+08:00
- 结束: 2026-04-30T12:07:15+08:00
- 输入: `/mnt/d/DDownload/_llm_release_v2/manifest.json`, `index.jsonl`, `checksums.sha256`, `/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/handoff-pack/baseline/baseline-snapshot.json`, `/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/existing-coverage.md`
- 输出: `/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/evidence_US002_baseline_freeze_2026-04-30_120715.md`, `/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/checkpoint-day2_2026-04-30_120715.md`, `/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/daily-executor-2026-04-30_120715.md`
- 验收: PASS
- 指标:
```json
{
  "manifest": {
    "exists": true,
    "size_bytes": 1191,
    "mtime": "2026-04-27T16:01:06+08:00"
  },
  "index": {
    "exists": true,
    "size_bytes": 67837708,
    "mtime": "2026-04-27T15:19:25+08:00"
  },
  "checksums": {
    "exists": true,
    "size_bytes": 69909224,
    "mtime": "2026-04-27T16:01:06+08:00"
  },
  "baseline_snapshot": {
    "exists": true,
    "size_bytes": 652,
    "mtime": "2026-04-29T12:04:19+08:00"
  },
  "coverage_report": {
    "exists": true,
    "size_bytes": 1178,
    "mtime": "2026-04-29T12:05:41+08:00"
  },
  "manifest_total_articles": 93000,
  "manifest_copied_articles": 93000,
  "quality_counts": {
    "ready": 81425,
    "review": 10437,
    "blocked": 1138
  },
  "index_lines": 93000,
  "checksums_lines": 558002
}
```
- 下一步: US-003 Context Gate / capture queue；WeChat 当前不可用时只做 queue/分析/状态报告，不启动 capture。

## Acceptance checks
- ✅ index line count matches manifest total_articles=93000
- ✅ manifest copied_articles=total_articles=93000
- ✅ baseline-snapshot.json exists
- ✅ existing-coverage.md exists
- ✅ checksums.sha256 exists with 558002 lines

## Failures
- none
