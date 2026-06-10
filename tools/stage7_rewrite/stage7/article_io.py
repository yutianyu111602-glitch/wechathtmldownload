"""Article input loader: read text evidence, meta, OCR from article directories."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from .atomic_io import safe_read_text, safe_read_json


TEXT_CANDIDATES = [
    "llm_input.md",
    "clean.md",
    "article.md",
]

META_CANDIDATES = [
    "meta.json",
]

OCR_CANDIDATES = [
    "poster_ocr.json",
    "image_ocr.json",
]


def load_article_inputs(article_dir: Path) -> dict[str, Any]:
    """Load all inputs for a single article directory.

    Returns dict with:
      - text: str (primary article text)
      - text_source: str (which file was used)
      - text_fallback_chain: list[str]
      - meta: dict
      - meta_source: str
      - ocr: dict (raw OCR JSON if present)
      - ocr_source: str
      - warnings: list[str]
    """
    result: dict[str, Any] = {
        "text": "",
        "text_source": "",
        "text_fallback_chain": [],
        "meta": {},
        "meta_source": "",
        "ocr": {},
        "ocr_source": "",
        "warnings": [],
    }

    # 1. Text evidence
    text, source, chain, text_warnings = _load_text_evidence(article_dir)
    result["text"] = text
    result["text_source"] = source
    result["text_fallback_chain"] = chain
    result["warnings"].extend(text_warnings)

    # 2. Meta evidence
    meta, meta_source, meta_warnings = _load_meta_evidence(article_dir)
    result["meta"] = meta
    result["meta_source"] = meta_source
    result["warnings"].extend(meta_warnings)

    # 3. OCR evidence
    ocr, ocr_source, ocr_warnings = _load_ocr_evidence(article_dir)
    result["ocr"] = ocr
    result["ocr_source"] = ocr_source
    result["warnings"].extend(ocr_warnings)

    return result


def _load_text_evidence(article_dir: Path) -> tuple[str, str, list[str], list[str]]:
    warnings: list[str] = []
    chain: list[str] = []

    for cand in TEXT_CANDIDATES:
        p = article_dir / cand
        if p.exists():
            text = safe_read_text(p, "")
            if text.strip():
                chain.append(cand)
                return text, cand, chain, warnings
            else:
                warnings.append(f"text_candidate_empty:{cand}")
                chain.append(f"{cand}(empty)")

    # Fallback: any .md in dir
    for p in sorted(article_dir.glob("*.md")):
        text = safe_read_text(p, "")
        if text.strip():
            chain.append(p.name)
            return text, p.name, chain, warnings

    warnings.append("no_text_found")
    return "", "", chain, warnings


def _load_meta_evidence(article_dir: Path) -> tuple[dict, str, list[str]]:
    warnings: list[str] = []
    for cand in META_CANDIDATES:
        p = article_dir / cand
        if p.exists():
            meta = safe_read_json(p, {})
            if meta:
                return meta, cand, warnings
            else:
                warnings.append(f"meta_empty:{cand}")
    warnings.append("no_meta_found")
    return {}, "", warnings


def _load_ocr_evidence(article_dir: Path) -> tuple[dict, str, list[str]]:
    warnings: list[str] = []
    for cand in OCR_CANDIDATES:
        p = article_dir / cand
        if p.exists():
            ocr = safe_read_json(p, {})
            if ocr:
                return ocr, cand, warnings
            else:
                warnings.append(f"ocr_empty:{cand}")
    warnings.append("no_ocr_found")
    return {}, "", warnings


def find_article_dirs(input_root: Path, limit: int | None = None) -> list[Path]:
    """Find article directories under input_root.

    Expected structure: input_root / account / article_id /
    """
    dirs: list[Path] = []
    for account_dir in sorted(input_root.iterdir()):
        if not account_dir.is_dir():
            continue
        for article_dir in sorted(account_dir.iterdir()):
            if article_dir.is_dir():
                dirs.append(article_dir)
                if limit and len(dirs) >= limit:
                    return dirs
    return dirs
