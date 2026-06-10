#!/usr/bin/env python3
"""Build Stage7 manifest from Full-Map processed articles.

The manifest is the routing authority for downstream LLM/OCR lanes, so image
counts must come from the archived local asset sidecar instead of a placeholder.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_PROCESSED_ROOT = (
    "/mnt/d/downstream_results/stage7_rewrite/longrun/WHERE_TO_RAVE_WECHAT_SYNC_20260508/"
    "FULL_MAP_SMART_BACKFILL_20260509/processed_FULL_MAP_SMART_BACKFILL_20260509"
)
DEFAULT_ARCHIVE_ROOT = (
    "/mnt/d/downstream_results/stage7_rewrite/longrun/WHERE_TO_RAVE_WECHAT_SYNC_20260508/"
    "FULL_MAP_SMART_BACKFILL_20260509/mptext_archive_FULL_MAP_SMART_BACKFILL_20260509"
)


def host_path(value: str | Path) -> Path:
    raw = str(value).replace("\\", "/")
    if os.name == "nt" and raw.startswith("/mnt/d/"):
        return Path("D:/" + raw.removeprefix("/mnt/d/"))
    if os.name == "nt" and raw == "/mnt/d":
        return Path("D:/")
    return Path(raw)


def display_path(path: Path, actual_root: Path, display_root: str) -> str:
    try:
        rel = path.relative_to(actual_root)
    except Exception:
        return str(path)
    return str(Path(display_root) / rel).replace("\\", "/")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_text_len(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace"))


def count_sidecar_images(raw_dir: Path) -> int:
    try:
        sidecar = read_json(raw_dir / "sidecar.json")
    except Exception:
        return 0
    images = sidecar.get("images", []) if isinstance(sidecar, dict) else []
    return len(images) if isinstance(images, list) else 0


def count_processed_assets(raw_dir: Path) -> int:
    try:
        assets = read_json(raw_dir / "assets.json")
    except Exception:
        return 0
    images = assets if isinstance(assets, list) else assets.get("images", [])
    return len(images) if isinstance(images, list) else 0


def count_archive_local_images(archive_dir: Path, *, probe_existing: bool) -> tuple[int, int]:
    try:
        assets = read_json(archive_dir / "assets_local.json")
    except Exception:
        return 0, 0
    images = assets if isinstance(assets, list) else assets.get("images", [])
    if not isinstance(images, list):
        return 0, 0
    downloaded = 0
    existing = 0
    for image in images:
        if not isinstance(image, dict):
            continue
        if image.get("status") == "downloaded":
            downloaded += 1
        local_path = image.get("local_path") or image.get("path") or image.get("file_path")
        if probe_existing and local_path and (archive_dir / str(local_path)).exists():
            existing += 1
    return downloaded, existing


def read_title(raw_dir: Path) -> str:
    try:
        meta = read_json(raw_dir / "meta.json")
    except Exception:
        return ""
    return str(meta.get("title") or "") if isinstance(meta, dict) else ""


def read_quality_grade(raw_dir: Path) -> str:
    try:
        quality = read_json(raw_dir / "quality_report.json")
    except Exception:
        return "ready"
    if isinstance(quality, dict):
        return str(quality.get("quality_grade") or quality.get("grade") or "ready")
    return "ready"


def build_manifest(
    out_path: str | Path,
    max_count: int = 0,
    *,
    processed_root: str | Path = DEFAULT_PROCESSED_ROOT,
    archive_root: str | Path = DEFAULT_ARCHIVE_ROOT,
    probe_existing: bool = True,
) -> int:
    processed_root_display = str(processed_root).replace("\\", "/")
    archive_root_display = str(archive_root).replace("\\", "/")
    processed_root_actual = host_path(processed_root)
    archive_root_actual = host_path(archive_root)
    count = 0
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with out_file.open("w", encoding="utf-8", newline="\n") as out:
        for acct_dir in sorted(path for path in processed_root_actual.iterdir() if path.is_dir()):
            acct = acct_dir.name
            for article_dir in sorted(path for path in acct_dir.iterdir() if path.is_dir()):
                art = article_dir.name
                raw_dir = article_dir / "raw"
                llm_path = raw_dir / "llm_input.md"
                if not llm_path.exists():
                    continue

                meta_path = raw_dir / "meta.json"
                archive_dir = archive_root_actual / acct / art
                archive_local_count, existing_local_count = count_archive_local_images(
                    archive_dir,
                    probe_existing=probe_existing,
                )
                sidecar_image_count = count_sidecar_images(raw_dir)
                processed_asset_image_count = count_processed_assets(raw_dir)
                local_image_count = existing_local_count or archive_local_count

                row = {
                    "article_uid": f"{acct}/{art}",
                    "article_id": art,
                    "source_account": acct,
                    "title": read_title(raw_dir),
                    "quality_grade": read_quality_grade(raw_dir),
                    "llm_input_path": display_path(llm_path, processed_root_actual, processed_root_display),
                    "meta_path": display_path(meta_path, processed_root_actual, processed_root_display)
                    if meta_path.exists()
                    else "",
                    "archive_dir": display_path(archive_dir, archive_root_actual, archive_root_display),
                    "input_chars": read_text_len(llm_path),
                    "local_image_count": local_image_count,
                    "existing_local_image_count": existing_local_count,
                    "archive_asset_image_count": archive_local_count,
                    "processed_asset_image_count": processed_asset_image_count,
                    "sidecar_image_count": sidecar_image_count,
                    "remote_image_count": max(sidecar_image_count, processed_asset_image_count),
                }
                out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                count += 1

                if count % 1000 == 0:
                    print(f"  {count} articles...", flush=True)

                if max_count > 0 and count >= max_count:
                    print(f"Reached max_count={max_count}, stopping")
                    return count

    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", nargs="?", default="/tmp/fullmap_manifest.jsonl")
    parser.add_argument("limit", nargs="?", type=int, default=0)
    parser.add_argument("--processed-root", default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--no-probe-existing",
        action="store_true",
        help="Skip per-image file existence checks; count downloaded asset rows only.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(f"Building manifest from {args.processed_root}")
    print(f"Archive root: {args.archive_root}")
    print(f"Output: {args.out}")
    n = build_manifest(
        args.out,
        args.limit,
        processed_root=args.processed_root,
        archive_root=args.archive_root,
        probe_existing=not args.no_probe_existing,
    )
    print(f"\n{n} articles written to {args.out}")
