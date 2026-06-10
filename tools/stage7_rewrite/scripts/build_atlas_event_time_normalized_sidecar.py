#!/usr/bin/env python3
"""Normalize Atlas event time candidates using recovered article publish dates.

This is a private/report-only overlay. It joins:

* ``event_time_candidates`` from ``build_atlas_dj_low_cost_repair_sidecar.py``
* ``article_source_url`` from ``build_atlas_source_url_recovery_sidecar.py``

The goal is to convert month-day-only event dates into sortable date candidates
without rerunning a paid LLM job. It keeps confidence/status fields so public
serving can decide what is auto-accepted and what stays in review.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPAIR = REPO_ROOT / "reports" / "atlas_dj_low_cost_repair_sidecar_20260522" / "atlas_dj_low_cost_repair_sidecar.sqlite"
DEFAULT_SOURCE_URLS = REPO_ROOT / "reports" / "atlas_source_url_recovery_20260522" / "atlas_source_url_recovery.sqlite"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_event_time_normalized_sidecar_20260522"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def parse_date(value: Any) -> date | None:
    raw = text(value)
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_partial(value: Any) -> tuple[int, int] | None:
    raw = text(value)
    if not raw or "-" not in raw:
        return None
    left, right = raw.split("-", 1)
    try:
        month = int(left)
        day = int(right)
    except ValueError:
        return None
    if 1 <= month <= 12 and 1 <= day <= 31:
        return month, day
    return None


def infer_year(partial_date: str, post_date: date) -> dict[str, Any] | None:
    parsed = parse_partial(partial_date)
    if not parsed:
        return None
    month, day = parsed
    try:
        same_year = date(post_date.year, month, day)
    except ValueError:
        return None
    if same_year >= post_date - timedelta(days=14):
        return {
            "normalized_date": same_year.isoformat(),
            "year_inference_status": "same_year_after_or_near_publish",
            "confidence_delta": 0.18,
        }
    if post_date.month >= 11 and month <= 2:
        try:
            next_year = date(post_date.year + 1, month, day)
        except ValueError:
            return None
        return {
            "normalized_date": next_year.isoformat(),
            "year_inference_status": "cross_year_forward_from_publish",
            "confidence_delta": 0.16,
        }
    return {
        "normalized_date": same_year.isoformat(),
        "year_inference_status": "same_year_past_or_ambiguous",
        "confidence_delta": -0.04,
    }


def infer_relative_weekday(partial_date: str, post_date: date) -> dict[str, Any] | None:
    raw = text(partial_date)
    if not raw.startswith("weekday:"):
        return None
    try:
        target_weekday = int(raw.split(":", 1)[1])
    except ValueError:
        return None
    if not 1 <= target_weekday <= 7:
        return None
    days_ahead = (target_weekday - post_date.isoweekday()) % 7
    inferred_date = post_date + timedelta(days=days_ahead)
    return {
        "normalized_date": inferred_date.isoformat(),
        "year_inference_status": "relative_weekday_from_article_post_date",
        "confidence_delta": 0.12,
    }


def clamp(value: float) -> float:
    return max(0.0, min(0.99, round(value, 4)))


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def build_rows(repair_db: Path, source_url_db: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(repair_db)
    conn.row_factory = sqlite3.Row
    rows: list[dict[str, Any]] = []
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(source_url_db),))
        sql = """
            SELECT
              t.event_key,
              t.source_article_uid,
              t.event_id,
              t.event_name,
              t.source_account,
              t.source_title,
              t.time_text,
              t.normalized_date,
              t.partial_date,
              t.time_of_day,
              t.precision,
              t.confidence,
              t.parse_status,
              s.post_date,
              s.post_time,
              s.source_url,
              s.match_basis AS source_url_match_basis
            FROM event_time_candidates t
            LEFT JOIN src.article_source_url s ON s.article_uid = t.source_article_uid
            ORDER BY t.source_article_uid, t.event_id, t.event_name
        """
        for raw_row in conn.execute(sql):
            row = row_dict(raw_row)
            base_confidence = float(row.get("confidence") or 0.0)
            normalized_date = text(row.get("normalized_date"))
            partial = text(row.get("partial_date"))
            post = parse_date(row.get("post_date") or row.get("post_time"))
            precision = text(row.get("precision"))
            status = text(row.get("parse_status"))
            inferred_from = "time_text"
            year_status = ""
            confidence = base_confidence
            review_tier = "review_candidate"

            if normalized_date:
                review_tier = "auto_candidate" if confidence >= 0.82 else "review_candidate"
            elif status in {"relative_today", "relative_tomorrow"} and post:
                offset_days = 1 if status == "relative_tomorrow" else 0
                normalized_date = (post + timedelta(days=offset_days)).isoformat()
                precision = "date_inferred_from_article_post_relative_day"
                year_status = f"{status}_from_article_post_date"
                inferred_from = "relative_time_text_plus_article_post_date"
                confidence = clamp(base_confidence + 0.08)
                review_tier = "auto_candidate" if confidence >= 0.70 else "review_candidate"
            elif status == "relative_weekday" and post:
                inferred = infer_relative_weekday(partial, post)
                if inferred:
                    normalized_date = inferred["normalized_date"]
                    year_status = inferred["year_inference_status"]
                    confidence = clamp(base_confidence + float(inferred["confidence_delta"]))
                    precision = "date_inferred_from_article_post_weekday"
                    inferred_from = "weekday_time_text_plus_article_post_date"
                    review_tier = "auto_candidate" if confidence >= 0.70 else "review_candidate"
            elif partial and post:
                inferred = infer_year(partial, post)
                if inferred:
                    normalized_date = inferred["normalized_date"]
                    year_status = inferred["year_inference_status"]
                    confidence = clamp(base_confidence + float(inferred["confidence_delta"]))
                    precision = "date_inferred_from_post_date"
                    status = "partial_date_year_inferred"
                    inferred_from = "time_text_partial_plus_article_post_date"
                    review_tier = "auto_candidate" if confidence >= 0.74 and "ambiguous" not in year_status else "review_candidate"
            elif status == "time_only" and post:
                normalized_date = post.isoformat()
                precision = "article_post_date_plus_time_only"
                status = "time_only_date_from_post_date_review"
                inferred_from = "article_post_date_plus_time_only"
                year_status = "post_date_used_as_event_date_low_confidence"
                confidence = clamp(base_confidence + 0.1)

            rows.append(
                {
                    "event_key": text(row.get("event_key")),
                    "source_article_uid": text(row.get("source_article_uid")),
                    "event_id": text(row.get("event_id")),
                    "event_name": text(row.get("event_name")),
                    "source_account": text(row.get("source_account")),
                    "source_title": text(row.get("source_title")),
                    "time_text": text(row.get("time_text")),
                    "normalized_date": normalized_date,
                    "partial_date": partial,
                    "time_of_day": text(row.get("time_of_day")),
                    "precision": precision,
                    "parse_status": status,
                    "year_inference_status": year_status,
                    "article_post_date": text(row.get("post_date")),
                    "source_url_match_basis": text(row.get("source_url_match_basis")),
                    "confidence": confidence,
                    "review_tier": review_tier,
                    "inferred_from": inferred_from,
                    "private_internal_only": 1,
                    "public_graph_visible": 0,
                }
            )
    finally:
        conn.close()
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


def write_sqlite(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE event_time_normalized (
              event_key TEXT PRIMARY KEY,
              source_article_uid TEXT,
              event_id TEXT,
              event_name TEXT,
              source_account TEXT,
              source_title TEXT,
              time_text TEXT,
              normalized_date TEXT,
              partial_date TEXT,
              time_of_day TEXT,
              precision TEXT,
              parse_status TEXT,
              year_inference_status TEXT,
              article_post_date TEXT,
              source_url_match_basis TEXT,
              confidence REAL,
              review_tier TEXT,
              inferred_from TEXT,
              private_internal_only INTEGER,
              public_graph_visible INTEGER
            );
            CREATE TABLE event_time_normalized_run (
              generated_at TEXT,
              summary_json TEXT,
              safety_json TEXT
            );
            CREATE INDEX idx_event_time_norm_source ON event_time_normalized(source_article_uid);
            CREATE INDEX idx_event_time_norm_date ON event_time_normalized(normalized_date);
            CREATE INDEX idx_event_time_norm_tier ON event_time_normalized(review_tier, confidence);
            """
        )
        columns = list(rows[0].keys()) if rows else []
        if columns:
            sql = f"INSERT OR REPLACE INTO event_time_normalized ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
            conn.executemany(sql, [[row.get(column) for column in columns] for row in rows])
        safety = {
            "source_sqlite_write_executed": False,
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "production_write_executed": False,
        }
        conn.execute(
            "INSERT INTO event_time_normalized_run VALUES (?, ?, ?)",
            (text(summary.get("generated_at")), json.dumps(summary, ensure_ascii=False), json.dumps(safety, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def build_summary(out_dir: Path, repair_db: Path, source_url_db: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    parse_counts = Counter(row["parse_status"] for row in rows)
    precision_counts = Counter(row["precision"] for row in rows)
    tier_counts = Counter(row["review_tier"] for row in rows)
    year_counts = Counter(row["year_inference_status"] or "not_needed_or_unavailable" for row in rows)
    normalized_count = sum(1 for row in rows if text(row.get("normalized_date")))
    return {
        "schema_version": "atlas_event_time_normalized_sidecar.summary.v1",
        "generated_at": now_iso(),
        "repair_db": str(repair_db),
        "source_url_db": str(source_url_db),
        "out_dir": str(out_dir),
        "sidecar_sqlite": str(out_dir / "atlas_event_time_normalized_sidecar.sqlite"),
        "input_time_candidates": len(rows),
        "normalized_date_count": normalized_count,
        "unresolved_date_count": len(rows) - normalized_count,
        "auto_candidate_count": tier_counts.get("auto_candidate", 0),
        "review_candidate_count": tier_counts.get("review_candidate", 0),
        "parse_status_counts": dict(parse_counts),
        "precision_counts": dict(precision_counts),
        "year_inference_status_counts": dict(year_counts),
        "safety": {
            "report_only": True,
            "source_sqlite_write_executed": False,
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "production_write_executed": False,
        },
        "next_gate": [
            "Use auto_candidate normalized dates for private DJ rollup sorting.",
            "Keep same_year_past_or_ambiguous rows in review before public timeline claims.",
            "Use local raw/llm_input evidence for the remaining unresolved or ambiguous rows before any paid model call.",
        ],
    }


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas Event Time Normalized Sidecar",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- sidecar_sqlite: `{summary['sidecar_sqlite']}`",
        "- write_status: `report_only_private_sidecar`",
        "",
        "## Coverage",
        "",
        f"- input_time_candidates: `{summary['input_time_candidates']}`",
        f"- normalized_date_count: `{summary['normalized_date_count']}`",
        f"- unresolved_date_count: `{summary['unresolved_date_count']}`",
        f"- auto_candidate_count: `{summary['auto_candidate_count']}`",
        f"- review_candidate_count: `{summary['review_candidate_count']}`",
        "",
        "## Precision Counts",
        "",
        "| Precision | Rows |",
        "|---|---:|",
    ]
    for key, value in sorted(summary["precision_counts"].items()):
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Year Inference", "", "| Status | Rows |", "|---|---:|"])
    for key, value in sorted(summary["year_inference_status_counts"].items()):
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Samples", "", "| Tier | Date | Source | Event | Raw Time |", "|---|---|---|---|---|"])
    for row in rows[:12]:
        event_name = text(row.get("event_name"))
        if len(event_name) > 50:
            event_name = event_name[:47] + "..."
        lines.append(
            f"| `{row['review_tier']}` | `{row['normalized_date']}` | `{row['source_account']}` | `{event_name}` | `{row['time_text']}` |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_time_normalized_sidecar(repair_db: Path, source_url_db: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = build_rows(repair_db, source_url_db)
    summary = build_summary(out_dir, repair_db, source_url_db, rows)
    write_json(out_dir / "summary.json", summary)
    write_jsonl(out_dir / "event_time_normalized.jsonl", rows)
    write_sqlite(out_dir / "atlas_event_time_normalized_sidecar.sqlite", rows, summary)
    write_markdown(out_dir / "summary.md", summary, rows)
    return {"summary": summary, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-db", type=Path, default=DEFAULT_REPAIR)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URLS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    result = build_time_normalized_sidecar(args.repair_db, args.source_url_db, args.out_dir)
    print(json.dumps({"ok": True, "summary": result["summary"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
