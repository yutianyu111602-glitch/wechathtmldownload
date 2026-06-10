#!/usr/bin/env python3
"""Build a report-only broader T6 source-context recovery packet.

This consumes the current T5 repair work orders and selects bounded review
slices for source-context, OCR/Markdown, and participant repair. It does not
fetch network content, call models, or write graph/database state.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT_DIR = REPO_ROOT / "reports" / "atlas_dj_repair_queue_review_packet_activity_current_20260525_1537"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_broader_source_context_recovery_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_BROADER_SOURCE_CONTEXT_RECOVERY_PACKET_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_broader_source_context_recovery.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for broader source-context recovery: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
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


def evidence(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("evidence")
    return value if isinstance(value, dict) else {}


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_review_row(generated_at: str, lane: str, row: dict[str, Any], rank: int) -> dict[str, Any]:
    ev = evidence(row)
    return {
        "schema_version": SCHEMA_VERSION + ".review_row",
        "generated_at": generated_at,
        "lane": lane,
        "rank": rank,
        "work_item_id": compact(row.get("work_item_id"), 80),
        "article_uid": compact(row.get("article_uid"), 200),
        "event_id": compact(row.get("event_id"), 120),
        "title": compact(row.get("title") or ev.get("title"), 500),
        "name": compact(row.get("name") or ev.get("name"), 300),
        "source_account": compact(row.get("source_account") or ev.get("source_account"), 200),
        "priority_score": number(row.get("priority_score")),
        "local_image_count": int(number(ev.get("local_image_count"))),
        "entity_count": int(number(ev.get("entity_count"))),
        "event_count": int(number(ev.get("event_count"))),
        "dj_entity_count": int(number(ev.get("dj_entity_count"))),
        "time_text": compact(row.get("time_text") or ev.get("time_text"), 100),
        "place": compact(row.get("place") or ev.get("place"), 200),
        "decision": compact(row.get("decision"), 120),
        "recommended_action": compact(row.get("recommended_action"), 500),
        "accepted_for_graph": False,
        "identity_proof": False,
        "avatar_display_allowed": False,
        "public_serving_field_allowed": False,
        "graph_write_allowed": False,
        "write_status": "report_only",
        "next_gate": "T5/T7 manual review before any source, serving, graph, or public promotion.",
    }


def sort_key(row: dict[str, Any]) -> tuple[float, float, float, str]:
    ev = evidence(row)
    return (
        number(row.get("priority_score")),
        number(ev.get("dj_entity_count")) + number(ev.get("entity_count")),
        number(ev.get("local_image_count")),
        compact(row.get("title") or ev.get("title")),
    )


def select_rows(generated_at: str, lane: str, rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected = sorted(rows, key=sort_key, reverse=True)[:limit]
    return [build_review_row(generated_at, lane, row, index + 1) for index, row in enumerate(selected)]


def counter_rows(counter: Counter[str], generated_at: str, lane: str, limit: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": SCHEMA_VERSION + ".source_account_priority",
            "generated_at": generated_at,
            "lane": lane,
            "source_account": key,
            "count": count,
            "write_status": "report_only",
        }
        for key, count in counter.most_common(limit)
    ]


def count_sources(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        ev = evidence(row)
        source = compact(row.get("source_account") or ev.get("source_account") or "UNKNOWN", 200)
        counts[source] += 1
    return counts


def leak_scan(rows: list[dict[str, Any]]) -> dict[str, int]:
    public_url_hits = 0
    secret_word_hits = 0
    local_path_hits = 0
    secret_re = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
    local_path_re = re.compile(r"([a-z]:\\|/mnt/[a-z]/)", re.I)
    url_re = re.compile(r"https?://", re.I)
    for row in rows:
        text = json.dumps(row, ensure_ascii=False)
        public_url_hits += len(url_re.findall(text))
        secret_word_hits += len(secret_re.findall(text))
        local_path_hits += len(local_path_re.findall(text))
    return {
        "public_url_hits": public_url_hits,
        "secret_word_hits": secret_word_hits,
        "local_path_hits": local_path_hits,
    }


def build_packet(*, input_dir: Path, out_dir: Path, report_path: Path, source_limit: int, ocr_limit: int, participant_limit: int) -> dict[str, Any]:
    reject_d_path(input_dir, "input_dir")
    reject_d_path(out_dir, "out_dir")
    source_rows = read_jsonl(input_dir / "source_context_reextract_work_order.jsonl")
    ocr_rows = read_jsonl(input_dir / "ocr_markdown_repair_work_order.jsonl")
    participant_rows = read_jsonl(input_dir / "participant_repair_review_work_order.jsonl")
    generated_at = now_iso()

    source_slice = select_rows(generated_at, "source_context_reextract", source_rows, source_limit)
    ocr_slice = select_rows(generated_at, "ocr_markdown_repair", ocr_rows, ocr_limit)
    participant_slice = select_rows(generated_at, "participant_repair_review", participant_rows, participant_limit)
    combined_slice = source_slice + ocr_slice + participant_slice

    source_priorities = (
        counter_rows(count_sources(source_rows), generated_at, "source_context_reextract")
        + counter_rows(count_sources(ocr_rows), generated_at, "ocr_markdown_repair")
        + counter_rows(count_sources(participant_rows), generated_at, "participant_repair_review")
    )

    write_jsonl(out_dir / "source_context_reextract_review_slice.jsonl", source_slice)
    write_jsonl(out_dir / "ocr_markdown_repair_review_slice.jsonl", ocr_slice)
    write_jsonl(out_dir / "participant_repair_review_slice.jsonl", participant_slice)
    write_jsonl(out_dir / "combined_broader_recovery_review_slice.jsonl", combined_slice)
    write_jsonl(out_dir / "source_account_priorities.jsonl", source_priorities)

    public_leak_scan = leak_scan(combined_slice + source_priorities)
    failed_checks = [
        key for key, value in public_leak_scan.items() if value
    ]
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": (
            "atlas_social_broader_source_context_recovery_ready_report_only"
            if not failed_checks
            else "atlas_social_broader_source_context_recovery_needs_manual_safety_review"
        ),
        "input_dir": str(input_dir),
        "out_dir": str(out_dir),
        "counts": {
            "source_context_input_rows": len(source_rows),
            "ocr_markdown_input_rows": len(ocr_rows),
            "participant_input_rows": len(participant_rows),
            "source_context_review_slice_rows": len(source_slice),
            "ocr_markdown_review_slice_rows": len(ocr_slice),
            "participant_review_slice_rows": len(participant_slice),
            "combined_review_slice_rows": len(combined_slice),
            "source_account_priority_rows": len(source_priorities),
        },
        "top_sources": {
            "source_context_reextract": count_sources(source_rows).most_common(10),
            "ocr_markdown_repair": count_sources(ocr_rows).most_common(10),
            "participant_repair_review": count_sources(participant_rows).most_common(10),
        },
        "public_leak_scan": public_leak_scan,
        "failed_checks": failed_checks,
        "outputs": {
            "summary_json": str(out_dir / "atlas_social_broader_source_context_recovery_summary.json"),
            "source_context_review_slice_jsonl": str(out_dir / "source_context_reextract_review_slice.jsonl"),
            "ocr_markdown_review_slice_jsonl": str(out_dir / "ocr_markdown_repair_review_slice.jsonl"),
            "participant_review_slice_jsonl": str(out_dir / "participant_repair_review_slice.jsonl"),
            "combined_review_slice_jsonl": str(out_dir / "combined_broader_recovery_review_slice.jsonl"),
            "source_account_priorities_jsonl": str(out_dir / "source_account_priorities.jsonl"),
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
        "wait_reason": "Selected rows remain review-only; source-context/OCR/participant facts require manual or later bounded evidence gates before any serving rebuild or product/public/graph promotion.",
        "next_resume_cursor": "Route the combined review slice to T5/T7 manual source-context/OCR/participant review, or build a narrower acceptance gate only after deterministic evidence exists.",
    }

    write_json(out_dir / "atlas_social_broader_source_context_recovery_summary.json", summary)
    write_text(report_path, render_report(summary))
    return summary


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    safety = summary["safety"]
    return "\n".join(
        [
            "# Atlas T6 Broader Source-Context Recovery Packet",
            "",
            f"Generated: {summary['generated_at']}",
            "",
            "## Decision",
            "",
            f"- decision: `{summary['decision']}`",
            "- scope: report-only selection from current T5 repair work orders.",
            "- no source/raw Atlas DB, serving SQLite, Neo4j, Qdrant, public pointer, deploy, upload/review, memory, network, model, paid API, secret, 9router, or D: root action was executed.",
            "",
            "## Counts",
            "",
            f"- source-context input/review slice: `{counts['source_context_input_rows']}` / `{counts['source_context_review_slice_rows']}`",
            f"- OCR/Markdown input/review slice: `{counts['ocr_markdown_input_rows']}` / `{counts['ocr_markdown_review_slice_rows']}`",
            f"- participant input/review slice: `{counts['participant_input_rows']}` / `{counts['participant_review_slice_rows']}`",
            f"- combined review slice: `{counts['combined_review_slice_rows']}`",
            f"- source-account priority rows: `{counts['source_account_priority_rows']}`",
            "",
            "## Outputs",
            "",
            f"- summary: `{summary['outputs']['summary_json']}`",
            f"- combined slice: `{summary['outputs']['combined_review_slice_jsonl']}`",
            f"- source priorities: `{summary['outputs']['source_account_priorities_jsonl']}`",
            "",
            "## Safety",
            "",
            f"- public leak scan: `{summary['public_leak_scan']}`",
            f"- failed checks: `{summary['failed_checks']}`",
            f"- report_only: `{safety['report_only']}`",
            f"- network/model/paid API: `{safety['network_call_executed']}` / `{safety['llm_call_executed']}` / `{safety['paid_api_call_executed']}`",
            f"- production writes: source SQLite `{safety['source_sqlite_write_executed']}`, serving SQLite `{safety['serving_sqlite_rebuild_executed']}`, Neo4j `{safety['neo4j_write_executed']}`, Qdrant `{safety['qdrant_write_executed']}`",
            "",
            "## Stop / Wait",
            "",
            f"- `STOP_REASON`: `{summary['stop_reason']}`",
            f"- `WAIT_REASON`: {summary['wait_reason']}",
            f"- next resume cursor: {summary['next_resume_cursor']}",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--source-limit", type=int, default=120)
    parser.add_argument("--ocr-limit", type=int, default=80)
    parser.add_argument("--participant-limit", type=int, default=120)
    args = parser.parse_args()
    summary = build_packet(
        input_dir=args.input_dir,
        out_dir=args.out_dir,
        report_path=args.report,
        source_limit=args.source_limit,
        ocr_limit=args.ocr_limit,
        participant_limit=args.participant_limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
