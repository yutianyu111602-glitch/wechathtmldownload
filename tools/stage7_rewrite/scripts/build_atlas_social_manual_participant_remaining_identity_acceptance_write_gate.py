#!/usr/bin/env python3
"""Build a report-only remaining-identity acceptance/write-gate packet."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_READBACK_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_remaining_identity_readback_gate_q6_20260526"
)
DEFAULT_READY_ROWS = DEFAULT_READBACK_DIR / "event_identity_readback_ready_report_only.jsonl"
DEFAULT_READBACK_SUMMARY = DEFAULT_READBACK_DIR / "event_identity_readback_gate_summary.json"
DEFAULT_TARGET_DB_PROVENANCE_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_target_db_provenance_q6_20260526"
    / "target_db_provenance_summary.json"
)
DEFAULT_OUT_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_remaining_identity_acceptance_write_gate_q6_20260526"
)
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_REMAINING_IDENTITY_ACCEPTANCE_WRITE_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_remaining_identity_acceptance_write_gate.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    raw = "|".join(compact(part, 800) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for remaining-identity acceptance gate: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def read_json(path: Path, label: str) -> dict[str, Any]:
    reject_d_path(path, label)
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


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_strings(value: Any, limit: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


def bool_is_false(row: dict[str, Any], key: str) -> bool:
    return row.get(key) is False


def scan_payload(payload: Any) -> dict[str, int]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def provenance_counts(summary: dict[str, Any]) -> dict[str, int]:
    counts = dict_value(summary.get("counts"))

    def intval(*keys: str) -> int:
        for key in keys:
            value = counts.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return 0

    return {
        "direct_existing_explicit_source_raw_target_db_paths": intval(
            "direct_existing_explicit_source_raw_target_db_paths",
            "direct_existing_explicit_target_db_paths",
        ),
        "ready_rows": intval("ready_rows", "target_db_ready_for_real_snapshot_rows"),
        "blocked_rows": intval("blocked_rows", "target_db_provenance_blocked_rows"),
        "write_execution_allowed_rows": intval("write_execution_allowed_rows"),
    }


def source_raw_target_db_ready(summary: dict[str, Any]) -> bool:
    counts = provenance_counts(summary)
    return counts["direct_existing_explicit_source_raw_target_db_paths"] > 0 and counts["ready_rows"] > 0


def participant_counts(row: dict[str, Any]) -> dict[str, int]:
    raw = dict_value(dict_value(row.get("db_readback")).get("participant_evidence_count_by_event"))
    result: dict[str, int] = {}
    for key, value in raw.items():
        try:
            result[compact(key, 180)] = int(value)
        except (TypeError, ValueError):
            result[compact(key, 180)] = 0
    return result


def selected_event_ids(row: dict[str, Any]) -> list[str]:
    return list_strings(row.get("selected_event_ids_review_only"), 180) or list_strings(
        row.get("selected_event_ids_report_only"), 180
    )


def row_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    db_readback = dict_value(row.get("db_readback"))
    later_contract = dict_value(row.get("later_write_contract"))
    rollback_contract = dict_value(row.get("rollback_contract"))
    postwrite_contract = dict_value(row.get("postwrite_verify_contract"))
    event_ids = selected_event_ids(row)
    source_refs = list_strings(row.get("source_ref_ids"), 180)
    counts_by_event = participant_counts(row)

    if compact(row.get("readback_status")) != "event_identity_db_readback_gate_ready_report_only":
        blockers.append("readback_status_not_ready")
    if row.get("readback_failures"):
        blockers.append("readback_failures_not_empty")
    if compact(row.get("write_status")) != "report_only":
        blockers.append("write_status_not_report_only")
    if not event_ids:
        blockers.append("selected_event_ids_missing")
    if not source_refs:
        blockers.append("source_ref_ids_missing")
    if compact(row.get("source_hash"), 180) and db_readback.get("selector_source_hash_present_in_evidence") is not True:
        blockers.append("selector_source_hash_not_confirmed_by_readback")

    performance = dict_value(db_readback.get("performance_event_rows"))
    try:
        event_row_count = int(performance.get("event_row_count") or 0)
    except (TypeError, ValueError):
        event_row_count = 0
    if event_row_count != len(event_ids):
        blockers.append("performance_event_row_count_mismatch")

    for key in [
        "performance_event_missing_event_ids",
        "duplicate_performance_event_event_ids",
        "event_source_ref_mismatch_event_ids",
        "selector_source_ref_missing_in_evidence_ref",
        "participant_evidence_missing_event_ids",
    ]:
        if db_readback.get(key):
            blockers.append(key)
    if not db_readback.get("evidence_ref_rows"):
        blockers.append("evidence_ref_rows_missing")
    if set(counts_by_event) != set(event_ids):
        blockers.append("participant_evidence_count_keys_mismatch")
    if any(count <= 0 for count in counts_by_event.values()):
        blockers.append("participant_evidence_count_not_positive")

    for key in [
        "accepted_for_graph",
        "source_sqlite_write_allowed",
        "serving_rebuild_allowed",
        "graph_write_allowed",
        "public_serving_field_allowed",
        "memory_write_allowed",
    ]:
        if not bool_is_false(row, key):
            blockers.append(f"{key}_not_false")

    if later_contract.get("write_allowed_now") is not False:
        blockers.append("later_write_contract_write_allowed_now_not_false")
    if later_contract.get("source_raw_target_db_required") is not True:
        blockers.append("later_write_contract_source_raw_target_db_required_not_true")
    if rollback_contract.get("required") is not True or rollback_contract.get("prewrite_snapshot_required") is not True:
        blockers.append("rollback_contract_incomplete")
    if postwrite_contract.get("required") is not True:
        blockers.append("postwrite_verify_contract_missing")
    return sorted(set(blockers))


def build_target(row: dict[str, Any], generated_at: str, target_db_ready: bool) -> dict[str, Any]:
    event_ids = selected_event_ids(row)
    readback_blockers = row_blockers(row)
    blockers = list(readback_blockers)
    if not target_db_ready:
        blockers.append("source_raw_target_db_provenance_missing")

    gate_id = stable_id(
        "remainingidentityacceptance",
        [
            row.get("resolution_id"),
            row.get("selector_hash"),
            row.get("source_account"),
            row.get("source_hash"),
            ",".join(event_ids),
        ],
    )
    source_refs = list_strings(row.get("source_ref_ids"), 180)
    participant_count_by_event = participant_counts(row)
    representative_event_id = compact(row.get("representative_event_id_review_only"), 180) or (event_ids[0] if event_ids else "")

    return {
        "schema_version": f"{SCHEMA_VERSION}.target_row",
        "generated_at": generated_at,
        "remaining_identity_acceptance_gate_id": gate_id,
        "resolution_id": compact(row.get("resolution_id"), 180),
        "resolution_lane": compact(row.get("resolution_lane"), 180),
        "resolution_reason": compact(row.get("resolution_reason"), 400),
        "selector_hash": compact(row.get("selector_hash"), 180),
        "work_item_id": compact(row.get("work_item_id"), 180),
        "article_uid": compact(row.get("article_uid"), 240),
        "source_account": compact(row.get("source_account"), 180),
        "source_hash": compact(row.get("source_hash"), 180),
        "source_ref_ids": source_refs,
        "selected_event_ids_review_only": event_ids,
        "representative_event_id_review_only": representative_event_id,
        "selected_event_id_count": len(event_ids),
        "selected_semantic_event_clusters": row.get("selected_semantic_event_clusters") if isinstance(row.get("selected_semantic_event_clusters"), list) else [],
        "participant_evidence_count_by_event": participant_count_by_event,
        "source_evidence_sample": dict_value(row.get("db_readback")).get("evidence_ref_rows", [])[:5],
        "readback_warnings": list_strings(row.get("readback_warnings"), 180),
        "readback_blockers": readback_blockers,
        "blockers": sorted(set(blockers)),
        "manual_event_identity_acceptance_precheck_ready": not readback_blockers,
        "source_raw_target_db_provenance_ready_report_only": target_db_ready,
        "dry_run_transaction_work_order": {
            "execution_allowed_now": False,
            "source_raw_target_db_required": True,
            "representative_event_id_review_only": representative_event_id,
            "selected_event_ids_review_only": event_ids,
            "source_ref_ids": source_refs,
            "required_prewrite": [
                "explicit source/raw target DB path provenance",
                "prewrite snapshot of every selected event row and source edge",
                "duplicate-drift check for representative and original event ids",
            ],
        },
        "rollback_contract": {
            "required": True,
            "prewrite_snapshot_required": True,
            "inverse_mapping_required": True,
            "postwrite_readback_required": True,
            "representative_event_id_review_only": representative_event_id,
            "original_event_ids": event_ids,
        },
        "postwrite_readback_contract": {
            "required": True,
            "must_verify": [
                "representative event retains source_ref/source_hash evidence",
                "all original selected event ids remain recoverable through alias/merge lineage",
                "participant evidence count is preserved or explained",
                "serving rebuild diff remains closed until a separate gate",
                "graph/vector/public pointer remain untouched unless a later gate permits them",
            ],
        },
        "write_execution_allowed_now": False,
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
    }


def group_batches(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in targets:
        grouped[row["source_account"]].append(row)
    batches = []
    for source_account, rows in sorted(grouped.items()):
        batches.append(
            {
                "source_account": source_account,
                "target_rows": len(rows),
                "selected_event_ids": sorted({event_id for row in rows for event_id in row["selected_event_ids_review_only"]}),
                "blocked_rows": sum(1 for row in rows if row["blockers"]),
                "source_raw_target_db_blocked_rows": sum(
                    1 for row in rows if "source_raw_target_db_provenance_missing" in row["blockers"]
                ),
            }
        )
    return batches


def render_summary_md(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return (
        "# Remaining-Identity Acceptance Write Gate Summary\n\n"
        f"- Decision: `{summary['decision']}`\n"
        f"- Failed checks: `{summary['failed_checks']}`\n"
        f"- Targets: `{counts['write_gate_target_rows']}`\n"
        f"- Manual event-identity acceptance precheck ready: `{counts['manual_event_identity_acceptance_precheck_ready_rows']}`\n"
        f"- Source/raw target DB blocked: `{counts['source_raw_target_db_blocked_rows']}`\n"
        f"- Write execution allowed rows: `{counts['write_execution_allowed_rows']}`\n"
        f"- Leak hits: `{summary['leak_counts']['public_url_hits']}/"
        f"{summary['leak_counts']['sensitive_key_hits']}/{summary['leak_counts']['local_path_hits']}`\n"
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    target_db = summary["target_db_provenance"]
    return f"""# Atlas T6 Manual Participant Remaining-Identity Acceptance Write Gate - 2026-05-26

## Decision

- Decision: `{summary['decision']}`
- Failed checks: `{summary['failed_checks']}`
- Boundary: report-only remaining event-identity acceptance/source-raw DB provenance write-gate contract. It does not open source/raw Atlas DB, write source/raw DB, rebuild or write serving SQLite, accept graph facts, write Neo4j/Qdrant/SQLite production state, update public pointers, deploy CloudRun/VPS, upload/review mini-program, execute OCR/network/model calls, or write memory.

## Counts

- Input readback-ready rows: `{counts['input_ready_rows']}`
- Write-gate target rows: `{counts['write_gate_target_rows']}`
- Manual event-identity acceptance precheck ready rows: `{counts['manual_event_identity_acceptance_precheck_ready_rows']}`
- Source/raw target DB provenance ready / blocked rows: `{counts['source_raw_target_db_provenance_ready_rows']}/{counts['source_raw_target_db_blocked_rows']}`
- Row-blocked rows: `{counts['row_blocked_rows']}`
- Source-account batches: `{counts['source_account_batches']}`
- Unique selected event ids: `{counts['unique_selected_event_ids']}`
- Prewrite snapshot / rollback / postwrite readback required rows: `{counts['prewrite_snapshot_required_rows']}/{counts['rollback_required_rows']}/{counts['postwrite_readback_required_rows']}`
- Write execution allowed rows: `{counts['write_execution_allowed_rows']}`
- Accepted/source-sqlite/serving/graph/public/memory rows: `{counts['accepted_for_graph_rows']}/{counts['source_sqlite_write_allowed_rows']}/{counts['serving_rebuild_allowed_rows']}/{counts['graph_write_allowed_rows']}/{counts['public_serving_field_allowed_rows']}/{counts['memory_write_allowed_rows']}`
- Public URL / sensitive key / local path leak hits: `{summary['leak_counts']['public_url_hits']}/{summary['leak_counts']['sensitive_key_hits']}/{summary['leak_counts']['local_path_hits']}`

## Source/Raw Target DB Provenance

- Upstream provenance summary: `{target_db['summary']}`
- Upstream provenance decision: `{target_db['decision']}`
- Direct existing explicit source/raw target DB paths: `{target_db['counts']['direct_existing_explicit_source_raw_target_db_paths']}`
- Provenance ready / blocked rows: `{target_db['counts']['ready_rows']}/{target_db['counts']['blocked_rows']}`
- Source/raw target DB ready: `{target_db['source_raw_target_db_ready']}`

## Evidence

- Summary JSON: `{summary['outputs']['summary_json']}`
- All targets: `{summary['outputs']['targets']}`
- Manual acceptance ready rows: `{summary['outputs']['manual_acceptance_ready']}`
- Source/raw target DB blocked rows: `{summary['outputs']['source_raw_target_db_blocked_rows']}`
- Dry-run work orders: `{summary['outputs']['dry_run_work_orders']}`
- Rollback contracts: `{summary['outputs']['rollback_contracts']}`
- Postwrite readback contracts: `{summary['outputs']['postwrite_contracts']}`
- Source-account batches: `{summary['outputs']['source_account_batches']}`

## Next Cursor

`{summary['next_cursor']}`

Remaining event-identity rows are ready only at report-only contract level. Keep write execution closed until a later explicit source/raw target DB real snapshot/write gate supplies target DB provenance, prewrite row hashes, inverse rollback, duplicate-drift checks, and postwrite readback evidence.
"""


def build_packet(
    ready_rows_path: Path,
    readback_summary_path: Path,
    target_db_provenance_summary_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    rows = read_jsonl(ready_rows_path, "ready_rows")
    readback_summary = read_json(readback_summary_path, "readback_summary")
    target_db_provenance_summary = read_json(target_db_provenance_summary_path, "target_db_provenance_summary")
    generated_at = now_iso()

    readback_counts = dict_value(readback_summary.get("counts"))
    expected_ready = int(readback_counts.get("ready_rows") or 0) if readback_counts else len(rows)
    upstream_failed_checks = list_strings(readback_summary.get("failed_checks"), 180)
    target_db_ready = source_raw_target_db_ready(target_db_provenance_summary)

    targets = [build_target(row, generated_at, target_db_ready) for row in rows]
    manual_ready_rows = [row for row in targets if row["manual_event_identity_acceptance_precheck_ready"]]
    source_raw_blocked_rows = [row for row in targets if "source_raw_target_db_provenance_missing" in row["blockers"]]
    row_blocked_rows = [row for row in targets if row["readback_blockers"]]
    batches = group_batches(targets)
    dry_run_rows = [
        row["dry_run_transaction_work_order"] | {"remaining_identity_acceptance_gate_id": row["remaining_identity_acceptance_gate_id"]}
        for row in targets
    ]
    rollback_rows = [
        row["rollback_contract"] | {"remaining_identity_acceptance_gate_id": row["remaining_identity_acceptance_gate_id"]}
        for row in targets
    ]
    postwrite_rows = [
        row["postwrite_readback_contract"] | {"remaining_identity_acceptance_gate_id": row["remaining_identity_acceptance_gate_id"]}
        for row in targets
    ]

    counts = {
        "input_ready_rows": len(rows),
        "write_gate_target_rows": len(targets),
        "manual_event_identity_acceptance_precheck_ready_rows": len(manual_ready_rows),
        "source_raw_target_db_provenance_ready_rows": sum(1 for row in targets if row["source_raw_target_db_provenance_ready_report_only"]),
        "source_raw_target_db_blocked_rows": len(source_raw_blocked_rows),
        "row_blocked_rows": len(row_blocked_rows),
        "source_account_batches": len(batches),
        "unique_selected_event_ids": len({event_id for row in targets for event_id in row["selected_event_ids_review_only"]}),
        "prewrite_snapshot_required_rows": len(targets),
        "rollback_required_rows": len(targets),
        "postwrite_readback_required_rows": len(targets),
        "write_execution_allowed_rows": 0,
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }

    failed_checks: list[str] = []
    if upstream_failed_checks:
        failed_checks.append("upstream_readback_failed_checks_present")
    if expected_ready != len(rows):
        failed_checks.append("input_ready_row_count_mismatch")
    if row_blocked_rows:
        failed_checks.append("row_blockers_present")
    if source_raw_blocked_rows:
        failed_checks.append("source_raw_target_db_provenance_missing")

    target_db_counts = provenance_counts(target_db_provenance_summary)
    decision = (
        "atlas_social_manual_participant_remaining_identity_acceptance_write_gate_ready_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_remaining_identity_acceptance_write_gate_blocked_report_only"
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "targets": out_dir / "remaining_identity_acceptance_write_gate_targets.jsonl",
        "manual_acceptance_ready": out_dir / "manual_event_identity_acceptance_ready_report_only.jsonl",
        "source_raw_target_db_blocked_rows": out_dir / "source_raw_target_db_blocked_rows.jsonl",
        "row_blocked_rows": out_dir / "remaining_identity_acceptance_row_blocked_rows.jsonl",
        "dry_run_work_orders": out_dir / "remaining_identity_acceptance_dry_run_work_orders.jsonl",
        "rollback_contracts": out_dir / "remaining_identity_acceptance_rollback_contracts.jsonl",
        "postwrite_contracts": out_dir / "remaining_identity_acceptance_postwrite_readback_contracts.jsonl",
        "source_account_batches": out_dir / "source_account_remaining_identity_acceptance_batches.jsonl",
        "summary_json": out_dir / "remaining_identity_acceptance_write_gate_summary.json",
        "summary_md": out_dir / "remaining_identity_acceptance_write_gate_summary.md",
    }

    write_jsonl(outputs["targets"], targets)
    write_jsonl(outputs["manual_acceptance_ready"], manual_ready_rows)
    write_jsonl(outputs["source_raw_target_db_blocked_rows"], source_raw_blocked_rows)
    write_jsonl(outputs["row_blocked_rows"], row_blocked_rows)
    write_jsonl(outputs["dry_run_work_orders"], dry_run_rows)
    write_jsonl(outputs["rollback_contracts"], rollback_rows)
    write_jsonl(outputs["postwrite_contracts"], postwrite_rows)
    write_jsonl(outputs["source_account_batches"], batches)

    leak_counts = scan_payload(
        {
            "targets": targets,
            "manual_ready_rows": manual_ready_rows,
            "source_raw_blocked_rows": source_raw_blocked_rows,
            "row_blocked_rows": row_blocked_rows,
            "batches": batches,
        }
    )
    if any(leak_counts.values()):
        failed_checks.append("leak_check_failed")
        decision = "atlas_social_manual_participant_remaining_identity_acceptance_write_gate_blocked_report_only"

    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "counts": counts,
        "target_db_provenance": {
            "summary": display_path(target_db_provenance_summary_path),
            "decision": compact(target_db_provenance_summary.get("decision"), 180),
            "failed_checks": list_strings(target_db_provenance_summary.get("failed_checks"), 180),
            "counts": target_db_counts,
            "source_raw_target_db_ready": target_db_ready,
        },
        "inputs": {
            "ready_rows": display_path(ready_rows_path),
            "readback_summary": display_path(readback_summary_path),
            "target_db_provenance_summary": display_path(target_db_provenance_summary_path),
        },
        "outputs": {key: display_path(value) for key, value in outputs.items()} | {"report": display_path(report_path)},
        "next_cursor": display_path(outputs["source_raw_target_db_blocked_rows"] if source_raw_blocked_rows else outputs["manual_acceptance_ready"]),
        "stop_reason": (
            "remaining_identity_acceptance_write_gate_blocked_source_raw_target_db_provenance_missing"
            if source_raw_blocked_rows
            else "none"
        ),
        "wait_reason": (
            "A later explicit source/raw target DB provenance gate must name an existing source/raw DB and provide prewrite, rollback, duplicate-drift, and postwrite evidence before any write."
            if source_raw_blocked_rows
            else "Report-only acceptance contract is ready, but write execution remains closed until a separate explicit apply gate."
        ),
        "leak_counts": leak_counts,
        "write_guards": {
            "write_execution_allowed_now": False,
            "accepted_for_graph": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "safety": {
            "report_only": True,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
    }

    write_json(outputs["summary_json"], summary)
    write_text(outputs["summary_md"], render_summary_md(summary))
    write_text(report_path, render_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-rows", type=Path, default=DEFAULT_READY_ROWS)
    parser.add_argument("--readback-summary", type=Path, default=DEFAULT_READBACK_SUMMARY)
    parser.add_argument("--target-db-provenance-summary", type=Path, default=DEFAULT_TARGET_DB_PROVENANCE_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_packet(
        args.ready_rows,
        args.readback_summary,
        args.target_db_provenance_summary,
        args.out_dir,
        args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
