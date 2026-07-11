import ast
import os
import runpy
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
    assert '$ResumeFromVl = -not [string]::IsNullOrWhiteSpace($ResumeVlDir)' in script
    assert 'Resume from existing VL package' in script
    assert '$PACK_OCR_DIR = (Resolve-Path -LiteralPath $ResumeVlDir).Path' in script
    assert '$QUEUE_FILE = $PrefetchQueue' in script
    assert '$PACK_DIR = $PACK_OCR_DIR' in script
    assert 'Step 3.5: Entity Enrichment (dj-dataset)' in script
    assert 'Step 4: Build Mini-Program API JSON' in script


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
    assert '$SourceMode -eq "sanji_desktop_rss"' in guard_block
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
        'python "$REFRESH_PREFETCH_SCRIPT" @prefetchArgs'
    )


def test_daily_runner_and_weekly_pipeline_support_sanji_desktop_rss_source_mode():
    weekly = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")
    sanji_scheduled = (ROOT / "run_sanji_desktop_recent_export.ps1").read_text(encoding="utf-8")

    assert '[ValidateSet("docker_exporter", "sanji_desktop_rss")]' in weekly
    assert '[string]$SourceMode = "sanji_desktop_rss"' in weekly
    assert 'if ($SourceMode -eq "sanji_desktop_rss")' in weekly
    assert "SourceMode=sanji_desktop_rss; 17300/mptext aggregate download endpoint disabled" in weekly
    assert "Use -SourceMode docker_exporter for fallback" in weekly
    assert "export_sanji_desktop_recent_articles.py" in weekly
    assert "--write-prefetch-queue" in weekly
    assert "Refresh Sanji Desktop RSS Queue" in weekly
    assert "Build Source Queue" in weekly
    assert '[ValidateSet("docker_exporter", "sanji_desktop_rss")]' in runner
    assert '[string]$SourceMode = "sanji_desktop_rss"' in runner
    assert "SourceMode = $SourceMode" in runner
    assert "Skip legacy 17300 exporter auth/QR diagnostics for Sanji source mode" in runner
    assert "use -SourceMode docker_exporter for deliberate 17300 fallback" in runner
    assert 'E:\\公众号\\sanji-daily-export"' in runner
    assert '"latest_summary.json"' in runner
    assert '"latest_queue.jsonl"' in runner
    assert "audit_weekly_sanji_queue_package_gap.py" in runner
    assert "blocked_on_sanji_queue_package_gap" in runner
    assert "function Update-ApiManifestSourceContract" in runner
    assert "function Write-Utf8NoBomText" in runner
    assert "System.Text.UTF8Encoding($false)" in runner
    assert "function Assert-SanjiLatestExportReady" in runner
    assert "Validate Sanji latest export on E drive" in runner
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
    assert 'if ($SourceMode -ne "sanji_desktop_rss")' in weekly
    assert "Sanji source mode keeps exporter loss-chain audit report-only" in weekly
    assert "--lookback-days 31" in sanji_scheduled
    assert "--body-text-limit 8000" in sanji_scheduled
    assert "export_club_overviews_from_sanji.py" in sanji_scheduled
    assert "latest_club_overviews.json" in sanji_scheduled
    assert "club_overviews.js" in sanji_scheduled
    assert "--out-js" in sanji_scheduled
    assert "export_club_overviews_from_sanji.py" in weekly
    assert "latest_club_overviews.json" in weekly
    assert "club_overviews.js" in weekly


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


def test_bake_deploy_does_not_refresh_miniprogram_offline_snapshot_by_default():
    repo_root = ROOT.parents[1]
    script = (repo_root / "services" / "weekly_activity_cloudrun" / "scripts" / "bake_and_deploy.py").read_text(
        encoding="utf-8"
    )
    bake_block = script[script.index("def bake_data(") :]
    bake_block = bake_block.split("def validate_stage7_atlas", 1)[0]

    assert "refresh_offline_snapshot: bool = False" in script
    assert '"--refresh-offline-snapshot"' in script
    assert "args.refresh_offline_snapshot" in script
    assert "skip mini-program offlineSnapshot.js refresh" in script
    assert "last live API cache tracks package updates" in script
    assert bake_block.index("if refresh_offline_snapshot:") < bake_block.index("regenerate_neighborhood_bundle")


def test_offline_snapshot_generator_keeps_small_first_launch_seed_default():
    script = (ROOT / "scripts" / "generate_offline_snapshot.py").read_text(encoding="utf-8")

    assert "default=55" in script
    assert "0 means full current_release" in script


def test_openclaw_publish_wrapper_requires_small_sanji_gap_missing_rows():
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    gap_block = runner[runner.index("▶ Run Sanji source coverage gate") :]
    gap_block = gap_block.split("$sanjiGapExitCode = $LASTEXITCODE", 1)[0]
    assert "audit_weekly_sanji_queue_package_gap.py" in runner
    assert "--max-missing 5" in gap_block
    assert "--max-missing 0" not in gap_block


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
        "& powershell -NoProfile -ExecutionPolicy Bypass -File $ExportScript"
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


def test_daily_runner_and_weekly_pipeline_default_to_sanji_qwen_vl_extraction():
    weekly = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

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


def test_sanji_twice_daily_publish_reclaims_stale_pid_lock():
    daily = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8")

    assert "function Get-LockPid" in daily
    assert "Get-Process -Id $lockPid" in daily
    assert "$lockExpired -or ($lockPid -gt 0 -and -not $pidAlive)" in daily


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
    assert "token_expired" in wrapper
    assert '"--action", "resume-sync"' in wrapper
    assert "Sanji CDP sync auto-resume" in wrapper
    assert 'if (args.action === "resume-sync") output.final = await waitForIdle(client, "sync"' in cdp


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


def test_sanji_hermes_installer_templates_are_valid_python():
    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")

    for rel_path, template in namespace["SCRIPT_TEMPLATES"].items():
        ast.parse(template, filename=rel_path)


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
    assert 'python "$AGGREGATE_EXPAND_SCRIPT" @aggregateArgs' in weekly
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


def test_openclaw_publish_wrapper_writes_summary_for_controlled_poster_blocker():
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
    assert "exit 0" in script
    assert "blocked_on_release_package_quality_gate" in script
    assert 'throw "Release package quality gate failed' not in script
    assert script.index("blocked_on_cloudbase_poster_migration_write_gate") < script.index("blocked_on_release_package_quality_gate")


def test_openclaw_publish_wrapper_reports_actual_deploy_and_upload_execution_flags():
    script = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "$script:CloudRunDeployExecuted = $false" in script
    assert "$script:MiniProgramUploadExecuted = $false" in script
    assert "cloudrun_deploy_executed = [bool]$script:CloudRunDeployExecuted" in script
    assert "miniprogram_upload_executed = [bool]$script:MiniProgramUploadExecuted" in script
    assert "cloudrun_deploy_executed = [bool]$DeployBackend" not in script
    assert "miniprogram_upload_executed = [bool]$UploadFrontend" not in script
    deploy_step = script[
        script.index('Invoke-RunStep "Deploy CloudRun by direct CloudBase API"') :
        script.index('Invoke-RunStep "Smoke remote CloudRun and reconcile pagination"')
    ]
    assert "$script:CloudRunDeployExecuted = $true" in deploy_step
    upload_step = script[script.index('Invoke-RunStep "Upload miniprogram developer version"') :]
    assert "$script:MiniProgramUploadExecuted = $true" in upload_step


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


def test_weekly_pipeline_entity_enrichment_complete_output_overrides_nonzero_exit():
    script = (ROOT / "weekly_activity_next_week_pipeline.ps1").read_text(encoding="utf-8")

    assert "function Complete-EntityEnrichmentOutput" in script
    assert "entity_enrichment_summary.json" in script
    assert "entity_enrichment_exit_override.json" in script
    assert "complete_outputs_nonzero_exit_overridden" in script
    assert "$inputCandidateLines -ne $outputCandidateLines" in script
    assert "$inputReviewLines -ne $outputReviewLines" in script
    step35 = script[
        script.index('Invoke-Step "Step 3.5: Entity Enrichment') :
        script.index("# fallback：若实体富化没有输出")
    ]
    assert "Complete-EntityEnrichmentOutput" in step35
    assert "$global:LASTEXITCODE = 0" in step35


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
