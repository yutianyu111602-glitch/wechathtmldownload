from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any

import db2_shorturl_candidates
import db2_sidecar_cache
from db2_spool_client import JsonlSpoolClient


DEFAULT_DB = Path(os.environ.get("DB2_SWARM_DB", "/db2-data/atlas_swarm_data.sqlite"))
DEFAULT_SPOOL = Path(os.environ.get("DB2_WRITE_SPOOL", "/db2-spool"))
DEFAULT_LEGACY_SCRIPT = Path(os.environ.get("DB2_OUTLINK_EXPAND_SCRIPT", "/db2-scripts/outlink_expand_worker.py"))
DEFAULT_CACHE_DB = Path(os.environ.get("DB2_SIDECAR_CACHE_DB", "/db2-cache/db2_sidecar_cache.sqlite"))


def fallback_stable_id(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:16]


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
    spec = importlib.util.spec_from_file_location("db2_legacy_outlink_expand_worker", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot import legacy worker: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _legacy_now(legacy: ModuleType) -> str:
    if hasattr(legacy, "now_iso"):
        return str(legacy.now_iso())
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _legacy_worker_id(legacy: ModuleType) -> str:
    return str(getattr(legacy, "WORKER_ID", "outlink_expand_spool"))


def _legacy_stable_id(legacy: ModuleType, *parts: str) -> str:
    if hasattr(legacy, "stable_id"):
        return str(legacy.stable_id(*parts))
    return fallback_stable_id(*parts)


def install_spool_patches(
    legacy: ModuleType,
    db_path: Path,
    client: JsonlSpoolClient,
    cache_lookup: db2_sidecar_cache.SidecarCacheLookup | None = None,
) -> JsonlSpoolClient:
    legacy._USE_DB = Path(db_path)
    cache_lookup = cache_lookup or db2_sidecar_cache.SidecarCacheLookup(Path(""))
    adapter_stats = {
        "cache_source_skips": 0,
        "cache_output_skips": 0,
    }
    source_completions: dict[tuple[str, str], dict[str, Any]] = {}
    cache_source_hit_hashes: set[str] = set()
    original_fetch_linktree_page = getattr(legacy, "fetch_linktree_page", None)
    original_extract_links = getattr(legacy, "extract_links_from_linktree_html", None)
    original_resolve_short_url = getattr(legacy, "resolve_short_url", None)

    def record_source_completion(
        phase: str,
        source_url: str,
        *,
        result_urls: list[str] | None = None,
        result_count: int | None = None,
        output_attempt_delta: int = 0,
        output_saved_delta: int = 0,
        output_skip_delta: int = 0,
        status: str | None = None,
    ) -> None:
        source_hash = db2_sidecar_cache.lineage.url_key_hash(source_url)
        if not source_hash or source_hash in cache_source_hit_hashes:
            return
        now = _legacy_now(legacy)
        key = (phase, source_hash)
        entry = source_completions.setdefault(
            key,
            {
                "phase": phase,
                "source_url_hash": source_hash,
                "result_url_hashes": set(),
                "result_count": 0,
                "first_processed_at": now,
                "last_processed_at": now,
                "status": "processed",
                "output_attempt_count": 0,
                "output_saved_count": 0,
                "output_skip_count": 0,
            },
        )
        entry["last_processed_at"] = now
        if result_urls:
            for result_url in result_urls:
                result_hash = db2_sidecar_cache.lineage.url_key_hash(result_url)
                if result_hash:
                    entry["result_url_hashes"].add(result_hash)
        if result_count is not None:
            entry["result_count"] = max(int(entry["result_count"]), int(result_count))
        else:
            entry["result_count"] = max(int(entry["result_count"]), len(entry["result_url_hashes"]))
        entry["output_attempt_count"] += int(output_attempt_delta)
        entry["output_saved_count"] += int(output_saved_delta)
        entry["output_skip_count"] += int(output_skip_delta)
        if status:
            entry["status"] = status

    def finalized_source_completions() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entry in source_completions.values():
            result_hashes = sorted(entry["result_url_hashes"])
            status = "processed"
            if entry.get("status") not in {"processed", ""}:
                status = str(entry["status"])
            elif int(entry["result_count"]) == 0:
                status = "no_links"
            elif entry["output_attempt_count"] > 0 and entry["output_saved_count"] == 0:
                status = "duplicate_only"
            rows.append(
                {
                    "phase": entry["phase"],
                    "source_url_hash": entry["source_url_hash"],
                    "result_url_hashes": result_hashes,
                    "result_count": int(entry["result_count"]),
                    "first_processed_at": entry["first_processed_at"],
                    "last_processed_at": entry["last_processed_at"],
                    "status": status,
                    "output_attempt_count": int(entry["output_attempt_count"]),
                    "output_saved_count": int(entry["output_saved_count"]),
                    "output_skip_count": int(entry["output_skip_count"]),
                }
            )
        adapter_stats["source_completion_count"] = len(rows)
        adapter_stats["source_completion_duplicate_only"] = sum(1 for row in rows if row["status"] == "duplicate_only")
        adapter_stats["source_completion_no_links"] = sum(1 for row in rows if row["status"] == "no_links")
        return rows

    def get_db() -> sqlite3.Connection:
        return connect_readonly(db_path)

    def locked_commit(_conn: sqlite3.Connection | None = None) -> None:
        client.flush()

    def mark_swarm_progress(_conn: sqlite3.Connection, url: str, phase: str, status: str) -> None:
        now = _legacy_now(legacy)
        client.write_event(
            {
                "op": "insert_progress",
                "entity_id": str(url)[:64],
                "platform": "linktree",
                "phase": phase,
                "status": status,
                "worker_id": _legacy_worker_id(legacy),
                "started_at": now if status == "in_progress" else None,
                "finished_at": now if status in {"completed", "failed", "done"} else None,
                "result_count": 0,
            }
        )

    def save_outlink(
        _conn: sqlite3.Connection,
        eid: str,
        outlink_url: str,
        platform: str,
        handle: str,
        entity_name: str,
        source_layer: str,
        source_profile_url: str,
        profile_platform: str = "",
    ) -> bool:
        if source_layer in {"linktree_expand", "shorturl_resolve", "ig_bio"}:
            record_source_completion(
                source_layer,
                source_profile_url,
                result_urls=[outlink_url],
                output_attempt_delta=1,
            )
        if cache_lookup.url_seen(outlink_url):
            adapter_stats["cache_output_skips"] += 1
            if source_layer in {"linktree_expand", "shorturl_resolve", "ig_bio"}:
                record_source_completion(source_layer, source_profile_url, output_skip_delta=1)
            return False
        client.write_event(
            {
                "op": "insert_outlink",
                "outlink_id": _legacy_stable_id(legacy, "outlink_expand", eid, outlink_url),
                "eid": eid or "",
                "profile_id": "",
                "outlink_url": outlink_url,
                "outlink_platform": platform,
                "handle": handle or "",
                "entity_name": entity_name or "",
                "source_layer": source_layer,
                "source_profile_url": source_profile_url,
                "profile_platform": profile_platform,
                "discovered_at": _legacy_now(legacy),
                "source": "outlink_expand_worker.spool_adapter",
            }
        )
        if source_layer in {"linktree_expand", "shorturl_resolve", "ig_bio"}:
            record_source_completion(source_layer, source_profile_url, output_saved_delta=1)
        return True

    def fetch_linktree_page(url: str, *args: Any, **kwargs: Any) -> str | None:
        if cache_lookup.source_processed("linktree_expand", url):
            adapter_stats["cache_source_skips"] += 1
            source_hash = db2_sidecar_cache.lineage.url_key_hash(url)
            if source_hash:
                cache_source_hit_hashes.add(source_hash)
            return "<html></html>"
        if original_fetch_linktree_page is None:
            return None
        return original_fetch_linktree_page(url, *args, **kwargs)

    def extract_links_from_linktree_html(html: str, source_url: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        if original_extract_links is None:
            links: list[dict[str, Any]] = []
        else:
            links = list(original_extract_links(html, source_url, *args, **kwargs) or [])
        record_source_completion(
            "linktree_expand",
            source_url,
            result_urls=[str(link.get("url") or "") for link in links if isinstance(link, dict)],
            result_count=len(links),
        )
        return links

    def resolve_short_url(url: str, *args: Any, **kwargs: Any) -> str:
        if cache_lookup.source_processed("shorturl_resolve", url):
            adapter_stats["cache_source_skips"] += 1
            return url
        if original_resolve_short_url is None:
            return url
        return str(original_resolve_short_url(url, *args, **kwargs))

    def expand_short_urls(limit: int = 0, sleep_sec: float = 0.5) -> dict[str, Any]:
        conn = get_db()
        rows = db2_shorturl_candidates.select_shorturl_candidates(conn, limit=limit, include_landing=False)
        if not rows:
            conn.close()
            return {"phase": "shorturl", "processed": 0, "resolved": 0, "candidate_selector": "host_redirect_only"}

        stats = Counter()
        resolved_count = 0
        new_outlinks = 0
        start_time = time.time()
        for index, (url, entity_name, eid, _platform) in enumerate(rows):
            try:
                resolved = resolve_short_url(str(url))
                if resolved and resolved != url:
                    resolved_count += 1
                    classified = legacy.classify_url(resolved) if hasattr(legacy, "classify_url") else None
                    plat = classified["platform"] if classified else "other"
                    handle = classified["handle"] if classified else ""
                    saved = save_outlink(
                        conn,
                        eid=eid or "",
                        outlink_url=resolved,
                        platform=plat,
                        handle=handle,
                        entity_name=entity_name or "",
                        source_layer="shorturl_resolve",
                        source_profile_url=str(url),
                        profile_platform="shorturl",
                    )
                    if saved:
                        new_outlinks += 1
                        stats[f"resolve_{plat}"] += 1
                else:
                    record_source_completion(
                        "shorturl_resolve",
                        str(url),
                        result_count=0,
                        status="unresolved",
                    )
                if (index + 1) % 10 == 0 and hasattr(legacy, "log"):
                    elapsed = time.time() - start_time
                    rate = (index + 1) / max(elapsed, 0.1)
                    legacy.log.info(
                        "  [%s/%s] shorturl_host_filtered resolved=%s new_outlinks=%s | %.1f/s",
                        index + 1,
                        len(rows),
                        resolved_count,
                        new_outlinks,
                        rate,
                    )
            except Exception as exc:
                if hasattr(legacy, "log"):
                    legacy.log.error("  [%s/%s] shorturl_host_filtered error: %s", index + 1, len(rows), exc)
            if sleep_sec:
                time.sleep(sleep_sec)

        locked_commit(conn)
        elapsed = time.time() - start_time
        conn.close()
        return {
            "phase": "shorturl",
            "processed": len(rows),
            "resolved": resolved_count,
            "new_outlinks": new_outlinks,
            "candidate_selector": "host_redirect_only",
            "platforms": {key.replace("resolve_", ""): int(value) for key, value in stats.items()},
            "elapsed_sec": round(elapsed, 1),
        }

    legacy.get_db = get_db
    legacy.locked_commit = locked_commit
    legacy.mark_swarm_progress = mark_swarm_progress
    legacy.save_outlink = save_outlink
    legacy.fetch_linktree_page = fetch_linktree_page
    legacy.extract_links_from_linktree_html = extract_links_from_linktree_html
    legacy.resolve_short_url = resolve_short_url
    legacy.expand_short_urls = expand_short_urls
    legacy._DB2_ADAPTER_STATS = adapter_stats
    legacy._DB2_SOURCE_COMPLETIONS = finalized_source_completions
    return client


def selected_phase(worker_args: list[str]) -> str:
    for index, arg in enumerate(worker_args):
        if arg == "--phase" and index + 1 < len(worker_args):
            return worker_args[index + 1]
        if arg.startswith("--phase="):
            return arg.split("=", 1)[1]
    return "all"


def ensure_allowed_worker_args(worker_args: list[str], *, allow_igbio: bool = False) -> None:
    phase = selected_phase(worker_args)
    if phase in {"all", "igbio"} and not allow_igbio:
        raise SystemExit("outlink_expand spool adapter only allows --phase linktree or --phase shorturl")


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(description="Run legacy outlink_expand_worker with DB writes redirected to DB2 spool")
    parser.add_argument("--legacy-script", type=Path, default=DEFAULT_LEGACY_SCRIPT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--spool-dir", type=Path, default=DEFAULT_SPOOL)
    parser.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    parser.add_argument("--spool-batch-size", type=int, default=100)
    parser.add_argument("--allow-igbio", action="store_true")
    parser.add_argument("--disable-cache-lookup", action="store_true")
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> int:
    args, worker_args = parse_args(argv)
    ensure_allowed_worker_args(worker_args, allow_igbio=args.allow_igbio)
    legacy = load_legacy_module(args.legacy_script)
    client = JsonlSpoolClient(args.spool_dir, prefix="outlink_expand", batch_size=args.spool_batch_size)
    cache_lookup = None if args.disable_cache_lookup else db2_sidecar_cache.SidecarCacheLookup.open(args.cache_db)
    install_spool_patches(legacy, args.db, client, cache_lookup)
    old_argv = sys.argv
    sys.argv = [str(args.legacy_script), *worker_args]
    try:
        result = legacy.main()
    finally:
        sys.argv = old_argv
        client.flush()
        if cache_lookup is not None:
            cache_status = cache_lookup.status()
            cache_lookup.close()
        else:
            cache_status = {"enabled": False, "would_write": False}
    print(
        json.dumps(
            {
                "adapter": "outlink_expand_spool",
                "cache_lookup": cache_status,
                "cache_skip_stats": getattr(legacy, "_DB2_ADAPTER_STATS", {}),
                "legacy_script": str(args.legacy_script),
                "db_readonly": str(args.db),
                "spool": client.status(),
                "source_completions": legacy._DB2_SOURCE_COMPLETIONS() if hasattr(legacy, "_DB2_SOURCE_COMPLETIONS") else [],
                "legacy_result": result,
            },
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
