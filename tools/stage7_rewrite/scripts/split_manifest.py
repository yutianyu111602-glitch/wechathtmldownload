#!/usr/bin/env python3
"""Split manifest JSONL into N shards for parallel extraction."""
import argparse
import json
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Split manifest JSONL into shards")
    parser.add_argument("--input", required=True)
    parser.add_argument("--shards", type=int, default=8)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    in_path = Path(args.input)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Count total lines
    with in_path.open("r", encoding="utf-8") as f:
        total = sum(1 for _ in f)

    per_shard = (total + args.shards - 1) // args.shards
    print(f"Total: {total} rows, {args.shards} shards, ~{per_shard} rows/shard")

    shard_idx = 0
    row_count = 0
    out_f = None

    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            if row_count == 0 or row_count >= per_shard:
                if out_f:
                    out_f.close()
                shard_path = out_dir / f"manifest_shard_{shard_idx:02d}.jsonl"
                out_f = shard_path.open("w", encoding="utf-8")
                print(f"  shard {shard_idx:02d}: {shard_path}")
                shard_idx += 1
                row_count = 0
            out_f.write(line)
            row_count += 1

    if out_f:
        out_f.close()
    print(f"Done: {shard_idx} shards written to {out_dir}")

if __name__ == "__main__":
    main()
