#!/usr/bin/env python3
"""Safe direct OCR runner for Stage7 poster images.

Default behavior is report-only. Use `--dry-run --limit N` for a bounded
candidate check, or add `--execute` to actually write `poster_ocr.json`.
The script refuses broad D: roots and never scans D unless explicit scoped roots
or a manifest are provided.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_ARCHIVE = Path(
    "/mnt/d/downstream_results/stage7_rewrite/longrun/WHERE_TO_RAVE_WECHAT_SYNC_20260508/"
    "FULL_MAP_SMART_BACKFILL_20260509/mptext_archive_FULL_MAP_SMART_BACKFILL_20260509"
)
DEFAULT_PROCESSED = Path(
    "/mnt/d/downstream_results/stage7_rewrite/longrun/WHERE_TO_RAVE_WECHAT_SYNC_20260508/"
    "FULL_MAP_SMART_BACKFILL_20260509/processed_FULL_MAP_SMART_BACKFILL_20260509"
)
DEFAULT_OCR_SCRIPT = Path("/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/ocr_gpu.py")
DEFAULT_OUT_DIR = Path("reports/ocr_direct_safe_cli_20260514")

BANNED_ROOTS = {
    "d:/",
    "d:",
    "/mnt/d",
    "/mnt/d/",
    "/mnt/d/ddownload",
    "/mnt/d/aidata",
    "d:/ddownload",
    "d:/aidata",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def norm_path_for_guard(path: Path) -> str:
    return str(path).replace("\\", "/").rstrip("/").casefold()


def reject_broad_d_root(path: Path, label: str) -> None:
    normalized = norm_path_for_guard(path)
    if normalized in {root.rstrip("/").casefold() for root in BANNED_ROOTS}:
        raise ValueError(f"{label} refuses broad D root: {path}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def has_good_ocr(poster_path: Path) -> bool:
    if not poster_path.exists():
        return False
    try:
        data = read_json(poster_path)
    except Exception:
        return False
    return bool(data.get("backend") and data.get("backend") != "none" and data.get("plain_text"))


def load_images(archive_art: Path) -> list[dict[str, Any]]:
    assets_path = archive_art / "assets_local.json"
    if not assets_path.exists():
        return []
    try:
        assets = read_json(assets_path)
    except Exception:
        return []
    images = assets if isinstance(assets, list) else assets.get("images", [])
    return [img for img in images if isinstance(img, dict)]


def has_existing_image(archive_art: Path, images: list[dict[str, Any]], sample: int = 2) -> bool:
    for img in images[:sample]:
        local = str(img.get("local_path") or "")
        if local and (archive_art / local).exists():
            return True
    return False


def iter_manifest_pairs(manifest: Path):
    with manifest.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            raw_dir = Path(row.get("raw_dir") or row.get("raw_path") or "")
            archive_art = Path(row.get("archive_dir") or row.get("archive_path") or "")
            if raw_dir and archive_art:
                yield raw_dir, archive_art


def find_articles(processed_root: Path, archive_root: Path, limit: int = 0) -> list[tuple[Path, Path]]:
    """Find processed articles that have archive images under explicit roots."""
    reject_broad_d_root(processed_root, "processed_root")
    reject_broad_d_root(archive_root, "archive_root")
    articles: list[tuple[Path, Path]] = []
    if not processed_root.exists() or not archive_root.exists():
        return articles

    for acct_dir in sorted(processed_root.iterdir()):
        if not acct_dir.is_dir():
            continue
        for art_dir in sorted(acct_dir.iterdir()):
            if not art_dir.is_dir():
                continue
            raw_dir = art_dir / "raw"
            if not raw_dir.exists() or has_good_ocr(raw_dir / "poster_ocr.json"):
                continue
            archive_art = archive_root / acct_dir.name / art_dir.name
            images = load_images(archive_art)
            if images and has_existing_image(archive_art, images):
                articles.append((raw_dir, archive_art))
                if limit and len(articles) >= limit:
                    return articles
    return articles


def candidate_pairs(args: argparse.Namespace) -> list[tuple[Path, Path]]:
    if args.manifest:
        pairs = []
        for raw_dir, archive_art in iter_manifest_pairs(args.manifest):
            if has_good_ocr(raw_dir / "poster_ocr.json"):
                continue
            images = load_images(archive_art)
            if images and has_existing_image(archive_art, images):
                pairs.append((raw_dir, archive_art))
                if args.limit and len(pairs) >= args.limit:
                    break
        return pairs
    if not args.execute and not args.dry_run:
        return []
    return find_articles(args.processed_root, args.archive_root, limit=args.limit)


def ocr_article(raw_dir: Path, archive_art: Path, ocr_script: Path, timeout: int, max_images: int) -> bool:
    """Run OCR on an article's images and write poster_ocr.json."""
    images = load_images(archive_art)
    results = []
    candidates = []
    for img in images[:max_images]:
        local = str(img.get("local_path") or "")
        img_path = archive_art / local
        if not local or not img_path.exists():
            continue
        if img_path.suffix.lower() in {".gif", ".svg", ".webp", ".bmp"}:
            continue
        if img_path.stat().st_size < 10000:
            continue
        candidates.append({"asset_id": img.get("asset_id", ""), "local_path": local})
        try:
            result = subprocess.run(
                [sys.executable, str(ocr_script), str(img_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            continue
        if result.returncode != 0:
            continue
        try:
            json_line = result.stdout.strip().split("\n")[0]
            results.append(json.loads(json_line))
        except Exception:
            continue

    if not results:
        poster_ocr = {
            "backend": "none",
            "plain_text": "",
            "blocks": [],
            "imageHeavy": False,
            "candidates": candidates,
            "recovered": {"venue_name_candidate": "", "date_texts": [], "lineup_lines": []},
            "warnings": [],
        }
    else:
        plain_text = "\n".join(str(r.get("plain_text") or "") for r in results)
        blocks = []
        for result in results:
            blocks.extend(result.get("blocks", []) or [])
        poster_ocr = {
            "backend": results[0].get("backend", "merged"),
            "plain_text": plain_text,
            "blocks": blocks,
            "imageHeavy": len(plain_text) < 100,
            "candidates": candidates,
            "recovered": results[0].get("recovered", {}),
            "warnings": [],
        }
    (raw_dir / "poster_ocr.json").write_text(json.dumps(poster_ocr, ensure_ascii=False), encoding="utf-8")
    return bool(results)


def write_report(out_dir: Path, payload: dict[str, Any]) -> None:
    write_json(out_dir / "ocr_direct_safe_cli_report.json", payload)
    lines = [
        "# OCR Direct Safe CLI Report",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- mode: `{payload['mode']}`",
        f"- candidates: `{payload['candidates']}`",
        f"- executed: `{payload['executed']}`",
        f"- ok: `{payload['ok']}`",
        f"- no_text: `{payload['no_text']}`",
        "",
        "## Safety",
        "",
        "- `--help` and default invocation do not scan D:.",
        "- `--execute` is required before writing `poster_ocr.json`.",
        "- Broad D roots are rejected.",
    ]
    (out_dir / "ocr_direct_safe_cli_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED)
    parser.add_argument("--ocr-script", type=Path, default=DEFAULT_OCR_SCRIPT)
    parser.add_argument("--manifest", type=Path, default=None, help="Optional JSONL with raw_dir/archive_dir pairs")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-images", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true", help="Find bounded candidates but do not OCR/write")
    parser.add_argument("--execute", action="store_true", help="Actually run OCR and write poster_ocr.json")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.execute and args.dry_run:
        raise ValueError("--execute and --dry-run are mutually exclusive")
    reject_broad_d_root(args.archive_root, "archive_root")
    reject_broad_d_root(args.processed_root, "processed_root")

    pairs = candidate_pairs(args)
    payload = {
        "schema_version": "stage7_ocr_direct_safe_cli.v1",
        "generated_at": now_iso(),
        "mode": "execute" if args.execute else ("dry-run" if args.dry_run else "plan"),
        "archive_root": str(args.archive_root),
        "processed_root": str(args.processed_root),
        "manifest": str(args.manifest) if args.manifest else "",
        "limit": args.limit,
        "candidates": len(pairs),
        "executed": 0,
        "ok": 0,
        "no_text": 0,
        "candidate_preview": [{"raw_dir": str(raw), "archive_dir": str(archive)} for raw, archive in pairs[:20]],
    }
    if args.execute:
        for idx, (raw_dir, archive_art) in enumerate(pairs, start=1):
            t0 = time.perf_counter()
            success = ocr_article(raw_dir, archive_art, args.ocr_script, args.timeout, args.max_images)
            payload["executed"] += 1
            payload["ok" if success else "no_text"] += 1
            if idx % 10 == 0:
                print(f"[{idx}/{len(pairs)}] ok={payload['ok']} no_text={payload['no_text']} elapsed={time.perf_counter()-t0:.1f}s")
    write_report(args.out_dir, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run(args)
    print(json.dumps({"mode": report["mode"], "candidates": report["candidates"], "executed": report["executed"], "ok": report["ok"], "no_text": report["no_text"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
