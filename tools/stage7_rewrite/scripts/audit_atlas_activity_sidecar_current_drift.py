#!/usr/bin/env python3
"""Audit drift between the current weekly activity sidecar and Atlas candidates.

This is a T4 report-only check. It opens SQLite inputs read-only and writes only
local evidence files; it does not copy or mutate any Atlas database.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = SCRIPT_DIR.parent

DEFAULT_SIDECAR_DB = (
    REPO_ROOT / "reports" / "atlas_activity_source_sidecar_current_20260523_132244" / "atlas_activity_source_sidecar.sqlite"
)
DEFAULT_CANDIDATE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate"
    / "atlas.sqlite"
)
DEFAULT_SELECTED_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_field_repair_fullcomplete_strict_20260523-1658"
    / "atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_activity_sidecar_current_drift_t4_20260525"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T4_ACTIVITY_SIDECAR_CURRENT_DRIFT_AUDIT_20260525.md"

CORE_EVENT_FIELDS = ("title", "event_date_start", "event_date_end", "event_time_text", "venue_name", "address", "city_name")


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()} if row else {}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def sample_event_core_changes(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    where = " OR ".join(f"COALESCE(s.{field}, '') != COALESCE(c.{field}, '')" for field in CORE_EVENT_FIELDS)
    rows = conn.execute(
        f"""
        SELECT s.event_id,
               s.title AS sidecar_title, c.title AS candidate_title,
               s.event_date_start AS sidecar_event_date_start, c.event_date_start AS candidate_event_date_start,
               s.event_time_text AS sidecar_event_time_text, c.event_time_text AS candidate_event_time_text,
               s.venue_name AS sidecar_venue_name, c.venue_name AS candidate_venue_name,
               s.address AS sidecar_address, c.address AS candidate_address,
               s.city_name AS sidecar_city_name, c.city_name AS candidate_city_name
        FROM sidecar.activity_events s
        JOIN atlas_activity_events c ON c.event_id = s.event_id
        WHERE {where}
        ORDER BY s.event_id
        LIMIT ?
        """,
        (limit,),
    )
    return [row_dict(row) for row in rows]


def evidence_key_cte(prefix: str, event_table: str, ref_table: str) -> str:
    return f"""
    SELECT e.event_id || char(31) || r.field_path || char(31) ||
           COALESCE(r.field_value, '') || char(31) || COALESCE(r.quote, '') AS k,
           e.event_id, r.field_path, r.field_value, r.quote
    FROM {ref_table} r
    JOIN {event_table} e ON e.activity_event_id = r.activity_event_id
    """


def diff_count_query(left_cte: str, right_cte: str) -> str:
    return f"""
    WITH left_keys AS (
      SELECT k, COUNT(*) AS n FROM ({left_cte}) GROUP BY k
    ),
    right_keys AS (
      SELECT k, COUNT(*) AS n FROM ({right_cte}) GROUP BY k
    )
    SELECT COALESCE(SUM(CASE WHEN left_keys.n > COALESCE(right_keys.n, 0)
                             THEN left_keys.n - COALESCE(right_keys.n, 0)
                             ELSE 0 END), 0)
    FROM left_keys
    LEFT JOIN right_keys USING (k)
    """


def evidence_diff_samples(conn: sqlite3.Connection, side_only: bool, limit: int = 30) -> list[dict[str, Any]]:
    side_cte = evidence_key_cte("side", "sidecar.activity_events", "sidecar.evidence_refs")
    cand_cte = evidence_key_cte("cand", "atlas_activity_events", "atlas_activity_evidence_refs")
    left = side_cte if side_only else cand_cte
    right = cand_cte if side_only else side_cte
    rows = conn.execute(
        f"""
        WITH left_rows AS ({left}),
             right_rows AS ({right})
        SELECT left_rows.event_id, left_rows.field_path, left_rows.field_value, left_rows.quote
        FROM left_rows
        LEFT JOIN right_rows ON right_rows.k = left_rows.k
        WHERE right_rows.k IS NULL
        ORDER BY left_rows.event_id, left_rows.field_path, left_rows.field_value
        LIMIT ?
        """,
        (limit,),
    )
    return [row_dict(row) for row in rows]


def selected_serving_counts(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    conn = connect_readonly(path)
    try:
        return {
            "activity_event_detail": table_count(conn, "activity_event_detail"),
            "activity_evidence_ref": table_count(conn, "activity_evidence_ref"),
        }
    finally:
        conn.close()


def write_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Atlas T4 Activity Sidecar Current Drift Audit",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Decision",
        "",
        f"`{report['decision']}`",
        "",
        "This is report-only/read-only. It does not copy, merge, or mutate any Atlas DB.",
        "",
        "## Inputs",
        "",
        f"- current sidecar DB: `{report['sidecar_db']}`",
        f"- derived candidate DB: `{report['candidate_db']}`",
        f"- selected serving DB: `{report['selected_serving_db']}`",
        "",
        "## Drift",
        "",
        f"- sidecar events/evidence: `{report['sidecar_counts']['events']}` / `{report['sidecar_counts']['evidence_refs']}`",
        f"- candidate events/evidence: `{report['candidate_counts']['events']}` / `{report['candidate_counts']['evidence_refs']}`",
        f"- selected serving activity/evidence: `{report['selected_serving_counts']}`",
        f"- event ids missing sidecar -> candidate: `{report['event_id_drift']['sidecar_missing_in_candidate']}`",
        f"- event ids extra candidate -> sidecar: `{report['event_id_drift']['candidate_not_in_sidecar']}`",
        f"- core event field changes: `{report['event_core_changed_count']}`",
        f"- current sidecar evidence rows not represented in candidate by natural key: `{report['evidence_natural_key_drift']['sidecar_not_in_candidate']}`",
        f"- candidate evidence rows not represented in current sidecar by natural key: `{report['evidence_natural_key_drift']['candidate_not_in_sidecar']}`",
        "",
        "## Outputs",
        "",
        f"- summary JSON: `{report['outputs']['summary_json']}`",
        f"- sidecar-only evidence samples: `{report['outputs']['sidecar_only_samples_json']}`",
        f"- candidate-only evidence samples: `{report['outputs']['candidate_only_samples_json']}`",
        f"- core field change samples: `{report['outputs']['core_change_samples_json']}`",
        "",
        "## Next Resume Cursor",
        "",
        report["next_resume_cursor"],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def audit_drift(
    sidecar_db: Path,
    candidate_db: Path,
    selected_serving_db: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for path in (sidecar_db, candidate_db):
        if not path.exists():
            raise FileNotFoundError(path)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_readonly(candidate_db)
    try:
        conn.execute("ATTACH DATABASE ? AS sidecar", (str(sidecar_db.resolve()),))
        sidecar_counts = {
            "events": int(conn.execute("SELECT COUNT(*) FROM sidecar.activity_events").fetchone()[0]),
            "evidence_refs": int(conn.execute("SELECT COUNT(*) FROM sidecar.evidence_refs").fetchone()[0]),
            "prov_activities": int(conn.execute("SELECT COUNT(*) FROM sidecar.prov_activities").fetchone()[0]),
        }
        candidate_counts = {
            "events": table_count(conn, "atlas_activity_events"),
            "evidence_refs": table_count(conn, "atlas_activity_evidence_refs"),
            "prov_activities": table_count(conn, "atlas_activity_prov_activities"),
        }
        event_id_drift = {
            "sidecar_missing_in_candidate": int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM sidecar.activity_events s
                    LEFT JOIN atlas_activity_events c ON c.event_id = s.event_id
                    WHERE c.event_id IS NULL
                    """
                ).fetchone()[0]
            ),
            "candidate_not_in_sidecar": int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM atlas_activity_events c
                    LEFT JOIN sidecar.activity_events s ON s.event_id = c.event_id
                    WHERE s.event_id IS NULL
                    """
                ).fetchone()[0]
            ),
        }
        where = " OR ".join(f"COALESCE(s.{field}, '') != COALESCE(c.{field}, '')" for field in CORE_EVENT_FIELDS)
        event_core_changed_count = int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM sidecar.activity_events s
                JOIN atlas_activity_events c ON c.event_id = s.event_id
                WHERE {where}
                """
            ).fetchone()[0]
        )
        side_cte = evidence_key_cte("side", "sidecar.activity_events", "sidecar.evidence_refs")
        cand_cte = evidence_key_cte("cand", "atlas_activity_events", "atlas_activity_evidence_refs")
        evidence_drift = {
            "sidecar_not_in_candidate": int(conn.execute(diff_count_query(side_cte, cand_cte)).fetchone()[0]),
            "candidate_not_in_sidecar": int(conn.execute(diff_count_query(cand_cte, side_cte)).fetchone()[0]),
        }
        sidecar_only_samples = evidence_diff_samples(conn, side_only=True)
        candidate_only_samples = evidence_diff_samples(conn, side_only=False)
        core_change_samples = sample_event_core_changes(conn)
    finally:
        conn.close()

    drift_present = (
        event_id_drift["sidecar_missing_in_candidate"] != 0
        or event_id_drift["candidate_not_in_sidecar"] != 0
        or event_core_changed_count != 0
        or evidence_drift["sidecar_not_in_candidate"] != 0
        or evidence_drift["candidate_not_in_sidecar"] != 0
    )
    decision = (
        "atlas_activity_sidecar_current_drift_refresh_needed_report_only"
        if drift_present
        else "atlas_activity_sidecar_current_aligned_report_only"
    )
    outputs = {
        "summary_json": str(out_dir / "atlas_activity_sidecar_current_drift_summary.json"),
        "sidecar_only_samples_json": str(out_dir / "sidecar_only_evidence_samples.json"),
        "candidate_only_samples_json": str(out_dir / "candidate_only_evidence_samples.json"),
        "core_change_samples_json": str(out_dir / "core_event_change_samples.json"),
        "markdown_report": str(report_path),
    }
    report = {
        "schema_version": "atlas_activity_sidecar_current_drift_audit.v1",
        "generated_at": now_stamp(),
        "decision": decision,
        "sidecar_db": str(sidecar_db),
        "candidate_db": str(candidate_db),
        "selected_serving_db": str(selected_serving_db),
        "sidecar_counts": sidecar_counts,
        "candidate_counts": candidate_counts,
        "selected_serving_counts": selected_serving_counts(selected_serving_db),
        "event_id_drift": event_id_drift,
        "event_core_changed_count": event_core_changed_count,
        "event_core_change_samples": core_change_samples,
        "evidence_natural_key_drift": evidence_drift,
        "sidecar_only_evidence_samples": sidecar_only_samples,
        "candidate_only_evidence_samples": candidate_only_samples,
        "safety": {
            "report_only": True,
            "sidecar_sqlite_read_only": True,
            "candidate_sqlite_read_only": True,
            "selected_serving_sqlite_read_only": selected_serving_db.exists(),
            "source_db_mutated": False,
            "candidate_db_mutated": False,
            "serving_db_mutated": False,
            "network_call_executed": False,
            "llm_call_executed": False,
            "production_write_executed": False,
        },
        "outputs": outputs,
        "next_resume_cursor": (
            "T4 has evidence drift between the current weekly sidecar and the derived candidate/selected serving activity tables. "
            "Next safe step is an additive derived-candidate refresh from the current sidecar, or a small sidecar-to-serving consumption plan; do not mutate raw Atlas SQLite."
        ),
    }
    write_json(out_dir / "sidecar_only_evidence_samples.json", sidecar_only_samples)
    write_json(out_dir / "candidate_only_evidence_samples.json", candidate_only_samples)
    write_json(out_dir / "core_event_change_samples.json", core_change_samples)
    write_json(out_dir / "atlas_activity_sidecar_current_drift_summary.json", report)
    write_report(report_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar-db", type=Path, default=DEFAULT_SIDECAR_DB)
    parser.add_argument("--candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument("--selected-serving-db", type=Path, default=DEFAULT_SELECTED_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = audit_drift(
        args.sidecar_db,
        args.candidate_db,
        args.selected_serving_db,
        args.out_dir,
        args.report_path,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "report": report["outputs"]["markdown_report"],
                "summary_json": report["outputs"]["summary_json"],
                "event_core_changed_count": report["event_core_changed_count"],
                "evidence_natural_key_drift": report["evidence_natural_key_drift"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
