from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from atlas_core_common import (  # noqa: E402
    default_reports_root,
    default_stage7_reports_root,
    json_dumps,
    row_count,
    sha256_file,
    table_columns,
    table_exists,
    utc_now,
    write_json,
    write_jsonl,
)

DEFAULT_OLD_SERVING = default_reports_root() / "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018" / "atlas_serving.sqlite"
DEFAULT_NEW_SERVING = default_stage7_reports_root() / "atlas_core_candidate_20260604" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = default_stage7_reports_root() / "atlas_core_serving_shadow_read_compare_20260605"

EXPECTED_TABLES = {
    "canonical_subject",
    "dj_profile",
    "performance_event",
    "dj_event",
    "dj_relation_rollup",
    "dj_venue_rollup",
    "evidence_ref",
    "search_document",
    "search_document_fts",
    "graph_window_cache",
}

KEY_CHECKS = [
    {
        "name": "dj_profile",
        "table": "dj_profile",
        "columns": ["dj_id"],
    },
    {
        "name": "performance_event",
        "table": "performance_event",
        "columns": ["event_id"],
    },
    {
        "name": "dj_event",
        "table": "dj_event",
        "columns": ["dj_id", "event_id", "source_ref_id"],
    },
    {
        "name": "dj_relation_rollup",
        "table": "dj_relation_rollup",
        "columns": ["src_dj_id", "dst_dj_id"],
    },
    {
        "name": "evidence_ref",
        "table": "evidence_ref",
        "columns": ["source_ref_id"],
    },
    {
        "name": "search_document",
        "table": "search_document",
        "columns": ["subject_id", "subject_type"],
    },
]

SEARCH_QUERIES = ["DJ", "OIL", "深圳", "上海", "Loopy", "Gekko", "Xhin", "3fungi"]

SECRET_OR_PRIVATE_RE = re.compile(r"(?i)(https?://|[A-Z]:\\|\\\\wsl\.localhost\\|\.env|cookie|password|secret|token=|/mnt/[cd]/|/home/)")


def attach_pair(old_db: Path, new_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("ATTACH DATABASE ? AS old", (f"file:{old_db.resolve().as_posix()}?mode=ro",))
    conn.execute("ATTACH DATABASE ? AS new", (f"file:{new_db.resolve().as_posix()}?mode=ro",))
    return conn


def db_tables(conn: sqlite3.Connection, schema: str) -> set[str]:
    return {row[0] for row in conn.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type IN ('table','view')")}


def fts_tokenizer(conn: sqlite3.Connection, schema: str, table: str) -> str:
    row = conn.execute(f"SELECT sql FROM {schema}.sqlite_master WHERE name=?", (table,)).fetchone()
    if not row or not row[0]:
        return ""
    match = re.search(r"tokenize\s*=\s*'([^']+)'", str(row[0]), flags=re.I)
    return match.group(1) if match else "default"


def qualified_columns(columns: list[str]) -> str:
    return ", ".join(columns)


def key_expr(columns: list[str]) -> str:
    return " || char(31) || ".join(f"COALESCE({column}, '')" for column in columns)


def key_coverage(conn: sqlite3.Connection, check: dict[str, Any]) -> dict[str, Any]:
    table = check["table"]
    columns = check["columns"]
    select_cols = qualified_columns(columns)
    old_count = int(conn.execute(f"SELECT COUNT(*) FROM old.{table}").fetchone()[0] or 0)
    new_count = int(conn.execute(f"SELECT COUNT(*) FROM new.{table}").fetchone()[0] or 0)
    missing_count = int(
        conn.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT {select_cols} FROM old.{table}
              EXCEPT
              SELECT {select_cols} FROM new.{table}
            )
            """
        ).fetchone()[0]
        or 0
    )
    added_count = int(
        conn.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT {select_cols} FROM new.{table}
              EXCEPT
              SELECT {select_cols} FROM old.{table}
            )
            """
        ).fetchone()[0]
        or 0
    )
    sample_rows = [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT {select_cols} FROM (
              SELECT {select_cols} FROM old.{table}
              EXCEPT
              SELECT {select_cols} FROM new.{table}
            )
            LIMIT 20
            """
        )
    ]
    return {
        "table": table,
        "columns": columns,
        "old_count": old_count,
        "new_count": new_count,
        "missing_count": missing_count,
        "added_count": added_count,
        "coverage": (old_count - missing_count) / old_count if old_count else 1.0,
        "missing_sample": sample_rows,
    }


def fts_count(conn: sqlite3.Connection, schema: str, query: str) -> int:
    try:
        return int(
            conn.execute(
                f"""
                SELECT COUNT(*)
                FROM {schema}.search_document_fts
                WHERE search_document_fts MATCH ?
                """,
                (query,),
            ).fetchone()[0]
            or 0
        )
    except sqlite3.Error:
        return 0


def fts_top(conn: sqlite3.Connection, schema: str, query: str) -> list[dict[str, Any]]:
    try:
        return [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT sd.subject_id, sd.subject_type, sd.display_name, sd.city_text
                FROM {schema}.search_document_fts f
                JOIN {schema}.search_document sd ON sd.doc_rowid = f.rowid
                WHERE search_document_fts MATCH ?
                ORDER BY bm25(search_document_fts), sd.rank_score DESC, sd.doc_rowid
                LIMIT 10
                """,
                (query,),
            )
        ]
    except sqlite3.Error:
        return []


def search_compare(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = []
    for query in SEARCH_QUERIES:
        old_count = fts_count(conn, "old", query)
        new_count = fts_count(conn, "new", query)
        rows.append(
            {
                "query": query,
                "old_count": old_count,
                "new_count": new_count,
                "new_not_below_old": new_count >= old_count,
                "old_top": fts_top(conn, "old", query),
                "new_top": fts_top(conn, "new", query),
            }
        )
    return rows


def table_inventory(path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(path)
    try:
        return {
            table: {
                "row_count": row_count(conn, table),
                "columns": table_columns(conn, table),
            }
            for table in sorted(EXPECTED_TABLES)
            if table_exists(conn, table)
        }
    finally:
        conn.close()


def leak_findings(payload: Any) -> list[dict[str, str]]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings = []
    for match in SECRET_OR_PRIVATE_RE.finditer(raw):
        findings.append({"kind": "private_or_secret_like", "sample": match.group(0)[:40]})
        if len(findings) >= 20:
            break
    return findings


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Atlas Core Serving Shadow-Read Compare",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- missing_expected_tables: `{summary['missing_expected_table_count']}`",
        f"- key_coverage_regression_count: `{summary['key_coverage_regression_count']}`",
        f"- search_regression_count: `{summary['search_regression_count']}`",
        f"- leak_finding_count: `{report['leak_finding_count']}`",
        f"- source_hashes_unchanged: `{report['source_hashes_unchanged']}`",
        "",
        "## Key Coverage",
        "",
    ]
    for item in report["key_coverage"]:
        lines.append(
            f"- `{item['table']}`: old `{item['old_count']}`, new `{item['new_count']}`, missing `{item['missing_count']}`, added `{item['added_count']}`, coverage `{item['coverage']:.6f}`"
        )
    lines.extend(["", "## Search", ""])
    for item in report["search_compare"]:
        lines.append(f"- `{item['query']}`: old `{item['old_count']}`, new `{item['new_count']}`")
    lines.extend(["", "## FTS Tokenizers", ""])
    for key, value in report.get("fts_tokenizers", {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Read-only compare.",
            "- No source, DB2, DB3, core, miniapp, graph, or production write.",
            "- This is not a promotion gate pass; it is a shadow-read coverage report.",
        ]
    )
    return "\n".join(lines) + "\n"


def compare_serving(old_db: Path, new_db: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {"old_serving": sha256_file(old_db), "new_serving": sha256_file(new_db)}
    conn = attach_pair(old_db, new_db)
    try:
        old_tables = db_tables(conn, "old")
        new_tables = db_tables(conn, "new")
        missing_expected_old = sorted(EXPECTED_TABLES - old_tables)
        missing_expected_new = sorted(EXPECTED_TABLES - new_tables)
        key_rows = [key_coverage(conn, check) for check in KEY_CHECKS if check["table"] in old_tables and check["table"] in new_tables]
        search_rows = search_compare(conn) if "search_document_fts" in old_tables and "search_document_fts" in new_tables else []
        fts_tokenizers = {
            "old_search_document_fts": fts_tokenizer(conn, "old", "search_document_fts") if "search_document_fts" in old_tables else "",
            "new_search_document_fts": fts_tokenizer(conn, "new", "search_document_fts") if "search_document_fts" in new_tables else "",
            "new_search_document_fts_unicode61": fts_tokenizer(conn, "new", "search_document_fts_unicode61") if "search_document_fts_unicode61" in new_tables else "",
        }
    finally:
        conn.close()
    after = {"old_serving": sha256_file(old_db), "new_serving": sha256_file(new_db)}

    key_regressions = [row for row in key_rows if row["missing_count"] > 0]
    search_regressions = [row for row in search_rows if not row["new_not_below_old"]]
    report_without_scan = {
        "key_coverage": key_rows,
        "search_compare": search_rows,
        "missing_expected_old": missing_expected_old,
        "missing_expected_new": missing_expected_new,
    }
    findings = leak_findings(report_without_scan)
    blockers = []
    if before != after:
        blockers.append("source_hash_changed")
    if missing_expected_new:
        blockers.append("new_serving_missing_expected_tables")
    if key_regressions:
        blockers.append("key_coverage_regressions")
    if findings:
        blockers.append("leak_findings_present")

    report = {
        "schema_version": "atlas_core_serving_shadow_read_compare.v1",
        "generated_at": utc_now(),
        "decision": "atlas_core_serving_shadow_read_compare_ready_report_only" if not blockers else "atlas_core_serving_shadow_read_compare_blocked_report_only",
        "blockers": blockers,
        "inputs": {"old_serving": str(old_db), "new_serving": str(new_db)},
        "outputs": {
            "report": str(out_dir / "atlas_core_serving_shadow_read_compare_report.json"),
            "key_coverage": str(out_dir / "atlas_core_serving_shadow_read_key_coverage.jsonl"),
            "search_compare": str(out_dir / "atlas_core_serving_shadow_read_search_compare.jsonl"),
            "summary_md": str(out_dir / "atlas_core_serving_shadow_read_compare_summary.md"),
        },
        "source_hashes_before": before,
        "source_hashes_after": after,
        "source_hashes_unchanged": before == after,
        "old_inventory": table_inventory(old_db),
        "new_inventory": table_inventory(new_db),
        "missing_expected_old": missing_expected_old,
        "missing_expected_new": missing_expected_new,
        "fts_tokenizers": fts_tokenizers,
        "key_coverage": key_rows,
        "search_compare": search_rows,
        "summary": {
            "missing_expected_table_count": len(missing_expected_new),
            "key_coverage_regression_count": len(key_regressions),
            "search_regression_count": len(search_regressions),
            "old_table_count": len(old_tables),
            "new_table_count": len(new_tables),
        },
        "safety": {
            "report_only": True,
            "old_serving_write_executed": False,
            "new_serving_write_executed": False,
            "production_write_executed": False,
            "source_hash_guard_enforced": True,
        },
        "leak_findings": findings,
        "leak_finding_count": len(findings),
    }
    write_json(out_dir / "atlas_core_serving_shadow_read_compare_report.json", report)
    write_jsonl(out_dir / "atlas_core_serving_shadow_read_key_coverage.jsonl", key_rows)
    write_jsonl(out_dir / "atlas_core_serving_shadow_read_search_compare.jsonl", search_rows)
    (out_dir / "atlas_core_serving_shadow_read_compare_summary.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare old serving SQLite and Atlas Core exported serving SQLite in read-only shadow mode.")
    parser.add_argument("--old-serving-db", type=Path, default=DEFAULT_OLD_SERVING)
    parser.add_argument("--new-serving-db", type=Path, default=DEFAULT_NEW_SERVING)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    return compare_serving(args.old_serving_db, args.new_serving_db, args.out_dir)


if __name__ == "__main__":
    print(json_dumps(main()))
