#!/usr/bin/env python3
"""Build a report-only audit for Atlas source-context increment work.

This consumes the Q6 source-context re-extract review slice and ranks rows that
are most likely to become new performance events, DJ-event edges, or OCR repair
inputs. It reads the selected serving SQLite in read-only mode only for
duplicate/context hints and never writes serving, graph, vector, or production
state.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_broader_source_context_recovery_q6_20260526"
    / "source_context_reextract_review_slice.jsonl"
)
DEFAULT_SELECTED_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_participant_delta_current_20260526_0016"
    / "atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_context_increment_audit_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_CONTEXT_INCREMENT_AUDIT_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_context_increment_audit.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)

EVENT_HINT_RE = re.compile(
    r"(派对|活动|现场|演出|专场|周年|开幕|closing|opening|session|club|live|rave|party|show|festival|周[一二三四五六日天]|\\b\\d{1,2}[./-]\\d{1,2}\\b|\\b20\\d{2}\\b)",
    re.I,
)
CONTEXT_ONLY_RE = re.compile(
    r"(歌单|playlist|访谈|interview|闲谈|研究|小记|唱片店|教程|指南|专访|radio|mix|mixmag|发展|历史|如何|podcast)",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for source-context increment audit: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def load_serving_title_index(db_path: Path | None) -> dict[tuple[str, str], int]:
    if not db_path:
        return {}
    reject_d_path(db_path, "selected_serving_db")
    if not db_path.exists():
        return {}
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            """
            SELECT source_account, source_title, COUNT(*)
            FROM evidence_ref
            GROUP BY source_account, source_title
            """
        ).fetchall()
    finally:
        conn.close()
    return {(normalize(source), normalize(title)): int(count or 0) for source, title, count in rows}


def source_title_seen_count(index: dict[tuple[str, str], int], row: dict[str, Any]) -> int:
    source = normalize(row.get("source_account"))
    title = normalize(row.get("title"))
    if not source or not title:
        return 0
    return index.get((source, title), 0)


def classify_row(row: dict[str, Any], seen_count: int) -> tuple[str, list[str], float]:
    title = compact(row.get("title"), 500)
    source_account = compact(row.get("source_account"), 200)
    dj_entities = int(number(row.get("dj_entity_count")))
    entities = int(number(row.get("entity_count")))
    images = int(number(row.get("local_image_count")))
    event_count = int(number(row.get("event_count")))
    base_score = number(row.get("priority_score")) + dj_entities * 1.8 + entities * 0.4 + images * 0.15
    blob = f"{title} {source_account}"
    reasons: list[str] = []

    if seen_count:
        reasons.append("selected_serving_has_same_source_title")
        base_score -= 8
    if event_count == 0:
        reasons.append("source_slice_event_count_zero")
        base_score += 4
    if dj_entities >= 8:
        reasons.append("dj_rich_article")
        base_score += 6
    if images >= 20:
        reasons.append("image_rich_requires_ocr_merge")
        base_score += 3
    if EVENT_HINT_RE.search(blob):
        reasons.append("event_like_title_or_source")
        base_score += 5
    if CONTEXT_ONLY_RE.search(blob):
        reasons.append("context_or_editorial_title")
        base_score -= 6

    if "selected_serving_has_same_source_title" in reasons:
        lane = "serving_duplicate_context_review"
    elif "context_or_editorial_title" in reasons and "event_like_title_or_source" not in reasons:
        lane = "context_only_or_noise_review"
    elif images >= 20 and event_count == 0:
        lane = "ocr_first_event_candidate"
    elif dj_entities >= 8 and event_count == 0:
        lane = "source_context_event_candidate"
    else:
        lane = "manual_source_context_review"
    return lane, reasons, round(base_score, 3)


def audit_row(generated_at: str, row: dict[str, Any], rank: int, seen_count: int) -> dict[str, Any]:
    lane, reasons, score = classify_row(row, seen_count)
    return {
        "schema_version": SCHEMA_VERSION + ".audit_row",
        "generated_at": generated_at,
        "rank": rank,
        "work_item_id": compact(row.get("work_item_id"), 80),
        "article_uid": compact(row.get("article_uid"), 200),
        "source_account": compact(row.get("source_account"), 200),
        "title": compact(row.get("title"), 500),
        "priority_score": number(row.get("priority_score")),
        "increment_score": score,
        "lane": lane,
        "reasons": reasons,
        "selected_serving_same_source_title_refs": seen_count,
        "dj_entity_count": int(number(row.get("dj_entity_count"))),
        "entity_count": int(number(row.get("entity_count"))),
        "event_count": int(number(row.get("event_count"))),
        "local_image_count": int(number(row.get("local_image_count"))),
        "recommended_action": compact(row.get("recommended_action"), 500),
        "next_gate": (
            "Run source/OCR evidence repair before any source DB, serving DB, graph, vector, public, or memory promotion."
        ),
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
    }


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    public_url_hits = 0
    secret_word_hits = 0
    local_path_hits = 0
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        public_url_hits += len(URL_RE.findall(text))
        secret_word_hits += len(SECRET_RE.findall(text))
        local_path_hits += len(LOCAL_PATH_RE.findall(text))
    return {
        "public_url_hits": public_url_hits,
        "secret_word_hits": secret_word_hits,
        "local_path_hits": local_path_hits,
    }


def source_rollups(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = row["source_account"] or "UNKNOWN"
        bucket = stats.setdefault(
            source,
            {
                "schema_version": SCHEMA_VERSION + ".source_rollup",
                "generated_at": generated_at,
                "source_account": source,
                "row_count": 0,
                "increment_score_sum": 0.0,
                "high_yield_rows": 0,
                "ocr_first_rows": 0,
                "context_only_rows": 0,
                "duplicate_context_rows": 0,
                "write_status": "report_only",
            },
        )
        bucket["row_count"] += 1
        bucket["increment_score_sum"] += row["increment_score"]
        if row["lane"] == "source_context_event_candidate":
            bucket["high_yield_rows"] += 1
        if row["lane"] == "ocr_first_event_candidate":
            bucket["ocr_first_rows"] += 1
        if row["lane"] == "context_only_or_noise_review":
            bucket["context_only_rows"] += 1
        if row["lane"] == "serving_duplicate_context_review":
            bucket["duplicate_context_rows"] += 1
    for item in stats.values():
        item["increment_score_sum"] = round(item["increment_score_sum"], 3)
    return sorted(
        stats.values(),
        key=lambda item: (item["high_yield_rows"] + item["ocr_first_rows"], item["increment_score_sum"], item["row_count"]),
        reverse=True,
    )


def markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas T5 Source-Context Increment Audit",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Input: `{summary['input_jsonl']}`",
        f"- Selected serving DB read-only: `{summary['selected_serving_db']}`",
        "",
        "## Counts",
    ]
    for key, value in summary["counts"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Lane Counts"])
    for key, value in sorted(summary["lane_counts"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Top Source Accounts"])
    for row in summary["top_source_accounts"]:
        lines.append(
            "- {source}: rows `{rows}`, high-yield `{high}`, OCR-first `{ocr}`, score `{score}`".format(
                source=row["source_account"],
                rows=row["row_count"],
                high=row["high_yield_rows"],
                ocr=row["ocr_first_rows"],
                score=row["increment_score_sum"],
            )
        )
    lines.extend(["", "## Outputs"])
    for key, value in sorted(summary["outputs"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Safety"])
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Public Leak Scan"])
    for key, value in sorted(summary["public_leak_scan"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This is report-only prioritization. It does not accept graph facts, rebuild serving SQLite, write source SQLite, write Neo4j/Qdrant, update public pointers, deploy, upload/review a mini-program, call models, read credentials, or write memory.",
            "",
        ]
    )
    return "\n".join(lines)


def build_audit(*, input_jsonl: Path, selected_db: Path | None, out_dir: Path, report_path: Path, limit: int | None = None) -> dict[str, Any]:
    reject_d_path(input_jsonl, "input_jsonl")
    reject_d_path(out_dir, "out_dir")
    rows = read_jsonl(input_jsonl)
    if limit is not None:
        rows = rows[:limit]
    generated_at = now_iso()
    title_index = load_serving_title_index(selected_db)
    audited = [
        audit_row(generated_at, row, rank, source_title_seen_count(title_index, row))
        for rank, row in enumerate(rows, start=1)
    ]
    audited.sort(key=lambda row: row["increment_score"], reverse=True)
    for index, row in enumerate(audited, start=1):
        row["audit_rank"] = index

    high_yield = [
        row
        for row in audited
        if row["lane"] in {"source_context_event_candidate", "ocr_first_event_candidate"}
    ]
    duplicate_context = [row for row in audited if row["lane"] == "serving_duplicate_context_review"]
    context_only = [row for row in audited if row["lane"] == "context_only_or_noise_review"]
    manual_review = [row for row in audited if row["lane"] == "manual_source_context_review"]
    source_rows = source_rollups(audited, generated_at)

    write_jsonl(out_dir / "source_context_increment_audit_rows.jsonl", audited)
    write_jsonl(out_dir / "high_yield_event_candidates.jsonl", high_yield)
    write_jsonl(out_dir / "duplicate_context_review.jsonl", duplicate_context)
    write_jsonl(out_dir / "context_only_or_noise_review.jsonl", context_only)
    write_jsonl(out_dir / "manual_source_context_review.jsonl", manual_review)
    write_jsonl(out_dir / "source_account_increment_rollup.jsonl", source_rows)

    leak = leak_scan(audited + source_rows)
    failed_checks = [key for key, value in leak.items() if value]
    lane_counts = Counter(row["lane"] for row in audited)
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_source_context_increment_audit_ready_report_only" if not failed_checks else "atlas_source_context_increment_audit_needs_safety_review",
        "input_jsonl": str(input_jsonl),
        "selected_serving_db": str(selected_db) if selected_db else "",
        "out_dir": str(out_dir),
        "counts": {
            "input_rows": len(rows),
            "audited_rows": len(audited),
            "high_yield_event_candidate_rows": len(high_yield),
            "duplicate_context_rows": len(duplicate_context),
            "context_only_or_noise_rows": len(context_only),
            "manual_review_rows": len(manual_review),
            "source_account_rollup_rows": len(source_rows),
        },
        "lane_counts": dict(lane_counts),
        "top_source_accounts": source_rows[:10],
        "public_leak_scan": leak,
        "failed_checks": failed_checks,
        "outputs": {
            "summary_json": str(out_dir / "source_context_increment_audit_summary.json"),
            "audit_rows_jsonl": str(out_dir / "source_context_increment_audit_rows.jsonl"),
            "high_yield_event_candidates_jsonl": str(out_dir / "high_yield_event_candidates.jsonl"),
            "duplicate_context_review_jsonl": str(out_dir / "duplicate_context_review.jsonl"),
            "context_only_or_noise_review_jsonl": str(out_dir / "context_only_or_noise_review.jsonl"),
            "manual_source_context_review_jsonl": str(out_dir / "manual_source_context_review.jsonl"),
            "source_account_rollup_jsonl": str(out_dir / "source_account_increment_rollup.jsonl"),
            "report_md": str(report_path),
        },
        "safety": {
            "report_only": True,
            "selected_serving_db_read_only": bool(selected_db),
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
        },
        "stop_reason": "none",
        "wait_reason": "High-yield rows still require source/OCR evidence repair before deterministic graph facts or serving rebuild.",
    }
    write_json(out_dir / "source_context_increment_audit_summary.json", summary)
    write_text(report_path, markdown_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--selected-db", type=Path, default=DEFAULT_SELECTED_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    summary = build_audit(
        input_jsonl=args.input_jsonl,
        selected_db=args.selected_db,
        out_dir=args.out_dir,
        report_path=args.report,
        limit=args.limit,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "summary": summary["outputs"]["summary_json"],
                "report": summary["outputs"]["report_md"],
                "high_yield_event_candidate_rows": summary["counts"]["high_yield_event_candidate_rows"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
