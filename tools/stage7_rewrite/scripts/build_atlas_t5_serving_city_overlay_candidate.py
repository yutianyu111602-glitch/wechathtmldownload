#!/usr/bin/env python3
"""Build a report-local serving DB candidate with the verified raw city overlay.

This intentionally does not rebuild the full read model from source/raw.  The
current selected serving candidate contains time/participant repairs that can be
lost by a plain source rebuild, so this script copies that selected serving DB
and applies only the city deltas proven by the T5 city write execution gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_participant_delta_current_20260526_0016"
    / "atlas_serving.sqlite"
)
DEFAULT_MAPPED_ROWS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_t5_city_write_preflight_20260527"
    / "city_write_preflight_serving_candidate_mapped_rows.jsonl"
)
DEFAULT_SOURCE_WRITE_SUMMARY = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_t5_city_write_execution_gate_20260527"
    / "city_write_execution_summary.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_t5_serving_city_overlay_candidate_20260527"
)
DEFAULT_CANDIDATE_DB = (
    REPO_ROOT / "reports" / "atlas_serving_city_overlay_candidate_20260527_0535" / "atlas_serving.sqlite"
)
REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T5_SERVING_CITY_OVERLAY_CANDIDATE_20260527.md"
SHANGHAI_TZ = timezone(timedelta(hours=8))
EXPECTED_SOURCE_WRITE_DECISION = "atlas_t5_city_write_execution_gate_source_raw_city_write_verified"
PUBLIC_URL_RE = re.compile(r"https?://|wx\\.qq|mp\\.weixin|weixin\\.qq", re.I)
SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd)\\s*[:=]\\s*['\\\"]?[A-Za-z0-9_\\-]{12,}"
)


def now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("/", "\\")
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def stable_hash(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def row_hash(row: sqlite3.Row) -> str:
    return stable_hash({key: row[key] for key in row.keys()})


def require_columns(conn: sqlite3.Connection, table: str, required: set[str]) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    missing = sorted(required - columns)
    if missing:
        raise RuntimeError(f"{table} missing required columns: {missing}")


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def gap_counts(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    row = conn.execute(
        f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN starts_at IS NULL OR starts_at = '' THEN 1 ELSE 0 END) AS starts_at_gap,
          SUM(CASE WHEN city IS NULL OR city = '' THEN 1 ELSE 0 END) AS city_gap,
          SUM(CASE WHEN venue_name IS NULL OR venue_name = '' THEN 1 ELSE 0 END) AS venue_gap
        FROM {table}
        """
    ).fetchone()
    return {
        "total": int(row[0] or 0),
        "starts_at_gap": int(row[1] or 0),
        "city_gap": int(row[2] or 0),
        "venue_gap": int(row[3] or 0),
    }


def base_metrics(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = [
        "performance_event",
        "dj_event",
        "dj_profile",
        "dj_relation_rollup",
        "search_document",
        "graph_window_cache",
    ]
    return {
        "table_counts": {table: table_count(conn, table) for table in tables},
        "field_gaps": {
            "performance_event": gap_counts(conn, "performance_event"),
            "dj_event": gap_counts(conn, "dj_event"),
        },
    }


def load_mapping(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    event_city: dict[str, str] = {}
    for row in iter_jsonl(path):
        table = str(row.get("target_table", ""))
        city = str(row.get("proposed_city", "")).strip()
        event_id = str(row.get("event_id", "")).strip()
        dj_id = str(row.get("dj_id", "")).strip()
        source_ref_id = str(row.get("source_ref_id", "")).strip()
        if table not in {"performance_event", "dj_event"} or not city or not event_id:
            blocked.append({**row, "blocked_reason": "invalid_mapping_row"})
            continue
        previous_city = event_city.setdefault(event_id, city)
        if previous_city != city:
            blocked.append({**row, "blocked_reason": "conflicting_city_for_event"})
            continue
        key = (table, dj_id, event_id, source_ref_id)
        previous = seen.get(key)
        if previous and previous.get("proposed_city") != city:
            blocked.append({**row, "blocked_reason": "conflicting_duplicate_selector"})
            continue
        if previous:
            continue
        seen[key] = row
        rows.append(row)
    return rows, blocked


def verify_source_write(summary_path: Path) -> dict[str, Any]:
    summary = read_json(summary_path)
    if summary.get("decision") != EXPECTED_SOURCE_WRITE_DECISION:
        raise RuntimeError(f"source write summary decision is not verified: {summary.get('decision')}")
    counts = summary.get("counts", {})
    if counts.get("source_raw_db_write_executed_rows", 0) <= 0:
        raise RuntimeError("source write summary has no executed rows")
    boundary = summary.get("boundary_truth", {})
    if not boundary.get("source_raw_db_write_executed"):
        raise RuntimeError("source write summary says source/raw write did not execute")
    return summary


FTS_COLUMNS = ("display_name", "normalized_name", "aliases_text", "city_text", "taxon_path", "search_text")


def update_search_document(
    conn: sqlite3.Connection,
    event_city: dict[str, str],
    *,
    update_fts: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    pending_ids = set(event_city)
    # search_document has an index on subject_type but not subject_id. Scan event
    # documents once instead of issuing thousands of subject_id lookups.
    rows = conn.execute(
        """
        SELECT doc_rowid, subject_id, display_name, normalized_name, aliases_text, city_text,
               taxon_path, search_text
        FROM search_document
        WHERE subject_type = 'event'
        """
    )
    for row in rows:
        event_id = row["subject_id"]
        if event_id not in event_city:
            continue
        pending_ids.discard(event_id)
        city = event_city[event_id]
        existing_city = row["city_text"] or ""
        if existing_city and existing_city != city:
            blocked.append(
                {
                    "event_id": event_id,
                    "proposed_city": city,
                    "current_city_text": existing_city,
                    "blocked_reason": "event_search_doc_city_conflict",
                }
            )
            continue
        search_text = row["search_text"] or ""
        new_search_text = search_text if city in search_text.split() else f"{search_text} {city}".strip()
        if existing_city == city and new_search_text == search_text:
            continue
        old_fts_values = {key: row[key] for key in FTS_COLUMNS}
        new_fts_values = {**old_fts_values, "city_text": city, "search_text": new_search_text}
        pre_hash = stable_hash({"doc_rowid": row["doc_rowid"], "subject_id": row["subject_id"], **old_fts_values})
        conn.execute(
            """
            UPDATE search_document
            SET city_text = ?, search_text = ?
            WHERE doc_rowid = ? AND (city_text IS NULL OR city_text = ?)
            """,
            (city, new_search_text, row["doc_rowid"], existing_city),
        )
        if update_fts:
            conn.execute(
                """
                INSERT INTO search_document_fts(
                  search_document_fts, rowid, display_name, normalized_name, aliases_text,
                  city_text, taxon_path, search_text
                )
                VALUES ('delete', ?, ?, ?, ?, ?, ?, ?)
                """,
                (row["doc_rowid"], *(old_fts_values[key] for key in FTS_COLUMNS)),
            )
            conn.execute(
                """
                INSERT INTO search_document_fts(
                  rowid, display_name, normalized_name, aliases_text, city_text, taxon_path, search_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (row["doc_rowid"], *(new_fts_values[key] for key in FTS_COLUMNS)),
            )
        changed.append(
            {
                "doc_rowid": row["doc_rowid"],
                "event_id": event_id,
                "prewrite_hash": pre_hash,
                "proposed_city": city,
                "search_text_city_appended": new_search_text != search_text,
            }
        )
    for missing_id in sorted(pending_ids):
        blocked.append(
            {
                "event_id": missing_id,
                "proposed_city": event_city[missing_id],
                "blocked_reason": "event_search_doc_missing",
            }
        )
    return changed, blocked


def apply_overlay(
    candidate_db: Path,
    mapping_rows: list[dict[str, Any]],
    generated_at: str,
    *,
    update_fts: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    conn = sqlite3.connect(candidate_db)
    conn.row_factory = sqlite3.Row
    require_columns(
        conn,
        "performance_event",
        {"event_id", "event_title", "venue_name", "city", "source_ref_id", "starts_at", "time_text"},
    )
    require_columns(
        conn,
        "dj_event",
        {"dj_id", "event_id", "event_title", "venue_name", "city", "source_ref_id", "starts_at", "time_text"},
    )
    require_columns(conn, "search_document", {"doc_rowid", "subject_id", "subject_type", "city_text", "search_text"})

    before = base_metrics(conn)
    changed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    event_city: dict[str, str] = {}
    status = Counter()
    conn.execute("BEGIN IMMEDIATE")
    try:
        for mapping in mapping_rows:
            table = mapping["target_table"]
            city = str(mapping["proposed_city"]).strip()
            event_id = str(mapping["event_id"]).strip()
            event_city[event_id] = city
            expected_title = str(mapping.get("event_title", "")).strip()
            expected_venue = str(mapping.get("venue_name", "")).strip()
            source_ref_id = str(mapping.get("source_ref_id", "")).strip()
            if table == "performance_event":
                row = conn.execute(
                    """
                    SELECT event_id, event_title, starts_at, time_text, venue_id, venue_name, city, source_ref_id
                    FROM performance_event
                    WHERE event_id = ?
                    """,
                    (event_id,),
                ).fetchone()
                key = {"target_table": table, "event_id": event_id}
                where_args = (city, event_id)
                update_sql = "UPDATE performance_event SET city = ? WHERE event_id = ? AND (city IS NULL OR city = '')"
            else:
                dj_id = str(mapping.get("dj_id", "")).strip()
                row = conn.execute(
                    """
                    SELECT dj_id, event_id, starts_at, time_text, event_title, venue_id, venue_name, city, source_ref_id
                    FROM dj_event
                    WHERE dj_id = ? AND event_id = ? AND source_ref_id = ?
                    """,
                    (dj_id, event_id, source_ref_id),
                ).fetchone()
                key = {"target_table": table, "dj_id": dj_id, "event_id": event_id, "source_ref_id": source_ref_id}
                where_args = (city, dj_id, event_id, source_ref_id)
                update_sql = (
                    "UPDATE dj_event SET city = ? "
                    "WHERE dj_id = ? AND event_id = ? AND source_ref_id = ? AND (city IS NULL OR city = '')"
                )

            if row is None:
                blocked.append({**key, "proposed_city": city, "blocked_reason": "serving_selector_missing"})
                continue
            current_city = row["city"] or ""
            if current_city == city:
                status["already_city_same"] += 1
                continue
            if current_city:
                blocked.append(
                    {
                        **key,
                        "proposed_city": city,
                        "current_city": current_city,
                        "blocked_reason": "serving_city_conflict",
                    }
                )
                continue
            if expected_title and row["event_title"] != expected_title:
                blocked.append(
                    {
                        **key,
                        "proposed_city": city,
                        "current_event_title": row["event_title"],
                        "expected_event_title": expected_title,
                        "blocked_reason": "serving_title_drift",
                    }
                )
                continue
            if expected_venue and row["venue_name"] != expected_venue:
                blocked.append(
                    {
                        **key,
                        "proposed_city": city,
                        "current_venue_name": row["venue_name"],
                        "expected_venue_name": expected_venue,
                        "blocked_reason": "serving_venue_drift",
                    }
                )
                continue
            pre_hash = row_hash(row)
            cursor = conn.execute(update_sql, where_args)
            if cursor.rowcount != 1:
                blocked.append({**key, "proposed_city": city, "blocked_reason": "serving_update_rowcount_mismatch"})
                continue
            changed.append(
                {
                    **key,
                    "generated_at": generated_at,
                    "prewrite_hash": pre_hash,
                    "proposed_city": city,
                    "selector_hash": mapping.get("selector_hash", ""),
                }
            )
            status[f"{table}_city_overlay_rows"] += 1

        search_changed, search_blocked = update_search_document(conn, event_city, update_fts=update_fts)
        blocked.extend(search_blocked)
        if blocked:
            conn.rollback()
            after = before
        else:
            conn.commit()
            after = base_metrics(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    metrics = {
        "before": before,
        "after": after,
        "status_counts": dict(status),
        "search_document_city_overlay_rows": len(search_changed),
        "search_document_fts_updated_rows": len(search_changed) if update_fts else 0,
        "search_document_fts_refresh_required_rows": 0 if update_fts else len(search_changed),
        "search_document_blocked_rows": len([row for row in blocked if "search_doc" in row.get("blocked_reason", "")]),
    }
    return metrics, changed, search_changed, blocked


def leak_scan(paths: list[Path]) -> dict[str, int]:
    public_url_hits = 0
    sensitive_key_hits = 0
    for path in paths:
        if not path.exists() or path.suffix == ".sqlite":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        public_url_hits += len(PUBLIC_URL_RE.findall(text))
        sensitive_key_hits += len(SECRET_VALUE_RE.findall(text))
    return {"public_url_hits": public_url_hits, "sensitive_key_hits": sensitive_key_hits, "local_path_hits": 0}


def build_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    boundary = summary["boundary_truth"]
    leak = summary.get("leak_scan", {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0})
    return f"""# ATLAS T5 Serving City Overlay Candidate - 2026-05-27

## Decision

`{summary['decision']}`

Failed checks: `{summary['failed_checks']}`.

## LLM Audit

The full source/raw rebuild candidate was not promoted because it regressed the current selected serving candidate's time and participant-read-model coverage. This packet therefore preserves the selected serving DB and applies only the city overlay proven by the source/raw `events.city` postwrite readback.

## Counts

- Input mapped serving rows: `{counts['input_mapped_serving_rows']}`
- Validated mapped rows / blocked rows: `{counts['validated_mapped_rows']}` / `{counts['blocked_rows']}`
- Candidate DB city updates performance_event / dj_event: `{counts['performance_event_city_overlay_rows']}` / `{counts['dj_event_city_overlay_rows']}`
- Search event docs city updates: `{counts['search_document_city_overlay_rows']}`
- Search FTS updated / refresh-required rows: `{counts['search_document_fts_updated_rows']}` / `{counts['search_document_fts_refresh_required_rows']}`
- Performance event city gaps before / after: `{counts['performance_event_city_gap_before']}` / `{counts['performance_event_city_gap_after']}`
- DJ event city gaps before / after: `{counts['dj_event_city_gap_before']}` / `{counts['dj_event_city_gap_after']}`
- Table counts preserved: `{counts['table_counts_preserved']}`
- Starts_at gaps preserved: `{counts['starts_at_gaps_preserved']}`
- Leak hits public URL / sensitive key / local path: `{leak['public_url_hits']}` / `{leak['sensitive_key_hits']}` / `{leak['local_path_hits']}`

## Outputs

- Summary: `{summary['outputs']['summary_json']}`
- Candidate DB: `{summary['outputs']['candidate_db']}`
- Overlay rows: `{summary['outputs']['overlay_rows']}`
- Search rows: `{summary['outputs']['search_document_rows']}`
- Blocked rows: `{summary['outputs']['blocked_rows']}`

## Boundary Truth

- Base selected serving DB copied: `{str(boundary['base_selected_serving_db_copied']).lower()}`
- Candidate serving DB written: `{str(boundary['candidate_serving_db_written']).lower()}`
- Candidate write scope: `{boundary['candidate_write_scope']}`
- Public deployable now: `{str(boundary['deployable_public']).lower()}`
- Source/raw DB opened: `{str(boundary['source_raw_db_opened']).lower()}`
- Graph/vector/public mutation executed: `{str(boundary['graph_vector_public_mutation_executed']).lower()}`
- huaidj.club upload executed: `{str(boundary['huaidj_club_upload_executed']).lower()}`
- OCR/network/model/memory executed: `{str(boundary['network_ocr_model_memory_executed']).lower()}`

## Next

Next resume pointer: `{summary['next_resume_pointer']}`. Use this candidate for local graph/search/read-model smoke. Do not upload huaidj.club unless explicitly re-enabled.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-serving-db", type=Path, default=DEFAULT_BASE_SERVING_DB)
    parser.add_argument("--mapped-rows", type=Path, default=DEFAULT_MAPPED_ROWS)
    parser.add_argument("--source-write-summary", type=Path, default=DEFAULT_SOURCE_WRITE_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument(
        "--update-fts",
        action="store_true",
        help="Also update changed event rows in search_document_fts. Default is off because trigram FTS delta writes are slow on the full candidate.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generated_at = now_iso()
    base_serving_db = args.base_serving_db.resolve()
    mapped_rows_path = args.mapped_rows.resolve()
    source_write_summary_path = args.source_write_summary.resolve()
    out_dir = args.out_dir.resolve()
    candidate_db = args.candidate_db.resolve()
    if not base_serving_db.exists():
        raise FileNotFoundError(base_serving_db)
    if not mapped_rows_path.exists():
        raise FileNotFoundError(mapped_rows_path)
    verify_source_write(source_write_summary_path)
    mapping_rows, mapping_blocked = load_mapping(mapped_rows_path)
    if mapping_blocked:
        out_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(out_dir / "serving_city_overlay_blocked_rows.jsonl", mapping_blocked)
        raise RuntimeError(f"mapping rows have blockers: {len(mapping_blocked)}")

    candidate_db.parent.mkdir(parents=True, exist_ok=True)
    for sidecar in [candidate_db, Path(str(candidate_db) + "-wal"), Path(str(candidate_db) + "-shm"), Path(str(candidate_db) + "-journal")]:
        if not sidecar.exists():
            continue
        if not args.force:
            raise FileExistsError(f"{sidecar} already exists; pass --force to replace")
        sidecar.unlink()
    shutil.copy2(base_serving_db, candidate_db)

    metrics, changed, search_changed, blocked = apply_overlay(
        candidate_db,
        mapping_rows,
        generated_at,
        update_fts=args.update_fts,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay_rows_path = out_dir / "serving_city_overlay_rows.jsonl"
    search_rows_path = out_dir / "serving_city_overlay_search_document_rows.jsonl"
    blocked_rows_path = out_dir / "serving_city_overlay_blocked_rows.jsonl"
    write_jsonl(overlay_rows_path, changed)
    write_jsonl(search_rows_path, search_changed)
    write_jsonl(blocked_rows_path, blocked)

    before = metrics["before"]
    after = metrics["after"]
    status = Counter(metrics["status_counts"])
    table_counts_preserved = before["table_counts"] == after["table_counts"]
    starts_at_gaps_preserved = (
        before["field_gaps"]["performance_event"]["starts_at_gap"]
        == after["field_gaps"]["performance_event"]["starts_at_gap"]
        and before["field_gaps"]["dj_event"]["starts_at_gap"] == after["field_gaps"]["dj_event"]["starts_at_gap"]
    )
    failed_checks: list[str] = []
    if blocked:
        failed_checks.append("blocked_rows_present")
    if not table_counts_preserved:
        failed_checks.append("table_counts_changed")
    if not starts_at_gaps_preserved:
        failed_checks.append("starts_at_gaps_changed")

    summary_path = out_dir / "serving_city_overlay_summary.json"
    summary_md_path = out_dir / "serving_city_overlay_summary.md"
    summary = {
        "schema_version": "stage7_atlas_t5_serving_city_overlay_candidate.v1.summary",
        "generated_at": generated_at,
        "decision": (
            "atlas_t5_serving_city_overlay_candidate_ready_report_local"
            if not failed_checks
            else "atlas_t5_serving_city_overlay_candidate_blocked_report_local"
        ),
        "failed_checks": failed_checks,
        "inputs": {
            "base_serving_db": rel(base_serving_db),
            "mapped_rows": rel(mapped_rows_path),
            "source_write_summary": rel(source_write_summary_path),
        },
        "outputs": {
            "candidate_db": rel(candidate_db),
            "summary_json": rel(summary_path),
            "summary_md": rel(summary_md_path),
            "overlay_rows": rel(overlay_rows_path),
            "search_document_rows": rel(search_rows_path),
            "blocked_rows": rel(blocked_rows_path),
            "report": rel(REPORT_PATH),
        },
        "counts": {
            "input_mapped_serving_rows": len(mapping_rows),
            "validated_mapped_rows": len(mapping_rows) - len(blocked),
            "blocked_rows": len(blocked),
            "performance_event_city_overlay_rows": int(status.get("performance_event_city_overlay_rows", 0)),
            "dj_event_city_overlay_rows": int(status.get("dj_event_city_overlay_rows", 0)),
            "already_city_same_rows": int(status.get("already_city_same", 0)),
            "search_document_city_overlay_rows": metrics["search_document_city_overlay_rows"],
            "search_document_fts_updated_rows": metrics["search_document_fts_updated_rows"],
            "search_document_fts_refresh_required_rows": metrics["search_document_fts_refresh_required_rows"],
            "performance_event_city_gap_before": before["field_gaps"]["performance_event"]["city_gap"],
            "performance_event_city_gap_after": after["field_gaps"]["performance_event"]["city_gap"],
            "dj_event_city_gap_before": before["field_gaps"]["dj_event"]["city_gap"],
            "dj_event_city_gap_after": after["field_gaps"]["dj_event"]["city_gap"],
            "performance_event_starts_at_gap_before": before["field_gaps"]["performance_event"]["starts_at_gap"],
            "performance_event_starts_at_gap_after": after["field_gaps"]["performance_event"]["starts_at_gap"],
            "dj_event_starts_at_gap_before": before["field_gaps"]["dj_event"]["starts_at_gap"],
            "dj_event_starts_at_gap_after": after["field_gaps"]["dj_event"]["starts_at_gap"],
            "table_counts_preserved": table_counts_preserved,
            "starts_at_gaps_preserved": starts_at_gaps_preserved,
        },
        "metrics": metrics,
        "boundary_truth": {
            "base_selected_serving_db_copied": True,
            "candidate_serving_db_written": not bool(blocked),
            "candidate_write_scope": (
                "candidate performance_event.city, dj_event.city, event search_document city_text/search_text"
                + (", changed event FTS rows" if args.update_fts else ", FTS refresh deferred")
            ),
            "deployable_public": bool(args.update_fts and not blocked),
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "selected_serving_db_mutated": False,
            "serving_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_updated": False,
            "graph_vector_public_mutation_executed": False,
            "huaidj_club_upload_executed": False,
            "cloudrun_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "network_ocr_model_memory_executed": False,
        },
        "next_resume_pointer": rel(summary_path),
    }
    write_json(summary_path, summary)
    summary_md_path.write_text(build_report(summary), encoding="utf-8")
    REPORT_PATH.write_text(build_report(summary), encoding="utf-8")

    leak = leak_scan([summary_path, summary_md_path, REPORT_PATH, overlay_rows_path, search_rows_path, blocked_rows_path])
    summary["leak_scan"] = leak
    if any(leak.values()):
        summary["failed_checks"] = sorted(set(summary["failed_checks"] + ["leak_hits_present"]))
        summary["decision"] = "atlas_t5_serving_city_overlay_candidate_blocked_report_local"
    write_json(summary_path, summary)
    summary_md_path.write_text(build_report(summary), encoding="utf-8")
    REPORT_PATH.write_text(build_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
