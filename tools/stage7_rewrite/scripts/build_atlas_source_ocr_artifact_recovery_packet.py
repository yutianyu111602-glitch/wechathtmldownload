#!/usr/bin/env python3
"""Build a report-only Atlas source/OCR artifact recovery packet.

This turns the blocked fast-date rows plus the first-batch event/OCR repair
targets into an explicit resumable work queue. It does not execute OCR, call
models, write source databases, rebuild serving SQLite, or touch graph/vector
production state.
"""
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
DEFAULT_DATE_BLOCKED = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_fast_date_repair_attempt_t5_20260526"
    / "date_blocked_rows.jsonl"
)
DEFAULT_EVENT_LIKE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_first_batch_repair_targets_t5_20260526"
    / "event_like_repair_targets.jsonl"
)
DEFAULT_OCR_MARKDOWN = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_first_batch_repair_targets_t5_20260526"
    / "ocr_markdown_repair_targets.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_artifact_recovery_packet_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_ARTIFACT_RECOVERY_PACKET_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_artifact_recovery_packet.v1"

URL_RE = re.compile(r"https?://", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(secret|token|cookie|password|api[_-]?key|authorization)", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas source/OCR artifact recovery: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def scrub_sensitive_words(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit)
    return re.sub(r"(secret|token|cookie|password|api[_-]?key|authorization)", "redacted-word", text, flags=re.I)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


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


def row_key(row: dict[str, Any]) -> str:
    work_item_id = compact(row.get("work_item_id"), 120)
    article_uid = compact(row.get("article_uid"), 200)
    return work_item_id or article_uid


def safe_source_url_evidence(row: dict[str, Any]) -> dict[str, Any]:
    source = row.get("source_url_evidence")
    if not isinstance(source, dict):
        source = row.get("source_url_metadata_checked")
    if not isinstance(source, dict):
        return {"source_url_recovery_found": False}
    return {
        "source_url_recovery_found": bool(source.get("source_url_recovery_found") or source.get("source_url_sidecar_found")),
        "source_ref_id": compact(source.get("source_ref_id"), 120),
        "source_url_sha256": compact(source.get("source_url_sha256"), 80),
        "source_url_present": bool(source.get("source_url_present") or source.get("source_url_sidecar_found")),
        "source_url_match_basis": scrub_sensitive_words(source.get("source_url_match_basis"), 160),
        "source_url_confidence": source.get("source_url_confidence") or 0,
        "post_time_present": bool(source.get("post_time_present")),
        "post_date_present": bool(source.get("post_date_present")),
    }


def list_values(values: Any, limit: int = 12) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            item = compact(value.get("name") or value.get("value"), 180)
        else:
            item = compact(value, 180)
        folded = item.casefold()
        if not item or folded in seen:
            continue
        seen.add(folded)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def blocking_fields(row: dict[str, Any]) -> list[str]:
    values = row.get("blocking_fields") or row.get("missing_after_probe") or []
    if not isinstance(values, list):
        return []
    return [compact(value, 120) for value in values if compact(value, 120)]


def merge_rows(
    date_blocked_rows: list[dict[str, Any]],
    event_like_rows: list[dict[str, Any]],
    ocr_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    sources: dict[str, set[str]] = {}
    for source_name, rows in (
        ("date_blocked", date_blocked_rows),
        ("event_like", event_like_rows),
        ("ocr_markdown", ocr_rows),
    ):
        for row in rows:
            key = row_key(row)
            if not key:
                continue
            current = merged.setdefault(key, {})
            current.update({k: v for k, v in row.items() if v not in (None, "", [])})
            sources.setdefault(key, set()).add(source_name)
    out: list[dict[str, Any]] = []
    for key, row in merged.items():
        row = dict(row)
        row["_source_sets"] = sorted(sources.get(key, set()))
        out.append(row)
    return out


def choose_recovery_lane(row: dict[str, Any]) -> str:
    source_sets = set(row.get("_source_sets") or [])
    primary = compact(row.get("primary_repair_lane"), 160)
    fields = set(blocking_fields(row))
    if "date_blocked" in source_sets:
        return "source_ocr_artifact_recovery_fast_date_blocked"
    if primary == "event_ocr_markdown_and_date_repair":
        return "event_ocr_markdown_and_date_repair"
    if "ocr_markdown_verified" in fields:
        return "ocr_markdown_localization_or_generation"
    if "date_verified" in fields:
        return "date_evidence_localization"
    return "manual_review_or_acceptance_precheck_hold"


def recovery_steps(row: dict[str, Any], lane: str) -> list[str]:
    fields = set(blocking_fields(row))
    steps: list[str] = []
    if "date_verified" in fields or "date_blocked" in set(row.get("_source_sets") or []):
        steps.extend(
            [
                "inspect_article_header_text_or_existing_local_markdown_for_exact_date",
                "inspect_existing_image_ocr_text_for_exact_date",
                "keep_acceptance_gate_closed_until_exact_date_is sourced",
            ]
        )
    if "ocr_markdown_verified" in fields or "ocr" in lane:
        steps.extend(
            [
                "locate_existing_local_images_for_article",
                "locate_existing_poster_ocr_or_llm_input_markdown",
                "queue_bounded_ocr_markdown_generation_if_existing_artifact_absent",
            ]
        )
    if "venue_verified" in fields:
        steps.append("verify_venue_against_recovered_source_context")
    if "lineup_verified" in fields:
        steps.append("verify_lineup_against_recovered_source_context")
    if not steps:
        steps.append("manual_review_before_acceptance_precheck")
    deduped: list[str] = []
    seen: set[str] = set()
    for step in steps:
        if step not in seen:
            seen.add(step)
            deduped.append(step)
    return deduped


def priority(row: dict[str, Any], lane: str) -> int:
    score = 0
    if lane == "source_ocr_artifact_recovery_fast_date_blocked":
        score += 200
    elif lane == "event_ocr_markdown_and_date_repair":
        score += 160
    elif lane == "ocr_markdown_localization_or_generation":
        score += 110
    score += min(int(row.get("candidate_field_counts", {}).get("lineup_candidates") or 0), 12)
    score += min(int(row.get("candidate_field_counts", {}).get("venue_candidates") or 0), 8)
    score += min(int(row.get("candidate_field_counts", {}).get("local_image_count") or 0), 40) // 4
    if safe_source_url_evidence(row).get("source_url_recovery_found"):
        score += 5
    return score


def recovery_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    lane = choose_recovery_lane(row)
    preview = row.get("candidate_preview") if isinstance(row.get("candidate_preview"), dict) else {}
    counts = row.get("candidate_field_counts") if isinstance(row.get("candidate_field_counts"), dict) else {}
    source_url = safe_source_url_evidence(row)
    return {
        "schema_version": SCHEMA_VERSION + ".work_order",
        "generated_at": generated_at,
        "recovery_rank": 0,
        "recovery_priority": priority(row, lane),
        "recovery_lane": lane,
        "source_sets": list(row.get("_source_sets") or []),
        "work_item_id": compact(row.get("work_item_id"), 120),
        "article_uid": compact(row.get("article_uid"), 200),
        "source_account": compact(row.get("source_account"), 200),
        "title": compact(row.get("title"), 500),
        "content_classification": compact(row.get("content_classification"), 120),
        "blocking_fields": blocking_fields(row),
        "candidate_field_counts": {
            "date_candidates": int(counts.get("date_candidates") or len(preview.get("date_values") or [])),
            "venue_candidates": int(counts.get("venue_candidates") or len(preview.get("venue_names") or [])),
            "lineup_candidates": int(counts.get("lineup_candidates") or len(preview.get("lineup_names") or [])),
            "local_image_count": int(counts.get("local_image_count") or 0),
            "source_entity_rows_found": int(counts.get("source_entity_rows_found") or 0),
            "source_event_rows_found": int(counts.get("source_event_rows_found") or 0),
        },
        "candidate_preview": {
            "date_values": list_values(preview.get("date_values"), 8),
            "venue_names": list_values(preview.get("venue_names"), 8),
            "lineup_names": list_values(preview.get("lineup_names"), 12),
            "source_entity_kinds": list_values(preview.get("source_entity_kinds"), 8),
        },
        "source_url_evidence": source_url,
        "artifact_recovery_steps": recovery_steps(row, lane),
        "acceptance_precheck_allowed_now": False,
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
        "next_gate": "recover_source_ocr_artifacts_then_rerun_source_ocr_acceptance_precheck",
    }


def leak_scan(rows: list[dict[str, Any]]) -> dict[str, int]:
    local_path_hits = 0
    public_url_hits = 0
    secret_word_hits = 0
    for row in rows:
        text = json.dumps(row, ensure_ascii=False)
        local_path_hits += len(LOCAL_PATH_RE.findall(text))
        public_url_hits += len(URL_RE.findall(text))
        secret_word_hits += len(SENSITIVE_KEY_RE.findall(text))
    return {
        "local_path_hits": local_path_hits,
        "public_url_hits": public_url_hits,
        "secret_word_hits": secret_word_hits,
    }


def source_rollup(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    by_source: Counter[str] = Counter()
    by_lane: Counter[tuple[str, str]] = Counter()
    for row in rows:
        source = row["source_account"] or "UNKNOWN"
        by_source[source] += 1
        by_lane[(source, row["recovery_lane"])] += 1
    rollup: list[dict[str, Any]] = []
    for rank, (source, count) in enumerate(by_source.most_common(), start=1):
        lanes = {
            lane: lane_count
            for (lane_source, lane), lane_count in by_lane.items()
            if lane_source == source
        }
        rollup.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_rollup",
                "generated_at": generated_at,
                "rank": rank,
                "source_account": source,
                "work_order_rows": count,
                "lane_counts": lanes,
                "write_status": "report_only",
            }
        )
    return rollup


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T5 Source/OCR Artifact Recovery Packet - 2026-05-26",
            "",
            "Status: `CURRENT_AUTHORITY`",
            "Mode: `report_only`",
            "",
            "## LLM Audit Finding",
            "",
            "The 02:59 production graph write is complete for the existing 138,102 base, but it does not advance the participant-delta public serving candidate. The live T5 blocker is now narrower: the fast-date lane accepted `0/2` rows and must be escalated into source/OCR artifact recovery before rerunning acceptance. Blindly rerunning the precheck would be a stale-loop error.",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            f"- Unique work orders: `{counts['unique_work_orders']}`",
            f"- Fast-date artifact recovery rows: `{counts['fast_date_artifact_recovery_rows']}`",
            f"- Event OCR+date repair rows: `{counts['event_ocr_markdown_and_date_repair_rows']}`",
            f"- OCR/Markdown localization rows: `{counts['ocr_markdown_localization_rows']}`",
            f"- Ready for acceptance now: `{counts['ready_for_acceptance_now']}`",
            "",
            "## Outputs",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- All work orders: `{outputs['work_orders_jsonl']}`",
            f"- Fast-date queue: `{outputs['fast_date_artifact_recovery_jsonl']}`",
            f"- Event OCR+date queue: `{outputs['event_ocr_markdown_and_date_jsonl']}`",
            f"- OCR/Markdown queue: `{outputs['ocr_markdown_localization_jsonl']}`",
            f"- Source rollup: `{outputs['source_rollup_jsonl']}`",
            "",
            "## Safety",
            "",
            f"- Leak scan: `{summary['leak_scan']}`",
            "- This packet is report-only. It does not execute OCR, call an LLM/model, write source/raw Atlas DB, rebuild serving SQLite, write Neo4j/Qdrant/SQLite production state, update public pointer, deploy CloudRun/VPS, upload/review mini-program, write memory, read credentials, use 9router, or scan D: roots.",
            "",
            "## Next Cursor",
            "",
            "Process `fast_date_artifact_recovery_queue.jsonl` and `event_ocr_markdown_and_date_repair_queue.jsonl` through bounded local source/OCR artifact localization or generation. Rerun source/OCR acceptance only after recovered artifacts produce exact date/OCR evidence.",
            "",
        ]
    )


def build_packet(
    *,
    date_blocked_path: Path,
    event_like_path: Path,
    ocr_markdown_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in (
        ("date_blocked_path", date_blocked_path),
        ("event_like_path", event_like_path),
        ("ocr_markdown_path", ocr_markdown_path),
        ("out_dir", out_dir),
        ("report_path", report_path),
    ):
        reject_d_path(path, label)

    generated_at = now_iso()
    date_blocked_rows = read_jsonl(date_blocked_path)
    event_like_rows = read_jsonl(event_like_path)
    ocr_markdown_rows = read_jsonl(ocr_markdown_path)

    rows = [recovery_row(row, generated_at) for row in merge_rows(date_blocked_rows, event_like_rows, ocr_markdown_rows)]
    rows.sort(key=lambda item: (item["recovery_priority"], item["source_account"], item["title"]), reverse=True)
    for index, row in enumerate(rows, start=1):
        row["recovery_rank"] = index

    fast_date_rows = [row for row in rows if row["recovery_lane"] == "source_ocr_artifact_recovery_fast_date_blocked"]
    event_rows = [row for row in rows if row["recovery_lane"] == "event_ocr_markdown_and_date_repair"]
    ocr_rows = [row for row in rows if row["recovery_lane"] == "ocr_markdown_localization_or_generation"]
    hold_rows = [row for row in rows if not row["acceptance_precheck_allowed_now"]]
    rollup_rows = source_rollup(rows, generated_at)

    write_jsonl(out_dir / "source_ocr_artifact_recovery_work_orders.jsonl", rows)
    write_jsonl(out_dir / "fast_date_artifact_recovery_queue.jsonl", fast_date_rows)
    write_jsonl(out_dir / "event_ocr_markdown_and_date_repair_queue.jsonl", event_rows)
    write_jsonl(out_dir / "ocr_markdown_localization_queue.jsonl", ocr_rows)
    write_jsonl(out_dir / "acceptance_hold_rows.jsonl", hold_rows)
    write_jsonl(out_dir / "source_account_recovery_rollup.jsonl", rollup_rows)

    scan_rows = rows + rollup_rows
    leak = leak_scan(scan_rows)
    failed_checks = [key for key, value in leak.items() if value]
    lane_counts = Counter(row["recovery_lane"] for row in rows)
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": (
            "atlas_source_ocr_artifact_recovery_packet_ready_report_only"
            if not failed_checks
            else "atlas_source_ocr_artifact_recovery_packet_failed_safety_scan"
        ),
        "failed_checks": failed_checks,
        "counts": {
            "date_blocked_input_rows": len(date_blocked_rows),
            "event_like_input_rows": len(event_like_rows),
            "ocr_markdown_input_rows": len(ocr_markdown_rows),
            "unique_work_orders": len(rows),
            "fast_date_artifact_recovery_rows": len(fast_date_rows),
            "event_ocr_markdown_and_date_repair_rows": len(event_rows),
            "ocr_markdown_localization_rows": len(ocr_rows),
            "acceptance_hold_rows": len(hold_rows),
            "ready_for_acceptance_now": sum(1 for row in rows if row["acceptance_precheck_allowed_now"]),
            "source_account_rollup_rows": len(rollup_rows),
        },
        "lane_counts": dict(lane_counts),
        "top_sources": Counter(row["source_account"] or "UNKNOWN" for row in rows).most_common(10),
        "inputs": {
            "date_blocked_rows": display_path(date_blocked_path),
            "event_like_targets": display_path(event_like_path),
            "ocr_markdown_targets": display_path(ocr_markdown_path),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "source_ocr_artifact_recovery_summary.json"),
            "work_orders_jsonl": display_path(out_dir / "source_ocr_artifact_recovery_work_orders.jsonl"),
            "fast_date_artifact_recovery_jsonl": display_path(out_dir / "fast_date_artifact_recovery_queue.jsonl"),
            "event_ocr_markdown_and_date_jsonl": display_path(out_dir / "event_ocr_markdown_and_date_repair_queue.jsonl"),
            "ocr_markdown_localization_jsonl": display_path(out_dir / "ocr_markdown_localization_queue.jsonl"),
            "acceptance_hold_rows_jsonl": display_path(out_dir / "acceptance_hold_rows.jsonl"),
            "source_rollup_jsonl": display_path(out_dir / "source_account_recovery_rollup.jsonl"),
            "report_md": display_path(report_path),
        },
        "leak_scan": leak,
        "safety": {
            "report_only": True,
            "credential_read": False,
            "d_root_scan": False,
            "network_call_executed": False,
            "llm_call_executed": False,
            "ocr_execution_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "raw_source_url_emitted": False,
            "raw_local_path_emitted": False,
        },
        "llm_audit": {
            "artifact_contradiction_found": False,
            "stale_loop_avoided": "acceptance_precheck_not_rerun_after_0_of_2_fast_date_acceptance",
            "highest_leverage_lane": "source_ocr_artifact_recovery_fast_date_blocked_then_event_ocr_markdown_and_date_repair",
            "pipeline_improvement": "new_resumable_report_only_work_order_packet",
        },
        "stop_reason": "none",
        "wait_reason": "recovery_work_orders_ready_report_only; exact date/OCR artifacts still need bounded localization or generation before acceptance.",
        "next_resume_cursor": "Process fast_date_artifact_recovery_queue.jsonl and event_ocr_markdown_and_date_repair_queue.jsonl; rerun source/OCR acceptance only after recovered exact date/OCR evidence exists.",
    }
    write_json(out_dir / "source_ocr_artifact_recovery_summary.json", summary)
    write_text(report_path, render_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-blocked-rows", type=Path, default=DEFAULT_DATE_BLOCKED)
    parser.add_argument("--event-like-targets", type=Path, default=DEFAULT_EVENT_LIKE)
    parser.add_argument("--ocr-markdown-targets", type=Path, default=DEFAULT_OCR_MARKDOWN)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_packet(
        date_blocked_path=args.date_blocked_rows,
        event_like_path=args.event_like_targets,
        ocr_markdown_path=args.ocr_markdown_targets,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
