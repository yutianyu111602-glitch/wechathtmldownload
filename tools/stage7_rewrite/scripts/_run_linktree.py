#!/usr/bin/env python3
"""Run linktree expansion adapter and report results."""
import subprocess, json, os, sys

os.environ["DB2_WORKER_EXECUTE"] = "1"
cmd = [
    "python3", "-u",
    "tools/stage7_rewrite/scripts/db2_outlink_expand_spool_adapter.py",
    "--legacy-script", "/home/pc/scripts/outlink_expand_worker.py",
    "--db", "/home/pc/swarm_data/atlas_swarm_data.sqlite",
    "--spool-dir", "/home/pc/swarm_data/write_spool",
    "--cache-db", "/home/pc/swarm_data/cache/db2_sidecar_cache.sqlite",
    "--phase", "linktree",
    "--limit", sys.argv[1] if len(sys.argv) > 1 else "200",
    "--sleep", "0.8",
]
r = subprocess.run(cmd, cwd="/mnt/c/code/githubstar/wechathtmldownload",
                   capture_output=True, text=True, timeout=600)
print(r.stdout[-500:])
if r.stderr:
    print(r.stderr[-300:])
