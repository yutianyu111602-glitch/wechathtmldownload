#!/usr/bin/env python3
"""Generic DB2 Write Spool Redirector — intercepts sqlite3.connect()
and redirects write operations to JSONL spool files.

Usage: DB2_WRITE_MODE=spool python3 generic_spool_adapter.py \\
  --legacy-script /home/pc/scripts/sc_deep_worker.py --source sc_deep --execute
"""
import argparse, hashlib, importlib.util, json, os, re, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any


SPOOL_BATCH = 50


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def stable_hash(*parts):
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:24]


class _CursorProxy:
    """Wraps a real sqlite3.Cursor, intercepting execute() for writes."""
    __slots__ = ("_cur", "_spool")

    def __init__(self, cursor, spool):
        object.__setattr__(self, "_cur", cursor)
        object.__setattr__(self, "_spool", spool)

    def execute(self, sql, params=None):
        cur = object.__getattribute__(self, "_cur")
        spool = object.__getattribute__(self, "_spool")
        sql_upper = sql.strip().upper()
        op = None
        for prefix in ("INSERT", "UPDATE", "DELETE", "REPLACE"):
            if sql_upper.startswith(prefix):
                op = prefix.lower()
                break
        if op:
            spool.enqueue(op, sql)
            return cur
        return cur.execute(sql, params or ())

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_cur"), name)

    def __setattr__(self, name, value):
        try:
            object.__setattr__(self, name, value)
        except AttributeError:
            setattr(object.__getattribute__(self, "_cur"), name, value)

    def __iter__(self):
        return iter(object.__getattribute__(self, "_cur"))


class _ConnProxy:
    """Wraps sqlite3.Connection, returning _CursorProxy from cursor()."""
    __slots__ = ("_conn", "_spool")

    def __init__(self, conn, spool):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_spool", spool)

    def cursor(self, factory=None):
        conn = object.__getattribute__(self, "_conn")
        cur = conn.cursor(factory)
        return _CursorProxy(cur, object.__getattribute__(self, "_spool"))

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_conn"), name)

    def __setattr__(self, name, value):
        try:
            object.__setattr__(self, name, value)
        except AttributeError:
            setattr(object.__getattribute__(self, "_conn"), name, value)

    def __enter__(self):
        object.__getattribute__(self, "_conn").__enter__()
        return self

    def __exit__(self, *args):
        return object.__getattribute__(self, "_conn").__exit__(*args)


class SpoolWriter:
    def __init__(self, spool_dir, source="generic"):
        self.dir = Path(spool_dir)
        self.source = source
        self.buffer = []
        self.flushed = 0
        self.events = 0
        self.stats = {"insert": 0, "update": 0, "delete": 0, "replace": 0}

    def enqueue(self, op, sql):
        self.stats[op] = self.stats.get(op, 0) + 1
        self.events += 1
        table = "unknown"
        m = re.search(r"(?:INTO|FROM|UPDATE)\s+(\w+)", sql, re.I)
        if m:
            table = m.group(1)
        self.buffer.append({
            "schema": "db2_spool_redirect.v1",
            "ts": now_iso(),
            "source": self.source,
            "op": op,
            "table": table,
            "hash": stable_hash(sql, str(self.events)),
        })
        if len(self.buffer) >= SPOOL_BATCH:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        (self.dir / "incoming").mkdir(parents=True, exist_ok=True)
        ts = now_iso().replace(":", "").replace("-", "")[:15]
        path = self.dir / "incoming" / f"{self.source}_{ts}_{self.flushed:04d}.jsonl"
        path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.buffer))
        self.flushed += 1
        self.buffer.clear()

    def enable(self):
        _real = sqlite3.connect
        spool = self

        def patched(*args, **kwargs):
            return _ConnProxy(_real(*args, **kwargs), spool)

        sqlite3.connect = patched

    def summary(self):
        self.flush()
        return {
            "source": self.source,
            "events": self.events,
            "files": self.flushed,
            "stats": dict(self.stats),
        }


def load_legacy(path):
    sys.path.insert(0, str(path.parent.resolve()))
    spec = importlib.util.spec_from_file_location("db2_legacy_" + path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def run(legacy_path, spool):
    mod = load_legacy(legacy_path)
    spool.enable()
    old_argv = sys.argv
    try:
        sys.argv = [str(legacy_path)]
        if hasattr(mod, "main"):
            mod.main()
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv
    return spool.summary()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--legacy-script", required=True)
    p.add_argument("--spool-dir", default=os.environ.get("DB2_WRITE_SPOOL", "/home/pc/swarm_data/write_spool"))
    p.add_argument("--source", default="generic_spool")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    if not args.execute:
        print(json.dumps({"mode": "dry_run", "script": args.legacy_script}))
        return

    spool = SpoolWriter(args.spool_dir, args.source)
    summary = run(Path(args.legacy_script), spool)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
