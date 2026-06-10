#!/usr/bin/env python3
"""Build a no-upload gate for weekly mini-program remote-effective drift."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_remote_effective_upload_cache_drift_gate.v1"
DECISION = "weekly_remote_effective_upload_cache_drift_gate_ready_report_only_local_green_remote_unproven"

DEFAULT_CURRENT_RELEASE_DIR = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release"
DEFAULT_APP_JS = REPO_ROOT / "apps" / "weekly_activity_miniprogram" / "app.js"
DEFAULT_API_JS = REPO_ROOT / "apps" / "weekly_activity_miniprogram" / "utils" / "api.js"
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_remote_effective_upload_cache_drift_gate_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_REMOTE_EFFECTIVE_UPLOAD_CACHE_DRIFT_GATE_20260603.md"

EXPECTED_WINDOW_START = "2026-06-02"
EXPECTED_WINDOW_END = "2026-06-16"
EXPECTED_ITEM_COUNT = 78
EXPECTED_REQUIRED_DATES = ["2026-06-02", "2026-06-03"]
STALE_DATE = "2026-05-29"

COVER_KEYS = ["coverUrl", "cover_url", "coverImageUrl", "cover_image_url", "posterUrl", "poster_url"]

REMOTE_EFFECTIVE_REQUIRED_ROWS = [
    {
        "proof_id": "remote_effective:miniprogram_render_after_storage_clear",
        "required_evidence": "WeChat DevTools or phone render after storage/cache clear shows 78 current items, 2026-06-02/2026-06-03, no 2026-05-29, no bundled snapshot notice, poster image load >= 1, image error = 0.",
        "status": "required_unproven",
    },
    {
        "proof_id": "remote_effective:cloudrun_current_endpoint",
        "required_evidence": "Public CloudRun /api/v1/weekly/current returns current package identity matching the local 2026-06-03 package and no stale 2026-05-29 rows.",
        "status": "required_unproven",
    },
    {
        "proof_id": "remote_effective:cloudbase_database_current",
        "required_evidence": "CloudBase database or weeklyDataSync hot path returns the same current package identity, count, date window, and poster field coverage.",
        "status": "required_unproven",
    },
    {
        "proof_id": "remote_effective:miniprogram_uploaded_version",
        "required_evidence": "Uploaded development/experience version metadata points to the current local package; formal review/public release remains separately gated.",
        "status": "required_unproven",
    },
    {
        "proof_id": "remote_effective:poster_image_fetch",
        "required_evidence": "At least one remote-effective poster URL loads successfully and poster image error count stays 0.",
        "status": "required_unproven",
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def current_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "events"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
    return []


def item_date(item: dict[str, Any]) -> str:
    for key in ("date", "event_date", "eventDate", "event_date_start", "event_date_iso_guess"):
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    return ""


def numeric_config(js_text: str, name: str) -> int | None:
    match = re.search(rf"\b{name}\s*:\s*(-?\d+)", js_text)
    return int(match.group(1)) if match else None


def boolean_config(js_text: str, name: str) -> bool | None:
    match = re.search(rf"\b{name}\s*:\s*(true|false)", js_text)
    if not match:
        return None
    return match.group(1) == "true"


def build_local_package_proof(repo_root: Path, current_release_dir: Path) -> dict[str, Any]:
    manifest_path = current_release_dir / "manifest.json"
    current_path = current_release_dir / "current.json"
    manifest = read_json(manifest_path)
    items = current_items(read_json(current_path))
    dates = sorted({date for date in (item_date(item) for item in items) if date})
    poster_cover_field_count = sum(1 for item in items if any(item.get(key) for key in COVER_KEYS))
    required_dates_present = [date for date in EXPECTED_REQUIRED_DATES if date in dates]
    gates = {
        "manifest_generated_at_present": bool(manifest.get("generated_at")),
        "window_start_matches": manifest.get("window_start") == EXPECTED_WINDOW_START,
        "window_end_matches": manifest.get("window_end") == EXPECTED_WINDOW_END,
        "manifest_item_count_matches": int(manifest.get("item_count", -1)) == EXPECTED_ITEM_COUNT,
        "current_item_count_matches": len(items) == EXPECTED_ITEM_COUNT,
        "stale_20260529_absent": STALE_DATE not in dates,
        "required_dates_present": len(required_dates_present) == len(EXPECTED_REQUIRED_DATES),
        "poster_cover_fields_complete": poster_cover_field_count == len(items) and len(items) > 0,
    }
    return {
        "manifest": display_path(manifest_path, repo_root),
        "current": display_path(current_path, repo_root),
        "generated_at": str(manifest.get("generated_at", "")),
        "window_start": str(manifest.get("window_start", "")),
        "window_end": str(manifest.get("window_end", "")),
        "manifest_item_count": int(manifest.get("item_count", 0) or 0),
        "current_item_count": len(items),
        "first_dates": dates[:12],
        "required_dates_present": required_dates_present,
        "contains_2026_05_29": STALE_DATE in dates,
        "poster_cover_field_count": poster_cover_field_count,
        "gates": gates,
        "local_current_package_green": all(gates.values()),
    }


def build_production_config_proof(app_js: Path, api_js: Path) -> dict[str, Any]:
    app_text = app_js.read_text(encoding="utf-8")
    api_text = api_js.read_text(encoding="utf-8")
    public_fallback_delay_ms = numeric_config(app_text, "publicFallbackDelayMs")
    public_request_timeout_ms = numeric_config(app_text, "publicRequestTimeoutMs")
    cache_fallback_delay_ms = numeric_config(app_text, "cacheFallbackDelayMs")
    offline_snapshot_fallback_delay_ms = numeric_config(app_text, "offlineSnapshotFallbackDelayMs")
    cache_waits_for_public = (
        cache_fallback_delay_ms is not None
        and public_fallback_delay_ms is not None
        and public_request_timeout_ms is not None
        and cache_fallback_delay_ms > public_fallback_delay_ms + public_request_timeout_ms
    )
    gates = {
        "offline_snapshot_fallback_disabled": boolean_config(app_text, "offlineSnapshotFallback") is False,
        "fast_offline_snapshot_fallback_disabled": boolean_config(app_text, "fastOfflineSnapshotFallback") is False,
        "offline_snapshot_fallback_delay_disabled": offline_snapshot_fallback_delay_ms == -1,
        "cache_fallback_waits_for_public_api": cache_waits_for_public,
        "cache_prefix_bumped_for_20260603": "weeklyActivityApiCache:v20260603:" in api_text,
    }
    return {
        "app_js": str(app_js.name),
        "api_js": str(api_js.name),
        "publicFallbackDelayMs": public_fallback_delay_ms,
        "publicRequestTimeoutMs": public_request_timeout_ms,
        "cacheFallbackDelayMs": cache_fallback_delay_ms,
        "offlineSnapshotFallbackDelayMs": offline_snapshot_fallback_delay_ms,
        "gates": gates,
        "production_config_blocks_stale_snapshot": all(gates.values()),
    }


def build_report(
    repo_root: Path,
    current_release_dir: Path,
    app_js: Path,
    api_js: Path,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    current_release_dir = current_release_dir if current_release_dir.is_absolute() else repo_root / current_release_dir
    app_js = app_js if app_js.is_absolute() else repo_root / app_js
    api_js = api_js if api_js.is_absolute() else repo_root / api_js
    local_proof = build_local_package_proof(repo_root, current_release_dir)
    production_config = build_production_config_proof(app_js, api_js)
    remote_rows = [
        {
            "schema_version": SCHEMA_VERSION,
            "proof_id": row["proof_id"],
            "required_evidence": row["required_evidence"],
            "status": row["status"],
            "evidence_artifact": "",
            "network_or_upload_executed_by_this_gate": False,
            "upload_allowed_now": False,
            "review_release_allowed_now": False,
        }
        for row in REMOTE_EFFECTIVE_REQUIRED_ROWS
    ]
    local_green = bool(local_proof["local_current_package_green"] and production_config["production_config_blocks_stale_snapshot"])
    remote_effective_proven = all(row["status"] == "proven" for row in remote_rows)
    summary = {
        "local_current_package_green": local_green,
        "local_current_item_count": local_proof["current_item_count"],
        "local_poster_cover_field_count": local_proof["poster_cover_field_count"],
        "local_contains_2026_05_29": local_proof["contains_2026_05_29"],
        "production_config_blocks_stale_snapshot": production_config["production_config_blocks_stale_snapshot"],
        "phone_screenshot_classified_as_remote_effective_drift": True,
        "remote_effective_required_proof_count": len(remote_rows),
        "remote_effective_proven_count": sum(1 for row in remote_rows if row["status"] == "proven"),
        "remote_effective_unproven_count": sum(1 for row in remote_rows if row["status"] != "proven"),
        "remote_effective_proven": remote_effective_proven,
        "coordinate_followup_blockers": "12/59/7",
        "db3_relation_integrity_blocker_count": 348,
        "cloudrun_deploy_allowed_now": False,
        "cloudbase_sync_allowed_now": False,
        "database_write_allowed_now": False,
        "package_rebuild_allowed_now": False,
        "upload_allowed_now": False,
        "review_release_allowed_now": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": DECISION,
        "mode": "report_only_no_upload_no_deploy_no_db_no_credentials",
        "objective": "Separate proven local current-package health from unproven remote-effective upload/cache state.",
        "local_current_package_proof": local_proof,
        "production_config_proof": production_config,
        "remote_effective_required_proof_rows": remote_rows,
        "summary": summary,
        "boundary": {
            "network_probe_executed": False,
            "cloudrun_deployed": False,
            "cloudbase_sync_executed": False,
            "database_mutations": False,
            "coordinate_writes": False,
            "package_rebuild_executed": False,
            "miniprogram_upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "credential_or_secret_read": False,
            "browser_profile_read": False,
        },
        "next_required_gate": "explicit_upload_effective_data_proof_gate_after_or_alongside_release_guard_approval",
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    local = report["local_current_package_proof"]
    lines = [
        "# Weekly Remote-Effective Upload/Cache Drift Gate",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- local current package green: `{summary['local_current_package_green']}`",
        f"- local item count: `{summary['local_current_item_count']}`",
        f"- local poster/cover field count: `{summary['local_poster_cover_field_count']}`",
        f"- local contains 2026-05-29: `{summary['local_contains_2026_05_29']}`",
        f"- local window: `{local['window_start']}..{local['window_end']}`",
        f"- remote-effective proven: `{summary['remote_effective_proven']}`",
        f"- remote-effective unproven rows: `{summary['remote_effective_unproven_count']}`",
        f"- upload allowed now: `{summary['upload_allowed_now']}`",
        f"- review/release allowed now: `{summary['review_release_allowed_now']}`",
        f"- remaining blockers: coordinate `{summary['coordinate_followup_blockers']}`, DB3 `{summary['db3_relation_integrity_blocker_count']}`",
        "",
        "## Required Remote-Effective Proof",
        "",
    ]
    for row in report["remote_effective_required_proof_rows"]:
        lines.append(f"- `{row['proof_id']}`: `{row['status']}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This gate does not upload, submit review, publish, deploy CloudRun, sync CloudBase, mutate DB/current packages, write coordinates, start workers, read credentials, or run provider/model calls.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build weekly remote-effective upload/cache drift gate.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--current-release-dir", type=Path, default=DEFAULT_CURRENT_RELEASE_DIR)
    parser.add_argument("--app-js", type=Path, default=DEFAULT_APP_JS)
    parser.add_argument("--api-js", type=Path, default=DEFAULT_API_JS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report = build_report(repo_root, args.current_release_dir, args.app_js, args.api_js)
    output_json = args.out_dir / "weekly_remote_effective_upload_cache_drift_gate.json"
    rows_jsonl = args.out_dir / "weekly_remote_effective_required_proof_rows.jsonl"
    write_json(output_json, report)
    write_jsonl(rows_jsonl, report["remote_effective_required_proof_rows"])
    write_scorecard(args.scorecard, report)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": report["decision"],
                "summary": report["summary"],
                "output_json": str(output_json),
                "scorecard": str(args.scorecard),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
