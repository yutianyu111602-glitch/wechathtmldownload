# PC Paths Index

Updated: 2026-05-27 22:10 CST

All paths below are PC-side paths for Windows Explorer / PowerShell unless marked WSL UNC.

| Role | PC path | Status / use |
| --- | --- | --- |
| Project root | `C:\code\githubstar\wechathtmldownload` | Authoritative repo root for this lane. |
| This execution package | `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527` | Give this directory to OpenClaw first. |
| Package README | `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527\README.md` | Entry point. |
| Package prompt | `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527\OPENCLAW_EXECUTION_PROMPT.md` | Paste to OpenClaw. |
| Operating knowledge | `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527\OPENCLAW_OPERATING_KNOWLEDGE.md` | Conversation-derived pitfalls and daily rules. |
| Package runbook | `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527\DAILY_RUNBOOK.md` | Daily execution steps. |
| Package handoff | `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527\HANDOFF.md` | Formal continuity artifact. |
| Current runtime SSOT | `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md` | Current state ledger; read before acting. |
| Documentation index | `C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md` | Current authority/evidence router. |
| Thread router | `C:\code\githubstar\wechathtmldownload\docs\threads\THREADS_INDEX_20260522.md` | T1-T7 boundaries. |
| T1 source intake | `C:\code\githubstar\wechathtmldownload\docs\threads\T1_source_intake_docker_exporter_20260522.md` | Docker exporter/source queue authority. |
| T2 backend release | `C:\code\githubstar\wechathtmldownload\docs\threads\T2_weekly_backend_release_20260522.md` | Backend/package/deploy gates. |
| T3 mini-program frontend | `C:\code\githubstar\wechathtmldownload\docs\threads\T3_mini_program_frontend_20260522.md` | Frontend upload/review boundary. |
| T7 docs control | `C:\code\githubstar\wechathtmldownload\docs\threads\T7_docs_ssot_control_20260522.md` | SSOT closeout owner. |
| Weekly handoff index | `C:\code\githubstar\wechathtmldownload\docs\weekly-miniprogram-handoff-20260519\INDEX.md` | Historical and active weekly mini-program handoff root. |
| Compact OpenClaw skillpack | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\OPENCLAW_WEEKLY_FULL_FLOW_SKILLPACK_20260526.md` | Current compact OpenClaw/Hermes operating entry. |
| Full OpenClaw runbook | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md` | Full guarded backend/resource lane. |
| Stage7 SSOT | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\SSOT.md` | Stage7 runtime truth. |
| OpenClaw package audit | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\OPENCLAW_PACKAGE_AUDIT_20260527.md` | Current package audit; local usable with version-control gap. |
| Latest T3 upload report | `C:\code\githubstar\wechathtmldownload\reports\WEEKLY_MINIPROGRAM_FRONTEND_UPLOAD_20260527_7_ATLAS_BETA_COPY.md` | Latest developer upload evidence. |
| Current drift gate | `C:\code\githubstar\wechathtmldownload\reports\WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md` | Blocks release claims until resolved. |
| Drift hook report | `C:\code\githubstar\wechathtmldownload\reports\WEEKLY_T2_T3_RELEASE_READINESS_DRIFT_HOOK_20260526.md` | Release-readiness dry-run gate. |
| Backend deploy proof | `C:\code\githubstar\wechathtmldownload\reports\WEEKLY_Q3_CACHE_KEY_BACKEND_DEPLOY_20260525.md` | CloudRun `weekly-api-066` evidence. |
| Alternate source research | `C:\code\githubstar\wechathtmldownload\reports\WECHAT_ALT_SOURCE_DOWNLOAD_RESEARCH_20260526.md` | 图文/视频号 automation research. |
| Account registry | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_accounts_seed.json` | 129 baseline accounts, 125 active, 4 inactive/closed. |
| Auth status script | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py` | No-secret exporter/session status and auth lifecycle. |
| Session diagnostic script | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py` | Real article-list session proof. |
| QR notification wrapper | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\notify_weekly_exporter_qr_refresh.ps1` | 3-day QR/iMessage notification wrapper. |
| Daily publish wrapper | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1` | Main OpenClaw daily backend/resource entry. |
| Current release drift validator | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_weekly_current_release_drift.py` | T2/T3 package-root drift check. |
| Current release dry-run builder | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_weekly_release_candidate_dry_run.py` | Release candidate gate with drift summary. |
| Mini-program validation script | `C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram\scripts\Test-CleanCiQuality.ps1` | T3 clean CI quality check. |
| iMessage switchover doc | `\\wsl.localhost\Ubuntu\home\pc\.openclaw\docs\imessage-bot-user-switchover-20260527.md` | WSL/Mac iMessage bot-account switchover notes. |
| iMessage bot activation script | `\\wsl.localhost\Ubuntu\home\pc\.openclaw\scripts\activate-openclaw-imessage-bot-account.sh` | Activates dedicated bot-account relay after Mac SSH/GUI setup. |
| Current OpenClaw WSL config root | `\\wsl.localhost\Ubuntu\home\pc\.openclaw` | WSL2 OpenClaw operational config/docs root. |

## Handoff / Report Directory Roots

Use these roots when OpenClaw needs to audit prior handoffs or evidence. Do not treat old handoffs as current truth unless `docs\DOCUMENTATION_INDEX.md` or `docs\current-runtime.md` promotes them.

| Role | PC path | Status / use |
| --- | --- | --- |
| Current package root | `C:\code\githubstar\wechathtmldownload\docs\handoffs\openclaw_daily_miniprogram_execution_package_20260527` | Current OpenClaw package. |
| Handoff root | `C:\code\githubstar\wechathtmldownload\docs\handoffs` | Durable handoff package directory. |
| Weekly mini-program handoff root | `C:\code\githubstar\wechathtmldownload\docs\weekly-miniprogram-handoff-20260519` | Weekly mini-program historical/current handoff collection; start with `INDEX.md`. |
| Root-level historical handoffs | `C:\code\githubstar\wechathtmldownload` | Contains older `NEXT_AGENT_HANDOFF_*.md/html`; use only as evidence through current docs index. |
| Repo reports | `C:\code\githubstar\wechathtmldownload\reports` | Repo-level reports and upload/deploy evidence. |
| Stage7 reports | `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports` | Stage7 run reports, daily wrapper outputs, auth/session reports. |
| Generated docs-site root | `C:\code\docs-site\projects\wechathtmldownload` | Generated HTML review surface; Markdown remains canonical. |
| Active project docs catalog | `C:\code\docs\generated\active-project-doc-sites.md` | Cross-project docs-site catalog. |
