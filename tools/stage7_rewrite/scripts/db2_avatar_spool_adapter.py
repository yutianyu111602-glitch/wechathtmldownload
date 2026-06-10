from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import db2_sidecar_cache
from db2_spool_client import JsonlSpoolClient


DEFAULT_DB = Path(os.environ.get("DB2_SWARM_DB", "/db2-data/atlas_swarm_data.sqlite"))
DEFAULT_SPOOL = Path(os.environ.get("DB2_WRITE_SPOOL", "/db2-spool"))
DEFAULT_AVATAR_DIR = Path(os.environ.get("DB2_AVATAR_OUTPUT_DIR", "/db2-avatar-output"))
DEFAULT_AVATAR_LOCAL_PATH_PREFIX = Path(os.environ.get("DB2_AVATAR_LOCAL_PATH_PREFIX", "/home/pc/swarm_data/output/avatars"))
DEFAULT_LEGACY_SCRIPT = Path(os.environ.get("DB2_AVATAR_SCRIPT", "/db2-scripts/avatar_dl_worker.py"))
DEFAULT_CACHE_DB = Path(os.environ.get("DB2_SIDECAR_CACHE_DB", "/db2-cache/db2_sidecar_cache.sqlite"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def load_legacy_module(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(path)
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("db2_legacy_avatar_dl_worker", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import legacy worker: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def host_visible_avatar_path(save_path: Path, avatar_dir: Path, local_path_prefix: Path) -> str:
    try:
        relative = save_path.resolve().relative_to(avatar_dir.resolve())
    except ValueError:
        return save_path.as_posix()
    return (local_path_prefix / relative).as_posix()


def install_spool_patches(
    legacy: ModuleType,
    db_path: Path,
    avatar_dir: Path,
    local_path_prefix: Path,
    client: JsonlSpoolClient,
    cache_lookup: db2_sidecar_cache.SidecarCacheLookup | None = None,
) -> JsonlSpoolClient:
    avatar_dir.mkdir(parents=True, exist_ok=True)
    legacy.SWARM_DB = Path(db_path)
    legacy.ATLAS_DB = Path(":memory:")
    legacy.AVATAR_DIR = Path(avatar_dir)
    cache_lookup = cache_lookup or db2_sidecar_cache.SidecarCacheLookup(Path(""))
    adapter_stats = {
        "cache_avatar_download_skips": 0,
        "cache_avatar_event_skips": 0,
    }
    original_download_file = getattr(legacy, "download_file", None)

    def swarm_db() -> sqlite3.Connection:
        return connect_readonly(db_path)

    def atlas_db() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        if hasattr(legacy, "ensure_atlas_tables"):
            legacy.ensure_atlas_tables(conn)
        return conn

    def record_swarm_avatar(
        eid: str,
        platform: str,
        handle: str,
        avatar_url: str,
        save_path: Path,
        file_size: int,
    ) -> None:
        if cache_lookup.avatar_seen(avatar_url):
            adapter_stats["cache_avatar_event_skips"] += 1
            return
        client.write_event(
            {
                "op": "insert_avatar",
                "mode": "replace",
                "avatar_id": f"{platform}_{eid}",
                "eid": eid,
                "platform": platform,
                "handle": handle or "",
                "avatar_url": avatar_url,
                "local_path": host_visible_avatar_path(Path(save_path), avatar_dir, local_path_prefix),
                "file_size": int(file_size),
                "downloaded_at": utc_now(),
            }
        )

    def download_file(avatar_url: str, save_path: Path, *args: Any, **kwargs: Any) -> bool:
        if cache_lookup.avatar_seen(avatar_url):
            adapter_stats["cache_avatar_download_skips"] += 1
            return False
        if original_download_file is None:
            return False
        return bool(original_download_file(avatar_url, save_path, *args, **kwargs))

    legacy.swarm_db = swarm_db
    legacy.atlas_db = atlas_db
    legacy.record_swarm_avatar = record_swarm_avatar
    legacy.download_file = download_file
    legacy._DB2_ADAPTER_STATS = adapter_stats
    return client


def select_missing_profiles(conn: sqlite3.Connection, platform: str, limit: int = 0) -> list[dict[str, Any]]:
    query = """
        WITH selected AS (
          SELECT MIN(sp.rowid) AS rid
          FROM dj_social_profiles sp
          WHERE sp.platform = ?
            AND sp.handle IS NOT NULL
            AND sp.handle != ''
            AND sp.profile_url IS NOT NULL
            AND sp.profile_url != ''
            AND sp.profile_url NOT LIKE '%/p/%'
            AND sp.profile_url NOT LIKE '%/reel/%'
            AND sp.profile_url NOT LIKE '%/stories/%'
            AND NOT EXISTS (
              SELECT 1 FROM dj_avatars av
              WHERE av.eid = sp.eid AND av.platform = sp.platform
            )
          GROUP BY sp.eid, sp.platform
          ORDER BY sp.eid
        )
        SELECT sp.eid, sp.entity_name, sp.platform, sp.handle, sp.profile_url
        FROM dj_social_profiles sp
        JOIN selected ON sp.rowid = selected.rid
        ORDER BY sp.eid
    """
    params: list[Any] = [platform]
    if limit and limit > 0:
        query += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(query, params).fetchall()
    cols = ["eid", "entity_name", "platform", "handle", "profile_url"]
    return [dict(zip(cols, row)) for row in rows]


def count_legacy_missing_rows(conn: sqlite3.Connection, platform: str, limit: int = 0) -> int:
    query = """
        SELECT COUNT(*)
        FROM (
          SELECT sp.eid
          FROM dj_social_profiles sp
          WHERE sp.platform = ?
            AND sp.handle IS NOT NULL
            AND sp.handle != ''
            AND sp.profile_url IS NOT NULL
            AND sp.profile_url != ''
            AND sp.profile_url NOT LIKE '%/p/%'
            AND sp.profile_url NOT LIKE '%/reel/%'
            AND sp.profile_url NOT LIKE '%/stories/%'
            AND NOT EXISTS (
              SELECT 1 FROM dj_avatars av
              WHERE av.eid = sp.eid AND av.platform = sp.platform
            )
          ORDER BY sp.eid
    """
    params: list[Any] = [platform]
    if limit and limit > 0:
        query += " LIMIT ?"
        params.append(limit)
    query += ")"
    return int(conn.execute(query, params).fetchone()[0])


def run_platform_deduped(legacy: ModuleType, platform: str, limit: int = 0) -> dict[str, Any]:
    sdb = legacy.swarm_db()
    adb = legacy.atlas_db()
    try:
        if hasattr(legacy, "ensure_atlas_tables"):
            legacy.ensure_atlas_tables(adb)
        profiles = select_missing_profiles(sdb, platform, limit=limit)
        legacy_row_count = count_legacy_missing_rows(sdb, platform, limit=limit)
    finally:
        sdb.close()

    if not profiles:
        legacy._DB2_AVATAR_SOURCE_COMPLETIONS = []
        return {
            "platform": platform,
            "total": 0,
            "downloaded": 0,
            "skipped": 0,
            "dedupe": {
                "selected_distinct_eids": 0,
                "legacy_selected_rows": 0,
                "duplicate_rows_removed": 0,
            },
        }

    downloaded = 0
    skipped = 0
    completions: list[dict[str, Any]] = []
    sleep_sec = getattr(legacy, "PLATFORM_SLEEP", {}).get(platform, 0.5)
    for profile in profiles:
        completion = {
            "phase": f"avatar_dl:{platform}",
            "source_url_hash": db2_sidecar_cache.lineage.url_key_hash(str(profile.get("profile_url") or "")),
            "result_hashes": [],
            "result_count": 0,
            "processed_at": utc_now(),
            "status": "attempted",
        }
        try:
            ok = legacy.process_profile(profile, adb)
            if ok:
                downloaded += 1
                completion["status"] = "downloaded_or_existing"
                completion["result_count"] = 1
            else:
                skipped += 1
                completion["status"] = "skipped_or_failed"
        except Exception as exc:
            skipped += 1
            completion["status"] = "exception"
            log = getattr(legacy, "log", None)
            if log is not None:
                log.error(f"[{platform}] {profile.get('handle', '')}: {exc}")
        if completion["source_url_hash"]:
            completions.append(completion)
        time.sleep(sleep_sec)

    adb.close()
    legacy._DB2_AVATAR_SOURCE_COMPLETIONS = completions
    return {
        "platform": platform,
        "total": len(profiles),
        "downloaded": downloaded,
        "skipped": skipped,
        "dedupe": {
            "selected_distinct_eids": len(profiles),
            "legacy_selected_rows": legacy_row_count,
            "duplicate_rows_removed": max(legacy_row_count - len(profiles), 0),
        },
        "source_completion_count": len(completions),
    }


def run_all_deduped(legacy: ModuleType, limit: int = 0) -> dict[str, Any]:
    platforms = list(getattr(legacy, "EXTRACTORS", {}).keys())
    results: dict[str, Any] = {}
    grand_total = 0
    grand_downloaded = 0
    grand_skipped = 0
    duplicate_rows_removed = 0
    for platform in platforms:
        stats = run_platform_deduped(legacy, platform, limit=limit)
        results[platform] = stats
        grand_total += int(stats.get("total") or 0)
        grand_downloaded += int(stats.get("downloaded") or 0)
        grand_skipped += int(stats.get("skipped") or 0)
        duplicate_rows_removed += int((stats.get("dedupe") or {}).get("duplicate_rows_removed") or 0)
    return {
        "platform": "all",
        "limit": limit,
        "total": grand_total,
        "downloaded": grand_downloaded,
        "skipped": grand_skipped,
        "dedupe": {
            "duplicate_rows_removed": duplicate_rows_removed,
            "selected_distinct_eids": grand_total,
        },
        "by_platform": results,
    }


def parse_adapter_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="Run legacy avatar_dl_worker with DB2 writes redirected to spool")
    parser.add_argument("--legacy-script", type=Path, default=DEFAULT_LEGACY_SCRIPT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--spool-dir", type=Path, default=DEFAULT_SPOOL)
    parser.add_argument("--avatar-dir", type=Path, default=DEFAULT_AVATAR_DIR)
    parser.add_argument("--avatar-local-path-prefix", type=Path, default=DEFAULT_AVATAR_LOCAL_PATH_PREFIX)
    parser.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    parser.add_argument("--spool-batch-size", type=int, default=50)
    parser.add_argument("--disable-cache-lookup", action="store_true")
    return parser.parse_known_args(argv)


def parse_worker_args(worker_args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Avatar DL Worker passthrough")
    parser.add_argument("--platform", "-p", type=str, default=None)
    parser.add_argument("--limit", "-n", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=None, help=argparse.SUPPRESS)
    args, unknown = parser.parse_known_args(worker_args)
    if unknown:
        raise SystemExit(f"unknown avatar worker args: {' '.join(unknown)}")
    return args


def run_legacy(legacy: ModuleType, worker_args: list[str]) -> Any:
    args = parse_worker_args(worker_args)
    if args.dry_run:
        sdb = legacy.swarm_db()
        try:
            rows = {}
            for plat in ["soundcloud", "youtube", "bandcamp", "mixcloud", "twitter", "facebook", "tiktok"]:
                rows[plat] = len(select_missing_profiles(sdb, plat, limit=0))
            return {"dry_run": True, "missing_by_platform": rows}
        finally:
            sdb.close()

    if args.platform and args.platform != "all":
        return run_platform_deduped(legacy, args.platform, limit=args.limit)

    return run_all_deduped(legacy, limit=args.limit)


def main(argv: list[str] | None = None) -> int:
    args, worker_args = parse_adapter_args(argv)
    legacy = load_legacy_module(args.legacy_script)
    client = JsonlSpoolClient(args.spool_dir, prefix="avatar_dl", batch_size=args.spool_batch_size)
    cache_lookup = None if args.disable_cache_lookup else db2_sidecar_cache.SidecarCacheLookup.open(args.cache_db)
    install_spool_patches(legacy, args.db, args.avatar_dir, args.avatar_local_path_prefix, client, cache_lookup)
    try:
        result = run_legacy(legacy, worker_args)
    finally:
        client.flush()
        if cache_lookup is not None:
            cache_status = cache_lookup.status()
            cache_lookup.close()
        else:
            cache_status = {"enabled": False, "would_write": False}
    print(
        json.dumps(
            {
                "adapter": "avatar_dl_spool",
                "avatar_dir": str(args.avatar_dir),
                "cache_lookup": cache_status,
                "cache_skip_stats": getattr(legacy, "_DB2_ADAPTER_STATS", {}),
                "db_readonly": str(args.db),
                "legacy_script": str(args.legacy_script),
                "legacy_result": result,
                "source_completions": getattr(legacy, "_DB2_AVATAR_SOURCE_COMPLETIONS", []),
                "spool": client.status(),
            },
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
