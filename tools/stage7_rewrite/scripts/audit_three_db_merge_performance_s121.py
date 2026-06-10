#!/usr/bin/env python3
"""Read-only S121 audit for DB1/DB2/DB3 merge and performance risks."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "three_db_merge_performance_s121.v1"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "three_db_merge_performance_s121_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_THREE_DB_MERGE_PERFORMANCE_S121_20260601.md"

DEFAULT_DB_PATHS = {
    "DB1_source_raw_atlas": REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite",
    "DB2_serving_read_model": REPO_ROOT
    / "reports"
    / "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018"
    / "atlas_serving.sqlite",
    "DB3_miniapp_sqlite": REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite",
    "S119_external_link_sidecar": STAGE7_ROOT
    / "reports"
    / "external_link_db2_sidecar_contract_s119_20260601"
    / "external_link_db2_sidecar.sqlite",
}
DEFAULT_S120_ITEMS = STAGE7_ROOT / "reports" / "miniprogram_external_link_contract_s120_20260601" / "miniprogram_external_link_items.json"

TABLES = {
    "DB1_source_raw_atlas": ["articles", "atlas_activity_events", "atlas_activity_evidence_refs", "entities"],
    "DB2_serving_read_model": [
        "canonical_subject",
        "performance_event",
        "dj_profile",
        "dj_event",
        "dj_relation_rollup",
        "dj_venue_rollup",
        "evidence_ref",
        "search_document",
    ],
    "DB3_miniapp_sqlite": ["subject", "dj_profile", "dj_event", "dj_collaborator", "dj_venue", "source_ref"],
    "S119_external_link_sidecar": ["external_link_candidates", "promotion_gates"],
}
ATTACH_SCHEMA = {
    "DB1_source_raw_atlas": "db1",
    "DB2_serving_read_model": "db2",
    "DB3_miniapp_sqlite": "db3",
    "S119_external_link_sidecar": "s119",
}
JOIN_CHECKS = [
    {
        "id": "dj_profile_db2_to_db3",
        "source": ("db2", "dj_profile", "dj_id"),
        "target": ("db3", "dj_profile", "dj_id"),
        "meaning": "DB2 DJ profile ids available in DB3 miniapp profile table",
    },
    {
        "id": "source_ref_db2_to_db3",
        "source": ("db2", "evidence_ref", "source_ref_id"),
        "target": ("db3", "source_ref", "source_ref_id"),
        "meaning": "DB2 evidence source refs available in DB3 miniapp source_ref table",
    },
    {
        "id": "performance_event_db2_to_db3_dj_event",
        "source": ("db2", "performance_event", "event_id"),
        "target": ("db3", "dj_event", "event_id"),
        "meaning": "DB2 event ids represented in DB3 dj_event projection",
    },
    {
        "id": "dj_venue_rollup_db2_to_db3",
        "source": ("db2", "dj_venue_rollup", ["dj_id", "venue_id"]),
        "target": ("db3", "dj_venue", ["dj_id", "venue_id"]),
        "meaning": "DB2 DJ-venue rollup pairs available in DB3 miniapp venue projection",
    },
    {
        "id": "dj_relation_rollup_db2_to_db3",
        "source": ("db2", "dj_relation_rollup", ["src_dj_id", "dst_dj_id"]),
        "target": ("db3", "dj_collaborator", ["src_dj_id", "dst_dj_id"]),
        "meaning": "DB2 DJ relation pairs available in DB3 collaborator projection",
    },
]
INDEX_EXPECTATIONS = {
    ("db2", "dj_profile"): [["dj_id"], ["normalized_name"]],
    ("db2", "dj_event"): [["dj_id", "event_id"], ["event_id"], ["source_ref_id"]],
    ("db2", "performance_event"): [["event_id"], ["venue_id"], ["starts_at"]],
    ("db2", "dj_relation_rollup"): [["src_dj_id", "dst_dj_id"], ["src_dj_id"], ["dst_dj_id"]],
    ("db2", "dj_venue_rollup"): [["dj_id", "venue_id"], ["venue_id"]],
    ("db2", "evidence_ref"): [["source_ref_id"]],
    ("db3", "subject"): [["subject_id"], ["normalized_name"], ["subject_type"]],
    ("db3", "dj_profile"): [["dj_id"], ["normalized_name"]],
    ("db3", "dj_event"): [["dj_id", "event_id"], ["event_id"], ["source_ref_id"]],
    ("db3", "dj_collaborator"): [["src_dj_id", "dst_dj_id"], ["src_dj_id"]],
    ("db3", "dj_venue"): [["dj_id", "venue_id"], ["dj_id"]],
    ("db3", "source_ref"): [["source_ref_id"], ["source_account"]],
    ("s119", "external_link_candidates"): [["sidecar_id"], ["entity_search_id"], ["platform"], ["promotion_status"]],
}
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def sqlite_uri(path: Path) -> str:
    return f"file:{path.resolve().as_posix()}?mode=ro"


def quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def attach_readonly(db_paths: dict[str, Path]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", uri=True)
    conn.row_factory = sqlite3.Row
    for layer, path in db_paths.items():
        schema = ATTACH_SCHEMA[layer]
        conn.execute(f"ATTACH DATABASE ? AS {quote_ident(schema)}", (sqlite_uri(path),))
    return conn


def table_exists(conn: sqlite3.Connection, schema: str, table: str) -> bool:
    row = conn.execute(
        f"SELECT name FROM {quote_ident(schema)}.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, schema: str, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(f"PRAGMA {quote_ident(schema)}.table_info({quote_ident(table)})").fetchall()
    return [
        {"name": row[1], "type": row[2], "notnull": bool(row[3]), "default": row[4], "pk": int(row[5])}
        for row in rows
    ]


def table_indexes(conn: sqlite3.Connection, schema: str, table: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in conn.execute(f"PRAGMA {quote_ident(schema)}.index_list({quote_ident(table)})").fetchall():
        index_name = row[1]
        cols = [info[2] for info in conn.execute(f"PRAGMA {quote_ident(schema)}.index_info({quote_ident(index_name)})").fetchall()]
        out.append({"name": index_name, "unique": bool(row[2]), "origin": row[3], "columns": cols})
    return out


def table_summary(conn: sqlite3.Connection, schema: str, table: str) -> dict[str, Any]:
    if not table_exists(conn, schema, table):
        return {"exists": False, "row_count": 0, "columns": [], "indexes": []}
    row_count = conn.execute(f"SELECT COUNT(*) FROM {quote_ident(schema)}.{quote_ident(table)}").fetchone()[0]
    return {
        "exists": True,
        "row_count": int(row_count),
        "columns": table_columns(conn, schema, table),
        "indexes": table_indexes(conn, schema, table),
    }


def index_covers(index_columns: list[str], expected: list[str]) -> bool:
    return index_columns[: len(expected)] == expected


def has_covering_index(summary: dict[str, Any], expected: list[str]) -> bool:
    pk_columns = [col["name"] for col in sorted(summary.get("columns", []), key=lambda col: col["pk"]) if col.get("pk")]
    if pk_columns and index_covers(pk_columns, expected):
        return True
    for index in summary.get("indexes", []):
        if index_covers(index.get("columns", []), expected):
            return True
    return False


def audit_indexes(schema_summaries: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for (schema, table), expectations in INDEX_EXPECTATIONS.items():
        summary = schema_summaries.get(schema, {}).get(table, {"exists": False})
        for expected in expectations:
            rows.append(
                {
                    "schema": schema,
                    "table": table,
                    "expected_prefix": expected,
                    "passed": bool(summary.get("exists")) and has_covering_index(summary, expected),
                }
            )
    return rows


def distinct_count(conn: sqlite3.Connection, schema: str, table: str, columns: list[str]) -> int:
    col_sql = ", ".join(quote_ident(col) for col in columns)
    row = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT {col_sql} FROM {quote_ident(schema)}.{quote_ident(table)} WHERE "
        + " AND ".join(f"{quote_ident(col)} IS NOT NULL AND {quote_ident(col)} != ''" for col in columns)
        + ")"
    ).fetchone()
    return int(row[0] or 0)


def join_coverage(conn: sqlite3.Connection, check: dict[str, Any]) -> dict[str, Any]:
    src_schema, src_table, src_cols_raw = check["source"]
    dst_schema, dst_table, dst_cols_raw = check["target"]
    src_cols = src_cols_raw if isinstance(src_cols_raw, list) else [src_cols_raw]
    dst_cols = dst_cols_raw if isinstance(dst_cols_raw, list) else [dst_cols_raw]
    src_select = ", ".join(quote_ident(col) for col in src_cols)
    dst_select = ", ".join(quote_ident(col) for col in dst_cols)
    src_not_null = " AND ".join(f"{quote_ident(col)} IS NOT NULL AND {quote_ident(col)} != ''" for col in src_cols)
    dst_not_null = " AND ".join(f"{quote_ident(col)} IS NOT NULL AND {quote_ident(col)} != ''" for col in dst_cols)
    join_expr = " AND ".join(f"src.{quote_ident(src)} = dst.{quote_ident(dst)}" for src, dst in zip(src_cols, dst_cols))
    dst_null = f"dst.{quote_ident(dst_cols[0])} IS NULL"
    src_count = distinct_count(conn, src_schema, src_table, src_cols)
    dst_count = distinct_count(conn, dst_schema, dst_table, dst_cols)
    missing_sql = f"""
        SELECT COUNT(*) FROM (
          SELECT DISTINCT {src_select}
          FROM {quote_ident(src_schema)}.{quote_ident(src_table)}
          WHERE {src_not_null}
        ) AS src
        LEFT JOIN (
          SELECT DISTINCT {dst_select}
          FROM {quote_ident(dst_schema)}.{quote_ident(dst_table)}
          WHERE {dst_not_null}
        ) AS dst ON {join_expr}
        WHERE {dst_null}
    """
    started = time.perf_counter()
    missing = int(conn.execute(missing_sql).fetchone()[0] or 0)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    covered = max(src_count - missing, 0)
    coverage_ratio = round(covered / src_count, 6) if src_count else 1.0
    return {
        "id": check["id"],
        "meaning": check["meaning"],
        "source": {"schema": src_schema, "table": src_table, "columns": src_cols, "distinct_count": src_count},
        "target": {"schema": dst_schema, "table": dst_table, "columns": dst_cols, "distinct_count": dst_count},
        "missing_in_target": missing,
        "covered_in_target": covered,
        "coverage_ratio": coverage_ratio,
        "elapsed_ms": elapsed_ms,
    }


def explain_query_plan(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[str]:
    return [str(row[3]) for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()]


def timed_query(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    started = time.perf_counter()
    rows = conn.execute(sql, params).fetchmany(20)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {"elapsed_ms": elapsed_ms, "row_count_sampled": len(rows), "plan": explain_query_plan(conn, sql, params)}


def first_value(conn: sqlite3.Connection, schema: str, table: str, column: str) -> str:
    row = conn.execute(
        f"SELECT {quote_ident(column)} FROM {quote_ident(schema)}.{quote_ident(table)} WHERE {quote_ident(column)} IS NOT NULL AND {quote_ident(column)} != '' LIMIT 1"
    ).fetchone()
    return str(row[0]) if row else ""


def performance_smokes(conn: sqlite3.Connection) -> dict[str, Any]:
    dj_id = first_value(conn, "db3", "dj_profile", "dj_id")
    event_id = first_value(conn, "db3", "dj_event", "event_id")
    source_ref_id = first_value(conn, "db3", "source_ref", "source_ref_id")
    smokes: dict[str, Any] = {}
    if dj_id:
        smokes["db3_profile_by_dj_id"] = timed_query(conn, 'SELECT * FROM db3."dj_profile" WHERE "dj_id" = ?', (dj_id,))
        smokes["db3_dj_events_by_dj_id"] = timed_query(conn, 'SELECT * FROM db3."dj_event" WHERE "dj_id" = ? LIMIT 20', (dj_id,))
        smokes["db2_profile_by_dj_id"] = timed_query(conn, 'SELECT * FROM db2."dj_profile" WHERE "dj_id" = ?', (dj_id,))
    if event_id:
        smokes["db3_event_by_event_id"] = timed_query(conn, 'SELECT * FROM db3."dj_event" WHERE "event_id" = ? LIMIT 20', (event_id,))
        smokes["db2_event_by_event_id"] = timed_query(conn, 'SELECT * FROM db2."performance_event" WHERE "event_id" = ?', (event_id,))
    if source_ref_id:
        smokes["db3_source_ref_by_id"] = timed_query(conn, 'SELECT * FROM db3."source_ref" WHERE "source_ref_id" = ?', (source_ref_id,))
        smokes["db2_evidence_ref_by_id"] = timed_query(conn, 'SELECT * FROM db2."evidence_ref" WHERE "source_ref_id" = ?', (source_ref_id,))
    return smokes


def sidecar_mapping(conn: sqlite3.Connection, s120_items_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if table_exists(conn, "s119", "external_link_candidates"):
        rows = conn.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN confidence_band='high' AND block_reasons_json='[]' THEN 1 ELSE 0 END) AS high_safe,
              SUM(CASE WHEN p.dj_id IS NOT NULL THEN 1 ELSE 0 END) AS high_safe_db3_profile_match
            FROM s119.external_link_candidates AS l
            LEFT JOIN db3.dj_profile AS p ON p.dj_id = l.entity_search_id
            WHERE l.confidence_band='high' AND l.block_reasons_json='[]'
            """
        ).fetchone()
        out["s119_high_safe_to_db3_profile"] = {
            "total_candidates": int(rows["total"] or 0),
            "high_safe": int(rows["high_safe"] or 0),
            "db3_profile_matches": int(rows["high_safe_db3_profile_match"] or 0),
        }
    if s120_items_path.exists():
        items = json.loads(s120_items_path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            items = []
        ids = sorted({str(item.get("entity_search_id") or "") for item in items if isinstance(item, dict) and item.get("entity_search_id")})
        matches = 0
        if ids:
            placeholders = ", ".join("?" for _ in ids)
            matches = int(
                conn.execute(f'SELECT COUNT(*) FROM db3."dj_profile" WHERE "dj_id" IN ({placeholders})', tuple(ids)).fetchone()[0]
                or 0
            )
        out["s120_items_to_db3_profile"] = {
            "item_count": len(items),
            "entity_id_count": len(ids),
            "db3_profile_matches": matches,
            "by_category": dict(Counter(str(item.get("public_category") or "unknown") for item in items if isinstance(item, dict))),
        }
    else:
        out["s120_items_to_db3_profile"] = {"item_count": 0, "entity_id_count": 0, "db3_profile_matches": 0, "missing_input": True}
    return out


def collect_findings(
    schema_summaries: dict[str, dict[str, dict[str, Any]]],
    index_audit: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    sidecar: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for schema, table_map in schema_summaries.items():
        for table, summary in table_map.items():
            if not summary.get("exists"):
                findings.append({"severity": "high", "check": f"{schema}.{table}.missing", "message": "required table is missing"})
    for row in index_audit:
        if not row["passed"]:
            findings.append(
                {
                    "severity": "warning",
                    "check": f"{row['schema']}.{row['table']}.index.{'.'.join(row['expected_prefix'])}",
                    "message": "expected hot-path index prefix is absent or not visible",
                }
            )
    for row in coverage:
        if row["source"]["distinct_count"] and row["coverage_ratio"] < 0.95:
            findings.append(
                {
                    "severity": "warning",
                    "check": f"{row['id']}.coverage",
                    "message": f"coverage ratio {row['coverage_ratio']} with missing {row['missing_in_target']}",
                }
            )
    s120 = sidecar.get("s120_items_to_db3_profile") or {}
    if s120.get("item_count") and s120.get("db3_profile_matches", 0) == 0:
        findings.append(
            {
                "severity": "warning",
                "check": "s120_external_link_entity_ids_not_db3_dj_ids",
                "message": "S120 entity_search_id values do not directly join DB3 dj_profile.dj_id; a mapping table/gate is needed before projection.",
            }
        )
    return findings


def secret_findings(report: dict[str, Any]) -> list[dict[str, str]]:
    text = json.dumps(report, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def markdown_table(rows: list[dict[str, Any]], columns: list[str], limit: int = 24) -> list[str]:
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in columns) + " |")
    if len(rows) > limit:
        out.append("| " + " | ".join([f"{len(rows) - limit} more rows omitted"] + ["" for _ in columns[1:]]) + " |")
    return out


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weekly Three-DB Merge / Performance Audit S121",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Blocking findings: `{report['blocking_finding_count']}`",
        f"- Risk findings: `{report['risk_finding_count']}`",
        f"- Secret-like findings: `{report['secret_like_finding_count']}`",
        "",
        "## Inputs",
        "",
    ]
    for key, value in report["inputs"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Table Counts", ""])
    table_rows = []
    for schema, tables in report["schemas"].items():
        for table, summary in tables.items():
            table_rows.append(
                {
                    "schema": schema,
                    "table": table,
                    "exists": summary["exists"],
                    "row_count": summary["row_count"],
                    "index_count": len(summary.get("indexes", [])),
                }
            )
    lines.extend(markdown_table(table_rows, ["schema", "table", "exists", "row_count", "index_count"]))
    lines.extend(["", "## Join Coverage", ""])
    lines.extend(markdown_table(report["join_coverage"], ["id", "missing_in_target", "covered_in_target", "coverage_ratio", "elapsed_ms"]))
    lines.extend(["", "## External Link Sidecar Mapping", ""])
    for key, value in report["sidecar_mapping"].items():
        lines.append(f"- `{key}`: `{json.dumps(value, ensure_ascii=False)}`")
    lines.extend(["", "## Hot Query Smokes", ""])
    for key, value in report["performance_smokes"].items():
        lines.append(f"- `{key}` elapsed_ms `{value['elapsed_ms']}` plan `{'; '.join(value['plan'])}`")
    if report["findings"]:
        lines.extend(["", "## Findings", ""])
        lines.extend(markdown_table(report["findings"], ["severity", "check", "message"], 80))
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- Read-only audit only: SQLite databases are attached with `mode=ro`.",
            "- No DB1/DB2/DB3 mutation, DB2 projection, mini-program upload/release, external network fetch, or cookie/token value read.",
            "- S122 should route poster/lineup extraction; S124/S125 should only proceed after entity-id mapping is explicit.",
            "",
        ]
    )
    return "\n".join(lines)


def build_audit(
    db_paths: dict[str, Path],
    s120_items_path: Path,
    out_dir: Path,
    scorecard: Path,
) -> dict[str, Any]:
    missing_paths = {key: path for key, path in db_paths.items() if not path.exists()}
    conn: sqlite3.Connection | None = None
    try:
        conn = attach_readonly(db_paths)
        schema_summaries: dict[str, dict[str, dict[str, Any]]] = {}
        for layer, schema in ATTACH_SCHEMA.items():
            schema_summaries[schema] = {table: table_summary(conn, schema, table) for table in TABLES[layer]}
        index_audit = audit_indexes(schema_summaries)
        coverage = [join_coverage(conn, check) for check in JOIN_CHECKS]
        sidecar = sidecar_mapping(conn, s120_items_path)
        smokes = performance_smokes(conn)
        findings = collect_findings(schema_summaries, index_audit, coverage, sidecar)
    except Exception as exc:  # noqa: BLE001
        schema_summaries = {}
        index_audit = []
        coverage = []
        sidecar = {}
        smokes = {}
        findings = [{"severity": "high", "check": "audit_execution_failed", "message": str(exc)}]
    finally:
        if conn is not None:
            conn.close()

    for key, path in missing_paths.items():
        findings.append({"severity": "high", "check": f"{key}.missing_path", "message": rel_path(path)})

    blocking = [finding for finding in findings if finding["severity"] == "high"]
    risks = [finding for finding in findings if finding["severity"] != "high"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "three_db_merge_performance_audit_ready_read_only" if not blocking else "three_db_merge_performance_audit_blocked",
        "inputs": {key: rel_path(path) for key, path in db_paths.items()} | {"S120_items": rel_path(s120_items_path)},
        "schemas": schema_summaries,
        "index_audit": index_audit,
        "join_coverage": coverage,
        "sidecar_mapping": sidecar,
        "performance_smokes": smokes,
        "findings": findings,
        "blocking_finding_count": len(blocking),
        "risk_finding_count": len(risks),
        "boundaries": {
            "read_only": True,
            "sqlite_mode": "mode=ro",
            "database_mutation": False,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection_allowed": False,
            "miniapp_release": False,
            "network_fetch": False,
            "cookie_values_read": False,
            "token_values_read": False,
        },
        "next_story": "S122",
    }
    secret_like = secret_findings(report)
    report["secret_like_findings"] = secret_like
    report["secret_like_finding_count"] = len(secret_like)
    if secret_like:
        report["decision"] = "three_db_merge_performance_audit_blocked_secret_like_output"

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "three_db_merge_performance_audit.json"
    markdown_path = out_dir / "three_db_merge_performance_audit.md"
    report["outputs"] = {"report": rel_path(report_path), "markdown": rel_path(markdown_path), "scorecard": rel_path(scorecard)}
    atomic_write_json(report_path, report)
    markdown = render_markdown(report)
    atomic_write_text(markdown_path, markdown)
    atomic_write_text(scorecard, markdown)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--s120-items", type=Path, default=DEFAULT_S120_ITEMS)
    parser.add_argument("--db1", type=Path, default=DEFAULT_DB_PATHS["DB1_source_raw_atlas"])
    parser.add_argument("--db2", type=Path, default=DEFAULT_DB_PATHS["DB2_serving_read_model"])
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB_PATHS["DB3_miniapp_sqlite"])
    parser.add_argument("--s119-sidecar", type=Path, default=DEFAULT_DB_PATHS["S119_external_link_sidecar"])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_paths = {
        "DB1_source_raw_atlas": args.db1,
        "DB2_serving_read_model": args.db2,
        "DB3_miniapp_sqlite": args.db3,
        "S119_external_link_sidecar": args.s119_sidecar,
    }
    report = build_audit(db_paths, args.s120_items, args.out_dir, args.scorecard)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "blocking_finding_count": report["blocking_finding_count"],
                "risk_finding_count": report["risk_finding_count"],
                "secret_like_finding_count": report["secret_like_finding_count"],
                "outputs": report["outputs"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if report["blocking_finding_count"] or report["secret_like_finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
