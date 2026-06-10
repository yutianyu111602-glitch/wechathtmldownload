from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import build_db2_outlink_lineage_reconcile_s125 as lineage
import db2_shorturl_candidates


DEFAULT_LIVE_DB = Path(os.environ.get("DB2_SWARM_DB", "/home/pc/swarm_data/atlas_swarm_data.sqlite"))
DEFAULT_CACHE_DB = Path(os.environ.get("DB2_SIDECAR_CACHE_DB", "/home/pc/swarm_data/cache/db2_sidecar_cache.sqlite"))

SHORT_URL_HOSTS = db2_shorturl_candidates.SHORT_URL_HOSTS
SOURCE_PROCESSED_PHASES = {"linktree_expand", "shorturl_resolve", "ig_bio"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def assert_cache_path_allowed(path: Path) -> None:
    normalized = str(path).replace("\\", "/").lower()
    if normalized.startswith("d:") or normalized == "/mnt/d" or normalized.startswith("/mnt/d/"):
        raise ValueError("D drive is cold-data storage and is forbidden for DB2 sidecar cache")


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def connect_cache_writer(path: Path) -> sqlite3.Connection:
    assert_cache_path_allowed(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not table_exists(conn, table_name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def cache_table_ready(conn: sqlite3.Connection, table_name: str) -> bool:
    try:
        return table_exists(conn, table_name)
    except sqlite3.DatabaseError:
        return False


def safe_json_list(values: set[str]) -> str:
    return json.dumps(sorted(value for value in values if value), ensure_ascii=False)


def read_rows(conn: sqlite3.Connection, table: str, wanted: list[str], limit: int) -> list[sqlite3.Row]:
    columns = table_columns(conn, table)
    if not columns:
        return []
    select_parts = [name if name in columns else f"NULL AS {name}" for name in wanted]
    query = f"SELECT {', '.join(select_parts)} FROM {table}"
    if limit > 0:
        query += " LIMIT ?"
        return list(conn.execute(query, (limit,)).fetchall())
    return list(conn.execute(query).fetchall())


def row_value(row: sqlite3.Row, key: str, default: Any = "") -> Any:
    return row[key] if key in row.keys() and row[key] is not None else default


def canonical_host(url: str) -> str:
    canonical = lineage.canonicalize_url(url)
    if not canonical or canonical.startswith("invalid-url:"):
        return ""
    try:
        return urlsplit(canonical).netloc.lower()
    except ValueError:
        return ""


def is_short_url(row: sqlite3.Row) -> bool:
    markers = " ".join(
        str(row_value(row, key, "") or "").lower()
        for key in ["outlink_platform", "source"]
    )
    if "shorturl" in markers or "short_url" in markers:
        return True
    layer = str(row_value(row, "source_layer", "") or "").lower()
    if layer in {"shorturl", "short_url"}:
        return True
    return db2_shorturl_candidates.is_shorturl_like(str(row_value(row, "outlink_url", "") or ""))


def update_url_seen(aggregate: dict[str, dict[str, Any]], row: sqlite3.Row) -> None:
    hashed = lineage.url_key_hash(str(row_value(row, "outlink_url", "") or ""))
    if not hashed:
        return
    seen_at = str(row_value(row, "discovered_at", "") or "")
    entry = aggregate.setdefault(
        hashed,
        {
            "url_key_hash": hashed,
            "seen_count": 0,
            "first_seen_at": seen_at,
            "last_seen_at": seen_at,
            "platforms": set(),
            "sources": set(),
        },
    )
    entry["seen_count"] += 1
    if seen_at:
        if not entry["first_seen_at"] or seen_at < entry["first_seen_at"]:
            entry["first_seen_at"] = seen_at
        if not entry["last_seen_at"] or seen_at > entry["last_seen_at"]:
            entry["last_seen_at"] = seen_at
    platform = str(row_value(row, "outlink_platform", "") or "")
    source = str(row_value(row, "source", "") or "")
    if platform:
        entry["platforms"].add(platform)
    if source:
        entry["sources"].add(source)


def update_avatar_seen(aggregate: dict[str, dict[str, Any]], row: sqlite3.Row) -> None:
    avatar_hash = lineage.url_key_hash(str(row_value(row, "avatar_url", "") or ""))
    if not avatar_hash:
        return
    seen_at = str(row_value(row, "downloaded_at", "") or row_value(row, "created_at", "") or "")
    local_path = str(row_value(row, "local_path", "") or "")
    entry = aggregate.setdefault(
        avatar_hash,
        {
            "avatar_url_hash": avatar_hash,
            "image_sha256": str(row_value(row, "image_sha256", "") or ""),
            "file_size": row_value(row, "file_size", None),
            "width": row_value(row, "width", None),
            "height": row_value(row, "height", None),
            "content_type": str(row_value(row, "content_type", "") or ""),
            "local_path_hash": hash_text(local_path),
            "first_seen_at": seen_at,
            "last_seen_at": seen_at,
        },
    )
    if seen_at:
        if not entry["first_seen_at"] or seen_at < entry["first_seen_at"]:
            entry["first_seen_at"] = seen_at
        if not entry["last_seen_at"] or seen_at > entry["last_seen_at"]:
            entry["last_seen_at"] = seen_at


def update_source_processed(aggregate: dict[tuple[str, str], dict[str, Any]], row: sqlite3.Row) -> None:
    source_url = str(row_value(row, "source_profile_url", "") or "")
    source_hash = lineage.url_key_hash(source_url)
    phase = str(row_value(row, "source_layer", "") or "")
    if phase not in {"linktree_expand", "shorturl_resolve", "ig_bio"} or not source_hash:
        return
    result_hash = lineage.url_key_hash(str(row_value(row, "outlink_url", "") or ""))
    processed_at = str(row_value(row, "discovered_at", "") or "")
    key = (phase, source_hash)
    entry = aggregate.setdefault(
        key,
        {
            "phase": phase,
            "source_url_hash": source_hash,
            "result_url_hashes": set(),
            "result_count": 0,
            "first_processed_at": processed_at,
            "last_processed_at": processed_at,
            "status": "processed",
        },
    )
    if result_hash:
        entry["result_url_hashes"].add(result_hash)
    entry["result_count"] += 1
    if processed_at:
        if not entry["first_processed_at"] or processed_at < entry["first_processed_at"]:
            entry["first_processed_at"] = processed_at
        if not entry["last_processed_at"] or processed_at > entry["last_processed_at"]:
            entry["last_processed_at"] = processed_at


def collect_seed_candidates(live_db: Path, *, limit: int = 0) -> dict[str, Any]:
    conn = connect_readonly(live_db)
    try:
        outlink_rows = read_rows(
            conn,
            "dj_outlinks",
            ["outlink_url", "outlink_platform", "source", "source_layer", "source_profile_url", "discovered_at"],
            limit,
        )
        avatar_rows = read_rows(
            conn,
            "dj_avatars",
            ["avatar_url", "image_sha256", "file_size", "width", "height", "content_type", "local_path", "downloaded_at", "created_at"],
            limit,
        )
    finally:
        conn.close()

    url_seen: dict[str, dict[str, Any]] = {}
    short_urls: dict[str, dict[str, Any]] = {}
    source_processed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in outlink_rows:
        update_url_seen(url_seen, row)
        update_source_processed(source_processed, row)
        if str(row_value(row, "source_layer", "") or "") == "shorturl_resolve":
            source_hash = lineage.url_key_hash(str(row_value(row, "source_profile_url", "") or ""))
            target_hash = lineage.url_key_hash(str(row_value(row, "outlink_url", "") or ""))
            if source_hash and target_hash:
                short_urls[source_hash] = {
                    "short_url_hash": source_hash,
                    "target_url_hash": target_hash,
                    "resolver_status": "resolved",
                    "first_seen_at": str(row_value(row, "discovered_at", "") or ""),
                    "last_seen_at": str(row_value(row, "discovered_at", "") or ""),
                    "seen_count": 1,
                }
        if is_short_url(row):
            short_hash = lineage.url_key_hash(str(row_value(row, "outlink_url", "") or ""))
            if short_hash:
                short_urls.setdefault(
                    short_hash,
                    {
                        "short_url_hash": short_hash,
                        "target_url_hash": "",
                        "resolver_status": "known_unresolved",
                        "first_seen_at": str(row_value(row, "discovered_at", "") or ""),
                        "last_seen_at": str(row_value(row, "discovered_at", "") or ""),
                        "seen_count": 0,
                    },
                )
                short_urls[short_hash]["seen_count"] += 1

    avatars: dict[str, dict[str, Any]] = {}
    for row in avatar_rows:
        update_avatar_seen(avatars, row)

    url_counter = Counter(item["url_key_hash"] for item in url_seen.values())
    duplicate_url_rows = sum(item["seen_count"] - 1 for item in url_seen.values() if item["seen_count"] > 1)
    return {
        "live_db": str(live_db),
        "outlinks_read": len(outlink_rows),
        "avatars_read": len(avatar_rows),
        "url_seen": list(url_seen.values()),
        "short_urls": list(short_urls.values()),
        "avatars": list(avatars.values()),
        "source_processed": list(source_processed.values()),
        "duplicate_url_rows": duplicate_url_rows,
        "distinct_url_hashes": len(url_counter),
    }


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cache_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS url_seen_cache (
          url_key_hash TEXT PRIMARY KEY,
          first_seen_at TEXT NOT NULL DEFAULT '',
          last_seen_at TEXT NOT NULL DEFAULT '',
          seen_count INTEGER NOT NULL DEFAULT 0,
          platforms_json TEXT NOT NULL DEFAULT '[]',
          sources_json TEXT NOT NULL DEFAULT '[]',
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shorturl_cache (
          short_url_hash TEXT PRIMARY KEY,
          target_url_hash TEXT NOT NULL DEFAULT '',
          resolver_status TEXT NOT NULL DEFAULT 'known_unresolved',
          first_seen_at TEXT NOT NULL DEFAULT '',
          last_seen_at TEXT NOT NULL DEFAULT '',
          seen_count INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS avatar_cache (
          avatar_url_hash TEXT PRIMARY KEY,
          image_sha256 TEXT NOT NULL DEFAULT '',
          file_size INTEGER,
          width INTEGER,
          height INTEGER,
          content_type TEXT NOT NULL DEFAULT '',
          local_path_hash TEXT NOT NULL DEFAULT '',
          first_seen_at TEXT NOT NULL DEFAULT '',
          last_seen_at TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_processed_cache (
          phase TEXT NOT NULL,
          source_url_hash TEXT NOT NULL,
          result_hashes_json TEXT NOT NULL DEFAULT '[]',
          result_count INTEGER NOT NULL DEFAULT 0,
          first_processed_at TEXT NOT NULL DEFAULT '',
          last_processed_at TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'processed',
          updated_at TEXT NOT NULL,
          PRIMARY KEY (phase, source_url_hash)
        );
        """
    )
    now = utc_now()
    conn.execute(
        """
        INSERT INTO cache_meta (key, value, updated_at)
        VALUES ('schema_version', '2', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT INTO cache_meta (key, value, updated_at)
        VALUES ('stores_raw_urls', 'false', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (now,),
    )


def upsert_seed(conn: sqlite3.Connection, candidates: dict[str, Any]) -> dict[str, int]:
    ensure_schema(conn)
    now = utc_now()
    counts = {"url_seen": 0, "short_urls": 0, "avatars": 0}
    for item in candidates["url_seen"]:
        conn.execute(
            """
            INSERT INTO url_seen_cache
              (url_key_hash, first_seen_at, last_seen_at, seen_count, platforms_json, sources_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url_key_hash) DO UPDATE SET
              first_seen_at=MIN(url_seen_cache.first_seen_at, excluded.first_seen_at),
              last_seen_at=MAX(url_seen_cache.last_seen_at, excluded.last_seen_at),
              seen_count=MAX(url_seen_cache.seen_count, excluded.seen_count),
              platforms_json=excluded.platforms_json,
              sources_json=excluded.sources_json,
              updated_at=excluded.updated_at
            """,
            (
                item["url_key_hash"],
                item["first_seen_at"],
                item["last_seen_at"],
                int(item["seen_count"]),
                safe_json_list(item["platforms"]),
                safe_json_list(item["sources"]),
                now,
            ),
        )
        counts["url_seen"] += 1
    for item in candidates["short_urls"]:
        conn.execute(
            """
            INSERT INTO shorturl_cache
              (short_url_hash, target_url_hash, resolver_status, first_seen_at, last_seen_at, seen_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(short_url_hash) DO UPDATE SET
              target_url_hash=COALESCE(NULLIF(excluded.target_url_hash, ''), shorturl_cache.target_url_hash),
              resolver_status=excluded.resolver_status,
              first_seen_at=MIN(shorturl_cache.first_seen_at, excluded.first_seen_at),
              last_seen_at=MAX(shorturl_cache.last_seen_at, excluded.last_seen_at),
              seen_count=MAX(shorturl_cache.seen_count, excluded.seen_count),
              updated_at=excluded.updated_at
            """,
            (
                item["short_url_hash"],
                item["target_url_hash"],
                item["resolver_status"],
                item["first_seen_at"],
                item["last_seen_at"],
                int(item["seen_count"]),
                now,
            ),
        )
        counts["short_urls"] += 1
    for item in candidates["avatars"]:
        conn.execute(
            """
            INSERT INTO avatar_cache
              (avatar_url_hash, image_sha256, file_size, width, height, content_type, local_path_hash, first_seen_at, last_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(avatar_url_hash) DO UPDATE SET
              image_sha256=COALESCE(NULLIF(excluded.image_sha256, ''), avatar_cache.image_sha256),
              file_size=COALESCE(excluded.file_size, avatar_cache.file_size),
              width=COALESCE(excluded.width, avatar_cache.width),
              height=COALESCE(excluded.height, avatar_cache.height),
              content_type=COALESCE(NULLIF(excluded.content_type, ''), avatar_cache.content_type),
              local_path_hash=COALESCE(NULLIF(excluded.local_path_hash, ''), avatar_cache.local_path_hash),
              first_seen_at=MIN(avatar_cache.first_seen_at, excluded.first_seen_at),
              last_seen_at=MAX(avatar_cache.last_seen_at, excluded.last_seen_at),
              updated_at=excluded.updated_at
            """,
            (
                item["avatar_url_hash"],
                item["image_sha256"],
                item["file_size"],
                item["width"],
                item["height"],
                item["content_type"],
                item["local_path_hash"],
                item["first_seen_at"],
                item["last_seen_at"],
                now,
            ),
        )
        counts["avatars"] += 1
    counts["source_processed"] = 0
    for item in candidates["source_processed"]:
        conn.execute(
            """
            INSERT INTO source_processed_cache
              (phase, source_url_hash, result_hashes_json, result_count, first_processed_at, last_processed_at, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(phase, source_url_hash) DO UPDATE SET
              result_hashes_json=excluded.result_hashes_json,
              result_count=MAX(source_processed_cache.result_count, excluded.result_count),
              first_processed_at=MIN(source_processed_cache.first_processed_at, excluded.first_processed_at),
              last_processed_at=MAX(source_processed_cache.last_processed_at, excluded.last_processed_at),
              status=excluded.status,
              updated_at=excluded.updated_at
            """,
            (
                item["phase"],
                item["source_url_hash"],
                safe_json_list(item["result_url_hashes"]),
                int(item["result_count"]),
                item["first_processed_at"],
                item["last_processed_at"],
                item["status"],
                now,
            ),
        )
        counts["source_processed"] += 1
    return counts


def _hash_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    result: list[str] = []
    for value in values:
        text = str(value or "")
        if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text.lower()):
            result.append(text.lower())
    return sorted(set(result))


def is_source_processed_phase_allowed(phase: str) -> bool:
    return phase in SOURCE_PROCESSED_PHASES or phase.startswith("avatar_dl:")


def upsert_source_completion_rows(conn: sqlite3.Connection, completions: list[dict[str, Any]]) -> int:
    ensure_schema(conn)
    now = utc_now()
    count = 0
    for item in completions:
        phase = str(item.get("phase") or "")
        source_hash = str(item.get("source_url_hash") or "")
        if not is_source_processed_phase_allowed(phase):
            continue
        if len(source_hash) != 64 or not all(ch in "0123456789abcdef" for ch in source_hash.lower()):
            continue
        result_hashes = _hash_list(item.get("result_url_hashes") or item.get("result_hashes"))
        result_count = int(item.get("result_count") or len(result_hashes))
        processed_at = str(item.get("last_processed_at") or item.get("processed_at") or now)
        status = str(item.get("status") or "processed")
        conn.execute(
            """
            INSERT INTO source_processed_cache
              (phase, source_url_hash, result_hashes_json, result_count, first_processed_at, last_processed_at, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(phase, source_url_hash) DO UPDATE SET
              result_hashes_json=excluded.result_hashes_json,
              result_count=MAX(source_processed_cache.result_count, excluded.result_count),
              first_processed_at=CASE
                WHEN source_processed_cache.first_processed_at = '' THEN excluded.first_processed_at
                WHEN excluded.first_processed_at = '' THEN source_processed_cache.first_processed_at
                ELSE MIN(source_processed_cache.first_processed_at, excluded.first_processed_at)
              END,
              last_processed_at=MAX(source_processed_cache.last_processed_at, excluded.last_processed_at),
              status=excluded.status,
              updated_at=excluded.updated_at
            """,
            (
                phase,
                source_hash.lower(),
                json.dumps(result_hashes, ensure_ascii=False),
                result_count,
                processed_at,
                processed_at,
                status,
                now,
            ),
        )
        count += 1
    return count


def upsert_source_completions(cache_db: Path, completions: list[dict[str, Any]], *, execute: bool = False) -> dict[str, Any]:
    assert_cache_path_allowed(cache_db)
    payload = {
        "cache_db": str(cache_db),
        "completion_count": len(completions),
        "execute": execute,
        "would_write": bool(execute),
        "write_scope": "sidecar_sqlite_only" if execute else "none",
        "live_db_would_write": False,
        "privacy_contract": privacy_contract(),
    }
    if execute:
        conn = connect_cache_writer(cache_db)
        try:
            with conn:
                payload["inserted_or_updated"] = upsert_source_completion_rows(conn, completions)
        finally:
            conn.close()
        payload["status"] = cache_status(cache_db)
    return payload


def privacy_contract() -> dict[str, Any]:
    return {
        "stores_raw_urls": False,
        "stores_raw_local_paths": False,
        "prints_raw_urls": False,
        "key_fields": ["url_key_hash", "short_url_hash", "target_url_hash", "avatar_url_hash", "local_path_hash", "source_url_hash"],
    }


def cache_status(cache_db: Path = DEFAULT_CACHE_DB) -> dict[str, Any]:
    assert_cache_path_allowed(cache_db)
    payload: dict[str, Any] = {
        "cache_db": str(cache_db),
        "cache_exists": cache_db.exists(),
        "would_write": False,
        "privacy_contract": privacy_contract(),
        "storage_policy": {
            "live_db2": "WSL ext4",
            "sidecar_cache_default": "/home/pc/swarm_data/cache",
            "d_drive_allowed": False,
        },
    }
    if not cache_db.exists():
        payload["tables"] = {}
        return payload
    conn = connect_readonly(cache_db)
    try:
        payload["tables"] = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) if table_exists(conn, table) else 0
            for table in ["url_seen_cache", "shorturl_cache", "avatar_cache", "source_processed_cache", "cache_meta"]
        }
    finally:
        conn.close()
    return payload


def seed_from_live(live_db: Path, cache_db: Path = DEFAULT_CACHE_DB, *, limit: int = 0, execute: bool = False) -> dict[str, Any]:
    assert_cache_path_allowed(cache_db)
    candidates = collect_seed_candidates(live_db, limit=limit)
    payload: dict[str, Any] = {
        "live_db": str(live_db),
        "cache_db": str(cache_db),
        "execute": execute,
        "would_write": bool(execute),
        "write_scope": "sidecar_sqlite_only" if execute else "none",
        "live_db_would_write": False,
        "limit": limit,
        "source_counts": {
            "outlinks_read": candidates["outlinks_read"],
            "avatars_read": candidates["avatars_read"],
            "duplicate_url_rows": candidates["duplicate_url_rows"],
        },
        "candidate_counts": {
            "url_seen": len(candidates["url_seen"]),
            "short_urls": len(candidates["short_urls"]),
            "avatars": len(candidates["avatars"]),
            "source_processed": len(candidates["source_processed"]),
        },
        "sample_hashes": {
            "url_seen": [item["url_key_hash"] for item in candidates["url_seen"][:5]],
            "short_urls": [item["short_url_hash"] for item in candidates["short_urls"][:5]],
            "avatars": [item["avatar_url_hash"] for item in candidates["avatars"][:5]],
            "source_processed": [item["source_url_hash"] for item in candidates["source_processed"][:5]],
        },
        "privacy_contract": privacy_contract(),
    }
    if execute:
        conn = connect_cache_writer(cache_db)
        try:
            with conn:
                payload["inserted_or_updated"] = upsert_seed(conn, candidates)
        finally:
            conn.close()
        payload["status"] = cache_status(cache_db)
    return payload


class SidecarCacheLookup:
    def __init__(self, cache_db: Path, conn: sqlite3.Connection | None = None):
        self.cache_db = cache_db
        self.conn = conn
        self.enabled = conn is not None
        self.stats = {
            "enabled": self.enabled,
            "source_processed_hits": 0,
            "url_seen_hits": 0,
            "avatar_seen_hits": 0,
            "lookup_errors": 0,
        }

    @classmethod
    def open(cls, cache_db: Path = DEFAULT_CACHE_DB) -> "SidecarCacheLookup":
        assert_cache_path_allowed(cache_db)
        if not cache_db.exists():
            return cls(cache_db)
        try:
            return cls(cache_db, connect_readonly(cache_db))
        except sqlite3.DatabaseError:
            lookup = cls(cache_db)
            lookup.stats["lookup_errors"] = 1
            return lookup

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
            self.enabled = False

    def _exists(self, table: str, where: str, params: tuple[Any, ...]) -> bool:
        if self.conn is None or not cache_table_ready(self.conn, table):
            return False
        try:
            row = self.conn.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", params).fetchone()
            return row is not None
        except sqlite3.DatabaseError:
            self.stats["lookup_errors"] += 1
            return False

    def source_processed(self, phase: str, source_url: str) -> bool:
        source_hash = lineage.url_key_hash(source_url)
        if not source_hash:
            return False
        hit = self._exists("source_processed_cache", "phase=? AND source_url_hash=?", (phase, source_hash))
        if hit:
            self.stats["source_processed_hits"] += 1
        return hit

    def url_seen(self, url: str) -> bool:
        hashed = lineage.url_key_hash(url)
        if not hashed:
            return False
        hit = self._exists("url_seen_cache", "url_key_hash=?", (hashed,))
        if hit:
            self.stats["url_seen_hits"] += 1
        return hit

    def avatar_seen(self, avatar_url: str) -> bool:
        hashed = lineage.url_key_hash(avatar_url)
        if not hashed:
            return False
        hit = self._exists("avatar_cache", "avatar_url_hash=?", (hashed,))
        if hit:
            self.stats["avatar_seen_hits"] += 1
        return hit

    def status(self) -> dict[str, Any]:
        return {
            "cache_db": str(self.cache_db),
            "enabled": self.enabled,
            "stats": dict(self.stats),
            "would_write": False,
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DB2 hash-first sidecar cache")
    parser.add_argument("--live-db", type=Path, default=DEFAULT_LIVE_DB)
    parser.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.set_defaults(func=lambda args: cache_status(args.cache_db))

    seed = sub.add_parser("seed")
    seed.add_argument("--limit", type=int, default=1000)
    seed.add_argument("--execute", action="store_true")
    seed.set_defaults(func=lambda args: seed_from_live(args.live_db, args.cache_db, limit=args.limit, execute=args.execute))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(json.dumps(args.func(args), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
