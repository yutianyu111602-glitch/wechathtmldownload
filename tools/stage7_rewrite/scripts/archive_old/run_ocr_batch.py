#!/usr/bin/env python3
"""GPU-accelerated OCR batch for WeChat poster images.

Uses EasyOCR with CUDA to extract text from poster images,
then merges results into llm_input.md for LLM extraction.

Usage:
  python scripts/run_ocr_batch.py --manifest reports/flash_ready_manifest_20260509.jsonl \
    --limit 100 --gpu
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import easyocr

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent

# ── GPU OCR Engine ─────────────────────────────────────────────────────────

def get_reader(gpu: bool = True) -> easyocr.Reader:
    """Initialize EasyOCR reader with GPU support."""
    return easyocr.Reader(
        ['ch_sim', 'en'],  # Chinese simplified + English
        gpu=gpu,
        model_storage_directory=str(Path.home() / ".cache" / "easyocr"),
    )


def ocr_image(image_path: str, reader: easyocr.Reader) -> tuple[str, list[dict]]:
    """Run OCR on a single image. Returns (plain_text, blocks)."""
    try:
        results = reader.readtext(image_path, detail=1, paragraph=True)
    except Exception as e:
        return "", [{"error": str(e)}]
    
    blocks = []
    lines = []
    for bbox, text, conf in results:
        blocks.append({
            "text": text,
            "confidence": round(conf, 3),
            "bbox": [[int(x), int(y)] for x, y in bbox],
        })
        if conf > 0.3:  # Only include readable text
            lines.append(text)
    
    plain_text = "\n".join(lines)
    return plain_text, blocks


def ocr_article_poster(
    article_dir: str,
    reader: easyocr.Reader,
    force: bool = False,
) -> dict:
    """OCR all poster images in an article directory. Returns poster_ocr dict."""
    poster_path = os.path.join(article_dir, "poster_ocr.json")
    
    # Skip if already has good OCR result
    if not force and os.path.exists(poster_path):
        try:
            with open(poster_path) as f:
                existing = json.load(f)
            backend = existing.get("backend", "")
            plain = existing.get("plain_text", "")
            if backend and backend != "none" and len(plain) > 20:
                return existing  # Already has good OCR
        except:
            pass
    
    # Load assets
    assets_path = os.path.join(article_dir, "assets_local.json")
    if not os.path.exists(assets_path):
        return {"backend": "none", "error": "no assets_local.json", "plain_text": ""}
    
    try:
        with open(assets_path) as f:
            assets = json.load(f)
    except:
        return {"backend": "none", "error": "invalid assets_local.json", "plain_text": ""}
    
    if not isinstance(assets, list):
        assets = assets.get("images", assets.get("assets", []))
    
    if not assets:
        return {"backend": "none", "error": "no images in assets", "plain_text": ""}
    
    # Load meta for title context
    meta_path = os.path.join(article_dir, "meta.json")
    title = ""
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            title = meta.get("title", "")
        except:
            pass
    
    # OCR each poster image
    all_lines = []
    all_blocks = []
    image_count = 0
    
    for asset in assets[:6]:  # Max 6 poster images
        if not isinstance(asset, dict):
            continue
        img_path = asset.get("local_path", asset.get("path", ""))
        if not img_path:
            continue
        
        # Resolve path — may be relative to article dir
        if not os.path.isabs(img_path):
            img_path = os.path.join(article_dir, img_path)
        
        if not os.path.exists(img_path):
            continue
        
        try:
            plain_text, blocks = ocr_image(img_path, reader)
            if plain_text:
                all_lines.append(plain_text)
            all_blocks.extend(blocks)
            image_count += 1
        except Exception as e:
            all_blocks.append({"error": str(e)})
    
    plain_text = "\n---\n".join(all_lines)
    
    result = {
        "backend": "easyocr-gpu-wsl",
        "imageHeavy": len(assets) > 3 or (len(plain_text) < 200 and len(assets) > 0),
        "image_count": image_count,
        "plain_text": plain_text,
        "blocks": all_blocks,
        "recovered": {
            "venue_name_candidate": "",
            "venue_address_lines": [],
            "date_texts": [],
            "lineup_lines": all_lines[:3] if all_lines else [],
        },
    }
    
    # Save poster_ocr.json
    try:
        with open(poster_path, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except:
        pass
    
    return result


def merge_ocr_into_llm_input(article_dir: str) -> bool:
    """Merge poster_ocr.json text into llm_input.md."""
    poster_path = os.path.join(article_dir, "poster_ocr.json")
    llm_path = os.path.join(article_dir, "llm_input.md")
    
    if not os.path.exists(poster_path) or not os.path.exists(llm_path):
        return False
    
    try:
        with open(poster_path) as f:
            ocr = json.load(f)
        with open(llm_path) as f:
            llm_text = f.read()
    except:
        return False
    
    plain = ocr.get("plain_text", "")
    if not plain or len(plain) < 10:
        return False
    
    # Check if OCR section already exists
    if "## Poster OCR" in llm_text:
        return False  # Already merged
    
    # Append OCR section
    ocr_section = f"\n\n## Poster OCR (GPU-extracted from poster images)\n\n{plain}\n"
    new_text = llm_text + ocr_section
    
    try:
        with open(llm_path, "w") as f:
            f.write(new_text)
        return True
    except:
        return False


# ── Batch Processing ───────────────────────────────────────────────────────

def process_manifest(
    manifest_path: str,
    reader: easyocr.Reader,
    limit: int = 0,
    force: bool = False,
) -> dict:
    """Process articles from manifest JSONL."""
    total = 0
    ocr_ran = 0
    ocr_skipped = 0
    merged = 0
    errors = 0
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            if limit and total >= limit:
                break
            line = line.strip()
            if not line:
                continue
            total += 1
            
            try:
                row = json.loads(line)
            except:
                errors += 1
                continue
            
            llm_path = row.get("llm_input_path", "")
            if not llm_path:
                continue
            
            article_dir = os.path.dirname(llm_path)
            
            # Translate Windows path to WSL
            if article_dir[1:2] == ":":
                drive = article_dir[0].lower()
                rest = article_dir[2:].replace("\\", "/")
                article_dir = f"/mnt/{drive}{rest}"
            
            if not os.path.isdir(article_dir):
                continue
            
            # Check if already has OCR
            poster_path = os.path.join(article_dir, "poster_ocr.json")
            has_ocr = os.path.exists(poster_path)
            if has_ocr and not force:
                try:
                    with open(poster_path) as pf:
                        existing = json.load(pf)
                    if existing.get("backend") and existing["backend"] != "none":
                        ocr_skipped += 1
                        continue
                except:
                    pass
            
            # Run OCR
            try:
                ocr_result = ocr_article_poster(article_dir, reader, force=force)
                if ocr_result.get("backend") != "none":
                    ocr_ran += 1
                    if merge_ocr_into_llm_input(article_dir):
                        merged += 1
                else:
                    ocr_skipped += 1
            except Exception as e:
                errors += 1
            
            if total % 10 == 0:
                print(f"  {total}: ocr={ocr_ran} merged={merged} skipped={ocr_skipped} err={errors}", flush=True)
    
    return {
        "total": total,
        "ocr_ran": ocr_ran,
        "merged": merged,
        "skipped": ocr_skipped,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="Path to manifest JSONL")
    parser.add_argument("--limit", type=int, default=0, help="Max articles to process")
    parser.add_argument("--gpu", action="store_true", default=True, help="Use GPU")
    parser.add_argument("--cpu", dest="gpu", action="store_false", help="Use CPU only")
    parser.add_argument("--force", action="store_true", help="Re-run OCR even if exists")
    args = parser.parse_args()
    
    manifest_path = args.manifest
    if not os.path.isabs(manifest_path):
        manifest_path = str(STAGE7_ROOT / manifest_path)
    
    print(f"OCR Batch: {manifest_path}")
    print(f"  GPU: {args.gpu}, Force: {args.force}, Limit: {args.limit or 'all'}")
    
    started = time.perf_counter()
    reader = get_reader(gpu=args.gpu)
    print(f"  Reader ready in {time.perf_counter() - started:.1f}s")
    
    started = time.perf_counter()
    stats = process_manifest(manifest_path, reader, limit=args.limit, force=args.force)
    elapsed = time.perf_counter() - started
    
    print(f"\nDone in {elapsed:.0f}s")
    print(f"  Total: {stats['total']}")
    print(f"  OCR ran: {stats['ocr_ran']}")
    print(f"  Merged to llm_input.md: {stats['merged']}")
    print(f"  Skipped (already has OCR): {stats['skipped']}")
    print(f"  Errors: {stats['errors']}")


if __name__ == "__main__":
    main()
