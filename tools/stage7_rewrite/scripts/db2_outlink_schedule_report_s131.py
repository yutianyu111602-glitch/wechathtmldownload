from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import db2_outlink_existing_data_audit_s130 as existing_data_audit
import db2_outlink_recovery_preflight_s126 as preflight
import db2_shorturl_candidates
import db2_sidecar_cache
import db2_worker_profile_runner
import db2_writer_daemon


DEFAULT_LIVE_DB = Path("/home/pc/swarm_data/atlas_swarm_data.sqlite")
DEFAULT_SPOOL = Path("/home/pc/swarm_data/write_spool")
DEFAULT_CACHE_DB = db2_sidecar_cache.DEFAULT_CACHE_DB
DEFAULT_AVATAR_OUTPUT_DIR = Path("/home/pc/swarm_data/output/avatars")


def compact_existing_audit(audit: dict[str, Any]) -> dict[str, Any]:
    dedupe = dict(audit.get("outlink_dedupe") or {})
    return {
        "would_write": bool(audit.get("would_write", False)),
        "projection_allowed": bool(audit.get("projection_allowed", False)),
        "table_counts": audit.get("table_counts") or {},
        "outlink_dedupe": {
            "rows": dedupe.get("rows", 0),
            "distinct_url_hashes": dedupe.get("distinct_url_hashes", 0),
            "duplicate_url_rows": dedupe.get("duplicate_url_rows", 0),
            "duplicate_url_ratio": dedupe.get("duplicate_url_ratio", 0),
        },
        "top_outlink_platforms": audit.get("top_outlink_platforms") or [],
        "top_source_layers": audit.get("top_source_layers") or [],
    }


def worker_plan_summary(profile: str, only_workers: list[str] | None = None) -> dict[str, Any]:
    worker_scope = "only-worker" if only_workers else "profile"
    plan = db2_worker_profile_runner.build_plan(profile, only_workers, only=bool(only_workers))
    workers = [
        {
            "worker": item["worker"],
            "spool_ready": bool(item.get("spool_ready")),
        }
        for item in plan
    ]
    return {
        "profile": profile,
        "worker_scope": worker_scope,
        "workers": workers,
        "spool_ready_workers": [item["worker"] for item in workers if item["spool_ready"]],
        "not_spool_migrated": [item["worker"] for item in workers if not item["spool_ready"]],
    }


def collect_shorturl_candidate_audit(live_db: Path, cache_db: Path, *, limit: int) -> dict[str, Any]:
    conn = db2_sidecar_cache.connect_readonly(live_db)
    lookup = db2_sidecar_cache.SidecarCacheLookup.open(cache_db)
    try:
        return db2_shorturl_candidates.audit_shorturl_candidates(conn, limit=limit, cache_lookup=lookup)
    finally:
        lookup.close()
        conn.close()


def collect_linktree_candidate_audit(live_db: Path, cache_db: Path, *, limit: int) -> dict[str, Any]:
    conn = db2_sidecar_cache.connect_readonly(live_db)
    lookup = db2_sidecar_cache.SidecarCacheLookup.open(cache_db)
    try:
        rows = list(
            conn.execute(
                """
                SELECT DISTINCT ol.outlink_url
                FROM dj_outlinks ol
                WHERE ol.outlink_platform = 'linktree'
                  AND ol.outlink_url LIKE '%linktr.ee%'
                  AND COALESCE(ol.outlink_url, '') != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM dj_outlinks done
                    WHERE done.source_layer = 'linktree_expand'
                      AND done.source_profile_url = ol.outlink_url
                  )
                """
            ).fetchall()
        )
        bad_patterns = (
            "earn.linktr.ee",
            "business.linktr.ee",
            "linktr.ee/s/",
            "linktr.ee/pricing",
            "linktr.ee/privacy",
            "linktr.ee/terms",
            "linktr.ee/about",
            "linktr.ee/login",
            "linktr.ee/signup",
            "linktr.ee/help",
            "linktr.ee/blog",
            "linktr.ee/developer",
            "linktr.ee/creators",
        )
        filtered = [str(row[0] or "") for row in rows if not any(pattern in str(row[0] or "") for pattern in bad_patterns)]
        selected = filtered[:limit] if limit > 0 else filtered
        source_hits = sum(1 for url in selected if lookup.source_processed("linktree_expand", url))
        return {
            "would_write": False,
            "prints_raw_urls": False,
            "legacy_candidate_total": len(rows),
            "after_bad_url_filter": len(filtered),
            "selected_total": len(selected),
            "source_processed_hits": source_hits,
            "selected_after_source_processed_skip": max(len(selected) - source_hits, 0),
            "zero_yield_risk": bool(selected and source_hits / max(len(selected), 1) > 0.2),
            "sample_hashes": [db2_sidecar_cache.lineage.url_key_hash(url) for url in selected[:5]],
        }
    finally:
        lookup.close()
        conn.close()


def avatar_local_file_exists(avatar_dir: Path, eid: str, platform: str) -> bool:
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        if (avatar_dir / f"{eid}_{platform}{ext}").exists():
            return True
    return False


def collect_avatar_candidate_audit(
    live_db: Path,
    cache_db: Path = DEFAULT_CACHE_DB,
    *,
    limit: int,
    platform: str = "soundcloud",
    avatar_dir: Path = DEFAULT_AVATAR_OUTPUT_DIR,
) -> dict[str, Any]:
    conn = db2_sidecar_cache.connect_readonly(live_db)
    lookup = db2_sidecar_cache.SidecarCacheLookup.open(cache_db)
    try:
        filters = """
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
        """
        legacy_query = f"SELECT sp.eid {filters} ORDER BY sp.eid"
        legacy_params: list[Any] = [platform]
        if limit > 0:
            legacy_query += " LIMIT ?"
            legacy_params.append(limit)
        legacy_rows = [str(row[0] or "") for row in conn.execute(legacy_query, legacy_params).fetchall()]
        legacy_distinct = set(legacy_rows)

        distinct_query = f"""
            WITH selected AS (
              SELECT MIN(sp.rowid) AS rid
              {filters}
              GROUP BY sp.eid, sp.platform
              ORDER BY sp.eid
            )
            SELECT sp.eid, sp.profile_url
            FROM dj_social_profiles sp
            JOIN selected ON sp.rowid = selected.rid
            ORDER BY sp.eid
        """
        distinct_params: list[Any] = [platform]
        if limit > 0:
            distinct_query += " LIMIT ?"
            distinct_params.append(limit)
        selected_rows = [(str(row[0] or ""), str(row[1] or "")) for row in conn.execute(distinct_query, distinct_params).fetchall()]
        selected_eids = [row[0] for row in selected_rows]
        all_distinct_total = int(
            conn.execute(
                f"SELECT COUNT(*) FROM (SELECT sp.eid {filters} GROUP BY sp.eid, sp.platform)",
                (platform,),
            ).fetchone()[0]
        )
        local_file_hits = 0
        source_processed_hits = 0
        remaining_after_pre_crawl_skip = 0
        phase = f"avatar_dl:{platform}"
        for eid, profile_url in selected_rows:
            has_local_file = avatar_local_file_exists(avatar_dir, eid, platform)
            has_source_processed = lookup.source_processed(phase, profile_url)
            if has_local_file:
                local_file_hits += 1
            if has_source_processed:
                source_processed_hits += 1
            if not has_local_file and not has_source_processed:
                remaining_after_pre_crawl_skip += 1
        return {
            "would_write": False,
            "prints_raw_eids": False,
            "prints_raw_paths": False,
            "platform": platform,
            "phase": phase,
            "all_missing_distinct_eids": all_distinct_total,
            "legacy_limited_rows": len(legacy_rows),
            "legacy_limited_distinct_eids": len(legacy_distinct),
            "duplicate_rows_in_legacy_limit": max(len(legacy_rows) - len(legacy_distinct), 0),
            "selected_distinct_eids": len(selected_eids),
            "selected_local_file_hits": local_file_hits,
            "selected_source_processed_hits": source_processed_hits,
            "selected_after_local_file_skip": max(len(selected_eids) - local_file_hits, 0),
            "selected_after_pre_crawl_skip": remaining_after_pre_crawl_skip,
            "sample_eid_hashes": [db2_sidecar_cache.hash_text(eid) for eid in selected_eids[:5]],
        }
    finally:
        lookup.close()
        conn.close()


def collect_worker_candidate_audit(live_db: Path, cache_db: Path, only_workers: list[str] | None, *, limit: int) -> dict[str, Any]:
    if not only_workers:
        return {}
    audits: dict[str, Any] = {}
    if "outlink_expand_shorturl" in only_workers:
        audits["shorturl"] = collect_shorturl_candidate_audit(live_db, cache_db, limit=limit)
    if "outlink_expand_linktree" in only_workers:
        audits["linktree"] = collect_linktree_candidate_audit(live_db, cache_db, limit=limit)
    if "avatar_dl" in only_workers:
        audits["avatar"] = collect_avatar_candidate_audit(live_db, cache_db, limit=limit)
    return audits


def build_schedule_decision(
    *,
    preflight_report: dict[str, Any],
    writer_status: dict[str, Any],
    cache_status: dict[str, Any],
    cache_seed: dict[str, Any],
    worker_plan: dict[str, Any],
    stale_reset_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    production_blockers: list[str] = []
    warnings: list[str] = []
    next_actions: list[str] = []

    stop_gates = list(preflight_report.get("stop_gates") or [])
    production_blockers.extend(stop_gates)
    if preflight_report.get("integrity") != "ok":
        production_blockers.append("integrity_not_ok")
    if preflight_report.get("decision") == "ready_reset_stale_running":
        production_blockers.append("stale_running_requires_reset_before_worker_start")
        next_actions.append("Review db2ctl recovery stale-running-plan before any reset execute path is added.")
        if stale_reset_plan and stale_reset_plan.get("execute_allowed_after_review"):
            next_actions.append("Stale-running reset plan is clean for operator review: no active workers and no fresh running rows.")
    if int(preflight_report.get("searxng_delta") or 0) > 0:
        production_blockers.append("searxng_delta")
    if int(writer_status.get("failed_spool") or 0) > 0:
        production_blockers.append("writer_failed_spool_present")
    if int(writer_status.get("incoming_spool") or 0) > 0 or int(writer_status.get("processing_spool") or 0) > 0:
        production_blockers.append("writer_backlog_present")
    if worker_plan.get("not_spool_migrated"):
        production_blockers.append("full_profile_contains_non_spool_migrated_workers")
        next_actions.append("Use worker-specific one-shot commands for migrated workers only.")
    if not cache_status.get("cache_exists"):
        production_blockers.append("sidecar_cache_missing_for_long_run")
        warnings.append("sidecar_cache_missing")
        next_actions.append("Run db2ctl cache seed --limit 1000 for dry-run evidence before any longer worker run.")

    candidate_counts = dict(cache_seed.get("candidate_counts") or {})
    duplicate_ratio = (cache_seed.get("source_counts") or {}).get("duplicate_url_rows")
    if duplicate_ratio:
        warnings.append("duplicate_existing_rows_present")
    if int(candidate_counts.get("avatars") or 0) > 0:
        next_actions.append("Avatar lane can benefit from avatar_cache after a reviewed sidecar seed.")
    if int(candidate_counts.get("url_seen") or 0) > 0:
        next_actions.append("Outlink lanes can benefit from url_seen_cache after a reviewed sidecar seed.")

    if production_blockers:
        decision = "hold_production"
    elif warnings:
        decision = "ready_after_operator_review"
    else:
        decision = "ready_one_shot_migrated_worker"

    return {
        "decision": decision,
        "production_blockers": sorted(set(production_blockers)),
        "warnings": sorted(set(warnings)),
        "safe_one_shot_workers": worker_plan.get("spool_ready_workers") or [],
        "denied_full_profile_workers": worker_plan.get("not_spool_migrated") or [],
        "next_actions": list(dict.fromkeys(next_actions)),
        "would_write": False,
    }


def collect_schedule_report(
    live_db: Path,
    spool_dir: Path,
    cache_db: Path,
    *,
    profile: str = "safe",
    only_workers: list[str] | None = None,
    limit: int = 20,
    active_workers: int = 0,
) -> dict[str, Any]:
    preflight_report = preflight.collect_preflight(live_db, active_workers=active_workers)
    stale_reset_plan = preflight.collect_stale_running_reset_plan(live_db, active_workers=active_workers)
    writer = db2_writer_daemon.writer_status(spool_dir)
    existing = existing_data_audit.collect_audit(live_db, limit=limit)
    cache_status = db2_sidecar_cache.cache_status(cache_db)
    cache_seed = db2_sidecar_cache.seed_from_live(live_db, cache_db, limit=limit, execute=False)
    worker_plan = worker_plan_summary(profile, only_workers)
    worker_candidate_audit = collect_worker_candidate_audit(live_db, cache_db, only_workers, limit=limit)
    decision = build_schedule_decision(
        preflight_report=preflight_report,
        writer_status=writer,
        cache_status=cache_status,
        cache_seed=cache_seed,
        worker_plan=worker_plan,
        stale_reset_plan=stale_reset_plan,
    )
    return {
        "report": "db2_outlink_schedule_report_s131",
        "profile": profile,
        "only_workers": only_workers or [],
        "read_only": True,
        "would_write": False,
        "projection_allowed": False,
        "preflight": preflight_report,
        "stale_running_reset_plan": stale_reset_plan,
        "writer": writer,
        "existing_data": compact_existing_audit(existing),
        "cache_status": cache_status,
        "cache_seed_dry_run": cache_seed,
        "worker_candidate_audit": worker_candidate_audit,
        "worker_plan": worker_plan,
        "schedule_decision": decision,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only DB2 outlink scheduling report")
    parser.add_argument("--live-db", type=Path, default=DEFAULT_LIVE_DB)
    parser.add_argument("--spool-dir", type=Path, default=DEFAULT_SPOOL)
    parser.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    parser.add_argument("--profile", choices=sorted(db2_worker_profile_runner.PROFILE_WORKERS), default="safe")
    parser.add_argument("--only-worker", action="append", default=[])
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--active-workers", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    print(
        json.dumps(
            collect_schedule_report(
                args.live_db,
                args.spool_dir,
                args.cache_db,
                profile=args.profile,
                only_workers=args.only_worker,
                limit=args.limit,
                active_workers=args.active_workers,
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
