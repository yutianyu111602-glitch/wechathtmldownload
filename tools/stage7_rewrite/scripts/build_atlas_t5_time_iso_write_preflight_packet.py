#!/usr/bin/env python3
"""Build a report-only source/raw time_iso write-preflight packet.

This consumes the T6 time-title readback-ready rows and maps the conservative
exact-date subset back to the explicit source/raw Atlas SQLite target in
read-only mode. It prepares prewrite snapshots, inverse rollback contracts, and
postwrite requirements for `events.time_iso`, but it never executes a write.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import build_atlas_t5_city_write_preflight_packet as base


READBACK_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_readback_gate_20260527"
DEFAULT_READY_ROWS = READBACK_DIR / "time_title_readback_ready_report_only.jsonl"
DEFAULT_READBACK_SUMMARY = READBACK_DIR / "time_title_readback_summary.json"
DEFAULT_READBACK_CONTRACT = READBACK_DIR / "time_title_readback_contract.json"
DEFAULT_TARGET_DB_PROVENANCE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_source_raw_mapping_probe_q6_20260526"
    / "source_raw_mapping_target_db_provenance_summary.json"
)
DEFAULT_TARGET_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_time_iso_write_preflight_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_TIME_ISO_WRITE_PREFLIGHT_PACKET_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t5_time_iso_write_preflight.v1"

DATE_RE = re.compile(r"^(20\d{2})-(\d{2})-(\d{2})$")
YEAR_RE = re.compile(r"20\d{2}")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        for row in rows:
            handle.write(base.canonical_json(row))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def parsed_date(value: Any) -> tuple[str, str, str] | None:
    match = DATE_RE.fullmatch(base.compact(value, 40))
    if not match:
        return None
    return match.group(1), str(int(match.group(2))), str(int(match.group(3)))


def date_variant_groups(value: Any) -> tuple[set[str], set[str]]:
    parsed = parsed_date(value)
    if not parsed:
        return set(), set()
    year, month, day = parsed
    mm = f"{int(month):02d}"
    dd = f"{int(day):02d}"
    full = {
        f"{year}{mm}{dd}",
        f"{year}-{mm}-{dd}",
        f"{year}-{int(month)}-{int(day)}",
        f"{year}.{mm}.{dd}",
        f"{year}.{int(month)}.{int(day)}",
        f"{year}/{mm}/{dd}",
        f"{year}/{int(month)}/{int(day)}",
        f"{year}年{month}月{day}日",
        f"{year}年{month}月{dd}日",
        f"{year}年{mm}月{day}日",
        f"{year}年{mm}月{dd}日",
    }
    partial = {
        f"{int(month)}/{int(day)}",
        f"{mm}/{dd}",
        f"{int(month)}.{int(day)}",
        f"{mm}.{dd}",
        f"{month}月{day}日",
        f"{month}月{dd}日",
        f"{mm}月{day}日",
        f"{mm}月{dd}日",
    }
    return full, partial


def date_variants(value: Any) -> set[str]:
    full, partial = date_variant_groups(value)
    return full | partial


def date_matches(candidate_date: str, *texts: Any) -> bool:
    full_variants, partial_variants = date_variant_groups(candidate_date)
    if not full_variants and not partial_variants:
        return False
    haystacks = [base.compact(text, 500) for text in texts if base.compact(text, 500)]
    for haystack in haystacks:
        normalized_haystack = base.normalize_text(haystack)
        if any(variant in haystack or base.normalize_text(variant) in normalized_haystack for variant in full_variants):
            return True
        if YEAR_RE.search(haystack):
            continue
        if any(variant in haystack or base.normalize_text(variant) in normalized_haystack for variant in partial_variants):
            return True
    return False


def raw_event_projection(row: sqlite3.Row) -> dict[str, Any]:
    raw_json = row["raw_json"] if "raw_json" in row.keys() else ""
    return {
        "row_pk": int(row["row_pk"]),
        "evid": base.compact(row["evid"], 120),
        "name": base.compact(row["name"], 240),
        "place": base.compact(row["place"], 240),
        "city": base.compact(row["city"], 120),
        "time_iso": base.compact(row["time_iso"], 120),
        "time_text": base.compact(row["time_text"], 180),
        "source_article_uid_hash": base.short_hash(base.compact(row["source_article_uid"], 500), 16),
        "raw_json_hash": base.hashlib.sha256(str(raw_json or "").encode("utf-8", errors="replace")).hexdigest(),
    }


def build_raw_index(conn: sqlite3.Connection) -> dict[tuple[str, str], list[dict[str, Any]]]:
    sql = """
    SELECT row_pk, evid, name, place, city, time_iso, time_text, source_article_uid, raw_json
    FROM events
    WHERE coalesce(time_iso, '') = ''
      AND coalesce(name, '') <> ''
      AND coalesce(place, '') <> ''
    ORDER BY row_pk
    """
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute(sql):
        key = (base.normalize_text(row["name"]), base.venue_family(row["place"]))
        if key[0] and key[1]:
            item = raw_event_projection(row)
            item["prewrite_row_hash"] = base.row_hash(item)
            index[key].append(item)
    return index


def validate_readback_summary(summary: dict[str, Any], ready_rows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    if summary.get("decision") != "atlas_t6_time_title_readback_gate_ready_report_only":
        failures.append("readback_summary_not_ready")
    if summary.get("failed_checks") not in ([], None):
        failures.append("readback_summary_failed_checks_present")
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    if counts.get("ready_rows") != len(ready_rows):
        failures.append("ready_row_count_mismatch_against_readback_summary")
    if (summary.get("boundary_truth") or {}).get("source_raw_db_opened") is not False:
        failures.append("readback_summary_source_raw_boundary_drift")
    if (summary.get("boundary_truth") or {}).get("serving_sqlite_opened_read_only") is not True:
        failures.append("readback_summary_serving_readonly_missing")
    return failures


def validate_readback_contract(contract: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if contract.get("write_execution_allowed_now") is not False:
        failures.append("readback_contract_write_execution_not_false")
    required = set(contract.get("later_gate_requires") or [])
    expected = {
        "explicit source/raw target DB provenance",
        "source/raw prewrite snapshots for every target row",
        "inverse rollback mapping",
        "postwrite source/raw readback",
        "serving rebuild candidate with no time/participant regression",
    }
    if not expected.issubset(required):
        failures.append("readback_contract_later_gate_requirements_missing")
    return failures


def validate_provenance(provenance: dict[str, Any], target_db: Path) -> tuple[bool, list[str], str]:
    return base.validate_provenance(provenance, target_db)


def raw_required_columns(conn: sqlite3.Connection) -> list[str]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
        return ["events_table_missing"]
    required = {"row_pk", "evid", "name", "place", "city", "time_iso", "time_text", "source_article_uid", "raw_json"}
    missing = sorted(required - base.table_columns(conn, "events"))
    return ["events_required_columns_missing:" + ",".join(missing)] if missing else []


def source_titles(row: dict[str, Any]) -> list[str]:
    values = [
        base.compact(row.get("source_title"), 240),
        base.compact((row.get("evidence_ref_readback") or {}).get("source_title"), 240)
        if isinstance(row.get("evidence_ref_readback"), dict)
        else "",
    ]
    for key in ("performance_event_samples", "dj_event_samples"):
        for item in row.get(key) or []:
            if isinstance(item, dict):
                values.append(base.compact(item.get("event_title"), 240))
    return sorted({item for item in values if item})


def source_venues(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("performance_event_samples", "dj_event_samples"):
        for item in row.get(key) or []:
            if isinstance(item, dict):
                values.append(base.compact(item.get("venue_name"), 240))
    return sorted({item for item in values if item})


def sample_event_ids(row: dict[str, Any], limit: int = 24) -> list[str]:
    ids = [base.compact(item, 160) for item in row.get("performance_event_ids") or [] if base.compact(item, 160)]
    for pair in row.get("dj_event_pairs") or []:
        text = base.compact(pair, 240)
        if "::" in text:
            ids.append(text.split("::", 1)[0])
    return sorted(set(ids))[:limit]


def sample_dj_ids(row: dict[str, Any], limit: int = 24) -> list[str]:
    ids: list[str] = []
    for pair in row.get("dj_event_pairs") or []:
        text = base.compact(pair, 240)
        if "::" in text:
            ids.append(text.split("::", 1)[1])
    return sorted(set(ids))[:limit]


def input_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if row.get("schema_version") != "stage7_atlas_t6_time_title_readback_gate.v1.row":
        blockers.append("readback_row_schema_unexpected")
    if row.get("readback_status") != "time_title_date_readback_ready_report_only":
        blockers.append("readback_status_not_ready")
    if row.get("readback_failures") not in ([], None):
        blockers.append("readback_failures_present")
    candidate_date = base.compact(row.get("candidate_event_date"), 40)
    if not parsed_date(candidate_date):
        blockers.append("candidate_event_date_invalid_or_missing")
    accepted = row.get("accepted_date_candidate")
    if not accepted:
        blockers.append("accepted_date_candidate_missing")
    elif isinstance(accepted, dict):
        accepted_value = base.compact(accepted.get("value"), 40)
        if accepted_value and accepted_value != candidate_date:
            blockers.append("accepted_date_candidate_value_mismatch")
    if row.get("source_raw_db_write_allowed") is not False:
        blockers.append("source_raw_db_write_allowed_not_false")
    if row.get("serving_rebuild_allowed") is not False:
        blockers.append("serving_rebuild_allowed_not_false")
    if row.get("public_serving_field_allowed") is not False:
        blockers.append("public_serving_field_allowed_not_false")
    if row.get("write_gate_allowed_now") is not False:
        blockers.append("write_gate_allowed_now_not_false")
    if not source_titles(row):
        blockers.append("event_title_evidence_missing")
    if not source_venues(row):
        blockers.append("venue_evidence_missing")
    return sorted(set(blockers))


def mapped_readback_row(row: dict[str, Any], raw_rows: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".readback_mapping",
        "generated_at": generated_at,
        "time_title_readback_selector_id": base.compact(row.get("time_title_readback_selector_id"), 160),
        "source_ref_id": base.compact(row.get("source_ref_id"), 160),
        "source_hash_prefix": base.compact(row.get("source_hash_prefix"), 80),
        "candidate_event_date": base.compact(row.get("candidate_event_date"), 40),
        "accepted_date_policy": base.compact((row.get("accepted_date_candidate") or {}).get("evidence_policy"), 160)
        if isinstance(row.get("accepted_date_candidate"), dict)
        else "",
        "title_sample": source_titles(row)[:8],
        "venue_sample": source_venues(row)[:8],
        "serving_event_ids_sample": sample_event_ids(row),
        "serving_dj_ids_sample": sample_dj_ids(row),
        "raw_event_row_pks_report_only": [item["row_pk"] for item in raw_rows],
        "raw_event_match_count": len(raw_rows),
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
    }


def blocked_row(row: dict[str, Any], blockers: list[str], generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".blocked_readback_row",
        "generated_at": generated_at,
        "time_title_readback_selector_id": base.compact(row.get("time_title_readback_selector_id"), 160),
        "source_ref_id": base.compact(row.get("source_ref_id"), 160),
        "source_hash_prefix": base.compact(row.get("source_hash_prefix"), 80),
        "candidate_event_date": base.compact(row.get("candidate_event_date"), 40),
        "blockers": sorted(set(blockers)),
        "title_sample": source_titles(row)[:8],
        "venue_sample": source_venues(row)[:8],
        "serving_event_ids_sample": sample_event_ids(row, limit=12),
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
    }


def ready_raw_row(
    raw_row: dict[str, Any],
    proposed_time_iso: str,
    refs: list[dict[str, Any]],
    target_db_display: str,
    generated_at: str,
) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA_VERSION + ".ready_raw_event_time_iso_row",
        "generated_at": generated_at,
        "target_db": target_db_display,
        "target_table": "events",
        "target_column": "time_iso",
        "raw_event_row_pk": raw_row["row_pk"],
        "raw_event_evid": raw_row["evid"],
        "raw_event_name": raw_row["name"],
        "raw_event_place": raw_row["place"],
        "raw_event_city": raw_row["city"],
        "raw_event_current_time_iso": raw_row["time_iso"],
        "raw_event_time_text": raw_row["time_text"],
        "source_article_uid_hash": raw_row["source_article_uid_hash"],
        "raw_json_hash": raw_row["raw_json_hash"],
        "prewrite_row_hash": raw_row["prewrite_row_hash"],
        "proposed_time_iso": proposed_time_iso,
        "candidate_event_date": proposed_time_iso,
        "candidate_refs": refs[:20],
        "candidate_ref_count": len(refs),
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
        "rollback_required": True,
        "postwrite_readback_required": True,
        "serving_rebuild_required_after_future_write": True,
    }
    row["prewrite_contract_hash"] = base.row_hash(row)
    return row


def rollback_contract(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".rollback_contract",
        "generated_at": generated_at,
        "target_db": row["target_db"],
        "target_table": "events",
        "target_column": "time_iso",
        "raw_event_row_pk": row["raw_event_row_pk"],
        "restore_time_iso": row["raw_event_current_time_iso"],
        "prewrite_row_hash": row["prewrite_row_hash"],
        "verify_contract_hash": row["prewrite_contract_hash"],
        "rollback_required_if_future_write_executes": True,
    }


def postwrite_contract(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".postwrite_readback_contract",
        "generated_at": generated_at,
        "target_db": row["target_db"],
        "target_table": "events",
        "target_column": "time_iso",
        "raw_event_row_pk": row["raw_event_row_pk"],
        "expected_time_iso": row["proposed_time_iso"],
        "expected_source_article_uid_hash": row["source_article_uid_hash"],
        "postwrite_readback_required": True,
        "serving_rebuild_required_after_future_write": True,
        "serving_postbuild_must_not_regress_time_or_participant_coverage": True,
    }


def build_report(summary: dict[str, Any]) -> str:
    c = summary["counts"]
    t = summary["target_db"]
    return "\n".join(
        [
            "# Atlas T5 Time ISO Write Preflight Packet",
            "",
            f"- Generated at: `{summary['generated_at']}`",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            f"- Input/readback mapped/blocked rows: `{c['input_readback_rows']}/{c['mapped_readback_rows']}/{c['blocked_readback_rows']}`",
            f"- Raw `events.time_iso` update targets: `{c['raw_event_time_iso_update_target_rows']}`",
            f"- Duplicate selector/conflict groups: `{c['duplicate_selector_groups']}/{c['conflict_groups']}`",
            f"- Rollback/postwrite contracts: `{c['rollback_contract_rows']}/{c['postwrite_readback_contract_rows']}`",
            f"- Target DB: `{t['display']}`",
            f"- Target opened read-only: `{t['opened_read_only']}`",
            f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
            "",
            "## LLM Audit",
            "",
            "The source/raw DB does not have a `starts_at` column; the safe source/raw field is `events.time_iso`, which the serving read-model maps to `starts_at`. The preflight therefore binds exact-date serving readback rows to raw `events.time_iso` only, using conservative exact normalized title plus venue-family matching and requiring a date token match in raw `name` or `time_text`.",
            "",
            "## Boundary",
            "",
            "Report-only and source/raw SQLite read-only. No source/raw DB write, selected serving mutation/rebuild, graph/vector/public pointer mutation, huaidj.club upload, CloudRun deploy, mini-program upload/review, memory write, credential read, network/OCR/model call, 9router use, destructive Git, or D-root scan occurred.",
            "",
            f"Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def build_packet(
    ready_rows_path: Path,
    readback_summary_path: Path,
    readback_contract_path: Path,
    target_db_provenance_path: Path,
    target_db: Path,
    out_dir: Path,
    report_path: Path,
    max_raw_matches_per_readback: int,
) -> dict[str, Any]:
    generated_at = now_iso()
    out_dir.mkdir(parents=True, exist_ok=True)

    ready_inputs = base.read_jsonl(ready_rows_path, "time_title_readback_ready_rows")
    readback_summary = base.read_json(readback_summary_path, "time_title_readback_summary")
    readback_contract = base.read_json(readback_contract_path, "time_title_readback_contract")
    provenance = base.read_json(target_db_provenance_path, "target_db_provenance")

    upstream_failures = validate_readback_summary(readback_summary, ready_inputs)
    upstream_failures.extend(validate_readback_contract(readback_contract))
    provenance_ready, provenance_blockers, provenance_sha = validate_provenance(provenance, target_db)
    target_db_display = base.display_path(target_db)
    target_db_present = target_db.exists()

    target_schema_hash = ""
    target_db_opened = False
    raw_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    raw_column_failures: list[str] = []
    if target_db_present and provenance_ready:
        conn = base.open_readonly(target_db)
        try:
            target_db_opened = True
            target_schema_hash = base.schema_hash(conn)
            raw_column_failures = raw_required_columns(conn)
            if not raw_column_failures:
                raw_index = build_raw_index(conn)
        finally:
            conn.close()

    critical_blockers = upstream_failures + provenance_blockers + raw_column_failures
    mapped_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    raw_refs: dict[int, dict[str, Any]] = {}
    raw_dates: dict[int, set[str]] = defaultdict(set)
    raw_candidate_refs: dict[int, list[dict[str, Any]]] = defaultdict(list)

    if critical_blockers:
        for row in ready_inputs:
            blocked_rows.append(blocked_row(row, critical_blockers, generated_at))
    else:
        for row in ready_inputs:
            blockers = input_blockers(row)
            candidate_date = base.compact(row.get("candidate_event_date"), 40)
            raw_matches: dict[int, dict[str, Any]] = {}
            if "accepted_date_candidate_value_mismatch" not in blockers:
                for title in source_titles(row):
                    for venue in source_venues(row):
                        key = (base.normalize_text(title), base.venue_family(venue))
                        for raw_row in raw_index.get(key, []):
                            if date_matches(candidate_date, raw_row.get("time_text"), raw_row.get("name")):
                                raw_matches[int(raw_row["row_pk"])] = raw_row
            raw_rows = [raw_matches[key] for key in sorted(raw_matches)]
            if not raw_rows:
                blockers.append("source_raw_exact_title_venue_date_mapping_missing")
            if len(raw_rows) > max_raw_matches_per_readback:
                blockers.append("source_raw_exact_title_venue_date_mapping_too_broad")
            if blockers:
                blocked_rows.append(blocked_row(row, blockers, generated_at))
                continue

            mapped_rows.append(mapped_readback_row(row, raw_rows, generated_at))
            ref = {
                "time_title_readback_selector_id": base.compact(row.get("time_title_readback_selector_id"), 160),
                "source_ref_id": base.compact(row.get("source_ref_id"), 160),
                "source_hash_prefix": base.compact(row.get("source_hash_prefix"), 80),
                "candidate_event_date": candidate_date,
                "serving_event_ids_sample": sample_event_ids(row, limit=12),
                "serving_dj_ids_sample": sample_dj_ids(row, limit=12),
            }
            for raw_row in raw_rows:
                raw_pk = int(raw_row["row_pk"])
                raw_refs[raw_pk] = raw_row
                raw_dates[raw_pk].add(candidate_date)
                raw_candidate_refs[raw_pk].append(ref)

    conflict_groups: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []
    ready_rows: list[dict[str, Any]] = []
    for raw_pk, raw_row in sorted(raw_refs.items()):
        dates = sorted(raw_dates[raw_pk])
        refs = raw_candidate_refs[raw_pk]
        if len(dates) != 1:
            conflict_groups.append(
                {
                    "schema_version": SCHEMA_VERSION + ".conflict_group",
                    "generated_at": generated_at,
                    "raw_event_row_pk": raw_pk,
                    "candidate_event_dates": dates,
                    "candidate_refs": refs[:20],
                    "blocker": "conflicting_candidate_event_dates_for_raw_event",
                }
            )
            continue
        if len(refs) > 1:
            duplicate_groups.append(
                {
                    "schema_version": SCHEMA_VERSION + ".duplicate_selector_group",
                    "generated_at": generated_at,
                    "raw_event_row_pk": raw_pk,
                    "candidate_event_date": dates[0],
                    "candidate_ref_count": len(refs),
                    "candidate_refs": refs[:20],
                    "collapse_policy": "same raw row and same proposed time_iso collapse to one source/raw update target",
                }
            )
        ready_rows.append(ready_raw_row(raw_row, dates[0], refs, target_db_display, generated_at))

    rollback_rows = [rollback_contract(row, generated_at) for row in ready_rows]
    postwrite_rows = [postwrite_contract(row, generated_at) for row in ready_rows]

    output_paths = {
        "summary_json": out_dir / "time_iso_write_preflight_summary.json",
        "summary_md": out_dir / "time_iso_write_preflight_summary.md",
        "contract_json": out_dir / "time_iso_write_preflight_contract.json",
        "ready_raw_event_rows": out_dir / "time_iso_write_preflight_ready_raw_event_rows.jsonl",
        "mapped_readback_rows": out_dir / "time_iso_write_preflight_mapped_readback_rows.jsonl",
        "blocked_rows": out_dir / "time_iso_write_preflight_blocked_rows.jsonl",
        "duplicate_selector_groups": out_dir / "time_iso_write_preflight_duplicate_selector_groups.jsonl",
        "conflict_groups": out_dir / "time_iso_write_preflight_conflict_groups.jsonl",
        "rollback_contracts": out_dir / "time_iso_write_preflight_rollback_contracts.jsonl",
        "postwrite_readback_contracts": out_dir / "time_iso_write_preflight_postwrite_readback_contracts.jsonl",
    }

    write_jsonl(output_paths["ready_raw_event_rows"], ready_rows)
    write_jsonl(output_paths["mapped_readback_rows"], mapped_rows)
    write_jsonl(output_paths["blocked_rows"], blocked_rows)
    write_jsonl(output_paths["duplicate_selector_groups"], duplicate_groups)
    write_jsonl(output_paths["conflict_groups"], conflict_groups)
    write_jsonl(output_paths["rollback_contracts"], rollback_rows)
    write_jsonl(output_paths["postwrite_readback_contracts"], postwrite_rows)

    failed_checks: list[str] = []
    if critical_blockers:
        failed_checks.append("critical_preflight_blockers_present")
    if conflict_groups:
        failed_checks.append("conflict_groups_present")
    decision = (
        "atlas_t5_time_iso_write_preflight_partial_ready_report_only"
        if ready_rows
        else "atlas_t5_time_iso_write_preflight_blocked_report_only"
    )
    counts = {
        "input_readback_rows": len(ready_inputs),
        "mapped_readback_rows": len(mapped_rows),
        "blocked_readback_rows": len(blocked_rows),
        "raw_event_time_iso_update_target_rows": len(ready_rows),
        "duplicate_selector_groups": len(duplicate_groups),
        "conflict_groups": len(conflict_groups),
        "rollback_contract_rows": len(rollback_rows),
        "postwrite_readback_contract_rows": len(postwrite_rows),
        "raw_index_keys": len(raw_index),
        "source_raw_target_db_present": int(target_db_present),
        "source_raw_target_db_opened_read_only": int(target_db_opened),
        "source_raw_target_db_provenance_ready": int(provenance_ready),
        "source_raw_db_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
        "write_execution_allowed_rows": 0,
    }
    contract = {
        "schema_version": SCHEMA_VERSION + ".contract",
        "generated_at": generated_at,
        "target_db": {
            "display": target_db_display,
            "exists": target_db_present,
            "opened_read_only": target_db_opened,
            "schema_sha256": target_schema_hash,
            "provenance_summary": base.display_path(target_db_provenance_path),
            "provenance_sha256": provenance_sha,
            "written": False,
        },
        "mapping_rule": {
            "rule": "time-title readback rows map to raw events only by exact normalized event title, venue family, blank raw time_iso, and raw title/time_text date-token match",
            "target_source_column": "events.time_iso",
            "serving_field_after_rebuild": "starts_at",
            "max_raw_matches_per_readback": max_raw_matches_per_readback,
            "conflict_policy": "conflicting proposed dates for a raw row block that raw row",
        },
        "prewrite_requirements": [
            "re-open source/raw target DB read-only and recheck schema/provenance before any future write",
            "write only events.time_iso for ready raw_event_row_pk selectors",
            "do not modify events.city, place, participants, source article, graph/vector/public state in this writer",
        ],
        "rollback_requirements": [
            "restore each events.time_iso from time_iso_write_preflight_rollback_contracts.jsonl",
            "verify row_pk and prewrite selector identity before rollback",
            "run post-rollback readback if any future write executes",
        ],
        "postwrite_requirements": [
            "read back every events.row_pk time_iso after future confirmed write",
            "build a serving candidate separately and verify starts_at gap deltas",
            "reject serving candidate if time or participant coverage regresses",
            "run graph/search/API smoke before any graph/vector/public promotion",
        ],
        "write_execution_allowed_now": False,
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "inputs": {
            "time_title_readback_ready_rows": base.display_path(ready_rows_path),
            "time_title_readback_summary": base.display_path(readback_summary_path),
            "time_title_readback_contract": base.display_path(readback_contract_path),
            "target_db_provenance_summary": base.display_path(target_db_provenance_path),
            "target_db": target_db_display,
        },
        "target_db": contract["target_db"],
        "outputs": {name: base.display_path(path) for name, path in output_paths.items()},
        "next_resume_pointer": base.display_path(output_paths["ready_raw_event_rows"]),
        "next_if_write_gate_closed": base.display_path(READBACK_DIR / "time_title_readback_blocked_rows.jsonl"),
        "boundary_truth": {
            "report_only": True,
            "source_raw_db_opened_read_only": target_db_opened,
            "source_raw_db_write_executed": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "cloudrun_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_executed": False,
            "network_fetch_executed": False,
            "ocr_executed": False,
            "model_call_executed": False,
            "write_execution_allowed_now": False,
        },
    }
    leak_payload = {"summary": summary, "contract": contract, "ready_rows": ready_rows[:20], "blocked_rows": blocked_rows[:20]}
    leak_scan = base.scan_payload(leak_payload)
    summary["leak_scan"] = leak_scan

    write_json(output_paths["contract_json"], contract)
    write_json(output_paths["summary_json"], summary)
    write_text(output_paths["summary_md"], build_report(summary))
    write_text(report_path, build_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-rows", type=Path, default=DEFAULT_READY_ROWS)
    parser.add_argument("--readback-summary", type=Path, default=DEFAULT_READBACK_SUMMARY)
    parser.add_argument("--readback-contract", type=Path, default=DEFAULT_READBACK_CONTRACT)
    parser.add_argument("--target-db-provenance", type=Path, default=DEFAULT_TARGET_DB_PROVENANCE)
    parser.add_argument("--target-db", type=Path, default=DEFAULT_TARGET_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-raw-matches-per-readback", type=int, default=80)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_packet(
        args.ready_rows,
        args.readback_summary,
        args.readback_contract,
        args.target_db_provenance,
        args.target_db,
        args.out_dir,
        args.report,
        args.max_raw_matches_per_readback,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
