#!/usr/bin/env python3
"""Shard completion watchdog — auto-trigger enhance + scorer when a V6 shard finishes.

Monitors the overnight_v6 output directory. When a shard's flash_rows.jsonl 
appears (meaning the partial has been finalized), automatically:
  1. Runs enhance_title_fallback.py
  2. Runs deepseek_hybrid_scorer.py (if available)
  3. Logs all activity to pipeline memory

Usage:
  python scripts/shard_watchdog.py \
    --base-dir reports/overnight_v6_20260510_111419 \
    --interval 60
"""
import argparse, json, os, subprocess, sys, time, glob
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
ENHANCE_SCRIPT = SCRIPT_DIR / "enhance_title_fallback.py"
SCORER_SCRIPT = SCRIPT_DIR / "deepseek_hybrid_scorer.py"


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def log_memory(text: str, metadata: dict | None = None):
    """Write to pipeline memory."""
    try:
        from pipeline_memory import add
        add(text, metadata=(metadata or {}))
    except:
        print(f"  [memory] failed to write: {text[:60]}")


def find_partial_or_final(shard_dir: Path) -> tuple[Path | None, bool]:
    """Return (path_to_jsonl, is_final). is_final=True means flash_rows.jsonl exists."""
    final = shard_dir / "flash_rows.jsonl"
    if final.exists():
        return final, True
    partial = shard_dir / "flash_rows.partial.jsonl"
    if partial.exists():
        return partial, False
    return None, False


def check_stall(shard_dir: Path, last_lines: dict) -> bool:
    """Check if a running shard is stalled (no new lines in 60 min)."""
    partial = shard_dir / "flash_rows.partial.jsonl"
    if not partial.exists():
        return False
    shard_name = shard_dir.name
    current_lines = count_lines(partial)
    prev = last_lines.get(shard_name, 0)
    last_lines[shard_name] = current_lines
    if prev > 0 and current_lines == prev:
        return True
    return False


def count_lines(path: Path) -> int:
    try:
        with open(path) as f:
            return sum(1 for _ in f)
    except:
        return 0


def get_summary(shard_dir: Path) -> dict | None:
    """Read running summary."""
    summary_path = shard_dir / "flash_running_summary.json"
    if not summary_path.exists():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except:
        return None


def run_enhance(input_jsonl: Path, output_jsonl: Path) -> bool:
    """Run enhance_title_fallback.py. Returns True on success."""
    if output_jsonl.exists():
        print(f"    enhance output already exists: {output_jsonl.name}")
        return True
    cmd = [sys.executable, str(ENHANCE_SCRIPT), str(input_jsonl), str(output_jsonl)]
    print(f"    Running enhance: {input_jsonl.name} → {output_jsonl.name}")
    result = subprocess.run(cmd, cwd=str(STAGE7_ROOT), capture_output=True, text=True, timeout=600)
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if "Results" in line or "Entity" in line or "Event" in line:
                print(f"      {line.strip()}")
        return True
    print(f"    enhance FAILED: {result.stderr[-200:]}")
    return False


def run_scorer(input_jsonl: Path, out_dir: Path) -> bool:
    """Run deepseek_hybrid_scorer.py. Returns True on success."""
    if not SCORER_SCRIPT.exists():
        print(f"    Scorer script not found, skipping")
        return True
    summary_path = out_dir / "hybrid_score_summary.json"
    if summary_path.exists():
        print(f"    scorer output already exists")
        return True
    cmd = [
        sys.executable, str(SCORER_SCRIPT),
        "--flash-jsonl", str(input_jsonl),
        "--out-dir", str(out_dir),
    ]
    print(f"    Running scorer: {input_jsonl.name}")
    result = subprocess.run(cmd, cwd=str(STAGE7_ROOT), capture_output=True, text=True, timeout=600)
    if result.returncode == 0:
        for line in result.stdout.strip().split("\n"):
            if "Scored" in line or "accept" in line or "ratio" in line:
                print(f"      {line.strip()}")
        return True
    print(f"    scorer FAILED: {result.stderr[-200:]}")
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", required=True, help="Overnight V6 run directory")
    parser.add_argument("--interval", type=int, default=60, help="Check interval in seconds")
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    if not base_dir.is_absolute():
        base_dir = STAGE7_ROOT / base_dir
    if not base_dir.exists():
        print(f"ERROR: base_dir not found: {base_dir}")
        return 1

    print(f"Shard Watchdog: {base_dir}")
    print(f"  interval: {args.interval}s")
    print(f"  enhance: {'found' if ENHANCE_SCRIPT.exists() else 'MISSING'}")
    print(f"  scorer: {'found' if SCORER_SCRIPT.exists() else 'MISSING'}")

    last_lines: dict[str, int] = {}
    processed: set[str] = set()
    log_memory(f"Shard watchdog started: {base_dir}", {"type": "shard_watchdog", "phase": "start"})

    while True:
        # Find all shard directories
        shard_dirs = sorted(Path(base_dir).glob("flash_manifest_shard_*_*"))
        if not shard_dirs:
            print(f"  [{now_stamp()}] No shard dirs found yet...")
            time.sleep(args.interval)
            continue

        running = 0
        finished = 0
        stalled = 0

        for shard_dir in shard_dirs:
            jsonl_path, is_final = find_partial_or_final(shard_dir)
            summary = get_summary(shard_dir)
            status = summary.get("status", "?") if summary else "?"

            if is_final:
                finished += 1
                if str(shard_dir) in processed:
                    continue

                print(f"  [{now_stamp()}] FINISHED: {shard_dir.name}")
                samples = count_lines(jsonl_path)

                # Run enhance
                enhanced_path = shard_dir / "flash_rows_enhanced.jsonl"
                if run_enhance(jsonl_path, enhanced_path):
                    # Run scorer
                    score_dir = shard_dir / "score"
                    score_dir.mkdir(exist_ok=True)
                    run_scorer(enhanced_path, score_dir)

                log_memory(
                    f"Shard {shard_dir.name} processed: enhance + scorer done. {samples} samples.",
                    {"type": "shard_watchdog", "phase": "shard_done", "shard": shard_dir.name},
                )
                processed.add(str(shard_dir))

            elif jsonl_path:
                running += 1
                if check_stall(shard_dir, last_lines):
                    stalled += 1
                    print(f"  [{now_stamp()}] ⚠️ STALLED: {shard_dir.name} (0 new lines in {args.interval}s)")
            else:
                print(f"  [{now_stamp()}] ⚠️ EMPTY: {shard_dir.name}")

        # Status line
        print(f"  [{now_stamp()}] finished={finished}/{len(shard_dirs)} running={running} stalled={stalled}")

        if finished >= len(shard_dirs):
            print(f"\n  ALL SHARDS COMPLETE! Watchdog exiting.")
            log_memory(f"All {len(shard_dirs)} shards complete. Watchdog done.", {"type": "shard_watchdog", "phase": "complete"})
            break

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
