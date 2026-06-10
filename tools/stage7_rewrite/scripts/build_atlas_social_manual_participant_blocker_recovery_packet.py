#!/usr/bin/env python3
"""Build a report-only recovery packet for blocked Q6 manual participant rows.

This packet only consolidates existing redacted report artifacts into bounded
work orders. It does not open SQLite, fetch network resources, call an LLM, or
accept/write graph facts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_blocker_recovery.v1"

DEFAULT_SOURCE_CONTEXT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_source_context_review_q6_20260526"
DEFAULT_ACCEPTANCE_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_acceptance_precheck_q6_20260526"
DEFAULT_EVENT_CLUSTER_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_event_cluster_review_q6_20260526"

DEFAULT_SOURCE_CONTEXT_BLOCKED = DEFAULT_SOURCE_CONTEXT_DIR / "source_context_blocked_rows.jsonl"
DEFAULT_SOURCE_OCR_NEEDED = DEFAULT_SOURCE_CONTEXT_DIR / "source_ocr_recovery_needed_rows.jsonl"
DEFAULT_ACCEPTANCE_BLOCKED = DEFAULT_ACCEPTANCE_DIR / "blocked_manual_participant_acceptance_rows.jsonl"
DEFAULT_MANUAL_EVENT_IDENTITY_BLOCKED = DEFAULT_EVENT_CLUSTER_DIR / "manual_event_identity_blocked_rows.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_blocker_recovery_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_BLOCKER_RECOVERY_PACKET_20260526.md"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    raw = "|".join(compact(part, 800) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for manual participant blocker recovery: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    if not path.exists():
        return []
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


def closed_write_flags() -> dict[str, bool | str]:
    return {
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_status": "report_only",
    }


def summarize_source_matches(row: dict[str, Any]) -> list[dict[str, Any]]:
    matches = row.get("source_matches") if isinstance(row.get("source_matches"), list) else []
    return [
        {
            "source_ref_id": compact(match.get("source_ref_id"), 140),
            "source_hash": compact(match.get("source_hash"), 140),
            "source_account": compact(match.get("source_account"), 220),
            "post_date": compact(match.get("post_date"), 80),
            "title_match_score": round(number(match.get("title_match_score")), 4),
            "title_match_strategy": compact(match.get("title_match_strategy"), 120),
            "public_url_allowed": False,
        }
        for match in matches[:5]
        if isinstance(match, dict)
    ]


def summarize_best_source(row: dict[str, Any]) -> dict[str, Any]:
    best = row.get("best_source_match") if isinstance(row.get("best_source_match"), dict) else {}
    return {
        "source_ref_id": compact(best.get("source_ref_id"), 140),
        "source_hash": compact(best.get("source_hash"), 140),
        "source_account": compact(best.get("source_account"), 220),
        "post_date": compact(best.get("post_date"), 80),
        "title_match_score": round(number(best.get("title_match_score")), 4),
        "title_match_strategy": compact(best.get("title_match_strategy"), 120),
        "public_url_allowed": False,
    }


def base_identity(row: dict[str, Any], generated_at: str, blocker_stage: str, blocker_status: str) -> dict[str, Any]:
    work_item_id = compact(row.get("work_item_id"), 120)
    article_uid = compact(row.get("article_uid"), 260)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "recovery_work_order_id": stable_id(
            "participantrecovery",
            [blocker_stage, blocker_status, work_item_id, article_uid, row.get("source_account"), row.get("name")],
        ),
        "blocker_stage": blocker_stage,
        "blocker_status": blocker_status,
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": article_uid,
        "work_item_id": work_item_id,
        "rank": int(number(row.get("rank"))),
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 320),
        "blocking_reason": compact(row.get("blocking_reason"), 520),
        "upstream_next_gate": compact(row.get("next_gate"), 520),
        **closed_write_flags(),
    }


def source_context_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    status = compact(row.get("review_status"), 140)
    lane = "source_ocr_recovery" if status == "source_ocr_recovery_required" else "manual_event_match_review"
    next_safe_action = (
        "Recover/localize article, image, OCR, or Markdown evidence before any participant acceptance precheck."
        if lane == "source_ocr_recovery"
        else "Review candidate event name against existing performance_event rows; rerun acceptance precheck only after a deterministic event identity is selected."
    )
    return {
        **base_identity(row, generated_at, "source_context_review", status),
        "recovery_lane": lane,
        "source_match_rows": int(number(row.get("source_match_rows"))),
        "matched_performance_event_rows": int(number(row.get("matched_performance_event_rows"))),
        "matched_event_candidate_rows": int(number(row.get("matched_event_candidate_rows"))),
        "participant_sample_rows": int(number(row.get("participant_sample_rows"))),
        "source_refs_for_review": summarize_source_matches(row),
        "event_refs_for_review": [],
        "manual_review_required": True,
        "source_ocr_recovery_required": lane == "source_ocr_recovery",
        "event_identity_recovery_required": lane == "manual_event_match_review",
        "evidence_reextract_required": False,
        "safe_next_action": next_safe_action,
    }


def acceptance_blocked_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    status = compact(row.get("gate_status"), 140)
    return {
        **base_identity(row, generated_at, "acceptance_precheck", status),
        "recovery_lane": "blocked_event_evidence_repair",
        "source_match_rows": int(number(row.get("source_match_rows"))),
        "matched_event_candidate_rows": int(number(row.get("matched_event_candidate_rows"))),
        "qualified_event_candidate_rows": int(number(row.get("qualified_event_candidate_rows"))),
        "participant_sample_rows": int(number(row.get("participant_sample_rows"))),
        "source_refs_for_review": [summarize_best_source(row)] if summarize_best_source(row)["source_ref_id"] else [],
        "event_refs_for_review": [],
        "manual_review_required": True,
        "source_ocr_recovery_required": False,
        "event_identity_recovery_required": False,
        "evidence_reextract_required": True,
        "safe_next_action": (
            "Repair or re-extract event evidence for the matched source before any strict manual acceptance gate."
        ),
    }


def event_cluster_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    status = compact(row.get("review_status"), 140)
    safe_next = {
        "blocked_conflicting_event_dates": "Disambiguate event date from source context/OCR before consolidation.",
        "blocked_conflicting_city_or_venue": "Disambiguate venue/city identity from source context before consolidation.",
        "blocked_low_title_similarity": "Manually review title/event identity before consolidation.",
    }.get(status, "Manual event identity review is required before consolidation.")
    return {
        **base_identity(row, generated_at, "event_cluster_review", status),
        "recovery_lane": "manual_event_identity_review",
        "source_ref_id": compact(row.get("source_ref_id"), 140),
        "source_hash": compact(row.get("source_hash"), 140),
        "post_date": compact(row.get("post_date"), 80),
        "semantic_event_cluster_count": int(number(row.get("semantic_event_cluster_count"))),
        "event_id_count": int(number(row.get("event_id_count"))),
        "candidate_rows": int(number(row.get("candidate_rows"))),
        "participant_sample_rows": int(number(row.get("participant_sample_rows"))),
        "representative_event_id_review_only": compact(row.get("representative_event_id_review_only"), 140),
        "event_ids_for_review": [compact(item, 140) for item in row.get("event_ids_for_consolidation_review", [])[:24]],
        "semantic_event_clusters": row.get("semantic_event_clusters", [])[:8]
        if isinstance(row.get("semantic_event_clusters"), list)
        else [],
        "cluster_date_consistent": bool(row.get("cluster_date_consistent")),
        "cluster_city_consistent": bool(row.get("cluster_city_consistent")),
        "cluster_venue_consistent": bool(row.get("cluster_venue_consistent")),
        "cluster_title_min_similarity": round(number(row.get("cluster_title_min_similarity")), 4),
        "source_refs_for_review": [
            {
                "source_ref_id": compact(row.get("source_ref_id"), 140),
                "source_hash": compact(row.get("source_hash"), 140),
                "post_date": compact(row.get("post_date"), 80),
                "public_url_allowed": False,
            }
        ]
        if compact(row.get("source_ref_id"), 140)
        else [],
        "event_refs_for_review": [compact(item, 140) for item in row.get("event_ids_for_consolidation_review", [])[:24]],
        "manual_review_required": True,
        "source_ocr_recovery_required": False,
        "event_identity_recovery_required": True,
        "evidence_reextract_required": False,
        "safe_next_action": safe_next,
    }


def collapse_source_context_rows(
    source_context_rows: list[dict[str, Any]], source_ocr_rows: list[dict[str, Any]], generated_at: str
) -> list[dict[str, Any]]:
    ocr_keys = {
        (
            compact(row.get("work_item_id"), 120),
            compact(row.get("article_uid"), 260),
        )
        for row in source_ocr_rows
    }
    normalized: list[dict[str, Any]] = []
    for row in source_context_rows:
        key = (compact(row.get("work_item_id"), 120), compact(row.get("article_uid"), 260))
        if key in ocr_keys:
            continue
        normalized.append(source_context_row(row, generated_at))
    normalized.extend(source_context_row(row, generated_at) for row in source_ocr_rows)
    normalized.sort(key=lambda item: (item["source_account"], item["recovery_lane"], item["rank"], item["work_item_id"]))
    return normalized


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        counts["public_url_hits"] += len(URL_RE.findall(text))
        counts["secret_word_hits"] += len(SECRET_RE.findall(text))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    return dict(counts)


def batch_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"]].append(row)
    batches: list[dict[str, Any]] = []
    for source_account, values in sorted(grouped.items()):
        lanes = Counter(row["recovery_lane"] for row in values)
        statuses = Counter(row["blocker_status"] for row in values)
        batches.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "source_account": source_account,
                "recovery_work_order_rows": len(values),
                "lane_counts": dict(sorted(lanes.items())),
                "status_counts": dict(sorted(statuses.items())),
                "top_recovery_work_order_ids": [row["recovery_work_order_id"] for row in values[:8]],
                "write_status": "report_only",
                "next_gate": "Use these work orders only for bounded source/OCR, event identity, or event evidence recovery; all write gates remain closed.",
            }
        )
    return batches


def markdown_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T6 Manual Participant Blocker Recovery Packet",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input source-context blocked rows: `{counts['input_source_context_blocked_rows']}`",
        f"- Input source/OCR recovery rows: `{counts['input_source_ocr_recovery_rows']}`",
        f"- Input acceptance blocked rows: `{counts['input_acceptance_blocked_rows']}`",
        f"- Input manual event-identity blocked rows: `{counts['input_manual_event_identity_blocked_rows']}`",
        f"- Recovery work-order rows: `{counts['recovery_work_order_rows']}`",
        f"- Source/OCR recovery work orders: `{counts['source_ocr_recovery_work_order_rows']}`",
        f"- Manual event-match review work orders: `{counts['manual_event_match_review_work_order_rows']}`",
        f"- Blocked event-evidence repair work orders: `{counts['blocked_event_evidence_repair_work_order_rows']}`",
        f"- Manual event-identity review work orders: `{counts['manual_event_identity_review_work_order_rows']}`",
        f"- Public URL / secret / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['secret_word_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Lane Counts",
        "",
    ]
    for key, value in sorted(summary["recovery_lane_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Blocker Status Counts", ""])
    for key, value in sorted(summary["blocker_status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Output Cursors",
            "",
            f"- all recovery rows: `{summary['outputs']['recovery_rows_jsonl']}`",
            f"- source/OCR recovery work orders: `{summary['outputs']['source_ocr_recovery_work_orders_jsonl']}`",
            f"- manual event-match review work orders: `{summary['outputs']['manual_event_match_review_work_orders_jsonl']}`",
            f"- blocked event-evidence repair work orders: `{summary['outputs']['blocked_event_evidence_repair_work_orders_jsonl']}`",
            f"- manual event-identity review work orders: `{summary['outputs']['manual_event_identity_review_work_orders_jsonl']}`",
            f"- source-account batches: `{summary['outputs']['source_account_batches_jsonl']}`",
            "",
            "## LLM Audit Finding",
            "",
            "- The 08:05 target DB provenance lane is honestly blocked; repeating it without new explicit source/raw DB evidence would not advance the graph.",
            "- The useful next local work is not a write. It is blocker recovery: source/OCR recovery for missing source context, manual event-name matching for source-context rows, event evidence repair for weak acceptance rows, and manual event identity review for conflicting clusters.",
            "- The source/OCR row appears in both source-context blocked output and the dedicated source/OCR recovery output; this packet collapses that duplicate into one source/OCR work order while preserving both input counts.",
            "",
            "## Boundary",
            "",
            "- Report-only consolidation over existing redacted JSONL artifacts.",
            "- No source/raw Atlas DB open or mutation, serving SQLite read/write/rebuild, graph fact acceptance, Neo4j/Qdrant/SQLite production write, public pointer, deploy, upload/review, memory write, credential read, network/model/paid API, 9router use, or D: root scan occurred.",
            "",
            f"- Next resume cursor: {summary['next_resume_cursor']}",
            "",
        ]
    )
    return "\n".join(lines)


def build_blocker_recovery_packet(
    source_context_blocked_path: Path,
    source_ocr_needed_path: Path,
    acceptance_blocked_path: Path,
    manual_event_identity_blocked_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()

    source_context_inputs = read_jsonl(source_context_blocked_path)
    source_ocr_inputs = read_jsonl(source_ocr_needed_path)
    acceptance_inputs = read_jsonl(acceptance_blocked_path)
    event_identity_inputs = read_jsonl(manual_event_identity_blocked_path)

    source_context_work = collapse_source_context_rows(source_context_inputs, source_ocr_inputs, generated_at)
    acceptance_work = [acceptance_blocked_row(row, generated_at) for row in acceptance_inputs]
    event_identity_work = [event_cluster_row(row, generated_at) for row in event_identity_inputs]
    rows = source_context_work + acceptance_work + event_identity_work
    rows.sort(key=lambda item: (item["source_account"], item["recovery_lane"], item["rank"], item["recovery_work_order_id"]))

    source_ocr_work = [row for row in rows if row["recovery_lane"] == "source_ocr_recovery"]
    manual_event_match_work = [row for row in rows if row["recovery_lane"] == "manual_event_match_review"]
    evidence_repair_work = [row for row in rows if row["recovery_lane"] == "blocked_event_evidence_repair"]
    manual_event_identity_work = [row for row in rows if row["recovery_lane"] == "manual_event_identity_review"]
    batches = batch_rows(rows)

    leaks = leak_scan(rows + batches)
    failed_checks = [key for key, value in leaks.items() if value]
    lane_counts = Counter(row["recovery_lane"] for row in rows)
    status_counts = Counter(row["blocker_status"] for row in rows)
    decision = (
        "atlas_social_manual_participant_blocker_recovery_failed_safety_scan"
        if failed_checks
        else "atlas_social_manual_participant_blocker_recovery_ready_report_only"
        if rows
        else "atlas_social_manual_participant_blocker_recovery_empty_report_only"
    )

    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "source_context_blocked_rows_jsonl": display_path(source_context_blocked_path),
            "source_ocr_recovery_needed_rows_jsonl": display_path(source_ocr_needed_path),
            "acceptance_blocked_rows_jsonl": display_path(acceptance_blocked_path),
            "manual_event_identity_blocked_rows_jsonl": display_path(manual_event_identity_blocked_path),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "manual_participant_blocker_recovery_summary.json"),
            "recovery_rows_jsonl": display_path(out_dir / "manual_participant_blocker_recovery_rows.jsonl"),
            "source_ocr_recovery_work_orders_jsonl": display_path(out_dir / "source_ocr_recovery_work_orders.jsonl"),
            "manual_event_match_review_work_orders_jsonl": display_path(out_dir / "manual_event_match_review_work_orders.jsonl"),
            "blocked_event_evidence_repair_work_orders_jsonl": display_path(
                out_dir / "blocked_event_evidence_repair_work_orders.jsonl"
            ),
            "manual_event_identity_review_work_orders_jsonl": display_path(
                out_dir / "manual_event_identity_review_work_orders.jsonl"
            ),
            "source_account_batches_jsonl": display_path(out_dir / "source_account_blocker_recovery_batches.jsonl"),
            "report_md": display_path(report_path),
        },
        "counts": {
            "input_source_context_blocked_rows": len(source_context_inputs),
            "input_source_ocr_recovery_rows": len(source_ocr_inputs),
            "input_acceptance_blocked_rows": len(acceptance_inputs),
            "input_manual_event_identity_blocked_rows": len(event_identity_inputs),
            "recovery_work_order_rows": len(rows),
            "source_ocr_recovery_work_order_rows": len(source_ocr_work),
            "manual_event_match_review_work_order_rows": len(manual_event_match_work),
            "blocked_event_evidence_repair_work_order_rows": len(evidence_repair_work),
            "manual_event_identity_review_work_order_rows": len(manual_event_identity_work),
            "source_account_batches": len(batches),
            "accepted_for_graph_rows": 0,
            "source_sqlite_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "recovery_lane_counts": dict(sorted(lane_counts.items())),
        "blocker_status_counts": dict(sorted(status_counts.items())),
        "leak_scan": leaks,
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_read_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if not failed_checks else "safety_scan_failed",
        "wait_reason": (
            "blocked rows now have report-only recovery work orders; each lane still needs separate source/OCR, event identity, or event evidence recovery before any write."
            if not failed_checks
            else "output safety scan failed"
        ),
        "next_resume_cursor": (
            "Process tools/stage7_rewrite/reports/atlas_social_manual_participant_blocker_recovery_q6_20260526/"
            "source_ocr_recovery_work_orders.jsonl first if source artifacts can be localized safely; otherwise process "
            "manual_event_identity_review_work_orders.jsonl by source account. All write gates remain closed."
        ),
    }

    write_jsonl(out_dir / "manual_participant_blocker_recovery_rows.jsonl", rows)
    write_jsonl(out_dir / "source_ocr_recovery_work_orders.jsonl", source_ocr_work)
    write_jsonl(out_dir / "manual_event_match_review_work_orders.jsonl", manual_event_match_work)
    write_jsonl(out_dir / "blocked_event_evidence_repair_work_orders.jsonl", evidence_repair_work)
    write_jsonl(out_dir / "manual_event_identity_review_work_orders.jsonl", manual_event_identity_work)
    write_jsonl(out_dir / "source_account_blocker_recovery_batches.jsonl", batches)
    write_json(out_dir / "manual_participant_blocker_recovery_summary.json", summary)
    write_text(out_dir / "manual_participant_blocker_recovery_summary.md", markdown_report(summary))
    write_text(report_path, markdown_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-context-blocked", type=Path, default=DEFAULT_SOURCE_CONTEXT_BLOCKED)
    parser.add_argument("--source-ocr-needed", type=Path, default=DEFAULT_SOURCE_OCR_NEEDED)
    parser.add_argument("--acceptance-blocked", type=Path, default=DEFAULT_ACCEPTANCE_BLOCKED)
    parser.add_argument("--manual-event-identity-blocked", type=Path, default=DEFAULT_MANUAL_EVENT_IDENTITY_BLOCKED)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_blocker_recovery_packet(
        args.source_context_blocked,
        args.source_ocr_needed,
        args.acceptance_blocked,
        args.manual_event_identity_blocked,
        args.out_dir,
        args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 1 if summary["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
