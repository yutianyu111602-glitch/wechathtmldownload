#!/usr/bin/env python3
"""Consume source-fetch runtime reports into a no-coordinate-write packet."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_source_fetch_result_acceptance_packet.v1"
BLOCKED_DECISION = "weekly_current_missing_geo_source_fetch_result_acceptance_blocked_no_coordinate_write"
READY_DECISION = "weekly_current_missing_geo_source_fetch_result_acceptance_ready_for_review_no_coordinate_write"

DEFAULT_RUNTIME_DIR = REPORTS_ROOT / "weekly_current_missing_geo_source_fetch_runtime_20260603_060305"
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_source_fetch_result_acceptance_packet_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_RESULT_ACCEPTANCE_PACKET_20260603.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


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


def acceptance_row(row: dict[str, Any]) -> dict[str, Any]:
    fetch_status = str(row.get("fetch_status", ""))
    blocked_reason = str(row.get("blocked_reason", ""))
    address_candidates = list(row.get("address_candidates", []))
    accepted = fetch_status == "fetched" and bool(address_candidates) and not blocked_reason
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": str(row.get("task_id", "")),
        "current_item_id": str(row.get("current_item_id", "")),
        "event_id": str(row.get("event_id", "")),
        "source_url_hash": str(row.get("source_url_hash", "")),
        "source_account_name": str(row.get("source_account_name", "")),
        "runtime_fetch_status": fetch_status,
        "runtime_blocked_reason": blocked_reason,
        "accepted_source_evidence": accepted,
        "address_candidate_count": len(address_candidates),
        "coordinate_candidate_count": len(list(row.get("coordinate_candidates", []))),
        "needs_provider_verification": bool(row.get("needs_provider_verification", True)),
        "provider_or_geocode_call_allowed_now": False,
        "coordinate_write_allowed_now": False,
        "db_write_allowed_now": False,
        "registry_mutation_allowed_now": False,
        "current_package_mutation_allowed_now": False,
        "upload_review_release_allowed_now": False,
        "next_gate": "manual_or_runtime_source_evidence_review_before_provider_or_coordinate_gate",
    }


def build_report(repo_root: Path, runtime_dir: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    runtime_dir = runtime_dir if runtime_dir.is_absolute() else repo_root / runtime_dir
    summary_path = runtime_dir / "weekly_current_missing_geo_source_fetch_runtime_summary.json"
    results_path = runtime_dir / "weekly_current_missing_geo_source_fetch_runtime_results.jsonl"
    blockers_path = runtime_dir / "weekly_current_missing_geo_source_fetch_runtime_blockers.jsonl"
    runtime_summary = load_json(summary_path)
    results = load_jsonl(results_path)
    blockers = load_jsonl(blockers_path)
    rows = [acceptance_row(row) for row in results]
    reason_counts = Counter(row["runtime_blocked_reason"] for row in rows if row["runtime_blocked_reason"])
    accepted_count = sum(1 for row in rows if row["accepted_source_evidence"])
    blocked_count = len(rows) - accepted_count
    decision = READY_DECISION if accepted_count else BLOCKED_DECISION

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "mode": "report_only_no_coordinate_write_no_provider_no_db_no_upload",
        "inputs": {
            "runtime_dir": display_path(runtime_dir, repo_root),
            "runtime_summary": display_path(summary_path, repo_root),
            "runtime_results": display_path(results_path, repo_root),
            "runtime_blockers": display_path(blockers_path, repo_root),
        },
        "summary": {
            "runtime_worker_task_count": int(runtime_summary.get("worker_task_count", 0) or 0),
            "runtime_completed_count": int(runtime_summary.get("completed_count", 0) or 0),
            "runtime_blocked_count": int(runtime_summary.get("blocked_count", 0) or 0),
            "acceptance_row_count": len(rows),
            "accepted_source_evidence_count": accepted_count,
            "blocked_acceptance_count": blocked_count,
            "wechat_environment_verification_required_count": int(reason_counts.get("wechat_environment_verification_required", 0)),
            "provider_or_geocode_call_allowed_count": 0,
            "coordinate_write_allowed_count": 0,
            "db_write_allowed_count": 0,
            "raw_url_private_path_secret_leak_count": int(runtime_summary.get("raw_url_private_path_secret_leak_count", 0) or 0),
            "network_scope_drift_count": int(runtime_summary.get("network_scope_drift_count", 0) or 0),
        },
        "runtime_summary_decision": runtime_summary.get("decision", ""),
        "blocked_reason_counts": dict(reason_counts),
        "acceptance_rows": rows,
        "blocked_rows": [row for row in rows if not row["accepted_source_evidence"]],
        "boundary": {
            "provider_or_geocode_calls": False,
            "coordinate_writes": False,
            "database_mutations": False,
            "registry_mutations": False,
            "package_rebuild_executed": False,
            "cloudrun_deployed": False,
            "cloudbase_sync_executed": False,
            "upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "secret_files_read": False,
            "browser_profile_read": False,
        },
        "next_required_gate": "resolve_wechat_environment_verification_or_provide_accepted_no_fetch_disposition",
        "consumer_notification_fields": [
            "decision",
            "summary",
            "blocked_reason_counts",
            "boundary",
            "next_required_gate",
        ],
        "runtime_blocker_sample_count": len(blockers),
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Weekly Current Missing-Geo Source-Fetch Result Acceptance Packet",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- runtime completed count: `{summary['runtime_completed_count']}`",
        f"- runtime blocked count: `{summary['runtime_blocked_count']}`",
        f"- accepted source evidence count: `{summary['accepted_source_evidence_count']}`",
        f"- wechat environment verification required count: `{summary['wechat_environment_verification_required_count']}`",
        f"- provider/geocode allowed count: `{summary['provider_or_geocode_call_allowed_count']}`",
        f"- coordinate write allowed count: `{summary['coordinate_write_allowed_count']}`",
        "",
        "## Boundary",
        "",
        "This packet consumes runtime reports only. It does not call providers, write coordinates, mutate DB/registry/current packages, sync CloudBase, upload, review, release, or read credentials.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build source-fetch result acceptance packet.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report = build_report(repo_root, args.runtime_dir)
    output_json = args.out_dir / "weekly_current_missing_geo_source_fetch_result_acceptance_packet.json"
    rows_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_result_acceptance_rows.jsonl"
    blocked_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_result_acceptance_blocked_rows.jsonl"
    write_json(output_json, report)
    write_jsonl(rows_jsonl, report["acceptance_rows"])
    write_jsonl(blocked_jsonl, report["blocked_rows"])
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
