#!/usr/bin/env python3
"""Overnight watchdog: monitor 8-shard parallel Flash extraction.

Checks progress, writes memory, detects stalls.
Run: python scripts/overnight_watchdog.py --run-dir reports/overnight_81k_YYYYMMDD_HHMMSS
"""
import json
import glob
import os
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent

def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def mem0_add(text: str, meta: dict = None) -> None:
    try:
        from pipeline_memory import add
        add(text, metadata=(meta or {}))
    except:
        pass

def check_run(run_dir: str) -> dict:
    """Check all 8 shards and return status."""
    shards = {}
    total_samples = 0
    total_cost = 0
    total_chunks = 0
    parse_rates = []
    schema_rates = []
    statuses = []
    
    for i in range(8):
        pattern = f"{run_dir}/flash_manifest_shard_0{i}_*/flash_running_summary.json"
        files = glob.glob(pattern)
        if not files:
            statuses.append("missing")
            continue
        
        with open(files[0]) as f:
            d = json.load(f)
        
        s = d.get("processed_samples", 0)
        c = d.get("estimated_cny", 0)
        ch = d.get("chunk_count", 0)
        st = d.get("status", "unknown")
        
        shards[f"shard_{i:02d}"] = {
            "samples": s, "cost": round(c, 4), "chunks": ch,
            "parse": d.get("parse_ok_rate", 0), "schema": d.get("schema_ok_rate", 0),
            "status": st
        }
        total_samples += s
        total_cost += c
        total_chunks += ch
        parse_rates.append(d.get("parse_ok_rate", 0))
        schema_rates.append(d.get("schema_ok_rate", 0))
        statuses.append(st)
    
    running = sum(1 for s in statuses if s == "running")
    complete = sum(1 for s in statuses if s == "complete")
    avg_parse = sum(parse_rates) / max(len(parse_rates), 1)
    avg_schema = sum(schema_rates) / max(len(schema_rates), 1)
    
    return {
        "time": now(),
        "total_samples": total_samples,
        "total_cost": round(total_cost, 4),
        "total_chunks": total_chunks,
        "running_shards": running,
        "complete_shards": complete,
        "avg_parse": round(avg_parse, 4),
        "avg_schema": round(avg_schema, 4),
        "shards": shards,
    }

def main():
    if len(sys.argv) < 2:
        # Auto-find latest overnight run
        pattern = str(STAGE7_ROOT / "reports" / "overnight_81k_*")
        dirs = sorted(glob.glob(pattern), reverse=True)
        if not dirs:
            print("No overnight run found")
            sys.exit(1)
        run_dir = dirs[0]
    else:
        run_dir = sys.argv[1]
    
    print(f"Overnight Watchdog — {now()}")
    print(f"Run: {run_dir}")
    print(f"PID: {os.getpid()}")
    print()
    
    prev_samples = 0
    stall_count = 0
    
    while True:
        status = check_run(run_dir)
        
        # Progress line
        new_samples = status["total_samples"] - prev_samples
        print(f"[{status['time']}] samples={status['total_samples']} (+{new_samples}) "
              f"running={status['running_shards']}/8 complete={status['complete_shards']} "
              f"parse={status['avg_parse']:.1%} schema={status['avg_schema']:.1%} "
              f"¥{status['total_cost']:.2f}")
        
        # Stall detection
        if new_samples == 0 and status["running_shards"] > 0:
            stall_count += 1
            if stall_count >= 3:
                print(f"  ⚠️ STALL DETECTED: no progress for {stall_count} checks")
                mem0_add(f"OVERNIGHT STALL: {status['running_shards']} shards running but 0 new samples in {stall_count} checks",
                        {"type": "overnight_watchdog", "phase": "stall_warning"})
        else:
            stall_count = 0
        
        prev_samples = status["total_samples"]
        
        # All complete?
        if status["complete_shards"] == 8:
            print(f"\n🎉 ALL 8 SHARDS COMPLETE!")
            print(f"   Total: {status['total_samples']} samples, ¥{status['total_cost']:.2f}")
            mem0_add(f"OVERNIGHT COMPLETE: {status['total_samples']} samples, ¥{status['total_cost']:.2f}, "
                    f"parse={status['avg_parse']:.1%}, schema={status['avg_schema']:.1%}",
                    {"type": "overnight_watchdog", "phase": "complete"})
            break
        
        # Hourly memory checkpoint
        if new_samples > 0:
            mem0_add(f"Overnight progress: {status['total_samples']} samples (+{new_samples}), "
                    f"{status['running_shards']}/8 running, ¥{status['total_cost']:.2f}, "
                    f"parse={status['avg_parse']:.1%}, schema={status['avg_schema']:.1%}",
                    {"type": "overnight_watchdog", "phase": "checkpoint"})
        
        time.sleep(1800)  # 30 minutes

if __name__ == "__main__":
    main()
