#!/usr/bin/env python3
"""Build a factual report for the CloudRun production deploy attempt."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LOG = Path("reports/full_pipeline_production_deploy_20260518/weekly_bake_and_deploy.log")
DEFAULT_VERSION_LIST = Path("reports/full_pipeline_production_deploy_20260518/cloudrun_version_list_after.txt")
DEFAULT_DIRECT_API_REPORT = Path("reports/full_pipeline_production_deploy_20260518/cloudrun_direct_api_deploy_report.json")
DEFAULT_OUT_DIR = Path("reports/full_pipeline_production_deploy_20260518")
ATTEMPT_STARTED_AT = "2026-05-18 03:00:00"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_first_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def active_version(version_payload: dict[str, Any]) -> dict[str, Any]:
    versions = version_payload.get("data") if isinstance(version_payload.get("data"), list) else []
    active = [item for item in versions if int(item.get("flowRatio") or 0) == 100]
    return active[-1] if active else {}


def build_report(log_text: str, version_text: str, direct_api_report: dict[str, Any] | None = None) -> dict[str, Any]:
    direct_api_report = direct_api_report or {}
    version_payload = parse_first_json_object(version_text)
    active = active_version(version_payload)
    gzip_package_used = "articles payload articles.jsonl.gz" in log_text
    modern_attempted = "tcb run deploy weekly-api" in log_text
    modern_unsupported = "Current capability does not support" in log_text
    deprecated_create_attempted = "run:deprecated version create" in log_text
    deprecated_update_attempted = "run:deprecated version update" in log_text
    deprecated_image_upload_attempted = "run:deprecated image upload" in log_text
    image_deploy_attempted = deprecated_image_upload_attempted and "--image" in log_text
    timeout_or_no_done = "==== retry with gzip stage7 atlas package ====" in log_text and "=== Done ===" not in log_text.split(
        "==== retry with gzip stage7 atlas package ===="
    )[-1]
    active_updated_at = str(active.get("updatedTime") or "")
    visible_version_change = active_updated_at >= ATTEMPT_STARTED_AT
    direct_api_verified = bool(direct_api_report.get("ok")) and direct_api_report.get("decision") == "cloudrun_direct_api_deploy_verified"
    direct_api_version_name = str((direct_api_report.get("operation") or {}).get("version_name") or "")
    direct_api_publish_verified = bool((direct_api_report.get("safety") or {}).get("production_publish_verified"))
    cloud_deploy_executed = bool((visible_version_change and not timeout_or_no_done) or (direct_api_verified and direct_api_publish_verified))
    blockers = []
    if not cloud_deploy_executed:
        if modern_unsupported:
            blockers.append("modern_tcb_run_deploy_unsupported_for_env")
        if timeout_or_no_done:
            blockers.append("deprecated_rolling_update_timed_out_before_success_marker")
        if deprecated_image_upload_attempted:
            blockers.append("deprecated_image_upload_did_not_produce_verified_version_update")
        if not visible_version_change:
            blockers.append("cloudrun_version_list_has_no_visible_post_attempt_update")
    decision = "cloudrun_deploy_verified" if cloud_deploy_executed else "cloudrun_deploy_blocked_external_cli"
    return {
        "schema_version": "cloudrun_deploy_execution_report.v1",
        "generated_at": now_iso(),
        "ok": cloud_deploy_executed,
        "decision": decision,
        "attempt_started_after": ATTEMPT_STARTED_AT,
        "facts": {
            "local_bake_executed": "--- bake data:" in log_text and "copied: current.json" in log_text,
            "gzip_stage7_package_used": gzip_package_used,
            "modern_deploy_attempted": modern_attempted,
            "modern_deploy_unsupported_for_env": modern_unsupported,
            "deprecated_create_attempted": deprecated_create_attempted,
            "deprecated_update_attempted": deprecated_update_attempted,
            "deprecated_image_upload_attempted": deprecated_image_upload_attempted,
            "image_deploy_attempted": image_deploy_attempted,
            "direct_api_deploy_verified": direct_api_verified,
            "direct_api_version_name": direct_api_version_name,
            "timeout_or_missing_success_marker": timeout_or_no_done,
            "active_version": active.get("versionName", ""),
            "active_version_flow_ratio": active.get("flowRatio"),
            "active_version_updated_time": active_updated_at,
            "visible_version_change_after_attempt": visible_version_change,
        },
        "blockers": blockers,
        "safety": {
            "secret_value_read_or_printed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "production_sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "cloud_deploy_executed": cloud_deploy_executed,
            "production_publish_verified": cloud_deploy_executed,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# CloudRun Deploy Execution Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        "",
        "## Facts",
        "",
    ]
    for key, value in report["facts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        lines.extend(f"- `{item}`" for item in report["blockers"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- cloud_deploy_executed: `{report['safety']['cloud_deploy_executed']}`",
            f"- production_publish_verified: `{report['safety']['production_publish_verified']}`",
            "- No secret value was read or printed.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--version-list", type=Path, default=DEFAULT_VERSION_LIST)
    parser.add_argument("--direct-api-report", type=Path, default=DEFAULT_DIRECT_API_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    direct_api_report = {}
    if args.direct_api_report.exists():
        direct_api_report = json.loads(args.direct_api_report.read_text(encoding="utf-8", errors="replace"))
    report = build_report(
        args.log.read_text(encoding="utf-8", errors="replace"),
        args.version_list.read_text(encoding="utf-8", errors="replace"),
        direct_api_report,
    )
    write_json(args.out_dir / "cloudrun_deploy_execution_report.json", report)
    write_markdown(args.out_dir / "cloudrun_deploy_execution_report.md", report)
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "blockers": report["blockers"]}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] or args.report_only_exit_zero else 2


if __name__ == "__main__":
    raise SystemExit(main())
