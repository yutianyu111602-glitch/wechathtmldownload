#!/usr/bin/env python3
"""Materialize canonical Atlas projections into a candidate serving copy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = "atlas_canonical_serving.v1"
RAW_TABLES = ("dj_profile", "dj_event", "performance_event")
MATERIALIZED_TABLES = (
    "canonical_dj_profile",
    "canonical_event",
    "canonical_event_member",
    "canonical_dj_event",
    "canonical_event_merge_review_candidate",
    "dj_identity_redirect",
    "dj_identity_review_candidate",
    "identity_build_metadata",
    "venue_identity_redirect",
    "venue_identity_review_candidate",
    "venue_identity_build_metadata",
    "canonical_build_metadata",
)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1",
        (table,),
    ).fetchone() is not None


def _require_tables(con: sqlite3.Connection, tables: Iterable[str], label: str) -> None:
    missing = [table for table in tables if not _table_exists(con, table)]
    if missing:
        raise ValueError(f"{label} is missing required tables: {', '.join(missing)}")


def _counts(con: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    return {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


def _copy_rows(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    select_sql: str,
    insert_sql: str,
    batch_size: int = 10_000,
) -> int:
    cursor = source.execute(select_sql)
    copied = 0
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        target.executemany(insert_sql, [tuple(row) for row in rows])
        copied += len(rows)
    return copied


def _resolve_mapping(mapping: dict[str, str], label: str) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for source in mapping:
        current = source
        seen: set[str] = set()
        while current in mapping:
            if current in seen:
                raise ValueError(f"{label} redirect cycle detected at {current}")
            seen.add(current)
            current = mapping[current]
        resolved[source] = current
    return resolved


def _aliases(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _first(values: Iterable[str | None]) -> str | None:
    present = sorted(value for value in values if value)
    return present[0] if present else None


def _last(values: Iterable[str | None]) -> str | None:
    present = sorted(value for value in values if value)
    return present[-1] if present else None


def _unique_normalized_names(
    profiles: dict[str, dict], canonical_subject_ids: set[str]
) -> dict[str, str]:
    groups: dict[str, list[str]] = defaultdict(list)
    for dj_id, profile in profiles.items():
        groups[str(profile["normalized_name"] or "")].append(dj_id)

    used: set[str] = set()
    result: dict[str, str] = {}
    for base, dj_ids in sorted(groups.items()):
        ranked = sorted(
            dj_ids,
            key=lambda dj_id: (
                int(dj_id not in canonical_subject_ids),
                -int(profiles[dj_id].get("event_count") or 0),
                dj_id,
            ),
        )
        for index, dj_id in enumerate(ranked):
            candidate = base if index == 0 and base else ""
            if not candidate or candidate in used:
                suffix = hashlib.sha256(dj_id.encode("utf-8")).hexdigest()[:10]
                stem = base or "unnamed"
                candidate = f"{stem}--{suffix}"
                counter = 2
                while candidate in used:
                    candidate = f"{stem}--{suffix}-{counter}"
                    counter += 1
            used.add(candidate)
            result[dj_id] = candidate
    return result


def _create_schema(con: sqlite3.Connection) -> None:
    for table in MATERIALIZED_TABLES:
        con.execute(f"DROP TABLE IF EXISTS {table}")
    con.executescript(
        """
        CREATE TABLE canonical_event (
          canonical_event_id TEXT PRIMARY KEY,
          event_date TEXT,
          start_time TEXT,
          venue_id TEXT,
          venue_name TEXT,
          city_norm TEXT,
          title_norm TEXT,
          title_display TEXT,
          merge_key_strong TEXT,
          merge_key_medium TEXT,
          confidence REAL,
          status TEXT,
          member_count INTEGER,
          created_at TEXT,
          merge_version TEXT
        );
        CREATE TABLE canonical_event_member (
          canonical_event_id TEXT NOT NULL,
          mention_id TEXT,
          legacy_event_id TEXT NOT NULL,
          source_article_id TEXT,
          match_rule TEXT,
          match_confidence REAL,
          is_primary INTEGER,
          provenance_rank INTEGER
        );
        CREATE TABLE canonical_dj_event (
          dj_id TEXT NOT NULL,
          canonical_event_id TEXT NOT NULL,
          role TEXT,
          role_confidence REAL,
          source_count INTEGER,
          first_source_article_id TEXT,
          last_seen_at TEXT,
          PRIMARY KEY(dj_id,canonical_event_id)
        );
        CREATE TABLE canonical_event_merge_review_candidate (
          canonical_event_id_a TEXT,
          canonical_event_id_b TEXT,
          event_date TEXT,
          venue_id TEXT,
          title_display_a TEXT,
          title_display_b TEXT,
          title_similarity REAL,
          review_state TEXT
        );
        CREATE TABLE dj_identity_redirect (
          source_dj_id TEXT PRIMARY KEY,
          canonical_dj_id TEXT NOT NULL,
          decision_method TEXT NOT NULL,
          decision_reason TEXT NOT NULL,
          confidence REAL NOT NULL,
          decided_at TEXT NOT NULL
        );
        CREATE TABLE dj_identity_review_candidate (
          source_dj_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          city_primary TEXT,
          candidate_dj_id TEXT,
          candidate_city TEXT,
          reason TEXT NOT NULL,
          review_state TEXT NOT NULL
        );
        CREATE TABLE identity_build_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE venue_identity_redirect (
          source_venue_id TEXT PRIMARY KEY,
          source_city TEXT NOT NULL,
          source_city_key TEXT NOT NULL,
          canonical_venue_id TEXT NOT NULL,
          canonical_city TEXT NOT NULL,
          canonical_city_key TEXT NOT NULL,
          decision_method TEXT NOT NULL,
          decision_reason TEXT NOT NULL,
          confidence REAL NOT NULL,
          decided_at TEXT NOT NULL
        );
        CREATE TABLE venue_identity_review_candidate (
          source_venue_id TEXT NOT NULL,
          candidate_venue_id TEXT NOT NULL,
          city TEXT,
          source_name TEXT NOT NULL,
          candidate_name TEXT NOT NULL,
          reason TEXT NOT NULL,
          review_state TEXT NOT NULL,
          PRIMARY KEY(source_venue_id,candidate_venue_id)
        );
        CREATE TABLE venue_identity_build_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE canonical_dj_profile (
          dj_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          city_primary TEXT,
          source_article_count INTEGER NOT NULL,
          event_count INTEGER NOT NULL,
          venue_count INTEGER NOT NULL,
          collaborator_count INTEGER NOT NULL,
          organization_count INTEGER NOT NULL,
          media_count INTEGER NOT NULL,
          first_seen_at TEXT,
          last_seen_at TEXT,
          confidence REAL NOT NULL
        );
        CREATE TABLE canonical_build_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE INDEX idx_canonical_event_date ON canonical_event(event_date DESC,canonical_event_id);
        CREATE INDEX idx_canonical_event_venue ON canonical_event(venue_id,event_date DESC);
        CREATE UNIQUE INDEX idx_canonical_event_member_legacy ON canonical_event_member(legacy_event_id);
        CREATE INDEX idx_canonical_event_member_event ON canonical_event_member(canonical_event_id);
        CREATE INDEX idx_canonical_dj_event_event ON canonical_dj_event(canonical_event_id,dj_id);
        CREATE INDEX idx_dj_identity_redirect_canonical ON dj_identity_redirect(canonical_dj_id);
        CREATE INDEX idx_venue_identity_redirect_canonical ON venue_identity_redirect(canonical_venue_id);
        """
    )


def _copy_canonical_tables(
    canonical: sqlite3.Connection,
    target: sqlite3.Connection,
) -> dict[str, int]:
    copied = {}
    copied["canonical_event"] = _copy_rows(
        canonical,
        target,
        "SELECT canonical_event_id,event_date,start_time,venue_id,venue_name,city_norm,title_norm,title_display,merge_key_strong,merge_key_medium,confidence,status,member_count,created_at,merge_version FROM canonical_event",
        "INSERT INTO canonical_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    )
    copied["canonical_event_member"] = _copy_rows(
        canonical,
        target,
        "SELECT canonical_event_id,mention_id,legacy_event_id,source_article_id,match_rule,match_confidence,is_primary,provenance_rank FROM canonical_event_member",
        "INSERT INTO canonical_event_member VALUES (?,?,?,?,?,?,?,?)",
    )
    copied["canonical_dj_event"] = _copy_rows(
        canonical,
        target,
        "SELECT dj_id,canonical_event_id,role,role_confidence,source_count,first_source_article_id,last_seen_at FROM canonical_dj_event",
        "INSERT INTO canonical_dj_event VALUES (?,?,?,?,?,?,?)",
    )
    copied["canonical_event_merge_review_candidate"] = _copy_rows(
        canonical,
        target,
        "SELECT canonical_event_id_a,canonical_event_id_b,event_date,venue_id,title_display_a,title_display_b,title_similarity,review_state FROM canonical_event_merge_review_candidate",
        "INSERT INTO canonical_event_merge_review_candidate VALUES (?,?,?,?,?,?,?,?)",
    )
    return copied


def _copy_identity_tables(
    identity: sqlite3.Connection,
    target: sqlite3.Connection,
) -> dict[str, int]:
    copied = {}
    redirect_rows = list(
        identity.execute(
            "SELECT source_dj_id,canonical_dj_id,decision_method,decision_reason,"
            "confidence,decided_at FROM dj_identity_redirect ORDER BY source_dj_id"
        )
    )
    terminal_targets = _resolve_mapping(
        {row["source_dj_id"]: row["canonical_dj_id"] for row in redirect_rows},
        "DJ",
    )
    target.executemany(
        "INSERT INTO dj_identity_redirect VALUES (?,?,?,?,?,?)",
        [
            (
                row["source_dj_id"],
                terminal_targets[row["source_dj_id"]],
                row["decision_method"],
                row["decision_reason"],
                row["confidence"],
                row["decided_at"],
            )
            for row in redirect_rows
        ],
    )
    copied["dj_identity_redirect"] = len(redirect_rows)
    copied["dj_identity_review_candidate"] = _copy_rows(
        identity,
        target,
        "SELECT source_dj_id,display_name,normalized_name,city_primary,candidate_dj_id,candidate_city,reason,review_state FROM dj_identity_review_candidate",
        "INSERT INTO dj_identity_review_candidate VALUES (?,?,?,?,?,?,?,?)",
    )
    copied["identity_build_metadata"] = _copy_rows(
        identity,
        target,
        "SELECT key,value FROM identity_build_metadata",
        "INSERT INTO identity_build_metadata VALUES (?,?)",
    )
    return copied


def _copy_venue_tables(
    venue: sqlite3.Connection,
    target: sqlite3.Connection,
) -> dict[str, int]:
    copied = {}
    copied["venue_identity_redirect"] = _copy_rows(
        venue,
        target,
        "SELECT source_venue_id,source_city,source_city_key,canonical_venue_id,canonical_city,canonical_city_key,decision_method,decision_reason,confidence,decided_at FROM venue_identity_redirect",
        "INSERT INTO venue_identity_redirect VALUES (?,?,?,?,?,?,?,?,?,?)",
    )
    copied["venue_identity_review_candidate"] = _copy_rows(
        venue,
        target,
        "SELECT source_venue_id,candidate_venue_id,city,source_name,candidate_name,reason,review_state FROM venue_identity_review_candidate",
        "INSERT INTO venue_identity_review_candidate VALUES (?,?,?,?,?,?,?)",
    )
    copied["venue_identity_build_metadata"] = _copy_rows(
        venue,
        target,
        "SELECT key,value FROM venue_identity_build_metadata",
        "INSERT INTO venue_identity_build_metadata VALUES (?,?)",
    )
    return copied


def _dict_counts(con: sqlite3.Connection, sql: str) -> dict[str, int]:
    return {row[0]: int(row[1] or 0) for row in con.execute(sql)}


def _materialize_profiles(con: sqlite3.Connection) -> dict[str, int]:
    raw_profiles = {
        row["dj_id"]: dict(row)
        for row in con.execute(
            """
            SELECT dj_id,display_name,normalized_name,aliases_json,city_primary,
                   source_article_count,event_count,venue_count,collaborator_count,
                   organization_count,media_count,first_seen_at,last_seen_at,confidence
              FROM dj_profile
             ORDER BY dj_id
            """
        )
    }
    raw_redirects = dict(
        con.execute("SELECT source_dj_id,canonical_dj_id FROM dj_identity_redirect")
    )
    redirects = _resolve_mapping(raw_redirects, "DJ")
    for source, target in redirects.items():
        if source not in raw_profiles or target not in raw_profiles:
            raise ValueError(f"DJ redirect is not covered by raw profiles: {source} -> {target}")

    aggregates: dict[str, dict] = {}
    for dj_id, profile in raw_profiles.items():
        target_id = redirects.get(dj_id, dj_id)
        aggregate = aggregates.setdefault(
            target_id,
            {
                "profiles": [],
                "aliases": set(),
            },
        )
        aggregate["profiles"].append(profile)
        aggregate["aliases"].update(_aliases(profile["aliases_json"]))
        aggregate["aliases"].add(str(profile["display_name"] or "").strip())
        if profile["normalized_name"] != raw_profiles[target_id]["normalized_name"]:
            aggregate["aliases"].add(str(profile["normalized_name"] or "").strip())

    retained = {dj_id: raw_profiles[dj_id] for dj_id in aggregates}
    canonical_subject_ids = {
        row[0]
        for row in con.execute(
            "SELECT subject_id FROM canonical_subject WHERE subject_type='dj'"
        )
    } if _table_exists(con, "canonical_subject") else set()
    normalized_names = _unique_normalized_names(retained, canonical_subject_ids)

    con.execute(
        "CREATE TEMP TABLE canonical_dj_identity_map(raw_dj_id TEXT PRIMARY KEY,canonical_dj_id TEXT NOT NULL)"
    )
    con.executemany(
        "INSERT INTO canonical_dj_identity_map VALUES (?,?)",
        [(dj_id, redirects.get(dj_id, dj_id)) for dj_id in sorted(raw_profiles)],
    )
    source_counts = _dict_counts(
        con,
        """
        SELECT map.canonical_dj_id,COUNT(DISTINCT NULLIF(event.source_ref_id,''))
          FROM dj_event event
          JOIN canonical_dj_identity_map map ON map.raw_dj_id=event.dj_id
         GROUP BY map.canonical_dj_id
        """,
    )
    event_counts = _dict_counts(
        con,
        "SELECT dj_id,COUNT(DISTINCT canonical_event_id) FROM canonical_dj_event GROUP BY dj_id",
    )
    venue_counts = _dict_counts(
        con,
        """
        SELECT dj.dj_id,COUNT(DISTINCT NULLIF(event.venue_id,''))
          FROM canonical_dj_event dj
          JOIN canonical_event event USING(canonical_event_id)
         GROUP BY dj.dj_id
        """,
    )
    collaborator_counts: dict[str, int] = {}
    if _table_exists(con, "dj_relation_rollup"):
        collaborator_counts = _dict_counts(
            con,
            """
            SELECT source_map.canonical_dj_id,COUNT(DISTINCT target_map.canonical_dj_id)
              FROM dj_relation_rollup relation
              JOIN canonical_dj_identity_map source_map ON source_map.raw_dj_id=relation.src_dj_id
              JOIN canonical_dj_identity_map target_map ON target_map.raw_dj_id=relation.dst_dj_id
             WHERE source_map.canonical_dj_id<>target_map.canonical_dj_id
             GROUP BY source_map.canonical_dj_id
            """,
        )
    organization_counts: dict[str, int] = {}
    if _table_exists(con, "dj_org_rollup"):
        organization_counts = _dict_counts(
            con,
            """
            SELECT map.canonical_dj_id,COUNT(DISTINCT relation.org_id)
              FROM dj_org_rollup relation
              JOIN canonical_dj_identity_map map ON map.raw_dj_id=relation.dj_id
             GROUP BY map.canonical_dj_id
            """,
        )

    rows = []
    for dj_id in sorted(retained):
        base = raw_profiles[dj_id]
        aggregate = aggregates[dj_id]
        members = aggregate["profiles"]
        rows.append(
            (
                dj_id,
                base["display_name"],
                normalized_names[dj_id],
                json.dumps(sorted(alias for alias in aggregate["aliases"] if alias), ensure_ascii=False),
                base["city_primary"],
                source_counts.get(dj_id, 0),
                event_counts.get(dj_id, 0),
                venue_counts.get(dj_id, 0),
                collaborator_counts.get(dj_id, 0),
                organization_counts.get(dj_id, 0),
                max(int(member["media_count"] or 0) for member in members),
                _first(member["first_seen_at"] for member in members),
                _last(member["last_seen_at"] for member in members),
                max(float(member["confidence"] or 0) for member in members),
            )
        )
    con.executemany(
        "INSERT INTO canonical_dj_profile VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.execute(
        "CREATE UNIQUE INDEX idx_canonical_dj_normalized ON canonical_dj_profile(normalized_name)"
    )
    con.execute(
        "CREATE INDEX idx_canonical_dj_rank ON canonical_dj_profile(event_count DESC,dj_id ASC)"
    )
    dangling = con.execute(
        """
        SELECT COUNT(*)
          FROM canonical_dj_event event
          LEFT JOIN canonical_dj_profile profile ON profile.dj_id=event.dj_id
         WHERE profile.dj_id IS NULL
        """
    ).fetchone()[0]
    if dangling:
        raise ValueError(f"canonical_dj_event has {dangling} DJs missing from canonical_dj_profile")
    return {
        "raw_profiles": len(raw_profiles),
        "redirect_sources": len(redirects),
        "canonical_profiles": len(rows),
        "normalized_name_splits": sum(
            normalized_names[dj_id] != str(retained[dj_id]["normalized_name"] or "")
            for dj_id in retained
        ),
    }


def _copy_metadata(
    target: sqlite3.Connection,
    canonical: sqlite3.Connection,
    identity: sqlite3.Connection,
    venue: sqlite3.Connection,
    materialized_at: str,
) -> None:
    rows = {
        "schema_version": SCHEMA_VERSION,
        "materialized_at": materialized_at,
    }
    for prefix, source, table in (
        ("canonical", canonical, "build_metadata"),
        ("identity", identity, "identity_build_metadata"),
        ("venue", venue, "venue_identity_build_metadata"),
    ):
        if not _table_exists(source, table):
            continue
        for key, value in source.execute(f"SELECT key,value FROM {table}"):
            rows[f"{prefix}.{key}"] = str(value)
    target.executemany(
        "INSERT INTO canonical_build_metadata(key,value) VALUES (?,?)",
        sorted(rows.items()),
    )


def materialize(
    candidate_serving_db: Path | str,
    canonical_events_db: Path | str,
    identity_db: Path | str,
    venue_redirect_db: Path | str,
    *,
    out_db: Path | str | None = None,
    report_path: Path | str | None = None,
    replace: bool = False,
) -> dict:
    source_candidate = Path(candidate_serving_db).resolve()
    canonical_path = Path(canonical_events_db).resolve()
    identity_path = Path(identity_db).resolve()
    venue_path = Path(venue_redirect_db).resolve()
    target_path = Path(out_db).resolve() if out_db else source_candidate
    for path in (source_candidate, canonical_path, identity_path, venue_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    if target_path in {canonical_path, identity_path, venue_path}:
        raise ValueError("materialized serving target overlaps a read-only input")

    created_copy = target_path != source_candidate
    if created_copy:
        if target_path.exists() and not replace:
            raise FileExistsError(target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        required = source_candidate.stat().st_size + canonical_path.stat().st_size + 512 * 1024 * 1024
        free = shutil.disk_usage(target_path.parent).free
        if free < required:
            raise OSError(f"insufficient free space for materialized candidate: need {required}, have {free}")
        temp_copy = target_path.with_name(f"{target_path.name}.copying")
        if temp_copy.exists():
            temp_copy.unlink()
        shutil.copy2(source_candidate, temp_copy)
        if target_path.exists():
            target_path.unlink()
        os.replace(temp_copy, target_path)

    canonical = _connect_read_only(canonical_path)
    identity = _connect_read_only(identity_path)
    venue = _connect_read_only(venue_path)
    target = sqlite3.connect(target_path)
    target.row_factory = sqlite3.Row
    try:
        _require_tables(target, RAW_TABLES, "candidate serving DB")
        _require_tables(
            canonical,
            (
                "canonical_event",
                "canonical_event_member",
                "canonical_dj_event",
                "canonical_event_merge_review_candidate",
                "build_metadata",
            ),
            "canonical events DB",
        )
        _require_tables(
            identity,
            ("dj_identity_redirect", "dj_identity_review_candidate", "identity_build_metadata"),
            "identity DB",
        )
        _require_tables(
            venue,
            ("venue_identity_redirect", "venue_identity_review_candidate", "venue_identity_build_metadata"),
            "venue redirect DB",
        )
        for label, con in (
            ("candidate", target),
            ("canonical", canonical),
            ("identity", identity),
            ("venue", venue),
        ):
            check = con.execute("PRAGMA quick_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"{label} DB failed PRAGMA quick_check: {check}")

        raw_before = _counts(target, RAW_TABLES)
        target.execute("PRAGMA foreign_keys=OFF")
        target.execute("BEGIN IMMEDIATE")
        _create_schema(target)
        copied = {}
        copied.update(_copy_canonical_tables(canonical, target))
        copied.update(_copy_identity_tables(identity, target))
        copied.update(_copy_venue_tables(venue, target))
        profile_counts = _materialize_profiles(target)
        materialized_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        _copy_metadata(target, canonical, identity, venue, materialized_at)

        raw_after = _counts(target, RAW_TABLES)
        if raw_after != raw_before:
            raise RuntimeError(f"raw serving rows changed during materialization: {raw_before} -> {raw_after}")
        event_dangling = target.execute(
            """
            SELECT COUNT(*)
              FROM canonical_event_member member
              LEFT JOIN canonical_event event USING(canonical_event_id)
             WHERE event.canonical_event_id IS NULL
            """
        ).fetchone()[0]
        dj_event_dangling = target.execute(
            """
            SELECT COUNT(*)
              FROM canonical_dj_event dj
              LEFT JOIN canonical_event event USING(canonical_event_id)
             WHERE event.canonical_event_id IS NULL
            """
        ).fetchone()[0]
        if event_dangling or dj_event_dangling:
            raise RuntimeError(
                f"canonical event FK coverage failed: members={event_dangling}, dj_events={dj_event_dangling}"
            )
        quick_check = target.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RuntimeError(f"materialized candidate failed PRAGMA quick_check: {quick_check}")
        target.commit()

        report = {
            "schema_version": SCHEMA_VERSION,
            "decision": "READY",
            "candidate_source": str(source_candidate),
            "materialized_candidate": str(target_path),
            "canonical_events_db": str(canonical_path),
            "identity_db": str(identity_path),
            "venue_redirect_db": str(venue_path),
            "raw_counts_before": raw_before,
            "raw_counts_after": raw_after,
            "raw_counts_unchanged": raw_before == raw_after,
            "copied_counts": copied,
            "profile_counts": profile_counts,
            "quick_check": quick_check,
            "safety": {
                "read_inputs_opened_read_only": True,
                "raw_tables_preserved": True,
                "candidate_only": True,
                "production_pointer_updated": False,
            },
        }
        if report_path is not None:
            report_file = Path(report_path).resolve()
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    except Exception:
        if target.in_transaction:
            target.rollback()
        target.close()
        canonical.close()
        identity.close()
        venue.close()
        if created_copy and target_path.exists():
            target_path.unlink()
        raise
    finally:
        try:
            target.close()
        except Exception:
            pass
        canonical.close()
        identity.close()
        venue.close()


def verify_materialized_candidate(candidate_db: Path | str) -> dict:
    """Run the promotion gate against one fully materialized serving candidate."""
    candidate_path = Path(candidate_db).resolve()
    report = {
        "schema_version": f"{SCHEMA_VERSION}.gate.v1",
        "candidate": str(candidate_path),
        "pass": False,
        "checks": {},
        "conditions": {},
        "failures": [],
    }
    if not candidate_path.is_file():
        report["failures"] = ["candidate_exists"]
        return report

    con = _connect_read_only(candidate_path)
    try:
        required_tables = (*RAW_TABLES, *MATERIALIZED_TABLES)
        missing_tables = [table for table in required_tables if not _table_exists(con, table)]
        report["checks"]["missing_tables"] = missing_tables
        report["conditions"]["required_tables_present"] = not missing_tables
        if missing_tables:
            report["failures"] = ["required_tables_present"]
            return report

        checks = {
            "quick_check": con.execute("PRAGMA quick_check").fetchone()[0],
            "raw_profile_count": con.execute("SELECT COUNT(*) FROM dj_profile").fetchone()[0],
            "raw_event_count": con.execute("SELECT COUNT(*) FROM performance_event").fetchone()[0],
            "redirect_count": con.execute("SELECT COUNT(*) FROM dj_identity_redirect").fetchone()[0],
            "canonical_profile_count": con.execute("SELECT COUNT(*) FROM canonical_dj_profile").fetchone()[0],
            "canonical_event_count": con.execute("SELECT COUNT(*) FROM canonical_event").fetchone()[0],
            "canonical_member_count": con.execute("SELECT COUNT(*) FROM canonical_event_member").fetchone()[0],
            "duplicate_normalized_names": con.execute(
                "SELECT COUNT(*) FROM ("
                "SELECT normalized_name FROM canonical_dj_profile "
                "GROUP BY normalized_name HAVING COUNT(*) > 1)"
            ).fetchone()[0],
            "redirect_sources_visible": con.execute(
                "SELECT COUNT(*) FROM dj_identity_redirect redirect "
                "JOIN canonical_dj_profile profile ON profile.dj_id=redirect.source_dj_id"
            ).fetchone()[0],
            "redirect_target_dangling": con.execute(
                "SELECT COUNT(*) FROM dj_identity_redirect redirect "
                "LEFT JOIN canonical_dj_profile profile ON profile.dj_id=redirect.canonical_dj_id "
                "WHERE profile.dj_id IS NULL"
            ).fetchone()[0],
            "canonical_dj_event_profile_dangling": con.execute(
                "SELECT COUNT(*) FROM canonical_dj_event link "
                "LEFT JOIN canonical_dj_profile profile ON profile.dj_id=link.dj_id "
                "WHERE profile.dj_id IS NULL"
            ).fetchone()[0],
            "canonical_dj_event_event_dangling": con.execute(
                "SELECT COUNT(*) FROM canonical_dj_event link "
                "LEFT JOIN canonical_event event USING(canonical_event_id) "
                "WHERE event.canonical_event_id IS NULL"
            ).fetchone()[0],
            "canonical_profile_event_count_mismatch": con.execute(
                "SELECT COUNT(*) FROM canonical_dj_profile profile "
                "LEFT JOIN ("
                "SELECT dj_id,COUNT(DISTINCT canonical_event_id) AS event_count "
                "FROM canonical_dj_event GROUP BY dj_id"
                ") counts ON counts.dj_id=profile.dj_id "
                "WHERE profile.event_count<>COALESCE(counts.event_count,0)"
            ).fetchone()[0],
            "canonical_member_event_dangling": con.execute(
                "SELECT COUNT(*) FROM canonical_event_member member "
                "LEFT JOIN canonical_event event USING(canonical_event_id) "
                "WHERE event.canonical_event_id IS NULL"
            ).fetchone()[0],
        }
        report["checks"].update(checks)
        expected_profiles = checks["raw_profile_count"] - checks["redirect_count"]
        report["checks"]["expected_canonical_profile_count"] = expected_profiles
        conditions = {
            "required_tables_present": True,
            "quick_check_ok": checks["quick_check"] == "ok",
            "canonical_profiles_complete": checks["canonical_profile_count"] == expected_profiles,
            "canonical_events_present": checks["canonical_event_count"] > 0,
            "raw_events_fully_mapped": checks["canonical_member_count"] == checks["raw_event_count"],
            "normalized_names_unique": checks["duplicate_normalized_names"] == 0,
            "redirect_sources_hidden": checks["redirect_sources_visible"] == 0,
            "redirect_targets_resolve": checks["redirect_target_dangling"] == 0,
            "canonical_dj_event_profiles_resolve": checks["canonical_dj_event_profile_dangling"] == 0,
            "canonical_dj_events_resolve": checks["canonical_dj_event_event_dangling"] == 0,
            "canonical_profile_event_counts_match": checks["canonical_profile_event_count_mismatch"] == 0,
            "canonical_members_resolve": checks["canonical_member_event_dangling"] == 0,
        }
        report["conditions"] = conditions
        report["failures"] = [name for name, passed in conditions.items() if not passed]
        report["pass"] = not report["failures"]
        return report
    except sqlite3.Error as exc:
        report["failures"] = ["sqlite_error"]
        report["error"] = str(exc)
        return report
    finally:
        con.close()


def _self_check() -> None:
    from test_materialize_canonical_serving import build_fixture
    import tempfile

    with tempfile.TemporaryDirectory(prefix="atlas_materialize_selfcheck_") as tmp:
        candidate, events, identity, venue = build_fixture(Path(tmp))
        report = materialize(candidate, events, identity, venue)
        assert report["raw_counts_unchanged"], report
        con = sqlite3.connect(candidate)
        try:
            assert con.execute("SELECT COUNT(*) FROM canonical_dj_profile").fetchone()[0] == 2
            assert con.execute("SELECT COUNT(*) FROM canonical_event").fetchone()[0] == 2
        finally:
            con.close()
    print("self-check OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-serving-db", type=Path)
    parser.add_argument("--canonical-events-db", type=Path)
    parser.add_argument("--identity-db", type=Path)
    parser.add_argument("--venue-redirect-db", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--verify-candidate", type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return
    if args.verify_candidate:
        report = verify_materialized_candidate(args.verify_candidate)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["pass"]:
            raise SystemExit(2)
        return
    required = (
        args.candidate_serving_db,
        args.canonical_events_db,
        args.identity_db,
        args.venue_redirect_db,
    )
    if any(path is None for path in required):
        parser.error(
            "--candidate-serving-db, --canonical-events-db, --identity-db and --venue-redirect-db are required"
        )
    report = materialize(
        args.candidate_serving_db,
        args.canonical_events_db,
        args.identity_db,
        args.venue_redirect_db,
        out_db=args.out,
        report_path=args.report,
        replace=args.replace,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
