#!/usr/bin/env python3
"""Report-only acceptance precheck for Atlas source/OCR repair rows."""
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
DEFAULT_REPAIR_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_repair_packet_t5_20260526"
    / "source_ocr_repair_packet_rows.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_acceptance_precheck_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_ACCEPTANCE_PRECHECK_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_acceptance_precheck.v1"

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
        raise ValueError(f"{label} must not point to D: for source/OCR acceptance precheck: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def truthy(row: dict[str, Any], key: str) -> bool:
    value = row.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "passed", "verified"}
    return bool(value)


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


def required_evidence(row: dict[str, Any]) -> list[str]:
    lane = compact(row.get("repair_lane"), 100)
    required = ["date_verified", "venue_verified", "lineup_verified"]
    if lane in {"source_context_reextract", "source_plus_ocr_repair"}:
        required.append("source_context_verified")
    if lane in {"ocr_markdown_repair", "source_plus_ocr_repair"}:
        required.append("ocr_markdown_verified")
    return required


def precheck_row(row: dict[str, Any], generated_at: str, rank: int) -> dict[str, Any]:
    lane = compact(row.get("repair_lane"), 100)
    required = required_evidence(row)
    missing = [key for key in required if not truthy(row, key)]
    blockers: list[str] = []
    if lane == "manual_editorial_filter":
        blockers.append("manual_editorial_filter_required")
    if truthy(row, "accepted_for_graph") or truthy(row, "graph_write_allowed") or truthy(row, "serving_rebuild_allowed"):
        blockers.append("input_claims_mutation_permission_not_allowed_in_precheck")
    blockers.extend(f"missing_{key}" for key in missing)
    ready = not blockers
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "precheck_rank": rank,
        "work_item_id": compact(row.get("work_item_id"), 120),
        "article_uid": compact(row.get("article_uid"), 200),
        "source_account": compact(row.get("source_account"), 200),
        "title": compact(row.get("title"), 500),
        "repair_lane": lane,
        "required_evidence": required,
        "missing_evidence": missing,
        "blockers": blockers,
        "ready_for_acceptance_gate": ready,
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
        "next_gate": (
            "Run bounded repair for missing evidence, then rerun this precheck before any deterministic "
            "graph acceptance or serving rebuild."
        ),
    }


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
    lane_counts = summary["repair_lane_counts"]
    blocker_counts = summary["blocker_counts"]
    lines = [
        "# Atlas T5 Source/OCR Acceptance Precheck",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input repair rows: `{counts['input_rows']}`",
        f"- Ready for deterministic acceptance gate: `{counts['ready_for_acceptance_gate_rows']}`",
        f"- Blocked rows: `{counts['blocked_rows']}`",
        f"- Manual editorial filter rows: `{counts['manual_editorial_filter_rows']}`",
        f"- Public leak scan: `{summary['public_leak_scan']}`",
        "",
        "## Repair Lane Counts",
        "",
        "| lane | rows |",
        "| --- | ---: |",
    ]
    for lane, count in sorted(lane_counts.items()):
        lines.append(f"| `{lane}` | `{count}` |")
    lines.extend(["", "## Blocker Counts", "", "| blocker | rows |", "| --- | ---: |"])
    for blocker, count in sorted(blocker_counts.items()):
        lines.append(f"| `{blocker}` | `{count}` |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This precheck is report-only. It does not execute OCR, call LLMs, accept graph facts, "
            "rebuild serving SQLite, write source/raw Atlas DBs, write graph/vector/DB state, update "
            "public pointers, deploy, upload/review mini-programs, write memory, read credentials, use "
            "9router, scan D: roots, or run destructive Git.",
            "",
        ]
    )
    return "\n".join(lines)


def build_precheck(repair_rows_jsonl: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    rows = read_jsonl(repair_rows_jsonl)
    precheck_rows = [precheck_row(row, generated_at, idx) for idx, row in enumerate(rows, start=1)]
    ready_rows = [row for row in precheck_rows if row["ready_for_acceptance_gate"]]
    blocked_rows = [row for row in precheck_rows if not row["ready_for_acceptance_gate"]]
    manual_rows = [row for row in precheck_rows if row["repair_lane"] == "manual_editorial_filter"]
    execution_rows = [
        row
        for row in precheck_rows
        if row["repair_lane"] in {"source_plus_ocr_repair", "source_context_reextract", "ocr_markdown_repair"}
    ]

    leak_hits = leak_scan(precheck_rows)
    blocker_counts = Counter(blocker for row in precheck_rows for blocker in row["blockers"])
    lane_counts = Counter(row["repair_lane"] for row in precheck_rows)
    failed_checks = []
    if any(leak_hits.values()):
        failed_checks.append("public_leak_scan_nonzero")

    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_source_ocr_acceptance_precheck_blocked_report_only"
        if blocked_rows
        else "atlas_source_ocr_acceptance_precheck_ready_report_only",
        "failed_checks": failed_checks,
        "repair_rows_jsonl": str(repair_rows_jsonl),
        "out_dir": str(out_dir),
        "report_md": str(report_path),
        "counts": {
            "input_rows": len(rows),
            "precheck_rows": len(precheck_rows),
            "ready_for_acceptance_gate_rows": len(ready_rows),
            "blocked_rows": len(blocked_rows),
            "manual_editorial_filter_rows": len(manual_rows),
            "execution_order_rows": len(execution_rows),
        },
        "repair_lane_counts": dict(sorted(lane_counts.items())),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "public_leak_scan": leak_hits,
        "outputs": {
            "summary_json": str(out_dir / "source_ocr_acceptance_precheck_summary.json"),
            "precheck_rows_jsonl": str(out_dir / "source_ocr_acceptance_precheck_rows.jsonl"),
            "blocked_rows_jsonl": str(out_dir / "source_ocr_acceptance_blocked_rows.jsonl"),
            "ready_rows_jsonl": str(out_dir / "source_ocr_acceptance_ready_rows.jsonl"),
            "manual_editorial_filter_jsonl": str(out_dir / "manual_editorial_filter_blocked.jsonl"),
            "execution_order_jsonl": str(out_dir / "source_ocr_repair_execution_order.jsonl"),
        },
        "safety": {
            "report_only": True,
            "ocr_execution_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
        },
        "stop_reason": "none",
        "wait_reason": "Rows remain blocked until required source/OCR/date/venue/lineup evidence is repaired.",
    }

    write_json(out_dir / "source_ocr_acceptance_precheck_summary.json", summary)
    write_jsonl(out_dir / "source_ocr_acceptance_precheck_rows.jsonl", precheck_rows)
    write_jsonl(out_dir / "source_ocr_acceptance_blocked_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "source_ocr_acceptance_ready_rows.jsonl", ready_rows)
    write_jsonl(out_dir / "manual_editorial_filter_blocked.jsonl", manual_rows)
    write_jsonl(out_dir / "source_ocr_repair_execution_order.jsonl", execution_rows)
    write_text(report_path, build_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair-rows", type=Path, default=DEFAULT_REPAIR_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_precheck(args.repair_rows, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
