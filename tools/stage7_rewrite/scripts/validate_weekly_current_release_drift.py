#!/usr/bin/env python3
"""Validate drift between the weekly API default package and deploy package."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_DIR = Path("services/weekly_activity_cloudrun/data/current_release")
DEFAULT_DEPLOY_DIR = Path("services/weekly_activity_cloudrun/tmp/cloudrun_deploy_context/data/current_release")
DEFAULT_OUT_DIR = Path("tools/stage7_rewrite/reports/weekly_current_release_drift_gate_20260526")
DEFAULT_TOP_REPORT = Path("reports/WEEKLY_T2_T3_CURRENT_RELEASE_DRIFT_GATE_20260526.md")
ISO_DATE_LENGTH = 10


def load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON: {path}")
    return data


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iso_date(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) == ISO_DATE_LENGTH and text[4] == "-" and text[7] == "-":
        return text
    return ""


def item_date_keys(item: dict[str, Any]) -> list[str]:
    dates: set[str] = set()
    for key in ("event_date_start", "event_date_end", "event_date_iso_guess"):
        date = iso_date(item.get(key))
        if date:
            dates.add(date)
    for key in ("event_date_iso_guesses", "event_date_text"):
        raw = item.get(key)
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            date = iso_date(value)
            if date:
                dates.add(date)
    return sorted(dates)


def is_current_or_future(item: dict[str, Any], today: str) -> bool:
    dates = item_date_keys(item)
    start = iso_date(item.get("event_date_start")) or (dates[0] if dates else "")
    end = iso_date(item.get("event_date_end")) or (dates[-1] if dates else start)
    if not start and not end:
        return True
    return (end or start) >= today


def has_geo(item: dict[str, Any]) -> bool:
    return item.get("geo_lat") is not None and item.get("geo_lng") is not None


def current_api_total(items: list[dict[str, Any]], today: str) -> int:
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        if item.get("quality_status") != "READY":
            continue
        if not is_current_or_future(item, today):
            continue
        key = str(item.get("dedupe_key") or item.get("id") or len(deduped))
        deduped[key] = item
    return len(deduped)


def package_metrics(package_dir: Path, *, today: str, label: str) -> dict[str, Any]:
    manifest_path = package_dir / "manifest.json"
    current_path = package_dir / "current.json"
    by_id_dir = package_dir / "by-id"
    manifest = load_json_object(manifest_path)
    current = load_json_object(current_path)
    raw_items = current.get("items")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    quality_counts = Counter(str(item.get("quality_status") or "unknown") for item in items)
    by_id_count = len(list(by_id_dir.glob("*.json"))) if by_id_dir.exists() else 0
    return {
        "label": label,
        "package_dir": str(package_dir),
        "manifest_path": str(manifest_path),
        "current_path": str(current_path),
        "by_id_dir": str(by_id_dir),
        "manifest_sha256": sha256_file(manifest_path),
        "current_sha256": sha256_file(current_path),
        "manifest_generated_at": manifest.get("generated_at") or manifest.get("generatedAt"),
        "manifest_item_count": manifest.get("item_count") or manifest.get("items_total") or 0,
        "current_generated_at": current.get("generated_at") or current.get("generatedAt"),
        "current_item_count": current.get("item_count") or current.get("items_total") or 0,
        "items_len": len(items),
        "by_id_json_count": by_id_count,
        "ready_item_count": quality_counts.get("READY", 0),
        "quality_status_counts": dict(sorted(quality_counts.items())),
        "geo_coord_count": sum(1 for item in items if has_geo(item)),
        "api_current_total_for_today": current_api_total(items, today),
        "window_start": manifest.get("window_start"),
        "window_end": manifest.get("window_end"),
        "source_queue_match_count": manifest.get("source_queue_match_count"),
        "source_rows_loaded": (manifest.get("source_summary") or {}).get("source_rows_loaded")
        if isinstance(manifest.get("source_summary"), dict)
        else None,
        "city_route_count": manifest.get("city_route_count"),
        "date_route_count": manifest.get("date_route_count"),
    }


def check_package_internal(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "manifest_matches_current_items": metrics["manifest_item_count"] == metrics["items_len"],
        "current_count_matches_items": metrics["current_item_count"] == metrics["items_len"],
        "by_id_matches_items": metrics["by_id_json_count"] == metrics["items_len"],
        "has_current_json": Path(metrics["current_path"]).exists(),
        "has_manifest_json": Path(metrics["manifest_path"]).exists(),
    }


def build_report(
    *,
    default_dir: Path,
    deploy_dir: Path,
    today: str = "2026-05-26",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    now = generated_at or datetime.now()
    default_metrics = package_metrics(default_dir, today=today, label="default_runtime")
    deploy_metrics = package_metrics(deploy_dir, today=today, label="deploy_context")
    checks = {
        "package_current_sha256_match": default_metrics["current_sha256"] == deploy_metrics["current_sha256"],
        "package_manifest_sha256_match": default_metrics["manifest_sha256"] == deploy_metrics["manifest_sha256"],
        "package_manifest_item_count_match": default_metrics["manifest_item_count"]
        == deploy_metrics["manifest_item_count"],
        "package_items_len_match": default_metrics["items_len"] == deploy_metrics["items_len"],
        "package_by_id_count_match": default_metrics["by_id_json_count"] == deploy_metrics["by_id_json_count"],
        "package_geo_coord_count_match": default_metrics["geo_coord_count"] == deploy_metrics["geo_coord_count"],
        "package_api_current_total_match": default_metrics["api_current_total_for_today"]
        == deploy_metrics["api_current_total_for_today"],
        "default_internal_manifest_current_by_id_consistent": all(check_package_internal(default_metrics).values()),
        "deploy_internal_manifest_current_by_id_consistent": all(check_package_internal(deploy_metrics).values()),
    }
    failed_checks = [key for key, value in checks.items() if not value]
    drift_detected = bool(failed_checks)
    decision = (
        "weekly_current_release_drift_detected_report_only"
        if drift_detected
        else "weekly_current_release_no_drift_report_only"
    )
    return {
        "schema_version": "weekly_current_release_drift_gate.v1",
        "generated_at": now.isoformat(timespec="seconds"),
        "today": today,
        "decision": decision,
        "ok": not drift_detected,
        "failed_checks": failed_checks,
        "checks": checks,
        "default_runtime": default_metrics,
        "deploy_context": deploy_metrics,
        "internal_checks": {
            "default_runtime": check_package_internal(default_metrics),
            "deploy_context": check_package_internal(deploy_metrics),
        },
        "authority": {
            "preferred_current_authority": "deploy_context",
            "preferred_reason": (
                "Existing SSOT/deploy evidence points at deploy_context while default runtime package currently "
                "has fewer items and no geo coordinates."
            ),
            "do_not_overwrite_runtime_package_automatically": True,
            "requires_human_or_release_guardian_sync_decision": drift_detected,
        },
        "boundaries": {
            "report_only": True,
            "runtime_package_overwrite_executed": False,
            "cloudrun_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "credential_read_executed": False,
            "network_call_executed": False,
            "memory_write_executed": False,
            "d_drive_scan_executed": False,
        },
        "stop_reason": "weekly_default_vs_deploy_current_release_drift" if drift_detected else "none",
        "wait_reason": (
            "Default weekly API package and deploy context package diverge; package sync must be explicit and "
            "verified before claiming local default equals deployed authority."
            if drift_detected
            else "none"
        ),
    }


def write_markdown(path: Path, report: dict[str, Any], summary_path: Path) -> None:
    default = report["default_runtime"]
    deploy = report["deploy_context"]
    lines = [
        "# Weekly T2/T3 Current Release Drift Gate",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Decision: `{report['decision']}`",
        f"- OK: `{str(report['ok']).lower()}`",
        f"- Today for API-current total: `{report['today']}`",
        f"- Summary JSON: `{summary_path}`",
        "",
        "## Package Metrics",
        "",
        "| metric | default_runtime | deploy_context |",
        "| --- | ---: | ---: |",
        f"| manifest item_count | `{default['manifest_item_count']}` | `{deploy['manifest_item_count']}` |",
        f"| current item_count | `{default['current_item_count']}` | `{deploy['current_item_count']}` |",
        f"| current items length | `{default['items_len']}` | `{deploy['items_len']}` |",
        f"| by-id JSON count | `{default['by_id_json_count']}` | `{deploy['by_id_json_count']}` |",
        f"| READY item count | `{default['ready_item_count']}` | `{deploy['ready_item_count']}` |",
        f"| geo coordinate count | `{default['geo_coord_count']}` | `{deploy['geo_coord_count']}` |",
        f"| API current total for today | `{default['api_current_total_for_today']}` | `{deploy['api_current_total_for_today']}` |",
        f"| window_start | `{default['window_start']}` | `{deploy['window_start']}` |",
        f"| window_end | `{default['window_end']}` | `{deploy['window_end']}` |",
        f"| source_queue_match_count | `{default['source_queue_match_count']}` | `{deploy['source_queue_match_count']}` |",
        f"| source_rows_loaded | `{default['source_rows_loaded']}` | `{deploy['source_rows_loaded']}` |",
        "",
        "## Failed Checks",
        "",
    ]
    if report["failed_checks"]:
        lines.extend(f"- `{check}`" for check in report["failed_checks"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Authority And Boundary",
            "",
            f"- Preferred current authority for this gate: `{report['authority']['preferred_current_authority']}`",
            f"- Reason: {report['authority']['preferred_reason']}",
            "- This gate does not overwrite `services\\weekly_activity_cloudrun\\data\\current_release`.",
            "- This gate does not deploy CloudRun, upload/review the mini-program, read credentials, call network, write memory, or scan D: roots.",
            f"- STOP_REASON: `{report['stop_reason']}`",
            f"- WAIT_REASON: `{report['wait_reason']}`",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--default-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--deploy-dir", type=Path, default=DEFAULT_DEPLOY_DIR)
    parser.add_argument("--today", default="2026-05-26")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-report", type=Path, default=DEFAULT_TOP_REPORT)
    args = parser.parse_args()

    report = build_report(default_dir=args.default_dir, deploy_dir=args.deploy_dir, today=args.today)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.out_dir / "summary.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(args.top_report, report, summary_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
