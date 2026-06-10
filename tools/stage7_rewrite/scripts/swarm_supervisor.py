#!/usr/bin/env python3
"""DB2 Swarm Supervisor v2 — non-blocking worker management with auto-restart."""
import subprocess, json, os, sys, time, signal
from datetime import datetime
from pathlib import Path

WORKERS = {
    "sc_deep": ["/home/pc/scripts/sc_deep_worker.py", "--max-profiles", "500"],
    "domestic": ["/home/pc/scripts/domestic_worker.py"],
}
SPOOL = Path("/home/pc/swarm_data/write_spool")
REPO = Path("/mnt/c/code/githubstar/wechathtmldownload")
LOG = Path("/home/pc/swarm_data/supervisor.log")

def log(msg):
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def count_spool():
    return len(list(SPOOL.glob("incoming/*.jsonl")))

def run_writer():
    r = subprocess.run(
        ["python3", str(REPO / "tools/stage7_rewrite/scripts/db2ctl.py"),
         "writer", "once", "--execute"],
        env={**os.environ, "DB2_WRITER_EXECUTE": "1"},
        capture_output=True, text=True, timeout=30,
    )
    try:
        d = json.loads(r.stdout.strip().split("\n")[-1])
        return d.get("processed_events", 0)
    except:
        return 0

def status():
    r = subprocess.run(
        ["python3", str(REPO / "tools/stage7_rewrite/scripts/db2ctl.py"), "status"],
        capture_output=True, text=True, timeout=15,
    )
    try:
        return json.loads(r.stdout.strip().split("\n")[-1])
    except:
        return {}

def main():
    procs = {}
    log("Supervisor v2 started")

    for name, cmd in WORKERS.items():
        p = subprocess.Popen(["python3", "-u"] + cmd[1:],
                            executable=cmd[0],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
        procs[name] = {"proc": p, "start": time.time(), "max": 3600}
        log(f"{name}: PID={p.pid}")

    prev_spool = count_spool()

    while True:
        time.sleep(60)

        # Check dead workers
        for name, info in list(procs.items()):
            p = info["proc"]
            if p.poll() is not None:
                elapsed = time.time() - info["start"]
                log(f"{name}: exited r={p.returncode} ({elapsed:.0f}s)")
                del procs[name]
                # Restart after cooldown
                time.sleep(30)
                log(f"{name}: restarting")
                p2 = subprocess.Popen(["python3", "-u"] + WORKERS[name][1:],
                                    executable=WORKERS[name][0],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
                procs[name] = {"proc": p2, "start": time.time(), "max": 3600}
                log(f"{name}: PID={p2.pid}")

            # Timeout check
            elif time.time() - info["start"] > info["max"]:
                log(f"{name}: timeout, killing")
                p.kill()
                del procs[name]
                time.sleep(30)
                p2 = subprocess.Popen(["python3", "-u"] + WORKERS[name][1:],
                                    executable=WORKERS[name][0],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
                procs[name] = {"proc": p2, "start": time.time(), "max": 3600}

        # Writer
        cur_spool = count_spool()
        if cur_spool > prev_spool:
            ev = run_writer()
            if ev:
                log(f"writer: {ev} events")
            prev_spool = count_spool()

        # Status
        if time.time() % 300 < 60:
            st = status()
            done = st.get("progress", {}).get("done", "?")
            failed = st.get("progress", {}).get("failed", "?")
            running_pids = {n: i["proc"].pid for n, i in procs.items() if i["proc"].poll() is None}
            log(f"status: done={done} failed={failed} workers={list(running_pids.keys())}")

if __name__ == "__main__":
    main()
