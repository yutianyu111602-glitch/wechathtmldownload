#!/usr/bin/env python3
"""Build a report-only OCR staging manifest from PRD-05a localized images.

The output adapts source-backed localized image candidates to the existing
`run_ocr_direct.py --manifest` contract without mutating the official OCR index
or source archives.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_LOCALIZATION = Path("reports/prd05a_image_candidate_localization_20260516_100/image_candidate_localization.jsonl")
DEFAULT_OUT_DIR = Path("reports/prd05a_ocr_staging_manifest_20260516")
ALLOWED_IMAGE_DOMAINS = {"mmbiz.qpic.cn"}
ALLOWED_SOURCE_FIELDS = {"og:image", "twitter:image", "src", "data-src", "data-original", "data-lazy-src"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def safe_part(value: str, fallback: str = "unknown") -> str:
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    text = text.strip("._-")
    return text[:120] or fallback


def resolve_local_path(value: str, root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def review_candidate(row: dict[str, Any], root: Path, min_dimension: int) -> tuple[bool, list[str], Path]:
    reasons: list[str] = []
    image_path = resolve_local_path(str(row.get("local_path") or ""), root)

    if not bool(row.get("ocr_ready_candidate")):
        reasons.append("not_ocr_ready_candidate")
    if str(row.get("download_status") or "") != "downloaded_image":
        reasons.append("not_downloaded_image")
    if bool(row.get("unsafe_action")):
        reasons.append("unsafe_action")
    if bool(row.get("official_ocr_index_updated")):
        reasons.append("official_ocr_index_already_updated")
    if str(row.get("write_scope") or "") != "reports_only":
        reasons.append("write_scope_not_reports_only")
    if str(row.get("image_domain") or "") not in ALLOWED_IMAGE_DOMAINS:
        reasons.append("image_domain_not_allowed")
    if str(row.get("source_field") or "") not in ALLOWED_SOURCE_FIELDS:
        reasons.append("source_field_not_allowed")
    if not str(row.get("content_type") or "").lower().startswith("image/"):
        reasons.append("content_type_not_image")
    if int(row.get("width") or 0) < min_dimension or int(row.get("height") or 0) < min_dimension:
        reasons.append("below_min_dimension")
    if not str(row.get("sha256") or ""):
        reasons.append("missing_sha256")
    if not image_path.exists():
        reasons.append("local_image_missing")

    return not reasons, reasons, image_path


def build_manifest(localization_path: Path, out_dir: Path, limit: int, min_dimension: int, root: Path) -> dict[str, Any]:
    rows = read_jsonl(localization_path)
    manifest_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    selected = 0

    processed_root = out_dir / "processed"
    archive_root = out_dir / "archive"

    for idx, row in enumerate(rows):
        accepted, reasons, image_path = review_candidate(row, root=root, min_dimension=min_dimension)
        source_article_id = str(row.get("source_article_id") or f"candidate-{idx}")
        account = safe_part(str(row.get("source_account") or source_article_id.split("/", 1)[0]), "account")
        article_slug = safe_part(source_article_id.split("/", 1)[-1], f"article_{idx}")
        review = {
            "schema_version": "stage7_prd05a_ocr_staging_contract_review.v1.row",
            "source_prd": "PRD-05a",
            "source_article_id": source_article_id,
            "source_account": row.get("source_account", ""),
            "source_field": row.get("source_field", ""),
            "image_domain": row.get("image_domain", ""),
            "local_path": str(image_path),
            "sha256": row.get("sha256", ""),
            "width": row.get("width", 0),
            "height": row.get("height", 0),
            "accepted_for_staging_ocr": accepted,
            "rejection_reasons": reasons,
            "official_ocr_index_updated": False,
            "write_scope": "reports_only",
        }
        review_rows.append(review)
        if not accepted:
            continue
        if limit and selected >= limit:
            review["accepted_for_staging_ocr"] = False
            review["rejection_reasons"] = ["over_limit"]
            continue

        raw_dir = processed_root / account / article_slug / "raw"
        archive_dir = archive_root / account / article_slug
        raw_dir.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)

        suffix = image_path.suffix.lower() or f".{row.get('image_format') or 'img'}"
        asset_name = f"poster_{selected + 1}{suffix}"
        copied = archive_dir / asset_name
        shutil.copyfile(image_path, copied)
        assets = [
            {
                "asset_id": f"prd05a:{source_article_id}:{selected + 1}",
                "local_path": asset_name,
                "source_url": row.get("image_url", ""),
                "source_field": row.get("source_field", ""),
                "source_article_id": source_article_id,
                "sha256": row.get("sha256", ""),
                "width": row.get("width", 0),
                "height": row.get("height", 0),
                "content_type": row.get("content_type", ""),
                "contract": "prd05a_source_backed_staging_ocr_only",
            }
        ]
        write_json(archive_dir / "assets_local.json", assets)

        manifest_rows.append(
            {
                "schema_version": "stage7_prd05a_ocr_staging_manifest.v1.row",
                "raw_dir": str(raw_dir),
                "archive_dir": str(archive_dir),
                "source_prd": "PRD-05a",
                "source_article_id": source_article_id,
                "source_account": row.get("source_account", ""),
                "article_uid": article_slug,
                "article_id": source_article_id,
                "poster_ocr_path": str(raw_dir / "poster_ocr.json"),
                "assets_local_path": str(archive_dir / "assets_local.json"),
                "existing_local_image_count": 1,
                "local_image_count": 1,
                "ocr_status": "no_text",
                "official_ocr_index_updated": False,
                "write_scope": "reports_only",
            }
        )
        selected += 1

    write_jsonl(out_dir / "source_image_contract_review.jsonl", review_rows)
    write_jsonl(out_dir / "staging_manifest.jsonl", manifest_rows)

    reason_counts = Counter(reason for row in review_rows for reason in row["rejection_reasons"])
    summary = {
        "schema_version": "stage7_prd05a_ocr_staging_manifest.summary.v1",
        "generated_at": now_iso(),
        "source_prd": "PRD-05a",
        "localization_path": str(localization_path),
        "out_dir": str(out_dir),
        "input_rows": len(rows),
        "review_rows": len(review_rows),
        "accepted_staging_rows": len(manifest_rows),
        "decision": "staging_ocr_manifest_ready" if manifest_rows else "no_contract_accepted_candidates",
        "min_dimension": min_dimension,
        "rejection_reason_counts": dict(reason_counts),
        "outputs": {
            "manifest": str(out_dir / "staging_manifest.jsonl"),
            "contract_review": str(out_dir / "source_image_contract_review.jsonl"),
            "summary_json": str(out_dir / "staging_manifest_summary.json"),
            "summary_md": str(out_dir / "staging_manifest_summary.md"),
        },
        "safety": [
            "reports_only",
            "staging_manifest_only",
            "no_official_ocr_index_update",
            "no_source_archive_mutation",
            "no_d_scan",
            "no_paid_api",
            "no_publish",
        ],
    }
    write_json(out_dir / "staging_manifest_summary.json", summary)
    write_markdown(out_dir / "staging_manifest_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-05a OCR Staging Manifest",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- accepted_staging_rows: `{summary['accepted_staging_rows']}`",
        f"- manifest: `{summary['outputs']['manifest']}`",
        "",
        "## Safety",
        "",
    ]
    for item in summary["safety"]:
        lines.append(f"- `{item}`")
    if summary["rejection_reason_counts"]:
        lines.extend(["", "## Rejections", ""])
        for reason, count in sorted(summary["rejection_reason_counts"].items()):
            lines.append(f"- `{reason}`: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--localization", type=Path, default=DEFAULT_LOCALIZATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-dimension", type=int, default=480)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_manifest(
        localization_path=args.localization,
        out_dir=args.out_dir,
        limit=args.limit,
        min_dimension=args.min_dimension,
        root=Path.cwd(),
    )
    print(json.dumps({"decision": summary["decision"], "accepted_staging_rows": summary["accepted_staging_rows"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
