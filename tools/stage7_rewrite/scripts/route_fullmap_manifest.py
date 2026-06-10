#!/usr/bin/env python3
"""Route a Full-Map manifest into no-API lanes before Flash reruns."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def collect_processed_uids(run_dir: Path | None) -> set[str]:
    if not run_dir or not run_dir.exists():
        return set()
    processed: set[str] = set()
    for path in run_dir.glob("flash_manifest_shard_*/flash_rows*.jsonl"):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                uid = str(row.get("article_uid") or row.get("article_id") or "")
                if uid:
                    processed.add(uid)
    return processed


def classify(row: dict[str, Any], *, empty_threshold: int, short_threshold: int) -> str:
    try:
        input_chars = int(row.get("input_chars") or 0)
    except Exception:
        input_chars = 0
    try:
        local_images = int(row.get("local_image_count") or row.get("existing_local_image_count") or 0)
    except Exception:
        local_images = 0
    try:
        remote_images = int(row.get("remote_image_count") or row.get("sidecar_image_count") or 0)
    except Exception:
        remote_images = 0
    if input_chars <= empty_threshold:
        if local_images > 0:
            return "needs_ocr"
        if remote_images > 0:
            return "needs_asset_repair"
        return "empty_no_local_image"
    if local_images > 0 and input_chars <= short_threshold:
        return "needs_ocr"
    if remote_images > 0 and input_chars <= short_threshold:
        return "needs_asset_repair"
    if input_chars <= short_threshold:
        return "short_text_review"
    return "ready_text"


def legacy_classify(row: dict[str, Any], *, empty_threshold: int, short_threshold: int) -> str:
    try:
        input_chars = int(row.get("input_chars") or 0)
    except Exception:
        input_chars = 0
    if input_chars <= empty_threshold:
        return "needs_ocr"
    if input_chars <= short_threshold:
        return "short_text_review"
    return "ready_text"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_shards(out_dir: Path, rows: list[dict[str, Any]], shard_count: int) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    shards: list[list[dict[str, Any]]] = [[] for _ in range(shard_count)]
    for idx, row in enumerate(rows):
        shards[idx % shard_count].append(row)

    result = []
    for idx, shard_rows in enumerate(shards):
        path = out_dir / f"manifest_shard_{idx:02d}.jsonl"
        write_jsonl(path, shard_rows)
        result.append({"path": str(path), "rows": len(shard_rows)})
    return result


def route_manifest(
    manifest_path: Path,
    out_dir: Path,
    *,
    processed_run_dir: Path | None,
    empty_threshold: int,
    short_threshold: int,
    shards: int,
    split_empty_by_images: bool = True,
) -> dict[str, Any]:
    rows = read_jsonl(manifest_path)
    processed = collect_processed_uids(processed_run_dir)

    lanes: dict[str, list[dict[str, Any]]] = {
        "ready_text": [],
        "needs_ocr": [],
        "needs_asset_repair": [],
        "empty_no_local_image": [],
        "short_text_review": [],
    }
    remaining: dict[str, list[dict[str, Any]]] = {key: [] for key in lanes}
    processed_by_lane = {key: 0 for key in lanes}

    for row in rows:
        lane = (
            classify(row, empty_threshold=empty_threshold, short_threshold=short_threshold)
            if split_empty_by_images
            else legacy_classify(row, empty_threshold=empty_threshold, short_threshold=short_threshold)
        )
        lanes[lane].append(row)
        uid = str(row.get("article_uid") or row.get("article_id") or "")
        if uid and uid in processed:
            processed_by_lane[lane] += 1
        else:
            remaining[lane].append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    for lane, lane_rows in lanes.items():
        write_jsonl(out_dir / f"{lane}.all.jsonl", lane_rows)
    for lane, lane_rows in remaining.items():
        write_jsonl(out_dir / f"{lane}.remaining.jsonl", lane_rows)

    ready_shards = write_shards(out_dir / "ready_text_remaining_shards", remaining["ready_text"], shards)

    summary = {
        "manifest_path": str(manifest_path),
        "processed_run_dir": str(processed_run_dir) if processed_run_dir else "",
        "thresholds": {
            "empty_threshold": empty_threshold,
            "short_threshold": short_threshold,
            "split_empty_by_images": split_empty_by_images,
        },
        "total_rows": len(rows),
        "processed_uids": len(processed),
        "lanes": {
            lane: {
                "all": len(lanes[lane]),
                "already_processed": processed_by_lane[lane],
                "remaining": len(remaining[lane]),
            }
            for lane in lanes
        },
        "ready_text_remaining_shards": ready_shards,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--processed-run-dir", default="")
    parser.add_argument("--empty-threshold", type=int, default=80)
    parser.add_argument("--short-threshold", type=int, default=500)
    parser.add_argument("--shards", type=int, default=4)
    parser.add_argument("--legacy-lanes", action="store_true", help="Use historical text-length-only routing")
    args = parser.parse_args()

    if args.shards < 1:
        raise SystemExit("--shards must be >= 1")
    if args.empty_threshold >= args.short_threshold:
        raise SystemExit("--empty-threshold must be less than --short-threshold")

    summary = route_manifest(
        Path(args.manifest),
        Path(args.out_dir),
        processed_run_dir=Path(args.processed_run_dir) if args.processed_run_dir else None,
        empty_threshold=args.empty_threshold,
        short_threshold=args.short_threshold,
        shards=args.shards,
        split_empty_by_images=not args.legacy_lanes,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
