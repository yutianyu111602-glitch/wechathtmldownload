#!/usr/bin/env python3
"""Batch spool-runner for workers. Runs worker, monitors spool, handles writer."""

import subprocess, json, os, sys, time, argparse
from pathlib import Path

REPO = Path("/mnt/c/code/githubstar/wechathtmldownload")
SPOOL_DIR = Path("/home/pc/swarm_data/write_spool")
WORKERS = {
    "sc_deep": "/home/pc/scripts/sc_deep_worker.py",
    "domestic": "/home/pc/scripts/domestic_worker.py",
}

os.environ["DB2_WRITE_MODE"] = "spool"

def count_spool(prefix):
    return len(list(SPOOL_DIR.glob(f"incoming/{prefix}*")))

def run_worker(name, script, timeout=600):
    print(f"\n[{name}] Starting worker: {script}")
    before = count_spool(name)
    try:
        r = subprocess.run(
            ["python3", "-u", script],
            cwd=Path(script).parent,
            capture_output=True, text=True, timeout=timeout
        )
        after = count_spool(name)
        new_files = after - before
        print(f"[{name}] Done. exit={r.returncode} spool_files=+{new_files}")
        if r.stdout:
            print(f"[{name}] stdout: {r.stdout[-300:]}")
        if r.stderr:
            print(f"[{name}] stderr: {r.stderr[-300:]}")
        return new_files
    except subprocess.TimeoutExpired:
        after = count_spool(name)
        print(f"[{name}] Timeout ({timeout}s). spool_files=+{after-before} (partial)")
        return after - before

def run_writer():
    r = subprocess.run(
        ["python3", str(REPO / "tools/stage7_rewrite/scripts/db2ctl.py"), "writer", "once", "--execute"],
        env={**os.environ, "DB2_WRITER_EXECUTE": "1"},
        cwd=str(REPO), capture_output=True, text=True, timeout=30
    )
    try:
        d = json.loads(r.stdout.strip().split("\n")[-1])
        return d.get("processed_events", 0)
    except:
        return 0

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workers", default="domestic")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--loop", action="store_true")
    args = p.parse_args()

    names = [w.strip() for w in args.workers.split(",")]

    while True:
        for name in names:
            if name not in WORKERS:
                print(f"Unknown worker: {name}")
                continue
            run_worker(name, WORKERS[name], args.timeout)
            ev = run_writer()
            if ev:
                print(f"  writer: {ev} events")

        if not args.loop:
            break
        print(f"\n--- Sleeping 300s before next round ---")
        time.sleep(300)

if __name__ == "__main__":
    main()
