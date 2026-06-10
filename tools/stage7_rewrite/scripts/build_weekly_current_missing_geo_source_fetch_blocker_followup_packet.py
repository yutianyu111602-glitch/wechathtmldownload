#!/usr/bin/env python3
"""Build no-write follow-up queues for blocked source-fetch rows."""
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

SCHEMA_VERSION = "weekly_current_missing_geo_source_fetch_blocker_followup_packet.v1"
DECISION = "weekly_current_missing_geo_source_fetch_blocker_followup_ready_report_only"

DEFAULT_ACCEPTANCE_PACKET = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_source_fetch_result_acceptance_packet_20260603"
    / "weekly_current_missing_geo_source_fetch_result_acceptance_packet.json"
)
DEFAULT_WORKER_CONTRACT = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_source_fetch_worker_contract_20260603"
    / "weekly_current_missing_geo_source_fetch_worker_contract.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_source_fetch_blocker_followup_packet_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_BLOCKER_FOLLOWUP_PACKET_20260603.md"

REQUIRED_MANUAL_REVIEW_FIELDS = [
    "current_item_id",
    "source_url_hash",
    "source_account_name",
    "source_evidence_artifact_ref",
    "address_or_poi_evidence",
    "reviewer_disposition",
    "reviewer_identity_or_artifact",
    "no_coordinate_write",
]

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


def source_cache_lookup_contract(source_url_hash: str) -> dict[str, Any]:
    return {
        "lookup_scope": "bounded_local_source_cache_only",
        "source_url_hash": source_url_hash,
        "raw_source_url_output_allowed": False,
        "network_fetch_allowed_now": False,
        "docker_worker_allowed_now": False,
        "credential_read_allowed_now": False,
        "browser_profile_read_allowed_now": False,
        "d_drive_unbounded_scan_allowed": False,
        "future_runtime_required": "separate_explicit_controller_release_required",
    }


def build_followup_row(
    index: int,
    acceptance_row: dict[str, Any],
    worker_task: dict[str, Any] | None,
) -> dict[str, Any]:
    source_url = str(worker_task.get("source_url", "")) if worker_task else ""
    expected_hash = str(acceptance_row.get("source_url_hash", ""))
    computed_hash = sha256_text(source_url) if source_url else ""
    hash_verified = bool(source_url) and bool(expected_hash) and computed_hash == expected_hash
    task_id = str(acceptance_row.get("task_id", ""))
    blocker_reasons: list[str] = []
    if not worker_task:
        blocker_reasons.append("worker_contract_task_missing")
    if worker_task and not hash_verified:
        blocker_reasons.append("source_url_hash_mismatch")
    if str(acceptance_row.get("runtime_blocked_reason", "")):
        blocker_reasons.append(str(acceptance_row.get("runtime_blocked_reason")))

    source_url_hash = expected_hash or computed_hash
    return {
        "schema_version": SCHEMA_VERSION,
        "followup_id": f"source_fetch_blocker_followup:{index:03d}:{source_url_hash[:16]}",
        "task_id": task_id,
        "current_item_id": str(acceptance_row.get("current_item_id", "")),
        "event_id": str(acceptance_row.get("event_id", "")),
        "source_account_name": str(acceptance_row.get("source_account_name", "")),
        "source_url_hash": source_url_hash,
        "title": str(worker_task.get("title", "")) if worker_task else "",
        "city": str(worker_task.get("city", "")) if worker_task else "",
        "venue_name": str(worker_task.get("venue_name", "")) if worker_task else "",
        "runtime_fetch_status": str(acceptance_row.get("runtime_fetch_status", "")),
        "runtime_blocked_reason": str(acceptance_row.get("runtime_blocked_reason", "")),
        "source_url_hash_verified_against_worker_contract": hash_verified,
        "input_blocker_reasons": blocker_reasons,
        "accepted_source_evidence_now": False,
        "manual_source_evidence_review_required": True,
        "source_cache_lookup_candidate": True,
        "authenticated_source_cache_release_required": True,
        "accepted_no_fetch_disposition_required": True,
        "required_manual_review_fields": REQUIRED_MANUAL_REVIEW_FIELDS,
        "source_cache_lookup_contract": source_cache_lookup_contract(source_url_hash),
        "network_fetch_allowed_now": False,
        "docker_worker_allowed_now": False,
        "deepseek_or_model_call_allowed_now": False,
        "provider_or_geocode_call_allowed_now": False,
        "coordinate_write_allowed_now": False,
        "db_write_allowed_now": False,
        "registry_mutation_allowed_now": False,
        "current_package_mutation_allowed_now": False,
        "cloudrun_deploy_allowed_now": False,
        "cloudbase_sync_allowed_now": False,
        "upload_review_release_allowed_now": False,
        "credential_or_secret_read_allowed_now": False,
        "browser_profile_read_allowed_now": False,
        "next_gate": "manual_source_evidence_or_source_cache_disposition_before_provider_coordinate_gate",
    }


def find_raw_leaks(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for pattern in RAW_LEAK_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            findings.append({"pattern": pattern.pattern, "count": len(matches)})
    return findings


def blocked_acceptance_rows(packet: dict[str, Any]) -> list[dict[str, Any]]:
    blocked_rows = list(packet.get("blocked_rows", []))
    if blocked_rows:
        return blocked_rows
    return [row for row in packet.get("acceptance_rows", []) if not bool(row.get("accepted_source_evidence"))]


def build_report(repo_root: Path, acceptance_packet_path: Path, worker_contract_path: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    acceptance_packet_path = acceptance_packet_path if acceptance_packet_path.is_absolute() else repo_root / acceptance_packet_path
    worker_contract_path = worker_contract_path if worker_contract_path.is_absolute() else repo_root / worker_contract_path
    acceptance_packet = load_json(acceptance_packet_path)
    worker_contract = load_json(worker_contract_path)
    worker_tasks = {str(row.get("task_id", "")): row for row in worker_contract.get("worker_tasks", [])}
    blocked_rows = blocked_acceptance_rows(acceptance_packet)
    followup_rows = [
        build_followup_row(index, row, worker_tasks.get(str(row.get("task_id", ""))))
        for index, row in enumerate(blocked_rows, start=1)
    ]

    reason_counts = Counter()
    for row in followup_rows:
        for reason in row["input_blocker_reasons"]:
            reason_counts[reason] += 1

    raw_url_output_count = sum(finding["count"] for finding in find_raw_leaks(followup_rows))
    summary = {
        "input_acceptance_row_count": int(acceptance_packet.get("summary", {}).get("acceptance_row_count", len(blocked_rows)) or len(blocked_rows)),
        "blocked_followup_row_count": len(followup_rows),
        "wechat_environment_verification_required_count": int(reason_counts.get("wechat_environment_verification_required", 0)),
        "manual_source_evidence_review_count": len(followup_rows),
        "source_cache_lookup_candidate_count": len(followup_rows),
        "authenticated_source_cache_release_required_count": len(followup_rows),
        "accepted_no_fetch_disposition_required_count": len(followup_rows),
        "accepted_source_evidence_count": 0,
        "source_url_hash_verified_count": sum(1 for row in followup_rows if row["source_url_hash_verified_against_worker_contract"]),
        "source_url_hash_mismatch_count": int(reason_counts.get("source_url_hash_mismatch", 0)),
        "worker_contract_task_missing_count": int(reason_counts.get("worker_contract_task_missing", 0)),
        "input_blocker_count": int(reason_counts.get("source_url_hash_mismatch", 0) + reason_counts.get("worker_contract_task_missing", 0)),
        "provider_or_geocode_call_allowed_count": 0,
        "coordinate_write_allowed_count": 0,
        "db_write_allowed_count": 0,
        "network_fetch_allowed_now": False,
        "docker_worker_allowed_now": False,
        "raw_url_output_count": raw_url_output_count,
        "raw_url_private_path_secret_leak_count": raw_url_output_count,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": DECISION,
        "mode": "report_only_no_fetch_no_write_no_credentials",
        "inputs": {
            "source_fetch_result_acceptance_packet": display_path(acceptance_packet_path, repo_root),
            "source_fetch_worker_contract": display_path(worker_contract_path, repo_root),
        },
        "summary": summary,
        "input_blocker_reason_counts": dict(reason_counts),
        "followup_rows": followup_rows,
        "manual_source_evidence_review_rows": [row for row in followup_rows if row["manual_source_evidence_review_required"]],
        "source_cache_lookup_rows": [row for row in followup_rows if row["source_cache_lookup_candidate"]],
        "authenticated_source_cache_blockers": [row for row in followup_rows if row["authenticated_source_cache_release_required"]],
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
        "next_required_gate": "accepted_no_fetch_disposition_or_manual_source_evidence_or_explicit_authenticated_source_cache_release",
        "consumer_notification_fields": [
            "decision",
            "summary",
            "input_blocker_reason_counts",
            "boundary",
            "next_required_gate",
        ],
    }
    report["leak_findings"] = find_raw_leaks(report)
    report["summary"]["raw_url_private_path_secret_leak_count"] = sum(finding["count"] for finding in report["leak_findings"])
    return report


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Weekly Current Missing-Geo Source-Fetch Blocker Follow-Up Packet",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- blocked follow-up rows: `{summary['blocked_followup_row_count']}`",
        f"- manual source evidence review rows: `{summary['manual_source_evidence_review_count']}`",
        f"- source-cache lookup candidate rows: `{summary['source_cache_lookup_candidate_count']}`",
        f"- authenticated/source-cache release required rows: `{summary['authenticated_source_cache_release_required_count']}`",
        f"- accepted source evidence count: `{summary['accepted_source_evidence_count']}`",
        f"- provider/geocode allowed count: `{summary['provider_or_geocode_call_allowed_count']}`",
        f"- coordinate write allowed count: `{summary['coordinate_write_allowed_count']}`",
        f"- DB write allowed count: `{summary['db_write_allowed_count']}`",
        f"- raw URL/private path/secret leak count: `{summary['raw_url_private_path_secret_leak_count']}`",
        "",
        "## Boundary",
        "",
        "This packet creates follow-up queues only. It does not run network fetches, start Docker workers, call models or providers, write coordinates, mutate DB/registry/current packages, sync CloudBase, upload, review, release, read credentials, or output raw source URLs.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build source-fetch blocker follow-up packet.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--acceptance-packet", type=Path, default=DEFAULT_ACCEPTANCE_PACKET)
    parser.add_argument("--worker-contract", type=Path, default=DEFAULT_WORKER_CONTRACT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report = build_report(repo_root, args.acceptance_packet, args.worker_contract)
    output_json = args.out_dir / "weekly_current_missing_geo_source_fetch_blocker_followup_packet.json"
    rows_jsonl = args.out_dir / "weekly_current_missing_geo_source_fetch_blocker_followup_rows.jsonl"
    manual_jsonl = args.out_dir / "weekly_current_missing_geo_manual_source_evidence_review_rows.jsonl"
    source_cache_jsonl = args.out_dir / "weekly_current_missing_geo_source_cache_lookup_rows.jsonl"
    auth_blockers_jsonl = args.out_dir / "weekly_current_missing_geo_authenticated_source_cache_blockers.jsonl"
    write_json(output_json, report)
    write_jsonl(rows_jsonl, report["followup_rows"])
    write_jsonl(manual_jsonl, report["manual_source_evidence_review_rows"])
    write_jsonl(source_cache_jsonl, report["source_cache_lookup_rows"])
    write_jsonl(auth_blockers_jsonl, report["authenticated_source_cache_blockers"])
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
