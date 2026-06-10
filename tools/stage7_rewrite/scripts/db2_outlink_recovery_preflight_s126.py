from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path


DEFAULT_LIVE_DB = Path("/db2-data/atlas_swarm_data.sqlite")
RESET_CONFIRMATION = "reset-stale-running"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def connect_readwrite(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def count_table(conn: sqlite3.Connection, table_name: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    except sqlite3.Error:
        return 0


def progress_counts(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        return {
            str(status): int(count)
            for status, count in conn.execute("SELECT status, COUNT(*) FROM swarm_progress GROUP BY status").fetchall()
        }
    except sqlite3.Error:
        return {}


def count_stale_running(conn: sqlite3.Connection, now: datetime, ttl_minutes: int) -> int:
    cutoff = now - timedelta(minutes=ttl_minutes)
    try:
        rows = conn.execute(
            "SELECT started_at FROM swarm_progress WHERE status='running'"
        ).fetchall()
    except sqlite3.Error:
        return 0
    stale = 0
    for row in rows:
        started = parse_dt(row[0])
        if started is None:
            stale += 1
        else:
            if started.tzinfo is None:
                started = started.replace(tzinfo=now.tzinfo)
            if started < cutoff:
                stale += 1
    return stale


def classify_running_rows(conn: sqlite3.Connection, now: datetime, ttl_minutes: int) -> dict:
    cutoff = now - timedelta(minutes=ttl_minutes)
    try:
        rows = conn.execute(
            """
            SELECT
              COALESCE(entity_id, '') AS entity_id,
              COALESCE(platform, '') AS platform,
              COALESCE(phase, '') AS phase,
              COALESCE(worker_id, '') AS worker_id,
              started_at
            FROM swarm_progress
            WHERE status='running'
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []

    stale_rows = []
    fresh_rows = []
    unknown_started_at = 0
    for row in rows:
        started = parse_dt(row["started_at"])
        is_stale = False
        if started is None:
            unknown_started_at += 1
            is_stale = True
        else:
            if started.tzinfo is None:
                started = started.replace(tzinfo=now.tzinfo)
            is_stale = started < cutoff
        if is_stale:
            stale_rows.append(row)
        else:
            fresh_rows.append(row)

    def top_counts(key: str) -> list[dict[str, int | str]]:
        counter = Counter(str(row[key] or "") for row in stale_rows)
        return [{"key": value, "count": int(count)} for value, count in counter.most_common(20)]

    return {
        "running_count": len(rows),
        "stale_running_count": len(stale_rows),
        "fresh_running_count": len(fresh_rows),
        "unknown_started_at_count": unknown_started_at,
        "cutoff": cutoff.isoformat(),
        "stale_by_phase": top_counts("phase"),
        "stale_by_platform": top_counts("platform"),
        "stale_by_worker": top_counts("worker_id"),
    }


def count_searxng(conn: sqlite3.Connection) -> int:
    try:
        return int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM dj_outlinks
                WHERE source_layer LIKE '%searx%' OR outlink_platform LIKE '%searx%'
                """
            ).fetchone()[0]
        )
    except sqlite3.Error:
        return 0


def decide(integrity: str, active_workers: int, stale_running: int, searxng_delta: int = 0) -> tuple[str, list[str]]:
    stop_gates: list[str] = []
    if integrity != "ok":
        stop_gates.append("integrity_not_ok")
        return "blocked_integrity", stop_gates
    if searxng_delta > 0:
        stop_gates.append("searxng_delta")
        return "blocked_searxng_delta", stop_gates
    if active_workers > 0 and stale_running > 0:
        stop_gates.append("active_workers_with_stale_running")
        return "blocked_workers_active", stop_gates
    if stale_running > 0:
        return "ready_reset_stale_running", stop_gates
    return "ready_profile_a", stop_gates


def collect_preflight(
    live_db: Path,
    *,
    active_workers: int = 0,
    now_text: str | None = None,
    ttl_minutes: int = 30,
    searxng_baseline: int | None = None,
) -> dict:
    now = parse_dt(now_text) if now_text else datetime.now(timezone(timedelta(hours=8)))
    assert now is not None
    conn = connect_readonly(live_db)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        table_counts = {
            table: count_table(conn, table)
            for table in ["dj_social_profiles", "dj_outlinks", "dj_identity_candidates", "ra_profiles"]
        }
        progress = progress_counts(conn)
        stale_running = count_stale_running(conn, now, ttl_minutes)
        searxng_tagged = count_searxng(conn)
    finally:
        conn.close()
    searxng_delta = 0 if searxng_baseline is None else searxng_tagged - searxng_baseline
    decision, stop_gates = decide(integrity, active_workers, stale_running, searxng_delta)
    return {
        "decision": decision,
        "integrity": integrity,
        "table_counts": table_counts,
        "progress": progress,
        "active_worker_count": active_workers,
        "stale_running_count": stale_running,
        "searxng_tagged_count": searxng_tagged,
        "searxng_delta": searxng_delta,
        "stop_gates": stop_gates,
        "would_write": False,
    }


def build_reset_stale_running_sql(marker: str = "reset_stale_running") -> str:
    safe_marker = marker.replace("'", "''")
    return (
        "UPDATE swarm_progress\n"
        "SET status='pending',\n"
        f"    error_msg=COALESCE(error_msg, '') || ' | {safe_marker}'\n"
        "WHERE status='running';"
    )


def collect_snapshot_proof(snapshot_path: Path | None) -> dict:
    if snapshot_path is None:
        return {
            "snapshot_path": "",
            "exists": False,
            "integrity": "missing_snapshot_path",
            "size_bytes": 0,
            "usable": False,
        }
    proof = {
        "snapshot_path": str(snapshot_path),
        "exists": snapshot_path.exists(),
        "integrity": "missing",
        "size_bytes": 0,
        "usable": False,
    }
    if not snapshot_path.exists() or not snapshot_path.is_file():
        return proof
    proof["size_bytes"] = snapshot_path.stat().st_size
    try:
        conn = connect_readonly(snapshot_path)
        try:
            proof["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
            proof["swarm_progress_rows"] = count_table(conn, "swarm_progress")
        finally:
            conn.close()
    except (sqlite3.Error, FileNotFoundError) as exc:
        proof["integrity"] = f"error: {type(exc).__name__}"
    proof["usable"] = bool(proof["exists"] and proof["size_bytes"] > 0 and proof["integrity"] == "ok")
    return proof


def collect_stale_running_reset_plan(
    live_db: Path,
    *,
    active_workers: int = 0,
    now_text: str | None = None,
    ttl_minutes: int = 30,
    marker: str = "reset_stale_running_s126",
) -> dict:
    now = parse_dt(now_text) if now_text else datetime.now(timezone(timedelta(hours=8)))
    assert now is not None
    conn = connect_readonly(live_db)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        running = classify_running_rows(conn, now, ttl_minutes)
    finally:
        conn.close()

    blockers: list[str] = []
    if integrity != "ok":
        blockers.append("integrity_not_ok")
    if active_workers > 0:
        blockers.append("active_workers_present")
    if running["fresh_running_count"] > 0:
        blockers.append("fresh_running_rows_present")
    if running["stale_running_count"] == 0:
        blockers.append("no_stale_running_rows")

    return {
        "plan": "stale_running_reset",
        "live_db": str(live_db),
        "read_only": True,
        "would_write": False,
        "execute_allowed_after_review": not blockers,
        "blockers": blockers,
        "integrity": integrity,
        "active_worker_count": active_workers,
        "ttl_minutes": ttl_minutes,
        "marker": marker,
        "reset_scope": "all_running_rows",
        "affected_rows_if_executed": running["running_count"],
        "running": running,
        "reset_sql": build_reset_stale_running_sql(marker),
        "safety_notes": [
            "This command only plans the reset and does not mutate DB2.",
            "Do not execute if active workers exist or fresh running rows are present.",
            "Take a DB2 snapshot or operator-approved backup before any execute path is added.",
        ],
    }


def reset_stale_running_with_snapshot_gate(
    live_db: Path,
    *,
    snapshot_path: Path | None = None,
    active_workers: int = 0,
    now_text: str | None = None,
    ttl_minutes: int = 30,
    marker: str = "reset_stale_running_s126",
    execute: bool = False,
    confirm: str = "",
) -> dict:
    plan = collect_stale_running_reset_plan(
        live_db,
        active_workers=active_workers,
        now_text=now_text,
        ttl_minutes=ttl_minutes,
        marker=marker,
    )
    snapshot_proof = collect_snapshot_proof(snapshot_path)
    blockers = list(plan.get("blockers") or [])
    if not snapshot_proof.get("usable"):
        blockers.append("snapshot_proof_not_usable")
    if execute and confirm != RESET_CONFIRMATION:
        blockers.append("confirmation_mismatch")

    payload = {
        "action": "stale_running_reset",
        "live_db": str(live_db),
        "execute": execute,
        "would_write": bool(execute),
        "executed": False,
        "confirmation_required": RESET_CONFIRMATION,
        "plan": plan,
        "snapshot_proof": snapshot_proof,
        "blockers": sorted(set(blockers)),
    }
    if not execute:
        payload["would_write"] = False
        return payload
    if blockers:
        payload["would_write"] = False
        return payload

    now = parse_dt(now_text) if now_text else datetime.now(timezone(timedelta(hours=8)))
    assert now is not None
    conn = connect_readwrite(live_db)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("BEGIN IMMEDIATE")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        running = classify_running_rows(conn, now, ttl_minutes)
        execute_blockers: list[str] = []
        if integrity != "ok":
            execute_blockers.append("integrity_not_ok")
        if active_workers > 0:
            execute_blockers.append("active_workers_present")
        if running["fresh_running_count"] > 0:
            execute_blockers.append("fresh_running_rows_present")
        if running["stale_running_count"] == 0:
            execute_blockers.append("no_stale_running_rows")
        if execute_blockers:
            conn.rollback()
            payload["would_write"] = False
            payload["blockers"] = sorted(set(payload["blockers"] + execute_blockers))
            payload["pre_execute_running"] = running
            return payload
        cursor = conn.execute(build_reset_stale_running_sql(marker))
        changed = cursor.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    after = collect_preflight(live_db, active_workers=active_workers, ttl_minutes=ttl_minutes)
    payload.update(
        {
            "executed": True,
            "rows_changed": changed,
            "pre_execute_running": running,
            "post_preflight": after,
            "blockers": [],
        }
    )
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only DB2 recovery preflight")
    parser.add_argument("--live-db", type=Path, default=DEFAULT_LIVE_DB)
    parser.add_argument("--active-workers", type=int, default=0)
    parser.add_argument("--ttl-minutes", type=int, default=30)
    parser.add_argument("--searxng-baseline", type=int)
    parser.add_argument("--emit-reset-sql", action="store_true")
    parser.add_argument("--emit-reset-plan", action="store_true")
    parser.add_argument("--snapshot-path", type=Path)
    parser.add_argument("--execute-reset", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = collect_preflight(
        args.live_db,
        active_workers=args.active_workers,
        ttl_minutes=args.ttl_minutes,
        searxng_baseline=args.searxng_baseline,
    )
    if args.emit_reset_sql:
        result["reset_stale_running_sql"] = build_reset_stale_running_sql("reset_stale_running_s126")
    if args.emit_reset_plan:
        result["reset_stale_running_plan"] = collect_stale_running_reset_plan(
            args.live_db,
            active_workers=args.active_workers,
            ttl_minutes=args.ttl_minutes,
            marker="reset_stale_running_s126",
        )
    if args.execute_reset:
        result["reset_stale_running_execute"] = reset_stale_running_with_snapshot_gate(
            args.live_db,
            snapshot_path=args.snapshot_path,
            active_workers=args.active_workers,
            ttl_minutes=args.ttl_minutes,
            marker="reset_stale_running_s126",
            execute=True,
            confirm=args.confirm,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
