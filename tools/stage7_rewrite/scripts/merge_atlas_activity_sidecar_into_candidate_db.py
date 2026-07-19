#!/usr/bin/env python3
"""Cumulatively merge weekly activity source facts into a derived AtlasV2 DB.

The pointed AtlasV2 candidate is immutable.  This command first copies it with
SQLite's online backup API, writes only the ``atlas_activity_*`` source
namespace plus a small allow-list of ``build_metadata`` watermarks, verifies
the result, and only then atomically publishes a new candidate file.  Canonical,
search, graph, DJ, performance, and serving projection tables are read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


RAW_URL_RE = re.compile(r"https?://|www\.|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|qpic\.cn|openid", re.I)
SCHEMA_VERSION = "atlas_activity_candidate_db_merge.v2"
PROJECTION_STATUS = "source_namespace_only"
ALLOWED_METADATA_KEYS = {
    "atlas_activity_source_schema_version",
    "atlas_activity_projection_status",
    "atlas_activity_source_last_import_id",
    "atlas_activity_source_summary",
}
PROTECTED_TABLES = (
    "canonical_build_metadata",
    "activity_event_detail",
    "activity_evidence_ref",
    "performance_event",
    "dj_event",
    "dj_profile",
    "canonical_event",
    "canonical_event_member",
    "search_document",
    "graph_window_cache",
)
EVENT_SOURCE_COLUMNS = (
    "activity_event_id",
    "event_id",
    "publish_package",
    "title",
    "event_date_text_json",
    "event_date_start",
    "event_date_end",
    "event_time_text",
    "time_start",
    "time_end",
    "venue_name",
    "venue_id",
    "address",
    "city_key",
    "city_name",
    "lineup_artists_json",
    "music_styles_json",
    "genres_json",
    "price_json",
    "ticketing_text",
    "source_url_map_key",
    "source_url_hash",
    "source_token_hash",
    "source_article_json",
    "source_action_json",
    "raw_event_json",
    "generated_at",
)
EVIDENCE_SOURCE_COLUMNS = (
    "evidence_ref_id",
    "activity_event_id",
    "field_path",
    "field_value",
    "support_type",
    "source_kind",
    "source_url_map_key",
    "source_url_hash",
    "source_account_name",
    "source_published_at",
    "quote",
    "quote_policy",
    "ocr_span_id",
    "ocr_span_status",
    "confidence",
    "created_at",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_evidence_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def evidence_key(event_id: str, field_path: Any, field_value: Any, quote: Any) -> str:
    blob = "\x1f".join(
        (
            event_id.strip(),
            normalized_evidence_text(field_path),
            normalized_evidence_text(field_value),
            normalized_evidence_text(quote),
        )
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    )


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def count_table(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def schema_counts(conn: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int | None]:
    return {table: count_table(conn, table) if table_exists(conn, table) else None for table in tables}


def validate_base_schema(base_db: Path) -> None:
    conn = sqlite3.connect(f"file:{base_db.as_posix()}?mode=ro", uri=True)
    try:
        if not table_exists(conn, "build_metadata"):
            raise ValueError("base candidate is not the current AtlasV2 schema: build_metadata missing")
        if table_exists(conn, "metadata"):
            raise ValueError("legacy metadata schema is not accepted as an AtlasV2 serving candidate")
        if not any(table_exists(conn, table) for table in PROTECTED_TABLES):
            raise ValueError("base candidate has no protected AtlasV2 projection tables")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("base candidate PRAGMA quick_check failed")
    finally:
        conn.close()


def validate_sidecar_schema(sidecar_db: Path) -> None:
    conn = sqlite3.connect(f"file:{sidecar_db.as_posix()}?mode=ro", uri=True)
    try:
        for table, required in (
            ("activity_events", set(EVENT_SOURCE_COLUMNS)),
            ("evidence_refs", set(EVIDENCE_SOURCE_COLUMNS)),
        ):
            if not table_exists(conn, table):
                raise ValueError(f"invalid activity sidecar {sidecar_db}: {table} missing")
            missing = sorted(required - table_columns(conn, table))
            if missing:
                raise ValueError(f"invalid activity sidecar {sidecar_db}: {table} missing columns {missing}")
        duplicate_ids = conn.execute(
            "SELECT event_id FROM activity_events GROUP BY event_id HAVING count(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate_ids:
            raise ValueError(f"invalid activity sidecar {sidecar_db}: duplicate event_id={duplicate_ids[0]}")
        blank_id = conn.execute(
            "SELECT count(*) FROM activity_events WHERE event_id IS NULL OR trim(event_id)=''"
        ).fetchone()[0]
        if blank_id:
            raise ValueError(f"invalid activity sidecar {sidecar_db}: blank event_id rows={blank_id}")
    finally:
        conn.close()


def source_sidecar_counts(sidecar_db: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{sidecar_db.as_posix()}?mode=ro", uri=True)
    try:
        return {
            "activity_events": count_table(conn, "activity_events"),
            "evidence_refs": count_table(conn, "evidence_refs"),
        }
    finally:
        conn.close()


def backup_sqlite(base_db: Path, building_db: Path) -> None:
    source = sqlite3.connect(f"file:{base_db.as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(building_db)
    try:
        source.backup(destination, pages=8192)
        destination.commit()
    finally:
        destination.close()
        source.close()


def create_namespace_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS atlas_activity_events (
          event_id TEXT PRIMARY KEY,
          activity_event_id TEXT NOT NULL,
          publish_package TEXT,
          title TEXT,
          event_date_text_json TEXT,
          event_date_start TEXT,
          event_date_end TEXT,
          event_time_text TEXT,
          time_start TEXT,
          time_end TEXT,
          venue_name TEXT,
          venue_id TEXT,
          address TEXT,
          city_key TEXT,
          city_name TEXT,
          lineup_artists_json TEXT,
          music_styles_json TEXT,
          genres_json TEXT,
          price_json TEXT,
          ticketing_text TEXT,
          source_url_map_key TEXT,
          source_url_hash TEXT,
          source_token_hash TEXT,
          source_article_json TEXT,
          source_action_json TEXT,
          raw_event_json TEXT,
          generated_at TEXT,
          first_publish_package TEXT NOT NULL,
          latest_publish_package TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          latest_source_generated_at TEXT,
          last_import_id TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_atlas_activity_events_activity_id
          ON atlas_activity_events(activity_event_id);
        CREATE INDEX IF NOT EXISTS idx_atlas_activity_events_date_city
          ON atlas_activity_events(event_date_start, city_key);

        CREATE TABLE IF NOT EXISTS atlas_activity_evidence_refs (
          evidence_key TEXT PRIMARY KEY,
          event_id TEXT NOT NULL,
          evidence_ref_id TEXT NOT NULL,
          activity_event_id TEXT NOT NULL,
          field_path TEXT,
          field_value TEXT,
          support_type TEXT,
          source_kind TEXT,
          source_url_map_key TEXT,
          source_url_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          quote TEXT,
          quote_policy TEXT,
          ocr_span_id TEXT,
          ocr_span_status TEXT,
          confidence REAL,
          created_at TEXT,
          first_publish_package TEXT NOT NULL,
          latest_publish_package TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          last_import_id TEXT NOT NULL,
          FOREIGN KEY(event_id) REFERENCES atlas_activity_events(event_id)
        );
        CREATE INDEX IF NOT EXISTS idx_atlas_activity_evidence_event
          ON atlas_activity_evidence_refs(event_id);
        CREATE INDEX IF NOT EXISTS idx_atlas_activity_evidence_field
          ON atlas_activity_evidence_refs(field_path);

        CREATE TABLE IF NOT EXISTS atlas_activity_import_watermark (
          import_id TEXT PRIMARY KEY,
          imported_at TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          projection_status TEXT NOT NULL,
          canonical_projection_updated INTEGER NOT NULL CHECK(canonical_projection_updated = 0),
          base_candidate_sha256 TEXT,
          source_hashes_json TEXT NOT NULL,
          sidecar_paths_json TEXT NOT NULL,
          sidecar_counts_json TEXT NOT NULL,
          candidate_counts_json TEXT NOT NULL
        );
        """
    )
    expected = {
        "atlas_activity_events": {"event_id", "first_publish_package", "latest_publish_package", "last_import_id"},
        "atlas_activity_evidence_refs": {"evidence_key", "event_id", "last_import_id"},
        "atlas_activity_import_watermark": {"import_id", "projection_status", "canonical_projection_updated"},
    }
    for table, required in expected.items():
        missing = required - table_columns(conn, table)
        if missing:
            raise ValueError(f"existing {table} schema is incompatible with cumulative merge: {sorted(missing)}")


def write_authorizer(action: int, arg1: str | None, _arg2: str | None, _db: str | None, _source: str | None) -> int:
    write_actions = {
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
    }
    if action in write_actions:
        table = str(arg1 or "")
        if table == "build_metadata" or table.startswith("atlas_activity_"):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _rich_update(column: str) -> str:
    return (
        f"{column}=CASE WHEN excluded.{column} IS NULL OR trim(CAST(excluded.{column} AS TEXT))='' "
        f"OR trim(CAST(excluded.{column} AS TEXT)) IN ('[]','{{}}','null') "
        f"THEN atlas_activity_events.{column} ELSE excluded.{column} END"
    )


EVENT_PAYLOAD_COLUMNS = tuple(
    column for column in EVENT_SOURCE_COLUMNS if column not in {"event_id", "activity_event_id", "publish_package"}
)


def merge_one_sidecar(
    conn: sqlite3.Connection,
    sidecar_db: Path,
    *,
    import_id: str,
    imported_at: str,
) -> tuple[set[str], int]:
    source = sqlite3.connect(f"file:{sidecar_db.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        events = source.execute(
            f"SELECT {', '.join(EVENT_SOURCE_COLUMNS)} FROM activity_events ORDER BY event_id"
        ).fetchall()
        activity_to_event = {str(row["activity_event_id"]): str(row["event_id"]).strip() for row in events}
        event_to_package = {
            str(row["event_id"]).strip(): str(row["publish_package"] or "").strip() or "unknown"
            for row in events
        }
        event_ids = set(activity_to_event.values())
        event_insert_columns = (
            "event_id",
            "activity_event_id",
            "publish_package",
            *EVENT_PAYLOAD_COLUMNS,
            "first_publish_package",
            "latest_publish_package",
            "first_seen_at",
            "last_seen_at",
            "latest_source_generated_at",
            "last_import_id",
        )
        update_parts = [
            "activity_event_id=excluded.activity_event_id",
            "publish_package=excluded.publish_package",
            *(_rich_update(column) for column in EVENT_PAYLOAD_COLUMNS),
            "latest_publish_package=excluded.latest_publish_package",
            "last_seen_at=excluded.last_seen_at",
            "latest_source_generated_at=excluded.latest_source_generated_at",
            "last_import_id=excluded.last_import_id",
        ]
        event_sql = (
            f"INSERT INTO atlas_activity_events ({', '.join(event_insert_columns)}) "
            f"VALUES ({', '.join('?' for _ in event_insert_columns)}) "
            f"ON CONFLICT(event_id) DO UPDATE SET {', '.join(update_parts)}"
        )
        for row in events:
            event_id = str(row["event_id"]).strip()
            package = str(row["publish_package"] or "").strip() or "unknown"
            generated_at = str(row["generated_at"] or "").strip()
            values = [
                event_id,
                str(row["activity_event_id"]),
                package,
                *(row[column] for column in EVENT_PAYLOAD_COLUMNS),
                package,
                package,
                imported_at,
                imported_at,
                generated_at,
                import_id,
            ]
            conn.execute(event_sql, values)

        evidence_rows = source.execute(
            f"SELECT {', '.join(EVIDENCE_SOURCE_COLUMNS)} FROM evidence_refs ORDER BY evidence_ref_id"
        ).fetchall()
        evidence_sql = """
            INSERT INTO atlas_activity_evidence_refs (
              evidence_key, event_id, evidence_ref_id, activity_event_id,
              field_path, field_value, support_type, source_kind,
              source_url_map_key, source_url_hash, source_account_name,
              source_published_at, quote, quote_policy, ocr_span_id,
              ocr_span_status, confidence, created_at, first_publish_package,
              latest_publish_package, first_seen_at, last_seen_at, last_import_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(evidence_key) DO UPDATE SET
              evidence_ref_id=excluded.evidence_ref_id,
              activity_event_id=excluded.activity_event_id,
              support_type=excluded.support_type,
              source_kind=excluded.source_kind,
              source_url_map_key=excluded.source_url_map_key,
              source_url_hash=excluded.source_url_hash,
              source_account_name=excluded.source_account_name,
              source_published_at=excluded.source_published_at,
              quote_policy=excluded.quote_policy,
              ocr_span_id=excluded.ocr_span_id,
              ocr_span_status=excluded.ocr_span_status,
              confidence=excluded.confidence,
              created_at=excluded.created_at,
              latest_publish_package=excluded.latest_publish_package,
              last_seen_at=excluded.last_seen_at,
              last_import_id=excluded.last_import_id
        """
        for row in evidence_rows:
            activity_event_id = str(row["activity_event_id"] or "")
            event_id = activity_to_event.get(activity_event_id)
            if not event_id:
                raise ValueError(
                    f"invalid activity sidecar {sidecar_db}: evidence references unknown activity_event_id={activity_event_id}"
                )
            package = event_to_package[event_id]
            key = evidence_key(event_id, row["field_path"], row["field_value"], row["quote"])
            conn.execute(
                evidence_sql,
                (
                    key,
                    event_id,
                    str(row["evidence_ref_id"]),
                    activity_event_id,
                    *(row[column] for column in EVIDENCE_SOURCE_COLUMNS[2:]),
                    package,
                    package,
                    imported_at,
                    imported_at,
                    import_id,
                ),
            )
        return event_ids, len(evidence_rows)
    finally:
        source.close()


def candidate_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "activity_events": count_table(conn, "atlas_activity_events"),
        "evidence_refs": count_table(conn, "atlas_activity_evidence_refs"),
        "watermarks": count_table(conn, "atlas_activity_import_watermark"),
    }


def scan_activity_table_leaks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for table in ("atlas_activity_events", "atlas_activity_evidence_refs"):
        columns = [
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})")
            if str(row[2]).upper() in {"TEXT", ""}
        ]
        for column in columns:
            for rowid, value in conn.execute(
                f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL"
            ):
                if isinstance(value, str) and RAW_URL_RE.search(value):
                    hits.append({"table": table, "column": column, "rowid": rowid})
                    break
    return hits


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Atlas Activity Source Namespace Merge",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- projection_status: `{report['projection_status']}`",
        f"- base_db: `{report['base_db']}`",
        f"- out_db: `{report['out_db']}`",
        f"- import_id: `{report['import_id']}`",
        f"- protected_tables_unchanged: `{report['protected_tables_unchanged']}`",
        f"- quick_check: `{report['quick_check']}`",
        "",
        "## Counts",
        "",
        f"- activity_events: `{report['candidate_counts']['activity_events']}`",
        f"- evidence_refs: `{report['candidate_counts']['evidence_refs']}`",
        f"- watermarks: `{report['candidate_counts']['watermarks']}`",
        f"- raw_url_leak_hits: `{len(report['safety']['raw_url_leak_hits'])}`",
        "",
        "Canonical, search, graph, DJ, performance, and serving projection tables were not updated.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def build_activity_candidate_db(
    base_db: Path,
    activity_sidecar_dbs: Sequence[Path] | Path,
    out_db: Path,
    *,
    sidecar_summary_path: Path | None = None,
    report_dir: Path | None = None,
    import_id: str = "",
    source_hashes: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    del sidecar_summary_path  # v1 compatibility; v2 watermarks come from explicit hashes and DB contents.
    if overwrite:
        raise ValueError("overwrite is forbidden; AtlasV2 pointed candidates are immutable")
    started = time.time()
    base_db = Path(base_db)
    out_db = Path(out_db)
    sidecars = [Path(activity_sidecar_dbs)] if isinstance(activity_sidecar_dbs, (str, Path)) else [Path(p) for p in activity_sidecar_dbs]
    if not base_db.is_file():
        raise FileNotFoundError(base_db)
    if not sidecars:
        raise ValueError("at least one activity sidecar is required")
    for sidecar in sidecars:
        if not sidecar.is_file():
            raise FileNotFoundError(sidecar)
        validate_sidecar_schema(sidecar)
    validate_base_schema(base_db)
    if out_db.resolve() == base_db.resolve():
        raise ValueError("out_db must be a new derived candidate path, not base_db")
    if out_db.exists():
        raise FileExistsError(out_db)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    building_db = out_db.with_name(out_db.name + ".building")
    if building_db.exists():
        raise FileExistsError(f"stale building candidate requires review: {building_db}")

    imported_at = utc_now()
    effective_import_id = import_id.strip() or f"activity-source-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    base_sha256 = file_sha256(base_db)
    sidecar_counts = {str(path): source_sidecar_counts(path) for path in sidecars}
    backup_sqlite(base_db, building_db)

    conn = sqlite3.connect(building_db)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        protected_before = schema_counts(conn, PROTECTED_TABLES)
        conn.execute("BEGIN IMMEDIATE")
        create_namespace_schema(conn)
        conn.set_authorizer(write_authorizer)
        current_event_ids: set[str] = set()
        input_evidence_rows = 0
        for sidecar in sidecars:
            event_ids, evidence_rows = merge_one_sidecar(
                conn,
                sidecar,
                import_id=effective_import_id,
                imported_at=imported_at,
            )
            current_event_ids.update(event_ids)
            input_evidence_rows += evidence_rows
        counts_before_watermark = candidate_counts(conn)
        source_hash_payload = dict(source_hashes or {})
        watermark = (
            effective_import_id,
            imported_at,
            SCHEMA_VERSION,
            PROJECTION_STATUS,
            0,
            base_sha256,
            json.dumps(source_hash_payload, ensure_ascii=False, sort_keys=True),
            json.dumps([str(path) for path in sidecars], ensure_ascii=False),
            json.dumps(sidecar_counts, ensure_ascii=False, sort_keys=True),
            json.dumps(counts_before_watermark, ensure_ascii=False, sort_keys=True),
        )
        conn.execute(
            "INSERT INTO atlas_activity_import_watermark VALUES (?,?,?,?,?,?,?,?,?,?)",
            watermark,
        )
        metadata = {
            "atlas_activity_source_schema_version": SCHEMA_VERSION,
            "atlas_activity_projection_status": PROJECTION_STATUS,
            "atlas_activity_source_last_import_id": effective_import_id,
            "atlas_activity_source_summary": json.dumps(
                {
                    "import_id": effective_import_id,
                    "imported_at": imported_at,
                    "sidecar_count": len(sidecars),
                    "input_unique_events": len(current_event_ids),
                    "input_evidence_rows": input_evidence_rows,
                    "projection_status": PROJECTION_STATUS,
                    "canonical_projection_updated": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
        if set(metadata) != ALLOWED_METADATA_KEYS:
            raise AssertionError("build_metadata write allow-list drift")
        conn.executemany(
            "INSERT INTO build_metadata(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            metadata.items(),
        )
        conn.commit()
        conn.set_authorizer(None)

        protected_after = schema_counts(conn, PROTECTED_TABLES)
        protected_unchanged = protected_before == protected_after
        merged_counts = candidate_counts(conn)
        present_count = conn.execute(
            f"SELECT count(*) FROM atlas_activity_events WHERE event_id IN ({','.join('?' for _ in current_event_ids)})",
            sorted(current_event_ids),
        ).fetchone()[0] if current_event_ids else 0
        current_present = present_count == len(current_event_ids)
        unique_event_count = conn.execute("SELECT count(DISTINCT event_id) FROM atlas_activity_events").fetchone()[0]
        unique_events_ok = unique_event_count == merged_counts["activity_events"]
        unique_evidence_count = conn.execute(
            "SELECT count(DISTINCT evidence_key) FROM atlas_activity_evidence_refs"
        ).fetchone()[0]
        unique_evidence_ok = unique_evidence_count == merged_counts["evidence_refs"]
        leak_hits = scan_activity_table_leaks(conn)
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
    except Exception:
        try:
            conn.rollback()
        finally:
            conn.close()
        raise
    else:
        conn.close()

    gates_ok = all(
        (
            protected_unchanged,
            current_present,
            unique_events_ok,
            unique_evidence_ok,
            not leak_hits,
            quick_check == "ok",
        )
    )
    if not gates_ok:
        raise ValueError(
            "Atlas activity candidate gates failed; building file retained for audit: "
            f"protected={protected_unchanged} current={current_present} unique_events={unique_events_ok} "
            f"unique_evidence={unique_evidence_ok} leaks={len(leak_hits)} quick_check={quick_check}"
        )

    candidate_sha256 = file_sha256(building_db)
    os.replace(building_db, out_db)
    readback_sha256 = file_sha256(out_db)
    if readback_sha256 != candidate_sha256:
        raise ValueError("candidate hash changed after atomic publish")

    generated_at = utc_now()
    report_root = report_dir or out_db.parent
    summary_json = report_root / "activity_candidate_db_merge_summary.json"
    summary_md = report_root / "activity_candidate_db_merge_summary.md"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": "activity_source_namespace_merged_into_derived_candidate_db",
        "projection_status": PROJECTION_STATUS,
        "canonical_projection_updated": False,
        "import_id": effective_import_id,
        "base_db": str(base_db),
        "base_candidate_sha256": base_sha256,
        "activity_sidecars": [str(path) for path in sidecars],
        "out_db": str(out_db),
        "candidate_sha256": candidate_sha256,
        "candidate_size": out_db.stat().st_size,
        "copied_base_db": True,
        "copy_method": "sqlite3.Connection.backup",
        "atomic_publish": True,
        "elapsed_sec": round(time.time() - started, 3),
        "sidecar_counts": sidecar_counts,
        "candidate_counts": merged_counts,
        "source_hashes": dict(source_hashes or {}),
        "current_event_ids_present": current_present,
        "unique_event_ids": unique_events_ok,
        "unique_evidence_keys": unique_evidence_ok,
        "protected_table_counts_before": protected_before,
        "protected_table_counts_after": protected_after,
        "protected_tables_unchanged": protected_unchanged,
        "quick_check": quick_check,
        "safety": {
            "source_db_mutated": False,
            "raw_url_leak_hits": leak_hits,
            "prov_activities_copied": False,
            "overwrite_allowed": False,
        },
        "outputs": {
            "summary_json": str(summary_json),
            "summary_md": str(summary_md),
        },
    }
    write_json(summary_json, report)
    write_markdown(summary_md, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-db", type=Path, required=True)
    parser.add_argument("--activity-sidecar-db", type=Path, action="append", required=True)
    parser.add_argument("--out-db", type=Path, required=True)
    parser.add_argument("--sidecar-summary", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--import-id", default="")
    parser.add_argument("--source-hashes-json", type=Path, default=None)
    parser.add_argument("--merge-mode", choices=["cumulative-source-namespace"], default="cumulative-source-namespace")
    parser.add_argument("--identity-key", choices=["event_id"], default="event_id")
    parser.add_argument("--preserve-canonical", action="store_true")
    parser.add_argument("--overwrite", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.preserve_canonical:
        parser.error("--preserve-canonical is required")
    source_hashes = read_json(args.source_hashes_json, {}) if args.source_hashes_json else {}
    report = build_activity_candidate_db(
        args.base_db,
        args.activity_sidecar_db,
        args.out_db,
        sidecar_summary_path=args.sidecar_summary,
        report_dir=args.report_dir,
        import_id=args.import_id,
        source_hashes=source_hashes,
        overwrite=args.overwrite,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
