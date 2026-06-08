<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Execution Plan: WeChat Article Pipeline Week Run

更新时间：2026-04-27 13:15 +08

## Master Plan

1. Freeze evidence and protect state.
2. Repair stale MarkItDown state with backup.
3. Resume MarkItDown and monitor until completion or stop gate.
4. Clean and finish L2 extraction.
5. Generate L2 report and L3 candidate list.
6. Run bounded L3 only if L2 quality is acceptable.
7. Audit L1 coverage gaps.
8. Dry-run rawwechat LLM artifact export.
9. Start full rawwechat LLM export only if gates pass.
10. Close with final operator report and SSOT update.

## Loop Protocol

- Read `manifest.md`, latest loop handoff, and `.omc/ralph/wechat-article-pipeline-week-run/prd.json`.
- Pick the lowest-priority story with `passes=false` and dependencies satisfied.
- Define file boundary and verification commands before modifying files.
- Run the smallest complete action.
- Verify.
- Update `prd.json`, `.omc/state/wechat-article-pipeline-week-run-state.json`, `manifest.md`, and loop handoff.
- Continue unless a stop gate fires.

## Production Write Policy

- `D:\rawwechat_md\markitdown-batch-status.json` may be modified only by US-002 and only after backup.
- `D:\rawwechat_md\**\*.md` may be written only by the official `export:rawwechat-md` script.
- `D:\rawwechat_llm_artifacts` may be created only after US-010 dry-run gates pass.
- No source data under `D:\rawwechat` or `D:\DDownload\_llm_release\articles` may be modified.

## Verification Commands

- Baseline counts: PowerShell path-specific counts only.
- Status validation: `Get-Content <status.json> -Raw | ConvertFrom-Json`.
- Repo build if code changed: `npm run build`.
- Tests if code changed: targeted `npm test -- <test file>` or full `npm test` when safe.
- JSON validation: parse each JSON/JSONL line with PowerShell or Node scripts.

## One-Week Budget

- Max iterations: 24.
- Max repairs per story: 3.
- Major checkpoint: every 3 stories.
- Heartbeat: at least once per story and before/after any long-running command.

## Stop Gates

- Conflicting active writer process.
- Backup missing before production status edit.
- JSON parse failure after status edit.
- Count regression without explanation.
- Same story fails 3 times.
- Need deletion, external publish, paid call, secret, git push, or process kill.
