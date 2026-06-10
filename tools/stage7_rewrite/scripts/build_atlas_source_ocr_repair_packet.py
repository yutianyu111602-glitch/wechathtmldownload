#!/usr/bin/env python3
"""Build a report-only source/OCR repair packet for Atlas high-yield rows."""
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
DEFAULT_HIGH_YIELD = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_context_increment_audit_t5_20260526"
    / "high_yield_event_candidates.jsonl"
)
DEFAULT_SOURCE_WORK_ORDER = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_repair_queue_review_packet_activity_current_20260525_1537"
    / "source_context_reextract_work_order.jsonl"
)
DEFAULT_OCR_WORK_ORDER = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_repair_queue_review_packet_activity_current_20260525_1537"
    / "ocr_markdown_repair_work_order.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_repair_packet_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_REPAIR_PACKET_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_repair_packet.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
EVENT_HINT_RE = re.compile(
    r"(本周|周[一二三四五六日天]|一览|活动|派对|演出|现场|专场|舞台|开幕|周年|免费入场|club|rave|party|live|session|jar|\\b\\d{1,2}[./-]\\d{1,2}\\b)",
    re.I,
)
EDITORIAL_RE = re.compile(
    r"(歌单|playlist|访谈|专访|闲谈|研究|小记|唱片|专辑|书|教程|指南|历史|如何|radio|mix|podcast)",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for source/OCR repair packet: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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


def index_rows(rows: Iterable[dict[str, Any]]) -> tuple[set[str], set[str]]:
    article_uids: set[str] = set()
    work_item_ids: set[str] = set()
    for row in rows:
        article_uid = compact(row.get("article_uid"), 200)
        work_item_id = compact(row.get("work_item_id"), 120)
        if article_uid:
            article_uids.add(article_uid)
        if work_item_id:
            work_item_ids.add(work_item_id)
    return article_uids, work_item_ids


def in_index(row: dict[str, Any], article_uids: set[str], work_item_ids: set[str]) -> bool:
    article_uid = compact(row.get("article_uid"), 200)
    work_item_id = compact(row.get("work_item_id"), 120)
    return bool((article_uid and article_uid in article_uids) or (work_item_id and work_item_id in work_item_ids))


def classify_repair(row: dict[str, Any], *, in_source: bool, in_ocr: bool) -> tuple[str, list[str], str]:
    title = compact(row.get("title"), 500)
    source_account = compact(row.get("source_account"), 200)
    blob = f"{title} {source_account}"
    source_lane = compact(row.get("lane"), 100)
    images = int(number(row.get("local_image_count")))
    reasons = list(row.get("reasons") or [])
    event_like = bool(EVENT_HINT_RE.search(blob))
    editorial = bool(EDITORIAL_RE.search(blob))

    if in_source:
        reasons.append("present_in_source_context_work_order")
    if in_ocr:
        reasons.append("present_in_ocr_markdown_work_order")
    if event_like:
        reasons.append("event_hint_in_title_or_source")
    if editorial:
        reasons.append("editorial_or_context_title")

    if editorial and not event_like:
        lane = "manual_editorial_filter"
        action = "人工复核是否只是歌单/访谈/专辑/历史文本；未确认前不要生成 performance_event。"
    elif in_ocr and (in_source or source_lane == "source_context_event_candidate"):
        lane = "source_plus_ocr_repair"
        action = "先做 source-context 复核，再检查 OCR/Markdown 合并；两者一致后才进入 deterministic acceptance gate。"
    elif source_lane == "ocr_first_event_candidate" or images >= 20 or in_ocr:
        lane = "ocr_markdown_repair"
        action = "检查 image/GIF -> OCR -> Markdown merge；必要时只重跑该文章的 bounded OCR/LLM 修复。"
    else:
        lane = "source_context_reextract"
        action = "复核原文/Markdown 中的日期、场地、阵容，形成候选 performance_event/DJ_PLAYED_EVENT 证据。"
    return lane, sorted(set(reasons)), action


def build_row(generated_at: str, row: dict[str, Any], rank: int, in_source: bool, in_ocr: bool) -> dict[str, Any]:
    lane, reasons, action = classify_repair(row, in_source=in_source, in_ocr=in_ocr)
    return {
        "schema_version": SCHEMA_VERSION + ".repair_row",
        "generated_at": generated_at,
        "repair_rank": rank,
        "work_item_id": compact(row.get("work_item_id"), 120),
        "article_uid": compact(row.get("article_uid"), 200),
        "source_account": compact(row.get("source_account"), 200),
        "title": compact(row.get("title"), 500),
        "input_lane": compact(row.get("lane"), 100),
        "repair_lane": lane,
        "priority_score": number(row.get("priority_score")),
        "increment_score": number(row.get("increment_score")),
        "dj_entity_count": int(number(row.get("dj_entity_count"))),
        "entity_count": int(number(row.get("entity_count"))),
        "event_count": int(number(row.get("event_count"))),
        "local_image_count": int(number(row.get("local_image_count"))),
        "present_in_source_context_work_order": in_source,
        "present_in_ocr_markdown_work_order": in_ocr,
        "reasons": reasons,
        "recommended_action": action,
        "next_gate": "Bounded source/OCR evidence repair; no source DB, serving DB, graph, vector, public, or memory promotion.",
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
                "source_plus_ocr_repair": 0,
                "source_context_reextract": 0,
                "ocr_markdown_repair": 0,
                "manual_editorial_filter": 0,
                "increment_score_sum": 0.0,
                "write_status": "report_only",
            },
        )
        bucket["row_count"] += 1
        bucket[row["repair_lane"]] += 1
        bucket["increment_score_sum"] = round(bucket["increment_score_sum"] + number(row.get("increment_score")), 3)
    return sorted(stats.values(), key=lambda item: (-item["row_count"], -item["increment_score_sum"], item["source_account"]))


def write_report(path: Path, summary: dict[str, Any]) -> None:
    counts = summary["counts"]
    lane_counts = summary["repair_lane_counts"]
    lines = [
        "# Atlas T5 Source/OCR Repair Packet",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- High-yield input rows: `{counts['high_yield_input_rows']}`",
        f"- Repair rows: `{counts['repair_rows']}`",
        f"- Source/OCR overlap rows: `{counts['source_plus_ocr_repair_rows']}`",
        f"- Source-context reextract rows: `{counts['source_context_reextract_rows']}`",
        f"- OCR/Markdown repair rows: `{counts['ocr_markdown_repair_rows']}`",
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
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            f"- repair packet rows: `{summary['outputs']['repair_packet_rows_jsonl']}`",
            f"- source/OCR overlap queue: `{summary['outputs']['source_plus_ocr_repair_jsonl']}`",
            f"- source-context queue: `{summary['outputs']['source_context_reextract_jsonl']}`",
            f"- OCR/Markdown queue: `{summary['outputs']['ocr_markdown_repair_jsonl']}`",
            f"- manual editorial filter queue: `{summary['outputs']['manual_editorial_filter_jsonl']}`",
            f"- source rollup: `{summary['outputs']['source_rollup_jsonl']}`",
            "",
            "## Boundary",
            "",
            "This packet is report-only. It does not run OCR, call LLMs, write source/raw Atlas DBs, rebuild serving SQLite, write graph/vector/DB state, update public pointers, deploy, upload/review mini-programs, write memory, read credentials, use 9router, scan D: roots, or run destructive Git.",
            "",
        ]
    )
    write_text(path, "\n".join(lines))


def build_packet(
    *,
    high_yield_jsonl: Path,
    source_work_order: Path,
    ocr_work_order: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    high_yield = read_jsonl(high_yield_jsonl)
    source_articles, source_work_items = index_rows(read_jsonl(source_work_order))
    ocr_articles, ocr_work_items = index_rows(read_jsonl(ocr_work_order))

    repair_rows = [
        build_row(
            generated_at,
            row,
            rank,
            in_index(row, source_articles, source_work_items),
            in_index(row, ocr_articles, ocr_work_items),
        )
        for rank, row in enumerate(high_yield, start=1)
    ]
    lane_counts = dict(Counter(row["repair_lane"] for row in repair_rows))
    by_lane = {
        "source_plus_ocr_repair": [row for row in repair_rows if row["repair_lane"] == "source_plus_ocr_repair"],
        "source_context_reextract": [row for row in repair_rows if row["repair_lane"] == "source_context_reextract"],
        "ocr_markdown_repair": [row for row in repair_rows if row["repair_lane"] == "ocr_markdown_repair"],
        "manual_editorial_filter": [row for row in repair_rows if row["repair_lane"] == "manual_editorial_filter"],
    }
    rollups = source_rollups(repair_rows, generated_at)
    public_leaks = leak_scan(repair_rows + rollups)
    failed_checks = [key for key, value in public_leaks.items() if value]
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_source_ocr_repair_packet_ready_report_only"
        if not failed_checks
        else "atlas_source_ocr_repair_packet_blocked_public_leak_scan",
        "failed_checks": failed_checks,
        "high_yield_jsonl": str(high_yield_jsonl),
        "source_work_order": str(source_work_order),
        "ocr_work_order": str(ocr_work_order),
        "out_dir": str(out_dir),
        "report_md": str(report_path),
        "counts": {
            "high_yield_input_rows": len(high_yield),
            "repair_rows": len(repair_rows),
            "source_plus_ocr_repair_rows": len(by_lane["source_plus_ocr_repair"]),
            "source_context_reextract_rows": len(by_lane["source_context_reextract"]),
            "ocr_markdown_repair_rows": len(by_lane["ocr_markdown_repair"]),
            "manual_editorial_filter_rows": len(by_lane["manual_editorial_filter"]),
            "source_rollup_rows": len(rollups),
        },
        "repair_lane_counts": lane_counts,
        "public_leak_scan": public_leaks,
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
        "outputs": {
            "summary_json": str(out_dir / "source_ocr_repair_packet_summary.json"),
            "repair_packet_rows_jsonl": str(out_dir / "source_ocr_repair_packet_rows.jsonl"),
            "source_plus_ocr_repair_jsonl": str(out_dir / "source_plus_ocr_repair_queue.jsonl"),
            "source_context_reextract_jsonl": str(out_dir / "source_context_reextract_queue.jsonl"),
            "ocr_markdown_repair_jsonl": str(out_dir / "ocr_markdown_repair_queue.jsonl"),
            "manual_editorial_filter_jsonl": str(out_dir / "manual_editorial_filter_queue.jsonl"),
            "source_rollup_jsonl": str(out_dir / "source_ocr_repair_source_rollup.jsonl"),
        },
        "stop_reason": "none" if not failed_checks else "public_leak_scan_failed",
        "wait_reason": "Repair queues require bounded source/OCR execution before deterministic graph acceptance.",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(Path(summary["outputs"]["summary_json"]), summary)
    write_jsonl(Path(summary["outputs"]["repair_packet_rows_jsonl"]), repair_rows)
    write_jsonl(Path(summary["outputs"]["source_plus_ocr_repair_jsonl"]), by_lane["source_plus_ocr_repair"])
    write_jsonl(Path(summary["outputs"]["source_context_reextract_jsonl"]), by_lane["source_context_reextract"])
    write_jsonl(Path(summary["outputs"]["ocr_markdown_repair_jsonl"]), by_lane["ocr_markdown_repair"])
    write_jsonl(Path(summary["outputs"]["manual_editorial_filter_jsonl"]), by_lane["manual_editorial_filter"])
    write_jsonl(Path(summary["outputs"]["source_rollup_jsonl"]), rollups)
    write_report(report_path, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--high-yield-jsonl", type=Path, default=DEFAULT_HIGH_YIELD)
    parser.add_argument("--source-work-order", type=Path, default=DEFAULT_SOURCE_WORK_ORDER)
    parser.add_argument("--ocr-work-order", type=Path, default=DEFAULT_OCR_WORK_ORDER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    summary = build_packet(
        high_yield_jsonl=args.high_yield_jsonl,
        source_work_order=args.source_work_order,
        ocr_work_order=args.ocr_work_order,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
