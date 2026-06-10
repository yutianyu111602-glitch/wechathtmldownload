#!/usr/bin/env python3
"""Build a report-only manual participant DB write-gate contract packet."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_READBACK_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_readback_preflight_q6_20260526"
DEFAULT_READY_ROWS = DEFAULT_READBACK_DIR / "write_preflight_ready_report_only.jsonl"
DEFAULT_READBACK_SUMMARY = DEFAULT_READBACK_DIR / "manual_participant_readback_preflight_summary.json"
DEFAULT_DUPLICATE_SELECTOR_EVIDENCE = DEFAULT_READBACK_DIR / "duplicate_selector_evidence_rows.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_db_write_gate_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_DB_WRITE_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_db_write_gate.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for manual participant write-gate packet: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_path(path, label)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def list_strings(value: Any, limit: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def bool_is_false(row: dict[str, Any], key: str) -> bool:
    return row.get(key) is False


def participant_counts(row: dict[str, Any]) -> dict[str, int]:
    db_readback = dict_value(row.get("db_readback"))
    raw = dict_value(db_readback.get("participant_evidence_count_by_event"))
    result: dict[str, int] = {}
    for key, value in raw.items():
        try:
            result[compact(key, 160)] = int(value)
        except (TypeError, ValueError):
            result[compact(key, 160)] = 0
    return result


def performance_row_count(row: dict[str, Any]) -> int:
    db_readback = dict_value(row.get("db_readback"))
    performance = dict_value(db_readback.get("performance_event_rows"))
    try:
        return int(performance.get("event_row_count") or 0)
    except (TypeError, ValueError):
        return 0


def row_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    db_readback = dict_value(row.get("db_readback"))
    write_contract = dict_value(row.get("write_preflight_contract"))
    event_ids = list_strings(row.get("event_ids_for_consolidation_review"), 180)
    source_refs = list_strings(row.get("source_ref_ids"), 180)
    representative = compact(row.get("representative_event_id_review_only"), 180)
    source_hash = compact(row.get("source_hash"), 180)
    counts_by_event = participant_counts(row)

    if compact(row.get("readback_status")) != "manual_participant_db_readback_write_preflight_ready_report_only":
        blockers.append("readback_status_not_ready")
    if row.get("readback_failures"):
        blockers.append("readback_failures_not_empty")
    if compact(row.get("write_status")) != "report_only":
        blockers.append("write_status_not_report_only")
    if not event_ids:
        blockers.append("event_ids_missing")
    if len(event_ids) < 2:
        blockers.append("event_identity_consolidation_needs_multiple_event_ids")
    if not representative:
        blockers.append("representative_event_id_missing")
    elif representative not in set(event_ids):
        blockers.append("representative_event_id_not_in_event_ids")
    if not source_refs:
        blockers.append("source_ref_ids_missing")
    if source_hash and db_readback.get("selector_source_hash_present_in_evidence") is not True:
        blockers.append("selector_source_hash_not_confirmed_by_readback")
    if performance_row_count(row) != len(event_ids):
        blockers.append("performance_event_row_count_mismatch")
    missing_checks = [
        "performance_event_missing_event_ids",
        "event_source_ref_mismatch_event_ids",
        "selector_source_ref_missing_in_evidence_ref",
        "participant_evidence_missing_event_ids",
    ]
    for key in missing_checks:
        if db_readback.get(key):
            blockers.append(key)
    if set(counts_by_event) != set(event_ids):
        blockers.append("participant_evidence_count_keys_mismatch")
    if any(count <= 0 for count in counts_by_event.values()):
        blockers.append("participant_evidence_count_not_positive")
    if not dict_value(db_readback.get("performance_event_rows")).get("date_values"):
        blockers.append("event_date_readback_missing")
    if not dict_value(db_readback.get("performance_event_rows")).get("source_ref_ids"):
        blockers.append("event_source_ref_readback_missing")
    if not db_readback.get("evidence_ref_rows"):
        blockers.append("evidence_ref_rows_missing")

    closed_guard_keys = [
        "accepted_for_graph",
        "source_sqlite_write_allowed",
        "serving_rebuild_allowed",
        "graph_write_allowed",
        "public_serving_field_allowed",
        "memory_write_allowed",
    ]
    for key in closed_guard_keys:
        if not bool_is_false(row, key):
            blockers.append(f"{key}_not_false")
    for key in [
        "write_allowed_now",
        "source_sqlite_write_allowed",
        "serving_rebuild_allowed",
        "graph_write_allowed",
        "public_serving_field_allowed",
        "memory_write_allowed",
    ]:
        if write_contract.get(key) is not False:
            blockers.append(f"write_preflight_contract_{key}_not_false")
    if write_contract.get("next_explicit_gate_required") is not True:
        blockers.append("next_explicit_gate_required_not_true")
    return sorted(set(blockers))


def build_target(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    event_ids = list_strings(row.get("event_ids_for_consolidation_review"), 180)
    representative = compact(row.get("representative_event_id_review_only"), 180)
    source_refs = list_strings(row.get("source_ref_ids"), 180)
    counts_by_event = participant_counts(row)
    merge_edge_count = max(0, len(event_ids) - 1)
    participant_total = sum(counts_by_event.values())
    db_readback = dict_value(row.get("db_readback"))
    performance = dict_value(db_readback.get("performance_event_rows"))
    non_representative_event_ids = [event_id for event_id in event_ids if event_id != representative]

    return {
        "schema_version": SCHEMA_VERSION + ".target_row",
        "generated_at": generated_at,
        "gate_status": "manual_participant_db_write_gate_ready_report_only",
        "selector_hash": compact(row.get("selector_hash"), 100),
        "review_lane": compact(row.get("review_lane"), 100),
        "consolidation_review_id": compact(row.get("consolidation_review_id"), 160),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "work_item_id": compact(row.get("work_item_id"), 140),
        "source_hash": compact(row.get("source_hash"), 180),
        "source_ref_ids": source_refs,
        "target_namespace": "source_raw_atlas_event_identity_consolidation_report_only",
        "target_selector": {
            "representative_event_id": representative,
            "original_event_ids": event_ids,
            "non_representative_event_ids": non_representative_event_ids,
            "source_ref_ids": source_refs,
            "source_hash": compact(row.get("source_hash"), 180),
            "selector_hash": compact(row.get("selector_hash"), 100),
        },
        "evidence_contract": {
            "source_match_verified": True,
            "event_match_verified": True,
            "participant_evidence_verified": True,
            "event_row_count": performance_row_count(row),
            "merge_edge_count": merge_edge_count,
            "participant_evidence_total": participant_total,
            "participant_evidence_count_by_event": counts_by_event,
            "date_values": performance.get("date_values") or [],
            "city_values": performance.get("city_values") or [],
            "venue_values": performance.get("venue_values") or [],
            "title_sample": performance.get("title_sample") or [],
            "readback_warnings": sorted(set(list_strings(row.get("readback_warnings"), 240))),
        },
        "dry_run_transaction_work_order": {
            "execution_allowed_now": False,
            "source_raw_db_write_allowed_now": False,
            "requires_separate_confirmed_writer": True,
            "operation_sequence": [
                "open explicit target DB only after a future gate names it",
                "capture prewrite snapshots for all selected event and source rows",
                "insert or update event identity lineage from every original event_id to representative_event_id",
                "preserve participant evidence counts and source evidence links",
                "emit postwrite readback evidence before any serving rebuild",
            ],
            "estimated_identity_lineage_edges": merge_edge_count,
            "would_touch_event_ids": event_ids,
        },
        "prewrite_snapshot_contract": {
            "required": True,
            "mode": "read_only_before_any_later_write",
            "snapshot_scope": {
                "event_ids": event_ids,
                "representative_event_id": representative,
                "source_ref_ids": source_refs,
                "source_hash": compact(row.get("source_hash"), 180),
            },
            "minimum_snapshot_tables": [
                "performance_event or equivalent source/raw event table",
                "dj_event or equivalent participant edge table",
                "event identity lineage table if present",
                "evidence_ref or equivalent source evidence table",
            ],
            "must_record_row_hashes": True,
        },
        "rollback_contract": {
            "required": True,
            "inverse_mapping_required": True,
            "representative_event_id": representative,
            "original_event_ids": event_ids,
            "non_representative_event_ids": non_representative_event_ids,
            "rollback_must_restore": [
                "event identity lineage rows for this selector",
                "participant event links",
                "source evidence links",
                "all prewrite row hashes",
            ],
        },
        "postwrite_readback_contract": {
            "required": True,
            "must_verify": [
                "every original event_id maps to the representative event_id or remains recoverable through lineage",
                "participant evidence total is unchanged or explicitly explained",
                "source_ref_ids and source_hash still support the representative event",
                "no serving SQLite rebuild happened in the write gate",
                "no graph/vector/public/memory state changed in the write gate",
            ],
        },
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
        "write_status": "report_only",
        "next_gate": "A future confirmed writer may consume this packet only after prewrite snapshots and rollback evidence are materialized.",
    }


def summarize_duplicate_selector_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".duplicate_selector_evidence",
        "generated_at": generated_at,
        "evidence_only": True,
        "selector_hash": compact(row.get("selector_hash"), 100),
        "consolidation_review_id": compact(row.get("consolidation_review_id"), 160),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "representative_event_id_review_only": compact(row.get("representative_event_id_review_only"), 180),
        "event_ids_for_consolidation_review": list_strings(row.get("event_ids_for_consolidation_review"), 180),
        "source_ref_ids": list_strings(dict_value(row.get("deterministic_selector")).get("source_ref_ids"), 180),
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_status": "report_only_evidence_only",
    }


def duplicate_selector_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for key in [
        "accepted_for_graph",
        "source_sqlite_write_allowed",
        "serving_rebuild_allowed",
        "graph_write_allowed",
        "public_serving_field_allowed",
        "memory_write_allowed",
    ]:
        if row.get(key) is not False:
            blockers.append(f"duplicate_evidence_{key}_not_false")
    if compact(row.get("write_status")) != "report_only":
        blockers.append("duplicate_evidence_write_status_not_report_only")
    if not compact(row.get("selector_hash")):
        blockers.append("duplicate_evidence_selector_hash_missing")
    return blockers


def scan_payload(rows: list[dict[str, Any]]) -> dict[str, int]:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def upstream_failures(summary: dict[str, Any], ready_rows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    counts = dict_value(summary.get("counts"))
    leaks = dict_value(summary.get("leak_counts"))
    def count_value(key: str, missing: int = -1) -> int:
        if key not in counts:
            return missing
        try:
            return int(counts.get(key))
        except (TypeError, ValueError):
            return missing

    if summary.get("decision") != "atlas_social_manual_participant_readback_preflight_ready_report_only":
        failures.append("upstream_readback_preflight_not_ready")
    if count_value("write_preflight_ready_report_only_rows") != len(ready_rows):
        failures.append("upstream_ready_row_count_mismatch")
    if count_value("readback_blocked_rows") != 0:
        failures.append("upstream_readback_blocked_rows_not_zero")
    if any(int(leaks.get(key) or 0) for key in ["public_url_hits", "sensitive_key_hits", "local_path_hits"]):
        failures.append("upstream_leak_counts_not_zero")
    return failures


def build_packet(
    ready_rows_path: Path,
    readback_summary_path: Path,
    duplicate_selector_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    ready_input_rows = read_jsonl(ready_rows_path, "ready_rows")
    readback_summary = read_json(readback_summary_path)
    duplicate_input_rows = read_jsonl(duplicate_selector_path, "duplicate_selector_evidence")

    targets: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for row in ready_input_rows:
        blockers = row_blockers(row)
        if blockers:
            blocked.append(
                {
                    "schema_version": SCHEMA_VERSION + ".blocked_row",
                    "generated_at": generated_at,
                    "selector_hash": compact(row.get("selector_hash"), 100),
                    "consolidation_review_id": compact(row.get("consolidation_review_id"), 160),
                    "representative_event_id_review_only": compact(
                        row.get("representative_event_id_review_only"), 180
                    ),
                    "event_ids_for_consolidation_review": list_strings(
                        row.get("event_ids_for_consolidation_review"), 180
                    ),
                    "blockers": blockers,
                    "accepted_for_graph": False,
                    "source_sqlite_write_allowed": False,
                    "serving_rebuild_allowed": False,
                    "graph_write_allowed": False,
                    "public_serving_field_allowed": False,
                    "memory_write_allowed": False,
                }
            )
        else:
            targets.append(build_target(row, generated_at))

    duplicate_evidence_rows = [summarize_duplicate_selector_row(row, generated_at) for row in duplicate_input_rows]
    duplicate_evidence_blocked = [
        {
            "schema_version": SCHEMA_VERSION + ".duplicate_selector_blocked",
            "generated_at": generated_at,
            "selector_hash": compact(row.get("selector_hash"), 100),
            "blockers": duplicate_selector_blockers(row),
        }
        for row in duplicate_input_rows
        if duplicate_selector_blockers(row)
    ]

    target_selector_counts = Counter(row["selector_hash"] for row in targets)
    duplicate_target_selectors = sorted(
        selector for selector, count in target_selector_counts.items() if selector and count > 1
    )
    target_selectors = set(target_selector_counts)
    duplicate_evidence_matched_rows = sum(
        1 for row in duplicate_evidence_rows if compact(row.get("selector_hash"), 100) in target_selectors
    )
    upstream = upstream_failures(readback_summary, ready_input_rows)
    leak_counts = scan_payload(targets + blocked + duplicate_evidence_rows + duplicate_evidence_blocked)
    failed_checks: list[str] = []
    failed_checks.extend(upstream)
    if blocked:
        failed_checks.append("write_gate_blocked_rows")
    if duplicate_evidence_blocked:
        failed_checks.append("duplicate_selector_evidence_blocked_rows")
    if duplicate_target_selectors:
        failed_checks.append("duplicate_selector_drift_in_write_gate_targets")
    failed_checks.extend(key for key, value in leak_counts.items() if value)
    decision = (
        "atlas_social_manual_participant_db_write_gate_ready_report_only"
        if targets and not failed_checks
        else "atlas_social_manual_participant_db_write_gate_blocked_report_only"
    )

    total_event_ids = {event_id for target in targets for event_id in target["target_selector"]["original_event_ids"]}
    merge_edge_count = sum(target["evidence_contract"]["merge_edge_count"] for target in targets)
    participant_total = sum(target["evidence_contract"]["participant_evidence_total"] for target in targets)
    lane_counts = Counter(target["review_lane"] for target in targets)
    outputs = {
        "summary_json": display_path(out_dir / "manual_participant_db_write_gate_summary.json"),
        "summary_md": display_path(out_dir / "manual_participant_db_write_gate_summary.md"),
        "write_gate_targets": display_path(out_dir / "manual_participant_db_write_gate_targets.jsonl"),
        "dry_run_work_orders": display_path(out_dir / "manual_participant_db_write_gate_dry_run_work_orders.jsonl"),
        "rollback_contract_rows": display_path(out_dir / "manual_participant_db_write_gate_rollback_contracts.jsonl"),
        "postwrite_readback_contract_rows": display_path(
            out_dir / "manual_participant_db_write_gate_postwrite_readback_contracts.jsonl"
        ),
        "blocked_rows": display_path(out_dir / "manual_participant_db_write_gate_blocked_rows.jsonl"),
        "duplicate_selector_evidence": display_path(out_dir / "duplicate_selector_evidence_rows.jsonl"),
        "duplicate_selector_blocked": display_path(out_dir / "duplicate_selector_blocked_rows.jsonl"),
        "report": display_path(report_path),
    }
    counts = {
        "input_ready_rows": len(ready_input_rows),
        "write_gate_target_rows": len(targets),
        "blocked_rows": len(blocked),
        "event_id_target_rows": lane_counts.get("event_id_dedupe", 0),
        "semantic_cluster_target_rows": lane_counts.get("semantic_event_cluster", 0),
        "unique_event_ids": len(total_event_ids),
        "planned_identity_lineage_edges_report_only": merge_edge_count,
        "participant_evidence_total": participant_total,
        "duplicate_selector_evidence_input_rows": len(duplicate_input_rows),
        "duplicate_selector_evidence_matched_target_rows": duplicate_evidence_matched_rows,
        "duplicate_selector_evidence_blocked_rows": len(duplicate_evidence_blocked),
        "prewrite_snapshot_required_rows": len(targets),
        "rollback_required_rows": len(targets),
        "postwrite_readback_required_rows": len(targets),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "counts": counts,
        "leak_counts": leak_counts,
        "inputs": {
            "ready_rows": display_path(ready_rows_path),
            "readback_summary": display_path(readback_summary_path),
            "duplicate_selector_evidence": display_path(duplicate_selector_path),
        },
        "outputs": outputs,
        "upstream_failures": upstream,
        "duplicate_selector_drift_in_write_gate_targets": duplicate_target_selectors,
        "write_guards": {
            "write_execution_allowed_now": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "boundary": {
            "report_only": True,
            "source_raw_db_write_executed": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_update_executed": False,
            "deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "credential_read_executed": False,
            "d_root_scan_executed": False,
        },
        "next_cursor": outputs["write_gate_targets"],
        "next_gate": "Use manual_participant_db_write_gate_targets.jsonl only for a future confirmed writer dry-run/prewrite snapshot packet; do not execute writes from this report-only packet.",
    }

    write_jsonl(out_dir / "manual_participant_db_write_gate_targets.jsonl", targets)
    write_jsonl(out_dir / "manual_participant_db_write_gate_dry_run_work_orders.jsonl", targets)
    write_jsonl(out_dir / "manual_participant_db_write_gate_rollback_contracts.jsonl", [
        {
            "selector_hash": target["selector_hash"],
            "rollback_contract": target["rollback_contract"],
            "write_execution_allowed_now": False,
        }
        for target in targets
    ])
    write_jsonl(out_dir / "manual_participant_db_write_gate_postwrite_readback_contracts.jsonl", [
        {
            "selector_hash": target["selector_hash"],
            "postwrite_readback_contract": target["postwrite_readback_contract"],
            "write_execution_allowed_now": False,
        }
        for target in targets
    ])
    write_jsonl(out_dir / "manual_participant_db_write_gate_blocked_rows.jsonl", blocked)
    write_jsonl(out_dir / "duplicate_selector_evidence_rows.jsonl", duplicate_evidence_rows)
    write_jsonl(out_dir / "duplicate_selector_blocked_rows.jsonl", duplicate_evidence_blocked)
    write_json(out_dir / "manual_participant_db_write_gate_summary.json", summary)
    write_text(out_dir / "manual_participant_db_write_gate_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant DB Write-Gate Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Input ready rows: `{counts['input_ready_rows']}`",
            f"- Write-gate target rows: `{counts['write_gate_target_rows']}`",
            f"- Blocked rows: `{counts['blocked_rows']}`",
            f"- Event-id / semantic target split: `{counts['event_id_target_rows']}/{counts['semantic_cluster_target_rows']}`",
            f"- Unique event_ids: `{counts['unique_event_ids']}`",
            f"- Planned identity-lineage edges, report-only: `{counts['planned_identity_lineage_edges_report_only']}`",
            f"- Duplicate selector evidence rows carried forward: `{counts['duplicate_selector_evidence_input_rows']}`",
            "- Write guards: execution, source SQLite, serving rebuild, graph write, public serving field, and memory write all remain `false`.",
            f"- Next cursor: `{summary['next_cursor']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant DB Write-Gate - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only explicit write-gate contract. It groups the readback-verified manual participant rows into dry-run work orders, rollback contracts, and postwrite readback contracts, but does not execute source/raw DB, serving SQLite, graph/vector, public, deploy, upload/review, or memory writes.",
            "",
            "## Counts",
            "",
            f"- Input ready rows: `{counts['input_ready_rows']}`",
            f"- Write-gate target rows: `{counts['write_gate_target_rows']}`",
            f"- Blocked rows: `{counts['blocked_rows']}`",
            f"- Event-id / semantic target split: `{counts['event_id_target_rows']}/{counts['semantic_cluster_target_rows']}`",
            f"- Unique event_ids: `{counts['unique_event_ids']}`",
            f"- Planned identity-lineage edges, report-only: `{counts['planned_identity_lineage_edges_report_only']}`",
            f"- Participant evidence total: `{counts['participant_evidence_total']}`",
            f"- Duplicate selector evidence input/matched/blocked: `{counts['duplicate_selector_evidence_input_rows']}/{counts['duplicate_selector_evidence_matched_target_rows']}/{counts['duplicate_selector_evidence_blocked_rows']}`",
            "- Accepted/source-sqlite/serving/graph/public/memory rows: `0/0/0/0/0/0`",
            f"- Public URL / sensitive key / local path leak hits: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- Target rows: `{outputs['write_gate_targets']}`",
            f"- Dry-run work orders: `{outputs['dry_run_work_orders']}`",
            f"- Rollback contracts: `{outputs['rollback_contract_rows']}`",
            f"- Postwrite readback contracts: `{outputs['postwrite_readback_contract_rows']}`",
            f"- Blocked rows: `{outputs['blocked_rows']}`",
            f"- Duplicate selector evidence: `{outputs['duplicate_selector_evidence']}`",
            "",
            "## Next Cursor",
            "",
            f"`{summary['next_cursor']}`",
            "",
            "A later writer must first materialize prewrite snapshots and rollback evidence. This packet is not a mutation execution packet.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-rows", type=Path, default=DEFAULT_READY_ROWS)
    parser.add_argument("--readback-summary", type=Path, default=DEFAULT_READBACK_SUMMARY)
    parser.add_argument("--duplicate-selector-evidence", type=Path, default=DEFAULT_DUPLICATE_SELECTOR_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        args.ready_rows,
        args.readback_summary,
        args.duplicate_selector_evidence,
        args.out_dir,
        args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["decision"].endswith("_ready_report_only") else 1


if __name__ == "__main__":
    raise SystemExit(main())
