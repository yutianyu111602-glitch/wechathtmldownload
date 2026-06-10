#!/usr/bin/env python3
"""Build a report-only event OCR/Markdown/date work order for the Atlas T5 lane."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
TARGET_ROOT = STAGE7_ROOT / "reports" / "atlas_source_ocr_first_batch_repair_targets_t5_20260526"
FAST_DATE_ROOT = STAGE7_ROOT / "reports" / "atlas_source_ocr_fast_date_repair_attempt_t5_20260526"
DEFAULT_EVENT_TARGETS = TARGET_ROOT / "event_like_repair_targets.jsonl"
DEFAULT_OCR_TARGETS = TARGET_ROOT / "ocr_markdown_repair_targets.jsonl"
DEFAULT_DATE_BLOCKED = FAST_DATE_ROOT / "date_blocked_rows.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_event_markdown_date_work_order_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_EVENT_MARKDOWN_DATE_WORK_ORDER_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_event_markdown_date_work_order.v1"

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
        raise ValueError(f"{label} must not point to D: for event OCR/date work order: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
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


def safe_source_url_evidence(row: dict[str, Any]) -> dict[str, Any]:
    evidence = row.get("source_url_evidence") if isinstance(row.get("source_url_evidence"), dict) else {}
    return {
        "source_url_recovery_found": bool(evidence.get("source_url_recovery_found")),
        "source_url_present": bool(evidence.get("source_url_present")),
        "source_ref_id": compact(evidence.get("source_ref_id"), 120),
        "source_url_sha256": compact(evidence.get("source_url_sha256"), 120),
        "source_url_match_basis": compact(evidence.get("source_url_match_basis"), 120),
        "source_url_confidence": evidence.get("source_url_confidence"),
        "post_date_present": bool(evidence.get("post_date_present")),
        "post_time_present": bool(evidence.get("post_time_present")),
    }


def merge_source_rows(
    event_targets: list[dict[str, Any]],
    ocr_targets: list[dict[str, Any]],
    date_blocked: list[dict[str, Any]],
    generated_at: str,
) -> list[dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    date_blocked_keys = {compact(row.get("work_item_id"), 120) or compact(row.get("article_uid"), 200) for row in date_blocked}

    for source_name, source_rows in (("event_like", event_targets), ("ocr_markdown", ocr_targets)):
        for row in source_rows:
            key = compact(row.get("work_item_id"), 120) or compact(row.get("article_uid"), 200)
            if not key:
                continue
            merged = rows_by_key.setdefault(
                key,
                {
                    "schema_version": SCHEMA_VERSION + ".work_order_row",
                    "generated_at": generated_at,
                    "work_item_id": key,
                    "article_uid": compact(row.get("article_uid"), 200),
                    "source_account": compact(row.get("source_account"), 200),
                    "title": compact(row.get("title"), 500),
                    "content_classification": compact(row.get("content_classification"), 100),
                    "source_rank": row.get("source_rank"),
                    "repair_priority": int(row.get("repair_priority") or 0),
                    "source_inputs": [],
                    "blocking_fields": [],
                    "repair_actions": [],
                    "candidate_field_counts": row.get("candidate_field_counts") or {},
                    "candidate_preview": row.get("candidate_preview") or {},
                    "source_url_evidence": safe_source_url_evidence(row),
                    "date_repair_status": "not_attempted",
                    "ready_for_acceptance_gate": False,
                    "accepted_for_graph": False,
                    "serving_rebuild_allowed": False,
                    "graph_write_allowed": False,
                    "public_serving_field_allowed": False,
                    "write_status": "report_only",
                },
            )
            merged["source_inputs"].append(source_name)
            merged["blocking_fields"] = sorted(
                set(merged["blocking_fields"]) | {compact(item, 120) for item in row.get("blocking_fields", [])}
            )
            merged["repair_actions"] = sorted(
                set(merged["repair_actions"]) | {compact(item, 160) for item in row.get("repair_actions", [])}
            )

    for row in rows_by_key.values():
        if row["work_item_id"] in date_blocked_keys:
            row["date_repair_status"] = "fast_date_blocked_escalated_to_artifact_recovery"
            row["repair_actions"] = sorted(set(row["repair_actions"]) | {"recover_date_from_ocr_markdown_or_article_artifact"})
        if "ocr_markdown_verified" in row["blocking_fields"]:
            row["next_gate"] = "Locate or generate local OCR/Markdown evidence, then rerun source/OCR acceptance precheck."
        else:
            row["next_gate"] = "Recover exact local date evidence, then rerun source/OCR acceptance precheck."

    return sorted(rows_by_key.values(), key=lambda row: (-row["repair_priority"], row["source_rank"] or 999999, row["source_account"], row["title"]))


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    hits = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        hits["public_url_hits"] += len(URL_RE.findall(text))
        hits["secret_word_hits"] += len(SECRET_RE.findall(text))
        hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    return hits


def build_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T5 Source/OCR Event Markdown Date Work Order",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Work order rows: `{counts['work_order_rows']}`",
        f"- Fast-date blocked escalations: `{counts['fast_date_blocked_escalations']}`",
        f"- Rows needing OCR/Markdown: `{counts['ocr_markdown_rows']}`",
        f"- Rows needing date evidence: `{counts['date_repair_rows']}`",
        f"- Public leak scan: `{summary['leak_scan']}`",
        "",
        "## Lane Counts",
        "",
        "| lane | rows |",
        "| --- | ---: |",
    ]
    for lane, count in sorted(summary["primary_lane_counts"].items()):
        lines.append(f"| `{lane}` | `{count}` |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This is a report-only work order. It does not execute OCR, call LLMs, accept graph facts, rebuild serving SQLite, write source/raw Atlas DBs, write graph/vector/DB state, update public pointers, deploy, upload/review mini-programs, write memory, read credentials, use 9router, scan D: roots, or run destructive Git.",
            "",
            "## Next Gate",
            "",
            "Process the work order by recovering local OCR/Markdown/date evidence, then rerun the source/OCR acceptance precheck before deterministic graph acceptance or serving rebuild.",
            "",
        ]
    )
    return "\n".join(lines)


def build_work_order(
    event_targets_path: Path,
    ocr_targets_path: Path,
    date_blocked_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    event_targets = read_jsonl(event_targets_path)
    ocr_targets = read_jsonl(ocr_targets_path)
    date_blocked = read_jsonl(date_blocked_path)
    work_rows = merge_source_rows(event_targets, ocr_targets, date_blocked, generated_at)
    for idx, row in enumerate(work_rows, start=1):
        row["work_order_rank"] = idx

    fast_escalations = [row for row in work_rows if row["date_repair_status"] == "fast_date_blocked_escalated_to_artifact_recovery"]
    ocr_rows = [row for row in work_rows if "ocr_markdown_verified" in row["blocking_fields"]]
    date_rows = [row for row in work_rows if "date_verified" in row["blocking_fields"]]
    leak_hits = leak_scan(work_rows)
    failed_checks: list[str] = []
    if any(leak_hits.values()):
        failed_checks.append("work_order_contains_public_url_secret_or_local_path")
    if not work_rows:
        failed_checks.append("no_work_order_rows")

    primary_lanes = Counter(
        "event_ocr_markdown_and_date_repair"
        if "ocr_markdown_verified" in row["blocking_fields"] and "date_verified" in row["blocking_fields"]
        else "date_artifact_recovery"
        for row in work_rows
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_source_ocr_event_markdown_date_work_order_ready_report_only"
        if not failed_checks
        else "atlas_source_ocr_event_markdown_date_work_order_failed_safety_scan",
        "failed_checks": failed_checks,
        "inputs": {
            "event_targets": display_path(event_targets_path),
            "ocr_targets": display_path(ocr_targets_path),
            "date_blocked_rows": display_path(date_blocked_path),
        },
        "outputs": {
            "work_order_rows": display_path(out_dir / "event_markdown_date_work_order_rows.jsonl"),
            "fast_date_escalations": display_path(out_dir / "fast_date_blocked_escalations.jsonl"),
            "ocr_markdown_rows": display_path(out_dir / "ocr_markdown_work_order_rows.jsonl"),
            "date_repair_rows": display_path(out_dir / "date_repair_work_order_rows.jsonl"),
        },
        "counts": {
            "input_event_targets": len(event_targets),
            "input_ocr_targets": len(ocr_targets),
            "input_date_blocked_rows": len(date_blocked),
            "work_order_rows": len(work_rows),
            "fast_date_blocked_escalations": len(fast_escalations),
            "ocr_markdown_rows": len(ocr_rows),
            "date_repair_rows": len(date_rows),
        },
        "primary_lane_counts": dict(sorted(primary_lanes.items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] for row in work_rows).items())),
        "leak_scan": leak_hits,
        "execution_cursor": {
            "next_lane": "event_ocr_markdown_and_date_repair",
            "rerun_acceptance_precheck_now": False,
            "next_command_intent": "Recover local OCR/Markdown/date evidence from artifact records, then rerun source/OCR acceptance precheck.",
        },
        "safety": {
            "report_only": True,
            "raw_source_url_emitted": False,
            "ocr_execution_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
            "production_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "source_sqlite_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if not failed_checks else "event_markdown_date_work_order_failed_checks",
        "wait_reason": "source_ocr_artifact_recovery_required_before_acceptance_precheck",
    }

    write_jsonl(out_dir / "event_markdown_date_work_order_rows.jsonl", work_rows)
    write_jsonl(out_dir / "fast_date_blocked_escalations.jsonl", fast_escalations)
    write_jsonl(out_dir / "ocr_markdown_work_order_rows.jsonl", ocr_rows)
    write_jsonl(out_dir / "date_repair_work_order_rows.jsonl", date_rows)
    write_json(out_dir / "event_markdown_date_work_order_summary.json", summary)
    write_text(report_path, build_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-targets", type=Path, default=DEFAULT_EVENT_TARGETS)
    parser.add_argument("--ocr-targets", type=Path, default=DEFAULT_OCR_TARGETS)
    parser.add_argument("--date-blocked", type=Path, default=DEFAULT_DATE_BLOCKED)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_work_order(args.event_targets, args.ocr_targets, args.date_blocked, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
