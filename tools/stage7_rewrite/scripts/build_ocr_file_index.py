#!/usr/bin/env python3
"""Build a bounded OCR file index from an existing Stage7 manifest.

The script never recursively scans D:. It reads a prepared JSONL manifest on C:,
derives exact processed/archive paths for each row, optionally probes only those
fixed paths, and writes a report-local index plus a tiny latest pointer.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = Path("reports/fullmap_manifest_20260513_routes/needs_ocr.remaining.jsonl")
DEFAULT_PROCESSED_ROOT = Path(
    "D:/downstream_results/stage7_rewrite/longrun/WHERE_TO_RAVE_WECHAT_SYNC_20260508/"
    "FULL_MAP_SMART_BACKFILL_20260509/processed_FULL_MAP_SMART_BACKFILL_20260509"
)
DEFAULT_ARCHIVE_ROOT = Path(
    "D:/downstream_results/stage7_rewrite/longrun/WHERE_TO_RAVE_WECHAT_SYNC_20260508/"
    "FULL_MAP_SMART_BACKFILL_20260509/mptext_archive_FULL_MAP_SMART_BACKFILL_20260509"
)
DEFAULT_OUT_DIR = Path("reports/ocr_file_index_20260515")
DEFAULT_LATEST_POINTER = Path("reports/ocr_file_index_latest.json")

BANNED_ROOTS = {
    "d:",
    "d:/",
    "d:/ddownload",
    "d:/aidata",
    "/mnt/d",
    "/mnt/d/",
    "/mnt/d/ddownload",
    "/mnt/d/aidata",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def path_for_json(path: Path) -> str:
    return str(path).replace("\\", "/")


def host_path(value: str | Path | None) -> Path:
    if not value:
        return Path("")
    raw = str(value).replace("\\", "/")
    if raw == "/mnt/d":
        return Path("D:/")
    if raw.startswith("/mnt/d/"):
        return Path("D:/" + raw.removeprefix("/mnt/d/"))
    return Path(raw)


def norm_path_for_guard(path: Path) -> str:
    return path_for_json(path).rstrip("/").casefold()


def reject_broad_d_root(path: Path, label: str) -> None:
    normalized = norm_path_for_guard(host_path(path))
    if normalized in {root.rstrip("/").casefold() for root in BANNED_ROOTS}:
        raise ValueError(f"{label} refuses broad D root: {path}")


def is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def iter_jsonl(path: Path, limit: int = 0):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for idx, line in enumerate(handle, start=1):
            if limit and idx > limit:
                break
            if line.strip():
                yield json.loads(line)


def safe_exists(path: Path, probe_files: bool) -> bool:
    return bool(probe_files and path and path.exists())


def safe_mtime(path: Path, probe_files: bool) -> str:
    if not probe_files or not path or not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")


def load_assets(assets_path: Path, probe_files: bool) -> list[dict[str, Any]]:
    if not safe_exists(assets_path, probe_files):
        return []
    try:
        data = read_json(assets_path)
    except Exception:
        return []
    images = data if isinstance(data, list) else data.get("images", [])
    return [item for item in images if isinstance(item, dict)]


def image_local_path(image: dict[str, Any]) -> str:
    return str(
        image.get("local_path")
        or image.get("path")
        or image.get("file_path")
        or image.get("filename")
        or image.get("name")
        or ""
    )


def poster_ocr_status(poster_path: Path, probe_files: bool) -> str:
    if not safe_exists(poster_path, probe_files):
        return "missing"
    try:
        data = read_json(poster_path)
    except Exception:
        return "corrupt"
    backend = str(data.get("backend") or "")
    plain_text = str(data.get("plain_text") or "")
    if backend and backend != "none" and plain_text.strip():
        return "complete"
    if backend == "none":
        return "no_text"
    return "present_without_text"


def derive_raw_dir(row: dict[str, Any]) -> Path:
    raw_dir = row.get("raw_dir") or row.get("raw_path") or row.get("processed_dir")
    if raw_dir:
        return host_path(raw_dir)
    llm_input = row.get("llm_input_path")
    if llm_input:
        return host_path(llm_input).parent
    meta_path = row.get("meta_path")
    if meta_path:
        return host_path(meta_path).parent
    return Path("")


def derive_archive_dir(row: dict[str, Any], raw_dir: Path, processed_root: Path, archive_root: Path) -> Path:
    archive_dir = row.get("archive_dir") or row.get("archive_path")
    if archive_dir:
        return host_path(archive_dir)
    account = str(row.get("source_account") or row.get("account") or "")
    article_id = str(row.get("article_id") or "")
    if account and article_id:
        return archive_root / account / article_id
    if raw_dir and is_under(raw_dir, processed_root):
        rel = raw_dir.relative_to(processed_root)
        if rel.parts and rel.parts[-1] == "raw":
            rel = Path(*rel.parts[:-1])
        return archive_root / rel
    return Path("")


def build_record(row: dict[str, Any], processed_root: Path, archive_root: Path, probe_files: bool) -> dict[str, Any]:
    raw_dir = derive_raw_dir(row)
    archive_dir = derive_archive_dir(row, raw_dir, processed_root, archive_root)
    llm_input_path = host_path(row.get("llm_input_path")) if row.get("llm_input_path") else raw_dir / "llm_input.md"
    sidecar_path = host_path(row.get("sidecar_path")) if row.get("sidecar_path") else raw_dir / "sidecar.json"
    meta_path = host_path(row.get("meta_path")) if row.get("meta_path") else raw_dir / "meta.json"
    poster_ocr_path = raw_dir / "poster_ocr.json"
    assets_local_path = archive_dir / "assets_local.json"
    processed_assets_path = raw_dir / "assets.json"
    archive_assets = load_assets(assets_local_path, probe_files)
    processed_assets = load_assets(processed_assets_path, probe_files)
    assets = archive_assets or processed_assets
    local_image_count = len(assets) if assets else int(row.get("local_image_count") or 0)
    existing_local_image_count = 0
    if probe_files and assets:
        for image in assets:
            local = image_local_path(image)
            if not local:
                continue
            candidates = [archive_dir / local, raw_dir / local]
            if any(path.exists() for path in candidates):
                existing_local_image_count += 1
    mtimes = [
        safe_mtime(path, probe_files)
        for path in [llm_input_path, sidecar_path, meta_path, poster_ocr_path, assets_local_path, processed_assets_path]
    ]
    last_write_time = max([value for value in mtimes if value], default="")

    return {
        "schema_version": "ocr_file_index.v1",
        "article_uid": str(row.get("article_uid") or ""),
        "source_account": str(row.get("source_account") or row.get("account") or ""),
        "article_id": str(row.get("article_id") or ""),
        "processed_dir": path_for_json(raw_dir),
        "archive_dir": path_for_json(archive_dir),
        "llm_input_path": path_for_json(llm_input_path),
        "sidecar_path": path_for_json(sidecar_path),
        "meta_path": path_for_json(meta_path),
        "poster_ocr_path": path_for_json(poster_ocr_path),
        "assets_local_path": path_for_json(assets_local_path),
        "processed_assets_path": path_for_json(processed_assets_path),
        "has_llm_input": safe_exists(llm_input_path, probe_files),
        "has_sidecar": safe_exists(sidecar_path, probe_files),
        "has_meta": safe_exists(meta_path, probe_files),
        "has_poster_ocr": safe_exists(poster_ocr_path, probe_files),
        "has_assets_local": safe_exists(assets_local_path, probe_files),
        "has_processed_assets": safe_exists(processed_assets_path, probe_files),
        "archive_asset_image_count": len(archive_assets),
        "processed_asset_image_count": len(processed_assets),
        "local_image_count": local_image_count,
        "existing_local_image_count": existing_local_image_count,
        "quality_grade": str(row.get("quality_grade") or ""),
        "ocr_status": poster_ocr_status(poster_ocr_path, probe_files),
        "last_write_time": last_write_time,
    }


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as handle:
        tmp_name = handle.name
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(tmp_name, path)


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# OCR File Index Report",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- status: `{summary['status']}`",
        f"- manifest_path: `{summary['manifest_path']}`",
        f"- record_count: `{summary['record_count']}`",
        f"- probe_files: `{summary['probe_files']}`",
        f"- index_path: `{summary['index_path']}`",
        f"- latest_pointer: `{summary['latest_pointer']}`",
        "",
        "## OCR Status",
        "",
    ]
    for status, count in sorted(summary["ocr_status_counts"].items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Quality Grade", ""])
    for grade, count in sorted(summary["quality_grade_counts"].items()):
        lines.append(f"- `{grade}`: {count}")
    lines.extend(["", "## Asset Counts", ""])
    for name, count in sorted(summary["asset_counts"].items()):
        lines.append(f"- `{name}`: {count}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- No recursive D: scan is used.",
            "- The script reads a prepared manifest and probes only fixed paths derived from each row.",
            "- Output is report-only: JSONL index, latest pointer, summary JSON, and markdown.",
            "- OCR execution remains a separate canary gate.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_index(
    manifest: Path,
    out_dir: Path,
    latest_pointer: Path,
    processed_root: Path,
    archive_root: Path,
    limit: int,
    probe_files: bool,
    build_index_file: bool,
) -> dict[str, Any]:
    reject_broad_d_root(processed_root, "processed_root")
    reject_broad_d_root(archive_root, "archive_root")
    if not manifest.exists():
        raise FileNotFoundError(f"manifest not found: {manifest}")

    rows = [
        build_record(row, processed_root=processed_root, archive_root=archive_root, probe_files=probe_files)
        for row in iter_jsonl(manifest, limit=limit)
    ]
    generated_at = now_iso()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    index_path = out_dir / f"ocr_file_index_{stamp}.jsonl"
    if build_index_file:
        write_jsonl_atomic(index_path, rows)

    status_counts = Counter(row["ocr_status"] for row in rows)
    quality_counts = Counter(row["quality_grade"] or "unknown" for row in rows)
    account_counts = Counter(row["source_account"] or "unknown" for row in rows)
    asset_counts = {
        "archive_asset_image_gt0": sum(1 for row in rows if int(row["archive_asset_image_count"] or 0) > 0),
        "existing_local_image_gt0": sum(1 for row in rows if int(row["existing_local_image_count"] or 0) > 0),
        "has_assets_local": sum(1 for row in rows if row["has_assets_local"]),
        "has_processed_assets": sum(1 for row in rows if row["has_processed_assets"]),
        "local_image_gt0": sum(1 for row in rows if int(row["local_image_count"] or 0) > 0),
        "processed_asset_image_gt0": sum(1 for row in rows if int(row["processed_asset_image_count"] or 0) > 0),
    }
    summary = {
        "schema_version": "ocr_file_index.summary.v1",
        "generated_at": generated_at,
        "status": "complete" if build_index_file else "plan",
        "manifest_path": path_for_json(manifest),
        "source_root": path_for_json(processed_root),
        "archive_root": path_for_json(archive_root),
        "index_path": path_for_json(index_path) if build_index_file else "",
        "latest_pointer": path_for_json(latest_pointer) if build_index_file else "",
        "record_count": len(rows),
        "limit": limit,
        "probe_files": probe_files,
        "ocr_status_counts": dict(status_counts),
        "quality_grade_counts": dict(quality_counts),
        "asset_counts": asset_counts,
        "top_source_accounts": dict(account_counts.most_common(20)),
        "sample_records": rows[:10],
        "safety": {
            "recursive_scan": False,
            "writes": "reports only",
            "ocr_execution": False,
            "d_roots_rejected": sorted(BANNED_ROOTS),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "ocr_file_index_summary.json", summary)
    write_markdown(out_dir / "ocr_file_index_summary.md", summary)
    if build_index_file:
        pointer = {
            "schema_version": "ocr_file_index.v1",
            "index_path": path_for_json(index_path),
            "generated_at": generated_at,
            "source_root": path_for_json(processed_root),
            "archive_root": path_for_json(archive_root),
            "manifest_path": path_for_json(manifest),
            "record_count": len(rows),
            "status": "complete",
            "probe_files": probe_files,
            "summary_path": path_for_json(out_dir / "ocr_file_index_summary.json"),
        }
        write_json(out_dir / "ocr_file_index_latest.json", pointer)
        write_json(latest_pointer, pointer)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--latest-pointer", type=Path, default=DEFAULT_LATEST_POINTER)
    parser.add_argument("--limit", type=int, default=0, help="Optional row cap for canary/plan runs")
    parser.add_argument("--no-probe-files", action="store_true", help="Do not touch derived artifact paths")
    parser.add_argument("--build-index", action="store_true", help="Write the JSONL index and latest pointer")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_index(
        manifest=args.manifest,
        out_dir=args.out_dir,
        latest_pointer=args.latest_pointer,
        processed_root=host_path(args.processed_root),
        archive_root=host_path(args.archive_root),
        limit=args.limit,
        probe_files=not args.no_probe_files,
        build_index_file=args.build_index,
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "record_count": summary["record_count"],
                "probe_files": summary["probe_files"],
                "index_path": summary["index_path"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
