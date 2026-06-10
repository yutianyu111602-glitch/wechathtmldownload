#!/usr/bin/env python3
"""Run or dry-run the S148 guarded DB3 relation identity canary.

S148 consumes the S147 execution gate, creates or validates a separate operator
approval artifact, and can execute exactly one DB3 identity merge canary under a
single-writer lock, backup, BEGIN IMMEDIATE transaction, rollback-on-failure,
source_ref readback, duplicate collapse, and no-empty-overwrite checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import build_atlas_relation_identity_db3_execution_gate_s147 as s147


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S148"
SCHEMA_VERSION = "atlas_relation_identity_db3_canary_s148.v1"

DEFAULT_S147_REPORT = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_execution_gate_s147_20260602"
    / "atlas_relation_identity_db3_execution_gate_s147.json"
)
DEFAULT_APPROVAL_ARTIFACT = (
    REPORTS_ROOT
    / "atlas_relation_identity_db3_execution_gate_s147_20260602"
    / "operator_approval_s147.json"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_db3_canary_s148_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_DB3_CANARY_S148_20260602.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object JSON: {path}")
    return value


class FileLock:
    def __init__(self, path: Path, *, max_attempts: int = 5, sleep_ms: int = 200) -> None:
        self.path = path
        self.max_attempts = max_attempts
        self.sleep_ms = sleep_ms
        self.fd: int | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self.max_attempts + 1):
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, json.dumps({"pid": os.getpid(), "created_at": now_iso()}).encode("utf-8"))
                return self
            except FileExistsError as exc:
                if attempt >= self.max_attempts:
                    raise TimeoutError(f"single_writer_lock_busy:{self.path}") from exc
                time.sleep(self.sleep_ms / 1000)
        raise TimeoutError(f"single_writer_lock_busy:{self.path}")

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def connect_rw(path: Path, *, busy_timeout_ms: int) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=rw", uri=True, timeout=busy_timeout_ms / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    return conn


def non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return values[0] if values else None


def min_text(*values: Any) -> str | None:
    cleaned = sorted(str(value) for value in values if value not in (None, ""))
    return cleaned[0] if cleaned else None


def max_text(*values: Any) -> str | None:
    cleaned = sorted(str(value) for value in values if value not in (None, ""))
    return cleaned[-1] if cleaned else None


def parse_aliases(value: Any) -> list[str]:
    aliases: list[str] = []
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                aliases.extend(str(item) for item in parsed if str(item).strip())
            else:
                aliases.append(value)
        except json.JSONDecodeError:
            aliases.append(value)
    elif isinstance(value, list):
        aliases.extend(str(item) for item in value if str(item).strip())
    return aliases


def alias_union(*values: Any) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        for alias in parse_aliases(value):
            key = alias
            if key not in seen:
                result.append(alias)
                seen.add(key)
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {table: table_count(conn, table) for table in ["dj_profile", "subject", "dj_event", "dj_venue", "dj_collaborator", "source_ref"]}


def fetch_rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def canary_snapshot(conn: sqlite3.Connection, selected: dict[str, Any]) -> dict[str, Any]:
    canonical = selected["canonical_dj_id"]
    old_ids = list(selected.get("merge_dj_ids") or [])
    all_ids = [canonical, *old_ids]
    ph = placeholders(all_ids)
    return {
        "table_counts": table_counts(conn),
        "profile_rows": fetch_rows(conn, f"SELECT * FROM dj_profile WHERE dj_id IN ({ph}) ORDER BY dj_id", tuple(all_ids)),
        "subject_rows": fetch_rows(conn, f"SELECT * FROM subject WHERE subject_id IN ({ph}) ORDER BY subject_id", tuple(all_ids)),
        "event_counts": fetch_rows(conn, f"SELECT dj_id, COUNT(*) AS count FROM dj_event WHERE dj_id IN ({ph}) GROUP BY dj_id ORDER BY dj_id", tuple(all_ids)),
        "venue_counts": fetch_rows(conn, f"SELECT dj_id, COUNT(*) AS count, SUM(COALESCE(event_count,0)) AS event_count_sum FROM dj_venue WHERE dj_id IN ({ph}) GROUP BY dj_id ORDER BY dj_id", tuple(all_ids)),
        "collaborator_relevant_count": int(conn.execute(f"SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id IN ({ph}) OR dst_dj_id IN ({ph})", tuple(all_ids + all_ids)).fetchone()[0]),
        "broken_source_ref_count": broken_source_ref_count(conn, [canonical, *old_ids]),
    }


def broken_source_ref_count(conn: sqlite3.Connection, ids: list[str]) -> int:
    if not ids:
        return 0
    ph = placeholders(ids)
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM dj_event e
            LEFT JOIN source_ref s ON s.source_ref_id = e.source_ref_id
            WHERE e.dj_id IN ({ph})
              AND e.source_ref_id IS NOT NULL
              AND e.source_ref_id != ''
              AND s.source_ref_id IS NULL
            """,
            tuple(ids),
        ).fetchone()[0]
    )


def collision_count(conn: sqlite3.Connection, table: str, id_col: str, key_col: str, canonical: str, old_ids: list[str]) -> int:
    if not old_ids:
        return 0
    all_ids = [canonical, *old_ids]
    ph = placeholders(all_ids)
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*) - COUNT(DISTINCT {key_col})
            FROM {table}
            WHERE {id_col} IN ({ph})
            """,
            tuple(all_ids),
        ).fetchone()[0]
        or 0
    )


def collaborator_expected_after_count(conn: sqlite3.Connection, canonical: str, old_ids: list[str]) -> tuple[int, int, int]:
    all_ids = [canonical, *old_ids]
    ph = placeholders(all_ids)
    rows = fetch_rows(
        conn,
        f"SELECT src_dj_id, dst_dj_id, same_event_count, relation_label_zh, relation_score FROM dj_collaborator WHERE src_dj_id IN ({ph}) OR dst_dj_id IN ({ph})",
        tuple(all_ids + all_ids),
    )
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    self_loops = 0
    for row in rows:
        src = canonical if row["src_dj_id"] in old_ids else row["src_dj_id"]
        dst = canonical if row["dst_dj_id"] in old_ids else row["dst_dj_id"]
        if src == dst:
            self_loops += 1
            continue
        key = (src, dst)
        current = groups.setdefault(
            key,
            {
                "src_dj_id": src,
                "dst_dj_id": dst,
                "same_event_count": 0,
                "relation_label_zh": "",
                "relation_score": None,
            },
        )
        current["same_event_count"] += int(row.get("same_event_count") or 0)
        current["relation_label_zh"] = non_empty(current.get("relation_label_zh"), row.get("relation_label_zh")) or ""
        score = row.get("relation_score")
        if score is not None:
            current["relation_score"] = score if current["relation_score"] is None else max(current["relation_score"], score)
    return len(rows), len(groups), self_loops


def expected_table_counts(conn: sqlite3.Connection, selected: dict[str, Any]) -> dict[str, int]:
    canonical = selected["canonical_dj_id"]
    old_ids = list(selected.get("merge_dj_ids") or [])
    before = table_counts(conn)
    old_ph = placeholders(old_ids)
    old_profiles = int(conn.execute(f"SELECT COUNT(*) FROM dj_profile WHERE dj_id IN ({old_ph})", tuple(old_ids)).fetchone()[0])
    old_subjects = int(conn.execute(f"SELECT COUNT(*) FROM subject WHERE subject_id IN ({old_ph})", tuple(old_ids)).fetchone()[0])
    event_collisions = collision_count(conn, "dj_event", "dj_id", "event_id", canonical, old_ids)
    venue_collisions = collision_count(conn, "dj_venue", "dj_id", "venue_id", canonical, old_ids)
    collab_before_relevant, collab_after_relevant, _self_loops = collaborator_expected_after_count(conn, canonical, old_ids)
    return {
        "dj_profile": before["dj_profile"] - old_profiles,
        "subject": before["subject"] - old_subjects,
        "dj_event": before["dj_event"] - event_collisions,
        "dj_venue": before["dj_venue"] - venue_collisions,
        "dj_collaborator": before["dj_collaborator"] - collab_before_relevant + collab_after_relevant,
        "source_ref": before["source_ref"],
    }


def coalesce_profile(conn: sqlite3.Connection, canonical: str, old_ids: list[str]) -> None:
    rows = fetch_rows(conn, f"SELECT * FROM dj_profile WHERE dj_id IN ({placeholders([canonical, *old_ids])})", tuple([canonical, *old_ids]))
    by_id = {row["dj_id"]: row for row in rows}
    canonical_row = by_id[canonical]
    merge_rows = [by_id[old_id] for old_id in old_ids if old_id in by_id]
    aliases = alias_union(canonical_row.get("aliases_json"), canonical_row.get("display_name"), *[row.get("aliases_json") for row in merge_rows], *[row.get("display_name") for row in merge_rows])
    conn.execute(
        """
        UPDATE dj_profile
        SET aliases_json = ?,
            city_primary = ?,
            bio = ?,
            bio_source = ?,
            avatar_url = ?
        WHERE dj_id = ?
        """,
        (
            aliases,
            non_empty(canonical_row.get("city_primary"), *[row.get("city_primary") for row in merge_rows]),
            non_empty(canonical_row.get("bio"), *[row.get("bio") for row in merge_rows]),
            non_empty(canonical_row.get("bio_source"), *[row.get("bio_source") for row in merge_rows]),
            non_empty(canonical_row.get("avatar_url"), *[row.get("avatar_url") for row in merge_rows]),
            canonical,
        ),
    )


def coalesce_subject(conn: sqlite3.Connection, canonical: str, old_ids: list[str]) -> None:
    rows = fetch_rows(conn, f"SELECT * FROM subject WHERE subject_id IN ({placeholders([canonical, *old_ids])})", tuple([canonical, *old_ids]))
    by_id = {row["subject_id"]: row for row in rows}
    canonical_row = by_id.get(canonical)
    if not canonical_row:
        return
    merge_rows = [by_id[old_id] for old_id in old_ids if old_id in by_id]
    aliases = alias_union(canonical_row.get("aliases_json"), canonical_row.get("display_name"), *[row.get("aliases_json") for row in merge_rows], *[row.get("display_name") for row in merge_rows])
    conn.execute(
        """
        UPDATE subject
        SET aliases_json = ?,
            city_primary = ?
        WHERE subject_id = ?
        """,
        (
            aliases,
            non_empty(canonical_row.get("city_primary"), *[row.get("city_primary") for row in merge_rows]),
            canonical,
        ),
    )


def merge_events(conn: sqlite3.Connection, canonical: str, old_ids: list[str]) -> dict[str, int]:
    updated = deleted = 0
    for old_id in old_ids:
        old_rows = fetch_rows(conn, "SELECT * FROM dj_event WHERE dj_id = ? ORDER BY event_id", (old_id,))
        for old in old_rows:
            existing = conn.execute("SELECT * FROM dj_event WHERE dj_id = ? AND event_id = ?", (canonical, old["event_id"])).fetchone()
            if existing:
                cur = dict(existing)
                conn.execute(
                    """
                    UPDATE dj_event
                    SET starts_at = ?, event_title = ?, venue_id = ?, venue_name = ?,
                        city = ?, source_ref_id = ?, confidence = ?
                    WHERE dj_id = ? AND event_id = ?
                    """,
                    (
                        non_empty(cur.get("starts_at"), old.get("starts_at")),
                        non_empty(cur.get("event_title"), old.get("event_title")),
                        non_empty(cur.get("venue_id"), old.get("venue_id")),
                        non_empty(cur.get("venue_name"), old.get("venue_name")),
                        non_empty(cur.get("city"), old.get("city")),
                        non_empty(cur.get("source_ref_id"), old.get("source_ref_id")),
                        max(float(cur.get("confidence") or 0), float(old.get("confidence") or 0)),
                        canonical,
                        old["event_id"],
                    ),
                )
                conn.execute("DELETE FROM dj_event WHERE dj_id = ? AND event_id = ?", (old_id, old["event_id"]))
                deleted += 1
            else:
                conn.execute("UPDATE dj_event SET dj_id = ? WHERE dj_id = ? AND event_id = ?", (canonical, old_id, old["event_id"]))
                updated += 1
    return {"updated_old_event_rows": updated, "deleted_duplicate_event_rows": deleted}


def merge_venues(conn: sqlite3.Connection, canonical: str, old_ids: list[str]) -> dict[str, int]:
    updated = deleted = 0
    for old_id in old_ids:
        old_rows = fetch_rows(conn, "SELECT * FROM dj_venue WHERE dj_id = ? ORDER BY venue_id", (old_id,))
        for old in old_rows:
            existing = conn.execute("SELECT * FROM dj_venue WHERE dj_id = ? AND venue_id = ?", (canonical, old["venue_id"])).fetchone()
            if existing:
                cur = dict(existing)
                conn.execute(
                    """
                    UPDATE dj_venue
                    SET venue_name = ?, city = ?, event_count = ?,
                        first_seen_at = ?, last_seen_at = ?
                    WHERE dj_id = ? AND venue_id = ?
                    """,
                    (
                        non_empty(cur.get("venue_name"), old.get("venue_name")),
                        non_empty(cur.get("city"), old.get("city")),
                        int(cur.get("event_count") or 0) + int(old.get("event_count") or 0),
                        min_text(cur.get("first_seen_at"), old.get("first_seen_at")),
                        max_text(cur.get("last_seen_at"), old.get("last_seen_at")),
                        canonical,
                        old["venue_id"],
                    ),
                )
                conn.execute("DELETE FROM dj_venue WHERE dj_id = ? AND venue_id = ?", (old_id, old["venue_id"]))
                deleted += 1
            else:
                conn.execute("UPDATE dj_venue SET dj_id = ? WHERE dj_id = ? AND venue_id = ?", (canonical, old_id, old["venue_id"]))
                updated += 1
    return {"updated_old_venue_rows": updated, "deleted_duplicate_venue_rows": deleted}


def merge_collaborators(conn: sqlite3.Connection, canonical: str, old_ids: list[str]) -> dict[str, int]:
    all_ids = [canonical, *old_ids]
    ph = placeholders(all_ids)
    rows = fetch_rows(
        conn,
        f"SELECT * FROM dj_collaborator WHERE src_dj_id IN ({ph}) OR dst_dj_id IN ({ph}) ORDER BY src_dj_id, dst_dj_id",
        tuple(all_ids + all_ids),
    )
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    self_loops = 0
    for row in rows:
        src = canonical if row["src_dj_id"] in old_ids else row["src_dj_id"]
        dst = canonical if row["dst_dj_id"] in old_ids else row["dst_dj_id"]
        if src == dst:
            self_loops += 1
            continue
        key = (src, dst)
        current = groups.setdefault(
            key,
            {
                "src_dj_id": src,
                "dst_dj_id": dst,
                "same_event_count": 0,
                "relation_label_zh": "",
                "relation_score": None,
            },
        )
        current["same_event_count"] += int(row.get("same_event_count") or 0)
        current["relation_label_zh"] = non_empty(current.get("relation_label_zh"), row.get("relation_label_zh")) or ""
        score = row.get("relation_score")
        if score is not None:
            current["relation_score"] = score if current["relation_score"] is None else max(float(current["relation_score"]), float(score))
    conn.execute(f"DELETE FROM dj_collaborator WHERE src_dj_id IN ({ph}) OR dst_dj_id IN ({ph})", tuple(all_ids + all_ids))
    for row in groups.values():
        conn.execute(
            """
            INSERT INTO dj_collaborator (src_dj_id, dst_dj_id, same_event_count, relation_label_zh, relation_score)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                row["src_dj_id"],
                row["dst_dj_id"],
                row["same_event_count"],
                row["relation_label_zh"],
                row["relation_score"],
            ),
        )
    return {
        "collaborator_rows_deleted_for_redirect": len(rows),
        "collaborator_rows_reinserted_after_collapse": len(groups),
        "collaborator_self_loops_dropped": self_loops,
    }


def recompute_counts(conn: sqlite3.Connection, canonical: str) -> dict[str, int]:
    event_count = int(conn.execute("SELECT COUNT(*) FROM dj_event WHERE dj_id = ?", (canonical,)).fetchone()[0])
    venue_count = int(conn.execute("SELECT COUNT(*) FROM dj_venue WHERE dj_id = ?", (canonical,)).fetchone()[0])
    collaborator_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = ? OR dst_dj_id = ?",
            (canonical, canonical),
        ).fetchone()[0]
    )
    conn.execute(
        "UPDATE dj_profile SET event_count = ?, venue_count = ?, collaborator_count = ? WHERE dj_id = ?",
        (event_count, venue_count, collaborator_count, canonical),
    )
    conn.execute(
        "UPDATE subject SET event_count = ?, relation_count = ? WHERE subject_id = ?",
        (event_count, collaborator_count, canonical),
    )
    return {"event_count": event_count, "venue_count": venue_count, "collaborator_count": collaborator_count}


def apply_canary_merge(conn: sqlite3.Connection, selected: dict[str, Any]) -> dict[str, Any]:
    canonical = selected["canonical_dj_id"]
    old_ids = list(selected.get("merge_dj_ids") or [])
    coalesce_profile(conn, canonical, old_ids)
    coalesce_subject(conn, canonical, old_ids)
    event_stats = merge_events(conn, canonical, old_ids)
    venue_stats = merge_venues(conn, canonical, old_ids)
    collaborator_stats = merge_collaborators(conn, canonical, old_ids)
    if old_ids:
        ph = placeholders(old_ids)
        conn.execute(f"DELETE FROM subject WHERE subject_id IN ({ph})", tuple(old_ids))
        conn.execute(f"DELETE FROM dj_profile WHERE dj_id IN ({ph})", tuple(old_ids))
    counts = recompute_counts(conn, canonical)
    return {**event_stats, **venue_stats, **collaborator_stats, "recomputed_counts": counts}


def validate_prewrite_state(conn: sqlite3.Connection, selected: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    canonical = selected["canonical_dj_id"]
    old_ids = list(selected.get("merge_dj_ids") or [])
    if conn.execute("SELECT COUNT(*) FROM dj_profile WHERE dj_id = ?", (canonical,)).fetchone()[0] != 1:
        blockers.append("canonical_profile_missing_or_duplicate")
    if conn.execute("SELECT COUNT(*) FROM subject WHERE subject_id = ?", (canonical,)).fetchone()[0] != 1:
        blockers.append("canonical_subject_missing_or_duplicate")
    if old_ids:
        ph = placeholders(old_ids)
        if conn.execute(f"SELECT COUNT(*) FROM dj_profile WHERE dj_id IN ({ph})", tuple(old_ids)).fetchone()[0] != len(old_ids):
            blockers.append("old_profile_count_drift")
        if conn.execute(f"SELECT COUNT(*) FROM subject WHERE subject_id IN ({ph})", tuple(old_ids)).fetchone()[0] != len(old_ids):
            blockers.append("old_subject_count_drift")
    if broken_source_ref_count(conn, [canonical, *old_ids]) != 0:
        blockers.append("source_ref_integrity_breaks_before_write")
    return blockers


def postwrite_readback(
    conn: sqlite3.Connection,
    selected: dict[str, Any],
    expected_counts: dict[str, int],
    canonical_before: dict[str, Any] | None,
) -> dict[str, Any]:
    canonical = selected["canonical_dj_id"]
    old_ids = list(selected.get("merge_dj_ids") or [])
    old_ph = placeholders(old_ids)
    table_after = table_counts(conn)
    profile = conn.execute(
        "SELECT display_name, normalized_name, aliases_json, city_primary, bio_source, event_count, venue_count, collaborator_count FROM dj_profile WHERE dj_id = ?",
        (canonical,),
    ).fetchone()
    old_profile_count = int(conn.execute(f"SELECT COUNT(*) FROM dj_profile WHERE dj_id IN ({old_ph})", tuple(old_ids)).fetchone()[0]) if old_ids else 0
    old_subject_count = int(conn.execute(f"SELECT COUNT(*) FROM subject WHERE subject_id IN ({old_ph})", tuple(old_ids)).fetchone()[0]) if old_ids else 0
    old_event_count = int(conn.execute(f"SELECT COUNT(*) FROM dj_event WHERE dj_id IN ({old_ph})", tuple(old_ids)).fetchone()[0]) if old_ids else 0
    old_venue_count = int(conn.execute(f"SELECT COUNT(*) FROM dj_venue WHERE dj_id IN ({old_ph})", tuple(old_ids)).fetchone()[0]) if old_ids else 0
    old_collab_count = (
        int(
            conn.execute(
                f"SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id IN ({old_ph}) OR dst_dj_id IN ({old_ph})",
                tuple(old_ids + old_ids),
            ).fetchone()[0]
        )
        if old_ids
        else 0
    )
    self_loops = int(conn.execute("SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = ? AND dst_dj_id = ?", (canonical, canonical)).fetchone()[0])
    source_ref_breaks = broken_source_ref_count(conn, [canonical])
    table_count_matches = {table: table_after.get(table) == expected for table, expected in expected_counts.items()}
    profile_dict = dict(profile) if profile else {}
    aliases = parse_aliases(profile_dict.get("aliases_json"))
    before = canonical_before or {}
    no_empty = all(
        [
            bool(profile_dict.get("display_name")),
            bool(profile_dict.get("normalized_name")),
            bool(profile_dict.get("aliases_json")),
            bool(profile_dict.get("city_primary")),
            profile_dict.get("display_name") == before.get("display_name"),
            profile_dict.get("normalized_name") == before.get("normalized_name"),
            all(alias in aliases for alias in parse_aliases(before.get("aliases_json"))),
        ]
    )
    ok = all(
        [
            profile is not None,
            old_profile_count == 0,
            old_subject_count == 0,
            old_event_count == 0,
            old_venue_count == 0,
            old_collab_count == 0,
            self_loops == 0,
            source_ref_breaks == 0,
            all(table_count_matches.values()),
            no_empty,
        ]
    )
    return {
        "ok": ok,
        "canonical_profile_present": profile is not None,
        "old_profile_count": old_profile_count,
        "old_subject_count": old_subject_count,
        "old_event_count": old_event_count,
        "old_venue_count": old_venue_count,
        "old_collaborator_count": old_collab_count,
        "canonical_collaborator_self_loops": self_loops,
        "source_ref_integrity_breaks": source_ref_breaks,
        "table_counts_after": table_after,
        "expected_table_counts_after": expected_counts,
        "table_count_matches": table_count_matches,
        "canonical_profile_after": profile_dict,
        "no_empty_overwrite_ok": no_empty,
    }


def ensure_autonomous_approval(
    *,
    s147_report: dict[str, Any],
    approval_path: Path,
    operator: str,
    create: bool,
) -> dict[str, Any]:
    if approval_path.exists():
        return {"created": False, "path": rel_path(approval_path), "reason": "approval_artifact_already_present"}
    if not create:
        return {"created": False, "path": rel_path(approval_path), "reason": "autonomous_approval_not_requested"}
    selected = s147_report.get("selected_canary") or {}
    payload = {
        "schema_version": s147.APPROVAL_SCHEMA_VERSION,
        "current_story_id": "S147",
        "approval_status": "approved",
        "approval_scope": "single_s147_canary_only",
        "source_report_sha256": (s147_report.get("source_inputs") or {}).get("s146_report_sha256"),
        "approved_prewrite_row_id": selected.get("prewrite_row_id"),
        "approved_group_id": selected.get("group_id"),
        "canonical_dj_id": selected.get("canonical_dj_id"),
        "merge_dj_ids": selected.get("merge_dj_ids") or [],
        "allow_single_canary_write": True,
        "operator": operator,
        "approved_at": now_iso(),
        "approval_statement": "User granted production write and autonomy for blocker repair; approve only this S148 single-row DB3 canary after S147 gate selection.",
        "approval_basis": {
            "user_authorization_recorded_in_prd": "production_write_policy.authorization",
            "s147_decision": s147_report.get("decision"),
            "selected_canary_only": True,
            "db2_projection_allowed": False,
            "deploy_upload_review_allowed": False,
        },
    }
    atomic_write_json(approval_path, payload)
    return {"created": True, "path": rel_path(approval_path), "reason": "created_autonomous_operator_approval"}


def execute_with_gate(
    *,
    db3_path: Path,
    out_dir: Path,
    selected: dict[str, Any],
    execute: bool,
    busy_timeout_ms: int,
    max_lock_attempts: int,
    story_label: str = "s148",
) -> dict[str, Any]:
    lock_path = out_dir / f"atlas_relation_identity_db3_canary_{story_label}.lock"
    result: dict[str, Any] = {
        "execute_requested": execute,
        "write_executed": False,
        "committed": False,
        "lock_path": rel_path(lock_path),
        "backup_path": "",
        "backup_sha256": "",
        "rollback_performed": False,
        "blocked_reasons": [],
    }
    if not execute:
        result["blocked_reasons"].append("execute_flag_not_set")
        return result

    with FileLock(lock_path, max_attempts=max_lock_attempts):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = out_dir / f"backup_before_relation_identity_db3_canary_{story_label}_{stamp}.sqlite"
        shutil.copy2(db3_path, backup_path)
        backup_sha = sha256_file(backup_path)
        result["backup_path"] = rel_path(backup_path)
        result["backup_sha256"] = backup_sha
        conn = connect_rw(db3_path, busy_timeout_ms=busy_timeout_ms)
        try:
            pre_blockers = validate_prewrite_state(conn, selected)
            if pre_blockers:
                result["blocked_reasons"].extend(pre_blockers)
                return result
            before = canary_snapshot(conn, selected)
            expected_counts = expected_table_counts(conn, selected)
            canonical_before = next((row for row in before["profile_rows"] if row.get("dj_id") == selected["canonical_dj_id"]), None)
            conn.execute("BEGIN IMMEDIATE")
            write_stats = apply_canary_merge(conn, selected)
            readback = postwrite_readback(conn, selected, expected_counts, canonical_before)
            result["prewrite_snapshot"] = before
            result["write_stats"] = write_stats
            result["precommit_readback"] = readback
            if not readback["ok"]:
                conn.rollback()
                result["rollback_performed"] = True
                result["blocked_reasons"].append("precommit_readback_failed")
                return result
            conn.commit()
            postcommit = postwrite_readback(conn, selected, expected_counts, canonical_before)
            result["postcommit_readback"] = postcommit
            if not postcommit["ok"]:
                result["blocked_reasons"].append("postcommit_readback_failed_manual_restore_required")
                return result
            result["write_executed"] = True
            result["committed"] = True
            return result
        except Exception as exc:  # noqa: BLE001
            try:
                conn.rollback()
                result["rollback_performed"] = True
            except sqlite3.Error:
                pass
            result["blocked_reasons"].append(f"{exc.__class__.__name__}:{exc}")
            return result
        finally:
            conn.close()


def build_report(
    *,
    s147_report_path: Path,
    approval_artifact_path: Path,
    db3_path: Path,
    out_dir: Path,
    execute: bool,
    autonomous_approval: bool,
    operator: str,
    busy_timeout_ms: int = 5000,
    max_lock_attempts: int = 5,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    s147_report = read_json(s147_report_path)
    selected = s147_report.get("selected_canary") or {}
    approval_creation = ensure_autonomous_approval(
        s147_report=s147_report,
        approval_path=approval_artifact_path,
        operator=operator,
        create=autonomous_approval,
    )
    approval, approval_state = s147.load_approval(approval_artifact_path)
    approval_valid, approval_gaps = s147.validate_approval(
        approval,
        selected,
        (s147_report.get("source_inputs") or {}).get("s146_report_sha256") or "",
    )
    execution = execute_with_gate(
        db3_path=db3_path,
        out_dir=out_dir,
        selected=selected,
        execute=execute and approval_valid,
        busy_timeout_ms=busy_timeout_ms,
        max_lock_attempts=max_lock_attempts,
    )
    if not approval_valid:
        decision = "atlas_relation_identity_db3_canary_s148_blocked_invalid_or_missing_approval"
    elif execution.get("committed"):
        decision = "atlas_relation_identity_db3_canary_s148_committed_with_readback"
    elif execute:
        decision = "atlas_relation_identity_db3_canary_s148_blocked_before_commit"
    else:
        decision = "atlas_relation_identity_db3_canary_s148_approval_valid_no_write_dry_run"
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "source_inputs": {
            "s147_report": rel_path(s147_report_path),
            "approval_artifact": rel_path(approval_artifact_path),
            "db3": rel_path(db3_path),
        },
        "selected_canary": selected,
        "operator_approval": {
            "artifact_present": approval_state == "present",
            "valid": approval_valid,
            "validation_gaps": approval_gaps,
            "creation": approval_creation,
            "raw_values_printed": False,
        },
        "execution": execution,
        "write_state": {
            "execute_requested": execute,
            "write_executed": bool(execution.get("write_executed")),
            "database_mutations": bool(execution.get("committed")),
            "db3_identity_write": bool(execution.get("committed")),
            "committed": bool(execution.get("committed")),
            "rollback_performed": bool(execution.get("rollback_performed")),
            "approved_for_write_gate_count": 1 if approval_valid else 0,
            "write_gate_candidate_count": 1 if approval_valid else 0,
            "database_write_allowed_count": 1 if approval_valid and execute else 0,
        },
        "safety": {
            "db1_mutation": False,
            "db2_projection": False,
            "release_rebuild": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "service_restart": False,
            "broad_disk_scan": False,
            "single_canary_only": True,
            "other_s146_rows_excluded": True,
            "s145_gap_rows_excluded": True,
        },
    }
    report["next_action_tasks"] = make_tasks(report)
    return report


def make_tasks(report: dict[str, Any]) -> list[dict[str, Any]]:
    selected = report.get("selected_canary") or {}
    base = {
        "story_id": CURRENT_STORY_ID,
        "group_id": selected.get("group_id"),
        "prewrite_row_id": selected.get("prewrite_row_id"),
    }
    if report["write_state"]["committed"]:
        return [
            {
                **base,
                "task_id": "s148:postwrite_relation_blocker_refresh",
                "status": "next",
                "next_action": "Rerun relation identity blocker/preflight audit to confirm the selected multi-id group is closed and select the next smallest canary.",
            }
        ]
    return [
        {
            **base,
            "task_id": "s148:canary_blocked_before_commit",
            "status": "blocked",
            "blockers": report.get("operator_approval", {}).get("validation_gaps") or report.get("execution", {}).get("blocked_reasons") or [],
            "next_action": "Repair approval or execution blockers, then rerun S148 on the same selected canary only.",
        }
    ]


def render_markdown(report: dict[str, Any], paths: dict[str, str]) -> str:
    selected = report.get("selected_canary") or {}
    write = report["write_state"]
    lines = [
        "# Atlas Relation Identity DB3 Canary S148",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Selected canary: `{selected.get('group_id')}` / `{selected.get('prewrite_row_id')}`",
        f"- Approval valid: `{str(report['operator_approval']['valid']).lower()}`",
        f"- Execute requested / committed: `{str(write['execute_requested']).lower()}` / `{str(write['committed']).lower()}`",
        f"- DB3 identity write: `{str(write['db3_identity_write']).lower()}`",
        "",
        "## Output Files",
        "",
        f"- JSON: `{paths['json']}`",
        f"- Readback: `{paths['readback']}`",
        f"- Tasks: `{paths['tasks']}`",
        "",
        "## Boundary",
        "",
        "- S148 touches only the selected canary row if approval is valid and execute is requested.",
        "- DB2 projection, release rebuild, deploy, upload, and review remain blocked.",
        "- Other S146 rows and S145 gap rows remain excluded.",
        "",
    ]
    execution = report.get("execution") or {}
    if execution.get("backup_path"):
        lines.extend(
            [
                "## Backup",
                "",
                f"- Backup: `{execution['backup_path']}`",
                f"- Backup sha256: `{execution['backup_sha256']}`",
                "",
            ]
        )
    if execution.get("blocked_reasons"):
        lines.extend(["## Blockers", ""])
        for blocker in execution["blocked_reasons"]:
            lines.append(f"- `{blocker}`")
        lines.append("")
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], out_dir: Path, scorecard: Path | None) -> dict[str, str]:
    paths = {
        "json": str(out_dir / "atlas_relation_identity_db3_canary_s148.json"),
        "readback": str(out_dir / "relation_identity_db3_canary_readback_s148.json"),
        "tasks": str(out_dir / "relation_identity_db3_canary_tasks_s148.jsonl"),
        "markdown": str(out_dir / "atlas_relation_identity_db3_canary_s148.md"),
    }
    atomic_write_json(Path(paths["json"]), report)
    atomic_write_json(Path(paths["readback"]), report.get("execution") or {})
    atomic_write_jsonl(Path(paths["tasks"]), report["next_action_tasks"])
    markdown = render_markdown(report, paths)
    atomic_write_text(Path(paths["markdown"]), markdown)
    if scorecard is not None:
        atomic_write_text(scorecard, markdown)
        paths["scorecard"] = str(scorecard)
    return paths


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s147-report", type=Path, default=DEFAULT_S147_REPORT)
    parser.add_argument("--approval-artifact", type=Path, default=DEFAULT_APPROVAL_ARTIFACT)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--operator", default="codex-autonomous-operator")
    parser.add_argument("--busy-timeout-ms", type=int, default=5000)
    parser.add_argument("--max-lock-attempts", type=int, default=5)
    parser.add_argument("--autonomous-approval", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--no-scorecard", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_report(
        s147_report_path=args.s147_report,
        approval_artifact_path=args.approval_artifact,
        db3_path=args.db3,
        out_dir=args.out_dir,
        execute=args.execute,
        autonomous_approval=args.autonomous_approval,
        operator=args.operator,
        busy_timeout_ms=args.busy_timeout_ms,
        max_lock_attempts=args.max_lock_attempts,
    )
    paths = write_outputs(report, args.out_dir, None if args.no_scorecard else args.scorecard)
    summary = {
        "decision": report["decision"],
        "selected_canary": {
            "group_id": (report.get("selected_canary") or {}).get("group_id"),
            "prewrite_row_id": (report.get("selected_canary") or {}).get("prewrite_row_id"),
        },
        "operator_approval": report["operator_approval"],
        "write_state": report["write_state"],
        "backup_path": (report.get("execution") or {}).get("backup_path"),
        "json": paths["json"],
        "tasks": paths["tasks"],
        "scorecard": paths.get("scorecard"),
    }
    print(json.dumps(report if args.json_only else summary, ensure_ascii=False, sort_keys=args.json_only, indent=None if args.json_only else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
