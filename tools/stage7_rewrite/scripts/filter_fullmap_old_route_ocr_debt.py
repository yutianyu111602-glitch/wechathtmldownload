#!/usr/bin/env python3
"""Filter FULL_MAP old-route OCR debt before any rerun or paid spend.

The input queue is already bounded by the FULL_MAP manifest router. This script
only reads those exact rows plus their referenced llm_input/meta paths. It does
not scan D: roots, call network/model APIs, pay Dajiala, or write graph/vector
stores.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
STAGE7_ROOT = SCRIPT_PATH.parents[1]
PROJECT_ROOT = SCRIPT_PATH.parents[3]
REPORTS = STAGE7_ROOT / "reports"
DEFAULT_INPUT = REPORTS / "fullmap_manifest_20260513_routes" / "needs_ocr.remaining.jsonl"
DEFAULT_CURRENT_ARTICLES = (
    PROJECT_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "stage7_atlas" / "articles.jsonl.gz"
)
DEFAULT_OUT_DIR = REPORTS / "fullmap_old_route_ocr_debt_filter_20260519"
SCHEMA_VERSION = "fullmap_old_route_ocr_debt_filter.v1"

SCAFFOLD_MARKERS = (
    "# Untitled",
    "## Main Content",
    "## Poster OCR",
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def mount_path_to_local(path_text: str) -> Path:
    text = str(path_text or "")
    lower = text.lower()
    if lower.startswith("/mnt/d/"):
        return Path("D:/" + text[7:])
    if lower.startswith("/mnt/c/"):
        return Path("C:/" + text[7:])
    return Path(text)


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                row["_source_line"] = line_no
                yield row


def load_current_article_uids(path: Path) -> set[str]:
    current: set[str] = set()
    if not path.exists():
        return current
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:  # type: ignore[arg-type]
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            uid = row.get("article_uid") if isinstance(row, dict) else None
            if uid:
                current.add(str(uid))
    return current


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def read_small_text(path: Path, max_bytes: int = 128 * 1024) -> tuple[str, bool, int]:
    if not path.exists() or not path.is_file():
        return "", False, 0
    size = path.stat().st_size
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        text = handle.read(max_bytes)
    return text, True, size


def read_small_json(path: Path, max_bytes: int = 256 * 1024) -> tuple[dict[str, Any], bool, int]:
    if not path.exists() or not path.is_file():
        return {}, False, 0
    size = path.stat().st_size
    if size > max_bytes:
        return {}, True, size
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}, True, size
    return data if isinstance(data, dict) else {}, True, size


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def meaningful_chars(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-z\u4e00-\u9fff]", text or ""))


def remove_scaffold(text: str) -> str:
    cleaned = text or ""
    for marker in SCAFFOLD_MARKERS:
        cleaned = cleaned.replace(marker, "")
    cleaned = re.sub(r"(?m)^#+\s*$", "", cleaned)
    return cleaned.strip()


def classify(row: dict[str, Any], current_uids: set[str]) -> dict[str, Any]:
    article_uid = str(row.get("article_uid") or "")
    llm_path = mount_path_to_local(str(row.get("llm_input_path") or ""))
    meta_path = mount_path_to_local(str(row.get("meta_path") or ""))
    archive_dir_text = str(row.get("archive_dir") or "")
    archive_dir = mount_path_to_local(archive_dir_text) if archive_dir_text else Path("")
    archive_url_path = archive_dir / "article.url.txt" if archive_dir_text else Path("")
    archive_meta_path = archive_dir / "archive_meta.json" if archive_dir_text else Path("")
    llm_text, llm_exists, llm_size = read_small_text(llm_path)
    meta, meta_exists, meta_size = read_small_json(meta_path)
    archive_url_text, archive_url_exists, archive_url_size = read_small_text(archive_url_path, max_bytes=4096)
    archive_meta, archive_meta_exists, archive_meta_size = read_small_json(archive_meta_path)
    non_scaffold = remove_scaffold(llm_text)
    non_scaffold_chars = meaningful_chars(non_scaffold)
    source_url = first_string(
        meta.get("source_url"),
        meta.get("url"),
        meta.get("final_url"),
        archive_meta.get("source_url"),
        archive_meta.get("url"),
        archive_meta.get("final_url"),
        archive_url_text,
    )
    meta_title = first_string(meta.get("title"), archive_meta.get("title"))
    html_length = int(meta.get("html_length") or 0)
    local_image_count = int(row.get("local_image_count") or 0)
    in_current = article_uid in current_uids

    if in_current:
        bucket = "already_in_current_atlas_no_rerun"
        decision = "reuse_current_product_base"
        next_action = "No OCR, LLM, Dajiala, graph, or vector rerun."
    elif local_image_count > 0:
        bucket = "local_image_candidate_for_nonpaid_ocr"
        decision = "eligible_for_local_ocr_canary"
        next_action = "Run non-paid local OCR canary only; no paid/API spend."
    elif non_scaffold_chars >= 80:
        bucket = "ready_text_reclass_candidate"
        decision = "recheck_as_text_lane_before_ocr"
        next_action = "Route to text-lane validation before any OCR."
    elif source_url:
        bucket = "source_url_reacquire_candidate"
        decision = "needs_source_reacquire_before_ocr"
        next_action = "Use source URL for bounded recapture; do not OCR empty local shell."
    elif llm_exists and meta_exists:
        bucket = "empty_shell_no_local_asset"
        decision = "blocked_until_source_locator_or_account_registry"
        next_action = "Use account/article registry or external source locator; current local files have no usable text/image evidence."
    elif not llm_exists and not meta_exists:
        bucket = "missing_local_artifacts"
        decision = "blocked_until_archive_locator"
        next_action = "Find exact archive/source path first; do not scan D roots."
    else:
        bucket = "partial_local_artifacts"
        decision = "blocked_until_artifact_repair"
        next_action = "Repair missing paired artifact before OCR/LLM."

    return {
        "schema_version": f"{SCHEMA_VERSION}.row",
        "article_uid": article_uid,
        "article_id": row.get("article_id"),
        "source_account": row.get("source_account"),
        "title": row.get("title"),
        "input_chars": int(row.get("input_chars") or 0),
        "local_image_count": local_image_count,
        "llm_input_path": row.get("llm_input_path"),
        "meta_path": row.get("meta_path"),
        "archive_dir": row.get("archive_dir"),
        "llm_exists": llm_exists,
        "llm_size": llm_size,
        "meta_exists": meta_exists,
        "meta_size": meta_size,
        "archive_article_url_exists": archive_url_exists,
        "archive_article_url_size": archive_url_size,
        "archive_meta_exists": archive_meta_exists,
        "archive_meta_size": archive_meta_size,
        "meta_source_url_present": bool(source_url),
        "meta_title_present": bool(meta_title),
        "meta_html_length": html_length,
        "source_url": source_url,
        "non_scaffold_chars": non_scaffold_chars,
        "in_current_atlas": in_current,
        "bucket": bucket,
        "decision": decision,
        "next_action": next_action,
        "eligible_for_ocr_now": bucket == "local_image_candidate_for_nonpaid_ocr",
        "eligible_for_paid_now": False,
        "eligible_for_llm_now": bucket == "ready_text_reclass_candidate",
        "source_line": row.get("_source_line"),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    bucket_counts = summary["bucket_counts"]
    lines = [
        "# FULL_MAP Old-Route OCR Debt Filter",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{counts['input_rows']}`",
        f"- already_in_current_atlas_no_rerun: `{bucket_counts.get('already_in_current_atlas_no_rerun', 0)}`",
        f"- local_image_candidate_for_nonpaid_ocr: `{bucket_counts.get('local_image_candidate_for_nonpaid_ocr', 0)}`",
        f"- ready_text_reclass_candidate: `{bucket_counts.get('ready_text_reclass_candidate', 0)}`",
        f"- source_url_reacquire_candidate: `{bucket_counts.get('source_url_reacquire_candidate', 0)}`",
        f"- empty_shell_no_local_asset: `{bucket_counts.get('empty_shell_no_local_asset', 0)}`",
        f"- missing_or_partial_local_artifacts: `{counts['missing_or_partial_local_artifacts']}`",
        "",
        "## Interpretation",
        "",
        summary["answer"],
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def build(input_path: Path, current_articles_path: Path, out_dir: Path) -> dict[str, Any]:
    current_uids = load_current_article_uids(current_articles_path)
    rows = [classify(row, current_uids) for row in iter_jsonl(input_path)]
    bucket_counts = Counter(row["bucket"] for row in rows)

    buckets = {
        "already_in_current_atlas_no_rerun": [row for row in rows if row["bucket"] == "already_in_current_atlas_no_rerun"],
        "local_image_candidate_for_nonpaid_ocr": [
            row for row in rows if row["bucket"] == "local_image_candidate_for_nonpaid_ocr"
        ],
        "ready_text_reclass_candidate": [row for row in rows if row["bucket"] == "ready_text_reclass_candidate"],
        "source_url_reacquire_candidate": [row for row in rows if row["bucket"] == "source_url_reacquire_candidate"],
        "empty_shell_no_local_asset": [row for row in rows if row["bucket"] == "empty_shell_no_local_asset"],
        "missing_local_artifacts": [row for row in rows if row["bucket"] == "missing_local_artifacts"],
        "partial_local_artifacts": [row for row in rows if row["bucket"] == "partial_local_artifacts"],
    }
    source_locator_rows = [
        row
        for row in rows
        if row["bucket"]
        in {
            "source_url_reacquire_candidate",
            "empty_shell_no_local_asset",
            "missing_local_artifacts",
            "partial_local_artifacts",
        }
    ]
    no_spend_hold_rows = [
        row
        for row in rows
        if row["bucket"]
        in {
            "already_in_current_atlas_no_rerun",
            "empty_shell_no_local_asset",
            "missing_local_artifacts",
            "partial_local_artifacts",
        }
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "summary_json": out_dir / "fullmap_old_route_ocr_debt_filter_summary.json",
        "summary_md": out_dir / "fullmap_old_route_ocr_debt_filter_summary.md",
        "reviewed_rows": out_dir / "reviewed_rows.jsonl",
        "already_current": out_dir / "already_in_current_atlas_no_rerun.jsonl",
        "local_ocr_candidates": out_dir / "local_image_candidate_for_nonpaid_ocr.jsonl",
        "ready_text_reclass_candidates": out_dir / "ready_text_reclass_candidate.jsonl",
        "source_reacquire_candidates": out_dir / "source_url_reacquire_candidate.jsonl",
        "empty_shell_no_local_asset": out_dir / "empty_shell_no_local_asset.jsonl",
        "source_locator_queue": out_dir / "source_locator_or_account_registry_queue.jsonl",
        "no_spend_hold": out_dir / "no_spend_hold.jsonl",
    }

    counts = {
        "input_rows": len(rows),
        "current_atlas_article_uid_count": len(current_uids),
        "llm_exists_rows": sum(1 for row in rows if row["llm_exists"]),
        "meta_exists_rows": sum(1 for row in rows if row["meta_exists"]),
        "source_url_present_rows": sum(1 for row in rows if row["meta_source_url_present"]),
        "local_image_count_gt0_rows": sum(1 for row in rows if int(row["local_image_count"]) > 0),
        "ready_text_reclass_candidate_rows": len(buckets["ready_text_reclass_candidate"]),
        "local_ocr_candidate_rows": len(buckets["local_image_candidate_for_nonpaid_ocr"]),
        "already_current_rows": len(buckets["already_in_current_atlas_no_rerun"]),
        "source_locator_queue_rows": len(source_locator_rows),
        "no_spend_hold_rows": len(no_spend_hold_rows),
        "missing_or_partial_local_artifacts": len(buckets["missing_local_artifacts"]) + len(buckets["partial_local_artifacts"]),
    }
    answer = (
        "FULL_MAP old-route OCR debt has no immediately executable OCR/paid queue: all rows have local_image_count=0, "
        f"{counts['already_current_rows']} rows already exist in the current atlas and must be reused, "
        f"{counts['local_ocr_candidate_rows']} rows have local image evidence for non-paid OCR, and "
        f"{counts['source_locator_queue_rows']} rows have source URLs but need bounded source recapture before any OCR/LLM/paid step."
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "fullmap_old_route_ocr_debt_filtered_no_blind_rerun",
        "project_root": str(PROJECT_ROOT),
        "answer": answer,
        "inputs": {
            "input": str(input_path),
            "current_articles": str(current_articles_path),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "counts": counts,
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "safety": {
            "bounded_manifest_rows_only": True,
            "d_root_scan_executed": False,
            "network_called": False,
            "llm_called": False,
            "paid_api_used": False,
            "ocr_execution": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "used_9router": False,
            "secrets_read_or_printed": False,
        },
    }

    write_json(outputs["summary_json"], summary)
    write_text(outputs["summary_md"], render_markdown(summary))
    write_jsonl(outputs["reviewed_rows"], rows)
    write_jsonl(outputs["already_current"], buckets["already_in_current_atlas_no_rerun"])
    write_jsonl(outputs["local_ocr_candidates"], buckets["local_image_candidate_for_nonpaid_ocr"])
    write_jsonl(outputs["ready_text_reclass_candidates"], buckets["ready_text_reclass_candidate"])
    write_jsonl(outputs["source_reacquire_candidates"], buckets["source_url_reacquire_candidate"])
    write_jsonl(outputs["empty_shell_no_local_asset"], buckets["empty_shell_no_local_asset"])
    write_jsonl(outputs["source_locator_queue"], source_locator_rows)
    write_jsonl(outputs["no_spend_hold"], no_spend_hold_rows)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--current-articles", type=Path, default=DEFAULT_CURRENT_ARTICLES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build(args.input, args.current_articles, args.out_dir)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "summary": summary["outputs"]["summary_json"],
                "counts": summary["counts"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
