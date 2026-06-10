#!/usr/bin/env python
"""Build a report-only review packet for public poster upload candidates.

Public WeChat/qpic cover images are not package truth. This packet verifies the
small public-upload subset from missing-poster work orders, keeps it separate
from article-image OCR recovery rows, and records that CloudBase upload/package
patch remains closed until a later explicit review/write gate.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "weekly_public_poster_upload_candidate_review_packet.v1"
READY_DECISION = "weekly_public_poster_upload_candidate_review_packet_ready_report_only_requires_main_poster_review"
NO_PUBLIC_READY_DECISION = "weekly_public_poster_upload_candidate_review_packet_not_applicable_report_only_no_public_candidates"
BLOCKED_DECISION = "weekly_public_poster_upload_candidate_review_packet_blocked_report_only"
WORK_ORDERS_SCHEMA = "weekly_missing_internal_poster_recovery_work_orders.v1"
WRITE_GATE_SCHEMA = "weekly_poster_cloudbase_migration_write_gate.v1"
SPLIT_PACKET_SCHEMA = "weekly_poster_recovery_split_controller_packet.v1"
DEFAULT_PUBLISH_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_weekly_daily_20260606_060904"
DEFAULT_WORK_ORDERS = DEFAULT_PUBLISH_DIR / "missing_internal_poster_recovery_work_orders.json"
DEFAULT_WRITE_GATE = DEFAULT_PUBLISH_DIR / "poster_cloudbase_migration_write_gate.json"
DEFAULT_SPLIT_PACKET = DEFAULT_PUBLISH_DIR / "poster_recovery_split_controller_packet.json"
DEFAULT_REPORT = DEFAULT_PUBLISH_DIR / "public_poster_upload_candidate_review_packet.json"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_PUBLIC_POSTER_UPLOAD_CANDIDATE_REVIEW_PACKET_20260606.md"
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})"
)
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
REVIEW_REQUIREMENTS = (
    "verify_public_cover_is_main_activity_poster_with_ocr_or_vision",
    "compare_cover_against_article_body_images_before_upload",
    "demote_weekly_or_monthly_overview_posters",
    "demote_qr_ticket_menu_logo_map_avatar_and_decorative_images",
    "preserve_backend_package_truth_as_cloudbase_file_id_only",
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


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            found = first_text(*value)
            if found:
                return found
        elif value is not None and str(value).strip():
            return str(value).strip()
    return ""


def sanitize_candidate(row: dict[str, Any]) -> dict[str, Any]:
    locator = as_dict(row.get("source_locator"))
    return {
        "id": first_text(row.get("id")),
        "title": first_text(row.get("title")),
        "lane": first_text(row.get("lane")),
        "event_date_start": first_text(row.get("event_date_start")),
        "event_date_end": first_text(row.get("event_date_end")),
        "city": [str(value) for value in as_list(row.get("city"))],
        "city_keys": [str(value) for value in as_list(row.get("city_keys"))],
        "venue": first_text(row.get("venue")),
        "account": first_text(row.get("account")),
        "planned_cloud_path": first_text(row.get("planned_cloud_path")),
        "planned_public_url_hash": first_text(row.get("planned_public_url_hash")),
        "public_poster_url_sha256": first_text(row.get("public_poster_url_sha256")),
        "requires_cloudbase_file_id": bool(row.get("requires_cloudbase_file_id")),
        "requires_main_poster_review": bool(row.get("requires_main_poster_review")),
        "candidate_ready_for_upload_now": False,
        "source_locator": {
            "source_locator_method": first_text(locator.get("source_locator_method")),
            "source_map_entry_present": bool(locator.get("source_map_entry_present")),
            "source_key_hash": first_text(locator.get("source_key")),
            "source_url_sha256": first_text(locator.get("source_url_sha256")),
            "source_action_available": bool(locator.get("source_action_available")),
            "source_published_at": first_text(locator.get("source_published_at")),
        },
        "review_requirements": list(REVIEW_REQUIREMENTS),
    }


def build_packet(work_orders_path: Path, write_gate_path: Path, split_packet_path: Path | None = None) -> dict[str, Any]:
    work_orders = read_json(work_orders_path)
    write_gate = read_json(write_gate_path)
    split_packet = read_json(split_packet_path) if split_packet_path and split_packet_path.exists() else None
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
    sanitized_candidates = [sanitize_candidate(row) for row in public_rows]
    packet = {
        "schema_version": f"{SCHEMA_VERSION}.controller_packet",
        "packet_status": (
            "not_applicable_no_public_candidates_report_only"
            if public_count == 0
            else "ready_for_public_candidate_review_report_only"
        ),
        "controller_release_created_by_this_packet": False,
        "public_cover_review_completed_by_this_packet": False,
        "public_upload_allowed_by_this_packet": False,
        "cloudbase_storage_write_allowed_by_this_packet": False,
        "package_patch_allowed_by_this_packet": False,
        "release_ready_by_this_packet": False,
        "backend_package_policy": "cloudbase_file_id_only_no_temp_url",
        "counts": {
            "missing_internal_poster_count": missing_count,
            "work_order_count": work_order_count,
            "public_upload_candidate_count": public_count,
            "article_image_ocr_recovery_count": ocr_count,
            "write_gate_target_count": write_target_count,
            "write_gate_planned_upload_count": planned_upload_count,
            "review_required_count": sum(1 for row in public_rows if row.get("requires_main_poster_review") is True),
            "candidate_ready_for_upload_now_count": 0,
        },
        "quality_status": {
            "public_subset_can_clear_quality_gate": False,
            "all_missing_posters_covered_by_public_candidates": public_count == missing_count and ocr_count == 0,
            "quality_counts_match_poster_targets_failed": "quality_counts_match_poster_targets" in write_failed_ids,
        },
        "public_upload_candidate_review_queue": sanitized_candidates,
        "next_required_actions": [
            "review_public_cover_against_article_body_images_and_ocr_layout",
            "accept_or_reject_each_public_cover_as_main_activity_poster",
            "continue_article_image_ocr_recovery_for_remaining_rows",
            "open_cloudbase_upload_write_gate_only_after_all_missing_posters_are_verified",
            "rerun_package_quality_and_readiness_after_cloudbase_file_id_patch",
        ],
        "stop_conditions": [
            "public_candidate_review_not_completed",
            "candidate_is_weekly_or_monthly_overview_cover",
            "candidate_is_qr_ticket_menu_logo_map_avatar_or_decorative_image",
            "article_image_ocr_recovery_rows_still_missing",
            "cloudbase_upload_or_package_patch_requested_without_confirm_token",
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
        check("ocr_rows_still_present", ocr_count > 0 and len(ocr_rows) == ocr_count, f"{len(ocr_rows)} == {ocr_count}"),
        check("write_gate_target_matches_public_candidates", write_target_count == public_count, f"{write_target_count} == {public_count}"),
        check("write_gate_planned_upload_matches_public_candidates", planned_upload_count == public_count, f"{planned_upload_count} == {public_count}"),
        check("write_gate_blocks_public_subset", "quality_counts_match_poster_targets" in write_failed_ids, ",".join(write_failed_ids)),
        check("public_subset_does_not_cover_all_missing", public_count < missing_count, f"{public_count} < {missing_count}"),
        check("all_public_candidates_require_main_poster_review", all(row.get("requires_main_poster_review") is True for row in public_rows), str(public_count)),
        check("all_public_candidates_have_planned_cloud_path", all(first_text(row.get("planned_cloud_path")).startswith("weekly-posters/") for row in public_rows), str(public_count)),
        check("all_public_candidates_have_redacted_public_hash", all(first_text(row.get("planned_public_url_hash")) or first_text(row.get("public_poster_url_sha256")) for row in public_rows), str(public_count)),
        check("work_orders_raw_url_leak_free", int_value(work_orders.get("raw_public_url_leak_count")) == 0, str(work_orders.get("raw_public_url_leak_count"))),
        check("controller_packet_leak_free", packet_leak_count == 0, str(packet_leak_count)),
    ]
    if split_packet is not None:
        split_counts = as_dict(split_packet.get("counts"))
        split_mixed = as_dict(split_packet.get("mixed_lane_status"))
        checks.extend(
            [
                check("split_packet_schema", split_packet.get("schema_version") == SPLIT_PACKET_SCHEMA, str(split_packet.get("schema_version"))),
                check("split_packet_public_count_matches", int_value(split_counts.get("public_url_upload_candidate_count")) == public_count, f"{int_value(split_counts.get('public_url_upload_candidate_count'))} == {public_count}"),
                check("split_packet_ocr_count_matches", int_value(split_counts.get("article_image_ocr_recovery_count")) == ocr_count, f"{int_value(split_counts.get('article_image_ocr_recovery_count'))} == {ocr_count}"),
                check("split_packet_keeps_public_subset_blocked", split_mixed.get("public_upload_subset_can_clear_quality_gate") is False, str(split_mixed.get("public_upload_subset_can_clear_quality_gate"))),
            ]
        )
    for key in WORK_ORDER_FALSE_KEYS:
        checks.append(check(f"work_orders_{key}_false", bool(work_orders.get(key)) is False, str(work_orders.get(key))))
    checks.append(check("write_gate_execute_allowed_now_false", bool(write_gate.get("execute_allowed_now")) is False, str(write_gate.get("execute_allowed_now"))))
    checks.append(check("write_gate_cloudbase_storage_write_allowed_count_zero", int_value(write_gate.get("cloudbase_storage_write_allowed_count")) == 0, str(write_gate.get("cloudbase_storage_write_allowed_count"))))
    for key in WRITE_GATE_BOUNDARY_FALSE_KEYS:
        checks.append(check(f"write_gate_boundary_{key}_false", bool(boundary.get(key)) is False, str(boundary.get(key))))
    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    if failed:
        decision = BLOCKED_DECISION
    elif public_count == 0:
        decision = NO_PUBLIC_READY_DECISION
    else:
        decision = READY_DECISION
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "report_only": True,
        "source_work_orders_report": safe_path(work_orders_path),
        "source_write_gate_report": safe_path(write_gate_path),
        "source_split_packet_report": safe_path(split_packet_path) if split_packet_path and split_packet_path.exists() else "",
        "controller_release_packet": packet,
        "counts": packet["counts"],
        "quality_status": packet["quality_status"],
        "checks": checks,
        "failed_required_check_ids": failed,
        "raw_url_private_path_secret_leak_count": packet_leak_count,
        "controller_release_created_by_this_packet": False,
        "public_cover_review_completed_by_this_packet": False,
        "public_upload_allowed_now": False,
        "cloudbase_storage_write_allowed_now": False,
        "package_patch_allowed_now": False,
        "db2_write_executed": False,
        "db3_write_executed": False,
        "cloudrun_deploy_executed": False,
        "cloudbase_sync_executed": False,
        "miniprogram_upload_executed": False,
        "wechat_review_submitted": False,
        "public_release_executed": False,
        "next_gate": "Perform source-backed main-poster review for the 4 public candidates and complete the 11 OCR recovery rows before any CloudBase upload/package patch.",
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = as_dict(report.get("counts"))
    quality = as_dict(report.get("quality_status"))
    lines = [
        "# Weekly Public Poster Upload Candidate Review Packet",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- decision: `{report.get('decision')}`",
        f"- report_only: `{report.get('report_only')}`",
        f"- public_upload_candidate_count: `{counts.get('public_upload_candidate_count')}`",
        f"- article_image_ocr_recovery_count: `{counts.get('article_image_ocr_recovery_count')}`",
        f"- candidate_ready_for_upload_now_count: `{counts.get('candidate_ready_for_upload_now_count')}`",
        f"- public_subset_can_clear_quality_gate: `{quality.get('public_subset_can_clear_quality_gate')}`",
        f"- failed_required_check_ids: `{', '.join(report.get('failed_required_check_ids') or [])}`",
        f"- leak_count: `{report.get('raw_url_private_path_secret_leak_count')}`",
        "",
        "Boundary: this packet does not download images, run OCR/vision, upload CloudBase Storage, patch packages, deploy, sync, upload a mini-program, submit review, or publish.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-orders", type=Path, default=DEFAULT_WORK_ORDERS)
    parser.add_argument("--write-gate", type=Path, default=DEFAULT_WRITE_GATE)
    parser.add_argument("--split-packet", type=Path, default=DEFAULT_SPLIT_PACKET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    split_packet = args.split_packet if args.split_packet and args.split_packet.exists() else None
    report = build_packet(args.work_orders, args.write_gate, split_packet)
    write_json(args.report, report)
    write_scorecard(args.scorecard, report)
    print(json.dumps({"decision": report["decision"], "report": safe_path(args.report)}, ensure_ascii=False))
    return 0 if not report["failed_required_check_ids"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
