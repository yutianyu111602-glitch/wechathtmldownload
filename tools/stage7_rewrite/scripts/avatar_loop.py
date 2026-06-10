#!/usr/bin/env python3
"""DB2 Avatar Continuous Production Loop — runs avatar batches indefinitely.

Usage: python3 avatar_loop.py [--limit N] [--sleep S]
"""

import subprocess, json, os, sys, time, argparse
from datetime import datetime
from pathlib import Path

REPO = Path("/mnt/c/code/githubstar/wechathtmldownload")
AVATAR_SCRIPT = REPO / "tools/stage7_rewrite/scripts/_run_avatar.py"
DB2CTL = REPO / "tools/stage7_rewrite/scripts/db2ctl.py"
LOG = Path("/home/pc/swarm_data/avatar_loop.log")
STATE = Path("/home/pc/swarm_data/avatar_loop_state.json")

os.environ["DB2_WORKER_EXECUTE"] = "1"
os.environ["DB2_WRITER_EXECUTE"] = "1"


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    line = f"[{ts()}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def run_avatar(limit):
    log(f"Starting avatar batch limit={limit}")
    r = subprocess.run(["/usr/bin/python3", "-u", str(AVATAR_SCRIPT), str(limit)],
                       capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        log(f"FAILED: {r.stderr[-300:]}")
        return None
    try:
        return json.loads(r.stdout.strip().split("\n")[-1])
    except:
        # Fallback: parse text
        for line in r.stdout.strip().split("\n"):
            if "downloaded=" in line:
                return line
        return r.stdout.strip()[-200:]


def run_writer():
    r = subprocess.run(["python3", str(DB2CTL), "writer", "once", "--execute"],
                       capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(r.stdout.strip().split("\n")[-1])
        return d.get("processed_events", 0), d.get("processed_files", 0)
    except:
        return 0, 0


def run_status():
    r = subprocess.run(["python3", str(DB2CTL), "status"],
                       capture_output=True, text=True, timeout=30)
    try:
        return json.loads(r.stdout.strip().split("\n")[-1])
    except:
        return {}


def run_cache_seed(limit=500):
    r = subprocess.run(["python3", str(DB2CTL), "cache", "seed", "--execute", "--limit", str(limit)],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--sleep", type=int, default=30)
    p.add_argument("--max-rounds", type=int, default=0)
    p.add_argument("--cache-seed-every", type=int, default=5)
    args = p.parse_args()

    log(f"Avatar loop started: limit={args.limit} sleep={args.sleep}s")
    total_downloaded = 0
    total_events = 0
    round_num = 0

    while True:
        round_num += 1
        if args.max_rounds and round_num > args.max_rounds:
            log(f"Max rounds ({args.max_rounds}) reached. Stopping.")
            break

        # 1. Status check
        st = run_status()
        done = st.get("progress", {}).get("done", "?")
        spool = st.get("writer", {}).get("done_spool", "?")
        log(f"Round {round_num}: done={done} spool={spool}")

        # 2. Avatar batch
        result = run_avatar(args.limit)
        if result is None:
            log("Avatar batch failed. Sleeping before retry.")
            time.sleep(args.sleep)
            continue

        if isinstance(result, dict):
            lr = result.get("legacy_result", {})
            sp = result.get("spool", {})
            downloaded = lr.get("downloaded", 0)
            spooled = sp.get("written_events", 0)
            total_downloaded += downloaded
            total_events += spooled
            log(f"  downloaded={downloaded} spooled={spooled} total_dl={total_downloaded} total_ev={total_events}")
        else:
            log(f"  result: {str(result)[:150]}")

        # 3. Writer
        events, files = run_writer()
        if events:
            log(f"  writer: {events} events in {files} files")

        # 4. Cache seed periodically
        if round_num % args.cache_seed_every == 0:
            run_cache_seed()
            log(f"  cache seeded")

        # 5. Save state
        with open(STATE, "w") as f:
            json.dump({
                "ts": ts(),
                "round": round_num,
                "total_downloaded": total_downloaded,
                "total_events": total_events,
                "limit": args.limit,
            }, f, indent=2)

        time.sleep(args.sleep)


if __name__ == "__main__":
    main()
