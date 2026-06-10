#!/usr/bin/env python3
"""Locate existing OCR evidence for V6 P1 visual-loss rows.

The P1 manifest points at exact article directories. This script checks only
those bounded directories for already-created poster_ocr.json and local image
evidence. It does not run OCR, download images, call paid APIs, or scan broad
D: roots.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("reports/v6_image_bucket_loss_audit_20260518/v6_image_bucket_p1_likely_visual_missing.jsonl")
DEFAULT_OUT_DIR = Path("reports/v6_p1_existing_ocr_locator_20260518")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
SCHEMA_VERSION = "stage7_v6_p1_existing_ocr_locator.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                row["_source_line"] = line_no
                yield row


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(path)


def path_from_manifest(value: str) -> Path:
    text = str(value or "").strip()
    if text.startswith("/mnt/") and len(text) > 6 and text[6] == "/":
        drive = text[5].upper()
        rest = text[7:].replace("/", "\\")
        return Path(f"{drive}:\\{rest}")
    return Path(text)


def image_files_in_dir(path: Path | None) -> list[Path]:
    if not path or not path.exists() or not path.is_dir():
        return []
    return [item for item in path.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES]


def text_from_ocr(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("plain_text"), str):
        return payload["plain_text"]
    parts = []
    for block in payload.get("blocks") or []:
        if isinstance(block, dict) and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts)


def ocr_quality_accepted(payload: dict[str, Any], has_text: bool) -> bool:
    quality = payload.get("quality") if isinstance(payload, dict) else None
    if isinstance(quality, dict) and isinstance(quality.get("accepted"), bool):
        return bool(quality["accepted"])
    return has_text


def classify_ocr_language_hint(*values: Any) -> str:
    text = " ".join(str(value or "") for value in values)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk and latin:
        return "mixed"
    if cjk:
        return "zh"
    if latin:
        return "en"
    return "unknown"


def recommended_ocr_mode(language_hint: str) -> str:
    if language_hint == "en":
        return "en"
    if language_hint == "zh":
        return "cn"
    return "mix"


def inspect_row(row: dict[str, Any]) -> dict[str, Any]:
    llm_input = path_from_manifest(str(row.get("llm_input_path") or ""))
    article_dir = llm_input.parent
    poster_ocr_path = article_dir / "poster_ocr.json"
    assets_path = article_dir / "assets.json"
    meta_path = article_dir / "meta.json"
    sidecar_path = article_dir / "sidecar.json"

    poster_ocr: dict[str, Any] = {}
    ocr_error = ""
    if poster_ocr_path.exists():
        try:
            value = read_json(poster_ocr_path)
            poster_ocr = value if isinstance(value, dict) else {}
        except Exception as exc:
            ocr_error = f"{type(exc).__name__}: {str(exc)[:200]}"

    ocr_text = text_from_ocr(poster_ocr) if poster_ocr else ""
    language_hint = classify_ocr_language_hint(row.get("title"), row.get("source_account"), ocr_text)
    ocr_image_raw = str(poster_ocr.get("image_path") or "") if poster_ocr else ""
    ocr_image_path = path_from_manifest(ocr_image_raw) if ocr_image_raw else None
    ocr_image_dir = ocr_image_path.parent if ocr_image_path else None
    sibling_images = image_files_in_dir(ocr_image_dir)
    suffix_counts = Counter(path.suffix.lower() for path in sibling_images)
    gif_or_webp_count = suffix_counts.get(".gif", 0) + suffix_counts.get(".webp", 0)

    assets_image_count = 0
    if assets_path.exists():
        try:
            assets = read_json(assets_path)
            if isinstance(assets, dict):
                assets_image_count = len(assets.get("images") or [])
        except Exception:
            assets_image_count = 0

    has_existing_ocr = bool(poster_ocr)
    has_ocr_text = len(ocr_text.strip()) > 0
    quality_accepted = ocr_quality_accepted(poster_ocr, has_ocr_text) if poster_ocr else False
    low_quality_text = bool(has_ocr_text and not quality_accepted)
    has_local_image = bool(ocr_image_path and ocr_image_path.exists()) or bool(sibling_images)
    return {
        "schema_version": f"{SCHEMA_VERSION}.row",
        "article_uid": row.get("article_uid"),
        "article_id": row.get("article_id"),
        "source_account": row.get("source_account"),
        "title": row.get("title"),
        "priority": row.get("priority"),
        "input_chars": row.get("input_chars"),
        "flash_entities": row.get("entities"),
        "flash_events": row.get("events"),
        "flash_output_count": row.get("output_count"),
        "manifest_local_image_count": row.get("local_image_count"),
        "llm_input_path": str(llm_input),
        "article_dir": str(article_dir),
        "article_dir_exists": article_dir.exists(),
        "assets_path": str(assets_path),
        "assets_json_exists": assets_path.exists(),
        "assets_image_count": assets_image_count,
        "meta_exists": meta_path.exists(),
        "sidecar_exists": sidecar_path.exists(),
        "poster_ocr_path": str(poster_ocr_path),
        "poster_ocr_exists": poster_ocr_path.exists(),
        "poster_ocr_error": ocr_error,
        "poster_ocr_backend": poster_ocr.get("backend"),
        "poster_ocr_block_count": len(poster_ocr.get("blocks") or []) if poster_ocr else 0,
        "poster_ocr_text_chars": len(ocr_text.strip()),
        "poster_ocr_quality_accepted": quality_accepted,
        "poster_ocr_low_quality_text": low_quality_text,
        "ocr_language_hint": language_hint,
        "recommended_ocr_mode": recommended_ocr_mode(language_hint),
        "poster_ocr_image_path": str(ocr_image_path) if ocr_image_path else "",
        "poster_ocr_image_exists": bool(ocr_image_path and ocr_image_path.exists()),
        "poster_ocr_image_dir": str(ocr_image_dir) if ocr_image_dir else "",
        "image_dir_image_count": len(sibling_images),
        "image_dir_gif_or_webp_count": gif_or_webp_count,
        "has_existing_ocr": has_existing_ocr,
        "has_ocr_text": has_ocr_text,
        "has_local_image_evidence": has_local_image,
        "static_frame_required": bool(gif_or_webp_count and not has_ocr_text),
        "merge_ocr_markdown_flash_ready": bool(article_dir.exists() and llm_input.exists() and has_existing_ocr and has_ocr_text and quality_accepted),
        "ocr_rerun_needed": bool(article_dir.exists() and has_local_image and (not has_existing_ocr or not has_ocr_text)),
        "ocr_low_quality_text_review_needed": low_quality_text,
        "recapture_or_external_locator_needed": bool(not has_local_image),
        "source_line": row.get("_source_line"),
    }


def build_report(input_path: Path, limit: int = 0) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    rows = []
    for index, row in enumerate(iter_jsonl(input_path), start=1):
        if limit and index > limit:
            break
        rows.append(inspect_row(row))

    buckets = {
        "merge_ready": [row for row in rows if row["merge_ocr_markdown_flash_ready"]],
        "ocr_rerun_needed": [row for row in rows if row["ocr_rerun_needed"]],
        "low_quality_text_review_needed": [row for row in rows if row["ocr_low_quality_text_review_needed"]],
        "recapture_needed": [row for row in rows if row["recapture_or_external_locator_needed"]],
        "static_frame_needed": [row for row in rows if row["static_frame_required"]],
        "all": rows,
    }
    counts = {
        "input_rows": len(rows),
        "article_dir_exists": sum(1 for row in rows if row["article_dir_exists"]),
        "poster_ocr_exists": sum(1 for row in rows if row["poster_ocr_exists"]),
        "poster_ocr_text_gt0": sum(1 for row in rows if row["has_ocr_text"]),
        "poster_ocr_quality_accepted": sum(1 for row in rows if row["poster_ocr_quality_accepted"]),
        "ocr_low_quality_text_review_needed": sum(1 for row in rows if row["ocr_low_quality_text_review_needed"]),
        "poster_ocr_image_exists": sum(1 for row in rows if row["poster_ocr_image_exists"]),
        "has_local_image_evidence": sum(1 for row in rows if row["has_local_image_evidence"]),
        "merge_ocr_markdown_flash_ready": len(buckets["merge_ready"]),
        "ocr_rerun_needed": len(buckets["ocr_rerun_needed"]),
        "recapture_or_external_locator_needed": len(buckets["recapture_needed"]),
        "static_frame_required": len(buckets["static_frame_needed"]),
    }
    language_counts = Counter(str(row.get("ocr_language_hint") or "unknown") for row in rows)
    ocr_mode_counts = Counter(str(row.get("recommended_ocr_mode") or "mix") for row in rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "v6_p1_existing_ocr_locator_ready",
        "input_path": str(input_path),
        "limit": limit,
        "counts": counts,
        "ocr_language_counts": dict(sorted(language_counts.items())),
        "recommended_ocr_mode_counts": dict(sorted(ocr_mode_counts.items())),
        "top_accounts_merge_ready": dict(Counter(str(row.get("source_account") or "") for row in buckets["merge_ready"]).most_common(20)),
        "interpretation": {
            "merge_ready": "Existing poster_ocr.json has text and can be merged into Markdown before DeepSeek Flash; no paid recapture needed first.",
            "ocr_rerun_needed": "Local image evidence exists but OCR is missing/empty; run local OCR before Flash.",
            "ocr_low_quality_text_review_needed": "OCR produced non-empty but low-quality text; do not send to Flash automatically.",
            "recapture_needed": "No local image evidence found from bounded exact paths; only these rows need external locator/recapture.",
            "static_frame_needed": "GIF/WebP image evidence exists without OCR text; extract static frames before OCR.",
            "ocr_language_policy": "Use cn for Chinese-dominant rows, en for English-only rows, and mix for mixed/unknown rows; preserve OCR mode metadata.",
        },
        "safety": {
            "d_broad_scan_executed": False,
            "bounded_exact_article_dirs_only": True,
            "ocr_execution": False,
            "deepseek_api_used": False,
            "paid_api_used": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "text_copied": False,
        },
    }
    return report, buckets


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "# V6 P1 Existing OCR Locator",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- input_rows: `{counts['input_rows']}`",
        f"- article_dir_exists: `{counts['article_dir_exists']}`",
        f"- poster_ocr_exists: `{counts['poster_ocr_exists']}`",
        f"- poster_ocr_text_gt0: `{counts['poster_ocr_text_gt0']}`",
        f"- poster_ocr_quality_accepted: `{counts['poster_ocr_quality_accepted']}`",
        f"- ocr_low_quality_text_review_needed: `{counts['ocr_low_quality_text_review_needed']}`",
        f"- has_local_image_evidence: `{counts['has_local_image_evidence']}`",
        f"- merge_ocr_markdown_flash_ready: `{counts['merge_ocr_markdown_flash_ready']}`",
        f"- ocr_rerun_needed: `{counts['ocr_rerun_needed']}`",
        f"- recapture_or_external_locator_needed: `{counts['recapture_or_external_locator_needed']}`",
        f"- static_frame_required: `{counts['static_frame_required']}`",
        "",
        "## OCR Language Routing",
        "",
    ]
    for key, value in sorted(report["ocr_language_counts"].items()):
        lines.append(f"- language `{key}`: `{value}`")
    for key, value in sorted(report["recommended_ocr_mode_counts"].items()):
        lines.append(f"- recommended mode `{key}`: `{value}`")
    lines.extend([
        "",
        "- Chinese-dominant poster text uses the Chinese OCR lane.",
        "- English-only poster text may use the English OCR lane.",
        "- Mixed or unknown flyer text uses mixed-mode OCR or combined engine outputs; do not collapse to one universal engine.",
        "",
        "## Safety",
        "",
    ])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report, buckets = build_report(args.input, args.limit)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "v6_p1_existing_ocr_locator_summary.json", report)
    write_jsonl(args.out_dir / "v6_p1_existing_ocr_all.jsonl", buckets["all"])
    write_jsonl(args.out_dir / "v6_p1_existing_ocr_merge_ready.jsonl", buckets["merge_ready"])
    write_jsonl(args.out_dir / "v6_p1_existing_ocr_rerun_needed.jsonl", buckets["ocr_rerun_needed"])
    write_jsonl(args.out_dir / "v6_p1_existing_ocr_low_quality_text_review_needed.jsonl", buckets["low_quality_text_review_needed"])
    write_jsonl(args.out_dir / "v6_p1_existing_ocr_recapture_needed.jsonl", buckets["recapture_needed"])
    write_jsonl(args.out_dir / "v6_p1_existing_ocr_static_frame_needed.jsonl", buckets["static_frame_needed"])
    write_markdown(args.out_dir / "v6_p1_existing_ocr_locator_summary.md", report)
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "counts": report["counts"], "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
