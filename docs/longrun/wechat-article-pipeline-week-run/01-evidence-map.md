<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Evidence Map: WeChat Article Pipeline Week Run

时间：2026-04-27 13:15 +08

## 已读权威文档

- `C:\code\githubstar\AGENT_START_HERE.md`
- `C:\code\githubstar\SKILL_SYSTEM.md`
- `C:\code\githubstar\SKILL_CLEANUP_REPORT.md`
- `C:\code\githubstar\.codex\skills\workflow-skill-router\SKILL.md`
- `C:\code\githubstar\wechathtmldownload\HANDOFF.md`
- `C:\code\githubstar\wechathtmldownload\docs\MD_METHOD_EVALUATION_AND_PRODUCTION_FLOW_2026-04-21.md`
- `C:\code\githubstar\wechathtmldownload\docs\longrun\wechat-100k-pipeline-performance\manifest.md`
- `C:\code\githubstar\wechathtmldownload\artifacts\next-stage-consumable\2026-04-27-expanded\ARTICLE_PIPELINE_HANDOFF_2026-04-27.md`
- `C:\code\githubstar\wechathtmldownload\artifacts\next-stage-consumable\2026-04-27-minimal\PILOT_CONVERSION_PLAN_2026-04-27.md`
- `C:\code\githubstar\wechathtmldownload\artifacts\next-stage-consumable\2026-04-27-minimal\llm-analysis\QWEN_BATCH_QUALITY_REVIEW_2026-04-27.md`
- `C:\code\githubstar\wechathtmldownload\package.json`
- `C:\code\githubstar\wechathtmldownload\src\pipeline\runMarkitdownBatch.ts`
- `C:\code\githubstar\wechathtmldownload\tests\runMarkitdownBatch.test.ts`
- `C:\code\githubstar\wechathtmldownload\tools\watchMarkitdownBatchStatus.mjs`

## 目录和计数事实

- `D:\rawwechat`: exists, HTML count `8095`.
- `D:\rawwechat_md`: exists, recursive Markdown count `3146`.
- `D:\rawwechat_archive`: missing.
- `D:\rawwechat_llm_artifacts`: missing.
- `D:\rawwechat\_state`: missing.
- `D:\DDownload\_llm_release\articles`: exists, club dirs `49`, article dirs `68733`.
- `artifacts\next-stage-consumable\2026-04-27-expanded`: `207` files, about `17.61 MB`.
- `artifacts\next-stage-consumable\2026-04-27-minimal`: `41` files, about `0.21 MB`.

## MarkItDown stale state

- Status file: `D:\rawwechat_md\markitdown-batch-status.json`.
- Status: `running`.
- Total: `8095`.
- Succeeded: `3146`.
- Failed: `0`.
- Skipped: `0`.
- Completed: `3146`.
- Items: `queued=4948`, `running=1`, `succeeded=3146`.
- Current file: `D:\rawwechat\loopy Club\html\20161026_11_13 周日｜兵马司唱片呈现Future Orients 全新专辑《Eat or Die》全国巡演杭州站_kI5WNi0LLOBQ5e0ID9aOtQ.html`.

## New article-release extraction state

- L1 facts: `67211` records.
- L1 part files: `article-facts.part-0001.jsonl=65794`, `article-facts.part-0002.jsonl=1417`.
- L2 target: `180` selected pilot articles, 6 clubs x 30.
- L2 current clean rerun: `94/180` unique article lines.
- L2 quality caveat: first 94 lines include `91` content_type rows and `3` null rows; some rows may include llama log text before the JSON payload.
- L2 runner: `scripts\l2-batch-runner.ps1` patched after bug discovery.

## Conflicts resolved

- Old report claimed `D:\rawwechat_md` output was empty. Confirmed false: recursive `.md` count is `3146`.
- `HANDOFF.md` is broad and historical; this week-run manifest is the current authority for this one-week unattended operation.
- `docs\longrun\wechat-100k-pipeline-performance\manifest.md` concerns previous `D:\DDownload\_llm_artifacts` production export; this run focuses on `D:\rawwechat` + `D:\rawwechat_md` + current article extraction artifacts.

## Evidence gaps

- Need fresh full process scan before any production write.
- Need backup and parse validation before editing MarkItDown status.
- Need L2 cleaner before post-processing current JSONL.
- Need decide after sample validation whether to resume rawwechat LLM artifact export.
