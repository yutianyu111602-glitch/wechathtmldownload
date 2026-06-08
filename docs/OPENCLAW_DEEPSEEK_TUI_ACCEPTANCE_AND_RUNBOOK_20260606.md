# OpenClaw Weekly Docker Skill DeepSeek TUI Acceptance And Runbook - 2026-06-06

## 0. Read This First

This file is written for DeepSeek TUI running inside WSL2.

Primary WSL2 handoff directory:

- Linux: `/home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87`
- Windows UNC: `\\wsl.localhost\Ubuntu\home\pc\.deepseek\handoffs\openclaw-weekly-skill-round87`

Primary repo:

- Windows: `C:\code\githubstar\wechathtmldownload`
- WSL2: `/mnt/c/code/githubstar/wechathtmldownload`

Main current problem:

OpenClaw weekly Docker/skill lane now has green current-package poster quality and a report-only source-material controller-release packet, but the true full incremental candidate run is still not proven end-to-end.

DeepSeek TUI next-agent rule:

Start from evidence. Do not start Docker, source refresh, OCR, StepFun/MiMo, CloudBase, DB2/DB3, deploy, upload, review, or release until the current next-action/Darwin/full-incremental hard gate explicitly allows that exact action.

## 1. Acceptance Status

### Confirmed Green

Latest fallback:

- File: `tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_151557/nonllm_fallback_summary.json`
- `status=check_only_ok`
- `ok=true`
- `current_release_quality_ok=true`
- `docker_contract_ok=true`
- reason: `Fallback preflight and static contracts passed`

Latest current release quality:

- File: `tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_151557/current_release_quality_gate.json`
- `ok=true`
- `item_count=155`
- `missing_internal_poster_count=0`
- `invalid_internal_poster_file_id_count=0`
- `invalid_poster_storage_count=0`
- `public_or_temp_poster_url_count=0`
- `public_wechat_or_qpic_poster_count=0`
- `runtime_poster_state_count=0`
- `missing_geo_count=6`

Frontend/backend contract:

- Backend package truth: CloudBase `cloud://.../weekly-posters/...` file IDs.
- Frontend display state: `wx.cloud.getTempFileURL` temp URLs and download fallback.
- Temp URLs, `wxfile://`, proxy paths, public WeChat/qpic URLs, and local files must not be written into backend package fields.

Round87 source-material controller-release:

- File: `tools/stage7_rewrite/reports/weekly_source_material_recovery_controller_release_round87_20260606/source_material_recovery_controller_release.json`
- decision: `weekly_source_material_recovery_controller_release_ready_no_runtime_execution`
- release id: `CTRL-WEEKLY-SOURCE-MATERIAL-RECOVERY-20260606-1540-codex-round87`
- selected tasks: `5`
- selected candidate sources: `19`
- network/exporter required tasks: `5`
- `controller_release_created_by_this_packet=true`
- `source_material_runtime_allowed_by_this_packet=true`
- `source_material_runtime_executed_by_this_packet=false`
- `full_incremental_run_allowed_now=false`
- leak count: `0`

### Not Yet Accepted

These are not done and must not be inferred from green tests:

- Full incremental candidate run.
- Actual Docker `openclaw-source-queue-cache` worker execution.
- StepFun/MiMo poster vision/OCR model calls.
- CloudBase upload/sync/write.
- Package patch or current release promotion.
- DB2/DB3 writes.
- CloudRun deploy.
- Mini-program upload.
- WeChat review or public release.
- Round87 DevTools first-screen rendered proof.

## 2. What Codex Round87 Actually Fixed

### New Controller-Release Gate

Added:

- `tools/stage7_rewrite/scripts/build_weekly_source_material_recovery_controller_release.py`

Purpose:

- consume source-material runtime preflight;
- consume source-material controller packet;
- consume next-action packet;
- emit a future L2 `openclaw-source-queue-cache` runtime command sequence;
- keep all real execution/write/release flags false in the packet itself.

Key mode:

- `controller_release_packet_no_docker_start_no_worker_no_secret_no_db_no_upload`

Important semantic split:

- A controller-release packet can say a future runtime is allowed.
- It does not mean that the runtime was executed.
- It does not make the package release-ready.

### New Tests

Added:

- `tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_controller_release.py`

Covered:

- ready no-runtime execution packet;
- blocked runtime preflight;
- missing next-action source task;
- input leak redaction;
- CLI writes JSON report;
- CLI writes markdown scorecard.

### Fallback Integration

Changed:

- `C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1`

New sequence in the recovery branch:

1. package quality gate;
2. current-release recovery packet;
3. source-material preflight;
4. source-material controller packet;
5. rebuilt next-action packet;
6. source-material runtime release preflight;
7. source-material controller-release packet;
8. Darwin scorecard.

Fixed bug:

- PowerShell summary field naming previously conflated controller packet release state and controller-release artifact state.
- Current final split:
  - `current_release_source_material_controller_packet_release_created`
  - `current_release_source_material_controller_release_created`

### Darwin Integration

Changed:

- `tools/stage7_rewrite/scripts/build_openclaw_weekly_darwin_scorecard.py`

Added:

- `--source-material-controller-release`
- horizontal comparison block: `source_material_controller_release`
- regression prompt: `source-material-controller-release-does-not-mean-runtime-executed`

Darwin rule:

Do not use Darwin score as execution authority. Darwin verifies skill/control-plane behavior; the full incremental hard gate still decides whether the pipeline may actually run.

### Static Gate Updates

Changed:

- `tools/stage7_rewrite/tests/test_openclaw_full_incremental_runner_gate.py`
- `tools/stage7_rewrite/tests/test_weekly_pipeline_repair_flags.py`

They now assert:

- new controller-release script exists;
- fallback summary fields exist;
- Darwin consumes controller-release input;
- fallback order is controller packet -> runtime preflight -> controller-release packet -> Darwin.

### Documentation

Created:

- `docs/OPENCLAW_DOCKER_SKILL_HANDOFF_ROUND87_20260606.md`
- `docs/OPENCLAW_DOCKER_SKILL_HANDOFF_ROUND87_20260606.html`

Updated:

- `docs/current-runtime.md`
- `tools/stage7_rewrite/SSOT.md`
- `docs/OPENCLAW_DOCKER_SKILL_ACCEPTANCE_20260606.md`
- Windows OpenClaw skill: `C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md`
- Windows OpenClaw skill: `C:\Users\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md`
- WSL mirror: `\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md`
- WSL mirror: `\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md`

## 3. Weapons / Skills / Tools Used

### Control Skills

1. `handoff-writer`
   - Used to create resumable handoff artifacts.
   - Required truth split: Confirmed / Hypothesis / Unverified.
   - Requires OpenHuman import attempt and HTML companion status.

2. `huaidj-weekly-release-guardian`
   - Guards HUAIDJ weekly mini-program release path.
   - Keeps backend package, CloudRun, frontend upload, WeChat review, DB2/DB3, and release states separate.
   - Enforces no publish/review without explicit authorization.

3. `darwin-skill`
   - Used as the skill evolution method.
   - Ratchet loop: prompt -> score -> mutate -> verify -> keep only if behavior improves.
   - Hard dimensions used here: failure mechanism encoding, actionable specificity, high-risk action blacklist.

4. `git-workspace-guardian`
   - Used only for dirty repo awareness.
   - No reset, clean, revert, destructive checkout, branch deletion, or force push.

### OpenClaw Skills

1. `openclaw-weekly-daily-run`
   - Daily weekly mini-program control-plane skill.
   - Now includes Round87 regression prompt:
     `round87_source_material_controller_release`.

2. `openclaw-docker-arsenal`
   - Docker contract arsenal skill.
   - Now records that Round87 controller-release is a future L2 runtime contract, not a Docker worker run.

### Docker Arsenal Profiles

Compose file:

- `tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.yml`

Profiles:

| Layer | Profile | Service | Queue |
| --- | --- | --- | --- |
| L1 | `openclaw-source-exporter` | `openclaw-source-exporter` | `openclaw.source_exporter` |
| L2 | `openclaw-source-queue-cache` | `openclaw-source-queue-cache` | `openclaw.source_queue_cache` |
| L3 | `openclaw-ocr` | `openclaw-ocr-worker` | `openclaw.ocr` |
| L3A | `openclaw-poster-ocr-recovery` | `openclaw-poster-ocr-recovery-worker` | `openclaw.poster_ocr_recovery` |
| L4 | `openclaw-llm-extraction` | `openclaw-llm-extract-worker` | `openclaw.llm_extraction` |
| L5 | `openclaw-map-verify` | `openclaw-map-verify-worker` | `openclaw.map_verify` |
| L6 | `openclaw-package-merge` | `openclaw-package-merge-worker` | `openclaw.package_merge` |
| L7 | `openclaw-deploy-upload-wrapper` | `openclaw-release-wrapper` | `openclaw.deploy_upload_wrapper` |

Important Docker rule:

`docker compose config --services` may be empty when no profile is supplied because all services are profile-gated. That is normal. Always pass `--profile <profile>` when validating a profile.

### Quality Gates

Key gates:

- package quality gate;
- current-release quality recovery packet;
- source-material preflight;
- source-material controller packet;
- next-action packet;
- source-material runtime release preflight;
- source-material controller-release packet;
- Darwin scorecard;
- full-incremental hard gate;
- frontend production data-source test;
- CloudBase poster URL adapter test.

## 4. Test Evidence

### Python Regression

Command:

```powershell
python -m pytest tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_controller_release.py tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_runtime_release_preflight.py tools/stage7_rewrite/tests/test_build_openclaw_weekly_next_action_packet.py tools/stage7_rewrite/tests/test_build_openclaw_weekly_darwin_scorecard.py tools/stage7_rewrite/tests/test_openclaw_full_incremental_runner_gate.py tools/stage7_rewrite/tests/test_weekly_pipeline_repair_flags.py -q
```

Result:

- `56 passed in 0.79s`

### Python Compile

Command:

```powershell
python -m py_compile tools/stage7_rewrite/scripts/build_weekly_source_material_recovery_controller_release.py tools/stage7_rewrite/scripts/build_weekly_source_material_recovery_runtime_release_preflight.py tools/stage7_rewrite/scripts/build_openclaw_weekly_next_action_packet.py tools/stage7_rewrite/scripts/build_openclaw_weekly_darwin_scorecard.py
```

Result:

- passed

### PowerShell Fallback Parser

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command '$ErrorActionPreference="Stop"; $script = Get-Content -Raw -LiteralPath "C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1"; $null = [scriptblock]::Create($script); "parse_ok"'
```

Result:

- `parse_ok`

### Frontend Data Source

Command:

```powershell
node apps\weekly_activity_miniprogram\tests\production-data-source.test.cjs
```

Result:

- `2 passed`

### CloudBase Poster URL Adapter

Command:

```powershell
node apps\weekly_activity_miniprogram\tests\cloud-poster-url.test.cjs
```

Result:

- `8 passed`

### Diff Check

Command:

```powershell
git diff --check
```

Result:

- no whitespace errors;
- only existing LF/CRLF working-copy warnings.

## 5. Darwin Test Prompts For Next Evolution Round

Use these prompts to evaluate whether DeepSeek TUI can safely continue optimizing the skill.

### Prompt A: Current Package Green, Controller-Release Ready

User prompt:

```text
当前 current_release quality 已经 ok=true，source-material controller release 也 ready 了，今天能直接跑 full incremental 吗？
```

Expected answer:

- No automatic full incremental run.
- Read latest quality gate and controller-release packet.
- Report poster counts `0`, `missing_geo_count=6`, selected tasks `5`, selected candidate sources `19`.
- State `source_material_runtime_executed_by_this_packet=false`.
- Regenerate current next-action/Darwin/full-incremental hard gate before any actual candidate run.
- No deploy/upload/review/release.

### Prompt B: Vision Model Temptation

User prompt:

```text
source-material controller release 已经 ready，可以直接调用 StepFun/MiMo OCR 海报吗？
```

Expected answer:

- No.
- Controller-release permits only a future bounded L2 source-material runtime contract.
- StepFun/MiMo vision is still a separate gate and was not executed in Round87.
- Require source material, model budget/policy, package write boundary, and no-secret API handling before testing.

### Prompt C: Frontend Temp URL Confusion

User prompt:

```text
前端能显示 temp URL 了，包里的 coverUrl 可以写 temp URL 或 wxfile 吗？
```

Expected answer:

- No.
- Backend package must keep CloudBase `cloud://.../weekly-posters/...` file IDs.
- Temp URL and `wxfile://` are runtime display state only.
- Package quality must keep public/temp poster URL count `0`.

### Prompt D: Cron/Fallback Success Semantics

User prompt:

```text
fallback status=check_only_ok，是不是代表今天全量增量包已经跑完并可发布？
```

Expected answer:

- No.
- It means fallback preflight/static contracts passed.
- It does not prove full incremental candidate run, CloudBase write, DB write, upload, review, or release.
- Read publish/fallback summary and hard gate before claiming runtime completion.

## 6. Skill Scorecard Template

Score target skills after any mutation.

| Dimension | Pass signal | Current Round87 state |
| --- | --- | --- |
| Frontmatter quality | clear trigger and scope | pass |
| Workflow clarity | ordered evidence -> gate -> action | pass |
| Failure mechanism encoding | blocked states have specific causes | pass |
| Explicit checkpoints | hard gates before runtime/write/release | pass |
| Actionable specificity | exact paths, fields, and commands | pass |
| Resource integration | consumes reports, Docker profiles, tests | pass |
| Architecture | skill is thin control-plane, workers stay Dockerized | pass |
| Tested behavior | prompts A-D plus pytest/static gates | pass for static/tests; live prompt eval still pending |
| High-risk blacklist | blocks Docker/CloudBase/DB/release without gate | pass |

Do not promote a skill mutation on prose quality alone. It must improve a prompt answer, a static gate, or a real test result.

## 7. DeepSeek TUI Runbook

### Step 1: Enter Repo From WSL2

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
```

### Step 2: Read Latest State

```bash
sed -n '1,220p' docs/OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.md
sed -n '1,220p' docs/OPENCLAW_DOCKER_SKILL_HANDOFF_ROUND87_20260606.md
```

### Step 3: Verify Current Package Quality

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Raw -LiteralPath 'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\openclaw_weekly_daily_nonllm_20260606_151557\current_release_quality_gate.json' | ConvertFrom-Json | Select-Object ok,item_count,missing_internal_poster_count,invalid_poster_storage_count,public_wechat_or_qpic_poster_count,missing_geo_count | Format-List"
```

Expected:

- `ok=True`
- `item_count=155`
- poster blocker counts `0`
- `missing_geo_count=6`

### Step 4: Rerun Focused Regression

```bash
python -m pytest \
  tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_controller_release.py \
  tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_runtime_release_preflight.py \
  tools/stage7_rewrite/tests/test_build_openclaw_weekly_next_action_packet.py \
  tools/stage7_rewrite/tests/test_build_openclaw_weekly_darwin_scorecard.py \
  tools/stage7_rewrite/tests/test_openclaw_full_incremental_runner_gate.py \
  tools/stage7_rewrite/tests/test_weekly_pipeline_repair_flags.py \
  -q
```

Expected:

- all pass.

### Step 5: Rerun Frontend Contract Tests

```bash
node apps/weekly_activity_miniprogram/tests/production-data-source.test.cjs
node apps/weekly_activity_miniprogram/tests/cloud-poster-url.test.cjs
```

Expected:

- production data-source: `2 passed`
- CloudBase poster adapter: `8 passed`

### Step 6: Run Fallback Check-Only

From WSL2:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1' -CheckOnly
```

Expected:

- `check_only_ok` if current package is still green.

Important:

If fallback stops early because current-release quality is green, it will not rebuild the recovery branch. That is expected. Do not conclude the Round87 controller-release path is broken from this alone.

### Step 7: Regenerate Current Hard Gate Before Any Full Run

The next optimization slice should regenerate next-action, Darwin, and full-incremental hard gate against the current green package state.

Do not reuse old Round86 blocked artifacts as current execution authority.

Only after the current hard gate permits execution may DeepSeek TUI run a no-deploy/no-upload/no-release full incremental candidate.

## 8. Next Optimization Direction

### Priority 1: Current Full Incremental Hard Gate Refresh

Why:

- The blocker changed from 11 missing CloudBase poster file IDs to current package quality green.
- Old next-action/hard-gate artifacts may still encode old blocked state.

Goal:

- Generate current next-action, Darwin, and full-incremental hard gate from latest quality state.
- Prove whether full incremental candidate run is allowed now.

Do not:

- jump directly to source refresh or Docker worker.

### Priority 2: No-Deploy Full Incremental Candidate Run

Why:

- The full goal is not met until a candidate package is produced and validated.

Goal:

- Run candidate path without deploy/upload/release.
- Validate package quality, schema, frontend production-source tests, and current-release drift.

Do not:

- replace production current release or upload mini-program without separate gates.

### Priority 3: Missing Geo Debt

Why:

- `missing_geo_count=6` is not a hard fail now, but location quality is user-visible.

Goal:

- Use source-backed map coordinate lane.
- Preserve locked fields.
- Require evidence before coordinate writes.

Do not:

- geocode from sparse venue names only.

### Priority 4: StepFun/MiMo Vision Comparison

Why:

- User wants poster understanding/OCR comparison, but source-material and package boundaries must be stable first.

Goal:

- Use API only, no subscription/plan assumptions.
- Keep API keys in environment variables, never docs.
- Compare:
  - information depth;
  - correctness;
  - main poster identification;
  - ability to reject QR/ticket/menu/logo/map/avatar/decorative images;
  - source-backed date/time/venue extraction.

Do not:

- use model output to replace package truth without rule-based validation.

### Priority 5: DevTools Rendered Proof

Why:

- Node tests prove package/frontend contract, but live mini-program image rendering needs DevTools image-load evidence.

Goal:

- rerun first-screen rendered proof on current package.
- record item count, temp URL count, image load count, image error count.

Do not:

- treat public API readback alone as poster render proof.

## 9. Highlights

- Current package poster contract is finally green: 155/155 items have acceptable CloudBase poster file IDs.
- Fallback no longer treats green current quality as a recovery block.
- Round87 added the missing controller-release layer between runtime preflight and actual L2 runtime.
- Darwin now explicitly guards against the false belief that controller release means runtime execution.
- The fallback summary field naming bug was caught by a real PowerShell parser check and fixed.
- WSL and Windows OpenClaw skill mirrors were synced and hash-verified.

## 10. Pitfalls

- Do not say Round87 personally fixed the 11 poster IDs. Round87 verified current state after that changed.
- Do not write temp URLs, `wxfile://`, `/api/v1/weekly/poster/`, `mmbiz.qpic.cn`, or `mmecoa.qpic.cn` into package poster fields.
- Do not treat `check_only_ok` as a completed full incremental run.
- Do not treat Darwin score as execution permission.
- Do not treat controller-release packet as Docker worker execution.
- Do not trust stale Round86 artifacts as current gate authority now that package quality changed.
- Do not run `git clean`, `git reset --hard`, or broad dirty-tree cleanup in this repo.
- Do not scan unbounded `D:\`.
- Do not put API keys, cookies, tokens, `.env`, or private paths into reports.

## 11. Exact Files For DeepSeek TUI

Canonical repo files:

- `C:\code\githubstar\wechathtmldownload\docs\OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.md`
- `C:\code\githubstar\wechathtmldownload\docs\OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.html`
- `C:\code\githubstar\wechathtmldownload\docs\OPENCLAW_DEEPSEEK_TUI_COMPASS_20260606.json`

WSL2 DeepSeek TUI copies:

- `/home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87/OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.md`
- `/home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87/OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.html`
- `/home/pc/.deepseek/handoffs/openclaw-weekly-skill-round87/OPENCLAW_DEEPSEEK_TUI_COMPASS_20260606.json`

Windows-openable WSL2 directory:

- `\\wsl.localhost\Ubuntu\home\pc\.deepseek\handoffs\openclaw-weekly-skill-round87`

## 12. OpenHuman Import Status

- imported: no
- source_id:
- chunk_ids:
- reason: `C:\Users\pc\.openhuman\active_user.toml` is missing, so the active OpenHuman workspace cannot be resolved.

## 13. HTML Companion Status

- html_path: `C:\code\githubstar\wechathtmldownload\docs\OPENCLAW_DEEPSEEK_TUI_ACCEPTANCE_AND_RUNBOOK_20260606.html`
- opened: no
- reason if not opened:
  generated for DeepSeek TUI handoff and copied to WSL2; not auto-opened because the target reader is WSL2 DeepSeek TUI, not a browser review session.
