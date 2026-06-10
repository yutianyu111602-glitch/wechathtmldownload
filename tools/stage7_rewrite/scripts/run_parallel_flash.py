#!/usr/bin/env python3
"""Launch N parallel DeepSeek Pro extraction instances on manifest shards.

Usage:
  python scripts/run_parallel_flash.py \
    --shards-dir reports/manifest_shards \
    --instances 4 --concurrency 4 \
    --out-dir reports --run-name parallel_100k
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
PILOT_SCRIPT = SCRIPT_DIR / "stage7_deepseek_flash_pilot.py"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def run_one_shard(
    shard_path: Path,
    out_dir: Path,
    run_name: str,
    api_key: str,
    concurrency: int,
    endpoint: str,
    seed: int,
) -> subprocess.Popen:
    """Launch one Pro instance on a shard. Returns Popen handle."""
    output_root = f"{run_name}_{shard_path.stem}_{now_stamp()}"
    cmd = [
        sys.executable, str(PILOT_SCRIPT),
        "--manifest-jsonl", str(shard_path),
        "--mode", "run",
        "--limit", "999999",  # all rows in manifest (limit=0 means 0!)
        "--seed", str(seed),
        "--max-per-account", "999999",
        "--concurrency", str(concurrency),
        "--model", "deepseek-v4-pro",
        "--prompt-path", str(STAGE7_ROOT / "config" / "prompt.extract.v6.zh.txt"),
        "--thinking", "disabled",
        "--max-tokens", "2048",  # V6 needs more for participants+relations
        "--endpoint", endpoint,
        "--out-dir", str(out_dir),
        "--output-root-name", output_root,
    ]
    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = api_key
    env["PYTHONUNBUFFERED"] = "1"

    log_dir = out_dir / output_root
    log_dir.mkdir(parents=True, exist_ok=True)

    stdout_f = (log_dir / "stdout.log").open("w")
    stderr_f = (log_dir / "stderr.log").open("w")

    proc = subprocess.Popen(
        cmd,
        cwd=str(STAGE7_ROOT),
        env=env,
        stdout=stdout_f,
        stderr=stderr_f,
        text=True,
    )
    print(f"  [{proc.pid}] {shard_path.name} → {output_root}")
    return proc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards-dir", required=True, help="Directory with manifest_shard_*.jsonl")
    parser.add_argument("--instances", type=int, default=4, help="Parallel instances (default: 4)")
    parser.add_argument("--concurrency", type=int, default=4, help="Per-instance concurrency (default: 4)")
    parser.add_argument("--out-dir", default="reports")
    parser.add_argument("--run-name", default="parallel_flash")
    parser.add_argument("--seed", type=int, default=20260509)
    parser.add_argument("--endpoint", default="https://api.deepseek.com")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"ERROR: {args.api_key_env} not set", file=sys.stderr)
        return 1

    shards_dir = Path(args.shards_dir)
    if not shards_dir.is_absolute():
        shards_dir = STAGE7_ROOT / shards_dir
    shard_files = sorted(shards_dir.glob("manifest_shard_*.jsonl"))
    if not shard_files:
        print(f"ERROR: no shard files in {shards_dir}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = STAGE7_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    run_name = f"{args.run_name}_{now_stamp()}"
    run_dir = out_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Parallel Flash: {run_name}")
    print(f"  shards: {len(shard_files)} files in {shards_dir}")
    print(f"  instances: {args.instances}, concurrency: {args.concurrency}")
    print(f"  out_dir: {run_dir}")

    procs: list[tuple[Path, subprocess.Popen]] = []
    pending = list(shard_files)

    # Launch initial batch
    for i in range(min(args.instances, len(pending))):
        shard = pending.pop(0)
        proc = run_one_shard(shard, run_dir, "flash", api_key, args.concurrency, args.endpoint, args.seed)
        procs.append((shard, proc))

    # Monitor and launch next when one finishes
    while procs:
        for shard, proc in list(procs):
            ret = proc.poll()
            if ret is not None:
                print(f"  [{proc.pid}] DONE {shard.name} (exit={ret})")
                procs.remove((shard, proc))
                if pending:
                    next_shard = pending.pop(0)
                    new_proc = run_one_shard(next_shard, run_dir, "flash", api_key, args.concurrency, args.endpoint, args.seed)
                    procs.append((next_shard, new_proc))
        if procs:
            time.sleep(30)

    print(f"\nAll {len(shard_files)} shards complete.")
    print(f"Output: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
