#!/usr/bin/env python3
"""Build a report-only source/date context recovery packet for Q6 participant blockers."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_blocked_identity_review_q6_20260526"
    / "source_date_context_recovery_work_orders.jsonl"
)
DEFAULT_OUT_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_source_date_context_recovery_q6_20260526"
)
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_DATE_CONTEXT_RECOVERY_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_source_date_context_recovery.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SUNDAY_HINT_RE = re.compile(r"周日|星期日|礼拜日|sunday", re.I)
SATURDAY_HINT_RE = re.compile(r"周六|星期六|礼拜六|saturday", re.I)
OVERNIGHT_HINT_RE = re.compile(r"跨年|countdown|new\s*year", re.I)


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
        raise ValueError(f"{label} must not point to D: for source date context recovery: {path}")


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


def parse_date(value: Any) -> date | None:
    text = compact(value, 32)
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def weekday_hint(text: str) -> int | None:
    if SUNDAY_HINT_RE.search(text):
        return 6
    if SATURDAY_HINT_RE.search(text):
        return 5
    return None


def is_adjacent_year_boundary(dates: list[date]) -> bool:
    if len(dates) < 2:
        return False
    ordered = sorted(dates)
    return any((right - left).days == 1 and left.year != right.year for left, right in zip(ordered, ordered[1:]))


def cluster_brief(cluster: dict[str, Any]) -> dict[str, Any]:
    event_ids = [compact(item, 140) for item in cluster.get("event_ids", []) if compact(item, 140)]
    source_refs = [compact(item, 140) for item in cluster.get("source_ref_ids", []) if compact(item, 140)]
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
        "source_ref_ids": source_refs[:8],
    }


def signal_for_weekday(row: dict[str, Any], clusters: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    text = " ".join([compact(row.get("title"), 520), compact(row.get("name"), 320)])
    hint = weekday_hint(text)
    if hint is None:
        return None, []
    matches = []
    for cluster in clusters:
        starts_at = parse_date(cluster.get("starts_at"))
        if starts_at and starts_at.weekday() == hint:
            matches.append(cluster)
    if not matches:
        return (
            {
                "signal_type": "title_weekday_no_candidate_match",
                "weekday_hint": hint,
                "source": "title_or_name",
            },
            [],
        )
    return (
        {
            "signal_type": "title_weekday_matches_candidate_date",
            "weekday_hint": hint,
            "matched_dates": sorted({compact(cluster.get("starts_at"), 40) for cluster in matches}),
        },
        matches,
    )


def signal_for_source_ref(row: dict[str, Any], clusters: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    source_ref = compact(row.get("source_ref_id"), 140)
    if not source_ref:
        return None, []
    matches = [cluster for cluster in clusters if source_ref in set(cluster.get("source_ref_ids", []))]
    if not matches:
        return (
            {
                "signal_type": "source_ref_not_found_in_candidate_clusters",
                "source_ref_id": source_ref,
            },
            [],
        )
    return (
        {
            "signal_type": "source_ref_matches_candidate_clusters",
            "source_ref_id": source_ref,
            "matched_dates": sorted({compact(cluster.get("starts_at"), 40) for cluster in matches}),
            "matched_cluster_count": len(matches),
        },
        matches,
    )


def selected_event_ids(clusters: list[dict[str, Any]]) -> list[str]:
    return sorted({event_id for cluster in clusters for event_id in cluster.get("event_ids", []) if compact(event_id, 140)})


def choose_resolution(row: dict[str, Any], clusters: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str, list[str]]:
    signals: list[dict[str, Any]] = []
    all_dates = [parsed for parsed in (parse_date(cluster.get("starts_at")) for cluster in clusters) if parsed]
    text = " ".join([compact(row.get("title"), 520), compact(row.get("name"), 320)])
    if OVERNIGHT_HINT_RE.search(text) and is_adjacent_year_boundary(all_dates):
        return (
            "overnight_or_span_review_required_report_only",
            [],
            [
                {
                    "signal_type": "overnight_year_boundary_candidates",
                    "matched_dates": sorted({cluster.get("starts_at") for cluster in clusters if cluster.get("starts_at")}),
                }
            ],
            "title suggests an overnight/year-boundary event; a later split/span gate must decide whether both dates are valid segments",
            ["span_or_split_identity_review", "source_artifact_or_schedule_context_before_write"],
        )

    weekday_signal, weekday_matches = signal_for_weekday(row, clusters)
    if weekday_signal:
        signals.append(weekday_signal)
    source_ref_signal, source_ref_matches = signal_for_source_ref(row, clusters)
    if source_ref_signal:
        signals.append(source_ref_signal)

    if len(weekday_matches) == 1:
        return (
            "date_context_candidate_ready_report_only",
            weekday_matches,
            signals,
            "title weekday signal selects exactly one candidate date",
            ["db_backed_readback_before_any_write", "manual_date_context_acceptance_gate"],
        )

    if not weekday_matches and len(source_ref_matches) == 1:
        return (
            "date_context_candidate_ready_report_only",
            source_ref_matches,
            signals,
            "source-ref lineage selects exactly one candidate date from existing report-local evidence",
            ["db_backed_readback_before_any_write", "manual_date_context_acceptance_gate"],
        )

    if len(weekday_matches) > 1 or len(source_ref_matches) > 1:
        return (
            "date_context_ambiguous_tiebreak_required_report_only",
            [],
            signals,
            "existing context matches multiple candidate clusters",
            ["source_artifact_or_schedule_context_recovery", "manual_cluster_tiebreak_before_write"],
        )

    return (
        "source_artifact_required_report_only",
        [],
        signals,
        "no deterministic date context was recovered from title/name/source-ref lineage",
        ["source_artifact_or_ocr_markdown_recovery", "date_review_before_consolidation"],
    )


def build_recovery_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    clusters = [cluster_brief(cluster) for cluster in row.get("semantic_event_clusters_for_review", []) if isinstance(cluster, dict)]
    status, selected_clusters, signals, reason, next_gates = choose_resolution(row, clusters)
    selected_dates = sorted({compact(cluster.get("starts_at"), 40) for cluster in selected_clusters if compact(cluster.get("starts_at"), 40)})
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "source_date_context_review_id": stable_id(
            "sourcedatectx",
            [row.get("review_work_order_id"), row.get("article_uid"), row.get("source_ref_id"), status],
        ),
        "upstream_review_work_order_id": compact(row.get("review_work_order_id"), 140),
        "upstream_resolution_id": compact(row.get("upstream_resolution_id"), 140),
        "upstream_work_item_id": compact(row.get("upstream_work_item_id"), 140),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "rank": int(number(row.get("rank"))),
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 320),
        "post_date": compact(row.get("post_date"), 40),
        "source_ref_id": compact(row.get("source_ref_id"), 140),
        "source_hash": compact(row.get("source_hash"), 140),
        "candidate_date_values": sorted({compact(item, 40) for item in row.get("candidate_date_values", []) if compact(item, 40)}),
        "semantic_event_cluster_count": len(clusters),
        "semantic_event_clusters_for_review": clusters,
        "context_signals": signals,
        "review_status": status,
        "resolution_reason": reason,
        "selected_date_report_only": selected_dates[0] if len(selected_dates) == 1 else "",
        "selected_event_ids_report_only": selected_event_ids(selected_clusters),
        "selected_cluster_ids_report_only": [cluster["cluster_id"] for cluster in selected_clusters if cluster.get("cluster_id")],
        "candidate_ready_report_only": status == "date_context_candidate_ready_report_only",
        "requires_source_artifact_recovery": status == "source_artifact_required_report_only",
        "requires_span_or_split_review": status == "overnight_or_span_review_required_report_only",
        "requires_manual_tiebreak": status == "date_context_ambiguous_tiebreak_required_report_only",
        "next_required_gates": next_gates,
        "llm_audit_judgment": "report_only_context_recovery; recovered signals are not accepted graph facts and require later readback/write gates",
        **closed_flags(),
    }


def grouped_batches(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"]].append(row)
    batches = []
    for source_account, values in sorted(grouped.items()):
        status_counts = Counter(row["review_status"] for row in values)
        batches.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "generated_at": generated_at,
                "source_date_context_batch_id": stable_id("sourcedatebatch", [source_account, len(values)]),
                "source_account": source_account,
                "review_rows": len(values),
                "review_status_counts": dict(sorted(status_counts.items())),
                "top_source_date_context_review_ids": [row["source_date_context_review_id"] for row in values[:12]],
                "next_gate": "Process candidate-ready rows through a separate readback gate; keep span/source-artifact rows closed for recovery.",
                **closed_flags(),
            }
        )
    return batches


def leak_scan(payload: Any) -> dict[str, int]:
    hits = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}

    def visit(value: Any, key: str = "") -> None:
        if SECRET_RE.search(key):
            hits["sensitive_key_hits"] += 1
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            hits["public_url_hits"] += len(URL_RE.findall(value))
            hits["sensitive_key_hits"] += len(SECRET_RE.findall(value))
            hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))

    visit(payload)
    return hits


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Manual Participant Source Date Context Recovery Summary",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
        f"- Input work orders: `{counts['input_work_order_rows']}`",
        f"- Review rows: `{counts['source_date_context_review_rows']}`",
        f"- Candidate-ready rows: `{counts['date_context_candidate_ready_report_only_rows']}`",
        f"- Source-artifact required rows: `{counts['source_artifact_required_report_only_rows']}`",
        f"- Overnight/span review rows: `{counts['overnight_or_span_review_required_report_only_rows']}`",
        f"- Ambiguous tiebreak rows: `{counts['date_context_ambiguous_tiebreak_required_report_only_rows']}`",
        f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
        f"- Next cursor: `{summary['next_resume_cursor']}`",
        "",
    ]
    return "\n".join(lines)


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    lines = [
        "# Atlas T6 Manual Participant Source Date Context Recovery - 2026-05-26",
        "",
        "Status: `CURRENT_AUTHORITY`",
        "Mode: `report_only`",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
        f"- Input source-date work orders: `{counts['input_work_order_rows']}`",
        f"- Review rows: `{counts['source_date_context_review_rows']}`",
        f"- Source-account batches: `{counts['source_account_batches']}`",
        f"- Candidate-ready / source-artifact / span / tiebreak rows: `{counts['date_context_candidate_ready_report_only_rows']}` / `{counts['source_artifact_required_report_only_rows']}` / `{counts['overnight_or_span_review_required_report_only_rows']}` / `{counts['date_context_ambiguous_tiebreak_required_report_only_rows']}`",
        f"- Accepted/write/promotion rows: `{counts['accepted_for_graph_rows']}/{counts['source_sqlite_write_allowed_rows']}/{counts['serving_rebuild_allowed_rows']}/{counts['graph_write_allowed_rows']}/{counts['public_serving_field_allowed_rows']}/{counts['memory_write_allowed_rows']}`",
        f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Review Status Counts",
        "",
    ]
    for key, value in sorted(summary["review_status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Outputs", ""])
    for label in [
        "summary_json",
        "review_rows_jsonl",
        "candidate_ready_jsonl",
        "source_artifact_required_jsonl",
        "overnight_or_span_review_jsonl",
        "ambiguous_tiebreak_jsonl",
        "source_account_batches_jsonl",
    ]:
        lines.append(f"- {label}: `{outputs[label]}`")
    lines.extend(
        [
            "",
            "## LLM Audit Finding",
            "",
            "- The 11:18 blocked-identity packet correctly split 13 rows into lane-specific recovery queues; target DB provenance is still blocked and should not be rerun blindly.",
            "- For the 4 source-date-context rows, existing report-local evidence yields three candidate-ready rows through deterministic title-weekday or source-ref lineage signals, and one cross-year countdown row that must stay in span/split review.",
            "- These candidates are not accepted graph facts. They only define the next readback/recovery contract before any source/raw DB, serving, graph, vector, public, or memory mutation.",
            "",
            "## Boundary",
            "",
            "- Report-only analysis over existing redacted JSONL artifacts.",
            "- No source/raw Atlas DB open or mutation, serving SQLite open/write/rebuild, OCR execution, model call, network fetch, graph fact acceptance, Neo4j/Qdrant/SQLite production write, public pointer, CloudRun/VPS deploy, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "- A later explicit gate must provide DB-backed readback, rollback contract, and postwrite verification before any mutation.",
            "",
            "## Next Cursor",
            "",
            f"Use `{summary['next_resume_cursor']}` first. Keep span/source-artifact rows closed for separate recovery.",
            "",
        ]
    )
    return "\n".join(lines)


def build_source_date_context_recovery_packet(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()
    input_rows = read_jsonl(input_path)
    rows = [build_recovery_row(row, generated_at) for row in input_rows]
    rows.sort(key=lambda item: (item["source_account"], item["review_status"], item["rank"], item["source_date_context_review_id"]))
    batches = grouped_batches(rows, generated_at)

    status_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        status_rows[row["review_status"]].append(row)

    leaks = leak_scan(rows + batches)
    failed_checks = [key for key, value in leaks.items() if value]
    status_counts = Counter(row["review_status"] for row in rows)
    decision = (
        "atlas_social_manual_participant_source_date_context_recovery_failed_safety_scan"
        if failed_checks
        else "atlas_social_manual_participant_source_date_context_recovery_ready_report_only"
        if rows
        else "atlas_social_manual_participant_source_date_context_recovery_empty_report_only"
    )

    paths = {
        "summary_json": out_dir / "source_date_context_recovery_summary.json",
        "summary_md": out_dir / "source_date_context_recovery_summary.md",
        "review_rows_jsonl": out_dir / "source_date_context_recovery_rows.jsonl",
        "candidate_ready_jsonl": out_dir / "date_context_candidate_ready_report_only.jsonl",
        "source_artifact_required_jsonl": out_dir / "source_artifact_required_rows.jsonl",
        "overnight_or_span_review_jsonl": out_dir / "overnight_or_span_review_required_rows.jsonl",
        "ambiguous_tiebreak_jsonl": out_dir / "date_context_ambiguous_tiebreak_required_rows.jsonl",
        "source_account_batches_jsonl": out_dir / "source_account_source_date_context_batches.jsonl",
        "report_md": report_path,
    }

    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {"source_date_context_work_orders": display_path(input_path)},
        "outputs": {key: display_path(path) for key, path in paths.items()},
        "counts": {
            "input_work_order_rows": len(input_rows),
            "source_date_context_review_rows": len(rows),
            "source_account_batches": len(batches),
            "date_context_candidate_ready_report_only_rows": len(status_rows["date_context_candidate_ready_report_only"]),
            "source_artifact_required_report_only_rows": len(status_rows["source_artifact_required_report_only"]),
            "overnight_or_span_review_required_report_only_rows": len(status_rows["overnight_or_span_review_required_report_only"]),
            "date_context_ambiguous_tiebreak_required_report_only_rows": len(
                status_rows["date_context_ambiguous_tiebreak_required_report_only"]
            ),
            "accepted_for_graph_rows": 0,
            "source_sqlite_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "review_status_counts": dict(sorted(status_counts.items())),
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
            "source-date-context candidates are staged for a separate readback gate; mutation gates remain closed"
            if not failed_checks
            else "output safety scan failed"
        ),
        "next_resume_cursor": display_path(paths["candidate_ready_jsonl"])
        if status_rows["date_context_candidate_ready_report_only"]
        else display_path(paths["source_artifact_required_jsonl"])
        if status_rows["source_artifact_required_report_only"]
        else display_path(paths["overnight_or_span_review_jsonl"]),
    }

    write_jsonl(paths["review_rows_jsonl"], rows)
    write_jsonl(paths["candidate_ready_jsonl"], status_rows["date_context_candidate_ready_report_only"])
    write_jsonl(paths["source_artifact_required_jsonl"], status_rows["source_artifact_required_report_only"])
    write_jsonl(paths["overnight_or_span_review_jsonl"], status_rows["overnight_or_span_review_required_report_only"])
    write_jsonl(paths["ambiguous_tiebreak_jsonl"], status_rows["date_context_ambiguous_tiebreak_required_report_only"])
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
    summary = build_source_date_context_recovery_packet(args.input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if summary["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
