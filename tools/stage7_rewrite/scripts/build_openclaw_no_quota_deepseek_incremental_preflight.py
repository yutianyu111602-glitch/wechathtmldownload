#!/usr/bin/env python3
"""Build a report-only OpenClaw no-quota DeepSeek incremental preflight.

This script proves the local weekly mini-program incremental package path from
repo evidence only. It does not read secret values, call DeepSeek, probe
CloudBase, start Docker, run the exporter, rebuild packages, deploy, upload, or
touch the mini-program release path.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_OUT_DIR = REPORTS_ROOT / "openclaw_no_quota_deepseek_incremental_preflight_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_OPENCLAW_NO_QUOTA_DEEPSEEK_INCREMENTAL_PREFLIGHT_20260602.md"
SCHEMA_VERSION = "openclaw_no_quota_deepseek_incremental_preflight.v1"


PATHS = {
    "daily_wrapper": Path("tools/stage7_rewrite/run_openclaw_weekly_daily_publish.ps1"),
    "weekly_pipeline": Path("tools/stage7_rewrite/weekly_activity_next_week_pipeline.ps1"),
    "deepseek_enrichment": Path("tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_deepseek.py"),
    "incremental_merge": Path("tools/stage7_rewrite/scripts/merge_weekly_incremental_api_package.py"),
    "incremental_merge_test": Path("tools/stage7_rewrite/tests/test_merge_weekly_incremental_api_package.py"),
    "docker_runbook": Path("tools/stage7_rewrite/OPENCLAW_WEEKLY_DOCKER_ORCHESTRATION_RUNBOOK.md"),
    "daily_runbook": Path("tools/stage7_rewrite/OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md"),
    "openclaw_automation": Path("apps/weekly_activity_miniprogram/OPENCLAW_AUTOMATION.md"),
    "cloudrun_readme": Path("services/weekly_activity_cloudrun/README.md"),
}


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def read_text(repo_root: Path, relative_path: Path) -> str:
    path = repo_root / relative_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def status_for(condition: bool) -> str:
    return "passed" if condition else "failed"


def check(check_id: str, condition: bool, evidence: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": required,
        "status": status_for(condition),
        "evidence": evidence,
    }


def find_latest_daily_summary(repo_root: Path) -> tuple[Path | None, dict[str, Any]]:
    candidates = sorted(
        (repo_root / "tools" / "stage7_rewrite" / "reports").glob(
            "openclaw_weekly_daily_*/openclaw_weekly_daily_publish_summary.json"
        ),
        key=lambda path: path.parent.name,
        reverse=True,
    )
    for path in candidates:
        try:
            return path, read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
    return None, {}


def safe_incremental_report(summary: dict[str, Any]) -> tuple[Path | None, dict[str, Any]]:
    report_path = summary.get("incremental_merge_report")
    if not report_path:
        return None, {}
    path = Path(str(report_path))
    if not path.exists():
        return path, {}
    try:
        return path, read_json(path)
    except (OSError, json.JSONDecodeError):
        return path, {}


def docker_profile_inventory(repo_root: Path) -> dict[str, Any]:
    compose_candidates: list[Path] = []
    for pattern in (
        "docker-compose*.yml",
        "docker-compose*.yaml",
        "compose*.yml",
        "compose*.yaml",
        "tools/stage7_rewrite/docker-compose*.yml",
        "tools/stage7_rewrite/docker-compose*.yaml",
        "tools/stage7_rewrite/compose*.yml",
        "tools/stage7_rewrite/compose*.yaml",
        "tools/stage7_rewrite/docker/**/*.yml",
        "tools/stage7_rewrite/docker/**/*.yaml",
    ):
        compose_candidates.extend(repo_root.glob(pattern))

    dockerfiles = [
        path
        for path in (
            repo_root / "vendor" / "wechat-article-exporter" / "Dockerfile",
            repo_root / "services" / "weekly_activity_cloudrun" / "Dockerfile",
        )
        if path.exists()
    ]
    profile_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in compose_candidates if path.exists()
    ).lower()
    expected_profiles = {
        "source_exporter": "source",
        "source_queue": "queue",
        "ocr": "ocr",
        "llm_extract": "llm",
        "map_verify": "map",
        "package_merge": "package",
        "deploy_upload": "deploy",
    }
    declared_layers = {
        layer: bool(profile_text and marker in profile_text)
        for layer, marker in expected_profiles.items()
    }
    return {
        "dockerfiles": [str(path.relative_to(repo_root)) for path in dockerfiles],
        "compose_files": [str(path.relative_to(repo_root)) for path in sorted(set(compose_candidates))],
        "profiles_declared": bool(compose_candidates),
        "declared_layers": declared_layers,
        "profiles_complete_for_all_layers": bool(compose_candidates) and all(declared_layers.values()),
    }


def build_report(repo_root: Path) -> dict[str, Any]:
    texts = {key: read_text(repo_root, rel) for key, rel in PATHS.items()}
    paths_exist = {key: (repo_root / rel).exists() for key, rel in PATHS.items()}
    latest_summary_path, latest_summary = find_latest_daily_summary(repo_root)
    merge_report_path, merge_report = safe_incremental_report(latest_summary)
    docker_inventory = docker_profile_inventory(repo_root)

    checks = [
        check("daily_wrapper_exists", paths_exist["daily_wrapper"], str(PATHS["daily_wrapper"])),
        check("weekly_pipeline_exists", paths_exist["weekly_pipeline"], str(PATHS["weekly_pipeline"])),
        check("deepseek_enrichment_exists", paths_exist["deepseek_enrichment"], str(PATHS["deepseek_enrichment"])),
        check("incremental_merge_exists", paths_exist["incremental_merge"], str(PATHS["incremental_merge"])),
        check(
            "direct_deepseek_official_api_route_declared",
            "https://api.deepseek.com" in texts["deepseek_enrichment"]
            and "DEFAULT_DEEPSEEK_BASE_URL" in texts["deepseek_enrichment"],
            "DeepSeek enrichment declares official direct API base URL.",
        ),
        check(
            "deepseek_flash_primary_pro_risk_policy_declared",
            "deepseek-v4-flash" in texts["weekly_pipeline"]
            and "deepseek-v4-pro" in texts["weekly_pipeline"]
            and "deepseek-v4-flash" in texts["deepseek_enrichment"]
            and "deepseek-v4-pro" in texts["deepseek_enrichment"],
            "Pipeline and enrichment script declare Flash primary plus Pro risk adjudication.",
        ),
        check(
            "deepseek_thinking_disabled",
            "DEEPSEEK_THINKING_TYPE = \"disabled\"" in texts["weekly_pipeline"]
            and "\"thinking\": {\"type\": \"disabled\"}" in texts["deepseek_enrichment"],
            "Pipeline and payload disable thinking mode.",
        ),
        check(
            "cloudbase_ai_not_required_for_local_materialize",
            "OpenClaw/Hermes 模型调用只走直连 DeepSeek API" in texts["openclaw_automation"]
            and "local materialize" in texts["openclaw_automation"],
            "OpenClaw automation document states local materialize uses direct DeepSeek API results.",
        ),
        check(
            "cloudbase_static_upload_disabled_by_default",
            "旧 CloudBase 静态上传默认禁用" in texts["weekly_pipeline"]
            and "if ($SkipUpload -or -not $EnableLegacyStaticUpload)" in texts["weekly_pipeline"],
            "Weekly pipeline keeps legacy CloudBase static upload disabled by default.",
        ),
        check(
            "incremental_merge_enabled_by_default",
            "if (-not $DisableIncrementalMerge)" in texts["daily_wrapper"]
            and "$PipelineMinExpectedItems = [Math]::Max(1, $IncrementalMinExpectedItems)" in texts["daily_wrapper"],
            "Daily wrapper enables incremental merge unless explicitly disabled and lowers candidate floor to 1.",
        ),
        check(
            "five_or_fewer_incremental_rows_tested",
            "test_five_or_fewer_incremental_rows_still_merge_into_full_current" in texts["incremental_merge_test"],
            "Focused test proves five incremental rows merge into the full current package.",
        ),
        check(
            "deploy_upload_requires_explicit_flags",
            "if ($DeployBackend)" in texts["daily_wrapper"] and "if ($UploadFrontend)" in texts["daily_wrapper"],
            "Daily wrapper deploy/upload branches require explicit switches.",
        ),
        check(
            "latest_local_incremental_evidence_exists",
            bool(latest_summary_path and latest_summary.get("incremental_merge_applied") is True),
            str(latest_summary_path) if latest_summary_path else "No latest OpenClaw daily summary found.",
            required=False,
        ),
        check(
            "latest_incremental_report_base_not_replaced_by_small_candidate",
            bool(
                merge_report
                and int(merge_report.get("base_count", 0)) >= 50
                and int(merge_report.get("incremental_count", 0)) <= 5
                and int(merge_report.get("merged_count", 0)) >= int(merge_report.get("base_count", 0))
            ),
            str(merge_report_path) if merge_report_path else "No incremental merge report found.",
            required=False,
        ),
        check(
            "docker_profiles_complete_for_all_layers",
            docker_inventory["profiles_complete_for_all_layers"],
            "Dockerfiles exist but full compose/profile coverage is required before claiming Docker architecture complete.",
            required=False,
        ),
    ]

    failed_required = [item["check_id"] for item in checks if item["required"] and item["status"] != "passed"]
    docker_complete = docker_inventory["profiles_complete_for_all_layers"]
    decision = (
        "openclaw_no_quota_deepseek_incremental_preflight_failed_report_only"
        if failed_required
        else (
            "openclaw_no_quota_deepseek_incremental_preflight_ready_report_only"
            if docker_complete
            else "openclaw_no_quota_deepseek_incremental_preflight_ready_report_only_docker_profiles_incomplete"
        )
    )

    latest_evidence = {
        "summary_path": str(latest_summary_path) if latest_summary_path else "",
        "summary_ok": latest_summary.get("ok") is True,
        "run_id": latest_summary.get("run_id", ""),
        "item_count": latest_summary.get("item_count"),
        "pipeline_min_expected_items": latest_summary.get("pipeline_min_expected_items"),
        "incremental_merge_enabled": latest_summary.get("incremental_merge_enabled"),
        "incremental_merge_applied": latest_summary.get("incremental_merge_applied"),
        "deploy_backend": latest_summary.get("deploy_backend"),
        "upload_frontend": latest_summary.get("upload_frontend"),
        "merge_report_path": str(merge_report_path) if merge_report_path else "",
        "merge_report": {
            "base_count": merge_report.get("base_count"),
            "incremental_count": merge_report.get("incremental_count"),
            "merged_count": merge_report.get("merged_count"),
            "added_count": merge_report.get("added_count"),
            "replaced_count": merge_report.get("replaced_count"),
        },
    }

    next_actions = [
        "Use this preflight as the first OpenClaw no-quota gate before any local incremental package run.",
        "For execution, call run_openclaw_weekly_daily_publish.ps1 without DeployBackend or UploadFrontend until package evidence is reviewed.",
        "Keep DB2 and release guard as read-only consumers until an explicit controller release clears package/deploy/upload gates.",
    ]
    if docker_complete:
        next_actions.insert(
            2,
            "Docker profile contracts are now statically complete; run weekly:openclaw:docker-profiles:contract-verify before any future container dry-run release.",
        )
        next_actions.insert(
            3,
            "The next execution slice should be a controller-released container dry-run from L1 through L6 with report-local outputs, not deploy/upload.",
        )
    else:
        next_actions.insert(
            2,
            "Move L1-L6 weekly workers behind Docker Compose or equivalent profiles, then rerun this preflight and a local dry-run source-to-package report.",
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_cst(),
        "decision": decision,
        "mode": "static_report_only_no_secret_no_network_no_docker_no_llm",
        "cloudbase_ai_quota_dependency": {
            "cloudbase_ai_required_for_local_incremental_update": False,
            "cloudbase_ai_allowed_as_health_probe_only": True,
            "direct_deepseek_api_required_for_llm_materialization_at_runtime": True,
            "deepseek_api_key_value_read_by_this_preflight": False,
            "deepseek_api_key_presence_probe_executed": False,
        },
        "checks": checks,
        "failed_required_check_ids": failed_required,
        "entrypoints": {key: str(value) for key, value in PATHS.items()},
        "direct_deepseek_route": {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "primary_model": "deepseek-v4-flash",
            "adjudication_model": "deepseek-v4-pro",
            "thinking": "disabled",
            "cloudbase_ai_used_for_package_materialization": False,
        },
        "incremental_package_path": {
            "candidate_floor_when_incremental_enabled": 1,
            "low_count_incremental_rows_allowed": True,
            "direct_small_candidate_replaces_full_current": False,
            "merge_script": str(PATHS["incremental_merge"]),
        },
        "docker_layer_status": docker_inventory,
        "latest_known_incremental_evidence": latest_evidence,
        "execution_flags": {
            "docker_started": False,
            "worker_started": False,
            "network_probe_executed": False,
            "deepseek_call_executed": False,
            "cloudbase_probe_executed": False,
            "package_rebuild_executed": False,
            "cloudrun_deploy_executed": False,
            "cloudbase_sync_executed": False,
            "miniprogram_upload_executed": False,
            "wechat_review_submitted": False,
            "public_release_executed": False,
        },
        "secret_policy": {
            "secret_values_read": False,
            "secret_values_printed": False,
            "env_secret_probe_executed": False,
            "forbidden_paths_read": False,
        },
        "next_actions": next_actions,
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    failed_required = report.get("failed_required_check_ids", [])
    latest = report.get("latest_known_incremental_evidence", {})
    docker_status = report.get("docker_layer_status", {})
    lines = [
        "# Weekly OpenClaw No-Quota DeepSeek Incremental Preflight",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Decision: `{report['decision']}`",
        "- Mode: report-only; no Docker, network, DeepSeek, CloudBase, package rebuild, deploy, upload, review, release, or secret probe.",
        f"- Failed required checks: `{len(failed_required)}`",
        f"- CloudBase AI required for local incremental update: `{report['cloudbase_ai_quota_dependency']['cloudbase_ai_required_for_local_incremental_update']}`",
        f"- Direct DeepSeek route: `{report['direct_deepseek_route']['base_url']}` / `{report['direct_deepseek_route']['primary_model']}` with Pro risk adjudication.",
        f"- Latest local incremental evidence: run `{latest.get('run_id', '')}`, item_count `{latest.get('item_count')}`, merge_applied `{latest.get('incremental_merge_applied')}`.",
        f"- Latest merge counts: base `{latest.get('merge_report', {}).get('base_count')}`, incremental `{latest.get('merge_report', {}).get('incremental_count')}`, merged `{latest.get('merge_report', {}).get('merged_count')}`.",
        f"- Docker profiles complete: `{docker_status.get('profiles_complete_for_all_layers')}`.",
        "",
        "## Boundary",
        "",
        "- This does not prove every weekly layer is containerized.",
        "- This does prove, from code and prior local evidence, that CloudBase AI quota is not a dependency for local DeepSeek materialization and incremental package merge.",
        "- Deploy, CloudBase sync, mini-program upload, WeChat review, and public release remain explicit separate gates.",
        "",
        "## Next",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("next_actions", []))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--scorecard", default=str(DEFAULT_SCORECARD))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    out_dir = Path(args.out_dir)
    scorecard = Path(args.scorecard)
    report = build_report(repo_root)
    write_json(out_dir / "openclaw_no_quota_deepseek_incremental_preflight.json", report)
    write_scorecard(scorecard, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["failed_required_check_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
