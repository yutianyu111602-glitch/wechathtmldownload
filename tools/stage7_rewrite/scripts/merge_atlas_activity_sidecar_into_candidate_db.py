#!/usr/bin/env python3
"""Merge Atlas activity source sidecar tables into a derived candidate DB.

This script is additive. By default it copies the base candidate SQLite to a
new path, then imports the activity sidecar tables into the copy. It must not be
used to overwrite the raw Atlas source database.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RAW_URL_RE = re.compile(r"https?://|www\.|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|qpic\.cn|openid", re.I)
SCHEMA_VERSION = "atlas_activity_candidate_db_merge.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Atlas Activity Candidate DB Merge",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- base_db: `{report['base_db']}`",
        f"- out_db: `{report['out_db']}`",
        f"- activity_sidecar: `{report['activity_sidecar']}`",
        f"- copied_base_db: `{report['copied_base_db']}`",
        f"- elapsed_sec: `{report['elapsed_sec']}`",
        "",
        "## Counts",
        "",
        "| table | sidecar | candidate | match |",
        "| --- | ---: | ---: | --- |",
    ]
    for key in ["activity_events", "evidence_refs", "prov_activities"]:
        lines.append(
            f"| {key} | {report['sidecar_counts'].get(key)} | "
            f"{report['candidate_counts'].get(key)} | {report['count_matches'].get(key)} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- source_db_mutated: `{report['safety']['source_db_mutated']}`",
            f"- raw_url_leak_hits: `{len(report['safety']['raw_url_leak_hits'])}`",
            f"- raw_url_leak_scan_scope: `atlas_activity_* tables only`",
            "",
            "## Outputs",
            "",
            f"- summary_json: `{report['outputs']['summary_json']}`",
            f"- summary_md: `{report['outputs']['summary_md']}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def count_table(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def source_sidecar_counts(sidecar_db: Path) -> dict[str, int]:
    conn = sqlite3.connect(sidecar_db)
    try:
        return {
            "activity_events": count_table(conn, "activity_events"),
            "evidence_refs": count_table(conn, "evidence_refs"),
            "prov_activities": count_table(conn, "prov_activities"),
        }
    finally:
        conn.close()


def candidate_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "activity_events": count_table(conn, "atlas_activity_events"),
        "evidence_refs": count_table(conn, "atlas_activity_evidence_refs"),
        "prov_activities": count_table(conn, "atlas_activity_prov_activities"),
    }


def scan_activity_table_leaks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for table in ("atlas_activity_events", "atlas_activity_evidence_refs", "atlas_activity_prov_activities"):
        columns = [
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            if str(row[2]).upper() in {"TEXT", ""}
        ]
        for column in columns:
            rows = conn.execute(f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL").fetchall()
            for rowid, value in rows:
                if isinstance(value, str) and RAW_URL_RE.search(value):
                    hits.append({"table": table, "column": column, "rowid": rowid})
                    break
    return hits


def merge_sidecar_tables(conn: sqlite3.Connection, sidecar_db: Path, summary: dict[str, Any]) -> None:
    conn.execute("ATTACH DATABASE ? AS activity_sidecar", (str(sidecar_db.resolve()),))
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS atlas_activity_events;
            DROP TABLE IF EXISTS atlas_activity_evidence_refs;
            DROP TABLE IF EXISTS atlas_activity_prov_activities;

            CREATE TABLE atlas_activity_events AS
              SELECT * FROM activity_sidecar.activity_events;
            CREATE TABLE atlas_activity_evidence_refs AS
              SELECT * FROM activity_sidecar.evidence_refs;
            CREATE TABLE atlas_activity_prov_activities AS
              SELECT * FROM activity_sidecar.prov_activities;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_atlas_activity_events_id
              ON atlas_activity_events(activity_event_id);
            CREATE INDEX IF NOT EXISTS idx_atlas_activity_events_event
              ON atlas_activity_events(event_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_atlas_activity_evidence_refs_id
              ON atlas_activity_evidence_refs(evidence_ref_id);
            CREATE INDEX IF NOT EXISTS idx_atlas_activity_evidence_refs_event
              ON atlas_activity_evidence_refs(activity_event_id);
            CREATE INDEX IF NOT EXISTS idx_atlas_activity_evidence_refs_field
              ON atlas_activity_evidence_refs(field_path);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("atlas_activity_sidecar_summary", json.dumps(summary, ensure_ascii=False, sort_keys=True)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            ("atlas_activity_sidecar_schema_version", SCHEMA_VERSION),
        )
        conn.commit()
    finally:
        conn.execute("DETACH DATABASE activity_sidecar")


def build_activity_candidate_db(
    base_db: Path,
    activity_sidecar_db: Path,
    out_db: Path,
    *,
    sidecar_summary_path: Path | None = None,
    report_dir: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    started = time.time()
    if not base_db.exists():
        raise FileNotFoundError(base_db)
    if not activity_sidecar_db.exists():
        raise FileNotFoundError(activity_sidecar_db)
    if out_db.resolve() == base_db.resolve():
        raise ValueError("out_db must be a derived candidate path, not the base_db")
    if out_db.exists() and not overwrite:
        raise FileExistsError(out_db)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(base_db, out_db)

    sidecar_summary = read_json(sidecar_summary_path, {}) if sidecar_summary_path else {}
    sidecar_counts = source_sidecar_counts(activity_sidecar_db)
    conn = sqlite3.connect(out_db)
    try:
        merge_sidecar_tables(conn, activity_sidecar_db, sidecar_summary)
        merged_counts = candidate_counts(conn)
        leak_hits = scan_activity_table_leaks(conn)
        article_count = count_table(conn, "articles")
        entity_count = count_table(conn, "entities")
        event_count = count_table(conn, "events")
    finally:
        conn.close()

    count_matches = {key: sidecar_counts[key] == merged_counts[key] for key in sidecar_counts}
    generated_at = utc_now()
    report_root = report_dir or out_db.parent
    summary_json = report_root / "activity_candidate_db_merge_summary.json"
    summary_md = report_root / "activity_candidate_db_merge_summary.md"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": "activity_sidecar_merged_into_derived_candidate_db"
        if all(count_matches.values()) and not leak_hits
        else "activity_sidecar_merge_needs_review",
        "base_db": str(base_db),
        "activity_sidecar": str(activity_sidecar_db),
        "out_db": str(out_db),
        "copied_base_db": True,
        "elapsed_sec": round(time.time() - started, 3),
        "base_counts": {
            "articles": article_count,
            "entities": entity_count,
            "events": event_count,
        },
        "sidecar_counts": sidecar_counts,
        "candidate_counts": merged_counts,
        "count_matches": count_matches,
        "safety": {
            "source_db_mutated": False,
            "raw_url_leak_hits": leak_hits,
        },
        "outputs": {
            "summary_json": str(summary_json),
            "summary_md": str(summary_md),
        },
    }
    write_json(summary_json, report)
    write_markdown(summary_md, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-db", type=Path, required=True)
    parser.add_argument("--activity-sidecar-db", type=Path, required=True)
    parser.add_argument("--out-db", type=Path, required=True)
    parser.add_argument("--sidecar-summary", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    report = build_activity_candidate_db(
        args.base_db,
        args.activity_sidecar_db,
        args.out_db,
        sidecar_summary_path=args.sidecar_summary,
        report_dir=args.report_dir,
        overwrite=args.overwrite,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["decision"] == "activity_sidecar_merged_into_derived_candidate_db" else 1


if __name__ == "__main__":
    raise SystemExit(main())
