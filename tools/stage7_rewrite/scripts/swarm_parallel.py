#!/usr/bin/env python3
"""DB2 Parallel Worker Architecture — each worker gets its own SQLite DB,
runs independently, then all merge into main DB with hash dedup.

Pattern:
  main DB:           /home/pc/swarm_data/atlas_swarm_data.sqlite (read-only during work)
  worker DBs:        /home/pc/swarm_data/swarm_work_<name>.sqlite (isolated write)
  merge:             dedup by url_key_hash → INSERT OR IGNORE into main

Usage:
  python3 swarm_parallel.py setup          — create worker DBs
  python3 swarm_parallel.py launch <name>  — launch one worker
  python3 swarm_parallel.py merge          — merge all worker DBs
  python3 swarm_parallel.py run-all        — setup + launch-all + wait + merge
"""

import hashlib, json, os, shutil, sqlite3, subprocess, sys, time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

MAIN_DB = Path("/home/pc/swarm_data/atlas_swarm_data.sqlite")
WORK_DIR = Path("/home/pc/swarm_data/swarm_parallel_work")
SCRIPTS = Path("/home/pc/scripts")
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

WORKERS = {
    "ig_fission": {
        "cmd": ["python3", "-u", str(SCRIPTS / "ig_nuclear_fission_v2.py"),
                "--worker-id", "1", "--worker-count", "1"],
        "db_vars": ["DB", "SWARM_DB"],
    },
    "sc_deep": {
        "cmd": ["python3", "-u", str(SCRIPTS / "sc_deep_worker.py"),
                "--max-profiles", "500"],
        "db_vars": ["DB", "SWARM_DB"],
    },
    "domestic": {
        "cmd": ["python3", "-u", str(SCRIPTS / "domestic_worker.py")],
        "db_vars": ["SWARM_DB"],
    },
}

SCHEMA_TABLES = [
    "dj_outlinks", "dj_social_profiles", "swarm_progress",
    "dj_avatars", "dj_identity_candidates",
]

DEDUP_COLUMNS = {
    "dj_outlinks": ("url_key_hash",),
    "dj_social_profiles": ("profile_url",),
    "dj_avatars": ("avatar_url_hash",),
    "swarm_progress": ("task_id",),
    "dj_identity_candidates": ("candidate_id",),
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def get_table_schema(db, table):
    row = db.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'").fetchone()
    return row[0] if row else None


def setup_worker_dbs():
    """Clone main DB schema into per-worker DBs (no data, just tables)."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    main = sqlite3.connect(str(MAIN_DB))
    main.row_factory = sqlite3.Row
    
    for name in WORKERS:
        wdb_path = WORK_DIR / f"swarm_{name}.sqlite"
        if wdb_path.exists():
            wdb_path.unlink()
        wdb = sqlite3.connect(str(wdb_path))
        wdb.execute("PRAGMA journal_mode=WAL")
        wdb.execute("PRAGMA synchronous=NORMAL")
        
        for table in SCHEMA_TABLES:
            schema = get_table_schema(main, table)
            if schema:
                wdb.execute(schema)
        
        # Also create indexes
        for idx_row in main.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name IN ({})".format(
            ",".join(f"'{t}'" for t in SCHEMA_TABLES)
        )).fetchall():
            if idx_row["sql"]:
                try:
                    wdb.execute(idx_row["sql"])
                except sqlite3.OperationalError:
                    pass
        
        wdb.commit()
        wdb.close()
        log(f"Worker DB: {wdb_path}")
    
    main.close()


def launch_worker(name):
    """Launch a single worker pointing to its isolated DB."""
    if name not in WORKERS:
        log(f"Unknown worker: {name}")
        return None
    
    wdb_path = WORK_DIR / f"swarm_{name}.sqlite"
    if not wdb_path.exists():
        log(f"Worker DB missing: {wdb_path}")
        return None
    
    cfg = WORKERS[name]
    env = os.environ.copy()
    for var in cfg["db_vars"]:
        env[var] = str(wdb_path)
    env["SOURCE_DB"] = str(MAIN_DB)  # Read-only source
    
    log_path = WORK_DIR / f"{name}_{TIMESTAMP}.log"
    log(f"Launching {name} → {log_path}")
    
    with open(log_path, "w") as lf:
        proc = subprocess.Popen(
            cfg["cmd"],
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
        )
    
    state = {
        "name": name,
        "pid": proc.pid,
        "log": str(log_path),
        "db": str(wdb_path),
        "started": datetime.now().isoformat(),
    }
    json.dump(state, open(WORK_DIR / f"{name}_state.json", "w"))
    return proc


def merge_worker_db(name):
    """Merge one worker DB into main DB with dedup."""
    wdb_path = WORK_DIR / f"swarm_{name}.sqlite"
    if not wdb_path.exists():
        return {"name": name, "inserted": 0, "skipped": 0}
    
    main = sqlite3.connect(str(MAIN_DB))
    main.execute("PRAGMA busy_timeout=60000")
    wdb = sqlite3.connect(str(wdb_path))
    wdb.row_factory = sqlite3.Row
    
    total_inserted = 0
    total_skipped = 0
    
    for table, key_cols in DEDUP_COLUMNS.items():
        # Get existing keys from main
        cols_str = ",".join(key_cols)
        existing = set()
        try:
            for row in main.execute(f"SELECT {cols_str} FROM {table}"):
                key = "|".join(str(row[i]) for i in range(len(key_cols)))
                existing.add(key)
        except sqlite3.OperationalError:
            continue
        
        # Get all rows from worker
        try:
            w_rows = list(wdb.execute(f"SELECT * FROM {table}"))
        except sqlite3.OperationalError:
            continue
        
        if not w_rows:
            continue
        
        columns = [desc[0] for desc in wdb.execute(f"SELECT * FROM {table} LIMIT 0").description]
        placeholders = ",".join("?" * len(columns))
        col_names = ",".join(columns)
        
        inserted = 0
        skipped = 0
        for row in w_rows:
            key = "|".join(str(row[col]) for col in key_cols)
            if key in existing:
                skipped += 1
                continue
            values = [row[col] for col in columns]
            try:
                main.execute(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", values)
                existing.add(key)
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1
        
        main.commit()
        total_inserted += inserted
        total_skipped += skipped
        log(f"  {name}/{table}: +{inserted} skipped={skipped}")
    
    main.close()
    wdb.close()
    return {"name": name, "inserted": total_inserted, "skipped": total_skipped}


def merge_all():
    """Merge all worker DBs into main DB."""
    log("Starting merge...")
    total = {"inserted": 0, "skipped": 0}
    for name in WORKERS:
        result = merge_worker_db(name)
        total["inserted"] += result["inserted"]
        total["skipped"] += result["skipped"]
    log(f"Merge complete: +{total['inserted']} inserted, {total['skipped']} skipped (dedup)")
    return total


def run_all():
    """Full pipeline: setup → launch all → wait → merge."""
    setup_worker_dbs()
    
    procs = {}
    for name in WORKERS:
        proc = launch_worker(name)
        if proc:
            procs[name] = proc
    
    log(f"All {len(procs)} workers launched. Waiting...")
    
    # Wait for all to complete
    for name, proc in procs.items():
        proc.wait()
        log(f"{name}: done (exit={proc.returncode})")
    
    # Merge
    result = merge_all()
    log(f"Pipeline complete. +{result['inserted']} new rows.")
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: swarm_parallel.py [setup|launch <name>|merge|run-all]")
        return
    
    cmd = sys.argv[1]
    if cmd == "setup":
        setup_worker_dbs()
    elif cmd == "launch":
        launch_worker(sys.argv[2])
    elif cmd == "merge":
        merge_all()
    elif cmd == "run-all":
        run_all()
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
