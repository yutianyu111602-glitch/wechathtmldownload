import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "summarize_openclaw_weekly_daily_readiness.py"
WRAPPER = ROOT / "run_openclaw_weekly_daily_publish.ps1"


def load_module():
    spec = importlib.util.spec_from_file_location("weekly_readiness_source_mode", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_explicit_args(module, tmp_path: Path, source_mode: str):
    inputs = {}
    for name in ("quality", "poster", "fallback"):
        path = tmp_path / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        inputs[name] = path
    report = tmp_path / "readiness.json"
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    return module.parse_args(
        [
            "--source-mode",
            source_mode,
            "--reports-root",
            str(reports_root),
            "--quality-report",
            str(inputs["quality"]),
            "--poster-migration-report",
            str(inputs["poster"]),
            "--fallback-summary",
            str(inputs["fallback"]),
            "--report",
            str(report),
        ]
    )


def test_sanji_source_mode_does_not_require_or_infer_docker_smoke(tmp_path: Path):
    module = load_module()
    args = make_explicit_args(module, tmp_path, "sanji_desktop_rss")

    resolved = module.resolve_input_paths(args)
    summary = module.summarize_docker(None, required=False)
    vision_summary = module.summarize_vision(None, required=False)

    assert resolved["docker_smoke_report"] is None
    assert resolved["vision_batch_report"] is None
    assert resolved["exporter_freshness_preflight_report"] is None
    assert resolved["exporter_auth_recovery_preflight_report"] is None
    assert summary == {
        "required": False,
        "present": False,
        "applicable": False,
        "ok": True,
        "profile_count": 0,
        "profiles_ok_count": 0,
        "failed_profiles": [],
        "safety": {},
        "safety_failures": [],
        "secret_like_diagnostic_leak_count": 0,
    }
    assert vision_summary["required"] is False
    assert vision_summary["present"] is False
    assert vision_summary["applicable"] is False
    assert vision_summary["ok"] is True
    assert vision_summary["stepfun_complete"] is False


def test_docker_exporter_source_mode_still_fails_closed_without_smoke(tmp_path: Path):
    module = load_module()
    args = make_explicit_args(module, tmp_path, "docker_exporter")

    with pytest.raises(FileNotFoundError, match="could not infer valid docker smoke report"):
        module.resolve_input_paths(args)


def test_publish_wrapper_passes_explicit_source_mode_to_readiness():
    wrapper = WRAPPER.read_text(encoding="utf-8")
    readiness_block = wrapper[
        wrapper.index('$readinessArgs = @(') : wrapper.index('python @readinessArgs')
    ]

    assert '"--source-mode", $SourceMode' in readiness_block
    assert 'if ($SourceMode -eq "docker_exporter" -and (Test-Path -LiteralPath $exporterFreshnessPreflightReportPath))' in readiness_block
    assert 'if ($SourceMode -eq "docker_exporter" -and (Test-Path -LiteralPath $exporterAuthRecoveryPreflightReportPath))' in readiness_block


def test_sanji_end_to_end_summary_needs_no_legacy_reports(tmp_path: Path):
    module = load_module()
    args = make_explicit_args(module, tmp_path, "sanji_desktop_rss")
    args.report_only_exit_zero = True

    Path(args.fallback_summary).write_text(
        json.dumps(
            {
                "schema_version": "openclaw_weekly_daily_publish_summary.v2",
                "source_mode": "sanji_desktop_rss",
                "ok": False,
                "status": "blocked_on_release_package_quality_gate",
                "package_candidate_ready": False,
                "deploy_backend": False,
                "upload_frontend": False,
                "write_actions_allowed_now": False,
                "boundary": {},
            }
        ),
        encoding="utf-8",
    )

    assert module.run(args) == 0
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    assert report["source_mode"] == "sanji_desktop_rss"
    assert report["source_mode_matches_fallback"] is True
    assert report["docker"]["applicable"] is False
    assert report["vision"]["applicable"] is False
    assert report["legacy_evidence_applicability"] == {
        "docker_smoke": "not_applicable",
        "poster_vision_batch": "not_applicable",
        "exporter_preflights": "not_applicable",
        "poster_ocr_recovery_bundle": "not_applicable",
    }
    assert report["exporter_freshness_preflight"]["present"] is False
    assert report["exporter_auth_recovery_preflight"]["present"] is False
    assert report["paths"]["docker_smoke_report"] == ""
    assert report["paths"]["vision_batch_report"] == ""
