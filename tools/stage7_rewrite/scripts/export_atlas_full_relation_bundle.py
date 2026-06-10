#!/usr/bin/env python3
"""Export a local, report-only Atlas entity/relation bundle from selected serving SQLite."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_SQLITE = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_full_relation_bundle_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_FULL_RELATION_BUNDLE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_full_relation_bundle.v1"

URL_RE = re.compile(r"https?://", re.I)
SENSITIVE_KEYS = {"token", "cookie", "password", "api_key", "apikey", "authorization"}
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:\\[^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\wsl\.localhost\\[^\s\"']+|\\\\[A-Za-z0-9][A-Za-z0-9_.-]+\\[A-Za-z0-9_.-]+\\[^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas relation export: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def open_readonly_sqlite(path: Path) -> sqlite3.Connection:
    reject_d_path(path, "sqlite")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def leak_hits_for_payload(payload: Any) -> dict[str, int]:
    hits = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}

    def visit(value: Any, key: str = "") -> None:
        key_norm = key.replace("-", "_").casefold()
        if key_norm in SENSITIVE_KEYS:
            hits["secret_word_hits"] += 1
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            hits["public_url_hits"] += len(URL_RE.findall(value))
            hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))

    visit(payload)
    return hits


def leak_hits_for_text(text: str) -> dict[str, int]:
    try:
        return leak_hits_for_payload(json.loads(text))
    except json.JSONDecodeError:
        return {
            "public_url_hits": len(URL_RE.findall(text)),
            "secret_word_hits": 0,
            "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
        }


def add_leak_hits(total: dict[str, int], payload: Any) -> None:
    hits = leak_hits_for_payload(payload)
    for key, value in hits.items():
        total[key] += value


def scalar(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0] or 0)


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return scalar(conn, f'SELECT COUNT(*) FROM "{table}"')


def maybe_limited(sql: str, limit: int | None) -> str:
    if limit is None:
        return sql
    return f"SELECT * FROM ({sql}) LIMIT {int(limit)}"


def stream_export(
    conn: sqlite3.Connection,
    sql: str,
    path: Path,
    map_row: Callable[[sqlite3.Row], dict[str, Any]],
    limit: int | None = None,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    leak_hits = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}
    tmp_path: Path | None = None
    query = maybe_limited(sql, limit)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as raw_handle:
        tmp_path = Path(raw_handle.name)
        with gzip.GzipFile(fileobj=raw_handle, mode="wb", mtime=0) as gzip_handle:
            for db_row in conn.execute(query):
                row = map_row(db_row)
                line = json.dumps(row, ensure_ascii=False, sort_keys=True)
                add_leak_hits(leak_hits, row)
                gzip_handle.write(line.encode("utf-8"))
                gzip_handle.write(b"\n")
                count += 1
    tmp_path.replace(path)
    return {
        "path": str(path),
        "rows": count,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
        "leak_scan": leak_hits,
    }


def node_canonical(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".node",
        "node_kind": "canonical_subject",
        "node_id": row["subject_id"],
        "subject_type": row["subject_type"],
        "display_name": row["display_name"],
        "normalized_name": row["normalized_name"],
        "taxon_path": row["taxon_path"],
        "city_primary": row["city_primary"],
        "confidence": row["confidence"],
        "source_count": row["source_count"],
        "event_count": row["event_count"],
        "relation_count": row["relation_count"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "public_state": row["public_state"],
    }


def node_dj(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".node",
        "node_kind": "dj_profile",
        "node_id": row["dj_id"],
        "display_name": row["display_name"],
        "normalized_name": row["normalized_name"],
        "city_primary": row["city_primary"],
        "source_article_count": row["source_article_count"],
        "event_count": row["event_count"],
        "venue_count": row["venue_count"],
        "collaborator_count": row["collaborator_count"],
        "organization_count": row["organization_count"],
        "media_count": row["media_count"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "confidence": row["confidence"],
    }


def node_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".node",
        "node_kind": "performance_event",
        "node_id": row["event_id"],
        "display_name": row["event_title"],
        "starts_at": row["starts_at"],
        "time_text": row["time_text"],
        "venue_id": row["venue_id"],
        "venue_name": row["venue_name"],
        "city": row["city"],
        "participant_count": row["participant_count"],
        "organizer_count": row["organizer_count"],
        "confidence": row["confidence"],
    }


def node_venue(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".node",
        "node_kind": "venue",
        "node_id": row["venue_id"],
        "display_name": row["venue_name"],
        "city": row["city"],
        "event_count": row["event_count"],
        "dj_count": row["dj_count"],
    }


def node_org(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".node",
        "node_kind": "organization",
        "node_id": row["org_id"],
        "display_name": row["org_name"],
        "org_type": row["org_type"],
        "evidence_count": row["evidence_count"],
        "dj_count": row["dj_count"],
        "score": row["score"],
    }


def rel_dj_dj(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".relation",
        "relation_kind": "dj_dj_rollup",
        "src_id": row["src_dj_id"],
        "dst_id": row["dst_dj_id"],
        "src_kind": "dj_profile",
        "dst_kind": "dj_profile",
        "same_event_count": row["same_event_count"],
        "same_label_count": row["same_label_count"],
        "same_venue_count": row["same_venue_count"],
        "same_source_context_count": row["same_source_context_count"],
        "source_diversity": row["source_diversity"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "relation_score": row["relation_score"],
        "relation_label_zh": row["relation_label_zh"],
        "public_state": row["public_state"],
    }


def rel_dj_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".relation",
        "relation_kind": "dj_event",
        "src_id": row["dj_id"],
        "dst_id": row["event_id"],
        "src_kind": "dj_profile",
        "dst_kind": "performance_event",
        "starts_at": row["starts_at"],
        "time_text": row["time_text"],
        "event_title": row["event_title"],
        "venue_id": row["venue_id"],
        "venue_name": row["venue_name"],
        "city": row["city"],
        "confidence": row["confidence"],
    }


def rel_dj_venue(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".relation",
        "relation_kind": "dj_venue",
        "src_id": row["dj_id"],
        "dst_id": row["venue_id"],
        "src_kind": "dj_profile",
        "dst_kind": "venue",
        "venue_name": row["venue_name"],
        "city": row["city"],
        "event_count": row["event_count"],
        "first_seen_at": row["first_seen_at"],
        "last_seen_at": row["last_seen_at"],
        "score": row["score"],
    }


def rel_dj_org(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".relation",
        "relation_kind": "dj_org",
        "src_id": row["dj_id"],
        "dst_id": row["org_id"],
        "src_kind": "dj_profile",
        "dst_kind": "organization",
        "org_name": row["org_name"],
        "org_type": row["org_type"],
        "evidence_count": row["evidence_count"],
        "score": row["score"],
    }


def rel_event_venue(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".relation",
        "relation_kind": "event_venue",
        "src_id": row["event_id"],
        "dst_id": row["venue_id"],
        "src_kind": "performance_event",
        "dst_kind": "venue",
        "event_title": row["event_title"],
        "venue_name": row["venue_name"],
        "city": row["city"],
        "starts_at": row["starts_at"],
        "confidence": row["confidence"],
    }


def build_field_completeness(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    specs = [
        ("dj_profile", "dj_id", ["display_name", "normalized_name", "city_primary", "first_seen_at", "last_seen_at"]),
        ("performance_event", "event_id", ["event_title", "starts_at", "venue_id", "venue_name", "city"]),
        ("dj_event", "dj_id || ':' || event_id", ["starts_at", "venue_id", "venue_name", "city"]),
        ("dj_relation_rollup", "src_dj_id || ':' || dst_dj_id", ["relation_label_zh", "public_state"]),
        ("dj_venue_rollup", "dj_id || ':' || venue_id", ["venue_name", "city"]),
        ("dj_org_rollup", "dj_id || ':' || org_id", ["org_name", "org_type"]),
    ]
    rows: list[dict[str, Any]] = []
    for table, _pk_expr, fields in specs:
        total = table_count(conn, table)
        for field in fields:
            missing = scalar(conn, f'SELECT COUNT(*) FROM "{table}" WHERE "{field}" IS NULL OR TRIM("{field}") = ""')
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION + ".field_completeness",
                    "table": table,
                    "field": field,
                    "total_rows": total,
                    "missing_rows": missing,
                    "coverage": 0 if total == 0 else round((total - missing) / total, 6),
                }
            )
    return rows


def build_report(summary: dict[str, Any]) -> str:
    counts = summary["source_table_counts"]
    relation_counts = summary["relation_counts"]
    node_counts = summary["node_counts"]
    lines = [
        "# Atlas T5 Full Relation Bundle",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Source SQLite SHA256: `{summary['source_sqlite_sha256']}`",
        f"- Public leak scan: `{summary['public_leak_scan']}`",
        "",
        "## Source Table Counts",
        "",
        "| table | rows |",
        "| --- | ---: |",
    ]
    for table, count in sorted(counts.items()):
        lines.append(f"| `{table}` | `{count}` |")
    lines.extend(["", "## Exported Nodes", "", "| node bundle | rows |", "| --- | ---: |"])
    for name, count in sorted(node_counts.items()):
        lines.append(f"| `{name}` | `{count}` |")
    lines.extend(["", "## Exported Relations", "", "| relation bundle | rows |", "| --- | ---: |"])
    for name, count in sorted(relation_counts.items()):
        lines.append(f"| `{name}` | `{count}` |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This export opens the selected serving SQLite read-only and writes local derived gzip JSONL files. "
            "It does not mutate source/raw Atlas DBs, serving SQLite, Neo4j, Qdrant, production pointers, "
            "CloudRun/VPS state, mini-program upload/review state, memory, credentials, 9router, D: roots, "
            "or Git history.",
            "",
        ]
    )
    return "\n".join(lines)


def build_relation_bundle(sqlite_path: Path, out_dir: Path, report_path: Path, limit: int | None = None) -> dict[str, Any]:
    generated_at = now_iso()
    conn = open_readonly_sqlite(sqlite_path)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        source_counts = {
            table: table_count(conn, table)
            for table in [
                "canonical_subject",
                "dj_profile",
                "performance_event",
                "dj_event",
                "dj_relation_rollup",
                "dj_venue_rollup",
                "dj_org_rollup",
                "search_document",
                "graph_window_cache",
                "activity_event_detail",
            ]
        }
        exports = {
            "nodes_canonical_subject": stream_export(
                conn,
                "SELECT * FROM canonical_subject",
                out_dir / "nodes_canonical_subject.jsonl.gz",
                node_canonical,
                limit,
            ),
            "nodes_dj_profile": stream_export(conn, "SELECT * FROM dj_profile", out_dir / "nodes_dj_profile.jsonl.gz", node_dj, limit),
            "nodes_performance_event": stream_export(
                conn,
                "SELECT * FROM performance_event",
                out_dir / "nodes_performance_event.jsonl.gz",
                node_event,
                limit,
            ),
            "nodes_venue": stream_export(
                conn,
                """
                SELECT venue_id,
                       COALESCE(MAX(NULLIF(venue_name, '')), venue_id) AS venue_name,
                       MAX(NULLIF(city, '')) AS city,
                       COUNT(DISTINCT event_id) AS event_count,
                       0 AS dj_count
                FROM performance_event
                WHERE venue_id IS NOT NULL AND TRIM(venue_id) != ''
                GROUP BY venue_id
                """,
                out_dir / "nodes_venue.jsonl.gz",
                node_venue,
                limit,
            ),
            "nodes_organization": stream_export(
                conn,
                """
                SELECT org_id,
                       COALESCE(MAX(NULLIF(org_name, '')), org_id) AS org_name,
                       COALESCE(MAX(NULLIF(org_type, '')), 'unknown') AS org_type,
                       SUM(evidence_count) AS evidence_count,
                       COUNT(DISTINCT dj_id) AS dj_count,
                       AVG(score) AS score
                FROM dj_org_rollup
                WHERE org_id IS NOT NULL AND TRIM(org_id) != ''
                GROUP BY org_id
                """,
                out_dir / "nodes_organization.jsonl.gz",
                node_org,
                limit,
            ),
            "relations_dj_dj": stream_export(
                conn,
                "SELECT * FROM dj_relation_rollup",
                out_dir / "relations_dj_dj.jsonl.gz",
                rel_dj_dj,
                limit,
            ),
            "relations_dj_event": stream_export(conn, "SELECT * FROM dj_event", out_dir / "relations_dj_event.jsonl.gz", rel_dj_event, limit),
            "relations_dj_venue": stream_export(
                conn,
                "SELECT * FROM dj_venue_rollup",
                out_dir / "relations_dj_venue.jsonl.gz",
                rel_dj_venue,
                limit,
            ),
            "relations_dj_org": stream_export(conn, "SELECT * FROM dj_org_rollup", out_dir / "relations_dj_org.jsonl.gz", rel_dj_org, limit),
            "relations_event_venue": stream_export(
                conn,
                "SELECT * FROM performance_event WHERE venue_id IS NOT NULL AND TRIM(venue_id) != ''",
                out_dir / "relations_event_venue.jsonl.gz",
                rel_event_venue,
                limit,
            ),
        }
        field_rows = build_field_completeness(conn)
    finally:
        conn.close()

    field_count = write_jsonl(out_dir / "field_completeness.jsonl", field_rows)
    output_files = {name: payload for name, payload in exports.items()}
    node_counts = {name: payload["rows"] for name, payload in exports.items() if name.startswith("nodes_")}
    relation_counts = {name: payload["rows"] for name, payload in exports.items() if name.startswith("relations_")}
    public_leak_scan = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}
    for payload in exports.values():
        for key, value in payload["leak_scan"].items():
            public_leak_scan[key] += value
    failed_checks = []
    if any(public_leak_scan.values()):
        failed_checks.append("public_leak_scan_nonzero")
    if sum(relation_counts.values()) == 0:
        failed_checks.append("no_relations_exported")

    relation_rollup_rows = [
        {
            "schema_version": SCHEMA_VERSION + ".relation_type_rollup",
            "relation_bundle": name,
            "rows": count,
            "path": output_files[name]["path"],
            "sha256": output_files[name]["sha256"],
            "bytes": output_files[name]["bytes"],
        }
        for name, count in sorted(relation_counts.items())
    ]
    rollup_count = write_jsonl(out_dir / "relation_type_rollup.jsonl", relation_rollup_rows)

    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_full_relation_bundle_ready_local_only" if not failed_checks else "atlas_full_relation_bundle_failed_local_only",
        "failed_checks": failed_checks,
        "source_sqlite": str(sqlite_path),
        "source_sqlite_size": sqlite_path.stat().st_size,
        "source_sqlite_sha256": file_sha256(sqlite_path),
        "out_dir": str(out_dir),
        "report_md": str(report_path),
        "source_table_counts": source_counts,
        "node_counts": node_counts,
        "relation_counts": relation_counts,
        "derived_counts": {
            "total_node_rows": sum(node_counts.values()),
            "total_relation_rows": sum(relation_counts.values()),
            "field_completeness_rows": field_count,
            "relation_type_rollup_rows": rollup_count,
        },
        "public_leak_scan": public_leak_scan,
        "outputs": {
            "summary_json": str(out_dir / "atlas_full_relation_bundle_summary.json"),
            "field_completeness_jsonl": str(out_dir / "field_completeness.jsonl"),
            "relation_type_rollup_jsonl": str(out_dir / "relation_type_rollup.jsonl"),
            **{name: payload["path"] for name, payload in output_files.items()},
        },
        "output_files": output_files,
        "safety": {
            "read_only_sqlite": True,
            "report_only": True,
            "production_write_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "memory_write_executed": False,
            "network_call_executed": False,
            "credential_read_executed": False,
        },
        "stop_reason": "none" if not failed_checks else "relation_bundle_failed_checks",
        "wait_reason": "none",
    }
    write_json(out_dir / "atlas_full_relation_bundle_summary.json", summary)
    write_text(report_path, build_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit", type=int, default=None, help="Optional per-bundle row limit for tests/smoke only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_relation_bundle(args.sqlite, args.out_dir, args.report, args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if summary["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
