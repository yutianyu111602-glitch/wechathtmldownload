#!/usr/bin/env python3
"""Build a report-only overnight-midnight acceptance/write-gate contract packet."""
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
DEFAULT_READBACK_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_overnight_midnight_readback_gate_q6_20260526"
DEFAULT_READY_ROWS = DEFAULT_READBACK_DIR / "overnight_midnight_readback_ready_report_only.jsonl"
DEFAULT_READBACK_SUMMARY = DEFAULT_READBACK_DIR / "overnight_midnight_readback_gate_summary.json"
DEFAULT_TARGET_DB_PROVENANCE_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_target_db_provenance_q6_20260526"
    / "target_db_provenance_summary.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_overnight_midnight_acceptance_write_gate_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_MIDNIGHT_ACCEPTANCE_WRITE_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_overnight_midnight_acceptance_write_gate.v1"

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
        raise ValueError(f"{label} must not point to D: for overnight-midnight acceptance gate: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def sanitize_report_text(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit).replace("\\", "/")
    text = URL_RE.sub("[url-redacted]", text)
    text = LOCAL_PATH_RE.sub("[local-path-redacted]", text)
    text = re.sub(r"token", "marker", text, flags=re.I)
    text = SECRET_RE.sub("[sensitive-label-redacted]", text)
    return text


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


def boundary_model(row: dict[str, Any]) -> dict[str, Any]:
    return dict_value(row.get("normalized_boundary_report_only"))


def row_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    db_readback = dict_value(row.get("db_readback"))
    later_contract = dict_value(row.get("later_write_contract"))
    rollback_contract = dict_value(row.get("rollback_contract"))
    postwrite_contract = dict_value(row.get("postwrite_verify_contract"))
    model = boundary_model(row)
    event_ids = list_strings(row.get("selected_event_ids_report_only"), 180)
    source_refs = list_strings(row.get("source_ref_ids"), 180)
    counts_by_event = participant_counts(row)
    start_date = compact(model.get("start_date_report_only"), 80)
    midnight_date = compact(model.get("midnight_boundary_date_report_only"), 80)

    if compact(row.get("readback_status")) != "overnight_midnight_boundary_db_readback_gate_ready_report_only":
        blockers.append("readback_status_not_ready")
    if row.get("readback_failures"):
        blockers.append("readback_failures_not_empty")
    if compact(row.get("write_status")) != "report_only":
        blockers.append("write_status_not_report_only")
    if compact(model.get("date_model_report_only")) != "single_overnight_event_midnight_boundary":
        blockers.append("boundary_model_not_single_overnight_midnight")
    if not start_date or not midnight_date:
        blockers.append("boundary_dates_missing")
    if start_date and midnight_date and start_date == midnight_date:
        blockers.append("boundary_dates_not_cross_midnight")
    if compact(model.get("midnight_boundary_time_report_only")) != "00:00":
        blockers.append("midnight_boundary_time_not_0000")
    if model.get("runtime_date_not_used_as_event_date") is not True:
        blockers.append("runtime_date_guard_not_true")
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

    date_values = set(list_strings(performance.get("date_values"), 80))
    if {start_date, midnight_date} - date_values:
        blockers.append("boundary_dates_not_in_readback_date_values")

    for key in [
        "performance_event_missing_event_ids",
        "event_source_ref_mismatch_event_ids",
        "selector_source_ref_missing_in_evidence_ref",
        "participant_evidence_missing_event_ids",
        "boundary_missing_dates",
        "outside_boundary_dates",
    ]:
        if db_readback.get(key):
            blockers.append(key)
    if not db_readback.get("evidence_ref_rows"):
        blockers.append("evidence_ref_rows_missing")
    if not db_readback.get("boundary_segment_readback_rows"):
        blockers.append("boundary_segment_readback_rows_missing")
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
    if later_contract.get("manual_midnight_boundary_acceptance_gate_required") is not True:
        blockers.append("later_write_contract_manual_midnight_gate_not_true")
    if later_contract.get("source_raw_target_db_required") is not True:
        blockers.append("later_write_contract_source_raw_target_db_required_not_true")
    if rollback_contract.get("required") is not True or rollback_contract.get("prewrite_snapshot_required") is not True:
        blockers.append("rollback_contract_incomplete")
    if postwrite_contract.get("required") is not True:
        blockers.append("postwrite_verify_contract_missing")
    return sorted(set(blockers))


def sample_evidence(row: dict[str, Any]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for item in dict_value(row.get("db_readback")).get("evidence_ref_rows") or []:
        if not isinstance(item, dict):
            continue
        samples.append(
            {
                "source_ref_id": compact(item.get("source_ref_id"), 180),
                "source_hash": compact(item.get("source_hash"), 180),
                "source_account": sanitize_report_text(item.get("source_account"), 180),
                "source_kind_label": sanitize_report_text(item.get("source_kind_label") or item.get("source_kind"), 180),
                "post_date": compact(item.get("post_date"), 80),
                "public_url_allowed": item.get("public_url_allowed") is True,
            }
        )
    return samples


def boundary_date_counts(row: dict[str, Any]) -> dict[str, int]:
    raw = dict_value(dict_value(row.get("db_readback")).get("performance_event_rows")).get("date_counts")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        try:
            out[compact(key, 80)] = int(value)
        except (TypeError, ValueError):
            out[compact(key, 80)] = 0
    return out


def build_target(row: dict[str, Any], generated_at: str, target_db_ready: bool) -> dict[str, Any]:
    event_ids = list_strings(row.get("selected_event_ids_report_only"), 180)
    source_refs = list_strings(row.get("source_ref_ids"), 180)
    model = boundary_model(row)
    start_date = compact(model.get("start_date_report_only"), 80)
    midnight_date = compact(model.get("midnight_boundary_date_report_only"), 80)
    selector_id = stable_id(
        "overnightmidnightacceptgate",
        [
            row.get("overnight_midnight_readback_selector_id"),
            row.get("overnight_midnight_correction_id"),
            row.get("article_uid"),
            start_date,
            midnight_date,
            "|".join(event_ids),
            "|".join(source_refs),
        ],
    )
    row_level_blockers = row_blockers(row)
    target_db_blockers: list[str] = []
    if not target_db_ready:
        target_db_blockers.append("source_raw_target_db_provenance_missing")

    manual_ready = not row_level_blockers
    source_raw_ready = manual_ready and target_db_ready
    blockers = sorted(set(row_level_blockers + target_db_blockers))
    participant_by_event = participant_counts(row)

    return {
        "schema_version": f"{SCHEMA_VERSION}.target_row",
        "generated_at": generated_at,
        "overnight_midnight_acceptance_gate_id": selector_id,
        "overnight_midnight_readback_selector_id": compact(row.get("overnight_midnight_readback_selector_id"), 180),
        "overnight_midnight_correction_id": compact(row.get("overnight_midnight_correction_id"), 180),
        "upstream_overnight_span_review_id": compact(row.get("upstream_overnight_span_review_id"), 180),
        "upstream_source_date_context_review_id": compact(row.get("upstream_source_date_context_review_id"), 180),
        "article_uid": compact(row.get("article_uid"), 260),
        "source_account": sanitize_report_text(row.get("source_account"), 180),
        "title": sanitize_report_text(row.get("title"), 260),
        "name": sanitize_report_text(row.get("name"), 260),
        "source_ref_id": compact(row.get("source_ref_id"), 180),
        "source_ref_ids": source_refs,
        "source_hash": compact(row.get("source_hash"), 180),
        "boundary_start_date_report_only": start_date,
        "midnight_boundary_date_report_only": midnight_date,
        "midnight_boundary_time_report_only": compact(model.get("midnight_boundary_time_report_only"), 40),
        "normalized_boundary_label_report_only": compact(model.get("normalized_boundary_label_report_only"), 180),
        "date_model_report_only": compact(model.get("date_model_report_only"), 140),
        "runtime_date_not_used_as_event_date": model.get("runtime_date_not_used_as_event_date") is True,
        "selected_event_ids_report_only": event_ids,
        "selected_event_id_count": len(event_ids),
        "selected_cluster_ids_report_only": list_strings(row.get("selected_cluster_ids_report_only"), 180),
        "candidate_date_values": list_strings(row.get("candidate_date_values"), 80),
        "boundary_date_counts": boundary_date_counts(row),
        "readback_status": compact(row.get("readback_status"), 180),
        "readback_warnings": list_strings(row.get("readback_warnings"), 220),
        "readback_blockers": row_level_blockers,
        "source_raw_target_db_blockers": target_db_blockers,
        "blockers": blockers,
        "manual_midnight_boundary_acceptance_precheck_ready": manual_ready,
        "source_raw_target_db_provenance_ready_report_only": source_raw_ready,
        "source_raw_target_db_provenance_required": True,
        "write_execution_allowed_now": False,
        "write_status": "report_only",
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "target_selector": {
            "article_uid": compact(row.get("article_uid"), 260),
            "source_ref_ids": source_refs,
            "source_hash": compact(row.get("source_hash"), 180),
            "boundary_start_date": start_date,
            "midnight_boundary_date": midnight_date,
            "selected_event_ids": event_ids,
            "representative_event_id": event_ids[0] if event_ids else "",
            "boundary_date_counts": boundary_date_counts(row),
        },
        "participant_evidence_count_by_event": participant_by_event,
        "source_evidence_sample": sample_evidence(row),
        "prewrite_snapshot_contract": {
            "required": True,
            "explicit_source_raw_target_db_required": True,
            "read_only_snapshot_first": True,
            "must_capture_tables": [
                "source/raw event fact table for selected event ids and boundary dates",
                "source/raw article/source_ref lineage table",
                "source/raw participant edge/evidence table",
                "source/raw date/span correction table if present",
            ],
            "must_capture_row_hashes": True,
            "write_execution_allowed_now": False,
        },
        "dry_run_transaction_work_order": {
            "execution_allowed_now": False,
            "operation": "manual_midnight_boundary_acceptance_report_only",
            "would_bind_article_uid": compact(row.get("article_uid"), 260),
            "would_bind_boundary_start_date": start_date,
            "would_bind_midnight_boundary_date": midnight_date,
            "would_bind_midnight_boundary_time": "00:00",
            "would_bind_event_ids": event_ids,
            "would_bind_source_ref_ids": source_refs,
            "requires_operator_review": True,
        },
        "rollback_contract": {
            "required": True,
            "inverse_mapping_required": True,
            "prewrite_snapshot_required": True,
            "postwrite_readback_required": True,
            "boundary_start_date_report_only": start_date,
            "midnight_boundary_date_report_only": midnight_date,
            "selected_event_ids_report_only": event_ids,
            "source_ref_ids": source_refs,
            "write_execution_allowed_now": False,
        },
        "postwrite_readback_contract": {
            "required": True,
            "must_verify": [
                "source/raw target DB row hashes changed only for declared selectors",
                "selected event ids still read back on the two boundary dates",
                "source_ref/source_hash lineage preserved",
                "participant evidence counts are preserved or explicitly explained",
                "serving rebuild candidate diff matches the midnight-boundary write packet",
                "graph/vector/public pointer remain untouched unless a separate gate permits them",
            ],
            "write_execution_allowed_now": False,
        },
    }


def group_batches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[compact(row.get("source_account"), 180)].append(row)
    batches: list[dict[str, Any]] = []
    for source_account, group in sorted(grouped.items()):
        batches.append(
            {
                "schema_version": f"{SCHEMA_VERSION}.source_account_batch",
                "source_account": source_account,
                "target_rows": len(group),
                "manual_midnight_boundary_acceptance_precheck_ready_rows": sum(
                    1 for row in group if row.get("manual_midnight_boundary_acceptance_precheck_ready") is True
                ),
                "source_raw_target_db_blocked_rows": sum(
                    1 for row in group if "source_raw_target_db_provenance_missing" in row.get("blockers", [])
                ),
                "selected_event_id_count_total": sum(len(row.get("selected_event_ids_report_only") or []) for row in group),
                "boundary_dates": sorted(
                    {
                        date
                        for row in group
                        for date in [
                            compact(row.get("boundary_start_date_report_only"), 80),
                            compact(row.get("midnight_boundary_date_report_only"), 80),
                        ]
                        if date
                    }
                ),
                "write_execution_allowed_now": False,
            }
        )
    return batches


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
    manual_ready_rows = [row for row in targets if row["manual_midnight_boundary_acceptance_precheck_ready"]]
    source_raw_blocked_rows = [row for row in targets if "source_raw_target_db_provenance_missing" in row["blockers"]]
    row_blocked_rows = [row for row in targets if row["readback_blockers"]]
    batches = group_batches(targets)
    dry_run_rows = [
        row["dry_run_transaction_work_order"] | {"overnight_midnight_acceptance_gate_id": row["overnight_midnight_acceptance_gate_id"]}
        for row in targets
    ]
    rollback_rows = [
        row["rollback_contract"] | {"overnight_midnight_acceptance_gate_id": row["overnight_midnight_acceptance_gate_id"]}
        for row in targets
    ]
    postwrite_rows = [
        row["postwrite_readback_contract"] | {"overnight_midnight_acceptance_gate_id": row["overnight_midnight_acceptance_gate_id"]}
        for row in targets
    ]

    unique_boundary_dates = {
        date
        for row in targets
        for date in [row["boundary_start_date_report_only"], row["midnight_boundary_date_report_only"]]
        if date
    }
    boundary_start_rows = sum(row["boundary_date_counts"].get(row["boundary_start_date_report_only"], 0) for row in targets)
    midnight_date_rows = sum(row["boundary_date_counts"].get(row["midnight_boundary_date_report_only"], 0) for row in targets)
    boundary_segment_rows = sum(len(dict_value(row.get("db_readback")).get("boundary_segment_readback_rows") or []) for row in rows)

    counts = {
        "input_ready_rows": len(rows),
        "write_gate_target_rows": len(targets),
        "manual_midnight_boundary_acceptance_precheck_ready_rows": len(manual_ready_rows),
        "source_raw_target_db_provenance_ready_rows": sum(1 for row in targets if row["source_raw_target_db_provenance_ready_report_only"]),
        "source_raw_target_db_blocked_rows": len(source_raw_blocked_rows),
        "row_blocked_rows": len(row_blocked_rows),
        "source_account_batches": len(batches),
        "unique_selected_event_ids": len({event_id for row in targets for event_id in row["selected_event_ids_report_only"]}),
        "unique_boundary_dates": len(unique_boundary_dates),
        "boundary_segment_rows": boundary_segment_rows,
        "boundary_start_date_event_rows": boundary_start_rows,
        "midnight_boundary_date_event_rows": midnight_date_rows,
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
        "atlas_social_manual_participant_overnight_midnight_acceptance_write_gate_ready_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_overnight_midnight_acceptance_write_gate_blocked_report_only"
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "targets": out_dir / "overnight_midnight_acceptance_write_gate_targets.jsonl",
        "manual_acceptance_ready": out_dir / "manual_midnight_boundary_acceptance_ready_report_only.jsonl",
        "source_raw_target_db_blocked_rows": out_dir / "source_raw_target_db_blocked_rows.jsonl",
        "row_blocked_rows": out_dir / "overnight_midnight_acceptance_row_blocked_rows.jsonl",
        "dry_run_work_orders": out_dir / "overnight_midnight_acceptance_dry_run_work_orders.jsonl",
        "rollback_contracts": out_dir / "overnight_midnight_acceptance_rollback_contracts.jsonl",
        "postwrite_contracts": out_dir / "overnight_midnight_acceptance_postwrite_readback_contracts.jsonl",
        "source_account_batches": out_dir / "source_account_overnight_midnight_acceptance_batches.jsonl",
        "summary_json": out_dir / "overnight_midnight_acceptance_write_gate_summary.json",
        "summary_md": out_dir / "overnight_midnight_acceptance_write_gate_summary.md",
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
        decision = "atlas_social_manual_participant_overnight_midnight_acceptance_write_gate_blocked_report_only"

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
            "overnight_midnight_readback_ready_rows": display_path(ready_rows_path),
            "overnight_midnight_readback_summary": display_path(readback_summary_path),
            "target_db_provenance_summary": display_path(target_db_provenance_summary_path),
        },
        "outputs": {key: display_path(value) for key, value in outputs.items()},
        "leak_counts": leak_counts,
        "write_guards": {
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
            "write_execution_allowed_now": False,
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
            "ocr_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "source_raw_target_db_provenance_missing" if source_raw_blocked_rows else "report_only_write_gate_contract_ready",
        "wait_reason": (
            "Manual midnight-boundary row is acceptance-precheck ready, but source/raw DB provenance remains missing; "
            "do not write until an explicit target DB, prewrite snapshots, rollback, and postwrite evidence exist."
            if source_raw_blocked_rows
            else "Rows may feed a later explicit source/raw DB real snapshot gate; this packet still executes no writes."
        ),
        "next_resume_pointer": display_path(outputs["source_raw_target_db_blocked_rows"] if source_raw_blocked_rows else outputs["manual_acceptance_ready"]),
        "next_resume_pointer_split": {
            "manual_midnight_boundary_acceptance_ready": display_path(outputs["manual_acceptance_ready"]),
            "source_raw_target_db_blocked": display_path(outputs["source_raw_target_db_blocked_rows"]),
            "event_date_or_source_year_recovery": "tools/stage7_rewrite/reports/atlas_social_manual_participant_blocked_identity_review_q6_20260526/event_date_or_source_year_recovery_work_orders.jsonl",
            "same_date_cluster_tiebreak": "tools/stage7_rewrite/reports/atlas_social_manual_participant_blocked_identity_review_q6_20260526/same_date_cluster_tiebreak_work_orders.jsonl",
            "venue_alias_lineage_review": "tools/stage7_rewrite/reports/atlas_social_manual_participant_blocked_identity_review_q6_20260526/venue_alias_lineage_work_orders.jsonl",
        },
    }

    write_json(outputs["summary_json"], summary)
    write_text(outputs["summary_md"], render_summary_md(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary_md(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return (
        "# Overnight-Midnight Acceptance Write Gate Summary\n\n"
        f"- Decision: `{summary['decision']}`\n"
        f"- Failed checks: `{summary['failed_checks']}`\n"
        f"- Targets: `{counts['write_gate_target_rows']}`\n"
        f"- Manual midnight-boundary acceptance precheck ready: `{counts['manual_midnight_boundary_acceptance_precheck_ready_rows']}`\n"
        f"- Source/raw target DB blocked: `{counts['source_raw_target_db_blocked_rows']}`\n"
        f"- Boundary start / midnight event rows: `{counts['boundary_start_date_event_rows']}/{counts['midnight_boundary_date_event_rows']}`\n"
        f"- Write execution allowed rows: `{counts['write_execution_allowed_rows']}`\n"
        f"- Leak hits: `{summary['leak_counts']['public_url_hits']}/"
        f"{summary['leak_counts']['sensitive_key_hits']}/{summary['leak_counts']['local_path_hits']}`\n"
        f"- Next resume pointer: `{summary['next_resume_pointer']}`\n"
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    target_db = summary["target_db_provenance"]
    return f"""# Atlas T6 Manual Participant Overnight-Midnight Acceptance Write Gate - 2026-05-26

## Decision

- Decision: `{summary['decision']}`
- Failed checks: `{summary['failed_checks']}`
- Boundary: report-only manual midnight-boundary acceptance/source-raw DB provenance write-gate contract. It does not open source/raw Atlas DB, write source/raw DB, rebuild or write serving SQLite, accept graph facts, write Neo4j/Qdrant/SQLite production state, update public pointers, deploy CloudRun/VPS, upload/review mini-program, execute OCR/network/model calls, or write memory.

## Counts

- Input readback-ready rows: `{counts['input_ready_rows']}`
- Write-gate target rows: `{counts['write_gate_target_rows']}`
- Manual midnight-boundary acceptance precheck ready rows: `{counts['manual_midnight_boundary_acceptance_precheck_ready_rows']}`
- Source/raw target DB provenance ready / blocked rows: `{counts['source_raw_target_db_provenance_ready_rows']}/{counts['source_raw_target_db_blocked_rows']}`
- Row-blocked rows: `{counts['row_blocked_rows']}`
- Source-account batches: `{counts['source_account_batches']}`
- Unique selected event ids / boundary dates: `{counts['unique_selected_event_ids']}/{counts['unique_boundary_dates']}`
- Boundary segment rows: `{counts['boundary_segment_rows']}`
- Boundary-start / midnight-date event rows: `{counts['boundary_start_date_event_rows']}/{counts['midnight_boundary_date_event_rows']}`
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
- Manual midnight-boundary acceptance ready rows: `{summary['outputs']['manual_acceptance_ready']}`
- Source/raw target DB blocked rows: `{summary['outputs']['source_raw_target_db_blocked_rows']}`
- Dry-run work orders: `{summary['outputs']['dry_run_work_orders']}`
- Rollback contracts: `{summary['outputs']['rollback_contracts']}`
- Postwrite readback contracts: `{summary['outputs']['postwrite_contracts']}`
- Source-account batches: `{summary['outputs']['source_account_batches']}`

## Next Resume Pointer

`{summary['next_resume_pointer']}`

Manual midnight-boundary rows are ready only at report-only contract level. Keep write execution closed until a later explicit source/raw DB real snapshot/write gate supplies target DB provenance, prewrite row hashes, inverse rollback, and postwrite readback evidence.
"""


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
