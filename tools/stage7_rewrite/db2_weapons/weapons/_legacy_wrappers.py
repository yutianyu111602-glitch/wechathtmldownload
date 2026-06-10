# Remaining weapon stubs — minimal wrappers that delegate to existing scripts.
# These run on WSL directly (not in Docker) since they need cookie/DB access.

import sys, subprocess, os, json
from pathlib import Path

SCRIPTS = Path("/home/pc/scripts")
DB2CTL = Path("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/db2ctl.py")

def run_sc_deep():
    subprocess.run(["python3", "-u", str(SCRIPTS / "sc_deep_worker.py"), "--max-profiles", "500"])

def run_ig_fission():
    subprocess.run(["python3", "-u", str(SCRIPTS / "ig_nuclear_fission_v2.py"), "--worker-id", "1", "--worker-count", "1"])

def run_domestic():
    subprocess.run(["python3", "-u", str(SCRIPTS / "domestic_worker.py")])

def run_avatar():
    subprocess.run(["python3", "-u", str(Path("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/_run_avatar.py")), "500"])

def run_expand():
    subprocess.run([
        "python3", "-u",
        str(Path("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/db2_outlink_expand_spool_adapter.py")),
        "--legacy-script", str(SCRIPTS / "outlink_expand_worker.py"),
        "--db", "/home/pc/swarm_data/atlas_swarm_data.sqlite",
        "--spool-dir", "/home/pc/swarm_data/write_spool",
        "--cache-db", "/home/pc/swarm_data/cache/db2_sidecar_cache.sqlite",
        "--phase", "linktree", "--limit", "200", "--sleep", "0.8",
    ])

def run_writer():
    os.environ["DB2_WRITER_EXECUTE"] = "1"
    subprocess.run(["python3", str(DB2CTL), "writer", "once", "--execute"])

def run_cache():
    subprocess.run(["python3", str(DB2CTL), "cache", "seed", "--execute", "--limit", "500"])

def run_dedup():
    subprocess.run(["python3", str(Path("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/swarm_dedup.py"))])

def run_monitor():
    r = subprocess.run(["python3", str(DB2CTL), "status"], capture_output=True, text=True)
    d = json.loads(r.stdout.strip().split("\n")[-1])
    p = d.get("progress", {})
    print(f"done={p.get('done')} failed={p.get('failed')} pending={p.get('pending')} running={p.get('running')}")
    print(f"integrity={d.get('integrity')} spool={d.get('writer',{}).get('spool_backlog')}")
