#!/usr/bin/env python3
"""DB2 Fission Dashboard — one-shot rich view with platform distribution and quality metrics."""

import sqlite3, json, os, subprocess, time
from datetime import datetime
from pathlib import Path

DB = "/home/pc/swarm_data/atlas_swarm_data.sqlite"

def dash():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)

    # Platform distribution
    platforms = conn.execute("SELECT platform, COUNT(*) FROM dj_social_profiles GROUP BY platform ORDER BY COUNT(*) DESC LIMIT 12").fetchall()
    profiles = conn.execute("SELECT COUNT(*) FROM dj_social_profiles").fetchone()[0]
    outlinks = conn.execute("SELECT COUNT(*) FROM dj_outlinks").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM swarm_progress WHERE status='done'").fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM swarm_progress WHERE status='failed'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM swarm_progress WHERE status='pending'").fetchone()[0]
    running = conn.execute("SELECT COUNT(*) FROM swarm_progress WHERE status='running'").fetchone()[0]
    total_p = conn.execute("SELECT COUNT(*) FROM swarm_progress").fetchone()[0]
    searxng = conn.execute("SELECT COUNT(*) FROM dj_outlinks WHERE source_layer LIKE '%searx%' OR outlink_platform LIKE '%searx%'").fetchone()[0]
    avatars = conn.execute("SELECT COUNT(*) FROM dj_avatars").fetchone()[0]

    # Process check
    procs = subprocess.run(["pgrep", "-af", "python3"], capture_output=True, text=True).stdout
    hive = "hive_controller" in procs
    bc = "bc_deep_worker" in procs

    db_size = round(os.path.getsize(DB) / 1024 / 1024, 1)

    # Rates (from baseline if exists)
    baseline_path = "/home/pc/swarm_data/.fission_monitor_baseline.json"
    rate_info = ""
    if os.path.exists(baseline_path):
        b = json.loads(open(baseline_path).read())
        elapsed = (datetime.fromisoformat(datetime.now().astimezone().isoformat()) - 
                   datetime.fromisoformat(b["ts"])).total_seconds() / 60
        if elapsed > 0:
            d_done = done - b.get("progress_done", done)
            rate_info = f"  rate: {d_done/elapsed:.1f}/min  ({elapsed:.0f}min)"

    # Render
    bar_w = 40
    f = int(bar_w * done / total_p) if total_p else 0
    bar = "█" * f + "░" * (bar_w - f)
    pct = done / total_p * 100 if total_p else 0

    print(f"""
╔══════════════════════════════════════════════════════════╗
║              DB2 FISSION DASHBOARD                       ║
║         {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                           ║
╠══════════════════════════════════════════════════════════╣
║  Progress: [{bar}] {pct:.1f}%
║  done={done:<7} failed={failed:<6} running={running}  pending={pending}
║  {rate_info}
╠══════════════════════════════════════════════════════════╣
║  Profiles: {profiles:<8}  Outlinks: {outlinks:<8}  Avatars: {avatars}
║  DB: {db_size}MB  Integrity: ok  SearXNG: {searxng}
╠══════════════════════════════════════════════════════════╣
║  Fleet: hive={'●' if hive else '○'}  bc_deep={'●' if bc else '○'}
╠══════════════════════════════════════════════════════════╣
║  Platform Distribution:""")
    for platform, count in platforms:
        bar_w2 = 25
        f2 = int(bar_w2 * count / max(p[1] for p in platforms))
        print(f"║    {platform:<16s} {count:>6d}  {'▌' * f2}")
    print("╚══════════════════════════════════════════════════════════╝")
    conn.close()


if __name__ == "__main__":
    dash()
