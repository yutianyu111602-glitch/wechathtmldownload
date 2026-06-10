#!/usr/bin/env python3
"""Build a report-only triage packet for Q6 manual participant review rows."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_broader_recovery_acceptance_gate_q6_20260526"
    / "manual_participant_review_candidates.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_review_triage_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_REVIEW_TRIAGE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_review_triage.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for manual participant review triage: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def number(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(row)
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


def triage_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    event_count = number(row.get("event_count"))
    entity_count = number(row.get("entity_count"))
    image_count = number(row.get("local_image_count"))
    has_event = bool(row.get("event_id_present"))
    has_time = bool(row.get("time_text_present"))
    has_place = bool(row.get("place_present"))
    source_account = compact(row.get("source_account"), 220)
    score = event_count * 4 + min(entity_count, 20) + image_count * 2
    if has_event:
        score += 4
    if has_time:
        score += 3
    if has_place:
        score += 3

    if not has_event or not has_time or not has_place:
        triage_bucket = "manual_review_blocked_missing_event_shell"
        next_action = "repair event/time/place shell before participant review"
    elif image_count > 0:
        triage_bucket = "ocr_source_context_review_first"
        next_action = "verify OCR plus source context before participant acceptance"
    elif event_count >= 5 and entity_count >= 10:
        triage_bucket = "high_yield_source_context_review"
        next_action = "review source context and participant mentions as a bounded batch"
    else:
        triage_bucket = "standard_source_context_review"
        next_action = "review source context before any deterministic acceptance"

    return {
        "schema_version": SCHEMA_VERSION + ".work_order",
        "generated_at": generated_at,
        "rank": number(row.get("rank")),
        "work_item_id": compact(row.get("work_item_id"), 120),
        "article_uid": compact(row.get("article_uid"), 220),
        "source_account": source_account,
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 320),
        "event_id_present": has_event,
        "time_text_present": has_time,
        "place_present": has_place,
        "event_count": event_count,
        "entity_count": entity_count,
        "local_image_count": image_count,
        "review_priority_score": score,
        "triage_bucket": triage_bucket,
        "next_action": next_action,
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
    }


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    hits = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        hits["public_url_hits"] += len(URL_RE.findall(text))
        hits["secret_word_hits"] += len(SECRET_RE.findall(text))
        hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    return hits


def source_account_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["source_account"] or "UNKNOWN"].append(row)

    queue: list[dict[str, Any]] = []
    for account, account_rows in groups.items():
        bucket_counts = Counter(row["triage_bucket"] for row in account_rows)
        queue.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "source_account": account,
                "review_rows": len(account_rows),
                "max_priority_score": max(row["review_priority_score"] for row in account_rows),
                "total_priority_score": sum(row["review_priority_score"] for row in account_rows),
                "triage_bucket_counts": dict(sorted(bucket_counts.items())),
                "top_work_item_ids": [row["work_item_id"] for row in account_rows[:5]],
                "write_status": "report_only",
                "next_action": "review account-local source context before participant acceptance",
            }
        )
    queue.sort(key=lambda row: (-row["total_priority_score"], -row["review_rows"], row["source_account"]))
    return queue


def markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas T6 Manual Participant Review Triage",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input manual candidate rows: `{summary['counts']['input_rows']}`",
        f"- High-yield source-context review rows: `{summary['counts']['high_yield_source_context_review_rows']}`",
        f"- Source account review batches: `{summary['counts']['source_account_batches']}`",
        f"- Public URL / secret / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['secret_word_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Triage Buckets",
        "",
        "| bucket | rows |",
        "| --- | ---: |",
    ]
    for bucket, count in sorted(summary["triage_bucket_counts"].items()):
        lines.append(f"| `{bucket}` | `{count}` |")
    lines.extend(["", "## Top Source Account Batches", ""])
    for row in summary["top_source_account_batches"]:
        lines.append(
            "- `{source_account}` rows `{review_rows}` score `{score}` buckets `{buckets}`".format(
                source_account=row["source_account"],
                review_rows=row["review_rows"],
                score=row["total_priority_score"],
                buckets=row["triage_bucket_counts"],
            )
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only local triage for manual participant review candidates.",
            "- No source/raw Atlas DB mutation, serving SQLite rebuild/write, graph/vector/DB production write, public pointer, deploy, upload/review, memory write, credential read, network/model/paid API, destructive Git, 9router use, or D: root scan occurred.",
            "- All work orders remain closed for graph/public promotion until bounded source/OCR/manual evidence review produces deterministic facts.",
            "",
        ]
    )
    return "\n".join(lines)


def build_triage(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    inputs = read_jsonl(input_path)
    work_orders = [triage_row(row, generated_at) for row in inputs]
    work_orders.sort(key=lambda row: (-row["review_priority_score"], row["rank"], row["work_item_id"]))
    account_queue = source_account_queue(work_orders)
    leaks = leak_scan(work_orders)
    failed_checks = [key for key, value in leaks.items() if value]
    bucket_counts = Counter(row["triage_bucket"] for row in work_orders)
    decision = (
        "atlas_social_manual_participant_review_triage_ready_report_only"
        if work_orders and not failed_checks
        else "atlas_social_manual_participant_review_triage_empty_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_review_triage_failed_safety_scan"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "input_jsonl": display_path(input_path),
        "outputs": {
            "summary_json": display_path(out_dir / "manual_participant_review_triage_summary.json"),
            "work_orders_jsonl": display_path(out_dir / "manual_participant_review_work_orders.jsonl"),
            "source_account_batch_queue_jsonl": display_path(out_dir / "source_account_batch_queue.jsonl"),
            "report_md": display_path(report_path),
        },
        "counts": {
            "input_rows": len(inputs),
            "work_order_rows": len(work_orders),
            "high_yield_source_context_review_rows": bucket_counts.get("high_yield_source_context_review", 0),
            "ocr_source_context_review_first_rows": bucket_counts.get("ocr_source_context_review_first", 0),
            "blocked_missing_event_shell_rows": bucket_counts.get("manual_review_blocked_missing_event_shell", 0),
            "source_account_batches": len(account_queue),
        },
        "triage_bucket_counts": dict(sorted(bucket_counts.items())),
        "top_source_account_batches": account_queue[:10],
        "leak_scan": leaks,
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if not failed_checks else "safety_scan_failed",
        "wait_reason": "manual participant rows still require source/OCR/manual evidence review before deterministic acceptance.",
        "next_resume_cursor": display_path(out_dir / "manual_participant_review_work_orders.jsonl"),
    }
    write_jsonl(out_dir / "manual_participant_review_work_orders.jsonl", work_orders)
    write_jsonl(out_dir / "source_account_batch_queue.jsonl", account_queue)
    write_json(out_dir / "manual_participant_review_triage_summary.json", summary)
    write_text(report_path, markdown_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_triage(args.input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
