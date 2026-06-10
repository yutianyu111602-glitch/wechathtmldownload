#!/usr/bin/env python3
"""Build a report-only health refresh for the selected Atlas serving DB.

This checks the DJ-first serving/search/graph surface that T5 owns. It opens the
candidate SQLite read-only and writes only local evidence files.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = SCRIPT_DIR.parent

DEFAULT_CANDIDATE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_field_repair_fullcomplete_strict_20260523-1658"
    / "atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_serving_search_graph_health_refresh_t5_20260525"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T5_SERVING_SEARCH_GRAPH_HEALTH_REFRESH_20260525.md"

REQUIRED_PUBLIC_TABLES = (
    "performance_event",
    "dj_profile",
    "dj_event",
    "dj_relation_rollup",
    "dj_venue_rollup",
    "dj_org_rollup",
    "evidence_ref",
    "search_document",
    "search_document_fts",
    "graph_window_cache",
    "activity_event_detail",
    "activity_evidence_ref",
)

DEFAULT_SEARCH_TERMS = ("MaFoL", "DaRou", "OIL", "SHCR", "BYYB", "DADA", "DADA昆明")

OLD_DJ_FIRST_PLAN_DOCS = (
    "docs/ATLAS_DJ_GRAPH_SAVEPOINT_AND_PLAN_20260522.md",
    "docs/ATLAS_DJ_FIRST_FULL_DESIGN_AND_PLAN_20260522.md",
    "docs/ATLAS_HIGH_PERFORMANCE_DATABASE_ARCHITECTURE_20260522.md",
    "docs/ATLAS_SERVING_READ_MODEL_PRODUCTION_RUN_20260522.md",
    "docs/ATLAS_GRAPH_DB_SEARCH_TAXONOMY_ARCHITECTURE_20260521.md",
    "reports/atlas_dj_first_canary_20260522/summary.md",
)

FORBIDDEN_SCHEMA_PATTERNS = (
    "raw_url",
    "source_url",
    "archive_html",
    "archive_path",
    "html_path",
    "openid",
    "fakeid",
    "unionid",
    "cookie",
    "token",
)
LEAK_VALUE_PATTERNS = (
    "http://",
    "https://",
    "mp.weixin.qq.com",
    "openid",
    "fakeid",
    "unionid",
    "C:\\",
    "D:\\",
    "/mnt/",
    "/home/",
    "\\\\wsl",
    "archive_html_path",
    "raw_html",
)
VALUE_SCAN_COLUMNS = {
    "evidence_ref": ("source_hash", "source_account", "source_title", "public_snippet", "source_kind"),
    "search_document": ("display_name", "aliases_text", "city_text", "taxon_path", "search_text"),
    "activity_event_detail": (
        "title",
        "event_time_text",
        "venue_name",
        "address",
        "city_name",
        "lineup_artists_json",
        "music_styles_json",
        "genres_json",
        "ticketing_text",
        "source_account_name",
    ),
    "activity_evidence_ref": (
        "field_path",
        "field_value",
        "support_type",
        "source_kind",
        "source_account_name",
        "quote",
        "ocr_span_id",
        "ocr_span_status",
    ),
}
NOISE_REVIEW_TERMS = ("入门卡", "优惠时段", "报名", "课程表", "瑜伽", "读书会", "咖啡", "火锅")

SECRETISH_RE = re.compile(
    r"https?://\S+|mp\.weixin\.qq\.com\S*|openid[=:\w-]*|fakeid[=:\w-]*|unionid[=:\w-]*|[A-Za-z]:\\\S+|/mnt/\S+|/home/\S+|\\\\wsl\S*",
    re.IGNORECASE,
)


def now_stamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'virtual table') AND name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not table_exists(conn, table):
        return []
    return [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")]


def table_count(conn: sqlite3.Connection, table: str) -> int | None:
    if not table_exists(conn, table):
        return None
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()} if row else {}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_report(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    safety = report["public_safety"]
    graph = report["graph_window_health"]
    search = report["search_health"]
    profile = report["profile_completeness"]
    paths = report["outputs"]
    lines = [
        "# Atlas T5 Serving Search Graph Health Refresh",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Decision",
        "",
        f"`{report['decision']}`",
        "",
        f"Candidate DB: `{report['candidate_db']}`",
        "",
        "This is report-only/read-only evidence. It does not update the serving pointer, public pointer, CloudRun/VPS, Neo4j, Qdrant, mini-program state, memory, or source Atlas SQLite.",
        "",
        "## DJ-First Plan Evidence",
        "",
    ]
    for item in report["old_dj_first_plan_docs"]:
        lines.append(f"- `{item['path']}` exists={str(item['exists']).lower()}")
    lines.extend(
        [
            "",
            "## Counts",
            "",
        ]
    )
    for key in REQUIRED_PUBLIC_TABLES:
        lines.append(f"- {key}: `{counts.get(key)}`")
    lines.extend(
        [
            "",
            "## Search Health",
            "",
            f"- terms checked: `{len(search['terms'])}`",
            f"- LIKE missing: `{search['like_missing_count']}`",
            f"- FTS missing: `{search['fts_missing_count']}`",
            f"- FTS errors: `{len(search['fts_errors'])}`",
            "",
            "## Graph/Profile Health",
            "",
            f"- DJ profiles: `{profile['dj_profiles']}`",
            f"- graph windows: `{graph['graph_windows']}`",
            f"- graph window gap: `{graph['graph_window_gap']}`",
            f"- seed DJ graph hits: `{graph['seed_dj_graph_hits']}`",
            f"- seed DJ graph missing: `{graph['seed_dj_graph_missing']}`",
            f"- missing avatar_asset_id: `{profile['missing_avatar_asset_id']}`",
            f"- missing city_primary: `{profile['missing_city_primary']}`",
            f"- zero event_count profiles: `{profile['zero_event_count_profiles']}`",
            "",
            "## Public-Safety Checks",
            "",
            f"- missing required tables: `{len(report['missing_required_tables'])}`",
            f"- forbidden schema hits: `{len(safety['forbidden_schema_hits'])}`",
            f"- forbidden value hits: `{safety['value_leak_hit_total']}`",
            f"- public_url_allowed nonzero rows: `{safety['public_url_allowed_nonzero_rows']}`",
            f"- review noise signals: `{safety['noise_review_hit_total']}` (not a hard blocker by itself)",
            "",
            "## Outputs",
            "",
            f"- summary JSON: `{paths['summary_json']}`",
            f"- search smoke: `{paths['search_smoke_json']}`",
            f"- graph samples: `{paths['graph_window_samples_json']}`",
            f"- leak scan: `{paths['leak_scan_json']}`",
            f"- top profiles: `{paths['top_profiles_json']}`",
            "",
            "## Next Resume Cursor",
            "",
            report["next_resume_cursor"],
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def sanitize_preview(value: Any, limit: int = 180) -> str:
    text = "" if value is None else str(value)
    text = SECRETISH_RE.sub("[redacted-public-safety-hit]", text)
    text = text.replace("\r", " ").replace("\n", " ")
    return text[:limit]


def existing_plan_docs() -> list[dict[str, Any]]:
    return [{"path": path, "exists": (REPO_ROOT / path).exists()} for path in OLD_DJ_FIRST_PLAN_DOCS]


def schema_forbidden_hits(conn: sqlite3.Connection) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for table in REQUIRED_PUBLIC_TABLES:
        for col in sqlite_columns(conn, table):
            lowered = col.lower()
            if col == "public_url_allowed":
                continue
            if any(pattern in lowered for pattern in FORBIDDEN_SCHEMA_PATTERNS):
                hits.append({"table": table, "column": col})
    return hits


def public_url_allowed_nonzero(conn: sqlite3.Connection) -> int:
    if not table_exists(conn, "evidence_ref") or "public_url_allowed" not in sqlite_columns(conn, "evidence_ref"):
        return 0
    return int(conn.execute("SELECT COUNT(*) FROM evidence_ref WHERE COALESCE(public_url_allowed, 0) != 0").fetchone()[0])


def value_leak_scan(conn: sqlite3.Connection) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    total = 0
    for table, columns in VALUE_SCAN_COLUMNS.items():
        if not table_exists(conn, table):
            continue
        present = set(sqlite_columns(conn, table))
        for column in columns:
            if column not in present:
                continue
            for pattern in LEAK_VALUE_PATTERNS:
                like_pattern = f"%{pattern}%"
                count = int(
                    conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} LIKE ?", (like_pattern,)).fetchone()[0]
                )
                if count == 0:
                    continue
                total += count
                sample = conn.execute(
                    f"SELECT {column} AS value FROM {table} WHERE {column} LIKE ? LIMIT 1",
                    (like_pattern,),
                ).fetchone()
                hits.append(
                    {
                        "table": table,
                        "column": column,
                        "pattern": pattern,
                        "count": count,
                        "value_preview": sanitize_preview(sample["value"] if sample else ""),
                    }
                )
    return {"total": total, "hits": hits}


def noise_review_scan(conn: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(conn, "search_document"):
        return {"total": 0, "terms": []}
    present = set(sqlite_columns(conn, "search_document"))
    columns = [col for col in ("display_name", "aliases_text", "search_text") if col in present]
    results = []
    total = 0
    for term in NOISE_REVIEW_TERMS:
        where = " OR ".join(f"{col} LIKE ?" for col in columns)
        params = tuple(f"%{term}%" for _ in columns)
        count = int(conn.execute(f"SELECT COUNT(*) FROM search_document WHERE {where}", params).fetchone()[0])
        total += count
        sample_row = None
        if count:
            sample_row = conn.execute(
                f"SELECT subject_id, subject_type, display_name FROM search_document WHERE {where} LIMIT 1",
                params,
            ).fetchone()
        results.append({"term": term, "count": count, "sample": row_dict(sample_row)})
    return {"total": total, "terms": results}


def search_health(conn: sqlite3.Connection, terms: tuple[str, ...]) -> dict[str, Any]:
    results = []
    fts_errors: list[dict[str, str]] = []
    like_missing = 0
    fts_missing = 0
    for term in terms:
        like_params = tuple(f"%{term}%" for _ in range(3))
        like_count = 0
        like_samples: list[dict[str, Any]] = []
        if table_exists(conn, "search_document"):
            like_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM search_document
                    WHERE display_name LIKE ? OR aliases_text LIKE ? OR search_text LIKE ?
                    """,
                    like_params,
                ).fetchone()[0]
            )
            like_samples = [
                row_dict(row)
                for row in conn.execute(
                    """
                    SELECT subject_id, subject_type, display_name, city_text, rank_score
                    FROM search_document
                    WHERE display_name LIKE ? OR aliases_text LIKE ? OR search_text LIKE ?
                    ORDER BY rank_score DESC, display_name
                    LIMIT 5
                    """,
                    like_params,
                )
            ]
        fts_count: int | None = None
        fts_samples: list[dict[str, Any]] = []
        if table_exists(conn, "search_document_fts"):
            try:
                fts_count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM search_document_fts WHERE search_document_fts MATCH ?",
                        (term,),
                    ).fetchone()[0]
                )
                fts_samples = [
                    row_dict(row)
                    for row in conn.execute(
                        """
                        SELECT sd.subject_id, sd.subject_type, sd.display_name, sd.city_text, sd.rank_score
                        FROM search_document_fts f
                        JOIN search_document sd ON sd.doc_rowid = f.rowid
                        WHERE search_document_fts MATCH ?
                        ORDER BY sd.rank_score DESC, sd.display_name
                        LIMIT 5
                        """,
                        (term,),
                    )
                ]
            except sqlite3.Error as exc:
                fts_errors.append({"term": term, "error": str(exc)})
        if like_count == 0:
            like_missing += 1
        if fts_count == 0 or fts_count is None:
            fts_missing += 1
        results.append(
            {
                "term": term,
                "like_count": like_count,
                "fts_count": fts_count,
                "like_samples": like_samples,
                "fts_samples": fts_samples,
            }
        )
    return {
        "terms": results,
        "like_missing_count": like_missing,
        "fts_missing_count": fts_missing,
        "fts_errors": fts_errors,
    }


def parse_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def graph_window_health(conn: sqlite3.Connection, terms: tuple[str, ...]) -> dict[str, Any]:
    dj_profiles = table_count(conn, "dj_profile") or 0
    graph_windows = table_count(conn, "graph_window_cache") or 0
    gap = 0
    if table_exists(conn, "dj_profile") and table_exists(conn, "graph_window_cache"):
        gap = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM dj_profile p
                LEFT JOIN graph_window_cache g ON g.seed_subject_id = p.dj_id
                WHERE g.seed_subject_id IS NULL
                """
            ).fetchone()[0]
        )
    seed_samples = []
    graph_hits = 0
    graph_missing = 0
    for term in terms:
        params = tuple(f"%{term}%" for _ in range(3))
        profile = conn.execute(
            """
            SELECT subject_id, subject_type, display_name, city_text, rank_score
            FROM search_document
            WHERE subject_type = 'dj'
              AND (display_name LIKE ? OR aliases_text LIKE ? OR search_text LIKE ?)
            ORDER BY rank_score DESC, display_name
            LIMIT 1
            """,
            params,
        ).fetchone()
        item: dict[str, Any] = {"term": term, "dj_profile_hit": row_dict(profile)}
        if not profile:
            item["status"] = "no_dj_profile_hit"
            graph_missing += 1
            seed_samples.append(item)
            continue
        window = conn.execute(
            """
            SELECT window_key, seed_subject_id, lens, depth, node_count, edge_count, nodes_json, edges_json
            FROM graph_window_cache
            WHERE seed_subject_id = ?
            LIMIT 1
            """,
            (profile["subject_id"],),
        ).fetchone()
        if not window:
            item["status"] = "missing_graph_window"
            graph_missing += 1
            seed_samples.append(item)
            continue
        nodes = parse_json_list(window["nodes_json"])
        edges = parse_json_list(window["edges_json"])
        item["status"] = "graph_window_present"
        item["graph_window"] = {
            "window_key": window["window_key"],
            "node_count": int(window["node_count"] or 0),
            "edge_count": int(window["edge_count"] or 0),
            "parsed_node_count": len(nodes),
            "parsed_edge_count": len(edges),
            "lens": window["lens"],
            "depth": window["depth"],
        }
        graph_hits += 1
        seed_samples.append(item)
    return {
        "dj_profiles": dj_profiles,
        "graph_windows": graph_windows,
        "graph_window_gap": gap,
        "seed_dj_graph_hits": graph_hits,
        "seed_dj_graph_missing": graph_missing,
        "seed_samples": seed_samples,
    }


def profile_completeness(conn: sqlite3.Connection) -> dict[str, Any]:
    if not table_exists(conn, "dj_profile"):
        return {
            "dj_profiles": 0,
            "missing_avatar_asset_id": 0,
            "missing_city_primary": 0,
            "zero_event_count_profiles": 0,
            "top_profiles": [],
        }
    missing_avatar = int(
        conn.execute("SELECT COUNT(*) FROM dj_profile WHERE avatar_asset_id IS NULL OR trim(avatar_asset_id) = ''").fetchone()[0]
    )
    missing_city = int(
        conn.execute("SELECT COUNT(*) FROM dj_profile WHERE city_primary IS NULL OR trim(city_primary) = ''").fetchone()[0]
    )
    zero_event = int(conn.execute("SELECT COUNT(*) FROM dj_profile WHERE COALESCE(event_count, 0) = 0").fetchone()[0])
    top_profiles = [
        row_dict(row)
        for row in conn.execute(
            """
            SELECT dj_id, display_name, city_primary, event_count, venue_count,
                   collaborator_count, organization_count, source_article_count,
                   avatar_asset_id, first_seen_at, last_seen_at, confidence
            FROM dj_profile
            ORDER BY event_count DESC, collaborator_count DESC, display_name
            LIMIT 20
            """
        )
    ]
    return {
        "dj_profiles": table_count(conn, "dj_profile") or 0,
        "missing_avatar_asset_id": missing_avatar,
        "missing_city_primary": missing_city,
        "zero_event_count_profiles": zero_event,
        "top_profiles": top_profiles,
    }


def build_refresh(
    candidate_db: Path,
    out_dir: Path,
    report_path: Path,
    search_terms: tuple[str, ...] = DEFAULT_SEARCH_TERMS,
) -> dict[str, Any]:
    if not candidate_db.exists():
        raise FileNotFoundError(candidate_db)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = now_stamp()
    conn = connect_readonly(candidate_db)
    try:
        counts = {table: table_count(conn, table) for table in REQUIRED_PUBLIC_TABLES}
        missing_required = [table for table, count in counts.items() if count is None]
        search = search_health(conn, search_terms) if not missing_required else {"terms": [], "like_missing_count": 0, "fts_missing_count": 0, "fts_errors": []}
        graph = graph_window_health(conn, search_terms) if not missing_required else {
            "dj_profiles": 0,
            "graph_windows": 0,
            "graph_window_gap": 0,
            "seed_dj_graph_hits": 0,
            "seed_dj_graph_missing": 0,
            "seed_samples": [],
        }
        profile = profile_completeness(conn)
        leaks = value_leak_scan(conn)
        noise = noise_review_scan(conn)
        public_safety = {
            "forbidden_schema_hits": schema_forbidden_hits(conn),
            "value_leak_hit_total": leaks["total"],
            "value_leak_hits": leaks["hits"],
            "public_url_allowed_nonzero_rows": public_url_allowed_nonzero(conn),
            "noise_review_hit_total": noise["total"],
            "noise_review_terms": noise["terms"],
        }
        blockers = []
        if missing_required:
            blockers.append({"gate": "required_public_tables", "value": missing_required})
        if graph["graph_window_gap"] != 0:
            blockers.append({"gate": "graph_window_gap", "value": graph["graph_window_gap"]})
        if public_safety["forbidden_schema_hits"]:
            blockers.append({"gate": "forbidden_schema_hits", "value": public_safety["forbidden_schema_hits"]})
        if public_safety["value_leak_hit_total"] != 0:
            blockers.append({"gate": "forbidden_value_hits", "value": public_safety["value_leak_hit_total"]})
        if public_safety["public_url_allowed_nonzero_rows"] != 0:
            blockers.append({"gate": "public_url_allowed_nonzero", "value": public_safety["public_url_allowed_nonzero_rows"]})

        decision = (
            "atlas_serving_search_graph_health_refresh_ready_report_only"
            if not blockers
            else "atlas_serving_search_graph_health_refresh_blocked_report_only"
        )
        outputs = {
            "summary_json": str(out_dir / "atlas_serving_search_graph_health_refresh_summary.json"),
            "search_smoke_json": str(out_dir / "search_smoke.json"),
            "graph_window_samples_json": str(out_dir / "graph_window_samples.json"),
            "leak_scan_json": str(out_dir / "public_safety_scan.json"),
            "top_profiles_json": str(out_dir / "top_profiles.json"),
            "markdown_report": str(report_path),
        }
        report = {
            "schema_version": "atlas_serving_search_graph_health_refresh.v1",
            "generated_at": generated_at,
            "decision": decision,
            "candidate_db": str(candidate_db),
            "counts": counts,
            "missing_required_tables": missing_required,
            "search_health": search,
            "graph_window_health": graph,
            "profile_completeness": profile,
            "public_safety": public_safety,
            "blockers": blockers,
            "old_dj_first_plan_docs": existing_plan_docs(),
            "safety": {
                "read_only_candidate_sqlite": True,
                "source_sqlite_write_executed": False,
                "serving_pointer_update_executed": False,
                "public_pointer_update_executed": False,
                "neo4j_write_executed": False,
                "qdrant_write_executed": False,
                "cloudrun_or_vps_deploy_executed": False,
                "miniprogram_upload_or_review_executed": False,
                "memory_write_executed": False,
                "credential_read_or_printed": False,
            },
            "outputs": outputs,
            "next_resume_cursor": (
                "Use this health refresh as the current T5 report-only proof for the selected field-repair fullcomplete strict candidate. "
                "If public target identity is still session-gated, switch next to T6 source-context recovery or T4 activity-to-Atlas sidecar instead of idling on T5 public exposure."
            ),
        }
        write_json(out_dir / "search_smoke.json", search)
        write_json(out_dir / "graph_window_samples.json", graph["seed_samples"])
        write_json(out_dir / "public_safety_scan.json", public_safety)
        write_json(out_dir / "top_profiles.json", profile["top_profiles"])
        write_json(out_dir / "atlas_serving_search_graph_health_refresh_summary.json", report)
        write_report(report_path, report)
        return report
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--search-term", action="append", dest="search_terms")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    terms = tuple(args.search_terms) if args.search_terms else DEFAULT_SEARCH_TERMS
    report = build_refresh(args.candidate_db, args.out_dir, args.report_path, terms)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "report": report["outputs"]["markdown_report"],
                "summary_json": report["outputs"]["summary_json"],
                "blockers": report["blockers"],
                "search_like_missing_count": report["search_health"]["like_missing_count"],
                "search_fts_missing_count": report["search_health"]["fts_missing_count"],
                "graph_window_gap": report["graph_window_health"]["graph_window_gap"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
