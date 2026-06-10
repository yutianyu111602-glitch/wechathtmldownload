from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB = Path(os.environ.get("DB2_SWARM_DB", "/db2-data/atlas_swarm_data.sqlite"))
DEFAULT_SPOOL = Path(os.environ.get("DB2_WRITE_SPOOL", "/db2-spool"))
DEFAULT_LOCK = Path(os.environ.get("DB2_WRITE_LOCK", "/db2-data/.db_write.lock"))

ALLOWED_TABLES = {
    "dj_outlinks",
    "dj_social_profiles",
    "swarm_progress",
    "dj_avatars",
    "dj_identity_candidates",
    "dj_followed_ig",
}

OP_ALIASES = {
    "insert_outlink": "dj_outlinks",
    "insert_profile": "dj_social_profiles",
    "insert_avatar": "dj_avatars",
    "insert_identity_candidate": "dj_identity_candidates",
    "insert_progress": "swarm_progress",
}

INTERNAL_EVENT_KEYS = {"op", "table", "row", "mode"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def connect_writer(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=60, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    return conn


@contextmanager
def write_tx(conn: sqlite3.Connection, max_retries: int = 8, metrics: dict[str, Any] | None = None):
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        if metrics is not None:
            metrics["write_tx_attempts"] = int(metrics.get("write_tx_attempts", 0)) + 1
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
                return
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as exc:
            last_exc = exc
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            if metrics is not None:
                metrics["lock_retries"] = int(metrics.get("lock_retries", 0)) + 1
            time.sleep(min(8.0, 0.25 * (2**attempt)))
    if last_exc:
        raise last_exc


@contextmanager
def exclusive_file_lock(lock_path: Path, metrics: dict[str, Any] | None = None):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if os.name == "posix":
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        if metrics is not None:
            metrics["file_lock_path"] = str(lock_path)
            metrics["file_lock_acquired"] = True
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def ensure_spool_dirs(spool_dir: Path) -> dict[str, Path]:
    dirs = {
        "incoming": spool_dir / "incoming",
        "processing": spool_dir / "processing",
        "done": spool_dir / "done",
        "failed": spool_dir / "failed",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def writer_status(spool_dir: Path) -> dict[str, Any]:
    dirs = ensure_spool_dirs(spool_dir)
    counts = {name: len(list(path.glob("*.jsonl"))) for name, path in dirs.items()}
    bytes_by_dir = {name: sum(file.stat().st_size for file in path.glob("*.jsonl")) for name, path in dirs.items()}
    return {
        "spool_dir": str(spool_dir),
        "incoming_spool": counts["incoming"],
        "processing_spool": counts["processing"],
        "done_spool": counts["done"],
        "failed_spool": counts["failed"],
        "incoming_bytes": bytes_by_dir["incoming"],
        "processing_bytes": bytes_by_dir["processing"],
        "done_bytes": bytes_by_dir["done"],
        "failed_bytes": bytes_by_dir["failed"],
        "spool_backlog": counts["incoming"] + counts["processing"] + counts["failed"],
        "spool_bytes": sum(bytes_by_dir.values()),
    }


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        raise ValueError(f"missing table: {table}")
    return {row["name"] for row in rows}


def normalize_event(event: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    # New: action-based format from ig_nuclear_fission spool (action=upsert + table + data)
    action = str(event.get("action", "")).strip().lower()
    if action in {"upsert", "insert", "update"}:
        table = str(event.get("table", "")).strip()
        if not table:
            raise ValueError("action-based event missing table")
        row = {key: value for key, value in event.items() if key not in {"action", "table"}}
        mode = "replace" if action == "upsert" else "ignore"
        if not row:
            raise ValueError("empty row")
        return table, row, mode

    # Original op-based format
    op = str(event.get("op", "")).strip()
    if op in OP_ALIASES:
        table = OP_ALIASES[op]
        row = {key: value for key, value in event.items() if key not in INTERNAL_EVENT_KEYS}
        mode = str(event.get("mode", "ignore"))
    elif op == "insert":
        table = str(event.get("table", "")).strip()
        row = dict(event.get("row") or {})
        mode = str(event.get("mode", "ignore"))
    else:
        raise ValueError(f"unknown op: {op}")

    if table not in ALLOWED_TABLES:
        raise ValueError(f"table not allowed: {table}")
    if not row:
        raise ValueError("empty row")
    if mode not in {"ignore", "replace"}:
        raise ValueError(f"unsupported mode: {mode}")
    return table, row, mode


def apply_insert(conn: sqlite3.Connection, table: str, row: dict[str, Any], mode: str) -> None:
    columns = table_columns(conn, table)
    filtered = {key: value for key, value in row.items() if key in columns}
    if "created_at" in columns and "created_at" not in filtered:
        filtered["created_at"] = utc_now()
    if "updated_at" in columns and "updated_at" not in filtered:
        filtered["updated_at"] = utc_now()
    if not filtered:
        raise ValueError(f"no valid columns for table: {table}")

    verb = "INSERT OR IGNORE" if mode == "ignore" else "INSERT OR REPLACE"
    names = list(filtered)
    placeholders = ", ".join(["?"] * len(names))
    quoted = ", ".join(names)
    values = [filtered[name] for name in names]
    conn.execute(f"{verb} INTO {table} ({quoted}) VALUES ({placeholders})", values)


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid json line {lineno}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"line {lineno} is not an object")
            normalize_event(event)
            events.append(event)
    return events


def summarize_events(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_op: dict[str, int] = {}
    by_table: dict[str, int] = {}
    for event in events:
        op = str(event.get("op", "")).strip()
        table, _row, _mode = normalize_event(event)
        by_op[op] = by_op.get(op, 0) + 1
        by_table[table] = by_table.get(table, 0) + 1
    return {"events_by_op": by_op, "events_by_table": by_table}


def merge_count_maps(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def process_spool_file(conn: sqlite3.Connection, path: Path) -> int:
    events = load_events(path)
    with write_tx(conn):
        for event in events:
            table, row, mode = normalize_event(event)
            apply_insert(conn, table, row, mode)
    return len(events)


def process_once(db_path: Path, spool_dir: Path, *, execute: bool = False, lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    started = time.monotonic()
    dirs = ensure_spool_dirs(spool_dir)
    incoming = sorted(dirs["incoming"].glob("*.jsonl"))
    summary: dict[str, Any] = {
        "execute": execute,
        "processed_files": 0,
        "processed_events": 0,
        "failed_files": 0,
        "events_by_op": {},
        "events_by_table": {},
        "file_lock_acquired": False,
        "file_lock_path": str(lock_path),
        "lock_retries": 0,
        "write_tx_attempts": 0,
    }
    if not incoming:
        if execute:
            with exclusive_file_lock(lock_path, summary):
                pass
        summary.update(writer_status(spool_dir))
        summary["duration_sec"] = round(time.monotonic() - started, 4)
        return summary

    conn: sqlite3.Connection | None = None
    try:
        lock_context = exclusive_file_lock(lock_path, summary) if execute else nullcontext()
        with lock_context:
            if execute:
                conn = connect_writer(db_path)
            for source in incoming:
                if execute:
                    processing = dirs["processing"] / source.name
                    os.replace(source, processing)
                else:
                    processing = source
                try:
                    events = load_events(processing)
                    event_summary = summarize_events(events)
                    merge_count_maps(summary["events_by_op"], event_summary["events_by_op"])
                    merge_count_maps(summary["events_by_table"], event_summary["events_by_table"])
                    if execute and conn is not None:
                        with write_tx(conn, metrics=summary):
                            for event in events:
                                table, row, mode = normalize_event(event)
                                apply_insert(conn, table, row, mode)
                        os.replace(processing, dirs["done"] / processing.name)
                    summary["processed_files"] += 1
                    summary["processed_events"] += len(events)
                except Exception:
                    summary["failed_files"] += 1
                    summary["last_error"] = {"file": processing.name, "type": "validation_or_write_error"}
                    if execute:
                        os.replace(processing, dirs["failed"] / processing.name)
                    raise
    finally:
        if conn is not None:
            conn.close()
    summary.update(writer_status(spool_dir))
    summary["duration_sec"] = round(time.monotonic() - started, 4)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Single-writer daemon for DB2 JSONL spool events")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--spool-dir", type=Path, default=DEFAULT_SPOOL)
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Actually write to SQLite; default is dry-run validation")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.status:
        print(json.dumps(writer_status(args.spool_dir), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    execute = args.execute or env_truthy(os.environ.get("DB2_WRITER_EXECUTE"))
    while True:
        result = process_once(args.db, args.spool_dir, execute=execute, lock_path=args.lock_path)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if args.once:
            return 0
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    raise SystemExit(main())
