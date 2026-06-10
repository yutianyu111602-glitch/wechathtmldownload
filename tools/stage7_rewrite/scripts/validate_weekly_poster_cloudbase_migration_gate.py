#!/usr/bin/env python
"""Validate the explicit CloudBase poster migration write gate.

This script is report-only. It consumes the dry-run poster migration plan and
the release package quality gate report. It never downloads posters, calls
CloudBase, patches package files, deploys, or syncs databases.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_poster_cloudbase_migration_write_gate.v1"
POSTER_MIGRATION_FIXABLE_FAILURES = {
    "missing_internal_poster_file_id",
    "invalid_internal_poster_file_id_format",
    "invalid_poster_storage",
    "public_or_temp_poster_url",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poster-migration-report", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-min-items", type=int, default=1)
    parser.add_argument("--confirm-token-prefix", default="ENABLE_CLOUDBASE_POSTER_MIGRATION")
    args = parser.parse_args(argv)

    poster = read_json(args.poster_migration_report)
    quality = read_json(args.quality_report)

    planned_uploads = as_list(poster.get("planned_uploads"))
    uploads = as_list(poster.get("uploads"))
    hard_failures = set(str(v) for v in as_list(quality.get("hard_failures")))
    target_count = int(poster.get("target_count") or 0)
    missing_internal = int(quality.get("missing_internal_poster_count") or 0)
    public_urls = int(
        quality.get(
            "public_wechat_or_qpic_poster_count",
            quality.get("public_wechat_poster_url_count") or 0,
        )
        or 0
    )
    public_or_temp_urls = int(quality.get("public_or_temp_poster_url_count") or public_urls or 0)
    invalid_file_ids = int(quality.get("invalid_internal_poster_file_id_count") or 0)
    invalid_storage = int(quality.get("invalid_poster_storage_count") or 0)
    item_count = int(quality.get("item_count") or 0)
    cloud_dir = str(poster.get("cloud_dir") or "")
    token_suffix = cloud_dir.rstrip("/").rsplit("/", 1)[-1] if cloud_dir else "UNKNOWN"
    required_confirm_token = f"{args.confirm_token_prefix}_{token_suffix}"

    checks = [
        ("poster_report_requested_no_write", poster.get("requested_write") is False),
        ("poster_report_is_dry_run", poster.get("write") is False and poster.get("dry_run") is True),
        ("poster_report_has_no_uploads", len(uploads) == 0),
        ("poster_report_has_no_migration", int(poster.get("migrated_count") or 0) == 0),
        ("poster_report_has_no_patch", int(poster.get("patched_occurrences") or 0) == 0),
        ("poster_report_confirm_token_matches_week_tag", poster.get("confirm_token_required") == required_confirm_token),
        ("planned_uploads_match_targets", len(planned_uploads) == target_count),
        ("quality_failed_only_on_poster_migration_fixable_fields", bool(hard_failures) and hard_failures.issubset(POSTER_MIGRATION_FIXABLE_FAILURES)),
        ("quality_counts_match_poster_targets", missing_internal == target_count and public_or_temp_urls >= target_count),
        ("quality_has_no_route_or_provenance_drift", int(quality.get("city_route_mismatch_count") or 0) == 0 and int(quality.get("manifest_provenance_issue_count") or 0) == 0),
        ("quality_item_count_meets_minimum", item_count >= args.expected_min_items),
    ]
    failed = [check_id for check_id, ok in checks if not ok]
    write_gate_ready = not failed and target_count > 0

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "poster_migration_report": str(args.poster_migration_report),
        "quality_report": str(args.quality_report),
        "write_gate_ready": write_gate_ready,
        "execute_allowed_now": False,
        "cloudbase_storage_write_allowed_count": 0,
        "required_confirm_token": required_confirm_token,
        "poster_report_confirm_token_required": poster.get("confirm_token_required", ""),
        "failed_check_ids": failed,
        "target_count": target_count,
        "planned_upload_count": len(planned_uploads),
        "upload_count": len(uploads),
        "migrated_count": int(poster.get("migrated_count") or 0),
        "patched_occurrences": int(poster.get("patched_occurrences") or 0),
        "quality_item_count": item_count,
        "missing_internal_poster_count": missing_internal,
        "public_wechat_poster_url_count": public_urls,
        "public_wechat_or_qpic_poster_count": public_urls,
        "public_or_temp_poster_url_count": public_or_temp_urls,
        "invalid_internal_poster_file_id_count": invalid_file_ids,
        "invalid_poster_storage_count": invalid_storage,
        "hard_failures": sorted(hard_failures),
        "planned_uploads": planned_uploads,
        "boundary": {
            "report_only": True,
            "downloads_executed": False,
            "cloudbase_storage_write_executed": False,
            "package_patch_executed": False,
            "deploy_executed": False,
            "cloudbase_db_write_executed": False,
            "miniprogram_upload_executed": False,
        },
    }
    write_json(args.report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if write_gate_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
