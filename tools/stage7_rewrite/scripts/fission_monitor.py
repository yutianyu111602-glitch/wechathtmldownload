#!/usr/bin/env python3
"""DB2 Fission Real-Time Monitor — run every 5 min via cron or manual loop.

Usage:
  python3 fission_monitor.py              # single run
  python3 fission_monitor.py --loop 60    # loop every 60s
  python3 fission_monitor.py --once       # single run + compare to baseline
"""

import sqlite3, json, sys, time, os
from datetime import datetime, timezone
from pathlib import Path

DB = "/home/pc/swarm_data/atlas_swarm_data.sqlite"
BASELINE = "/home/pc/swarm_data/.fission_monitor_baseline.json"
LOGDIR = "/home/pc/swarm_data/monitor_logs"
ALERT_THRESHOLDS = {
    "integrity_fail": "RED",
    "searxng_growth": "RED",
    "garbage_url_growth": "AMBER",
    "stale_running_30min": "AMBER",
    "rogue_workers": "RED",
    "lock_holder_multi": "AMBER",
    "spool_backlog": "AMBER",
    "profiles_stalled_10min": "AMBER",
    "failed_growth": "AMBER",
}


def iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log(msg, level="INFO"):
    ts = iso()
    Path(LOGDIR).mkdir(parents=True, exist_ok=True)
    logfile = Path(LOGDIR) / f"monitor_{datetime.now().strftime('%Y%m%d')}.log"
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def snapshot():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    snap = {
        "ts": iso(),
        "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "profiles": conn.execute("SELECT COUNT(*) FROM dj_social_profiles").fetchone()[0],
        "outlinks": conn.execute("SELECT COUNT(*) FROM dj_outlinks").fetchone()[0],
        "progress_total": conn.execute("SELECT COUNT(*) FROM swarm_progress").fetchone()[0],
    }
    for status in ("done", "failed", "pending", "running"):
        snap[f"progress_{status}"] = conn.execute(
            f"SELECT COUNT(*) FROM swarm_progress WHERE status='{status}'"
        ).fetchone()[0]
    snap["searxng"] = conn.execute(
        "SELECT COUNT(*) FROM dj_outlinks WHERE source_layer LIKE '%searx%' OR outlink_platform LIKE '%searx%'"
    ).fetchone()[0]
    snap["garbage_urls"] = conn.execute(
        "SELECT COUNT(*) FROM dj_outlinks WHERE outlink_url LIKE '%doubleclick%' "
        "OR outlink_url LIKE '%googleadservices%' OR outlink_url LIKE '%googlesyndication%' "
        "OR outlink_url LIKE '%facebook.com/tr%'"
    ).fetchone()[0]
    snap["empty_names"] = conn.execute(
        "SELECT COUNT(*) FROM dj_social_profiles WHERE entity_name IS NULL OR entity_name = ''"
    ).fetchone()[0]
    snap["db_size_mb"] = round(os.path.getsize(DB) / (1024 * 1024), 1)
    wal_path = DB + "-wal"
    snap["wal_size_mb"] = round(os.path.getsize(wal_path) / (1024 * 1024), 1) if os.path.exists(wal_path) else 0
    conn.close()

    # Process check
    import subprocess
    procs = subprocess.run(["pgrep", "-af", "python3"], capture_output=True, text=True).stdout
    snap["hive_running"] = "hive_controller" in procs
    snap["marathon_running"] = "swarm_marathon" in procs
    snap["bc_deep_running"] = "bc_deep_worker" in procs
    snap["rogue_count"] = sum(1 for _ in [
        "bc_deep_worker" in procs and "hive" not in procs.split("bc_deep")[0],
        "nuclear_fission" in procs,
        "scrape_ra_artist" in procs,
        "searxng" in procs,
    ] if _)
    return snap


def load_baseline():
    if os.path.exists(BASELINE):
        return json.loads(open(BASELINE).read())
    return {}


def save_baseline(snap):
    with open(BASELINE, "w") as f:
        json.dump(snap, f, indent=2)


def check_alerts(snap, baseline):
    alerts = []
    if snap["integrity"] != "ok":
        alerts.append(("RED", f"INTEGRITY FAIL: {snap['integrity']}"))
    if baseline and snap["searxng"] > baseline.get("searxng", 0):
        alerts.append(("RED", f"SearXNG grew: {baseline['searxng']}→{snap['searxng']}"))
    if baseline and snap["garbage_urls"] > baseline.get("garbage_urls", 0):
        alerts.append(("AMBER", f"Garbage URLs: {baseline['garbage_urls']}→{snap['garbage_urls']}"))
    if snap["rogue_count"] > 0:
        alerts.append(("RED", f"Rogue workers: {snap['rogue_count']}"))
    if snap["bc_deep_running"] and not snap["hive_running"]:
        alerts.append(("AMBER", "bc_deep running outside hive"))
    return alerts


def report(snap, baseline):
    print()
    print("=" * 55)
    print(f"  DB2 FISSION MONITOR  |  {snap['ts'][:19]}")
    print("=" * 55)

    # Progress bar
    total = snap["progress_total"]
    done = snap["progress_done"]
    failed = snap["progress_failed"]
    running = snap["progress_running"]
    pending = snap["progress_pending"]
    pct = done / total * 100 if total else 0
    bar_len = 30
    filled = int(bar_len * done / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"  Progress: [{bar}] {pct:.1f}%")
    print(f"  done={done}  failed={failed}  running={running}  pending={pending}")

    # Growth
    if baseline:
        d_profiles = snap["profiles"] - baseline.get("profiles", snap["profiles"])
        d_done = snap["progress_done"] - baseline.get("progress_done", snap["progress_done"])
        d_failed = snap["progress_failed"] - baseline.get("progress_failed", snap["progress_failed"])
        elapsed = (datetime.fromisoformat(snap["ts"]) - datetime.fromisoformat(baseline["ts"])).total_seconds() / 60
        rate = d_done / elapsed if elapsed > 0 else 0
        print(f"\n  Since baseline ({elapsed:.0f}min ago):")
        print(f"    profiles: {baseline['profiles']} → {snap['profiles']}  (+{d_profiles})")
        print(f"    done:     {baseline['progress_done']} → {snap['progress_done']}  (+{d_done})")
        print(f"    failed:   {baseline['progress_failed']} → {snap['progress_failed']}  ({d_failed:+d})")
        print(f"    rate:     {rate:.1f} done/min")
    else:
        print(f"\n  profiles={snap['profiles']}  outlinks={snap['outlinks']}")

    print(f"\n  DB: {snap['db_size_mb']}MB  WAL: {snap['wal_size_mb']}MB  integrity: {snap['integrity']}")
    print(f"  SearXNG: {snap['searxng']}  Garbage URLs: {snap['garbage_urls']}  Empty names: {snap['empty_names']}")
    print(f"  Fleet: hive={'✓' if snap['hive_running'] else '✗'}  marathon={'✓' if snap['marathon_running'] else '✗'}  rogues={snap['rogue_count']}")

    alerts = check_alerts(snap, baseline)
    if alerts:
        print("\n  ⚠ ALERTS:")
        for level, msg in alerts:
            icon = "🔴" if level == "RED" else "🟡"
            print(f"    {icon} [{level}] {msg}")
    else:
        print("\n  ✅ No alerts")

    print("=" * 55)
    return alerts


def main():
    import argparse
    p = argparse.ArgumentParser(description="DB2 Fission Real-Time Monitor")
    p.add_argument("--loop", type=int, default=0, help="Loop interval in seconds")
    p.add_argument("--once", action="store_true", help="Single run with baseline")
    p.add_argument("--reset-baseline", action="store_true")
    args = p.parse_args()

    if args.reset_baseline:
        save_baseline(snapshot())
        log("Baseline reset", "INFO")
        print("Baseline captured.")
        return

    if args.loop:
        log(f"Monitor loop started, interval={args.loop}s", "INFO")
        baseline = snapshot()
        save_baseline(baseline)
        report(baseline, {})
        try:
            while True:
                time.sleep(args.loop)
                snap = snapshot()
                alerts = report(snap, baseline)
                for level, msg in alerts:
                    log(msg, level)
        except KeyboardInterrupt:
            log("Monitor stopped", "INFO")
    else:
        baseline = load_baseline()
        snap = snapshot()
        alerts = report(snap, baseline)
        save_baseline(snap)
        for level, msg in alerts:
            log(msg, level)


if __name__ == "__main__":
    main()
