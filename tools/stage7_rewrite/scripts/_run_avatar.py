#!/usr/bin/env python3
"""Run avatar adapter and report results."""
import subprocess, json, sys, os

os.environ["DB2_WORKER_EXECUTE"] = "1"
cmd = [
    "python3", "-u",
    "tools/stage7_rewrite/scripts/db2_avatar_spool_adapter.py",
    "--legacy-script", "/home/pc/scripts/avatar_dl_worker.py",
    "--db", "/home/pc/swarm_data/atlas_swarm_data.sqlite",
    "--spool-dir", "/home/pc/swarm_data/write_spool",
    "--avatar-dir", "/home/pc/swarm_data/output/avatars",
    "--cache-db", "/home/pc/swarm_data/cache/db2_sidecar_cache.sqlite",
    "--platform", "soundcloud",
    "--limit", sys.argv[1] if len(sys.argv) > 1 else "100",
]
r = subprocess.run(cmd, cwd="/mnt/c/code/githubstar/wechathtmldownload",
                   capture_output=True, text=True, timeout=600)
if r.returncode != 0:
    print(r.stderr[-500:])
    sys.exit(1)
d = json.loads(r.stdout.strip().split("\n")[-1])
lr = d["legacy_result"]
sp = d["spool"]
ch = d["cache_lookup"]["stats"]
print(f"downloaded={lr['downloaded']}  skipped={lr['skipped']}  spool={sp['written_events']}  cache_hits={ch['avatar_seen_hits']}  distinct_eids={lr['dedupe']['selected_distinct_eids']}")
