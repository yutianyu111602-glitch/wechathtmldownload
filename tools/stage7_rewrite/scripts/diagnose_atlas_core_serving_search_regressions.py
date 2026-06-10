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
    sha256_file,
    utc_now,
    write_json,
    write_jsonl,
)

DEFAULT_OLD_SERVING = default_reports_root() / "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018" / "atlas_serving.sqlite"
DEFAULT_NEW_SERVING = default_stage7_reports_root() / "atlas_core_candidate_20260604" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = default_stage7_reports_root() / "atlas_core_serving_search_diagnosis_20260605"
DEFAULT_QUERIES = ["OIL", "Loopy"]

VALUE_SHAPED_LEAK_RE = re.compile(
    r"(?i)(https?://|"
    r"(api[_-]?key|access[_-]?token|auth[_-]?token|cookie|password|passwd|secret)\s*[:=]\s*['\"]?[^'\"\s,;]{8,}|"
    r"bearer\s+[a-z0-9._~+/-]{12,}|"
    r"(^|[\\/])\.env(\b|[\\/]))"
)


def attach_pair(old_db: Path, new_db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("ATTACH DATABASE ? AS old", (f"file:{old_db.resolve().as_posix()}?mode=ro",))
    conn.execute("ATTACH DATABASE ? AS new", (f"file:{new_db.resolve().as_posix()}?mode=ro",))
    return conn


def fts_sql(conn: sqlite3.Connection, schema: str) -> str:
    row = conn.execute(f"SELECT sql FROM {schema}.sqlite_master WHERE name='search_document_fts'").fetchone()
    return str(row[0] if row else "")


def tokenizer_from_sql(sql: str) -> str:
    match = re.search(r"tokenize\s*=\s*'([^']+)'", sql, flags=re.I)
    return match.group(1) if match else ""


def fts_count(conn: sqlite3.Connection, schema: str, query: str) -> int:
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


def like_count(conn: sqlite3.Connection, schema: str, query: str) -> int:
    like = f"%{query}%"
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {schema}.search_document
            WHERE display_name LIKE ?
               OR normalized_name LIKE ?
               OR aliases_text LIKE ?
               OR city_text LIKE ?
               OR taxon_path LIKE ?
               OR search_text LIKE ?
            """,
            (like, like, like, like, like, like),
        ).fetchone()[0]
        or 0
    )


def fts_keys(conn: sqlite3.Connection, schema: str, query: str) -> set[tuple[str, str]]:
    return {
        (str(row["subject_id"]), str(row["subject_type"]))
        for row in conn.execute(
            f"""
            SELECT sd.subject_id, sd.subject_type
            FROM {schema}.search_document_fts f
            JOIN {schema}.search_document sd ON sd.doc_rowid = f.rowid
            WHERE search_document_fts MATCH ?
            """,
            (query,),
        )
    }


def like_keys(conn: sqlite3.Connection, schema: str, query: str) -> set[tuple[str, str]]:
    like = f"%{query}%"
    return {
        (str(row["subject_id"]), str(row["subject_type"]))
        for row in conn.execute(
            f"""
            SELECT subject_id, subject_type
            FROM {schema}.search_document
            WHERE display_name LIKE ?
               OR normalized_name LIKE ?
               OR aliases_text LIKE ?
               OR city_text LIKE ?
               OR taxon_path LIKE ?
               OR search_text LIKE ?
            """,
            (like, like, like, like, like, like),
        )
    }


def like_delta(conn: sqlite3.Connection, query: str) -> dict[str, int]:
    like = f"%{query}%"
    old_like = """
        SELECT subject_id, subject_type
        FROM old.search_document
        WHERE display_name LIKE ?
           OR normalized_name LIKE ?
           OR aliases_text LIKE ?
           OR city_text LIKE ?
           OR taxon_path LIKE ?
           OR search_text LIKE ?
    """
    new_like = old_like.replace("old.search_document", "new.search_document")
    params = (like, like, like, like, like, like) * 2
    old_only = int(conn.execute(f"SELECT COUNT(*) FROM ({old_like} EXCEPT {new_like})", params).fetchone()[0] or 0)
    new_only = int(conn.execute(f"SELECT COUNT(*) FROM ({new_like} EXCEPT {old_like})", params).fetchone()[0] or 0)
    return {"old_like_only_count": old_only, "new_like_only_count": new_only}


def fts_delta_counts(conn: sqlite3.Connection, query: str) -> dict[str, int]:
    row = conn.execute(
        """
        WITH old_hits AS (
          SELECT sd.subject_id, sd.subject_type
          FROM old.search_document_fts f
          JOIN old.search_document sd ON sd.doc_rowid = f.rowid
          WHERE search_document_fts MATCH ?
        ),
        new_hits AS (
          SELECT sd.subject_id, sd.subject_type
          FROM new.search_document_fts f
          JOIN new.search_document sd ON sd.doc_rowid = f.rowid
          WHERE search_document_fts MATCH ?
        )
        SELECT
          (SELECT COUNT(*) FROM (SELECT * FROM old_hits INTERSECT SELECT * FROM new_hits)) AS common_count,
          (SELECT COUNT(*) FROM (SELECT * FROM old_hits EXCEPT SELECT * FROM new_hits)) AS old_only_count,
          (SELECT COUNT(*) FROM (SELECT * FROM new_hits EXCEPT SELECT * FROM old_hits)) AS new_only_count
        """,
        (query, query),
    ).fetchone()
    return {
        "common_count": int(row["common_count"] or 0),
        "old_only_count": int(row["old_only_count"] or 0),
        "new_only_count": int(row["new_only_count"] or 0),
    }


def delta_samples(conn: sqlite3.Connection, query: str, direction: str, limit: int = 12) -> list[dict[str, Any]]:
    if direction not in {"old_only", "new_only"}:
        raise ValueError(f"unsupported direction: {direction}")
    left_schema = "old" if direction == "old_only" else "new"
    right_schema = "new" if direction == "old_only" else "old"
    rows = conn.execute(
        f"""
        WITH left_hits AS (
          SELECT sd.subject_id, sd.subject_type
          FROM {left_schema}.search_document_fts f
          JOIN {left_schema}.search_document sd ON sd.doc_rowid = f.rowid
          WHERE search_document_fts MATCH ?
        ),
        right_hits AS (
          SELECT sd.subject_id, sd.subject_type
          FROM {right_schema}.search_document_fts f
          JOIN {right_schema}.search_document sd ON sd.doc_rowid = f.rowid
          WHERE search_document_fts MATCH ?
        ),
        delta AS (
          SELECT * FROM left_hits
          EXCEPT
          SELECT * FROM right_hits
        )
        SELECT
          d.subject_id,
          d.subject_type,
          l.display_name AS left_display_name,
          r.display_name AS right_display_name,
          l.city_text AS left_city_text,
          r.city_text AS right_city_text,
          substr(l.search_text, 1, 180) AS left_search_text,
          substr(r.search_text, 1, 180) AS right_search_text
        FROM delta d
        JOIN {left_schema}.search_document l USING(subject_id, subject_type)
        LEFT JOIN {right_schema}.search_document r USING(subject_id, subject_type)
        ORDER BY d.subject_type, d.subject_id
        LIMIT ?
        """,
        (query, query, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def delta_samples_from_keys(
    conn: sqlite3.Connection,
    keys: set[tuple[str, str]],
    direction: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    if direction not in {"old_only", "new_only"}:
        raise ValueError(f"unsupported direction: {direction}")
    left_schema = "old" if direction == "old_only" else "new"
    right_schema = "new" if direction == "old_only" else "old"
    samples: list[dict[str, Any]] = []
    for subject_id, subject_type in sorted(keys)[:limit]:
        row = conn.execute(
            f"""
            SELECT
              l.subject_id,
              l.subject_type,
              l.display_name AS left_display_name,
              r.display_name AS right_display_name,
              l.city_text AS left_city_text,
              r.city_text AS right_city_text,
              substr(l.search_text, 1, 180) AS left_search_text,
              substr(r.search_text, 1, 180) AS right_search_text
            FROM {left_schema}.search_document l
            LEFT JOIN {right_schema}.search_document r
              ON r.subject_id = l.subject_id
             AND r.subject_type = l.subject_type
            WHERE l.subject_id = ?
              AND l.subject_type = ?
            LIMIT 1
            """,
            (subject_id, subject_type),
        ).fetchone()
        if row:
            samples.append(dict(row))
    return samples


def likely_cause(query: str, old_tokenizer: str, new_tokenizer: str, counts: dict[str, int], like_delta_counts: dict[str, int]) -> str:
    if (
        counts["old_fts_count"] == counts["new_fts_count"]
        and counts["old_like_count"] == counts["new_like_count"]
        and like_delta_counts["old_like_only_count"] == 0
        and like_delta_counts["new_like_only_count"] == 0
    ):
        return "no_search_regression_observed"
    if (
        old_tokenizer.startswith("trigram")
        and new_tokenizer.startswith("unicode61")
        and counts["old_like_count"] == counts["new_like_count"]
        and counts["old_fts_count"] == counts["old_like_count"]
        and counts["new_fts_count"] < counts["new_like_count"]
        and like_delta_counts["old_like_only_count"] == 0
        and like_delta_counts["new_like_only_count"] == 0
    ):
        return "tokenizer_changed_from_trigram_substring_to_unicode61_token_matching"
    if counts["old_like_count"] != counts["new_like_count"]:
        return "search_document_projection_content_diff"
    if old_tokenizer != new_tokenizer:
        return "fts_tokenizer_or_query_semantics_diff"
    return "needs_manual_review"


def leak_findings(payload: Any) -> list[dict[str, str]]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, str]] = []
    for match in VALUE_SHAPED_LEAK_RE.finditer(raw):
        findings.append({"kind": "raw_url_or_secret_like_value", "sample": match.group(0)[:80]})
        if len(findings) >= 20:
            break
    return findings


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas Core Serving Search Regression Diagnosis",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- source_hashes_unchanged: `{report['source_hashes_unchanged']}`",
        f"- leak_finding_count: `{report['leak_finding_count']}`",
        f"- old_tokenizer: `{report['fts_definitions']['old']['tokenizer']}`",
        f"- new_tokenizer: `{report['fts_definitions']['new']['tokenizer']}`",
        "",
        "## Queries",
        "",
    ]
    for row in report["query_diagnostics"]:
        lines.extend(
            [
                f"### {row['query']}",
                "",
                f"- old_fts_count: `{row['counts']['old_fts_count']}`",
                f"- new_fts_count: `{row['counts']['new_fts_count']}`",
                f"- old_like_count: `{row['counts']['old_like_count']}`",
                f"- new_like_count: `{row['counts']['new_like_count']}`",
                f"- old_only_count: `{row['fts_delta']['old_only_count']}`",
                f"- new_only_count: `{row['fts_delta']['new_only_count']}`",
                f"- likely_cause: `{row['likely_cause']}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Boundary",
            "",
            "- Read-only diagnosis.",
            "- No source, DB2, DB3, core, miniapp, graph, or production write.",
            "- This report explains shadow-read search differences; it is not a promotion gate pass.",
        ]
    )
    return "\n".join(lines) + "\n"


def diagnose(old_db: Path, new_db: Path, out_dir: Path, queries: list[str]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {"old_serving": sha256_file(old_db), "new_serving": sha256_file(new_db)}
    conn = attach_pair(old_db, new_db)
    try:
        old_sql = fts_sql(conn, "old")
        new_sql = fts_sql(conn, "new")
        old_tokenizer = tokenizer_from_sql(old_sql)
        new_tokenizer = tokenizer_from_sql(new_sql)
        diagnostics: list[dict[str, Any]] = []
        for query in queries:
            old_fts_keys = fts_keys(conn, "old", query)
            new_fts_keys = fts_keys(conn, "new", query)
            old_like_keys = like_keys(conn, "old", query)
            new_like_keys = like_keys(conn, "new", query)
            old_only_fts_keys = old_fts_keys - new_fts_keys
            new_only_fts_keys = new_fts_keys - old_fts_keys
            counts = {
                "old_fts_count": len(old_fts_keys),
                "new_fts_count": len(new_fts_keys),
                "old_like_count": len(old_like_keys),
                "new_like_count": len(new_like_keys),
            }
            like_delta_counts = {
                "old_like_only_count": len(old_like_keys - new_like_keys),
                "new_like_only_count": len(new_like_keys - old_like_keys),
            }
            fts_delta = {
                "common_count": len(old_fts_keys & new_fts_keys),
                "old_only_count": len(old_only_fts_keys),
                "new_only_count": len(new_only_fts_keys),
            }
            diagnostics.append(
                {
                    "query": query,
                    "counts": counts,
                    "like_delta": like_delta_counts,
                    "fts_delta": fts_delta,
                    "old_only_samples": delta_samples_from_keys(conn, old_only_fts_keys, "old_only"),
                    "new_only_samples": delta_samples_from_keys(conn, new_only_fts_keys, "new_only"),
                    "likely_cause": likely_cause(query, old_tokenizer, new_tokenizer, counts, like_delta_counts),
                }
            )
    finally:
        conn.close()
    after = {"old_serving": sha256_file(old_db), "new_serving": sha256_file(new_db)}

    report_without_scan = {
        "fts_definitions": {
            "old": {"tokenizer": old_tokenizer, "sql": old_sql},
            "new": {"tokenizer": new_tokenizer, "sql": new_sql},
        },
        "query_diagnostics": diagnostics,
    }
    findings = leak_findings(report_without_scan)
    blockers = []
    if before != after:
        blockers.append("source_hash_changed")
    if findings:
        blockers.append("leak_findings_present")
    report = {
        "schema_version": "atlas_core_serving_search_regression_diagnosis.v1",
        "generated_at": utc_now(),
        "decision": "atlas_core_serving_search_regression_diagnosis_ready_report_only" if not blockers else "atlas_core_serving_search_regression_diagnosis_blocked_report_only",
        "blockers": blockers,
        "source_hashes_before": before,
        "source_hashes_after": after,
        "source_hashes_unchanged": before == after,
        "fts_definitions": report_without_scan["fts_definitions"],
        "query_diagnostics": diagnostics,
        "summary": {
            "query_count": len(diagnostics),
            "tokenizer_changed": old_tokenizer != new_tokenizer,
            "queries_with_projection_like_diff": sum(1 for row in diagnostics if row["like_delta"]["old_like_only_count"] or row["like_delta"]["new_like_only_count"]),
            "queries_explained_by_tokenizer": sum(1 for row in diagnostics if row["likely_cause"] == "tokenizer_changed_from_trigram_substring_to_unicode61_token_matching"),
        },
        "safety": {
            "report_only": True,
            "old_serving_write_executed": False,
            "new_serving_write_executed": False,
            "production_write_executed": False,
            "source_hash_guard_enforced": True,
        },
        "outputs": {
            "report": str(out_dir / "atlas_core_serving_search_regression_diagnosis_report.json"),
            "query_diagnostics": str(out_dir / "atlas_core_serving_search_regression_diagnostics.jsonl"),
            "summary_md": str(out_dir / "atlas_core_serving_search_regression_diagnosis_summary.md"),
        },
        "leak_findings": findings,
        "leak_finding_count": len(findings),
    }
    write_json(out_dir / "atlas_core_serving_search_regression_diagnosis_report.json", report)
    write_jsonl(out_dir / "atlas_core_serving_search_regression_diagnostics.jsonl", diagnostics)
    (out_dir / "atlas_core_serving_search_regression_diagnosis_summary.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose serving FTS search regressions between old serving and Atlas Core exported serving.")
    parser.add_argument("--old-serving-db", type=Path, default=DEFAULT_OLD_SERVING)
    parser.add_argument("--new-serving-db", type=Path, default=DEFAULT_NEW_SERVING)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--query", action="append", dest="queries", help="Search query to diagnose. Defaults to OIL and Loopy.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    return diagnose(args.old_serving_db, args.new_serving_db, args.out_dir, args.queries or DEFAULT_QUERIES)


if __name__ == "__main__":
    print(json_dumps(main()))
