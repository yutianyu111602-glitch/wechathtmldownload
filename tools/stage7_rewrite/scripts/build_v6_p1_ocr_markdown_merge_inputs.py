#!/usr/bin/env python3
"""Materialize V6 P1 OCR-merged Markdown inputs for DeepSeek Flash repair.

Reads the existing OCR locator output and writes new report-local Markdown
inputs that include poster_ocr.json text before LLM reprocessing. It does not
run OCR, call DeepSeek, download images, or write graph/vector stores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("reports/v6_p1_existing_ocr_locator_20260518/v6_p1_existing_ocr_merge_ready.jsonl")
DEFAULT_OUT_DIR = Path("reports/v6_p1_ocr_markdown_merge_inputs_20260518")
SCHEMA_VERSION = "stage7_v6_p1_ocr_markdown_merge_inputs.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


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


def safe_part(value: Any, fallback: str = "unknown") -> str:
    text = re.sub(r"\s+", "_", str(value or "").strip())
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = text.strip("._")
    return text[:80] or fallback


def bucket_for(chars: int, images: int) -> str:
    if chars <= 80:
        size = "tiny"
    elif chars <= 512:
        size = "short"
    elif chars <= 1800:
        size = "medium"
    elif chars <= 5000:
        size = "long"
    else:
        size = "xlong"
    return f"ocr_merged:{size}:{'image' if images else 'text'}"


def ocr_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("plain_text"), str) and payload["plain_text"].strip():
        return payload["plain_text"].strip()
    parts = []
    for block in payload.get("blocks") or []:
        if isinstance(block, dict) and str(block.get("text") or "").strip():
            parts.append(str(block["text"]).strip())
    return "\n".join(parts)


def compact(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def load_meta_title(meta_path: Path, fallback: str) -> str:
    if not meta_path.exists():
        return fallback
    meta = read_json(meta_path)
    for key in ("title", "article_title", "name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return compact(value, 200)
    return fallback


def materialize_row(row: dict[str, Any], out_dir: Path) -> dict[str, Any] | None:
    llm_input = Path(str(row.get("llm_input_path") or ""))
    poster_ocr_path = Path(str(row.get("poster_ocr_path") or ""))
    if not llm_input.exists() or not poster_ocr_path.exists():
        return None

    poster = read_json(poster_ocr_path)
    text = ocr_text(poster)
    if not text.strip():
        return None

    account = safe_part(row.get("source_account"))
    article_id = safe_part(row.get("article_id") or row.get("article_uid") or "article")
    digest = hashlib.sha1(str(row.get("article_uid") or row.get("poster_ocr_path") or "").encode("utf-8")).hexdigest()[:10]
    row_dir = out_dir / "articles" / account / f"{article_id}_{digest}"
    row_dir.mkdir(parents=True, exist_ok=True)

    original = llm_input.read_text(encoding="utf-8", errors="replace")
    merged = (
        original.rstrip()
        + "\n\n## Poster OCR Text (merged before DeepSeek Flash)\n"
        + f"- OCR backend: {poster.get('backend') or ''}\n"
        + f"- OCR source image: {row.get('poster_ocr_image_path') or poster.get('image_path') or ''}\n"
        + f"- OCR block count: {len(poster.get('blocks') or [])}\n\n"
        + "```text\n"
        + text.strip()
        + "\n```\n"
    )
    merged_path = row_dir / "llm_input.ocr_merged.md"
    meta_out = row_dir / "meta.json"
    source_row_out = row_dir / "source_locator_row.json"
    poster_ocr_out = row_dir / "poster_ocr.json"
    merged_path.write_text(merged, encoding="utf-8")
    write_json(source_row_out, row)
    write_json(poster_ocr_out, poster)

    meta_path = Path(str(row.get("article_dir") or "")) / "meta.json"
    title = load_meta_title(meta_path, str(row.get("title") or ""))
    meta_payload = read_json(meta_path) if meta_path.exists() else {}
    meta_payload.setdefault("title", title)
    meta_payload.setdefault("source_account", row.get("source_account"))
    meta_payload.setdefault("article_uid", row.get("article_uid"))
    write_json(meta_out, meta_payload)

    merged_chars = len(merged)
    local_images = int(row.get("manifest_local_image_count") or row.get("image_dir_image_count") or 0)
    return {
        "status": "pending",
        "sample_id": f"v6p1_ocr_{digest}",
        "article_uid": str(row.get("article_uid") or ""),
        "source_account": str(row.get("source_account") or ""),
        "article_id": str(row.get("article_id") or ""),
        "title": title,
        "input_chars": merged_chars,
        "quality_grade": "ocr_merged_p1",
        "local_image_count": local_images,
        "bucket": bucket_for(merged_chars, local_images),
        "llm_input_path": str(merged_path),
        "meta_path": str(meta_out),
        "poster_ocr_path": str(poster_ocr_out),
        "source_llm_input_path": str(llm_input),
        "source_poster_ocr_path": str(poster_ocr_path),
        "poster_ocr_text_chars": len(text),
        "ocr_language_hint": row.get("ocr_language_hint") or "",
        "recommended_ocr_mode": row.get("recommended_ocr_mode") or "mix",
        "has_ocr_before_markdown_contract": True,
        "allow_no_info_after_flash": True,
        "no_info_rule": "allowed_only_after_ocr_markdown_evidence_reaches_llm_input",
        "reprocess_lane": "v6_p1_existing_ocr_markdown_flash",
    }


def load_excluded_article_uids(paths: list[Path]) -> set[str]:
    excluded: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        for row in iter_jsonl(path):
            uid = str(row.get("article_uid") or "").strip()
            if uid:
                excluded.add(uid)
    return excluded


def build(input_path: Path, out_dir: Path, limit: int = 0, excluded_article_uids: set[str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    skipped = Counter()
    excluded = excluded_article_uids or set()
    for index, row in enumerate(iter_jsonl(input_path), start=1):
        if limit and index > limit:
            break
        if str(row.get("article_uid") or "").strip() in excluded:
            skipped["excluded_article_uid"] += 1
            continue
        result = materialize_row(row, out_dir)
        if result is None:
            skipped["not_materialized"] += 1
            continue
        rows.append(result)
    counts = {
        "input_rows_seen": index if "index" in locals() else 0,
        "materialized_rows": len(rows),
        "skipped": dict(sorted(skipped.items())),
        "account_count": len({row.get("source_account") for row in rows}),
        "total_input_chars": sum(int(row.get("input_chars") or 0) for row in rows),
        "total_poster_ocr_text_chars": sum(int(row.get("poster_ocr_text_chars") or 0) for row in rows),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "v6_p1_ocr_markdown_merge_inputs_ready",
        "input_path": str(input_path),
        "out_dir": str(out_dir),
        "limit": limit,
        "excluded_article_uid_count": len(excluded),
        "counts": counts,
        "top_accounts": dict(Counter(str(row.get("source_account") or "") for row in rows).most_common(25)),
        "ocr_language_policy": {
            "zh": "Use the Chinese OCR lane for Chinese-dominant poster text.",
            "en": "Use the English OCR lane for English-only poster text.",
            "mixed": "Use mixed-mode OCR or combine OCR engines; do not collapse mixed flyers to English-only or Chinese-only OCR.",
            "engine_boundary": "Different OCR engines have different strengths; preserve engine/mode metadata on every repaired row.",
        },
        "outputs": {
            "flash_manifest": str(out_dir / "flash_manifest.jsonl"),
            "summary_json": str(out_dir / "merge_summary.json"),
            "summary_md": str(out_dir / "merge_summary.md"),
        },
        "safety": {
            "d_broad_scan_executed": False,
            "bounded_exact_paths_only": True,
            "ocr_execution": False,
            "deepseek_api_used": False,
            "paid_api_used": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "report_only_materialization": True,
        },
    }
    return report, rows


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "# V6 P1 OCR Markdown Merge Inputs",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- excluded_article_uid_count: `{report.get('excluded_article_uid_count')}`",
        f"- materialized_rows: `{counts['materialized_rows']}`",
        f"- account_count: `{counts['account_count']}`",
        f"- total_input_chars: `{counts['total_input_chars']}`",
        f"- total_poster_ocr_text_chars: `{counts['total_poster_ocr_text_chars']}`",
        "",
        "## OCR Language Policy",
        "",
        "- Chinese/mixed poster text uses the Chinese or mixed OCR lane first.",
        "- English-only poster text may use the English OCR lane.",
        "- Mixed Chinese-English flyers keep mixed-mode OCR or combined engine outputs; every row preserves OCR mode metadata.",
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--exclude-manifest-jsonl",
        type=Path,
        action="append",
        default=[],
        help="Skip article_uid values already present in one or more prior Flash manifests.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    excluded = load_excluded_article_uids(args.exclude_manifest_jsonl)
    report, rows = build(args.input, args.out_dir, args.limit, excluded_article_uids=excluded)
    write_json(args.out_dir / "merge_summary.json", report)
    write_jsonl(args.out_dir / "flash_manifest.jsonl", rows)
    write_markdown(args.out_dir / "merge_summary.md", report)
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "counts": report["counts"], "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
