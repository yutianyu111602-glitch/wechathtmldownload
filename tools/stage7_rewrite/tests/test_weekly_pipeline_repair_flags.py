import ast
import json
import os
import runpy
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FALLBACK = (
    Path(os.environ.get("USERPROFILE", r"C:\Users\pc"))
    / ".openclaw"
    / "bin"
    / "openclaw-weekly-daily-nonllm-fallback.ps1"
)


def test_weekly_pipeline_resume_vl_dir_skips_upstream_reset_but_keeps_downstream_pipeline():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    assert '[string]$ResumeVlDir = ""' in script
    assert '[string]$ResumeVlEvidenceDir = ""' in script
    assert '$ResumeFromVl = -not [string]::IsNullOrWhiteSpace($ResumeVlDir)' in script
    assert 'Resume from existing VL package' in script
    assert '$PACK_OCR_DIR = (Resolve-Path -LiteralPath $ResumeVlDir).Path' in script
    assert '$QUEUE_FILE = $PrefetchQueue' in script
    assert '$PACK_DIR = $PACK_OCR_DIR' in script
    assert 'Step 3.5: Entity Enrichment (dj-dataset)' in script
    assert 'Step 4: Build Mini-Program API JSON' in script


def test_weekly_pipeline_resumes_partial_vl_evidence_without_deleting_it():
    weekly = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "function Complete-VlEnrichmentOutput" in weekly
    assert "vl_enrichment_exit_override.json" in weekly
    assert "complete_outputs_nonzero_exit_recorded" in weekly
    assert "non-zero process exit remains terminal" in weekly
    assert "--resume-from-evidence-dir" in weekly
    assert "$ResumeVlEvidenceDir" in weekly
    assert "Preserving VL output dir for evidence resume" in weekly
    assert "Complete-VlEnrichmentOutput -InputDir $PACK_DIR -OutputDir $PACK_OCR_DIR" in weekly
    vl_step = weekly[
        weekly.index('Invoke-Step "Step 3: Sanji Qwen3-VL Direct Enrichment') :
        weekly.index("# ─── Step 3.5:")
    ]
    assert "$global:LASTEXITCODE = $vlExitCode" in vl_step
    assert "$global:LASTEXITCODE = 0" not in vl_step

    build_block = runner[runner.index('Invoke-RunStep "Build daily source package from selected source queue"') :]
    build_block = build_block.split('if (-not $DisableIncrementalMerge)', 1)[0]
    assert '[string]$ResumeVlDir = ""' in runner
    assert '[string]$ResumeVlEvidenceDir = ""' in runner
    assert (
        '$allowImplicitVlResume = ($PosterExtractionMode -eq "vl_direct_qwen" -and '
        '-not (Test-SanjiClientSourceMode -Mode $SourceMode))'
    ) in build_block
    assert "$vlCompleteOutput" in build_block
    assert "elseif ($allowImplicitVlResume -and $vlCompleteOutput)" in build_block
    assert "elseif ($allowImplicitVlResume -and (Test-Path $vlEvidenceDir)" in build_block
    assert "$pipelineArgs.ResumeVlDir = $vlDir" in build_block
    assert "$pipelineArgs.ResumeVlEvidenceDir = $vlEvidenceDir" in build_block
    assert build_block.index("$pipelineArgs.ResumeVlDir = $vlDir") < build_block.index(
        "$pipelineArgs.ResumeVlEvidenceDir = $vlEvidenceDir"
    )


def test_sanji_publish_never_implicitly_resumes_a_week_tag_vl_package():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")
    build_block = runner[runner.index('Invoke-RunStep "Build daily source package from selected source queue"') :]
    build_block = build_block.split('if (-not $DisableIncrementalMerge)', 1)[0]

    assert '-not (Test-SanjiClientSourceMode -Mode $SourceMode)' in build_block
    assert "Skip implicit VL resume for Sanji source" in build_block
    assert "Sanji source snapshot must be rebuilt" in build_block


def test_weekly_pipeline_step_log_is_written_from_finally_on_failure():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")
    invoke_step = script[script.index("function Invoke-Step") : script.index("function Reset-OutputDir")]

    assert "finally {" in invoke_step
    assert "PIPELINE_STEP_LOG_$WEEK_TAG.jsonl" in invoke_step
    assert "status = if ($stepExit -eq 0)" in invoke_step
    assert "error = $stepError" in invoke_step


def test_weekly_pipeline_repair_step_enforces_window_and_explicit_source_maps():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    assert "repair_weekly_release_conflicts.py" in script
    assert "--explicit-source-maps-only" in script
    assert "--enforce-window-start" in script


def test_weekly_pipeline_materializes_all_release_items_before_strict_coverage_audit():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    step48 = script[script.index('Invoke-Step "Step 4.8: Source-grounded materialized enrichment"') :]
    step48 = step48.split('Invoke-Step "Step 4.9: Audit materialized field coverage"', 1)[0]
    assert "materialize_source_grounded_outputs.mjs" in script
    assert "--all-release-items" in step48
    assert step48.index("--all-release-items") > step48.index("--force")


def test_openclaw_publish_wrapper_repair_step_enforces_window_and_explicit_source_maps():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "repair_weekly_release_conflicts.py" in script
    assert "--explicit-source-maps-only" in script
    assert "--enforce-window-start" in script


def test_openclaw_publish_wrapper_quality_gate_fails_on_missing_geo():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    quality_block = script[script.index("▶ Run release package quality gate") :]
    quality_block = quality_block.split("python @qualityArgs", 1)[0]
    assert "validate_weekly_release_package_quality.py" in quality_block
    assert "--fail-on-missing-geo" in quality_block


def test_openclaw_publish_wrapper_points_release_guard_at_sanji_queue():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    guard_block = script[script.index('Invoke-RunStep "Run release guard against candidate API package"') :]
    guard_block = guard_block.split('Invoke-RunStep "Bake CloudRun deploy context"', 1)[0]
    assert 'Test-SanjiClientSourceMode -Mode $SourceMode' in guard_block
    assert "$script:SanjiRunQueuePath" in guard_block
    assert "$SanjiLatestExportRoot" in guard_block
    assert '"-DailyQueueDir"' in guard_block


def test_weekly_release_guard_fails_current_package_on_missing_geo():
    guard = (
        Path(os.environ.get("USERPROFILE", r"C:\Users\pc"))
        / ".codex"
        / "skills"
        / "huaidj-weekly-release-guardian"
        / "scripts"
        / "check_weekly_release_guard.ps1"
    ).read_text(encoding="utf-8")

    assert "validate_weekly_release_package_quality.py" in guard
    assert "current_package_quality_gate" in guard
    assert "--require-internal-posters" in guard
    assert "--fail-on-missing-geo" in guard


def test_weekly_pipeline_applies_confirmed_venue_locks_before_strict_field_audit():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    assert "apply_weekly_confirmed_venue_locks.py" in script
    assert "Step 4.5: Repair duplicate/conflicting release rows" in script
    repair_block = script[script.index('Invoke-Step "Step 4.5: Repair duplicate/conflicting release rows"') :]
    repair_block = repair_block.split("# Gate 检查", 1)[0]
    assert "--api-only" in repair_block
    assert repair_block.index("$CONFIRMED_VENUE_LOCK_SCRIPT") < repair_block.index(
        "audit_weekly_lineup_address_time.py"
    )


def test_openclaw_publish_wrapper_applies_confirmed_venue_locks_before_release_validators():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "apply_weekly_confirmed_venue_locks.py" in script
    assert 'Invoke-RunStep "Apply confirmed venue geo locks"' in script
    assert "--api-only" in script
    assert script.index('Invoke-RunStep "Apply confirmed venue geo locks"') < script.index(
        'Invoke-RunStep "Run strict release validators"'
    )


def test_openclaw_publish_wrapper_strict_geocodes_missing_geo_before_release_validators():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "repair_weekly_current_resource_fields.py" in script
    assert "Get-MissingGeoItemIds" in script
    assert 'Invoke-RunStep "Repair missing-geo resource fields from verified history"' in script
    resource_block = script[
        script.index('Invoke-RunStep "Repair missing-geo resource fields from verified history"') :
    ]
    resource_block = resource_block.split('Invoke-RunStep "Strict geocode missing venue coordinates"', 1)[0]
    assert "--no-registry-update" in resource_block
    assert "--only-item-id" in resource_block
    assert "geocode_weekly_activity_places.py" in script
    assert "apply_weekly_geocodes_to_api_package.py" in script
    assert 'Invoke-RunStep "Strict geocode missing venue coordinates"' in script
    geocode_block = script[script.index('Invoke-RunStep "Strict geocode missing venue coordinates"') :]
    geocode_block = geocode_block.split('Invoke-RunStep "Run strict release validators"', 1)[0]
    assert "--only-missing-geo" in geocode_block
    assert "--provider auto" in geocode_block
    assert "accepted_geocodes.jsonl" in geocode_block
    assert script.index('Invoke-RunStep "Apply confirmed venue geo locks"') < script.index(
        'Invoke-RunStep "Repair missing-geo resource fields from verified history"'
    )
    assert script.index('Invoke-RunStep "Repair missing-geo resource fields from verified history"') < script.index(
        'Invoke-RunStep "Strict geocode missing venue coordinates"'
    )
    assert script.index('Invoke-RunStep "Strict geocode missing venue coordinates"') < script.index(
        'Invoke-RunStep "Run strict release validators"'
    )


def test_openclaw_publish_wrapper_runs_no_secret_exporter_diagnostics_before_source_build():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "diagnose_weekly_exporter_session.py" in script
    assert "manage_weekly_exporter_auth.py" in script
    assert "diagnose_weekly_exporter_qr_endpoint.py" in script
    assert "Build weekly exporter auth recovery preflight (pre-build)" in script
    assert "--redacted-auth-probe" in script
    assert "--qr-endpoint-diagnostic" in script
    assert "weekly_exporter_qr_endpoint_diagnostic.json" in script
    assert script.index("Diagnose weekly exporter session (redacted-auth-probe, pre-build)") < script.index(
        "Build daily source package from selected source queue"
    )
    assert script.index("Diagnose weekly exporter QR endpoint (no-secret, pre-build)") < script.index(
        "Build daily source package from selected source queue"
    )
    assert script.index("Build weekly exporter auth recovery preflight (pre-build)") < script.index(
        "Build daily source package from selected source queue"
    )


def test_openclaw_publish_wrapper_syncs_mptext_runtime_cache_before_source_build_without_printing_key():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "function Sync-MptextAuthEnvFromRuntimeCache" in script
    assert ".mptext-data\\kv\\auth-key-current.json" in script
    assert "MPTEXT_AUTH_KEY" in script
    assert "Get-ShortSecretHash" in script
    assert "hash=$newHash" in script
    assert "key=$cachedKey" not in script
    assert script.index("Sync-MptextAuthEnvFromRuntimeCache") < script.index(
        "Diagnose weekly exporter session (redacted-auth-probe, pre-build)"
    )
    assert script.index("Sync-MptextAuthEnvFromRuntimeCache") < script.index(
        "Build daily source package from selected source queue"
    )


def test_weekly_pipeline_syncs_mptext_runtime_cache_before_exporter_refresh_without_printing_key():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    assert "function Sync-MptextAuthEnvFromRuntimeCache" in script
    assert ".mptext-data\\kv\\auth-key-current.json" in script
    assert "MPTEXT_AUTH_KEY" in script
    assert "Get-ShortSecretHash" in script
    assert "hash=$newHash" in script
    assert "key=$cachedKey" not in script
    assert script.index("Sync-MptextAuthEnvFromRuntimeCache") < script.index(
        "Test-MptextAutoAuthAvailable"
    )
    assert script.index("Sync-MptextAuthEnvFromRuntimeCache") < script.index(
        "Refresh Daily Download Queue"
    )


def test_weekly_pipeline_clears_stale_same_output_workers_before_retrying_locked_output_dir_delete():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    assert "function Stop-StaleOutputWritersForPath" in script
    assert "Get-CimInstance Win32_Process" in script
    assert '@("python.exe", "py.exe") -contains $_.Name' in script
    assert "enrich_weekly_activity_pack_with_deepseek.py" in script
    assert "build_weekly_activity_miniprogram_api.py" in script
    assert "Stop-ProcessTree -ProcessId" in script
    assert "Output dir is locked; checking for stale same-output workers" in script
    assert "Output dir still locked after stale-worker cleanup" in script
    reset = script[script.index("function Reset-OutputDir") : script.index("function Stop-ProcessTree")]
    assert "Remove-Item -LiteralPath $Path -Recurse -Force" in reset
    assert "Stop-StaleOutputWritersForPath -Path $Path" in reset
    assert reset.index("Stop-StaleOutputWritersForPath -Path $Path") < reset.rindex(
        "Remove-Item -LiteralPath $Path -Recurse -Force"
    )


def test_weekly_pipeline_stops_stale_daily_prefetch_writer_before_step0_refresh():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    step0 = script[script.index('Invoke-Step "Step 0: Refresh Daily Download Queue') :]
    step0 = step0.split("# ─── Step 1:", 1)[0]
    assert "Stop-StaleOutputWritersForPath -Path $DEFAULT_DAILY_PREFETCH_DIR" in step0
    assert step0.index("Stop-StaleOutputWritersForPath -Path $DEFAULT_DAILY_PREFETCH_DIR") < step0.index(
        '& $PythonExecutable "$REFRESH_PREFETCH_SCRIPT" @prefetchArgs'
    )


def test_daily_runner_and_weekly_pipeline_use_sanji_desktop_client_source_mode():
    weekly = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")
    sanji_scheduled = (ROOT / "run_sanji_desktop_recent_export.ps1").read_text(encoding="utf-8")

    assert '[ValidateSet("docker_exporter", "sanji_desktop_client", "sanji_desktop_rss")]' in weekly
    assert '[string]$SourceMode = "sanji_desktop_client"' in weekly
    assert 'Test-SanjiClientSourceMode -Mode $SourceMode' in weekly
    assert "SourceMode=sanji_desktop_client; Sanji 1.1.x native client snapshot selected" in weekly
    assert "export_sanji_desktop_recent_articles.py" in weekly
    assert "--write-prefetch-queue" in weekly
    assert "Refresh Sanji Desktop RSS Queue" in weekly
    assert "Build Source Queue" in weekly
    assert '[ValidateSet("docker_exporter", "sanji_desktop_client", "sanji_desktop_rss")]' in runner
    assert '[string]$SourceMode = "sanji_desktop_client"' in runner
    assert "SourceMode = $SourceMode" in runner
    assert "Skip legacy 17300 exporter auth/QR diagnostics for Sanji source mode" in runner
    assert "sanji_desktop_rss is a compatibility alias only" in runner
    assert 'E:\\公众号\\sanji-daily-export"' in runner
    assert '"latest_summary.json"' in runner
    assert '"latest_queue.jsonl"' in runner
    assert "audit_weekly_sanji_queue_package_gap.py" in runner
    assert "blocked_on_sanji_queue_package_gap" in runner
    assert "function Update-ApiManifestSourceContract" in runner
    assert "function Write-Utf8NoBomText" in runner
    assert "System.Text.UTF8Encoding($false)" in runner
    assert "function Assert-SanjiLatestExportReady" in runner
    assert "Freeze Sanji source snapshot before build" in runner
    assert "sanji_latest_export_ready.json" in runner
    assert "copied_into_daily_queue_pointer = $false" in runner
    assert "sanji_source_snapshot" in runner
    assert "frozen_run_snapshot_created = $true" in runner
    assert "$script:SanjiRunQueuePath" in runner
    assert "$script:SanjiRunSummaryPath" in runner
    assert "run_snapshot_queue_path" in runner
    assert 'Add-Member -NotePropertyName "source_queue_path"' in runner
    assert "sanji_source_queue_path" in runner
    assert "sanji_source_stays_on_e_drive = $true" in runner
    assert "E:\\weekly_activity_pipeline\\longrun" in runner
    assert "D:\\downstream_results\\stage7_rewrite\\longrun" not in runner
    assert "$SanjiLatestQueuePath" in runner
    assert "$SanjiLatestSummaryPath" in runner
    assert "Sanji refreshed queue row count mismatch" in runner
    assert "sanji_source_contract" in runner
    assert "sanji_wechat_client.v1" in runner
    assert "full_scope_sync_completed" in runner
    assert "credential_gate_passed" in runner
    assert "direct_rss_feed_fetch must stay false for weekly publish" in runner
    assert "sanji_db_snapshot_export must stay true" in runner
    assert "sanji_desktop_refresh_invoked must stay true before snapshot export" in runner
    assert "--write-prefetch-queue" in sanji_scheduled
    assert "SANJI_LATEST_PREFETCH_QUEUE" in weekly
    assert "Using Sanji latest prefetch queue on E" in weekly
    assert "E:\\weekly_activity_pipeline\\longrun" in weekly
    assert "D:\\downstream_results\\stage7_rewrite\\longrun" not in weekly
    assert "--source-queue" in weekly
    assert "$miniprogramApiArgs += $PrefetchQueue" in weekly
    assert '$SANJI_OVERVIEW_PREFETCH_JSON = "$SANJI_LATEST_EXPORT_ROOT\\latest_club_overviews.json"' in weekly
    assert '-not (Test-SanjiClientSourceMode -Mode $SourceMode)' in weekly
    assert "Sanji source mode keeps exporter loss-chain audit report-only" in weekly
    assert "--lookback-days 31" in sanji_scheduled
    assert "--body-text-limit 8000" in sanji_scheduled
    assert "export_club_overviews_from_sanji.py" in sanji_scheduled
    assert "latest_club_overviews.json" in sanji_scheduled
    assert "OverviewMiniProgramJsPath" not in sanji_scheduled
    assert "apps\\weekly_activity_miniprogram\\data\\club_overviews.js" not in sanji_scheduled
    assert "--out-js" not in sanji_scheduled
    assert "export_club_overviews_from_sanji.py" in weekly
    assert "latest_club_overviews.json" in weekly
    assert "SANJI_OVERVIEW_MINIPROGRAM_JS" not in weekly
    assert "apps\\weekly_activity_miniprogram\\data\\club_overviews.js" not in weekly
    assert '"--out-js",' not in weekly
    assert "Step 4.1: Attach club overview online artifact" in weekly
    assert '"$API_DIR\\club_overviews.json"' in weekly
    assert "club_overviews.v1" in weekly
    assert "$crossSourceAuditExit = $LASTEXITCODE" in weekly
    assert "Cross-source strict audit failed with exit code" in weekly


def test_openclaw_publish_freezes_one_sanji_snapshot_before_any_build_reads():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    freeze_label = 'Invoke-RunStep "Freeze Sanji source snapshot before build"'
    build_label = 'Invoke-RunStep "Build daily source package from selected source queue"'
    assert freeze_label in runner
    assert runner.index(freeze_label) < runner.index(build_label)
    assert runner.count("Assert-SanjiLatestExportReady") == 2  # function declaration + one call
    assert "Use frozen Sanji source snapshot for manifest and coverage gates" in runner


def test_openclaw_publish_can_resume_an_explicit_frozen_sanji_snapshot():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert '[string]$SanjiSourceSnapshotDir = ""' in runner
    assert "$usingProvidedSanjiSnapshot" in runner
    assert "$SanjiLatestExportRoot = (Resolve-Path -LiteralPath $SanjiSourceSnapshotDir).Path" in runner
    assert "provided_frozen_snapshot" in runner


def test_openclaw_run_step_initializes_native_exit_code_for_pure_powershell_steps():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")
    invoke_step = runner[runner.index("function Invoke-RunStep") : runner.index("function Assert-NativeSuccess")]

    assert "$global:LASTEXITCODE = 0" in invoke_step
    assert invoke_step.index("$global:LASTEXITCODE = 0") < invoke_step.index("& $Body")


def test_openclaw_publish_wrapper_mirrors_sanji_contract_to_manifest_top_level():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")
    block = runner[runner.index("function Update-ApiManifestSourceContract") :]
    block = block.split("function Get-ShortSecretHash", 1)[0]

    assert '"sanji_source_contract"' in block
    assert '"direct_rss_feed_fetch"' in block
    assert '"sanji_db_snapshot_export"' in block
    assert '"sanji_desktop_refresh_invoked"' in block
    assert '"sanji_latest_summary_path"' in block
    assert '"sanji_snapshot_db_path"' in block


def test_incremental_merge_preserves_sanji_manifest_source_contract_fields():
    script = (ROOT / "scripts" / "merge_weekly_incremental_api_package.py").read_text(encoding="utf-8")
    block = script[script.index("for source_contract_key in (") :]
    block = block.split("window_merge = merge_manifest_window", 1)[0]

    for key in (
        "source_mode",
        "source_queue_path",
        "sanji_source_contract",
        "direct_rss_feed_fetch",
        "sanji_db_snapshot_export",
        "sanji_desktop_refresh_invoked",
        "sanji_latest_summary_path",
        "sanji_snapshot_db_path",
        "source_contract_attached_at",
    ):
        assert key in block


def test_backend_bake_deploy_cannot_refresh_miniprogram_disaster_seed():
    repo_root = ROOT.parents[1]
    script = (repo_root / "services" / "weekly_activity_cloudrun" / "scripts" / "bake_and_deploy.py").read_text(
        encoding="utf-8"
    )
    bake_block = script[script.index("def bake_data(") :]
    bake_block = bake_block.split("def validate_stage7_atlas", 1)[0]

    assert "refresh_offline_snapshot" not in script
    assert '"--refresh-offline-snapshot"' not in script
    assert "generate_offline_snapshot.py" not in script
    assert "regenerate_miniprogram_offline_snapshot" not in bake_block
    assert "MINIPROGRAM_DIR" not in bake_block
    assert "mini-program disaster seed unchanged" in bake_block
    assert "online API + persisted last-good cache carry activity updates" in bake_block


def test_offline_snapshot_generator_keeps_small_first_launch_seed_default():
    script = (ROOT / "scripts" / "generate_offline_snapshot.py").read_text(encoding="utf-8")

    assert "default=55" in script
    assert "0 means full current_release" in script
    assert '"--confirm-disaster-seed-update"' in script
    assert "ordinary backend activity releases must not run this tool" in script


def test_miniprogram_upload_carries_but_never_regenerates_disaster_seed():
    repo_root = ROOT.parents[1]
    script = (
        repo_root / "apps" / "weekly_activity_miniprogram" / "scripts" / "upload_native_windows.ps1"
    ).read_text(encoding="utf-8")

    assert "frontend code upload; activity data stays online" in script
    assert '$SourceOfflineSeed = Join-Path $ProjectDir "utils\\offlineSnapshot.js"' in script
    assert '$UploadOfflineSeed = Join-Path $UploadProjectDir "utils\\offlineSnapshot.js"' in script
    assert "Get-FileHash -LiteralPath $SourceOfflineSeed -Algorithm SHA256" in script
    assert "Get-FileHash -LiteralPath $UploadOfflineSeed -Algorithm SHA256" in script
    assert "Upload staging mutated offlineSnapshot.js" in script
    assert "generate_offline_snapshot.py" not in script

    devtools_script = (
        repo_root / "apps" / "weekly_activity_miniprogram" / "scripts" / "upload_devtools_cli_windows.ps1"
    ).read_text(encoding="utf-8")
    assert "WeChat DevTools CLI" in devtools_script
    assert '"upload",' in devtools_script
    assert '"--project", $UploadProjectDir' in devtools_script
    assert '"--version", $Version' in devtools_script
    assert '"--info-output", $InfoOutput' in devtools_script
    assert 'HUAIDJ_CI_STAGING_ROOT' in devtools_script
    assert 'F:\\DevData\\HuaidjRuntime\\state\\staging\\wechat-devtools' in devtools_script
    assert 'WECHAT_DEVTOOLS_PROFILE_ROOT' in devtools_script
    assert '$env:USERPROFILE = $DevToolsProfileRoot' in devtools_script
    assert 'islogin --project $UploadProjectDir' in devtools_script
    assert '"login"\\s*:\\s*true' in devtools_script
    assert '$SourceOfflineSeed = Join-Path $ProjectDir "utils\\offlineSnapshot.js"' in devtools_script
    assert "Upload staging mutated offlineSnapshot.js" in devtools_script
    assert "generate_offline_snapshot.py" not in devtools_script


def test_openclaw_publish_wrapper_requires_small_sanji_gap_missing_rows():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    gap_block = runner[runner.index("▶ Run Sanji source coverage gate") :]
    gap_block = gap_block.split("$sanjiGapExitCode = $LASTEXITCODE", 1)[0]
    assert "audit_weekly_sanji_queue_package_gap.py" in runner
    assert "--max-missing 0" in gap_block


def test_openclaw_publish_wrapper_uses_frozen_sanji_snapshot_for_build_and_gap_audit():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "Copy-Item -LiteralPath $sourceQueuePath -Destination $snapshotQueuePath -Force" in runner
    assert "Copy-Item -LiteralPath $sourceSummaryPath -Destination $snapshotSummaryPath -Force" in runner
    build_block = runner[runner.index('Invoke-RunStep "Build daily source package from selected source queue"') :]
    build_block = build_block.split('Invoke-RunStep "Merge daily candidate into current full API package"', 1)[0]
    assert "$pipelineArgs.PrefetchQueue = $sanjiQueueForPipeline" in build_block
    assert "$script:SanjiRunQueuePath" in build_block
    source_material_block = runner[runner.index("▶ Build aggregate-child poster OCR source material preflight") :]
    source_material_block = source_material_block.split("▶ Build weekly exporter freshness preflight", 1)[0]
    assert "$sanjiQueueForSourceMaterial" in source_material_block
    assert "$script:SanjiRunQueuePath" in source_material_block
    gap_block = runner[runner.index("▶ Run Sanji source coverage gate") :]
    gap_block = gap_block.split("$sanjiGapExitCode = $LASTEXITCODE", 1)[0]
    assert "$sanjiQueueForGapAudit" in gap_block
    assert "$script:SanjiRunQueuePath" in gap_block


def test_weekly_poster_cloudbase_cache_defaults_to_e_drive():
    migrator = (ROOT / "scripts" / "migrate_weekly_public_posters_to_cloudbase.py").read_text(encoding="utf-8")
    review_queue = (ROOT / "scripts" / "build_weekly_main_poster_mimo_review_queue.py").read_text(encoding="utf-8")

    assert "E:/weekly_activity_pipeline/longrun/weekly_poster_cloudbase_cache" in migrator
    assert "D:/downstream_results/stage7_rewrite/longrun/weekly_poster_cloudbase_cache" not in migrator
    assert "E:/weekly_activity_pipeline/longrun/weekly_poster_cloudbase_cache" in review_queue
    assert "D:/downstream_results/stage7_rewrite/longrun/weekly_poster_cloudbase_cache" not in review_queue


def test_current_activity_pipeline_defaults_do_not_write_longrun_to_d_drive():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")
    weekly = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")
    queue_builder = (ROOT / "scripts" / "build_weekly_activity_queue_from_downloads.py").read_text(
        encoding="utf-8"
    )
    freshness = (ROOT / "scripts" / "build_weekly_exporter_freshness_preflight.py").read_text(
        encoding="utf-8"
    )
    refresh_validator = (ROOT / "scripts" / "validate_weekly_daily_queue_refresh.py").read_text(
        encoding="utf-8"
    )
    prefect_flow = (ROOT / "prefect" / "huaidj_weekly_flow.py").read_text(encoding="utf-8")
    ticket_eval = (ROOT / "scripts" / "evaluate_weekly_ticketing_strategies.mjs").read_text(
        encoding="utf-8"
    )

    e_queue = r"E:\weekly_activity_pipeline\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE"
    d_longrun = r"D:\downstream_results\stage7_rewrite\longrun"

    assert '$Longrun = "E:\\weekly_activity_pipeline\\longrun"' in runner
    assert '$LONGRUN = "E:\\weekly_activity_pipeline\\longrun"' in weekly
    assert "E:\\weekly_activity_pipeline\\longrun" in prefect_flow
    assert e_queue in queue_builder
    assert e_queue + r"\summary.json" in freshness
    assert e_queue + r"\summary.json" in refresh_validator
    assert "E:\\\\weekly_activity_pipeline\\\\longrun\\\\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE" in ticket_eval
    assert "/mnt/e/weekly_activity_pipeline/longrun/LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE" in queue_builder

    for text in (runner, weekly, queue_builder, freshness, refresh_validator, prefect_flow, ticket_eval):
        assert d_longrun not in text


def test_incremental_merge_carries_incremental_source_queue_path():
    merger = (ROOT / "scripts" / "merge_weekly_incremental_api_package.py").read_text(encoding="utf-8")

    source_contract_tuple = merger[
        merger.index("for source_contract_key in") : merger.index("window_merge = merge_manifest_window")
    ]
    assert '"source_queue_path"' in source_contract_tuple


def test_sanji_rss_fast_watch_skips_sanji_export_after_recent_successful_publish():
    watcher = (ROOT / "run_huaidj_sanji_rss_fast_watch.ps1").read_text(encoding="utf-8")

    assert "[int]$RecentPublishCooldownMinutes = 45" in watcher
    assert "function Get-RecentSuccessfulPublishSummary" in watcher
    assert "openclaw_weekly_daily_publish_summary.json" in watcher
    assert "cloudrun_deploy_executed" in watcher
    assert "skip_recent_successful_publish_cooldown" in watcher
    assert "sanji_export_executed = $false" in watcher
    assert watcher.index("Get-RecentSuccessfulPublishSummary -CooldownMinutes") < watcher.index(
        "& pwsh -NoProfile -ExecutionPolicy Bypass -File $ExportScript"
    )


def test_sanji_gap_audit_accounts_nested_review_risk_flags():
    namespace = runpy.run_path(str(ROOT / "scripts" / "audit_weekly_sanji_queue_package_gap.py"))

    reason = namespace["row_accounted_disposition"](
        {
            "poster_selection_evidence": {
                "risk_flags": ["missing_lineup_visible"],
            },
        },
        source_name="weekly_activity_recommendation_review_candidates.jsonl",
    )

    assert reason == "review_flag:missing_lineup_visible"


def test_daily_runner_and_weekly_pipeline_default_to_online_qwen_vl_extraction():
    weekly = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert '$env:PYTHONUTF8 = "1"' in weekly
    assert '$env:PYTHONIOENCODING = "utf-8"' in weekly
    assert 'GetEnvironmentVariable("HUAIDJ_PYTHON", "User")' in weekly
    assert 'hermes-agent\\venv\\Scripts\\python.exe' in weekly
    assert '& $PythonExecutable @vlArgs' in weekly
    assert '$env:PYTHONUTF8 = "1"' in runner
    assert '[ValidateSet("legacy_ocr", "vl_direct_qwen")]' in weekly
    assert '[string]$PosterExtractionMode = "vl_direct_qwen"' in weekly
    assert "enrich_weekly_activity_pack_with_qwen_vl.py" in weekly
    assert "filter_weekly_activity_pack_for_publish_window.py" in weekly
    assert "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_VL_$WEEK_TAG" in weekly
    assert "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_PUBLISH_WINDOW_$WEEK_TAG" in weekly
    assert "Step 3: Sanji Qwen3-VL Direct Enrichment" in weekly
    assert "Step 3.65: Publish-window Candidate Filter" in weekly
    assert "--weekly-queue" in weekly
    assert "--keep-undated" in weekly
    assert "--execute" in weekly
    assert "--concurrency" in weekly
    assert '[int]$PosterVlConcurrency = 4' in weekly
    assert "ATLAS_DASHSCOPE_API_KEY" in weekly
    assert "MIMO_VISION_API_KEY" in weekly
    assert "enrich_weekly_activity_pack_with_qwen_vl.py" in weekly[
        weekly.index("function Stop-StaleOutputWritersForPath") :
    ]
    assert '[ValidateSet("legacy_ocr", "vl_direct_qwen")]' in runner
    assert '[string]$PosterExtractionMode = "vl_direct_qwen"' in runner
    assert "PosterExtractionMode = $PosterExtractionMode" in runner
    assert "PosterVlConcurrency = $PosterVlConcurrency" in runner
    assert "poster_extraction_mode = $PosterExtractionMode" in runner
    assert '$PosterExtractionMode -eq "legacy_ocr"' in runner


def test_sanji_twice_daily_publish_defaults_to_online_qwen_vl_route():
    daily = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8")

    assert '$env:PYTHONUTF8 = "1"' in daily
    assert '$env:PYTHONIOENCODING = "utf-8"' in daily
    assert '[string]$PosterExtractionMode = "vl_direct_qwen"' in daily
    assert '"-PosterExtractionMode", $PosterExtractionMode' in daily


def test_weekly_pipeline_runs_strict_aggregate_child_qwen_gate_after_expansion_before_api_build():
    weekly = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    aggregate_label = "Step 3.6: Aggregate Article Expansion Gate"
    child_qwen_label = "Step 3.62: Aggregate Child Qwen Exact Poster Gate"
    publish_window_label = "Step 3.65: Publish-window Candidate Filter"
    api_label = "Step 4: Build Mini-Program API JSON"
    assert aggregate_label in weekly
    assert child_qwen_label in weekly
    assert "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_AGGREGATE_CHILD_VL_$WEEK_TAG" in weekly
    assert '"--only-aggregate-children"' in weekly
    assert '"--require-selected-poster"' in weekly
    assert '"--max-images", "$PosterVlMaxImages"' in weekly
    assert '"--limit", "$PosterVlLimit"' in weekly
    assert '"--provider", "$PosterVlProvider"' in weekly
    assert '"--model", "$PosterVlModel"' in weekly
    assert weekly.index(aggregate_label) < weekly.index(child_qwen_label)
    assert weekly.index(child_qwen_label) < weekly.index(publish_window_label)
    assert weekly.index(child_qwen_label) < weekly.index(api_label)


def test_weekly_pipeline_keeps_utf8_bom_for_windows_powershell_51():
    script_path = ROOT / "weekly_activity_next_week_pipeline.ps1"

    assert script_path.read_bytes().startswith(b"\xef\xbb\xbf")


def test_openclaw_publish_repairs_final_merged_source_policy_before_external_writes():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert '$SourcePolicyRepairScript = Join-Path $Scripts "repair_weekly_api_package_for_source_policy.py"' in runner
    repair_label = 'Invoke-RunStep "Repair final merged package source policy"'
    assert repair_label in runner
    repair_block = runner[runner.index(repair_label) :]
    assert "python $SourcePolicyRepairScript" in repair_block
    assert '"--api-dir", $ApiDir' in repair_block
    assert '"--source-policy", (Join-Path $Stage7 "registries\\weekly_sanji_source_policy.json")' in repair_block
    assert '"--report", (Join-Path $RunReportDir "source_policy_package_repair.json")' in repair_block
    assert runner.index('Invoke-RunStep "Repair soft lineup/address/time fields"') < runner.index(repair_label)
    assert runner.index(repair_label) < runner.index('Invoke-RunStep "Apply confirmed venue geo locks"')
    assert runner.index(repair_label) < runner.index('"Migrate public weekly posters into CloudBase storage"')
    assert runner.index(repair_label) < runner.index('Write-Host "▶ Run release package quality gate"')


def test_sanji_status_sync_preserves_ordered_dictionary_mutations():
    daily = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8")

    assert "return [ordered]@{" in daily
    assert daily.count("[System.Collections.IDictionary]$Status") >= 3
    assert "[hashtable]$Status" not in daily


def test_sanji_twice_daily_publish_uses_source_policy_cleaned_base_floor():
    daily = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8")
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")
    runbook = (ROOT.parents[1] / "docs" / "SANJI_DAILY_TWO_A_DAY_AUTOMATION_RUNBOOK_20260620.md").read_text(
        encoding="utf-8"
    )

    assert "[int]$MinExpectedItems = 40" in daily
    assert "[int]$MinExpectedItems = 40" in runner
    assert "-MinExpectedItems 40" in runbook
    assert "source-policy-cleaned current package floor is `40` items" in runbook


def test_sanji_twice_daily_publish_requires_local_snapshot_refresh_contract():
    daily = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8")

    assert "rss_contract" in daily
    assert "direct_rss_feed_fetch" in daily
    assert "direct_rss_feed_fetch must stay false" in daily
    assert "SkipSanjiExport" in daily
    assert "validating existing latest_summary.json from Hermes precheck" in daily
    assert "sanji_db_snapshot_export" in daily
    assert "sanji_desktop_refresh_invoked" in daily
    assert "Sanji export did not prove local DB snapshot export" in daily
    assert "Sanji export did not prove Sanji Desktop renderer refresh before snapshot" in daily


def test_sanji_twice_daily_publish_uses_os_lease_without_age_based_lock_stealing():
    daily = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8")

    assert "huaidj_sanji_daily_publish_lease.v2" in daily
    assert "$stream.Lock(0, 1)" in daily
    assert "$stream.Unlock(0, 1)" in daily
    assert 'authority = "os_byte_range_lock"' in daily
    assert "owner_process_start_utc" in daily
    assert "Never delete by path after unlock" in daily
    assert "$lockExpired -or" not in daily
    assert "Remove-Item -LiteralPath $LockPath" not in daily


def test_sanji_desktop_export_wrapper_enforces_process_timeout_for_cdp_calls():
    script = (ROOT / "run_sanji_desktop_recent_export.ps1").read_text(encoding="utf-8")

    assert "function Invoke-NativeProcessWithTimeout" in script
    assert "function Stop-ProcessTree" in script
    assert "function Ensure-SanjiCdpAvailable" in script
    assert "function Test-TcpPort" in script
    assert "--remote-debugging-port=$SanjiCdpPort" in script
    assert "Sanji CDP port ready after launch" in script
    assert "Sanji is already running but CDP port" in script
    assert "Sanji CDP process timeout" in script
    assert "$jsonOk = $json.ok -eq $true" in script
    assert "Ensure-SanjiCdpAvailable" in script[script.index("function Invoke-SanjiRefresh") :]
    assert "Invoke-NativeProcessWithTimeout -FilePath \"node\"" in script
    assert "-OutputPath $RefreshLogPath" in script
    assert "-OutputPath $FetchLogPath" in script
    assert "function Acquire-SanjiExportLock" in script
    assert "Global\\HUAIDJ_SANJI_DESKTOP_RECENT_EXPORT_LOCK" in script
    assert "sanji_desktop_recent_export.lock" in script
    assert "function Release-SanjiExportLock" in script
    assert "Acquire-SanjiExportLock" in script[script.index("try {") :]
    assert "Release-SanjiExportLock" in script[script.index("} finally {") :]


def test_sanji_desktop_export_auto_resumes_token_expired_sync_once():
    wrapper = (ROOT / "run_sanji_desktop_recent_export.ps1").read_text(encoding="utf-8")
    cdp = (ROOT / "scripts" / "sanji_desktop_cdp_control.mjs").read_text(encoding="utf-8")

    assert "[int]$SanjiSyncResumeAttempts = 1" in wrapper
    assert "function Get-SanjiPhaseError" in wrapper
    assert "perAccount" in wrapper
    assert '"--sync-resume-attempts", [string]$SanjiSyncResumeAttempts' in wrapper
    assert '"--completion-ledger", $SanjiCompletionLedgerPath' in wrapper
    assert "token_expired" in cdp
    assert 'expressionFor("resume-sync", accountArgs)' in cdp
    assert 'if (args.action === "resume-sync") output.final = await waitForIdle(client, "sync"' in cdp


def test_outer_daily_wrapper_can_resume_an_existing_cross_day_sanji_cycle():
    daily = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8")

    assert '[string]$SanjiSyncCycleId = ""' in daily
    assert '[string]$SanjiCompletionLedgerPath = ""' in daily
    assert "if ([string]::IsNullOrWhiteSpace($SanjiSyncCycleId))" in daily
    assert "-SanjiSyncCycleId $SanjiSyncCycleId" in daily
    assert "-SanjiCompletionLedgerPath $SanjiCompletionLedgerPath" in daily
    assert "sanji_sync_cycle_id = $SanjiSyncCycleId" in daily
    assert "sanji_completion_ledger_path = $SanjiCompletionLedgerPath" in daily


def test_sanji_cdp_control_treats_existing_task_as_waitable_state():
    script = (ROOT / "scripts" / "sanji_desktop_cdp_control.mjs").read_text(encoding="utf-8")

    assert "isExistingTaskError" in script
    assert "already_running" in script
    assert "JSON.stringify({ ...options, action })" in script
    assert 'waitForIdle(client, "sync"' in script
    assert 'waitForIdle(client, "fetch"' in script


def test_sanji_contract_audit_tracks_renderer_refresh_and_epoch_freshness_contract():
    audit = (ROOT / "scripts" / "audit_huaidj_sanji_hermes_contract.py").read_text(encoding="utf-8")

    assert "run_sanji_desktop_recent_export.ps1" in audit
    assert "sanji_db_snapshot_export" in audit
    assert "direct_rss_feed_fetch must stay false" in audit
    assert "-SkipSanjiExport" in audit
    assert "FORBIDDEN_SANJI_SOURCE_CLAIMS" in audit
    assert "FORBIDDEN_DOC_CLAIMS" in audit
    assert "STALE_HERMES_HOME_PATTERN" in audit
    assert "Sanji publish wrapper stays on E drive" in audit
    assert "Sanji weekly pipeline outputs stay on E drive" in audit
    assert "doc Hermes home is not agent root" in audit
    assert "HUAIDJ Sanji 登录授权提醒" in audit
    assert "huaidj/sanji_login_reminder.py" in audit
    assert "every 2880m" in audit
    assert "HUAIDJ 活动包/API TG Monitor" in audit
    assert "huaidj/package_api_tg_status.py" in audit
    assert "Hermes job deliver {expected_deliver}" in audit
    assert audit.count('"deliver": "telegram"') >= 6


def test_sanji_docs_do_not_restore_direct_rss_source_truth():
    integration = (ROOT.parents[1] / "docs" / "SANJI_DESKTOP_DAILY_PIPELINE_INTEGRATION.md").read_text(
        encoding="utf-8"
    )
    current_runtime = (ROOT.parents[1] / "docs" / "current-runtime.md").read_text(encoding="utf-8")
    runbook = (ROOT.parents[1] / "docs" / "SANJI_DAILY_TWO_A_DAY_AUTOMATION_RUNBOOK_20260620.md").read_text(
        encoding="utf-8"
    )
    cheap_plan = (ROOT.parents[1] / "docs" / "HUAIDJ_SANJI_HERMES_WEEKLY_CHEAP_PLAN_20260629.md").read_text(
        encoding="utf-8"
    )

    assert "Sanji direct RSS package remained the source of truth" not in integration
    assert "direct_rss_feed_fetch=true" not in integration
    assert "sanji_direct_rss_feed_fetch=true" not in current_runtime
    assert "Hermes root defaults to\n  `C:\\Users\\pc\\AppData\\Local\\hermes\\hermes-agent`" not in runbook
    assert "Hermes home defaults to `C:\\Users\\pc\\AppData\\Local\\hermes`" in runbook
    assert "This is the active production contract after the 2026-06-30 cadence update." not in cheap_plan
    assert "Superseded on 2026-07-05" in cheap_plan
    assert "HUAIDJ Sanji Fri 20:10" in cheap_plan
    assert "HUAIDJ Coverage Audit Fri 21:40" in cheap_plan


def test_sanji_hermes_installer_uses_wed_fri_snapshot_contract():
    installer = (ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py").read_text(encoding="utf-8")
    audit = (ROOT / "scripts" / "audit_huaidj_sanji_hermes_contract.py").read_text(encoding="utf-8")

    assert "HUAIDJ Sanji Wed 21:10" in installer
    assert "HUAIDJ Sanji Fri 20:10" in installer
    assert "10 21 * * 3" in installer
    assert "10 20 * * 5" in installer
    assert "HUAIDJ Coverage Audit Fri 21:40" in installer
    assert "40 21 * * 5" in installer
    assert "HUAIDJ Sanji 登录授权提醒" in installer
    assert "huaidj/sanji_login_reminder.py" in installer
    assert "every 2880m" in installer
    assert "公众号登录授权提醒" in installer
    assert "HUAIDJ 活动包/API TG Monitor" in installer
    assert "huaidj/package_api_tg_status.py" in installer
    assert "report_huaidj_package_api_tg_status.py" in installer
    assert '"deliver": "telegram"' in installer
    assert installer.count('"deliver": "telegram"') >= 6
    assert "*/30 8-23 * * *" in installer
    assert "huaidj/sanji_publish_afternoon.py" in installer
    assert "run_sanji_desktop_recent_export.ps1" in installer
    assert "-SkipSanjiExport" in installer
    assert "-DetectOnly" in installer
    assert "SCRIPT_CONTRACT_TOKENS" in installer
    assert "contract_ok" in installer
    assert "LEGACY_JOB_NAMES" in installer
    assert "HUAIDJ Sanji Fri 16:10" in installer
    assert "HUAIDJ Coverage Audit Fri 17:40" in installer
    assert '"HUAIDJ Sanji Publish Noon": {' not in installer
    assert '"HUAIDJ Sanji Publish Evening": {' not in installer
    assert '"HUAIDJ Sanji Wed 21:10": {' in installer
    assert '"HUAIDJ Sanji Fri 20:10": {' in installer
    assert installer.count('"deliver": "telegram"') >= 8
    assert '"HUAIDJ Atlas v2 Sanji Import Nightly"' in audit
    assert "ALLOWED_EXTRA_HERMES_JOBS" in audit


def test_sanji_hermes_installer_templates_are_valid_python():
    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")

    for rel_path, template in namespace["SCRIPT_TEMPLATES"].items():
        ast.parse(template, filename=rel_path)


def _exec_hermes_template(template: str) -> dict:
    namespace = {"__name__": "__test__"}
    exec(compile(template, "<hermes-template>", "exec"), namespace)
    return namespace


def test_sanji_publish_template_returns_failed_child_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HUAIDJ_REPO", str(tmp_path / "repo"))
    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")
    launcher = _exec_hermes_template(namespace["SCRIPT_TEMPLATES"]["huaidj/sanji_publish_afternoon.py"])
    return_codes = iter((0, 7))

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, next(return_codes))

    monkeypatch.setattr(launcher["subprocess"], "run", fake_run)
    assert launcher["main"]() == 7


def test_atlas_template_returns_worker_exit_and_cleans_lock(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    orchestrator = repo / "tools" / "atlas_rebuild" / "run_atlas_v2_sanji_import.py"
    orchestrator.parent.mkdir(parents=True)
    orchestrator.write_text("raise SystemExit(0)\n", encoding="utf-8")
    hermes_home = tmp_path / "hermes"
    report_root = tmp_path / "reports"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("HUAIDJ_REPO", str(repo))
    monkeypatch.setenv("HUAIDJ_PYTHON", os.sys.executable)
    monkeypatch.setenv("HUAIDJ_REPORT_ROOT", str(report_root))
    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")
    launcher = _exec_hermes_template(namespace["SCRIPT_TEMPLATES"]["huaidj/atlas_v2_sanji_import_nightly.py"])
    assert launcher["LOG_DIR"] == report_root / "atlas_v2_import"
    assert launcher["LOCK_PATH"] == report_root / "_locks" / "atlas_v2_import.lock"
    return_codes = iter((0, 7))

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, next(return_codes))

    monkeypatch.setattr(launcher["subprocess"], "run", fake_run)
    assert launcher["main"]() == 7
    assert launcher["LOCK_PATH"].exists()
    first = launcher["_acquire_lock"](tmp_path / "first.log")
    assert first is not None
    assert launcher["_acquire_lock"](tmp_path / "second.log") is None
    launcher["_release_lock"](first)
    reacquired = launcher["_acquire_lock"](tmp_path / "third.log")
    assert reacquired is not None
    launcher["_release_lock"](reacquired)


def test_atlas_template_distinguishes_noop_from_completed(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    orchestrator = repo / "tools" / "atlas_rebuild" / "run_atlas_v2_sanji_import.py"
    orchestrator.parent.mkdir(parents=True)
    orchestrator.write_text("raise SystemExit(0)\n", encoding="utf-8")
    report_root = tmp_path / "reports"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HUAIDJ_REPO", str(repo))
    monkeypatch.setenv("HUAIDJ_PYTHON", os.sys.executable)
    monkeypatch.setenv("HUAIDJ_REPORT_ROOT", str(report_root))
    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")
    launcher = _exec_hermes_template(namespace["SCRIPT_TEMPLATES"]["huaidj/atlas_v2_sanji_import_nightly.py"])
    summary_dir = tmp_path / "atlas-run"
    summary_dir.mkdir()
    summary_path = summary_dir / "run_summary.json"
    summary_path.write_text(
        json.dumps({"schema_version": "atlas_v2_sanji_import_run.v1", "status": "noop_no_new_articles"}),
        encoding="utf-8",
    )
    call_count = 0

    def fake_run(command, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            kwargs["stdout"].write(f"=== run noop_no_new_articles === summary: {summary_path}\n")
            kwargs["stdout"].flush()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher["subprocess"], "run", fake_run)
    assert launcher["main"]() == 0
    output = capsys.readouterr().out
    assert "[NOOP]" in output
    assert "[OK]" not in output


def test_installer_pauses_duplicate_active_jobs(monkeypatch, tmp_path):
    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")
    name, spec = next(iter(namespace["JOBS"].items()))
    jobs = [
        {
            "id": "newer-duplicate",
            "name": name,
            "enabled": True,
            "state": "scheduled",
            "created_at": "2026-07-18T12:00:00+08:00",
            "schedule": {"expr": spec["schedule"]},
        },
        {
            "id": "canonical-oldest",
            "name": name,
            "enabled": True,
            "state": "scheduled",
            "created_at": "2026-07-17T12:00:00+08:00",
            "schedule": {"expr": spec["schedule"]},
        },
    ]
    updates = []

    def fake_create_job(**kwargs):
        return {"id": f"created-{kwargs['name']}"}

    def fake_update_job(job_id, changes):
        updates.append((job_id, dict(changes)))
        return {"id": job_id, **changes}

    monkeypatch.setitem(
        namespace["ensure_jobs"].__globals__,
        "load_api",
        lambda *_args: (fake_create_job, lambda: list(jobs), fake_update_job),
    )
    actions = namespace["ensure_jobs"](tmp_path / "hermes", tmp_path / "runtime", True)
    target = next(action for action in actions if action.get("name") == name)
    assert target["job_id"] == "canonical-oldest"
    assert target["paused_duplicate_job_ids"] == ["newer-duplicate"]
    assert any(job_id == "canonical-oldest" and changes.get("enabled") is True for job_id, changes in updates)
    assert any(
        job_id == "newer-duplicate"
        and changes.get("enabled") is False
        and changes.get("state") == "paused"
        for job_id, changes in updates
    )


def test_monitor_template_propagates_child_and_timeout_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HUAIDJ_REPO", str(tmp_path / "repo"))
    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")
    monitor = _exec_hermes_template(namespace["SCRIPT_TEMPLATES"]["huaidj/package_api_tg_status.py"])
    monkeypatch.setattr(
        monitor["subprocess"],
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 7, stdout="", stderr="failed"),
    )
    assert monitor["main"]() == 7

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 90)

    monkeypatch.setattr(monitor["subprocess"], "run", timeout)
    assert monitor["main"]() == 124


def test_installer_replaces_detached_legacy_launcher(tmp_path):
    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")
    live_script = tmp_path / "scripts" / "huaidj" / "sanji_publish_afternoon.py"
    live_script.parent.mkdir(parents=True)
    live_script.write_text("import subprocess\nsubprocess.Popen([])\nprint('[LAUNCHED]')\n", encoding="utf-8")

    namespace["write_scripts"](tmp_path, apply=True)

    installed = live_script.read_text(encoding="utf-8")
    assert "subprocess.run(" in installed
    assert "subprocess.Popen(" not in installed
    assert "[LAUNCHED]" not in installed


def test_sanji_hermes_installer_waits_for_terminal_child_results():
    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")
    templates = namespace["SCRIPT_TEMPLATES"]
    publish = templates["huaidj/sanji_publish_afternoon.py"]
    atlas = templates["huaidj/atlas_v2_sanji_import_nightly.py"]
    monitor = templates["huaidj/package_api_tg_status.py"]

    for template in (publish, atlas):
        assert "subprocess.run(" in template
        assert "subprocess.Popen(" not in template
        assert "CREATE_NEW_PROCESS_GROUP" not in template
        assert "subprocess.DETACHED_PROCESS" not in template
        assert '["cmd.exe", "/d", "/c", "start"' not in template
        assert "[LAUNCHED]" not in template
    assert "return result_code" in publish
    assert "return result_code" in atlas
    assert "--advance-checkpoint" in atlas
    assert "No production promotion or service restart" in atlas
    assert "return int(result.returncode)" in monitor
    assert "return 2" in monitor


def test_sanji_fast_watch_propagates_finalize_failure():
    script = (ROOT / "run_huaidj_sanji_rss_fast_watch.ps1").read_text(encoding="utf-8")

    assert "$finalizeExitCode = $LASTEXITCODE" in script
    assert "if ($finalizeExitCode -ne 0)" in script
    assert "Sanji RSS finalize failed with exit code $finalizeExitCode" in script


def test_sanji_rss_fast_watch_skips_deepseek_peak_pricing_window():
    script = (ROOT / "run_huaidj_sanji_rss_fast_watch.ps1").read_text(encoding="utf-8")

    assert "[switch]$AllowDeepSeekPeakWindow" in script
    assert "Get-DeepSeekPricingWindowState" in script
    assert "skip_deepseek_peak_pricing_window" in script
    assert "09:00-12:00" in script
    assert "14:00-18:00" in script
    assert "deepseek_peak_pricing_guard" in script
    assert "publish_executed = $false" in script
    assert "cloudrun_deploy_executed = $false" in script
    assert script.index("Get-DeepSeekPricingWindowState") < script.index(
        'triggering high-quality publish'
    )


def test_sanji_aggregate_expansion_omits_blank_download_endpoint():
    weekly = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    assert "$aggregateArgs = @(" in weekly
    assert "[string]::IsNullOrWhiteSpace($AGGREGATE_DOWNLOAD_ENDPOINT)" in weekly
    assert '& $PythonExecutable "$AGGREGATE_EXPAND_SCRIPT" @aggregateArgs' in weekly
    assert "--download-endpoint $AGGREGATE_DOWNLOAD_ENDPOINT" not in weekly


def test_daily_runner_and_weekly_pipeline_keep_body_backfill_unlimited_by_default():
    weekly = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "[int]$PrefetchBodyBackfillLimit = 0" in weekly
    assert "[int]$PrefetchBodyBackfillLimit = 0" in runner
    assert "--body-backfill-limit" in weekly
    assert "PrefetchBodyBackfillLimit = $PrefetchBodyBackfillLimit" in runner


def test_queue_builder_writes_safe_body_backfill_progress_for_unlimited_runs():
    script = (ROOT / "scripts" / "build_weekly_activity_queue_from_downloads.py").read_text(encoding="utf-8")

    assert "--body-backfill-progress-every" in script
    assert "body_backfill_progress.json" in script
    assert "tmp_path = path.with_name" in script
    assert "os.replace(tmp_path, path)" in script
    assert '"schema_version": "weekly_activity_body_backfill_progress.v1"' in script
    assert '"unlimited": max(0, int(limit or 0)) == 0' in script
    assert "current_title_hash" in script
    assert "source_url" not in script[
        script.index("def write_body_backfill_progress") : script.index("def discover_latest_cookie_auth_key")
    ]
    assert 'f"unlimited={limit == 0} "' in script


def test_openclaw_publish_wrapper_generates_readiness_next_action_and_darwin_reports_on_exit():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "summarize_openclaw_weekly_daily_readiness.py" in script
    assert "build_openclaw_weekly_next_action_packet.py" in script
    assert "build_openclaw_weekly_darwin_scorecard.py" in script
    assert "function Write-OpenClawReadinessAndNextAction" in script
    assert "runtime_current_release_quality_gate.json" in script
    assert "openclaw_weekly_daily_readiness_summary.json" in script
    assert "openclaw_weekly_next_action_packet" in script
    assert "openclaw_darwin_scorecard" in script
    assert "--fallback-summary" in script
    assert "--candidate-quality" in script
    assert "--runtime-quality" in script
    assert "--darwin-scorecard" in script
    assert "--next-action-packet" in script
    assert "Rebuild OpenClaw Darwin scorecard with next-action packet" in script
    assert script.index("Write-OpenClawReadinessAndNextAction -SummaryPath $summaryPath") < script.index(
        "blocked on release package quality gate"
    )
    assert script.index("Build OpenClaw weekly next-action packet") < script.index(
        "Rebuild OpenClaw Darwin scorecard with next-action packet"
    )


def test_openclaw_cron_fallback_generates_current_release_recovery_packet_before_blocking():
    if not FALLBACK.exists():
        return
    script = FALLBACK.read_text(encoding="utf-8-sig")

    assert "function Build-CurrentReleaseRecoveryEvidence" in script
    assert "current_release_quality_recovery" in script
    assert "current_release_recovery_packet" in script
    assert "current_release_next_action_packet" in script
    assert "current_release_full_incremental_run_allowed_now" in script
    assert "current_release_darwin_scorecard" in script
    assert "build_weekly_missing_internal_poster_recovery_work_orders.py" in script
    assert "migrate_weekly_public_posters_to_cloudbase.py" in script
    assert "validate_weekly_poster_cloudbase_migration_gate.py" in script
    assert "build_weekly_poster_recovery_split_controller_packet.py" in script
    assert "build_weekly_aggregate_child_poster_ocr_recovery_tasks.py" in script
    assert "build_weekly_aggregate_child_poster_ocr_worker_contract.py" in script
    assert "build_weekly_aggregate_child_poster_ocr_execution_preflight.py" in script
    assert "build_weekly_aggregate_child_poster_ocr_controller_release_packet.py" in script
    assert "build_weekly_aggregate_child_poster_ocr_runtime_release_preflight.py" in script
    assert "build_weekly_aggregate_child_poster_ocr_source_material_preflight.py" in script
    assert "build_weekly_source_material_recovery_controller_packet.py" in script
    assert "build_weekly_source_material_recovery_runtime_release_preflight.py" in script
    assert "build_weekly_source_material_recovery_controller_release.py" in script
    assert "build_openclaw_current_release_quality_recovery_packet.py" in script
    assert "build_openclaw_weekly_next_action_packet.py" in script
    assert "build_openclaw_weekly_darwin_scorecard.py" in script
    assert "current_release_poster_ocr_task_count" in script
    assert "current_release_poster_ocr_ready_task_count" in script
    assert "current_release_poster_ocr_worker_contract_decision" in script
    assert "current_release_poster_ocr_execution_preflight_decision" in script
    assert "current_release_poster_ocr_controller_packet_decision" in script
    assert "current_release_poster_ocr_runtime_preflight_decision" in script
    assert "current_release_poster_ocr_source_material_preflight_decision" in script
    assert "current_release_poster_ocr_source_material_offline_ready_task_count" in script
    assert "current_release_poster_ocr_source_material_network_or_exporter_required_task_count" in script
    assert "current_release_source_material_controller_packet" in script
    assert "current_release_source_material_controller_decision" in script
    assert "current_release_source_material_controller_selected_task_count" in script
    assert "current_release_source_material_controller_docker_worker_allowed_now" in script
    assert "current_release_source_material_runtime_preflight_decision" in script
    assert "current_release_source_material_runtime_selected_task_count" in script
    assert "current_release_source_material_runtime_docker_worker_allowed_now" in script
    assert "current_release_source_material_runtime_full_incremental_allowed_now" in script
    assert "current_release_source_material_controller_release_decision" in script
    assert "current_release_source_material_controller_packet_release_created" in script
    assert "current_release_source_material_controller_release_created" in script
    assert "current_release_source_material_controller_release_runtime_allowed" in script
    assert "current_release_source_material_controller_release_runtime_executed" in script
    assert "--source-material-controller $CurrentReleaseSourceMaterialControllerPath" in script
    assert "--source-material-runtime-preflight $CurrentReleaseSourceMaterialRuntimePreflightPath" in script
    assert "--source-material-controller-release $CurrentReleaseSourceMaterialControllerReleasePath" in script
    assert script.index("Build current-release aggregate-child poster OCR execution preflight") < script.index(
        "Build current-release aggregate-child poster OCR controller packet"
    )
    assert script.index("Build current-release aggregate-child poster OCR controller packet") < script.index(
        "Build current-release aggregate-child poster OCR runtime release preflight"
    )
    assert script.index("Build current-release aggregate-child poster OCR runtime release preflight") < script.index(
        "Build current-release aggregate-child poster OCR source-material preflight"
    )
    assert script.index("Build current-release aggregate-child poster OCR source-material preflight") < script.index(
        "Build current-release source-material recovery controller packet"
    )
    assert script.index("Build current-release source-material recovery controller packet") < script.index(
        "Rebuild OpenClaw weekly next-action packet with source-material controller"
    )
    assert script.index("Rebuild OpenClaw weekly next-action packet with source-material controller") < script.index(
        "Build current-release source-material runtime release preflight"
    )
    assert script.index("Build current-release source-material runtime release preflight") < script.index(
        "Build current-release source-material controller release packet"
    )
    assert script.index("Build current-release source-material controller release packet") < script.index(
        "Rebuild OpenClaw Darwin scorecard for current-release recovery"
    )
    block = script.index('if (-not [bool]$summary.current_release_quality_ok)')
    evidence = script.index("Build-CurrentReleaseRecoveryEvidence", block)
    blocked = script.index('Save-Summary -Ok $true -Status "blocked_on_current_release_quality_gate"', block)
    assert evidence < blocked


def test_openclaw_publish_wrapper_treats_report_only_poster_packets_as_nonfatal():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "Poster recovery split controller packet blocked report-only" in script
    assert "Public poster upload candidate review packet blocked report-only" in script
    assert "Aggregate-child poster OCR recovery tasks blocked report-only" in script
    assert "Aggregate-child poster OCR Docker worker contract blocked report-only" in script
    assert "Aggregate-child poster OCR execution preflight blocked report-only" in script
    assert "Aggregate-child poster OCR controller release packet blocked report-only" in script
    assert "Aggregate-child poster OCR runtime release preflight blocked report-only" in script
    assert script.index("Poster recovery split controller packet blocked report-only") < script.index(
        "Build public poster upload candidate review packet"
    )
    assert script.index("Aggregate-child poster OCR execution preflight blocked report-only") < script.index(
        "Build weekly exporter freshness preflight"
    )


def test_openclaw_publish_wrapper_skips_incremental_self_merge_for_current_package_smoke():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "$resolvedCandidateApiDir = (Resolve-Path -LiteralPath $ApiDir).Path" in script
    assert "$resolvedBaseApiDir = (Resolve-Path -LiteralPath $IncrementalBaseApiDir).Path" in script
    assert "candidate API dir is the same as base current package" in script
    assert "$global:LASTEXITCODE = 0" in script
    assert script.index("$resolvedCandidateApiDir = (Resolve-Path -LiteralPath $ApiDir).Path") < script.index(
        "Candidate API package has no items"
    )


def test_openclaw_publish_wrapper_source_gate_allows_disabled_aggregate_children():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "aggregateChildDisabledByPolicy" in script
    assert "aggregate_child_parent_article" in script
    assert "agg-child-" in script


def test_openclaw_publish_wrapper_audits_public_posters_before_quality_gate_without_default_write():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "migrate_weekly_public_posters_to_cloudbase.py" in script
    assert "validate_weekly_poster_cloudbase_migration_gate.py" in script
    assert "[switch]$EnablePosterCloudBaseMigration" in script
    assert "Audit public weekly posters CloudBase migration plan" in script
    assert "Validate explicit poster CloudBase migration write gate" in script
    assert '[string]$PosterMigrationConfirmToken = ""' in script
    assert 'if ($EnablePosterCloudBaseMigration)' in script
    assert '$effectivePosterMigrationConfirmToken = $PosterMigrationConfirmToken' in script
    assert '"ENABLE_CLOUDBASE_POSTER_MIGRATION_$WeekTag"' in script
    assert '$posterMigrationArgs += "--confirm-token"' in script
    assert "$posterMigrationArgs += $effectivePosterMigrationConfirmToken" in script
    assert '$posterMigrationArgs += "--write"' in script
    assert script.index('$posterMigrationArgs += "--confirm-token"') < script.index('$posterMigrationArgs += "--write"')
    assert script.index("Audit public weekly posters CloudBase migration plan") < script.index("Run release package quality gate")
    assert '"--cloud-dir", "weekly-posters/$WeekTag"' in script


def test_openclaw_publish_wrapper_writes_failed_summary_and_nonzero_for_hard_blockers():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "function Write-PublishSummary" in script
    assert "openclaw_weekly_daily_publish_summary.v2" in script
    assert "blocked_on_cloudbase_poster_migration_write_gate" in script
    assert "poster_migration_write_gate_ready" in script
    assert "write_actions_allowed_now" in script
    assert "release_ready = $ReleaseReady" in script
    assert "-not [bool]$posterMigrationGate.execute_allowed_now" in script
    assert "[int]$posterMigrationGate.cloudbase_storage_write_allowed_count -eq 0" in script
    assert "[bool]$posterMigrationGate.boundary.report_only" in script
    assert "-Ok $false" in script
    assert "exit $qualityExitCode" in script
    assert "exit $sanjiGapExitCode" in script
    assert "exit $blockedExitCode" in script
    assert "blocked_on_release_package_quality_gate" in script
    assert script.index("blocked_on_cloudbase_poster_migration_write_gate") < script.index("blocked_on_release_package_quality_gate")


def test_openclaw_publish_wrapper_reports_actual_deploy_and_upload_execution_flags():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "$script:CloudRunDeployExecuted = $false" in script
    assert "$script:CloudRunDeployMutationUnknown = $false" in script
    assert "$script:MiniProgramUploadExecuted = $false" in script
    assert "cloudrun_deploy_executed = [bool]$script:CloudRunDeployExecuted" in script
    assert "cloudrun_deploy_mutation_unknown = [bool]$script:CloudRunDeployMutationUnknown" in script
    assert "miniprogram_upload_executed = [bool]$script:MiniProgramUploadExecuted" in script
    assert "cloudrun_deploy_executed = [bool]$DeployBackend" not in script
    assert "miniprogram_upload_executed = [bool]$UploadFrontend" not in script
    deploy_step = script[
        script.index('Invoke-RunStep "Deploy CloudRun by direct CloudBase API"') :
        script.index('Invoke-RunStep "Smoke remote CloudRun and reconcile pagination"')
    ]
    assert "Update-CloudRunDeployMutationState" in deploy_step
    assert "$script:CloudRunDeployExecuted = $true" not in deploy_step
    state_helper = script[
        script.index("function Update-CloudRunDeployMutationState") :
        script.index("function Write-RemoteRollbackPacket")
    ]
    assert 'PSObject.Properties.Name -contains "cloud_deploy_executed"' in state_helper
    assert 'PSObject.Properties.Name -contains "update_attempted"' in state_helper
    assert "$script:CloudRunDeployMutationUnknown = $true" in state_helper
    assert "$script:CloudRunDeployExecuted = [bool]$deployEvidence.safety.cloud_deploy_executed -or" in state_helper
    upload_step = script[script.index('Invoke-RunStep "Upload miniprogram developer version"') :]
    assert "pwsh -NoProfile -ExecutionPolicy Bypass" in upload_step
    assert "upload_devtools_cli_windows.ps1" in upload_step
    assert "upload_native_windows.ps1" not in upload_step
    assert "UploadFrontend requires -DevToolsSuiteSummaryPath" in script
    assert "-SuiteSummaryPath $DevToolsSuiteSummaryPath" in upload_step
    assert "-StaticPackageDir $CurrentReleasePackageDir" in upload_step
    assert "$CurrentReleasePackageDir = [System.IO.Path]::GetFullPath($IncrementalBaseApiDir)" in script
    assert "-ConfirmUpload" in upload_step
    assert 'Assert-NativeSuccess "Miniprogram developer upload"' in upload_step
    assert "$script:MiniProgramUploadExecuted = $true" in upload_step
    assert upload_step.index('Assert-NativeSuccess "Miniprogram developer upload"') < upload_step.index(
        "$script:MiniProgramUploadExecuted = $true"
    )


def test_openclaw_publish_wrapper_uses_activity_only_miniprogram_tests_for_backend_deploy():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "$ActivityOnlyBackendDeploy = [bool]($DeployBackend -and -not $UploadFrontend)" in script
    assert 'miniprogram_test_scope = $MiniProgramTestScope' in script
    assert "$activityOnlyTests = @(" in script
    assert "tests/api-static-fallback.test.cjs" in script
    assert "tests/production-data-source.test.cjs" in script
    assert "tests/page-source-routing.test.cjs" in script
    assert "tests/poster-pool.test.cjs" in script
    activity_block = script[
        script.index("if ($ActivityOnlyBackendDeploy)") :
        script.index("} else {", script.index("if ($ActivityOnlyBackendDeploy)"))
    ]
    assert "column-longform.test.cjs" not in activity_block
    assert "interview-column.test.cjs" not in activity_block
    assert "$SkipMiniProgramTests -or $ActivityOnlyBackendDeploy" in script


def test_weekly_pipeline_entity_enrichment_keeps_nonzero_exit_terminal():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    assert "function Complete-EntityEnrichmentOutput" in script
    assert "entity_enrichment_summary.json" in script
    assert "entity_enrichment_exit_override.json" in script
    assert "complete_outputs_nonzero_exit_recorded" in script
    assert "non-zero process exit remains terminal" in script
    assert "$inputCandidateLines -ne $outputCandidateLines" in script
    assert "$inputReviewLines -ne $outputReviewLines" in script
    step35 = script[
        script.index('Invoke-Step "Step 3.5: Entity Enrichment') :
        script.index("# fallback：若实体富化没有输出")
    ]
    assert "Complete-EntityEnrichmentOutput" in step35
    assert "$global:LASTEXITCODE = $entityExitCode" in step35
    assert "$global:LASTEXITCODE = 0" not in step35


def test_openclaw_publish_wrapper_builds_missing_poster_recovery_work_orders_on_quality_failure():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "build_weekly_missing_internal_poster_recovery_work_orders.py" in script
    assert "missing_internal_poster_recovery_work_orders.json" in script
    assert "Build missing internal poster recovery work orders" in script
    assert "missing_internal_poster_recovery_report" in script
    assert "--quality-report" in script
    assert "--poster-migration-report" in script
    assert "--source-url-map" in script
    assert script.index("Run release package quality gate") < script.index("Build missing internal poster recovery work orders")


def test_openclaw_publish_wrapper_builds_poster_recovery_split_controller_packet_before_ocr_tasks():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "build_weekly_poster_recovery_split_controller_packet.py" in script
    assert "poster_recovery_split_controller_packet.json" in script
    assert "Build poster recovery split controller packet" in script
    assert "poster_recovery_split_controller_packet_report" in script
    assert "--work-orders" in script
    assert "--write-gate" in script
    assert "WEEKLY_POSTER_RECOVERY_SPLIT_CONTROLLER_PACKET_$WeekTag.md" in script
    assert script.index("Build missing internal poster recovery work orders") < script.index(
        "Build poster recovery split controller packet"
    )
    assert script.index("Build poster recovery split controller packet") < script.index(
        "Build aggregate-child poster OCR recovery tasks"
    )


def test_openclaw_publish_wrapper_builds_public_poster_upload_candidate_review_packet_before_ocr_tasks():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "build_weekly_public_poster_upload_candidate_review_packet.py" in script
    assert "public_poster_upload_candidate_review_packet.json" in script
    assert "Build public poster upload candidate review packet" in script
    assert "public_poster_upload_candidate_review_packet_report" in script
    assert "--work-orders" in script
    assert "--write-gate" in script
    assert "--split-packet" in script
    assert "WEEKLY_PUBLIC_POSTER_UPLOAD_CANDIDATE_REVIEW_PACKET_$WeekTag.md" in script
    assert script.index("Build poster recovery split controller packet") < script.index(
        "Build public poster upload candidate review packet"
    )
    assert script.index("Build public poster upload candidate review packet") < script.index(
        "Build aggregate-child poster OCR recovery tasks"
    )


def test_openclaw_publish_wrapper_builds_aggregate_child_poster_ocr_recovery_tasks():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "build_weekly_aggregate_child_poster_ocr_recovery_tasks.py" in script
    assert "aggregate_child_poster_ocr_recovery_tasks.json" in script
    assert "Build aggregate-child poster OCR recovery tasks" in script
    assert "aggregate_child_poster_ocr_recovery_report" in script
    assert "--work-orders" in script
    assert "--source-url-map" in script
    assert script.index("Build missing internal poster recovery work orders") < script.index("Build aggregate-child poster OCR recovery tasks")


def test_openclaw_publish_wrapper_builds_aggregate_child_poster_ocr_worker_contract():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "build_weekly_aggregate_child_poster_ocr_worker_contract.py" in script
    assert "aggregate_child_poster_ocr_worker_contract.json" in script
    assert "Build aggregate-child poster OCR Docker worker contract" in script
    assert "aggregate_child_poster_ocr_worker_contract_report" in script
    assert "--tasks" in script
    assert "--compose" in script
    assert script.index("Build aggregate-child poster OCR recovery tasks") < script.index("Build aggregate-child poster OCR Docker worker contract")


def test_openclaw_publish_wrapper_builds_aggregate_child_poster_ocr_execution_preflight():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "build_weekly_aggregate_child_poster_ocr_execution_preflight.py" in script
    assert "aggregate_child_poster_ocr_execution_preflight.json" in script
    assert "Build aggregate-child poster OCR execution preflight" in script
    assert "aggregate_child_poster_ocr_execution_preflight_report" in script
    assert "--worker-contract" in script
    assert script.index("Build aggregate-child poster OCR Docker worker contract") < script.index("Build aggregate-child poster OCR execution preflight")


def test_openclaw_publish_wrapper_optionally_builds_aggregate_child_poster_ocr_controller_packet():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "build_weekly_aggregate_child_poster_ocr_controller_release_packet.py" in script
    assert "aggregate_child_poster_ocr_controller_release_packet.json" in script
    assert "Build aggregate-child poster OCR controller release packet" in script
    assert "aggregate_child_poster_ocr_controller_release_packet_report" in script
    assert '[string]$PosterOcrCanaryReportPath = ""' in script
    assert "--preflight" in script
    assert "--canary" in script
    assert "--max-tasks 5" in script
    assert "-not [string]::IsNullOrWhiteSpace($PosterOcrCanaryReportPath)" in script
    assert "Test-Path -LiteralPath $PosterOcrCanaryReportPath" in script
    assert "round55_frontend_adapted" not in script
    assert script.index("Build aggregate-child poster OCR execution preflight") < script.index("Build aggregate-child poster OCR controller release packet")


def test_openclaw_publish_wrapper_optionally_builds_aggregate_child_poster_ocr_runtime_preflight():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "build_weekly_aggregate_child_poster_ocr_runtime_release_preflight.py" in script
    assert "aggregate_child_poster_ocr_runtime_release_preflight.json" in script
    assert "Build aggregate-child poster OCR runtime release preflight" in script
    assert "aggregate_child_poster_ocr_runtime_release_preflight_report" in script
    assert "--execution-preflight" in script
    assert "--controller-packet" in script
    assert "--canary" in script
    assert "--max-tasks 5" in script
    assert "-not [string]::IsNullOrWhiteSpace($PosterOcrCanaryReportPath)" in script
    assert "Test-Path -LiteralPath $PosterOcrCanaryReportPath" in script
    assert script.index("Build aggregate-child poster OCR controller release packet") < script.index(
        "Build aggregate-child poster OCR runtime release preflight"
    )
