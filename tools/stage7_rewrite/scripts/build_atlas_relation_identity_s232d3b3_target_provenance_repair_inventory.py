#!/usr/bin/env python3
"""Build S232D-3B-3 target-provenance repair inventory.

This is a DB3-lane report-only static inventory. It does not fetch network
targets, generate search URLs, read credentials, open DBs, write DBs, project
DB2, start workers, or release downstream consumers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

STORY_ID = "S232D-3B-3"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b3_target_provenance_repair.v1"
DECISION_BLOCKED = "atlas_relation_identity_s232d3b3_target_provenance_repair_blocked_no_concrete_public_target_source_evidence"
DECISION_READY = "atlas_relation_identity_s232d3b3_target_provenance_repair_candidates_ready_for_controller_review"

DEFAULT_ACTUAL_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b_actual_canary_20260602"
DEFAULT_ACTUAL_JSON = DEFAULT_ACTUAL_DIR / "atlas_relation_identity_s232d3b_actual_canary.json"
DEFAULT_ACTUAL_PROVENANCE = DEFAULT_ACTUAL_DIR / "s232d3b_target_provenance.jsonl"
DEFAULT_S232D3A_QUEUE = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3a_seed_target_resolver_contract_20260602"
    / "s232d3a_seed_target_resolver_queue.jsonl"
)
DEFAULT_ALLOWLIST = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_20260602"
    / "s232d3b1_work_order_allowlist.jsonl"
)
DEFAULT_SCHEMA = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_20260602"
    / "s232d3b1_target_provenance_schema.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b3_target_provenance_repair_20260602"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B3_TARGET_PROVENANCE_REPAIR_20260602.md"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)

DEFAULT_EVIDENCE_DIRS = [
    REPORTS_ROOT / "atlas_relation_identity_s228_pending_candidate_workbench_20260602",
    REPORTS_ROOT / "atlas_relation_identity_p1_p2_recovery_workbench_s213_20260602",
    REPORTS_ROOT / "atlas_relation_identity_p1_p2_recovery_workbench_s219_after_s216_20260602",
    REPORTS_ROOT / "atlas_relation_identity_p1_p2_recovery_workbench_s221_after_s219_20260602",
    REPORTS_ROOT / "atlas_relation_identity_s232c_bounded_evidence_gate_20260602",
    REPORTS_ROOT / "atlas_relation_identity_s232d0_docker_worker_contract_20260602",
    REPORTS_ROOT / "atlas_relation_identity_s232d3_no_cookie_canary_20260602",
    REPORTS_ROOT / "atlas_relation_identity_s232d3a_seed_target_resolver_contract_20260602",
    REPORTS_ROOT / "atlas_relation_identity_s232d3b_target_resolution_release_preflight_20260602",
    REPORTS_ROOT / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_20260602",
    REPORTS_ROOT / "atlas_relation_identity_s232d3b2_controller_release_packet_20260602",
    DEFAULT_ACTUAL_DIR,
    REPORTS_ROOT / "atlas_relation_source_archive_replay_s214_from_s213_20260602",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def digest(value: str, size: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:size]


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return f"external-fixture/{path.name}"


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def leak_scan(payload: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def walk(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, f"{pointer}.{key}" if pointer else str(key))
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{pointer}[{index}]")
            return
        if not isinstance(value, str):
            return
        for kind, pattern in (("raw_url", RAW_URL_RE), ("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(value):
                findings.append({"kind": kind, "pointer": pointer})

    walk(payload, "")
    return findings


def iter_evidence_files(evidence_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for directory in evidence_dirs:
        if not directory.exists():
            continue
        if directory.is_file():
            files.append(directory)
            continue
        for suffix in ("*.json", "*.jsonl", "*.md"):
            files.extend(path for path in directory.rglob(suffix) if path.is_file())
    return sorted(set(files))


def row_has_concrete_target(row: dict[str, Any]) -> bool:
    work_order_id = str(row.get("work_order_id") or "")
    if not work_order_id:
        return False
    target_domain_hash = str(row.get("target_domain_hash") or "")
    provider_anchor_hash = str(row.get("provider_anchor_hash") or row.get("source_account_anchor_hash") or "")
    source_anchor_hash = str(row.get("source_anchor_hash") or "")
    source_ref_id = str(row.get("source_ref_id") or row.get("local_source_ref_id") or "")
    status = str(row.get("target_provenance_status") or row.get("status") or "")
    blocked = status.startswith("blocked_") or status in {"needs_review", "pending", "blocked"}
    return bool(target_domain_hash and (provider_anchor_hash or source_anchor_hash or source_ref_id) and not blocked)


def sanitize_candidate(row: dict[str, Any], evidence_file: Path) -> dict[str, Any]:
    work_order_id = str(row.get("work_order_id") or "")
    return {
        "schema_version": "atlas_relation_identity_s232d3b3_repair_candidate.v1",
        "work_order_id": work_order_id,
        "candidate_state": "repair_candidate_ready_for_controller_review",
        "target_provider_kind": str(row.get("target_provider_kind") or row.get("provider_kind") or "unknown"),
        "target_identity_hash": str(row.get("target_identity_hash") or ""),
        "target_domain_hash": str(row.get("target_domain_hash") or ""),
        "target_title_hash": str(row.get("target_title_hash") or ""),
        "provider_anchor_hash": str(row.get("provider_anchor_hash") or row.get("source_account_anchor_hash") or ""),
        "source_anchor_hash": str(row.get("source_anchor_hash") or ""),
        "source_ref_id_hash": digest(str(row.get("source_ref_id") or row.get("local_source_ref_id") or "")),
        "evidence_path_hash": digest(rel(evidence_file)),
        "evidence_file_rel": rel(evidence_file),
        "confidence": float(row.get("confidence") or 0.0),
        "reason": "existing_local_artifact_contains_hashed_target_descriptor_fields",
        "network_validation_allowed_now": False,
        "db_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "raw_url_output_allowed": False,
    }


def extract_json_objects(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from extract_json_objects(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from extract_json_objects(value)


def find_candidates(files: list[Path], work_order_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates: list[dict[str, Any]] = []
    match_counts = {"text_match_file_count": 0, "object_match_count": 0}
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not any(work_order_id in text for work_order_id in work_order_ids):
            continue
        match_counts["text_match_file_count"] += 1
        if path.suffix.lower() == ".jsonl":
            objects = read_jsonl(path)
        elif path.suffix.lower() == ".json":
            objects = list(extract_json_objects(read_json(path)))
        else:
            objects = []
        for obj in objects:
            if str(obj.get("work_order_id") or "") not in work_order_ids:
                continue
            match_counts["object_match_count"] += 1
            if row_has_concrete_target(obj):
                candidates.append(sanitize_candidate(obj, path))
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for candidate in candidates:
        key = (
            str(candidate.get("work_order_id")),
            str(candidate.get("target_domain_hash")),
            str(candidate.get("provider_anchor_hash") or candidate.get("source_anchor_hash") or candidate.get("source_ref_id_hash")),
        )
        deduped[key] = candidate
    return list(deduped.values()), match_counts


def build_missing_rows(
    queue_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_ids = {str(row.get("work_order_id")) for row in candidates}
    actual_by_id = {str(row.get("work_order_id")): row for row in actual_rows}
    missing: list[dict[str, Any]] = []
    for queue_row in queue_rows:
        work_order_id = str(queue_row.get("work_order_id") or "")
        if work_order_id in candidate_ids:
            continue
        actual = actual_by_id.get(work_order_id, {})
        missing.append(
            {
                "schema_version": "atlas_relation_identity_s232d3b3_missing_fields.v1",
                "work_order_id": work_order_id,
                "ordinal": int(queue_row.get("ordinal") or actual.get("ordinal") or 0),
                "display_name_hash": str(actual.get("display_name_hash") or digest(str(queue_row.get("display_name", "")))),
                "group_id_hash": str(actual.get("group_id_hash") or digest(str(queue_row.get("group_id", "")))),
                "seed_value_hash": str(queue_row.get("seed_value_hash") or actual.get("seed_value_hash") or ""),
                "repair_state": "blocked_no_concrete_public_target_source_evidence",
                "missing_fields": [
                    "concrete_public_provider_or_source_target",
                    "target_domain_hash",
                    "provider_anchor_hash_or_source_anchor_hash",
                    "source_ref_id_or_local_artifact_id",
                    "target_confidence_reason",
                    "no_cookie_public_access_evidence",
                ],
                "current_evidence_has_seed_only": True,
                "next_required_evidence": [
                    "source_ref_with_hashed_public_provider_or_source_target",
                    "same_seed_account_or_venue_anchor_crosscheck",
                    "no_cookie_public_access_or_local_source_ref_proof",
                    "controller_release_for_bounded_target_resolution_canary",
                ],
                "network_fetch_allowed_now": False,
                "search_url_generation_allowed_now": False,
                "db_write_allowed_now": False,
                "db2_projection_allowed_now": False,
            }
        )
    return missing


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    actual = read_json(Path(args.actual_json))
    actual_rows = read_jsonl(Path(args.actual_provenance))
    queue_rows = read_jsonl(Path(args.queue))
    allowlist_rows = read_jsonl(Path(args.allowlist))
    schema = read_json(Path(args.provenance_schema))

    work_order_ids = {str(row.get("work_order_id") or "") for row in allowlist_rows}
    work_order_ids.discard("")
    evidence_dirs = [Path(value) for value in (args.evidence_dir or [])] or DEFAULT_EVIDENCE_DIRS
    evidence_files = iter_evidence_files(evidence_dirs)
    candidates, match_counts = find_candidates(evidence_files, work_order_ids)
    missing_rows = build_missing_rows(queue_rows, actual_rows, candidates)

    failed_checks: list[dict[str, Any]] = []
    if actual.get("decision") != "atlas_relation_identity_s232d3b_actual_canary_blocked_no_concrete_public_targets_report_local":
        failed_checks.append({"check": "s232d3b_actual_blocked_decision_required"})
    if len(work_order_ids) != 5 or len(actual_rows) != 5 or len(queue_rows) != 5:
        failed_checks.append({"check": "first5_input_counts_required"})
    if not set(str(row.get("work_order_id") or "") for row in actual_rows).issubset(work_order_ids):
        failed_checks.append({"check": "actual_rows_must_match_allowlist"})
    if any(bool(actual.get(flag)) for flag in ("db_write_executed", "db1_mutation", "db2_mutation", "db3_mutation", "db2_projection_allowed_now")):
        failed_checks.append({"check": "actual_canary_forbidden_db_projection_flags_false"})

    decision = DECISION_READY if candidates and not failed_checks else DECISION_BLOCKED
    report = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "mode": "static_no_network_report_local_inventory",
        "decision": decision,
        "controller_release_id": actual.get("controller_release_id"),
        "controller_thread_id": actual.get("controller_thread_id"),
        "input_allowlist_count": len(work_order_ids),
        "actual_canary_decision": actual.get("decision"),
        "actual_canary_blocked_row_count": int(actual.get("blocked_row_count") or 0),
        "candidate_count": len(candidates),
        "missing_fields_row_count": len(missing_rows),
        "evidence_files_scanned_count": len(evidence_files),
        "evidence_text_match_file_count": match_counts["text_match_file_count"],
        "evidence_object_match_count": match_counts["object_match_count"],
        "candidate_target_descriptor_schema": {
            "required_for_candidate": [
                "work_order_id",
                "target_domain_hash",
                "provider_anchor_hash_or_source_anchor_hash_or_source_ref_id",
                "target_provenance_status_not_blocked",
                "confidence",
                "evidence_path_hash",
            ],
            "forbidden_output_fields": schema.get("forbidden_fields", []),
        },
        "repair_states": [
            "blocked_no_concrete_public_target_source_evidence",
            "repair_candidate_ready_for_controller_review",
            "requires_bounded_target_resolution_canary_release",
            "requires_source_evidence_acquisition",
        ],
        "stop_conditions": [
            "raw_url_or_private_path_or_secret_detected",
            "credential_cookie_token_env_browser_profile_required",
            "seed_direct_search_url_generation_required",
            "non_allowlist_work_order_detected",
            "db_write_or_db2_projection_required",
            "network_fetch_required_without_controller_release",
        ],
        "next_controller_release_preconditions": [
            "controller_review_accepts_repair_candidates_or_source_evidence_plan",
            "first5_or_new_allowlist_explicitly_named",
            "docker_container_worker_runtime_contract_present",
            "no_cookie_public_target_descriptor_present",
            "raw_url_private_path_secret_leak_count_zero",
            "db_projection_release_flags_false",
        ],
        "consumer_notification_fields": {
            "decision": decision,
            "candidate_count": len(candidates),
            "missing_fields_row_count": len(missing_rows),
            "network_attempt_count": 0,
            "db_write_executed": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_release_allowed_now": False,
            "raw_url_private_path_secret_leak_count": 0,
            "next_gate": "controller_review_before_any_s232d3b_target_resolution_canary_or_s232d4_write_gate",
        },
        "static_inventory_reason": "No Docker/container worker was started because S232D-3B-3 only inventories existing local artifacts and performs no target-resolution execution.",
        "network_attempt_count": 0,
        "network_fetch_success_count": 0,
        "docker_started": False,
        "worker_started": False,
        "target_resolution_execution_allowed_now": False,
        "db_write_executed": False,
        "db1_mutation": False,
        "db2_mutation": False,
        "db3_mutation": False,
        "db2_projection_allowed_now": False,
        "db3_write_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "cookie_or_token_read": False,
        "api_key_read": False,
        "browser_profile_read": False,
        "env_file_read": False,
        "search_url_generation_attempted": False,
        "raw_source_url_emitted": False,
        "private_path_emitted": False,
        "failed_checks": failed_checks,
    }
    leak_findings = leak_scan({"report": report, "candidates": candidates, "missing_rows": missing_rows})
    report["leak_findings"] = leak_findings
    report["raw_url_private_path_secret_leak_count"] = len(leak_findings)
    report["failed_check_count"] = len(failed_checks) + len(leak_findings)
    if leak_findings:
        report["decision"] = DECISION_BLOCKED
        report["consumer_notification_fields"]["decision"] = DECISION_BLOCKED
    return report, candidates, missing_rows


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# S232D-3B-3 Target Provenance Repair Inventory",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Mode: `{report['mode']}`",
        f"- Controller release consumed as upstream evidence: `{report.get('controller_release_id')}`",
        f"- Allowlist: `{report['input_allowlist_count']}`",
        f"- Repair candidates: `{report['candidate_count']}`",
        f"- Missing-field rows: `{report['missing_fields_row_count']}`",
        f"- Evidence files scanned / matched: `{report['evidence_files_scanned_count']}` / `{report['evidence_text_match_file_count']}`",
        f"- Network attempts/successes: `{report['network_attempt_count']}` / `{report['network_fetch_success_count']}`",
        f"- Failed checks / leak count: `{report['failed_check_count']}` / `{report['raw_url_private_path_secret_leak_count']}`",
        "",
        "Boundary: no network/web fetch, no search URL generation, no Docker/worker start, no DB1/DB2/DB3 write, no DB2 projection, no credential read, no deploy/sync/upload/review/release.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actual-json", type=Path, default=DEFAULT_ACTUAL_JSON)
    parser.add_argument("--actual-provenance", type=Path, default=DEFAULT_ACTUAL_PROVENANCE)
    parser.add_argument("--queue", type=Path, default=DEFAULT_S232D3A_QUEUE)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--provenance-schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--evidence-dir", action="append", default=[])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    args = parser.parse_args(argv)

    report, candidates, missing_rows = build_report(args)
    out_dir = Path(args.out_dir)
    write_json(out_dir / "atlas_relation_identity_s232d3b3_target_provenance_repair.json", report)
    write_jsonl(out_dir / "s232d3b3_repair_candidates.jsonl", candidates)
    write_jsonl(out_dir / "s232d3b3_missing_fields.jsonl", missing_rows)
    write_scorecard(out_dir / "atlas_relation_identity_s232d3b3_target_provenance_repair.md", report)
    write_scorecard(Path(args.scorecard), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["failed_check_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
