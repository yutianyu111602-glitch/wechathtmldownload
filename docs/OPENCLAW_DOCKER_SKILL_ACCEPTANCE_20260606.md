# OpenClaw Docker Skill Acceptance - 2026-06-06

## Scope

This acceptance document covers the OpenClaw weekly mini-program Docker/skill lane after the latest mini-program frontend adapter:

- backend/package truth remains CloudBase `cloud://.../weekly-posters/YYYYMMDD/...` file IDs;
- frontend runtime may convert `cloud://` to temp URLs with `wx.cloud.getTempFileURL`;
- temp URLs, `wxfile://`, proxy paths, public WeChat/qpic URLs, and local paths must never be written back into `current.json`;
- source-material recovery, poster OCR, StepFun/MiMo review, CloudBase upload, package patch, DB2/DB3 writes, deploy, upload, review, and public release remain separate gates.

## Round87 Update

The Round86 evidence below is retained for audit history, but it is no longer the latest package-quality state.

Latest verified state:

- `docs/OPENCLAW_DOCKER_SKILL_HANDOFF_ROUND87_20260606.md`
- `tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_151557/nonllm_fallback_summary.json`
- `tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_151557/current_release_quality_gate.json`

Current result:

- `status=check_only_ok`
- `current_release_quality_ok=true`
- `item_count=155`
- `missing_internal_poster_count=0`
- `invalid_internal_poster_file_id_count=0`
- `invalid_poster_storage_count=0`
- `public_or_temp_poster_url_count=0`
- `public_wechat_or_qpic_poster_count=0`
- `runtime_poster_state_count=0`
- `missing_geo_count=6`

Round87 did not execute the CloudBase/poster write or package patch that made this green; it verified the current state and added the next report-only source-material controller-release packet:

`tools/stage7_rewrite/reports/weekly_source_material_recovery_controller_release_round87_20260606/source_material_recovery_controller_release.json`

## Latest Evidence

Latest real fallback run:

`tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_145833/nonllm_fallback_summary.json`

Key outcome:

- `status=blocked_on_current_release_quality_gate`
- `ok=true`
- `current_release_quality_ok=false`
- `current_release_next_action_task_count=5`
- `current_release_full_incremental_run_allowed_now=false`
- `current_release_darwin_score_total=45`

Package quality gate:

`tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_145833/current_release_quality_gate.json`

- `item_count=155`
- `missing_internal_poster_count=11`
- `invalid_poster_storage_count=11`
- `public_or_temp_poster_url_count=0`
- `public_wechat_or_qpic_poster_count=0`
- `runtime_poster_state_count=0`
- `missing_geo_count=6`
- hard failures: `missing_internal_poster_file_id`, `invalid_poster_storage`

This proves the latest frontend adapter is not the blocker. The blocker is still upstream backend/package quality: 11 current items lack real CloudBase poster file IDs and `poster_storage=cloudbase`.

## New Runtime Gate

New script:

`tools/stage7_rewrite/scripts/build_weekly_source_material_recovery_runtime_release_preflight.py`

Latest report:

`tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_145833/current_release_quality_recovery/source_material_recovery_runtime_release_preflight.json`

Result:

- `decision=weekly_source_material_recovery_runtime_release_preflight_ready_report_only_requires_controller_release`
- `failed_required_check_ids=[]`
- `selected_task_count=5`
- `selected_candidate_source_count=19`
- `network_or_exporter_required_task_count=5`
- `controller_release_created_by_this_packet=false`
- `actual_source_material_acquisition_allowed_now=false`
- `docker_worker_allowed_now=false`
- `full_incremental_run_allowed_now=false`
- `raw_url_private_path_secret_leak_count=0`
- `backend_package_policy=cloudbase_file_id_only_no_temp_url`
- required file ID pattern: `cloud://.../weekly-posters/YYYYMMDD/...`

Interpretation:

This is a ready report-only runtime preflight. It does not authorize source refresh, Docker worker execution, OCR, StepFun/MiMo calls, CloudBase upload, package patch, DB writes, deploy, upload, review, or release.

## Darwin Acceptance

Latest Darwin scorecard:

`tools/stage7_rewrite/reports/openclaw_weekly_daily_nonllm_20260606_145833/current_release_quality_recovery/openclaw_darwin_scorecard/openclaw_weekly_darwin_scorecard.json`

- `decision=keep_next_action_mutation_continue_goal`
- `score=45/45`
- `test_prompts=10`
- consumes `source_material_runtime_preflight`
- `source_material_runtime_worker_allowed_now=false`
- `source_material_runtime_full_incremental_run_allowed_now=false`
- leak `0`

Acceptance rule:

Darwin score is skill/control-plane quality only. It cannot override package quality, source-material, full-incremental, CloudBase, DB, deploy, upload, review, or release gates.

## Frontend Adapter Acceptance

Frontend tests prove the current adapter behavior:

- CloudBase `cloud://` poster IDs are resolved to temp URLs for display.
- original `posterFileId` / `cloudFileId` is preserved.
- fallback may download a CloudBase file for display retry.
- runtime temp URL or `wxfile://` state is not package truth.
- aggregate child overview/source actions remain suppressed.

Tests passed:

- `apps/weekly_activity_miniprogram/tests/cloud-poster-url.test.cjs`: 8 passed
- `apps/weekly_activity_miniprogram/tests/poster-pool.test.cjs`: 7 passed
- `apps/weekly_activity_miniprogram/tests/format-quality.test.cjs`: passed all printed checks
- `apps/weekly_activity_miniprogram/tests/source-articles.test.cjs`: 6 passed
- `apps/weekly_activity_miniprogram/tests/external-link-action.test.cjs`: 4 passed

Production data-source gate remains intentionally red:

`node apps/weekly_activity_miniprogram/tests/production-data-source.test.cjs`

- 1 passed, 1 failed
- failure: `144 !== 155` at `apps/weekly_activity_miniprogram/tests/production-data-source.test.cjs:114`

Interpretation:

The production package has 155 items, but only 144 currently satisfy the CloudBase poster file ID contract. The remaining 11 missing backend file IDs block acceptance.

## Test Evidence

Focused Python regression:

`python -m pytest tools/stage7_rewrite/tests/test_openclaw_full_incremental_runner_gate.py tools/stage7_rewrite/tests/test_weekly_pipeline_repair_flags.py tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_controller_packet.py tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_runtime_release_preflight.py tools/stage7_rewrite/tests/test_build_openclaw_weekly_next_action_packet.py tools/stage7_rewrite/tests/test_build_openclaw_weekly_darwin_scorecard.py -q`

Result:

- `54 passed`

Static/diff check:

- `git diff --check` passed, with only existing CRLF warnings.

## Accepted Changes

Added:

- `tools/stage7_rewrite/scripts/build_weekly_source_material_recovery_runtime_release_preflight.py`
- `tools/stage7_rewrite/tests/test_build_weekly_source_material_recovery_runtime_release_preflight.py`
- `docs/OPENCLAW_DOCKER_SKILL_ACCEPTANCE_20260606.md`

Updated:

- `C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1`
- `tools/stage7_rewrite/scripts/build_openclaw_weekly_darwin_scorecard.py`
- `tools/stage7_rewrite/tests/test_build_openclaw_weekly_darwin_scorecard.py`
- `tools/stage7_rewrite/tests/test_openclaw_full_incremental_runner_gate.py`
- `tools/stage7_rewrite/tests/test_weekly_pipeline_repair_flags.py`

## Current Blockers

Do not run the full incremental update pipeline yet. Current blockers:

1. `missing_internal_poster_count=11`
2. `invalid_poster_storage_count=11`
3. `missing_geo_count=6`
4. source-material queue gap for selected OCR tasks: `network_or_exporter_required_task_count=5`
5. next-action still has `task_count=5`
6. `full_incremental_run_allowed_now=false`

## Next Accepted Action

The next safe action is a separate controller-released, bounded source-material acquisition or exporter/latest-queue recovery, followed by rerunning:

1. source-material preflight;
2. poster OCR recovery gates;
3. CloudBase poster file ID package quality gate;
4. missing geo recovery gate;
5. next-action packet;
6. Darwin scorecard;
7. full incremental preflight hard gate.

Until those gates are green, do not execute source refresh, Docker worker, OCR, StepFun/MiMo, CloudBase upload, package patch, DB2/DB3 write, CloudRun deploy, CloudBase sync, mini-program upload, WeChat review, or public release.
