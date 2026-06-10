#!/usr/bin/env python3
"""Build a no-write disposition queue for blocked weekly source-fetch rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_source_fetch_disposition_queue.v1"
DECISION = "weekly_current_missing_geo_source_fetch_disposition_queue_ready_report_only"

DEFAULT_FOLLOWUP_PACKET = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_source_fetch_blocker_followup_packet_20260603"
    / "weekly_current_missing_geo_source_fetch_blocker_followup_packet.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_source_fetch_disposition_queue_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_DISPOSITION_QUEUE_20260603.md"

RAW_LEAK_PATTERNS = [
    re.compile(r"https://mp\.weixin\.qq\.com/[^\s\"']+", re.I),
    re.compile(r"[A-Za-z]:\\Users\\pc\\", re.I),
    re.compile(r"/home/pc/", re.I),
    re.compile(r"(cookie|token|secret|password|authorization)\s*[:=]\s*[^,\s\"'}]+", re.I),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def find_raw_leaks(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for pattern in RAW_LEAK_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            findings.append({"pattern": pattern.pattern, "count": len(matches)})
    return findings


def followup_rows(packet: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(packet.get("followup_rows") or [])
    if rows:
        return rows
    return list(packet.get("manual_source_evidence_review_rows") or [])


def recommended_lanes(row: dict[str, Any]) -> list[str]:
    lanes: list[str] = []
    if row.get("manual_source_evidence_review_required"):
        lanes.append("manual_source_evidence_review")
    if row.get("source_cache_lookup_candidate"):
        lanes.append("source_cache_lookup")
    if row.get("authenticated_source_cache_release_required"):
        lanes.append("authenticated_source_cache_release")
    if row.get("accepted_no_fetch_disposition_required"):
        lanes.append("accepted_no_fetch_disposition")
    return lanes or ["manual_source_evidence_review"]


def build_disposition_row(index: int, row: dict[str, Any]) -> dict[str, Any]:
    account_name = str(row.get("source_account_name") or "")
    blocker_reasons = [str(item) for item in row.get("input_blocker_reasons", [])]
    if not blocker_reasons and row.get("runtime_blocked_reason"):
        blocker_reasons = [str(row["runtime_blocked_reason"])]
    lanes = recommended_lanes(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "row_id": f"source_fetch_disposition:{index:03d}:{str(row.get('source_url_hash', ''))[:16]}",
        "followup_id": str(row.get("followup_id") or ""),
        "task_id": str(row.get("task_id") or ""),
        "current_item_id": str(row.get("current_item_id") or ""),
        "event_id": str(row.get("event_id") or ""),
        "source_url_hash": str(row.get("source_url_hash") or ""),
        "account_hash": sha256_text(account_name) if account_name else "",
        "blocker_reason": blocker_reasons[0] if blocker_reasons else "",
        "blocker_reasons": blocker_reasons,
        "recommended_lane": lanes[0],
        "recommended_lanes": lanes,
        "manual_review_status": "pending",
        "source_cache_hit_status": "not_checked",
        "authenticated_release_required": bool(row.get("authenticated_source_cache_release_required")),
        "accepted_no_fetch_disposition": "pending",
        "source_evidence_artifact_ref": "",
        "address_or_poi_evidence": "",
        "reviewer_disposition": "",
        "reviewer_identity_or_artifact": "",
        "manual_source_evidence_review_required": bool(row.get("manual_source_evidence_review_required")),
        "source_cache_lookup_candidate": bool(row.get("source_cache_lookup_candidate")),
        "source_cache_lookup_allowed_now": False,
        "network_fetch_allowed_now": False,
        "docker_worker_allowed_now": False,
        "deepseek_or_model_call_allowed_now": False,
        "provider_or_geocode_call_allowed_now": False,
        "coordinate_write_allowed": False,
        "db_write_allowed": False,
        "registry_mutation_allowed_now": False,
        "cloudbase_sync_allowed_now": False,
        "upload_review_release_allowed_now": False,
        "raw_source_url_output_allowed": False,
        "credential_or_secret_read_allowed_now": False,
        "browser_profile_read_allowed_now": False,
        "next_required_gate": "manual_or_source_cache_disposition_acceptance_before_coordinate_write_gate",
    }


def build_report(repo_root: Path, followup_packet_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repo_root = repo_root.resolve()
    followup_packet_path = followup_packet_path if followup_packet_path.is_absolute() else repo_root / followup_packet_path
    packet = load_json(followup_packet_path)
    rows = [build_disposition_row(index, row) for index, row in enumerate(followup_rows(packet), start=1)]
    lane_counts = Counter(row["recommended_lane"] for row in rows)
    blocker_counts = Counter(reason for row in rows for reason in row["blocker_reasons"])
    leak_findings = find_raw_leaks(rows)
    summary = {
        "input_followup_row_count": len(followup_rows(packet)),
        "disposition_row_count": len(rows),
        "manual_review_pending_count": sum(1 for row in rows if row["manual_review_status"] == "pending"),
        "source_cache_not_checked_count": sum(1 for row in rows if row["source_cache_hit_status"] == "not_checked"),
        "accepted_no_fetch_pending_count": sum(1 for row in rows if row["accepted_no_fetch_disposition"] == "pending"),
        "authenticated_release_required_count": sum(1 for row in rows if row["authenticated_release_required"]),
        "accepted_source_evidence_count": 0,
        "source_cache_lookup_allowed_now_count": 0,
        "provider_or_geocode_call_allowed_count": 0,
        "coordinate_write_allowed_count": 0,
        "db_write_allowed_count": 0,
        "raw_url_output_count": 0,
        "raw_url_private_path_secret_leak_count": sum(finding["count"] for finding in leak_findings),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": DECISION,
        "mode": "report_only_no_fetch_no_write_no_credentials",
        "inputs": {
            "source_fetch_blocker_followup_packet": display_path(followup_packet_path, repo_root),
        },
        "summary": summary,
        "recommended_lane_counts": dict(sorted(lane_counts.items())),
        "blocker_reason_counts": dict(sorted(blocker_counts.items())),
        "boundary": {
            "network_fetch_executed": False,
            "docker_worker_executed": False,
            "deepseek_or_model_calls": False,
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
            "credential_or_secret_read": False,
            "browser_profile_read": False,
            "raw_source_url_output": False,
        },
        "leak_findings": leak_findings,
        "next_required_gate": "manual_source_evidence_acceptance_or_accepted_no_fetch_disposition_or_explicit_authenticated_source_cache_release",
        "consumer_notification_fields": [
            "decision",
            "summary",
            "recommended_lane_counts",
            "blocker_reason_counts",
            "boundary",
            "next_required_gate",
        ],
    }
    return report, rows


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# Weekly Current Missing-Geo Source-Fetch Disposition Queue",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- disposition rows: `{summary['disposition_row_count']}`",
        f"- manual review pending: `{summary['manual_review_pending_count']}`",
        f"- source-cache not checked: `{summary['source_cache_not_checked_count']}`",
        f"- accepted no-fetch pending: `{summary['accepted_no_fetch_pending_count']}`",
        f"- authenticated release required: `{summary['authenticated_release_required_count']}`",
        f"- accepted source evidence: `{summary['accepted_source_evidence_count']}`",
        f"- coordinate writes allowed: `{summary['coordinate_write_allowed_count']}`",
        f"- DB writes allowed: `{summary['db_write_allowed_count']}`",
        f"- raw URL/private path/secret leak count: `{summary['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Boundary",
        "",
        "Report-only. No network fetch, Docker worker, DeepSeek/model/provider/geocode call, coordinate write, DB mutation, CloudBase sync, upload, review, release, credential read, browser profile read, or raw source URL output occurred.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build no-write source-fetch disposition queue.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--followup-packet", type=Path, default=DEFAULT_FOLLOWUP_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report, rows = build_report(repo_root, args.followup_packet)
    output_json = args.out_dir / "weekly_current_missing_geo_source_fetch_disposition_queue.json"
    rows_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_disposition_review_rows.jsonl"
    manual_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_manual_review_pending_rows.jsonl"
    source_cache_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_source_cache_pending_rows.jsonl"
    no_fetch_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_no_fetch_disposition_pending_rows.jsonl"
    write_json(output_json, report)
    write_jsonl(rows_jsonl, rows)
    write_jsonl(manual_jsonl, [row for row in rows if row["manual_review_status"] == "pending"])
    write_jsonl(source_cache_jsonl, [row for row in rows if row["source_cache_hit_status"] == "not_checked"])
    write_jsonl(no_fetch_jsonl, [row for row in rows if row["accepted_no_fetch_disposition"] == "pending"])
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
    return 0 if report["summary"]["raw_url_private_path_secret_leak_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
