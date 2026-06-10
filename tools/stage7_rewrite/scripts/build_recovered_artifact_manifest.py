#!/usr/bin/env python3
"""Build a Stage7 manifest from recovered process artifacts.

This is for report/staging artifacts produced by Dajiala recovery waves. It
does not call APIs, scan D: recursively, or mutate production trees.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def compact(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def norm_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def count_json_images(path: Path) -> int:
    data = read_json(path)
    images = data if isinstance(data, list) else data.get("images", [])
    return len(images) if isinstance(images, list) else 0


def count_existing_image_files(raw_dir: Path) -> int:
    image_dir = raw_dir / "images"
    if not image_dir.exists() or not image_dir.is_dir():
        return 0
    return sum(1 for path in image_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)


def quality_grade(raw_dir: Path) -> str:
    quality = read_json(raw_dir / "quality_report.json")
    return str(quality.get("quality_grade") or quality.get("grade") or "ready")


def poster_ocr_stats(raw_dir: Path) -> dict[str, Any]:
    poster = read_json(raw_dir / "poster_ocr.json")
    blocks = poster.get("blocks", [])
    texts = [str(block.get("text") or "") for block in blocks if isinstance(block, dict)]
    plain_text = str(poster.get("plain_text") or "")
    joined_text = "\n".join(text for text in [plain_text, *texts] if text.strip())
    return {
        "poster_ocr_backend": str(poster.get("backend") or ""),
        "poster_ocr_blocks": len(texts),
        "poster_ocr_text_chars": len(joined_text),
    }


def article_root_from_meta(meta_path: Path) -> tuple[Path, Path]:
    raw_dir = meta_path.parent
    if raw_dir.name == "raw" and (raw_dir / "llm_input.md").exists():
        return raw_dir.parent, raw_dir
    return raw_dir, raw_dir


def account_article_id(process_root: Path, article_dir: Path) -> tuple[str, str] | None:
    try:
        rel = article_dir.relative_to(process_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def build_row(process_root: Path, meta_path: Path) -> dict[str, Any] | None:
    article_dir, raw_dir = article_root_from_meta(meta_path)
    account_art = account_article_id(process_root, article_dir)
    if not account_art:
        return None
    account, article_id = account_art
    llm_input = raw_dir / "llm_input.md"
    if not llm_input.exists():
        return None

    meta = read_json(meta_path)
    processed_asset_count = count_json_images(raw_dir / "assets.json")
    sidecar_image_count = count_json_images(raw_dir / "sidecar.json")
    existing_image_count = count_existing_image_files(raw_dir)
    local_image_count = max(existing_image_count, processed_asset_count)
    ocr = poster_ocr_stats(raw_dir)
    llm_text = llm_input.read_text(encoding="utf-8", errors="replace")
    has_poster_ocr_section = "## Poster OCR" in llm_text

    row = {
        "article_uid": f"{account}/{article_id}",
        "article_id": article_id,
        "source_account": str(meta.get("account_name") or meta.get("account") or account),
        "title": compact(meta.get("title"), 300),
        "quality_grade": quality_grade(raw_dir),
        "llm_input_path": norm_path(llm_input),
        "meta_path": norm_path(meta_path),
        "artifact_dir": norm_path(raw_dir),
        "process_root": norm_path(process_root),
        "input_chars": len(llm_text),
        "local_image_count": local_image_count,
        "existing_local_image_count": existing_image_count,
        "processed_asset_image_count": processed_asset_count,
        "sidecar_image_count": sidecar_image_count,
        "remote_image_count": max(sidecar_image_count, processed_asset_count),
        "has_poster_ocr_section": has_poster_ocr_section,
        "status": "pending",
        "recovery_source": "dajiala_empty_no_local_image_staging",
    }
    row.update(ocr)
    return row


def build_manifest(process_roots: list[Path], out_dir: Path) -> dict[str, Any]:
    rows_by_uid: dict[str, dict[str, Any]] = {}
    skipped_meta = 0
    duplicate_rows = 0
    roots = [root.resolve() for root in process_roots]
    for root in roots:
        for meta_path in sorted(root.rglob("meta.json")):
            row = build_row(root, meta_path)
            if row is None:
                skipped_meta += 1
                continue
            uid = str(row["article_uid"])
            if uid in rows_by_uid:
                duplicate_rows += 1
                continue
            rows_by_uid[uid] = row

    rows = sorted(rows_by_uid.values(), key=lambda item: (str(item["source_account"]), str(item["article_id"])))
    manifest_path = out_dir / "recovered_manifest.jsonl"
    summary_path = out_dir / "summary.json"
    summary_md_path = out_dir / "summary.md"
    write_jsonl(manifest_path, rows)

    quality_counts = Counter(str(row.get("quality_grade") or "") for row in rows)
    backend_counts = Counter(str(row.get("poster_ocr_backend") or "<missing>") for row in rows)
    summary = {
        "schema_version": "stage7_recovered_artifact_manifest.v1",
        "generated_at": now_iso(),
        "process_roots": [norm_path(root) for root in roots],
        "rows": len(rows),
        "skipped_meta": skipped_meta,
        "duplicate_rows": duplicate_rows,
        "local_image_rows": sum(1 for row in rows if int(row.get("local_image_count") or 0) > 0),
        "poster_ocr_section_rows": sum(1 for row in rows if row.get("has_poster_ocr_section")),
        "poster_ocr_text_rows": sum(1 for row in rows if int(row.get("poster_ocr_text_chars") or 0) > 0),
        "quality_grade_counts": dict(sorted(quality_counts.items())),
        "poster_ocr_backend_counts": dict(sorted(backend_counts.items())),
        "outputs": {
            "manifest": norm_path(manifest_path),
            "summary": norm_path(summary_path),
            "summary_md": norm_path(summary_md_path),
        },
        "writes": "C: report/staging manifest only; no API/archive/vector/DB writes",
    }
    write_json(summary_path, summary)
    summary_md_path.write_text(
        "\n".join(
            [
                "# Recovered Artifact Manifest Summary",
                "",
                f"- generated_at: `{summary['generated_at']}`",
                f"- rows: `{summary['rows']}`",
                f"- local_image_rows: `{summary['local_image_rows']}`",
                f"- poster_ocr_section_rows: `{summary['poster_ocr_section_rows']}`",
                f"- poster_ocr_text_rows: `{summary['poster_ocr_text_rows']}`",
                f"- manifest: `{summary['outputs']['manifest']}`",
                f"- writes: `{summary['writes']}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process-root", action="append", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_manifest(args.process_root, args.out_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
