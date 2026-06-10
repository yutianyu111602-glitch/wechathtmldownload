# DO NOT UPLOAD Hits

Audit date: 2026-06-10

## Files that exist locally but MUST NOT be in Git

| Type | Local Path | In Git? | Status |
|---|---|---|---|
| .env (secrets) | services/weekly_activity_cloudrun/.env | NO | SAFE - properly excluded by .gitignore |
| .env.local | apps/weekly_activity_miniprogram/.env.local | NO | SAFE |
| node_modules/ | */node_modules/ | NO | SAFE - properly excluded |
| SQLite DB | reports/**/*.sqlite | NO | SAFE - excluded by .gitignore |
| SQLite DB | tools/stage7_rewrite/atlas_dj_v2.sqlite | NO | SAFE |
| venv | tools/stage7_rewrite/.venv/ | NO | SAFE |
| venv | tools/stage7_rewrite/.venv-wsl-vector/ | NO | SAFE |
| Python cache | __pycache__/ | NO | SAFE |
| pytest cache | .pytest_cache/ | NO | SAFE |
| Upload logs | apps/weekly_activity_miniprogram/upload-*.log | NO | SAFE |
| Runtime logs | *.log, *.log.err | NO | SAFE |
| PID files | *.pid | NO | SAFE |
| Temp dirs | tmp/, tmp-*/ | NO | SAFE |
| Dist | dist/ | NO | SAFE |
| Build | build/ | NO | SAFE |
| IDE config | .vscode/ (non-shared) | PARTIAL | Some vscode files tracked |
| Mem0 cache | .mem0/ | NO | SAFE |
| HERMES runtime | .hermes/ | NO | SAFE |
| OpenClaw backup | _openclaw_backups/ | NO | SAFE |
| Understand cache | .understand-anything/ | NO | SAFE |
| CodeGraph | .codegraph/ | NO | SAFE |
| Night Watcher zip | NIGHT_WATCHER_COMPLETE_PACKAGE.zip | NO | SAFE |
| CloudRun zip artifacts | services/weekly_activity_cloudrun/code*.zip | NO | SAFE |

## Files that SHOULD be in .gitignore but are tracked

| File | Risk | Recommendation |
|---|---|---|
| cloudbaserc.json | Low (envId is not secret) | Already tracked, acceptable |
| project.config.json | Low (appId is public) | Already tracked, acceptable |
| package-lock.json | None (dependency lock) | Correctly tracked |

## Files that existed in PROD but are now excluded

- D:/rawwechat/ (TB of raw HTML) - External, never in Git
- D:/DDownload/_archive_mptext/ (TB of archives) - External, never in Git  
- /tmp/atlas_merged.sqlite (3.8GB) - External, never in Git
- /tmp/atlas_serving_final_v4/atlas_serving.sqlite (1.6GB) - External, never in Git

## VERDICT: Secrets and data artifacts are properly excluded.
