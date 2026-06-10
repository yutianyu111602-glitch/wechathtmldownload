#!/usr/bin/env python3
"""Repair Full-Map manifest text/image counts without rebuilding from D: trees."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = Path("reports/fullmap_manifest_20260513.jsonl")
DEFAULT_OUT = Path("reports/ocr_root_cause_20260515/fullmap_manifest_fixed_full_20260515.jsonl")
DEFAULT_ARCHIVE_ROOT = Path(
    "D:/downstream_results/stage7_rewrite/longrun/WHERE_TO_RAVE_WECHAT_SYNC_20260508/"
    "FULL_MAP_SMART_BACKFILL_20260509/mptext_archive_FULL_MAP_SMART_BACKFILL_20260509"
)


def manifest_key(account: str, token: str) -> str:
    return f"{account}/{token}"


def host_path(value: str | Path | None) -> Path:
    if not value:
        return Path("")
    raw = str(value).replace("\\", "/")
    if os.name == "nt" and raw.startswith("/mnt/d/"):
        return Path("D:/" + raw.removeprefix("/mnt/d/"))
    if os.name == "nt" and raw == "/mnt/d":
        return Path("D:/")
    return Path(raw)


def path_for_json(path: Path) -> str:
    return str(path).replace("\\", "/")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def load_asset_result_counts(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    result_path = host_path(path)
    if not result_path.exists():
        return {}
    counts: dict[str, dict[str, Any]] = {}
    with result_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            account = str(row.get("account_key") or "")
            token = str(row.get("token") or "")
            if not account or not token:
                continue
            counts[manifest_key(account, token)] = {
                "image_count": int(row.get("image_count") or 0),
                "downloaded_count": int(row.get("downloaded_count") or 0),
                "status": str(row.get("status") or ""),
            }
    return counts


def load_images(path: Path) -> list[dict[str, Any]]:
    try:
        data = read_json(path)
    except Exception:
        return []
    images = data if isinstance(data, list) else data.get("images", [])
    return [item for item in images if isinstance(item, dict)] if isinstance(images, list) else []


def image_local_path(image: dict[str, Any]) -> str:
    return str(
        image.get("local_path")
        or image.get("path")
        or image.get("file_path")
        or image.get("filename")
        or image.get("name")
        or ""
    )


def count_archive_images(archive_dir: Path, *, probe_existing: bool) -> tuple[int, int, bool]:
    assets_path = archive_dir / "assets_local.json"
    images = load_images(assets_path)
    if not images:
        return 0, 0, assets_path.exists()
    downloaded = 0
    existing = 0
    for image in images:
        if image.get("status") == "downloaded":
            downloaded += 1
        local = image_local_path(image)
        if probe_existing and local and (archive_dir / local).exists():
            existing += 1
    return downloaded, existing, True


def count_processed_images(raw_dir: Path) -> tuple[int, bool]:
    assets_path = raw_dir / "assets.json"
    images = load_images(assets_path)
    return len(images), assets_path.exists()


def count_sidecar_images(raw_dir: Path) -> int:
    try:
        sidecar = read_json(raw_dir / "sidecar.json")
    except Exception:
        return 0
    images = sidecar.get("images", []) if isinstance(sidecar, dict) else []
    return len(images) if isinstance(images, list) else 0


def recount_chars_if_needed(row: dict[str, Any], threshold: int) -> int:
    try:
        current = int(row.get("input_chars") or 0)
    except Exception:
        current = 0
    if threshold <= 0 or current > threshold:
        return current
    llm_path = host_path(row.get("llm_input_path"))
    try:
        return len(llm_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return current


def derive_archive_dir(row: dict[str, Any], archive_root: Path) -> Path:
    if row.get("archive_dir"):
        return host_path(row.get("archive_dir"))
    account = str(row.get("source_account") or row.get("account") or "")
    article_id = str(row.get("article_id") or "")
    if account and article_id:
        return archive_root / account / article_id
    llm_path = host_path(row.get("llm_input_path"))
    if llm_path and len(llm_path.parts) >= 3:
        return archive_root / llm_path.parts[-4] / llm_path.parts[-3]
    return Path("")


def repair_manifest(
    manifest: Path,
    out_path: Path,
    *,
    archive_root: Path,
    char_recount_threshold: int,
    probe_existing: bool,
    read_processed_assets: bool = True,
    read_sidecar: bool = True,
    asset_results_path: Path | None = None,
    limit: int = 0,
) -> dict[str, Any]:
    archive_root = host_path(archive_root)
    asset_result_counts = load_asset_result_counts(asset_results_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    local_image_gt0 = 0
    empty_no_local_image = 0
    needs_ocr_local_image = 0
    with manifest.open("r", encoding="utf-8", errors="replace") as src, out_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as out:
        for line in src:
            if not line.strip():
                continue
            row = json.loads(line)
            raw_dir = host_path(row.get("llm_input_path")).parent
            archive_dir = derive_archive_dir(row, archive_root)
            key = manifest_key(str(row.get("source_account") or ""), str(row.get("article_id") or ""))
            if key in asset_result_counts:
                asset_counts = asset_result_counts[key]
                archive_count = int(asset_counts.get("image_count") or 0)
                existing_count = int(asset_counts.get("downloaded_count") or 0)
                has_assets_local = str(asset_counts.get("status") or "") in {"succeeded", "skipped"}
            else:
                archive_count, existing_count, has_assets_local = count_archive_images(
                    archive_dir,
                    probe_existing=probe_existing,
                )
            processed_count, has_processed_assets = (
                count_processed_images(raw_dir) if read_processed_assets else (0, (raw_dir / "assets.json").exists())
            )
            sidecar_count = count_sidecar_images(raw_dir) if read_sidecar else 0
            local_count = existing_count or archive_count
            input_chars = recount_chars_if_needed(row, char_recount_threshold)
            repaired = {
                **row,
                "archive_dir": path_for_json(archive_dir) if archive_dir else "",
                "input_chars": input_chars,
                "local_image_count": local_count,
                "existing_local_image_count": existing_count,
                "archive_asset_image_count": archive_count,
                "processed_asset_image_count": processed_count,
                "sidecar_image_count": sidecar_count,
                "remote_image_count": max(sidecar_count, processed_count, archive_count),
                "has_assets_local": has_assets_local,
                "has_processed_assets": has_processed_assets,
            }
            out.write(json.dumps(repaired, ensure_ascii=False, sort_keys=True) + "\n")
            rows += 1
            if local_count > 0:
                local_image_gt0 += 1
            if input_chars <= 80 and local_count > 0:
                needs_ocr_local_image += 1
            if input_chars <= 80 and local_count == 0:
                empty_no_local_image += 1
            if limit and rows >= limit:
                break
    return {
        "manifest": path_for_json(manifest),
        "out_path": path_for_json(out_path),
        "rows": rows,
        "local_image_gt0": local_image_gt0,
        "needs_ocr_local_image": needs_ocr_local_image,
        "empty_no_local_image": empty_no_local_image,
        "probe_existing": probe_existing,
        "char_recount_threshold": char_recount_threshold,
        "read_processed_assets": read_processed_assets,
        "read_sidecar": read_sidecar,
        "asset_results_path": path_for_json(asset_results_path) if asset_results_path else "",
        "asset_result_rows": len(asset_result_counts),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--char-recount-threshold", type=int, default=2000)
    parser.add_argument("--probe-existing", action="store_true")
    parser.add_argument("--no-processed-assets", action="store_true")
    parser.add_argument("--no-sidecar", action="store_true")
    parser.add_argument("--asset-results", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = repair_manifest(
        args.manifest,
        args.out,
        archive_root=args.archive_root,
        char_recount_threshold=args.char_recount_threshold,
        probe_existing=args.probe_existing,
        read_processed_assets=not args.no_processed_assets,
        read_sidecar=not args.no_sidecar,
        asset_results_path=args.asset_results,
        limit=args.limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
