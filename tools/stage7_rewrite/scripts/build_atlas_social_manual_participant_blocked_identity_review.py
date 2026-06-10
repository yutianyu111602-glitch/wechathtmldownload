#!/usr/bin/env python3
"""Build a report-only review packet for still-blocked Q6 event identity rows."""
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
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_event_identity_resolution_q6_20260526"
    / "still_blocked_manual_event_identity_rows.jsonl"
)
DEFAULT_OUT_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_blocked_identity_review_q6_20260526"
)
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_BLOCKED_IDENTITY_REVIEW_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_blocked_identity_review.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
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
        raise ValueError(f"{label} must not point to D: for blocked identity review: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


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


def closed_flags() -> dict[str, bool | str]:
    return {
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_status": "report_only",
    }


def cluster_brief(cluster: dict[str, Any]) -> dict[str, Any]:
    event_ids = [compact(item, 140) for item in cluster.get("event_ids", []) if compact(item, 140)]
    return {
        "cluster_id": compact(cluster.get("cluster_id"), 140),
        "starts_at": compact(cluster.get("starts_at"), 40),
        "city_sample": compact(cluster.get("city_sample"), 80),
        "canonical_venue": compact(cluster.get("canonical_venue"), 160),
        "venue_name_sample": compact(cluster.get("venue_name_sample"), 180),
        "event_title_sample": compact(cluster.get("event_title_sample"), 260),
        "event_ids": event_ids[:16],
        "event_id_count": int(number(cluster.get("event_id_count")) or len(event_ids)),
        "candidate_rows": int(number(cluster.get("candidate_rows"))),
        "max_event_match_score": round(number(cluster.get("max_event_match_score")), 4),
        "max_participant_count": int(number(cluster.get("max_participant_count"))),
        "source_ref_ids": [compact(item, 140) for item in cluster.get("source_ref_ids", []) if compact(item, 140)][:8],
    }


def classify_row(row: dict[str, Any]) -> tuple[str, str, list[str], list[str]]:
    blocker = compact(row.get("blocker_status"), 140)
    reason = compact(row.get("resolution_reason"), 220)
    derived_dates = [compact(item, 40) for item in row.get("derived_title_date_candidates", []) if compact(item, 40)]

    if blocker == "blocked_conflicting_event_dates":
        if reason == "multiple_candidate_clusters_match_title_date":
            return (
                "same_date_cluster_tiebreak_review",
                "multiple matching clusters share the source-derived event date",
                [
                    "participant_lineup_overlap_for_matching_clusters",
                    "source_ref_precedence_for_matching_clusters",
                    "event_title_exactness_or_subtitle_scope",
                ],
                ["manual_event_identity_review", "db_backed_readback_before_any_write"],
            )
        if not derived_dates:
            return (
                "source_date_context_recovery",
                "title and post date did not yield an event-date candidate",
                [
                    "article_body_or_markdown_date_context",
                    "poster_ocr_or_image_caption_date_context",
                    "source_account_weekly_schedule_context",
                ],
                ["source_ocr_or_manual_artifact_recovery", "date_review_before_consolidation"],
            )
        return (
            "event_date_or_source_year_recovery",
            "source-derived date exists but no candidate cluster matches it",
            [
                "source_year_rollover_check",
                "candidate_event_date_backfill_evidence",
                "source_ref_to_event_date_lineage",
            ],
            ["source_ocr_or_manual_date_recovery", "event_date_repair_before_consolidation"],
        )

    if blocker == "blocked_conflicting_city_or_venue":
        if reason == "candidate_contains_multi_venue_context":
            return (
                "multi_venue_split_review",
                "candidate clusters include a multi-venue context",
                [
                    "day_night_or_room_split_evidence",
                    "participant_role_scope_by_venue_segment",
                    "source_text_lineage_for_each_venue_segment",
                ],
                ["manual_multi_venue_split_review", "separate_event_identity_before_consolidation"],
            )
        return (
            "venue_alias_lineage_review",
            "venue or city aliases do not canonicalize to one existing identity",
            [
                "venue_alias_equivalence_evidence",
                "city_inference_or_missing_city_evidence",
                "source_ref_to_venue_lineage",
            ],
            ["venue_alias_lineage_gate", "db_backed_readback_before_any_write"],
        )

    if blocker == "blocked_low_title_similarity":
        return (
            "low_title_similarity_manual_review",
            "candidate titles remain semantically close but below deterministic selector threshold",
            [
                "source_title_scope_review",
                "participant_lineup_tiebreak",
                "event_title_alias_or_subtitle_equivalence",
            ],
            ["manual_title_identity_review", "db_backed_readback_before_any_write"],
        )

    return (
        "manual_identity_review",
        "unknown blocker status requires manual review",
        ["source_context_review", "participant_lineup_review"],
        ["manual_event_identity_review"],
    )


def build_review_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    recovery_lane, lane_reason, evidence_requirements, next_gates = classify_row(row)
    clusters = [cluster_brief(cluster) for cluster in row.get("all_semantic_event_clusters", []) if isinstance(cluster, dict)]
    date_values = sorted({cluster["starts_at"] for cluster in clusters if cluster.get("starts_at")})
    venue_values = sorted({cluster["canonical_venue"] for cluster in clusters if cluster.get("canonical_venue")})
    event_ids = sorted({event_id for cluster in clusters for event_id in cluster.get("event_ids", []) if event_id})
    derived_dates = [compact(item, 40) for item in row.get("derived_title_date_candidates", []) if compact(item, 40)]
    matching_date_clusters = [cluster for cluster in clusters if cluster.get("starts_at") in set(derived_dates)]

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "review_work_order_id": stable_id(
            "blockedidentity",
            [row.get("resolution_id"), row.get("article_uid"), row.get("work_item_id"), recovery_lane],
        ),
        "upstream_resolution_id": compact(row.get("resolution_id"), 140),
        "upstream_work_item_id": compact(row.get("work_item_id"), 140),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "rank": int(number(row.get("rank"))),
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 320),
        "post_date": compact(row.get("post_date"), 40),
        "source_ref_id": compact(row.get("source_ref_id"), 140),
        "source_hash": compact(row.get("source_hash"), 140),
        "blocker_status": compact(row.get("blocker_status"), 140),
        "resolution_reason": compact(row.get("resolution_reason"), 220),
        "blocking_reason": compact(row.get("blocking_reason"), 520),
        "recovery_lane": recovery_lane,
        "lane_reason": lane_reason,
        "evidence_requirements": evidence_requirements,
        "next_required_gates": next_gates,
        "manual_review_required": True,
        "source_ocr_recovery_required": recovery_lane in {
            "source_date_context_recovery",
            "event_date_or_source_year_recovery",
        },
        "venue_alias_review_required": recovery_lane == "venue_alias_lineage_review",
        "multi_venue_split_required": recovery_lane == "multi_venue_split_review",
        "db_readback_required_before_write": recovery_lane
        in {
            "same_date_cluster_tiebreak_review",
            "venue_alias_lineage_review",
            "low_title_similarity_manual_review",
        },
        "derived_title_date_candidates": derived_dates,
        "matching_date_cluster_count": len(matching_date_clusters),
        "candidate_date_values": date_values,
        "candidate_venue_values": venue_values,
        "semantic_event_cluster_count": len(clusters),
        "candidate_rows": int(number(row.get("candidate_rows"))),
        "participant_sample_rows": int(number(row.get("participant_sample_rows"))),
        "candidate_event_id_count": len(event_ids),
        "candidate_event_ids_for_review": event_ids[:24],
        "semantic_event_clusters_for_review": clusters[:8],
        "llm_audit_judgment": (
            "report_only_work_order; blocker is not ready for acceptance or write; "
            "recover the named evidence and pass a later explicit gate first"
        ),
        "safe_next_action": safe_next_action(recovery_lane),
        **closed_flags(),
    }


def safe_next_action(recovery_lane: str) -> str:
    actions = {
        "source_date_context_recovery": "Recover source/OCR/Markdown date context, then rerun event-identity resolution in report-only mode.",
        "event_date_or_source_year_recovery": "Review source-year and candidate event-date lineage before any consolidation/readback gate.",
        "same_date_cluster_tiebreak_review": "Compare participant/source evidence across same-date clusters, then feed only deterministic selectors into a DB-backed readback gate.",
        "venue_alias_lineage_review": "Build venue-alias lineage evidence and readback requirements before any alias or event consolidation write.",
        "multi_venue_split_review": "Split day/night or room-scoped event identity with source evidence before any consolidation.",
        "low_title_similarity_manual_review": "Review title alias/subtitle and participant evidence before a readback gate.",
    }
    return actions.get(recovery_lane, "Manual event identity review remains required before any mutation.")


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        counts["public_url_hits"] += len(URL_RE.findall(text))
        counts["sensitive_key_hits"] += len(SECRET_RE.findall(text))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    return dict(counts)


def grouped_batches(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"]].append(row)

    batches: list[dict[str, Any]] = []
    for source_account, values in sorted(grouped.items()):
        lane_counts = Counter(row["recovery_lane"] for row in values)
        blocker_counts = Counter(row["blocker_status"] for row in values)
        batches.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "generated_at": generated_at,
                "source_account": source_account,
                "review_work_order_rows": len(values),
                "recovery_lane_counts": dict(sorted(lane_counts.items())),
                "blocker_status_counts": dict(sorted(blocker_counts.items())),
                "top_review_work_order_ids": [row["review_work_order_id"] for row in values[:8]],
                "next_gate": "Process lane-specific report-only work orders; all write gates remain closed.",
                **closed_flags(),
            }
        )
    return batches


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Manual Participant Blocked Identity Review Summary",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
        f"- Input rows: `{counts['input_still_blocked_rows']}`",
        f"- Work orders: `{counts['review_work_order_rows']}`",
        f"- Source date context recovery: `{counts['source_date_context_recovery_rows']}`",
        f"- Event date/source year recovery: `{counts['event_date_or_source_year_recovery_rows']}`",
        f"- Same-date cluster tiebreak: `{counts['same_date_cluster_tiebreak_review_rows']}`",
        f"- Venue alias lineage: `{counts['venue_alias_lineage_review_rows']}`",
        f"- Multi-venue split: `{counts['multi_venue_split_review_rows']}`",
        f"- Low-title manual review: `{counts['low_title_similarity_manual_review_rows']}`",
        f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
        f"- Next cursor: `{summary['next_resume_cursor']}`",
        "",
    ]
    return "\n".join(lines)


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    lines = [
        "# Atlas T6 Manual Participant Blocked Identity Review - 2026-05-26",
        "",
        "Status: `CURRENT_AUTHORITY`",
        "Mode: `report_only`",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
        f"- Input still-blocked rows: `{counts['input_still_blocked_rows']}`",
        f"- Review work-order rows: `{counts['review_work_order_rows']}`",
        f"- Source-account batches: `{counts['source_account_batches']}`",
        f"- Accepted/write/promotion rows: `{counts['accepted_for_graph_rows']}/{counts['source_sqlite_write_allowed_rows']}/{counts['serving_rebuild_allowed_rows']}/{counts['graph_write_allowed_rows']}/{counts['public_serving_field_allowed_rows']}/{counts['memory_write_allowed_rows']}`",
        f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Lane Counts",
        "",
    ]
    for key, value in sorted(summary["recovery_lane_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Outputs", ""])
    for label in [
        "summary_json",
        "review_rows_jsonl",
        "source_date_context_recovery_jsonl",
        "event_date_or_source_year_recovery_jsonl",
        "same_date_cluster_tiebreak_jsonl",
        "venue_alias_lineage_jsonl",
        "multi_venue_split_jsonl",
        "low_title_similarity_jsonl",
        "source_account_batches_jsonl",
    ]:
        lines.append(f"- {label}: `{outputs[label]}`")
    lines.extend(
        [
            "",
            "## LLM Audit Finding",
            "",
            "- The 10:55 visual API response smoke packet is locally consistent and does not need another blind rerun.",
            "- The 08:05 target DB provenance lane still lacks an explicit source/raw target DB path, so write gates remain closed.",
            "- The current highest-yield safe lane is to turn the 13 still-blocked event-identity rows into lane-specific recovery work orders, separating date-context recovery, same-date cluster tiebreaks, venue alias lineage, multi-venue split, and low-title manual review.",
            "",
            "## Boundary",
            "",
            "- Report-only review over existing redacted JSONL artifacts.",
            "- No source/raw Atlas DB open or mutation, serving SQLite read/write/rebuild, OCR execution, model call, network fetch, graph fact acceptance, Neo4j/Qdrant/SQLite production write, public pointer, CloudRun/VPS deploy, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "- These work orders are not accepted graph facts. A later explicit gate must provide rollback and postwrite readback before any mutation.",
            "",
            "## Next Cursor",
            "",
            f"Use `{summary['next_resume_cursor']}` first, then the lane-specific cursors in the output list. Keep all write flags closed.",
            "",
        ]
    )
    return "\n".join(lines)


def build_blocked_identity_review_packet(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()
    input_rows = read_jsonl(input_path)
    rows = [build_review_row(row, generated_at) for row in input_rows]
    rows.sort(key=lambda item: (item["source_account"], item["recovery_lane"], item["rank"], item["review_work_order_id"]))
    batches = grouped_batches(rows, generated_at)

    lane_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        lane_rows[row["recovery_lane"]].append(row)

    leaks = leak_scan(rows + batches)
    failed_checks = [key for key, value in leaks.items() if value]
    lane_counts = Counter(row["recovery_lane"] for row in rows)
    blocker_counts = Counter(row["blocker_status"] for row in rows)
    decision = (
        "atlas_social_manual_participant_blocked_identity_review_failed_safety_scan"
        if failed_checks
        else "atlas_social_manual_participant_blocked_identity_review_ready_report_only"
        if rows
        else "atlas_social_manual_participant_blocked_identity_review_empty_report_only"
    )

    paths = {
        "summary_json": out_dir / "manual_participant_blocked_identity_review_summary.json",
        "summary_md": out_dir / "manual_participant_blocked_identity_review_summary.md",
        "review_rows_jsonl": out_dir / "manual_participant_blocked_identity_review_rows.jsonl",
        "source_date_context_recovery_jsonl": out_dir / "source_date_context_recovery_work_orders.jsonl",
        "event_date_or_source_year_recovery_jsonl": out_dir / "event_date_or_source_year_recovery_work_orders.jsonl",
        "same_date_cluster_tiebreak_jsonl": out_dir / "same_date_cluster_tiebreak_work_orders.jsonl",
        "venue_alias_lineage_jsonl": out_dir / "venue_alias_lineage_work_orders.jsonl",
        "multi_venue_split_jsonl": out_dir / "multi_venue_split_work_orders.jsonl",
        "low_title_similarity_jsonl": out_dir / "low_title_similarity_work_orders.jsonl",
        "source_account_batches_jsonl": out_dir / "source_account_blocked_identity_batches.jsonl",
        "report_md": report_path,
    }

    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {"still_blocked_manual_event_identity_rows": display_path(input_path)},
        "outputs": {key: display_path(path) for key, path in paths.items()},
        "counts": {
            "input_still_blocked_rows": len(input_rows),
            "review_work_order_rows": len(rows),
            "source_account_batches": len(batches),
            "source_date_context_recovery_rows": len(lane_rows["source_date_context_recovery"]),
            "event_date_or_source_year_recovery_rows": len(lane_rows["event_date_or_source_year_recovery"]),
            "same_date_cluster_tiebreak_review_rows": len(lane_rows["same_date_cluster_tiebreak_review"]),
            "venue_alias_lineage_review_rows": len(lane_rows["venue_alias_lineage_review"]),
            "multi_venue_split_review_rows": len(lane_rows["multi_venue_split_review"]),
            "low_title_similarity_manual_review_rows": len(lane_rows["low_title_similarity_manual_review"]),
            "accepted_for_graph_rows": 0,
            "source_sqlite_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "recovery_lane_counts": dict(sorted(lane_counts.items())),
        "blocker_status_counts": dict(sorted(blocker_counts.items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] for row in rows).items())),
        "leak_scan": leaks,
        "safety": {
            "report_only": True,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "network_call_executed": False,
            "ocr_execution": False,
            "model_call_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
            "raw_source_url_emitted": False,
            "raw_local_path_emitted": False,
        },
        "stop_reason": "none" if not failed_checks else "safety_scan_failed",
        "wait_reason": (
            "still-blocked event identity rows now have lane-specific recovery work orders; all mutation gates remain closed"
            if not failed_checks
            else "output safety scan failed"
        ),
        "next_resume_cursor": display_path(paths["source_date_context_recovery_jsonl"])
        if lane_rows["source_date_context_recovery"]
        else display_path(paths["event_date_or_source_year_recovery_jsonl"])
        if lane_rows["event_date_or_source_year_recovery"]
        else display_path(paths["venue_alias_lineage_jsonl"]),
    }

    write_jsonl(paths["review_rows_jsonl"], rows)
    write_jsonl(paths["source_date_context_recovery_jsonl"], lane_rows["source_date_context_recovery"])
    write_jsonl(paths["event_date_or_source_year_recovery_jsonl"], lane_rows["event_date_or_source_year_recovery"])
    write_jsonl(paths["same_date_cluster_tiebreak_jsonl"], lane_rows["same_date_cluster_tiebreak_review"])
    write_jsonl(paths["venue_alias_lineage_jsonl"], lane_rows["venue_alias_lineage_review"])
    write_jsonl(paths["multi_venue_split_jsonl"], lane_rows["multi_venue_split_review"])
    write_jsonl(paths["low_title_similarity_jsonl"], lane_rows["low_title_similarity_manual_review"])
    write_jsonl(paths["source_account_batches_jsonl"], batches)
    write_json(paths["summary_json"], summary)
    write_text(paths["summary_md"], render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_blocked_identity_review_packet(args.input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if summary["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
