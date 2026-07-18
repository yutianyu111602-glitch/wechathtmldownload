#!/usr/bin/env python
"""Build a report-only controller packet for split poster recovery lanes.

The weekly package can have two different poster recovery lanes at the same
time: public-cover upload candidates and article-body-image OCR recovery. This
packet makes that split explicit so a partial CloudBase upload plan cannot be
mistaken for full package readiness.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_poster_recovery_split_controller_packet.v1"
READY_DECISION = "weekly_poster_recovery_split_controller_packet_ready_report_only_mixed_lanes"
OCR_ONLY_READY_DECISION = "weekly_poster_recovery_split_controller_packet_ready_report_only_ocr_only"
BLOCKED_DECISION = "weekly_poster_recovery_split_controller_packet_blocked_report_only"
WORK_ORDERS_SCHEMA = "weekly_missing_internal_poster_recovery_work_orders.v1"
WRITE_GATE_SCHEMA = "weekly_poster_cloudbase_migration_write_gate.v1"
DEFAULT_PUBLISH_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_weekly_daily_20260606_060904"
DEFAULT_WORK_ORDERS = DEFAULT_PUBLISH_DIR / "missing_internal_poster_recovery_work_orders.json"
DEFAULT_WRITE_GATE = DEFAULT_PUBLISH_DIR / "poster_cloudbase_migration_write_gate.json"
RUNTIME_REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports"))
DEFAULT_REPORT = RUNTIME_REPORT_ROOT / "poster_recovery" / "poster_recovery_split_controller_packet.json"
DEFAULT_SCORECARD = RUNTIME_REPORT_ROOT / "poster_recovery" / "WEEKLY_POSTER_RECOVERY_SPLIT_CONTROLLER_PACKET.md"
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\)")
SECRET_RE = re.compile(r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})")
WORK_ORDER_FALSE_KEYS = (
    "network_executed",
    "download_executed",
    "ocr_executed",
    "vision_api_executed",
    "cloudbase_storage_write_executed",
    "package_patch_executed",
)
WRITE_GATE_BOUNDARY_FALSE_KEYS = (
    "downloads_executed",
    "cloudbase_storage_write_executed",
    "package_patch_executed",
    "deploy_executed",
    "cloudbase_db_write_executed",
    "miniprogram_upload_executed",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def safe_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(RAW_URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def check(check_id: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": True,
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def sanitize_public_candidate(row: dict[str, Any]) -> dict[str, Any]:
    locator = as_dict(row.get("source_locator"))
    return {
        "id": str(row.get("id") or ""),
        "title": str(row.get("title") or ""),
        "lane": str(row.get("lane") or ""),
        "event_date_start": str(row.get("event_date_start") or ""),
        "city": [str(value) for value in as_list(row.get("city"))],
        "venue": str(row.get("venue") or ""),
        "planned_cloud_path": str(row.get("planned_cloud_path") or ""),
        "planned_public_url_hash": str(row.get("planned_public_url_hash") or ""),
        "public_poster_url_sha256": str(row.get("public_poster_url_sha256") or ""),
        "source_locator": {
            "source_locator_method": str(locator.get("source_locator_method") or ""),
            "source_map_entry_present": bool(locator.get("source_map_entry_present")),
            "source_url_sha256": str(locator.get("source_url_sha256") or ""),
            "source_action_available": bool(locator.get("source_action_available")),
        },
        "required_review": "verify_public_cover_is_main_activity_poster_with_ocr_or_vision",
    }


def sanitize_ocr_candidate(row: dict[str, Any]) -> dict[str, Any]:
    locator = as_dict(row.get("source_locator"))
    return {
        "id": str(row.get("id") or ""),
        "title": str(row.get("title") or ""),
        "lane": str(row.get("lane") or ""),
        "event_date_start": str(row.get("event_date_start") or ""),
        "city": [str(value) for value in as_list(row.get("city"))],
        "venue": str(row.get("venue") or ""),
        "aggregation_child": bool(row.get("aggregation_child")),
        "candidate_source_key_hashes": [str(value) for value in as_list(locator.get("candidate_source_keys"))],
        "candidate_source_url_sha256": [str(value) for value in as_list(locator.get("candidate_source_url_sha256"))],
        "source_locator_method": str(locator.get("source_locator_method") or ""),
        "source_map_candidate_count": int_value(locator.get("source_map_candidate_count")),
        "required_review": "enumerate_article_body_images_then_rank_main_activity_poster",
    }


def build_packet(work_orders_path: Path, write_gate_path: Path, public_limit: int = 8, ocr_limit: int = 12) -> dict[str, Any]:
    work_orders = read_json(work_orders_path)
    write_gate = read_json(write_gate_path)
    rows = [row for row in as_list(work_orders.get("work_orders")) if isinstance(row, dict)]
    public_rows = [row for row in rows if row.get("lane") == "public_url_cloudbase_upload_candidate"]
    ocr_rows = [row for row in rows if row.get("lane") == "article_image_ocr_main_poster_recovery"]
    missing_count = int_value(work_orders.get("missing_internal_poster_count") or write_gate.get("missing_internal_poster_count"))
    work_order_count = int_value(work_orders.get("work_order_count"))
    public_count = int_value(work_orders.get("public_url_upload_candidate_count"))
    ocr_count = int_value(work_orders.get("no_public_url_recovery_count"))
    write_target_count = int_value(write_gate.get("target_count"))
    planned_upload_count = int_value(write_gate.get("planned_upload_count"))
    write_failed_ids = [str(value) for value in as_list(write_gate.get("failed_check_ids"))]
    boundary = as_dict(write_gate.get("boundary"))
    packet = {
        "schema_version": f"{SCHEMA_VERSION}.controller_packet",
        "packet_status": "ready_for_split_recovery_controller_review",
        "controller_release_created_by_this_packet": False,
        "public_upload_allowed_by_this_packet": False,
        "article_image_ocr_allowed_by_this_packet": False,
        "cloudbase_storage_write_allowed_by_this_packet": False,
        "package_patch_allowed_by_this_packet": False,
        "release_ready_by_this_packet": False,
        "counts": {
            "missing_internal_poster_count": missing_count,
            "work_order_count": work_order_count,
            "public_url_upload_candidate_count": public_count,
            "article_image_ocr_recovery_count": ocr_count,
            "aggregate_child_recovery_count": int_value(work_orders.get("aggregate_child_recovery_count")),
            "write_gate_target_count": write_target_count,
            "write_gate_planned_upload_count": planned_upload_count,
        },
        "mixed_lane_status": {
            "mixed_recovery_required": public_count > 0 and ocr_count > 0,
            "ocr_only_recovery_required": public_count == 0 and ocr_count > 0,
            "public_only_recovery_required": public_count > 0 and ocr_count == 0,
            "public_upload_subset_can_clear_quality_gate": False,
            "all_missing_posters_covered_by_public_upload_plan": public_count == missing_count and ocr_count == 0,
            "quality_counts_match_poster_targets_failed": "quality_counts_match_poster_targets" in write_failed_ids,
        },
        "public_upload_review_queue": [sanitize_public_candidate(row) for row in public_rows[:public_limit]],
        "article_image_ocr_review_queue": [sanitize_ocr_candidate(row) for row in ocr_rows[:ocr_limit]],
        "next_required_actions": [
            "verify_public_cover_candidates_are_real_main_event_posters",
            "run_bounded_article_body_image_ocr_for_ocr_lane_after_separate_controller_release",
            "upload_all_verified_posters_to_cloudbase_only_after_confirm_token",
            "patch_package_only_after_all_missing_posters_have_cloudbase_file_ids",
            "rerun_release_package_quality_gate_and_readiness",
        ],
        "stop_conditions": [
            "public_upload_candidate_count_less_than_missing_internal_poster_count",
            "article_image_ocr_lane_not_completed",
            "raw_url_private_path_secret_would_be_emitted",
            "cloudbase_upload_or_package_patch_requested_without_confirm_token",
            "db_deploy_sync_upload_review_release_requested",
        ],
    }
    packet_leak_count = leak_count(packet)
    checks: list[dict[str, Any]] = [
        check("work_orders_schema", work_orders.get("schema_version") == WORK_ORDERS_SCHEMA, str(work_orders.get("schema_version"))),
        check("work_orders_report_only", work_orders.get("report_only") is True, str(work_orders.get("report_only"))),
        check("write_gate_schema", write_gate.get("schema_version") == WRITE_GATE_SCHEMA, str(write_gate.get("schema_version"))),
        check("write_gate_report_only", boundary.get("report_only") is True, str(boundary.get("report_only"))),
        check("work_order_count_matches_missing", work_order_count == missing_count, f"{work_order_count} == {missing_count}"),
        check("lane_counts_match_work_orders", public_count + ocr_count == work_order_count, f"{public_count}+{ocr_count} == {work_order_count}"),
        check("public_rows_match_count", len(public_rows) == public_count, f"{len(public_rows)} == {public_count}"),
        check("ocr_rows_match_count", len(ocr_rows) == ocr_count, f"{len(ocr_rows)} == {ocr_count}"),
        check(
            "recovery_lane_classified",
            (public_count > 0 or ocr_count > 0)
            and (
                packet["mixed_lane_status"]["mixed_recovery_required"]
                or packet["mixed_lane_status"]["ocr_only_recovery_required"]
                or packet["mixed_lane_status"]["public_only_recovery_required"]
            ),
            f"public={public_count} ocr={ocr_count}",
        ),
        check("write_gate_target_matches_public_candidates", write_target_count == public_count, f"{write_target_count} == {public_count}"),
        check("write_gate_planned_upload_matches_public_candidates", planned_upload_count == public_count, f"{planned_upload_count} == {public_count}"),
        check("write_gate_blocks_partial_public_subset", "quality_counts_match_poster_targets" in write_failed_ids, ",".join(write_failed_ids)),
        check("work_orders_raw_url_leak_free", int_value(work_orders.get("raw_public_url_leak_count")) == 0, str(work_orders.get("raw_public_url_leak_count"))),
        check("controller_packet_leak_free", packet_leak_count == 0, str(packet_leak_count)),
    ]
    for key in WORK_ORDER_FALSE_KEYS:
        checks.append(check(f"work_orders_{key}_false", bool(work_orders.get(key)) is False, str(work_orders.get(key))))
    if bool(write_gate.get("execute_allowed_now")):
        checks.append(check("write_gate_execute_allowed_now_false", False, str(write_gate.get("execute_allowed_now"))))
    else:
        checks.append(check("write_gate_execute_allowed_now_false", True, str(write_gate.get("execute_allowed_now"))))
    if int_value(write_gate.get("cloudbase_storage_write_allowed_count")):
        checks.append(check("write_gate_cloudbase_storage_write_allowed_count_zero", False, str(write_gate.get("cloudbase_storage_write_allowed_count"))))
    else:
        checks.append(check("write_gate_cloudbase_storage_write_allowed_count_zero", True, str(write_gate.get("cloudbase_storage_write_allowed_count"))))
    for key in WRITE_GATE_BOUNDARY_FALSE_KEYS:
        checks.append(check(f"write_gate_boundary_{key}_false", bool(boundary.get(key)) is False, str(boundary.get(key))))
    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    if failed:
        decision = BLOCKED_DECISION
    elif packet["mixed_lane_status"]["ocr_only_recovery_required"]:
        decision = OCR_ONLY_READY_DECISION
    else:
        decision = READY_DECISION
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "report_only": True,
        "source_work_orders_report": safe_path(work_orders_path),
        "source_write_gate_report": safe_path(write_gate_path),
        "controller_release_packet": packet,
        "counts": packet["counts"],
        "mixed_lane_status": packet["mixed_lane_status"],
        "checks": checks,
        "failed_required_check_ids": failed,
        "raw_url_private_path_secret_leak_count": packet_leak_count,
        "controller_release_created_by_this_packet": False,
        "public_upload_allowed_now": False,
        "article_image_ocr_allowed_now": False,
        "cloudbase_storage_write_allowed_now": False,
        "package_patch_allowed_now": False,
        "db2_write_executed": False,
        "db3_write_executed": False,
        "cloudrun_deploy_executed": False,
        "cloudbase_sync_executed": False,
        "miniprogram_upload_executed": False,
        "wechat_review_submitted": False,
        "public_release_executed": False,
        "next_gate": "Complete public-cover verification plus article-image OCR recovery, then rebuild quality/write-gate evidence before any CloudBase upload or package patch.",
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = as_dict(report.get("counts"))
    lines = [
        "# Weekly Poster Recovery Split Controller Packet",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Missing internal posters: `{counts.get('missing_internal_poster_count')}`",
        f"- Public upload candidates: `{counts.get('public_url_upload_candidate_count')}`",
        f"- Article-image OCR recovery rows: `{counts.get('article_image_ocr_recovery_count')}`",
        f"- Write-gate target count: `{counts.get('write_gate_target_count')}`",
        f"- Failed required checks: `{len(report['failed_required_check_ids'])}`",
        f"- Leak count: `{report['raw_url_private_path_secret_leak_count']}`",
        "",
        "Boundary: report-only split controller packet. No image download, OCR, vision API call, CloudBase upload, package patch, DB write, deploy, sync, mini-program upload, review, release, credential read, or secret-file read occurred.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-orders", type=Path, default=DEFAULT_WORK_ORDERS)
    parser.add_argument("--write-gate", type=Path, default=DEFAULT_WRITE_GATE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--public-limit", type=int, default=8)
    parser.add_argument("--ocr-limit", type=int, default=12)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_packet(args.work_orders, args.write_gate, args.public_limit, args.ocr_limit)
    write_json(args.report, report)
    write_scorecard(args.scorecard, report)
    print(json.dumps({"decision": report["decision"], "report": safe_path(args.report)}, ensure_ascii=False))
    return 0 if not report["failed_required_check_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
