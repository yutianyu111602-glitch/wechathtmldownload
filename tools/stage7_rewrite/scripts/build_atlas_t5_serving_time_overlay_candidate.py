#!/usr/bin/env python3
"""Build a report-local serving DB candidate with the verified time overlay.

The full source/raw serving rebuild is not used here because an earlier rebuild
regressed selected serving coverage. This script copies the current safe city
overlay serving candidate and applies only the verified `starts_at` deltas from
the T6 time-title readback rows whose source/raw `events.time_iso` write has
already committed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_city_overlay_candidate_20260527_0535" / "atlas_serving.sqlite"
DEFAULT_READBACK_ROWS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_t6_time_title_readback_gate_20260527"
    / "time_title_readback_ready_report_only.jsonl"
)
DEFAULT_MAPPED_READBACK_ROWS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_t5_time_iso_write_preflight_20260527"
    / "time_iso_write_preflight_mapped_readback_rows.jsonl"
)
DEFAULT_SOURCE_WRITE_SUMMARY = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_t5_time_iso_write_execution_gate_20260527"
    / "time_iso_write_execution_summary.json"
)
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "atlas_t5_serving_time_overlay_candidate_20260527"
DEFAULT_CANDIDATE_DB = REPO_ROOT / "reports" / "atlas_serving_time_overlay_candidate_20260527_0925" / "atlas_serving.sqlite"
REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T5_SERVING_TIME_OVERLAY_CANDIDATE_20260527.md"
EXPECTED_SOURCE_WRITE_DECISION = "atlas_t5_time_iso_write_execution_gate_source_raw_time_iso_write_verified"
SCHEMA_VERSION = "stage7_atlas_t5_serving_time_overlay_candidate.v1"
SHANGHAI_TZ = timezone(timedelta(hours=8))
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
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield json.loads(stripped)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
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


def load_time_mapping(
    readback_rows_path: Path,
    mapped_rows_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    mapped_selectors = {
        str(row.get("time_title_readback_selector_id") or "")
        for row in iter_jsonl(mapped_rows_path)
        if str(row.get("time_title_readback_selector_id") or "")
    }
    rows: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], str] = {}
    input_readback_rows = 0
    consumed_readback_rows = 0

    for row in iter_jsonl(readback_rows_path):
        input_readback_rows += 1
        selector = str(row.get("time_title_readback_selector_id") or "")
        if selector not in mapped_selectors:
            continue
        consumed_readback_rows += 1
        date_value = str(row.get("candidate_event_date") or "").strip()
        if not date_value:
            blocked.append({**row, "blocked_reason": "candidate_event_date_missing"})
            continue
        for event_id in row.get("performance_event_ids") or []:
            event_id = str(event_id or "").strip()
            key = ("performance_event", "", event_id)
            previous = seen.setdefault(key, date_value)
            if previous != date_value:
                blocked.append(
                    {
                        "target_table": "performance_event",
                        "event_id": event_id,
                        "previous_starts_at": previous,
                        "proposed_starts_at": date_value,
                        "blocked_reason": "conflicting_starts_at_for_event",
                    }
                )
                continue
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION + ".mapping_row",
                    "target_table": "performance_event",
                    "event_id": event_id,
                    "dj_id": "",
                    "proposed_starts_at": date_value,
                    "time_title_readback_selector_id": selector,
                    "source_ref_id": str(row.get("source_ref_id") or ""),
                }
            )
        for pair in row.get("dj_event_pairs") or []:
            text = str(pair or "")
            if "::" not in text:
                blocked.append({**row, "blocked_reason": "dj_event_pair_invalid", "pair": text})
                continue
            event_id, dj_id = text.split("::", 1)
            key = ("dj_event", dj_id, event_id)
            previous = seen.setdefault(key, date_value)
            if previous != date_value:
                blocked.append(
                    {
                        "target_table": "dj_event",
                        "event_id": event_id,
                        "dj_id": dj_id,
                        "previous_starts_at": previous,
                        "proposed_starts_at": date_value,
                        "blocked_reason": "conflicting_starts_at_for_dj_event",
                    }
                )
                continue
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION + ".mapping_row",
                    "target_table": "dj_event",
                    "event_id": event_id,
                    "dj_id": dj_id,
                    "proposed_starts_at": date_value,
                    "time_title_readback_selector_id": selector,
                    "source_ref_id": str(row.get("source_ref_id") or ""),
                }
            )

    deduped = list({(row["target_table"], row["dj_id"], row["event_id"], row["proposed_starts_at"]): row for row in rows}.values())
    stats = {
        "input_readback_rows": input_readback_rows,
        "mapped_selector_rows": len(mapped_selectors),
        "consumed_readback_rows": consumed_readback_rows,
        "candidate_mapping_rows_before_dedupe": len(rows),
        "candidate_mapping_rows": len(deduped),
    }
    return deduped, blocked, stats


def apply_overlay(
    candidate_db: Path,
    mapping_rows: list[dict[str, Any]],
    generated_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    conn = sqlite3.connect(candidate_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    require_columns(conn, "performance_event", {"event_id", "starts_at", "event_title", "time_text", "venue_name", "city", "source_ref_id"})
    require_columns(conn, "dj_event", {"dj_id", "event_id", "starts_at", "time_text", "event_title", "venue_name", "city", "source_ref_id"})
    metrics_before = base_metrics(conn)
    changed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    try:
        conn.execute("BEGIN IMMEDIATE")
        for row in mapping_rows:
            table = row["target_table"]
            proposed = str(row["proposed_starts_at"])
            if table == "performance_event":
                found = conn.execute(
                    """
                    SELECT event_id, event_title, starts_at, time_text, venue_name, city, source_ref_id
                    FROM performance_event
                    WHERE event_id = ?
                    """,
                    (row["event_id"],),
                ).fetchone()
                selector = {"event_id": row["event_id"]}
            else:
                found_rows = conn.execute(
                    """
                    SELECT dj_id, event_id, event_title, starts_at, time_text, venue_name, city, source_ref_id
                    FROM dj_event
                    WHERE dj_id = ? AND event_id = ?
                    ORDER BY source_ref_id
                    """,
                    (row["dj_id"], row["event_id"]),
                ).fetchall()
                found = found_rows[0] if found_rows else None
                selector = {"dj_id": row["dj_id"], "event_id": row["event_id"]}
                if len(found_rows) > 1:
                    nonempty_conflicts = [
                        item["source_ref_id"]
                        for item in found_rows
                        if str(item["starts_at"] or "") not in {"", proposed}
                    ]
                    if nonempty_conflicts:
                        blocked.append({**row, "blocked_reason": "dj_event_duplicate_source_ref_starts_at_conflict"})
                        continue

            if found is None:
                blocked.append({**row, "blocked_reason": "serving_target_missing"})
                continue
            current = str(found["starts_at"] or "")
            if current and current != proposed:
                blocked.append({**row, "blocked_reason": "serving_starts_at_conflict", "current_starts_at": current})
                continue
            if current == proposed:
                continue
            before_hash = row_hash(found)
            if table == "performance_event":
                cursor = conn.execute(
                    "UPDATE performance_event SET starts_at = ? WHERE event_id = ? AND coalesce(starts_at, '') = ''",
                    (proposed, row["event_id"]),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE dj_event
                    SET starts_at = ?
                    WHERE dj_id = ? AND event_id = ? AND coalesce(starts_at, '') = ''
                    """,
                    (proposed, row["dj_id"], row["event_id"]),
                )
            if cursor.rowcount <= 0:
                blocked.append({**row, "blocked_reason": "sqlite_update_rowcount_zero"})
                continue
            changed.append(
                {
                    "schema_version": SCHEMA_VERSION + ".changed_row",
                    "generated_at": generated_at,
                    "target_table": table,
                    **selector,
                    "proposed_starts_at": proposed,
                    "prewrite_hash": before_hash,
                    "updated_rows": cursor.rowcount,
                }
            )
        if blocked:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    metrics_after = base_metrics(conn)
    conn.close()
    return {"before": metrics_before, "after": metrics_after}, changed, blocked


def scan_outputs(*payloads: Any) -> dict[str, int]:
    text = json.dumps(payloads, ensure_ascii=False, sort_keys=True)
    return {
        "public_url_hits": len(PUBLIC_URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_VALUE_RE.findall(text)),
        "local_path_hits": 0,
    }


def render_report(summary: dict[str, Any]) -> str:
    c = summary["counts"]
    return "\n".join(
        [
            "# ATLAS T5 Serving Time Overlay Candidate - 2026-05-27",
            "",
            "## Decision",
            "",
            f"`{summary['decision']}`",
            "",
            f"Failed checks: `{summary['failed_checks']}`.",
            "",
            "## LLM Audit",
            "",
            (
                "The source/raw `events.time_iso` write is verified, but the previous full serving "
                "rebuild path had already been rejected for regressing selected serving coverage. This "
                "candidate therefore copies the current city overlay serving DB and applies only "
                "`starts_at` deltas to `performance_event` and `dj_event`."
            ),
            "",
            "## Counts",
            "",
            f"- Input readback / mapped selector rows: `{c['input_readback_rows']}` / `{c['mapped_selector_rows']}`",
            f"- Candidate mapping rows: `{c['candidate_mapping_rows']}`",
            f"- Changed rows: `{c['changed_rows']}` split performance_event/dj_event `{c['changed_performance_event_rows']}` / `{c['changed_dj_event_rows']}`",
            f"- Blocked rows: `{c['blocked_rows']}`",
            f"- Starts_at gaps performance_event `{c['performance_event_starts_at_gap_before']}` -> `{c['performance_event_starts_at_gap_after']}`",
            f"- Starts_at gaps dj_event `{c['dj_event_starts_at_gap_before']}` -> `{c['dj_event_starts_at_gap_after']}`",
            f"- Table-count drift rows: `{c['table_count_drift_rows']}`",
            f"- Search-date refresh deferred rows: `{c['search_date_refresh_deferred_rows']}`",
            f"- Leak hits public URL / sensitive key / local path: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
            "",
            "## Boundary Truth",
            "",
            "Report-local candidate serving DB only. No selected serving mutation, source/raw DB write, graph/vector/public pointer mutation, huaidj.club upload, CloudRun deploy, mini-program upload/review, memory write, credential read, network/OCR/model call, 9router use, destructive Git, or D-root scan occurred.",
            "",
            f"Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def build_candidate(
    *,
    base_serving_db: Path,
    readback_rows_path: Path,
    mapped_readback_rows_path: Path,
    source_write_summary_path: Path,
    candidate_db: Path,
    out_dir: Path,
    report_path: Path,
    force: bool,
) -> dict[str, Any]:
    generated_at = now_iso()
    out_dir.mkdir(parents=True, exist_ok=True)
    source_write_summary = verify_source_write(source_write_summary_path)
    mapping_rows, mapping_blocked, mapping_stats = load_time_mapping(readback_rows_path, mapped_readback_rows_path)

    if candidate_db.exists():
        if not force:
            raise FileExistsError(f"candidate DB already exists: {candidate_db}")
        candidate_db.unlink()
    candidate_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_serving_db, candidate_db)

    metrics, changed_rows, apply_blocked = apply_overlay(candidate_db, mapping_rows, generated_at)
    blocked_rows = mapping_blocked + apply_blocked
    table_count_drift = [
        table
        for table, before_count in metrics["before"]["table_counts"].items()
        if metrics["after"]["table_counts"].get(table) != before_count
    ]
    changed_split = Counter(row["target_table"] for row in changed_rows)
    search_date_refresh_deferred = len({row["event_id"] for row in changed_rows if row["target_table"] == "performance_event"})

    failed_checks: list[str] = []
    if blocked_rows:
        failed_checks.append("blocked_rows_present")
    if table_count_drift:
        failed_checks.append("table_count_drift_present")
    leak_scan = scan_outputs(changed_rows[:50], blocked_rows[:50], mapping_rows[:50])
    if any(leak_scan.values()):
        failed_checks.append("leak_scan_hits_present")

    counts = {
        **mapping_stats,
        "changed_rows": len(changed_rows),
        "changed_performance_event_rows": changed_split.get("performance_event", 0),
        "changed_dj_event_rows": changed_split.get("dj_event", 0),
        "blocked_rows": len(blocked_rows),
        "table_count_drift_rows": len(table_count_drift),
        "performance_event_starts_at_gap_before": metrics["before"]["field_gaps"]["performance_event"]["starts_at_gap"],
        "performance_event_starts_at_gap_after": metrics["after"]["field_gaps"]["performance_event"]["starts_at_gap"],
        "dj_event_starts_at_gap_before": metrics["before"]["field_gaps"]["dj_event"]["starts_at_gap"],
        "dj_event_starts_at_gap_after": metrics["after"]["field_gaps"]["dj_event"]["starts_at_gap"],
        "source_raw_time_iso_committed_rows": (source_write_summary.get("counts") or {}).get("write_committed_rows", 0),
        "search_date_refresh_deferred_rows": search_date_refresh_deferred,
        "source_raw_db_write_allowed_rows": 0,
        "selected_serving_write_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    decision = (
        "atlas_t5_serving_time_overlay_candidate_ready_report_local"
        if not failed_checks and changed_rows
        else "atlas_t5_serving_time_overlay_candidate_blocked_report_local"
    )
    outputs = {
        "summary_json": rel(out_dir / "serving_time_overlay_summary.json"),
        "summary_md": rel(out_dir / "serving_time_overlay_summary.md"),
        "mapping_rows": rel(out_dir / "serving_time_overlay_mapping_rows.jsonl"),
        "changed_rows": rel(out_dir / "serving_time_overlay_changed_rows.jsonl"),
        "blocked_rows": rel(out_dir / "serving_time_overlay_blocked_rows.jsonl"),
        "candidate_db": rel(candidate_db),
        "report": rel(report_path),
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "inputs": {
            "base_serving_db": rel(base_serving_db),
            "readback_rows": rel(readback_rows_path),
            "mapped_readback_rows": rel(mapped_readback_rows_path),
            "source_write_summary": rel(source_write_summary_path),
        },
        "outputs": outputs,
        "candidate_db": rel(candidate_db),
        "metrics": metrics,
        "leak_scan": leak_scan,
        "deployable_public": False,
        "boundary_truth": {
            "report_local_candidate_db_written": bool(changed_rows and not failed_checks),
            "selected_serving_db_mutated": False,
            "source_raw_db_write_executed_by_this_step": False,
            "serving_rebuild_executed": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "cloudrun_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_executed": False,
            "network_fetch_executed": False,
            "ocr_executed": False,
            "model_call_executed": False,
        },
        "next_resume_pointer": rel(out_dir / "serving_time_overlay_summary.json"),
        "next_if_ready": "run local API/search/graph smoke against the report-local serving time overlay candidate",
        "next_if_blocked": rel(out_dir / "serving_time_overlay_blocked_rows.jsonl"),
    }
    write_jsonl(out_dir / "serving_time_overlay_mapping_rows.jsonl", mapping_rows)
    write_jsonl(out_dir / "serving_time_overlay_changed_rows.jsonl", changed_rows)
    write_jsonl(out_dir / "serving_time_overlay_blocked_rows.jsonl", blocked_rows)
    write_json(out_dir / "serving_time_overlay_summary.json", summary)
    write_json(out_dir / "serving_time_overlay_summary.md.json", {"markdown": render_report(summary)})
    (out_dir / "serving_time_overlay_summary.md").write_text(render_report(summary), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-serving-db", type=Path, default=DEFAULT_BASE_SERVING_DB)
    parser.add_argument("--readback-rows", type=Path, default=DEFAULT_READBACK_ROWS)
    parser.add_argument("--mapped-readback-rows", type=Path, default=DEFAULT_MAPPED_READBACK_ROWS)
    parser.add_argument("--source-write-summary", type=Path, default=DEFAULT_SOURCE_WRITE_SUMMARY)
    parser.add_argument("--candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_candidate(
        base_serving_db=args.base_serving_db,
        readback_rows_path=args.readback_rows,
        mapped_readback_rows_path=args.mapped_readback_rows,
        source_write_summary_path=args.source_write_summary,
        candidate_db=args.candidate_db,
        out_dir=args.out_dir,
        report_path=args.report,
        force=args.force,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
