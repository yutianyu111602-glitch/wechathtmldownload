#!/usr/bin/env python3
"""Report-only preflight for Atlas serving promotion source selection.

This validator checks the selected public-safe serving SQLite and, when
provided, compares it with an earlier candidate. It never copies SQLite files,
updates serving pointers, deploys CloudRun/VPS services, or writes Neo4j/Qdrant.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CANDIDATE_DB = Path(
    "reports/atlas_serving_activity_participant_candidate_139123_publicsafe_djcomplete_v2_20260522-2335/atlas_serving.sqlite"
)
DEFAULT_COMPARISON_DB = Path(
    "reports/atlas_serving_participant_delta_public_candidate_publicsafe_v3_20260522/atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = Path("reports/atlas_serving_promotion_preflight_20260523")

PUBLIC_TABLES = [
    "performance_event",
    "dj_profile",
    "dj_event",
    "dj_relation_rollup",
    "search_document",
    "graph_window_cache",
    "evidence_ref",
    "activity_event_detail",
    "activity_evidence_ref",
]

REQUIRED_TABLES = [
    "performance_event",
    "dj_profile",
    "dj_event",
    "dj_relation_rollup",
    "search_document",
    "graph_window_cache",
    "evidence_ref",
    "activity_event_detail",
    "activity_evidence_ref",
]

FORBIDDEN_SCHEMA_FRAGMENTS = [
    "source_url",
    "raw_url",
    "archive_html",
    "archive_path",
    "raw_html",
    "article_uid",
    "openid",
    "fakeid",
    "local_path",
]

FORBIDDEN_VALUE_TERMS = [
    "mp.weixin.qq.com",
    "__biz",
    "openid",
    "fakeid",
    "archive_html",
    "archive_path",
    "raw_url",
    "source_url",
    "file://",
    "C:/code",
    "C:\\code",
    "/mnt/d",
    "/mnt/c",
]

HARD_NOISE_TERMS = [
    "wine menu",
    "wine tasting",
    "葡萄酒",
    "入门卡",
    "优惠时段",
    "报名",
    "预售截止",
    "购票链接",
    "票务链接",
]


@dataclass(frozen=True)
class SqliteFacts:
    path: str
    size_bytes: int
    tables: list[str]
    counts: dict[str, int | None]
    build_metadata: dict[str, str]
    forbidden_schema_columns: list[dict[str, str]]
    forbidden_value_hits: dict[str, list[dict[str, Any]]]
    hard_noise_hits: dict[str, int]
    duplicate_normalized_name_groups: int | None
    duplicate_normalized_profile_rows: int | None
    distinct_normalized_profiles: int | None
    activity_events_with_evidence: int | None
    public_url_allowed_nonzero: int | None
    graph_window_gap: int | None


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def open_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def table_names(cur: sqlite3.Cursor) -> set[str]:
    return {str(row[0]) for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(cur: sqlite3.Cursor, table: str) -> list[dict[str, str]]:
    return [{"name": str(row[1]), "type": str(row[2] or "")} for row in cur.execute(f'PRAGMA table_info("{table}")')]


def text_columns(cur: sqlite3.Cursor, table: str) -> list[str]:
    result: list[str] = []
    for col in columns(cur, table):
        col_type = col["type"].upper()
        if "TEXT" in col_type or col_type in {"VARCHAR", "CHAR"}:
            result.append(col["name"])
    return result


def count_table(cur: sqlite3.Cursor, tables: set[str], table: str) -> int | None:
    if table not in tables:
        return None
    return int(cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def read_build_metadata(cur: sqlite3.Cursor, tables: set[str]) -> dict[str, str]:
    if "build_metadata" not in tables:
        return {}
    return {str(row[0]): str(row[1]) for row in cur.execute("SELECT key, value FROM build_metadata")}


def scan_forbidden_schema(cur: sqlite3.Cursor, tables: set[str]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for table in PUBLIC_TABLES:
        if table not in tables:
            continue
        for col in columns(cur, table):
            lowered = col["name"].lower()
            if any(fragment in lowered for fragment in FORBIDDEN_SCHEMA_FRAGMENTS):
                hits.append({"table": table, "column": col["name"]})
    return hits


def scan_forbidden_values(cur: sqlite3.Cursor, tables: set[str]) -> dict[str, list[dict[str, Any]]]:
    hits: dict[str, list[dict[str, Any]]] = {}
    for table in PUBLIC_TABLES:
        if table not in tables:
            continue
        table_hits: list[dict[str, Any]] = []
        for col in text_columns(cur, table):
            for term in FORBIDDEN_VALUE_TERMS:
                # instr() is case-sensitive for these raw/private markers. This
                # avoids false positives such as "IBIZA" matching "__biz".
                count = int(
                    cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE instr("{col}", ?) > 0', (term,)).fetchone()[0]
                )
                if count:
                    table_hits.append({"column": col, "term": term, "count": count})
        if table_hits:
            hits[table] = table_hits
    return hits


def scan_hard_noise(cur: sqlite3.Cursor, tables: set[str]) -> dict[str, int]:
    if "search_document" not in tables:
        return {}
    available = {col["name"] for col in columns(cur, "search_document")}
    search_cols = [col for col in ["display_name", "aliases_text", "search_text"] if col in available]
    hits: dict[str, int] = {}
    for term in HARD_NOISE_TERMS:
        total = 0
        for col in search_cols:
            total += int(
                cur.execute(f'SELECT COUNT(*) FROM search_document WHERE "{col}" LIKE ?', (f"%{term}%",)).fetchone()[0]
            )
        if total:
            hits[term] = total
    return hits


def profile_duplicate_facts(cur: sqlite3.Cursor, tables: set[str]) -> tuple[int | None, int | None, int | None]:
    if "dj_profile" not in tables:
        return None, None, None
    available = {col["name"] for col in columns(cur, "dj_profile")}
    if "normalized_name" not in available:
        return None, None, None
    distinct_count = int(
        cur.execute(
            "SELECT COUNT(DISTINCT lower(normalized_name)) FROM dj_profile WHERE coalesce(normalized_name, '') <> ''"
        ).fetchone()[0]
    )
    duplicate_groups = int(
        cur.execute(
            """
            SELECT COUNT(*)
            FROM (
              SELECT lower(normalized_name) AS n, COUNT(*) AS c
              FROM dj_profile
              WHERE coalesce(normalized_name, '') <> ''
              GROUP BY n
              HAVING c > 1
            )
            """
        ).fetchone()[0]
    )
    duplicate_rows = int(
        cur.execute(
            """
            SELECT coalesce(SUM(c), 0)
            FROM (
              SELECT lower(normalized_name) AS n, COUNT(*) AS c
              FROM dj_profile
              WHERE coalesce(normalized_name, '') <> ''
              GROUP BY n
              HAVING c > 1
            )
            """
        ).fetchone()[0]
    )
    return duplicate_groups, duplicate_rows, distinct_count


def activity_evidence_count(cur: sqlite3.Cursor, tables: set[str]) -> int | None:
    if "activity_event_detail" not in tables or "activity_evidence_ref" not in tables:
        return None
    return int(
        cur.execute(
            """
            SELECT COUNT(DISTINCT d.event_id)
            FROM activity_event_detail d
            JOIN activity_evidence_ref e ON e.event_id = d.event_id
            """
        ).fetchone()[0]
    )


def public_url_allowed_nonzero(cur: sqlite3.Cursor, tables: set[str]) -> int | None:
    if "evidence_ref" not in tables:
        return None
    available = {col["name"] for col in columns(cur, "evidence_ref")}
    if "public_url_allowed" not in available:
        return None
    return int(cur.execute("SELECT COUNT(*) FROM evidence_ref WHERE coalesce(public_url_allowed, 0) != 0").fetchone()[0])


def graph_window_gap(cur: sqlite3.Cursor, tables: set[str]) -> int | None:
    if "dj_profile" not in tables or "graph_window_cache" not in tables:
        return None
    profile_cols = {col["name"] for col in columns(cur, "dj_profile")}
    graph_cols = {col["name"] for col in columns(cur, "graph_window_cache")}
    if "dj_id" not in profile_cols:
        return None
    graph_id_col = (
        "subject_id"
        if "subject_id" in graph_cols
        else "seed_subject_id"
        if "seed_subject_id" in graph_cols
        else "seed_id"
        if "seed_id" in graph_cols
        else None
    )
    if not graph_id_col:
        return None
    return int(
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM dj_profile p
            LEFT JOIN graph_window_cache g ON g."{graph_id_col}" = p.dj_id
            WHERE g."{graph_id_col}" IS NULL
            """
        ).fetchone()[0]
    )


def collect_sqlite_facts(path: Path) -> SqliteFacts:
    conn = open_ro(path)
    try:
        cur = conn.cursor()
        tables = table_names(cur)
        duplicate_groups, duplicate_rows, distinct_profiles = profile_duplicate_facts(cur, tables)
        return SqliteFacts(
            path=str(path),
            size_bytes=path.stat().st_size,
            tables=sorted(tables),
            counts={table: count_table(cur, tables, table) for table in PUBLIC_TABLES},
            build_metadata=read_build_metadata(cur, tables),
            forbidden_schema_columns=scan_forbidden_schema(cur, tables),
            forbidden_value_hits=scan_forbidden_values(cur, tables),
            hard_noise_hits=scan_hard_noise(cur, tables),
            duplicate_normalized_name_groups=duplicate_groups,
            duplicate_normalized_profile_rows=duplicate_rows,
            distinct_normalized_profiles=distinct_profiles,
            activity_events_with_evidence=activity_evidence_count(cur, tables),
            public_url_allowed_nonzero=public_url_allowed_nonzero(cur, tables),
            graph_window_gap=graph_window_gap(cur, tables),
        )
    finally:
        conn.close()


def total_forbidden_value_hits(facts: SqliteFacts) -> int:
    total = 0
    for table_hits in facts.forbidden_value_hits.values():
        total += sum(int(item["count"]) for item in table_hits)
    return total


def check(name: str, ok: bool, detail: Any) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def build_checks(candidate: SqliteFacts, comparison: SqliteFacts | None) -> list[dict[str, Any]]:
    metadata = candidate.build_metadata
    candidate_tables = set(candidate.tables)
    checks = [
        check("required_public_tables_present", all(table in candidate_tables for table in REQUIRED_TABLES), candidate.counts),
        check("deployable_public_metadata", metadata.get("deployable_public") in {"1", "true", "True"}, metadata),
        check("participant_acceptance_strict", metadata.get("participant_acceptance") == "strict", metadata.get("participant_acceptance")),
        check("raw_source_url_columns_not_copied", metadata.get("raw_source_url_columns_copied") in {"0", "false", "False"}, metadata),
        check("archive_html_path_columns_not_copied", metadata.get("archive_html_path_columns_copied") in {"0", "false", "False"}, metadata),
        check("forbidden_schema_columns_zero", len(candidate.forbidden_schema_columns) == 0, candidate.forbidden_schema_columns),
        check("forbidden_value_hits_zero", total_forbidden_value_hits(candidate) == 0, candidate.forbidden_value_hits),
        check("hard_noise_hits_zero", not candidate.hard_noise_hits, candidate.hard_noise_hits),
        check("activity_tables_present", candidate.counts.get("activity_event_detail") is not None and candidate.counts.get("activity_evidence_ref") is not None, candidate.counts),
        check(
            "activity_events_have_evidence",
            candidate.activity_events_with_evidence is not None
            and candidate.activity_events_with_evidence == candidate.counts.get("activity_event_detail"),
            {
                "activity_events_with_evidence": candidate.activity_events_with_evidence,
                "activity_event_detail": candidate.counts.get("activity_event_detail"),
            },
        ),
        check("duplicate_normalized_profile_groups_zero", candidate.duplicate_normalized_name_groups == 0, candidate.duplicate_normalized_name_groups),
        check("graph_window_gap_zero", candidate.graph_window_gap in {0, None}, candidate.graph_window_gap),
        check("public_url_allowed_zero_or_absent", candidate.public_url_allowed_nonzero in {0, None}, candidate.public_url_allowed_nonzero),
    ]
    if comparison:
        checks.extend(
            [
                check(
                    "candidate_activity_coverage_not_worse_than_comparison",
                    (
                        comparison.counts.get("activity_event_detail") is None
                        or (candidate.counts.get("activity_event_detail") or 0) >= (comparison.counts.get("activity_event_detail") or 0)
                    )
                    and (
                        comparison.counts.get("activity_evidence_ref") is None
                        or (candidate.counts.get("activity_evidence_ref") or 0) >= (comparison.counts.get("activity_evidence_ref") or 0)
                    ),
                    {
                        "candidate_activity_event_detail": candidate.counts.get("activity_event_detail"),
                        "candidate_activity_evidence_ref": candidate.counts.get("activity_evidence_ref"),
                        "comparison_activity_event_detail": comparison.counts.get("activity_event_detail"),
                        "comparison_activity_evidence_ref": comparison.counts.get("activity_evidence_ref"),
                    },
                ),
                check(
                    "candidate_duplicate_profile_groups_not_worse_than_comparison",
                    (candidate.duplicate_normalized_name_groups or 0) <= (comparison.duplicate_normalized_name_groups or 0),
                    {
                        "candidate": candidate.duplicate_normalized_name_groups,
                        "comparison": comparison.duplicate_normalized_name_groups,
                    },
                ),
                check(
                    "candidate_hard_noise_not_worse_than_comparison",
                    sum(candidate.hard_noise_hits.values()) <= sum(comparison.hard_noise_hits.values()),
                    {"candidate": candidate.hard_noise_hits, "comparison": comparison.hard_noise_hits},
                ),
            ]
        )
    return checks


def markdown_report(payload: dict[str, Any]) -> str:
    candidate = payload["candidate"]
    comparison = payload.get("comparison")
    checks = payload["checks"]
    failed = [item for item in checks if not item["ok"]]
    lines = [
        "# Atlas Serving Promotion Preflight",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "## Decision",
        "",
        f"- decision: `{payload['decision']}`",
        f"- selected_candidate: `{candidate['path']}`",
        "- production_write_executed: `false`",
        "- cloudrun_deploy_executed: `false`",
        "- neo4j_write_executed: `false`",
        "- qdrant_write_executed: `false`",
        "",
        "## Candidate",
        "",
        f"- size_bytes: `{candidate['size_bytes']}`",
        f"- counts: `{json.dumps(candidate['counts'], ensure_ascii=False)}`",
        f"- activity_events_with_evidence: `{candidate['activity_events_with_evidence']}`",
        f"- duplicate_normalized_name_groups: `{candidate['duplicate_normalized_name_groups']}`",
        f"- graph_window_gap: `{candidate['graph_window_gap']}`",
        "",
    ]
    if comparison:
        lines.extend(
            [
                "## Comparison",
                "",
                f"- comparison_candidate: `{comparison['path']}`",
                f"- counts: `{json.dumps(comparison['counts'], ensure_ascii=False)}`",
                f"- duplicate_normalized_name_groups: `{comparison['duplicate_normalized_name_groups']}`",
                f"- hard_noise_hits: `{json.dumps(comparison['hard_noise_hits'], ensure_ascii=False)}`",
                "",
            ]
        )
    lines.extend(["## Checks", ""])
    for item in checks:
        status = "PASS" if item["ok"] else "FAIL"
        lines.append(f"- `{status}` {item['name']}: `{json.dumps(item['detail'], ensure_ascii=False)}`")
    if failed:
        lines.extend(["", "## Blockers", ""])
        for item in failed:
            lines.append(f"- `{item['name']}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This is a local report-only preflight. Production pointer update, VPS/CloudRun deploy, Neo4j/Qdrant writes, and mini-program publication require a separate explicit gate.",
            "",
        ]
    )
    return "\n".join(lines)


def facts_to_dict(facts: SqliteFacts) -> dict[str, Any]:
    return {
        "path": facts.path,
        "size_bytes": facts.size_bytes,
        "tables": facts.tables,
        "counts": facts.counts,
        "build_metadata": facts.build_metadata,
        "forbidden_schema_columns": facts.forbidden_schema_columns,
        "forbidden_value_hits": facts.forbidden_value_hits,
        "hard_noise_hits": facts.hard_noise_hits,
        "duplicate_normalized_name_groups": facts.duplicate_normalized_name_groups,
        "duplicate_normalized_profile_rows": facts.duplicate_normalized_profile_rows,
        "distinct_normalized_profiles": facts.distinct_normalized_profiles,
        "activity_events_with_evidence": facts.activity_events_with_evidence,
        "public_url_allowed_nonzero": facts.public_url_allowed_nonzero,
        "graph_window_gap": facts.graph_window_gap,
    }


def build_payload(candidate_db: Path, comparison_db: Path | None) -> dict[str, Any]:
    candidate = collect_sqlite_facts(candidate_db)
    comparison = collect_sqlite_facts(comparison_db) if comparison_db else None
    checks = build_checks(candidate, comparison)
    ok = all(item["ok"] for item in checks)
    return {
        "schema_version": "atlas_serving_promotion_preflight.v1",
        "generated_at": now_iso(),
        "decision": "promotion_preflight_passed_local_only" if ok else "promotion_preflight_blocked",
        "candidate": facts_to_dict(candidate),
        "comparison": facts_to_dict(comparison) if comparison else None,
        "checks": checks,
        "safety": {
            "report_only": True,
            "source_sqlite_write_executed": False,
            "serving_pointer_update_executed": False,
            "cloudrun_deploy_executed": False,
            "vps_deploy_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mini_program_upload_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument("--comparison-db", type=Path, default=DEFAULT_COMPARISON_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-name", default="promotion_preflight.json")
    parser.add_argument("--md-name", default="promotion_preflight.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate_db = resolve_repo_path(args.candidate_db)
    comparison_db = resolve_repo_path(args.comparison_db) if args.comparison_db else None
    out_dir = resolve_repo_path(args.out_dir)
    payload = build_payload(candidate_db, comparison_db)
    write_json(out_dir / args.json_name, payload)
    write_text(out_dir / args.md_name, markdown_report(payload))
    print(
        json.dumps(
            {
                "decision": payload["decision"],
                "candidate": payload["candidate"]["path"],
                "comparison": payload["comparison"]["path"] if payload.get("comparison") else None,
                "failed_checks": [item["name"] for item in payload["checks"] if not item["ok"]],
                "json": str(out_dir / args.json_name),
                "markdown": str(out_dir / args.md_name),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0 if payload["decision"] == "promotion_preflight_passed_local_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
