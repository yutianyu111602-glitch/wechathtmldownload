#!/usr/bin/env python3
"""Build a report-only repair packet from high-yield Atlas source-context rows.

This consumes the T5 source-context increment audit high-yield queue and turns it
into bounded source-context and OCR/Markdown repair work orders. It does not
fetch content, call models, rebuild serving SQLite, or write graph/vector state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
    / "atlas_source_context_increment_audit_t5_20260526"
    / "high_yield_event_candidates.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_context_high_yield_repair_packet_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_CONTEXT_HIGH_YIELD_REPAIR_PACKET_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_context_high_yield_repair_packet.v1"

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
        raise ValueError(f"{label} must not point to D: for high-yield repair packet: {path}")


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


def item_id(row: dict[str, Any]) -> str:
    key = json.dumps(
        {
            "article_uid": compact(row.get("article_uid"), 200),
            "source_account": compact(row.get("source_account"), 200),
            "title": compact(row.get("title"), 500),
            "lane": compact(row.get("lane"), 120),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def route(row: dict[str, Any]) -> tuple[str, str]:
    lane = compact(row.get("lane"), 120)
    if lane == "ocr_first_event_candidate" or number(row.get("local_image_count")) >= 20:
        return (
            "ocr_markdown_repair",
            "OCR/Markdown evidence must be reviewed before event and participant facts can be accepted.",
        )
    return (
        "source_context_reextract",
        "Source-context re-extract/manual review is required before event and participant facts can be accepted.",
    )


def build_work_order(generated_at: str, row: dict[str, Any], rank: int) -> dict[str, Any]:
    decision, reason = route(row)
    return {
        "schema_version": SCHEMA_VERSION + ".work_order",
        "generated_at": generated_at,
        "work_order_id": item_id(row),
        "rank": rank,
        "audit_rank": int(number(row.get("audit_rank"))),
        "article_uid": compact(row.get("article_uid"), 200),
        "source_account": compact(row.get("source_account"), 200),
        "title": compact(row.get("title"), 500),
        "input_lane": compact(row.get("lane"), 120),
        "repair_lane": decision,
        "repair_reason": reason,
        "increment_score": number(row.get("increment_score")),
        "priority_score": number(row.get("priority_score")),
        "dj_entity_count": int(number(row.get("dj_entity_count"))),
        "entity_count": int(number(row.get("entity_count"))),
        "event_count": int(number(row.get("event_count"))),
        "local_image_count": int(number(row.get("local_image_count"))),
        "recommended_action": compact(row.get("recommended_action"), 500),
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
        "next_gate": "Run bounded source/OCR evidence repair and acceptance review before any source, serving, graph, vector, public, or memory promotion.",
    }


def source_rollups(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    counters: dict[str, Counter[str]] = {}
    scores: Counter[str] = Counter()
    for row in rows:
        source = row["source_account"] or "UNKNOWN"
        counters.setdefault(source, Counter())
        counters[source]["row_count"] += 1
        counters[source][row["repair_lane"]] += 1
        scores[source] += number(row.get("increment_score"))
    output = []
    for source, counts in counters.items():
        output.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_rollup",
                "generated_at": generated_at,
                "source_account": source,
                "row_count": counts["row_count"],
                "source_context_reextract_rows": counts["source_context_reextract"],
                "ocr_markdown_repair_rows": counts["ocr_markdown_repair"],
                "increment_score_sum": round(scores[source], 3),
                "write_status": "report_only",
            }
        )
    return sorted(output, key=lambda item: (item["row_count"], item["increment_score_sum"]), reverse=True)


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        counts["public_url_hits"] += len(URL_RE.findall(text))
        counts["secret_word_hits"] += len(SECRET_RE.findall(text))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    return dict(counts)


def markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas T5 Source-Context High-Yield Repair Packet",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Input: `{summary['input_jsonl']}`",
        "",
        "## Counts",
    ]
    for key, value in summary["counts"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Repair Lane Counts"])
    for key, value in sorted(summary["repair_lane_counts"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Top Source Accounts"])
    for row in summary["top_source_accounts"]:
        lines.append(
            "- {source}: rows `{rows}`, source-context `{source_context}`, OCR `{ocr}`, score `{score}`".format(
                source=row["source_account"],
                rows=row["row_count"],
                source_context=row["source_context_reextract_rows"],
                ocr=row["ocr_markdown_repair_rows"],
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
            "This packet is report-only. It creates bounded repair work orders but does not accept source facts, rebuild serving SQLite, write source SQLite, write Neo4j/Qdrant, update public pointers, deploy, upload/review a mini-program, call models, read credentials, or write memory.",
            "",
        ]
    )
    return "\n".join(lines)


def build_packet(*, input_jsonl: Path, out_dir: Path, report_path: Path, limit: int | None = None) -> dict[str, Any]:
    reject_d_path(input_jsonl, "input_jsonl")
    reject_d_path(out_dir, "out_dir")
    rows = read_jsonl(input_jsonl)
    if limit is not None:
        rows = rows[:limit]
    generated_at = now_iso()
    sorted_rows = sorted(rows, key=lambda row: (number(row.get("increment_score")), number(row.get("priority_score"))), reverse=True)
    work_orders = [build_work_order(generated_at, row, index + 1) for index, row in enumerate(sorted_rows)]
    source_context = [row for row in work_orders if row["repair_lane"] == "source_context_reextract"]
    ocr = [row for row in work_orders if row["repair_lane"] == "ocr_markdown_repair"]
    source_accounts = source_rollups(work_orders, generated_at)

    write_jsonl(out_dir / "high_yield_repair_work_orders.jsonl", work_orders)
    write_jsonl(out_dir / "source_context_reextract_work_order.jsonl", source_context)
    write_jsonl(out_dir / "ocr_markdown_repair_work_order.jsonl", ocr)
    write_jsonl(out_dir / "source_account_repair_rollup.jsonl", source_accounts)

    leak = leak_scan(work_orders + source_accounts)
    failed_checks = [key for key, value in leak.items() if value]
    lane_counts = Counter(row["repair_lane"] for row in work_orders)
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_source_context_high_yield_repair_ready_report_only"
        if not failed_checks
        else "atlas_source_context_high_yield_repair_needs_safety_review",
        "input_jsonl": str(input_jsonl),
        "out_dir": str(out_dir),
        "counts": {
            "input_rows": len(rows),
            "work_order_rows": len(work_orders),
            "source_context_reextract_rows": len(source_context),
            "ocr_markdown_repair_rows": len(ocr),
            "source_account_rollup_rows": len(source_accounts),
            "accepted_for_graph_rows": 0,
            "serving_rebuild_candidates": 0,
        },
        "repair_lane_counts": dict(lane_counts),
        "top_source_accounts": source_accounts[:10],
        "public_leak_scan": leak,
        "failed_checks": failed_checks,
        "outputs": {
            "summary_json": str(out_dir / "summary.json"),
            "work_orders_jsonl": str(out_dir / "high_yield_repair_work_orders.jsonl"),
            "source_context_reextract_work_order_jsonl": str(out_dir / "source_context_reextract_work_order.jsonl"),
            "ocr_markdown_repair_work_order_jsonl": str(out_dir / "ocr_markdown_repair_work_order.jsonl"),
            "source_account_repair_rollup_jsonl": str(out_dir / "source_account_repair_rollup.jsonl"),
            "report_md": str(report_path),
        },
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
        },
        "stop_reason": "none",
        "wait_reason": "Repair work orders still require bounded source/OCR evidence review before deterministic graph facts or serving rebuild.",
    }
    write_json(out_dir / "summary.json", summary)
    write_text(report_path, markdown_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    summary = build_packet(input_jsonl=args.input_jsonl, out_dir=args.out_dir, report_path=args.report, limit=args.limit)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "summary": summary["outputs"]["summary_json"],
                "report": summary["outputs"]["report_md"],
                "work_order_rows": summary["counts"]["work_order_rows"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
