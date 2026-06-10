#!/usr/bin/env python3
"""Normalize time candidates from the Atlas DJ repair work-order packet.

This is a report-only adapter for the 2026-05-25 DJ repair queue review packet.
It reads time-normalization work orders and uses recovered article post dates to
create deterministic date candidates without mutating atlas.sqlite, serving
SQLite, Neo4j, Qdrant, or production state.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_atlas_dj_low_cost_repair_sidecar import parse_time_candidate  # noqa: E402
from build_atlas_event_time_normalized_sidecar import (  # noqa: E402
    clamp,
    infer_relative_weekday,
    infer_year,
    now_iso,
    parse_date,
    text,
)


DEFAULT_WORK_ORDER = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_repair_queue_review_packet_activity_current_20260525_1537"
    / "time_normalization_work_order.jsonl"
)
DEFAULT_SOURCE_URL_DB = REPO_ROOT / "reports" / "atlas_source_url_recovery_20260522" / "atlas_source_url_recovery.sqlite"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_time_work_order_sidecar_20260525"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL row: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(payload)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)


def load_post_dates(source_url_db: Path, article_uids: set[str]) -> dict[str, dict[str, str]]:
    if not article_uids:
        return {}
    conn = sqlite3.connect(source_url_db)
    conn.row_factory = sqlite3.Row
    found: dict[str, dict[str, str]] = {}
    try:
        values = sorted(article_uids)
        for offset in range(0, len(values), 900):
            chunk = values[offset : offset + 900]
            placeholders = ",".join("?" for _ in chunk)
            sql = (
                "SELECT article_uid, post_date, post_time, match_basis "
                f"FROM article_source_url WHERE article_uid IN ({placeholders})"
            )
            for row in conn.execute(sql, chunk):
                found[text(row["article_uid"])] = {
                    "post_date": text(row["post_date"]),
                    "post_time": text(row["post_time"]),
                    "match_basis": text(row["match_basis"]),
                }
    finally:
        conn.close()
    return found


def normalize_work_order(row: dict[str, Any], post_dates: dict[str, dict[str, str]]) -> dict[str, Any]:
    article_uid = text(row.get("article_uid"))
    parsed = parse_time_candidate(row.get("time_text"), row.get("title")) or {}
    post_info = post_dates.get(article_uid, {})
    post = parse_date(post_info.get("post_date") or post_info.get("post_time"))
    normalized_date = text(parsed.get("normalized_date"))
    partial = text(parsed.get("partial_date"))
    precision = text(parsed.get("precision"))
    status = text(parsed.get("parse_status")) or "unparsed"
    confidence = float(parsed.get("confidence") or 0.0)
    time_of_day = text(parsed.get("time_of_day"))
    inferred_from = "time_text"
    year_status = ""

    if normalized_date:
        review_tier = "auto_candidate" if confidence >= 0.82 else "review_candidate"
    elif status in {"relative_today", "relative_tomorrow"} and post:
        offset_days = 1 if status == "relative_tomorrow" else 0
        normalized_date = (post + timedelta(days=offset_days)).isoformat()
        precision = "date_inferred_from_article_post_relative_day"
        year_status = f"{status}_from_article_post_date"
        inferred_from = "relative_time_text_plus_article_post_date"
        confidence = clamp(confidence + 0.08)
        review_tier = "auto_candidate" if confidence >= 0.70 else "review_candidate"
    elif status == "relative_weekday" and post:
        inferred = infer_relative_weekday(partial, post)
        if inferred:
            normalized_date = text(inferred["normalized_date"])
            year_status = text(inferred["year_inference_status"])
            confidence = clamp(confidence + float(inferred["confidence_delta"]))
            precision = "date_inferred_from_article_post_weekday"
            inferred_from = "weekday_time_text_plus_article_post_date"
        review_tier = "auto_candidate" if normalized_date and confidence >= 0.70 else "review_candidate"
    elif partial and post:
        inferred = infer_year(partial, post)
        if inferred:
            normalized_date = text(inferred["normalized_date"])
            year_status = text(inferred["year_inference_status"])
            confidence = clamp(confidence + float(inferred["confidence_delta"]))
            precision = "date_inferred_from_post_date"
            status = "partial_date_year_inferred"
            inferred_from = "time_text_partial_plus_article_post_date"
        review_tier = "auto_candidate" if normalized_date and confidence >= 0.74 and "ambiguous" not in year_status else "review_candidate"
    else:
        review_tier = "unresolved"

    if not normalized_date:
        review_tier = "unresolved"

    time_iso_candidate = ""
    if normalized_date:
        time_iso_candidate = f"{normalized_date}T{time_of_day or '00:00:00'}"

    return {
        "schema_version": "atlas_dj_time_work_order_sidecar.row.v1",
        "work_item_id": text(row.get("work_item_id")),
        "article_uid": article_uid,
        "event_id": text(row.get("event_id")),
        "source_account": text(row.get("source_account")),
        "title": text(row.get("title")),
        "event_name": text(row.get("name")),
        "place": text(row.get("place")),
        "time_text": text(row.get("time_text")),
        "normalized_date": normalized_date,
        "time_of_day": time_of_day,
        "time_iso_candidate": time_iso_candidate,
        "partial_date": partial,
        "precision": precision,
        "parse_status": status,
        "year_inference_status": year_status,
        "article_post_date": text(post_info.get("post_date")),
        "source_url_match_basis": text(post_info.get("match_basis")),
        "confidence": confidence,
        "review_tier": review_tier,
        "inferred_from": inferred_from,
        "serving_rebuild_candidate": review_tier == "auto_candidate",
        "serving_rebuild_executed": False,
        "write_status": "report_only",
    }


def build_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Time Work-Order Sidecar",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Source work order: `{summary['source_work_order']}`",
        f"- Input rows: {summary['counts']['input_rows']}",
        f"- Normalized rows: {summary['counts']['normalized_rows']}",
        f"- Auto candidates: {summary['counts']['auto_candidates']}",
        f"- Review candidates: {summary['counts']['review_candidates']}",
        f"- Unresolved rows: {summary['counts']['unresolved_rows']}",
        f"- Decision: {summary['decision']['status']}",
        f"- Reason: {summary['decision']['reason']}",
        "",
        "## Outputs",
    ]
    for name, path in sorted(summary["outputs"].items()):
        lines.append(f"- {name}: `{path}`")
    lines.extend(["", "## Safety"])
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def build_time_work_order_sidecar(work_order_path: Path, source_url_db: Path, out_dir: Path) -> dict[str, Any]:
    rows = read_jsonl(work_order_path)
    article_uids = {text(row.get("article_uid")) for row in rows if text(row.get("article_uid"))}
    post_dates = load_post_dates(source_url_db, article_uids)
    normalized_rows = [normalize_work_order(row, post_dates) for row in rows]

    auto_rows = [row for row in normalized_rows if row["review_tier"] == "auto_candidate"]
    review_rows = [row for row in normalized_rows if row["review_tier"] == "review_candidate"]
    unresolved_rows = [row for row in normalized_rows if row["review_tier"] == "unresolved"]
    tier_counts = Counter(row["review_tier"] for row in normalized_rows)
    status_counts = Counter(row["parse_status"] for row in normalized_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "summary_json": str(out_dir / "summary.json"),
        "summary_md": str(out_dir / "summary.md"),
        "all_candidates_jsonl": str(out_dir / "time_candidates.jsonl"),
        "auto_candidates_jsonl": str(out_dir / "time_auto_candidates.jsonl"),
        "review_candidates_jsonl": str(out_dir / "time_review_candidates.jsonl"),
        "unresolved_jsonl": str(out_dir / "time_unresolved.jsonl"),
    }

    write_jsonl(out_dir / "time_candidates.jsonl", normalized_rows)
    write_jsonl(out_dir / "time_auto_candidates.jsonl", auto_rows)
    write_jsonl(out_dir / "time_review_candidates.jsonl", review_rows)
    write_jsonl(out_dir / "time_unresolved.jsonl", unresolved_rows)

    summary = {
        "schema_version": "atlas_dj_time_work_order_sidecar.summary.v1",
        "generated_at": now_iso(),
        "source_work_order": str(work_order_path),
        "source_url_db": str(source_url_db),
        "out_dir": str(out_dir),
        "counts": {
            "input_rows": len(rows),
            "post_dates_found": len(post_dates),
            "normalized_rows": sum(1 for row in normalized_rows if row["normalized_date"]),
            "auto_candidates": len(auto_rows),
            "review_candidates": len(review_rows),
            "unresolved_rows": len(unresolved_rows),
        },
        "tier_counts": dict(sorted(tier_counts.items())),
        "parse_status_counts": dict(sorted(status_counts.items())),
        "decision": {
            "status": "atlas_dj_time_work_order_sidecar_materialized_report_only",
            "serving_rebuild_triggered": False,
            "reason": "Time candidates were materialized as a report-only sidecar; serving rebuild is deferred until acceptance/rebuild gate.",
        },
        "outputs": outputs,
        "safety": {
            "llm_call_executed": False,
            "network_call_executed": False,
            "neo4j_write_executed": False,
            "paid_api_call_executed": False,
            "production_write_executed": False,
            "qdrant_write_executed": False,
            "report_only": True,
            "serving_sqlite_rebuild_executed": False,
            "source_sqlite_write_executed": False,
        },
    }
    write_json(out_dir / "summary.json", summary)
    (out_dir / "summary.md").write_text(build_summary_md(summary), encoding="utf-8")
    return {"summary": summary, "rows": normalized_rows}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-order", type=Path, default=DEFAULT_WORK_ORDER)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_time_work_order_sidecar(args.work_order, args.source_url_db, args.out_dir)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
