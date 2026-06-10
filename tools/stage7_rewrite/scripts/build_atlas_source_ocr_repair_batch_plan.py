#!/usr/bin/env python3
"""Build report-only Atlas source/OCR repair batches from the acceptance precheck."""
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
DEFAULT_EXECUTION_ORDER = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_acceptance_precheck_t5_20260526"
    / "source_ocr_repair_execution_order.jsonl"
)
DEFAULT_MANUAL_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_acceptance_precheck_t5_20260526"
    / "manual_editorial_filter_blocked.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_repair_batch_plan_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_REPAIR_BATCH_PLAN_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_repair_batch_plan.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)

BATCH_BY_LANE = {
    "source_plus_ocr_repair": ("batch_01_source_plus_ocr", 100),
    "source_context_reextract": ("batch_02_source_context", 80),
    "ocr_markdown_repair": ("batch_03_ocr_markdown", 70),
    "manual_editorial_filter": ("deferred_manual_editorial_filter", 10),
}

REQUIRED_BY_BATCH = {
    "batch_01_source_plus_ocr": [
        "source_context_verified",
        "ocr_markdown_verified",
        "date_verified",
        "venue_verified",
        "lineup_verified",
    ],
    "batch_02_source_context": [
        "source_context_verified",
        "date_verified",
        "venue_verified",
        "lineup_verified",
    ],
    "batch_03_ocr_markdown": [
        "ocr_markdown_verified",
        "date_verified",
        "venue_verified",
        "lineup_verified",
    ],
    "deferred_manual_editorial_filter": [
        "date_verified",
        "venue_verified",
        "lineup_verified",
        "manual_editorial_reviewed",
    ],
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas source/OCR repair batch planning: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def read_jsonl(path: Path, required: bool = True) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return []
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


def as_int(value: Any, default: int = 999999) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_title(value: Any) -> str:
    text = compact(value, 500).casefold()
    text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return text or "untitled"


def classify_batch(row: dict[str, Any]) -> tuple[str, int]:
    lane = compact(row.get("repair_lane"), 100)
    return BATCH_BY_LANE.get(lane, ("deferred_unknown_lane", 1))


def next_action_for(batch_id: str) -> str:
    if batch_id == "batch_01_source_plus_ocr":
        return "Recover local article context and OCR/Markdown evidence, then verify date/venue/lineup fields."
    if batch_id == "batch_02_source_context":
        return "Recover local article context, then verify date/venue/lineup fields."
    if batch_id == "batch_03_ocr_markdown":
        return "Recover local OCR/Markdown evidence, then verify date/venue/lineup fields."
    if batch_id == "deferred_manual_editorial_filter":
        return "Keep out of automated graph acceptance until an editorial review marks it event-like."
    return "Inspect lane and assign a deterministic repair path before graph acceptance."


def plan_row(row: dict[str, Any], generated_at: str, batch_rank: int) -> dict[str, Any]:
    batch_id, priority = classify_batch(row)
    source_account = compact(row.get("source_account"), 200)
    title = compact(row.get("title"), 500)
    required = list(REQUIRED_BY_BATCH.get(batch_id, row.get("required_evidence") or []))
    missing = [compact(item, 100) for item in (row.get("missing_evidence") or []) if compact(item, 100)]
    if batch_id == "deferred_manual_editorial_filter" and "manual_editorial_reviewed" not in missing:
        missing.append("manual_editorial_reviewed")
    dedupe_key = f"{source_account.casefold()}::{normalize_title(title)}"
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "batch_rank": batch_rank,
        "source_rank": as_int(row.get("precheck_rank"), batch_rank),
        "batch_id": batch_id,
        "batch_priority": priority,
        "dedupe_key": dedupe_key,
        "work_item_id": compact(row.get("work_item_id"), 120),
        "article_uid": compact(row.get("article_uid"), 200),
        "source_account": source_account,
        "title": title,
        "repair_lane": compact(row.get("repair_lane"), 100),
        "required_evidence": required,
        "missing_evidence": missing,
        "original_blockers": row.get("blockers") or [],
        "next_action": next_action_for(batch_id),
        "ready_for_acceptance_gate": False,
        "accepted_for_graph": False,
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


def rollup_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_source[row["source_account"]].append(row)
    rollups: list[dict[str, Any]] = []
    for source, source_rows in by_source.items():
        batch_counts = Counter(row["batch_id"] for row in source_rows)
        dedupe_counts = Counter(row["dedupe_key"] for row in source_rows)
        repeated_title_groups = sum(1 for count in dedupe_counts.values() if count > 1)
        rollups.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_rollup",
                "source_account": source,
                "rows": len(source_rows),
                "batch_counts": dict(sorted(batch_counts.items())),
                "repeated_title_groups": repeated_title_groups,
                "first_batch_rank": min(row["batch_rank"] for row in source_rows),
                "write_status": "report_only",
            }
        )
    return sorted(rollups, key=lambda row: (-row["rows"], row["first_batch_rank"], row["source_account"]))


def build_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T5 Source/OCR Repair Batch Plan",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Execution-order rows: `{counts['execution_order_rows']}`",
        f"- Manual deferred rows: `{counts['manual_editorial_deferred_rows']}`",
        f"- Planned rows: `{counts['planned_rows']}`",
        f"- Public leak scan: `{summary['public_leak_scan']}`",
        "",
        "## Batch Counts",
        "",
        "| batch | rows |",
        "| --- | ---: |",
    ]
    for batch_id, count in sorted(summary["batch_counts"].items()):
        lines.append(f"| `{batch_id}` | `{count}` |")
    lines.extend(["", "## Top Source Accounts", "", "| source | rows | batch counts |", "| --- | ---: | --- |"])
    for row in summary["top_sources"]:
        lines.append(f"| `{row['source_account']}` | `{row['rows']}` | `{row['batch_counts']}` |")
    lines.extend(
        [
            "",
            "## Execution Cursor",
            "",
            f"- First active batch: `{summary['execution_cursor']['first_active_batch']}`",
            f"- First active rows: `{summary['execution_cursor']['first_active_rows']}`",
            f"- Next command intent: `{summary['execution_cursor']['next_command_intent']}`",
            "",
            "## Boundary",
            "",
            "This batch plan is report-only. It does not execute OCR, call LLMs, accept graph facts, "
            "rebuild serving SQLite, write source/raw Atlas DBs, write graph/vector/DB state, update "
            "public pointers, deploy, upload/review mini-programs, write memory, read credentials, use "
            "9router, scan D: roots, or run destructive Git.",
            "",
        ]
    )
    return "\n".join(lines)


def build_batch_plan(
    execution_order_jsonl: Path,
    manual_rows_jsonl: Path,
    out_dir: Path,
    report_path: Path,
    first_batch_limit: int,
) -> dict[str, Any]:
    generated_at = now_iso()
    execution_rows = read_jsonl(execution_order_jsonl)
    manual_rows = read_jsonl(manual_rows_jsonl, required=False)
    source_rows = execution_rows + manual_rows
    planned_rows = [plan_row(row, generated_at, idx) for idx, row in enumerate(source_rows, start=1)]
    planned_rows.sort(key=lambda row: (-row["batch_priority"], row["source_rank"], row["source_account"], row["title"]))
    for idx, row in enumerate(planned_rows, start=1):
        row["batch_rank"] = idx

    batch_counts = Counter(row["batch_id"] for row in planned_rows)
    source_rollups = rollup_sources(planned_rows)
    leak_hits = leak_scan(planned_rows)
    failed_checks = []
    if any(leak_hits.values()):
        failed_checks.append("public_leak_scan_nonzero")
    if not planned_rows:
        failed_checks.append("no_planned_rows")

    batch_01 = [row for row in planned_rows if row["batch_id"] == "batch_01_source_plus_ocr"]
    batch_02 = [row for row in planned_rows if row["batch_id"] == "batch_02_source_context"]
    batch_03 = [row for row in planned_rows if row["batch_id"] == "batch_03_ocr_markdown"]
    manual_deferred = [row for row in planned_rows if row["batch_id"] == "deferred_manual_editorial_filter"]

    first_active = batch_01 or batch_02 or batch_03
    first_active_batch = first_active[0]["batch_id"] if first_active else "none"
    first_active_rows = first_active[:first_batch_limit]

    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_source_ocr_repair_batch_plan_ready_report_only"
        if not failed_checks
        else "atlas_source_ocr_repair_batch_plan_failed_report_only",
        "failed_checks": failed_checks,
        "execution_order_jsonl": str(execution_order_jsonl),
        "manual_rows_jsonl": str(manual_rows_jsonl),
        "out_dir": str(out_dir),
        "report_md": str(report_path),
        "counts": {
            "execution_order_rows": len(execution_rows),
            "manual_editorial_deferred_rows": len(manual_rows),
            "planned_rows": len(planned_rows),
            "first_active_rows": len(first_active_rows),
            "source_account_rollup_rows": len(source_rollups),
        },
        "batch_counts": dict(sorted(batch_counts.items())),
        "top_sources": source_rollups[:10],
        "public_leak_scan": leak_hits,
        "execution_cursor": {
            "first_active_batch": first_active_batch,
            "first_active_rows": len(first_active_rows),
            "first_batch_limit": first_batch_limit,
            "next_command_intent": "Run the first active batch through local evidence repair, then rerun source/OCR acceptance precheck.",
        },
        "outputs": {
            "summary_json": str(out_dir / "source_ocr_repair_batch_plan_summary.json"),
            "batch_plan_rows_jsonl": str(out_dir / "batch_plan_rows.jsonl"),
            "batch_01_source_plus_ocr_jsonl": str(out_dir / "batch_01_source_plus_ocr.jsonl"),
            "batch_02_source_context_jsonl": str(out_dir / "batch_02_source_context.jsonl"),
            "batch_03_ocr_markdown_jsonl": str(out_dir / "batch_03_ocr_markdown.jsonl"),
            "first_active_batch_jsonl": str(out_dir / "first_active_batch.jsonl"),
            "manual_editorial_filter_deferred_jsonl": str(out_dir / "manual_editorial_filter_deferred.jsonl"),
            "source_account_batch_rollup_jsonl": str(out_dir / "source_account_batch_rollup.jsonl"),
        },
        "safety": {
            "report_only": True,
            "ocr_execution_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
            "production_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "source_sqlite_write_executed": False,
            "memory_write_executed": False,
        },
        "stop_reason": "none" if not failed_checks else "batch_plan_failed_checks",
        "wait_reason": "none",
    }

    write_json(out_dir / "source_ocr_repair_batch_plan_summary.json", summary)
    write_jsonl(out_dir / "batch_plan_rows.jsonl", planned_rows)
    write_jsonl(out_dir / "batch_01_source_plus_ocr.jsonl", batch_01)
    write_jsonl(out_dir / "batch_02_source_context.jsonl", batch_02)
    write_jsonl(out_dir / "batch_03_ocr_markdown.jsonl", batch_03)
    write_jsonl(out_dir / "first_active_batch.jsonl", first_active_rows)
    write_jsonl(out_dir / "manual_editorial_filter_deferred.jsonl", manual_deferred)
    write_jsonl(out_dir / "source_account_batch_rollup.jsonl", source_rollups)
    write_text(report_path, build_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-order-jsonl", type=Path, default=DEFAULT_EXECUTION_ORDER)
    parser.add_argument("--manual-rows-jsonl", type=Path, default=DEFAULT_MANUAL_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--first-batch-limit", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_batch_plan(
        args.execution_order_jsonl,
        args.manual_rows_jsonl,
        args.out_dir,
        args.report,
        args.first_batch_limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if summary["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
