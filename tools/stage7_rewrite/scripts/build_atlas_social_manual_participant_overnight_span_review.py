#!/usr/bin/env python3
"""Build a report-only overnight/span split review packet for Q6 participant blockers."""
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
    / "atlas_social_manual_participant_source_date_context_recovery_q6_20260526"
    / "overnight_or_span_review_required_rows.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_overnight_span_review_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_SPAN_REVIEW_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_overnight_span_review.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
OVERNIGHT_RE = re.compile(r"跨年|countdown|new\s*year|迎新年", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    raw = "|".join(compact(part, 800) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for overnight/span review: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
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


def parse_iso_date(value: Any) -> date | None:
    text = compact(value, 32)
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def list_strings(value: Any, limit: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


def number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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


def cluster_segment(cluster: dict[str, Any]) -> dict[str, Any]:
    event_ids = list_strings(cluster.get("event_ids"), 180)
    source_refs = list_strings(cluster.get("source_ref_ids"), 180)
    return {
        "segment_selector_id": stable_id("overnightspanseg", [cluster.get("cluster_id"), cluster.get("starts_at"), event_ids]),
        "cluster_id": compact(cluster.get("cluster_id"), 180),
        "selected_date_report_only": compact(cluster.get("starts_at"), 40),
        "selected_event_ids_report_only": event_ids,
        "source_ref_ids": source_refs,
        "city_sample": compact(cluster.get("city_sample"), 120),
        "canonical_venue": compact(cluster.get("canonical_venue"), 160),
        "venue_name_sample": compact(cluster.get("venue_name_sample"), 180),
        "event_title_sample": compact(cluster.get("event_title_sample"), 260),
        "candidate_rows": number(cluster.get("candidate_rows")),
        "event_id_count": number(cluster.get("event_id_count")) or len(event_ids),
        "max_event_match_score": cluster.get("max_event_match_score"),
        "max_participant_count": number(cluster.get("max_participant_count")),
    }


def adjacent_year_boundary(segments: list[dict[str, Any]]) -> bool:
    dates = sorted(parse_iso_date(segment.get("selected_date_report_only")) for segment in segments)
    dates = [item for item in dates if item]
    return any((right - left).days == 1 and left.year != right.year for left, right in zip(dates, dates[1:]))


def segment_blockers(row: dict[str, Any], segments: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    title_blob = " ".join([compact(row.get("title"), 600), compact(row.get("name"), 300)])
    dates = [segment.get("selected_date_report_only") for segment in segments if segment.get("selected_date_report_only")]
    venues = {compact(segment.get("canonical_venue"), 180).casefold() for segment in segments if segment.get("canonical_venue")}
    cities = {compact(segment.get("city_sample"), 180).casefold() for segment in segments if segment.get("city_sample")}

    if compact(row.get("review_status")) != "overnight_or_span_review_required_report_only":
        blockers.append("upstream_status_not_overnight_span")
    if not OVERNIGHT_RE.search(title_blob):
        blockers.append("overnight_title_signal_missing")
    if len(segments) < 2:
        blockers.append("span_segments_less_than_two")
    if not adjacent_year_boundary(segments):
        blockers.append("segments_not_adjacent_year_boundary")
    if len(set(dates)) != len(dates):
        blockers.append("duplicate_segment_dates")
    if len(venues) > 1:
        blockers.append("conflicting_segment_venues")
    if len(cities) > 1:
        blockers.append("conflicting_segment_cities")
    for segment in segments:
        if not segment["selected_event_ids_report_only"]:
            blockers.append("segment_event_ids_missing")
        if not segment["source_ref_ids"]:
            blockers.append("segment_source_refs_missing")
    return sorted(set(blockers))


def build_review_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    clusters = [item for item in row.get("semantic_event_clusters_for_review", []) if isinstance(item, dict)]
    segments = [cluster_segment(cluster) for cluster in clusters]
    segments = sorted(segments, key=lambda item: (item["selected_date_report_only"], item["cluster_id"]))
    blockers = segment_blockers(row, segments)
    selected_dates = [segment["selected_date_report_only"] for segment in segments if segment["selected_date_report_only"]]
    selected_events = sorted({event for segment in segments for event in segment["selected_event_ids_report_only"]})
    selected_clusters = [segment["cluster_id"] for segment in segments if segment["cluster_id"]]
    status = (
        "overnight_span_split_readback_candidate_report_only"
        if not blockers
        else "overnight_span_split_blocked_report_only"
    )
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "overnight_span_review_id": stable_id(
            "overnightspan",
            [row.get("article_uid"), row.get("source_date_context_review_id"), selected_dates, selected_events],
        ),
        "upstream_source_date_context_review_id": compact(row.get("source_date_context_review_id"), 180),
        "upstream_resolution_id": compact(row.get("upstream_resolution_id"), 180),
        "upstream_review_work_order_id": compact(row.get("upstream_review_work_order_id"), 180),
        "source_account": compact(row.get("source_account"), 160),
        "article_uid": compact(row.get("article_uid"), 260),
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 260),
        "post_date": compact(row.get("post_date"), 40),
        "source_ref_id": compact(row.get("source_ref_id"), 180),
        "source_hash": compact(row.get("source_hash"), 180),
        "candidate_date_values": list_strings(row.get("candidate_date_values"), 80),
        "review_status": status,
        "review_blockers": blockers,
        "span_split_readback_candidate_report_only": not blockers,
        "requires_db_readback_before_write": True,
        "requires_source_raw_target_db_provenance": True,
        "selected_dates_report_only": selected_dates,
        "selected_event_ids_report_only": selected_events,
        "selected_cluster_ids_report_only": selected_clusters,
        "selected_date_segments_report_only": segments,
        "segment_count": len(segments),
        "resolution_reason": (
            "title and adjacent year-boundary clusters support a report-only overnight split into date segments"
            if not blockers
            else "overnight/span row still blocked by deterministic segment checks"
        ),
        "next_required_gates": [
            "db_backed_span_segment_readback_gate",
            "manual_date_context_acceptance_gate",
            "source_raw_target_db_provenance_gate",
            "rollback_and_postwrite_readback_contract",
        ],
        "llm_audit_judgment": "report_only_span_split_review; not accepted graph facts and not a write approval",
        **closed_flags(),
    }


def scan_payload(payload: Any) -> dict[str, int]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Manual Participant Overnight Span Review Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Input span rows: `{counts['input_overnight_span_rows']}`",
            f"- Review rows: `{counts['overnight_span_review_rows']}`",
            f"- Split readback candidates: `{counts['overnight_span_split_readback_candidate_rows']}`",
            f"- Blocked rows: `{counts['overnight_span_split_blocked_rows']}`",
            f"- Selected date segments: `{counts['selected_date_segment_rows']}`",
            f"- Unique selected event ids: `{counts['unique_selected_event_ids']}`",
            f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
            f"- Next cursor: `{summary['next_resume_cursor']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Overnight Span Review",
            "",
            f"Generated: `{summary['generated_at']}`",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Input/review/candidate/blocked rows: `{counts['input_overnight_span_rows']}/{counts['overnight_span_review_rows']}/{counts['overnight_span_split_readback_candidate_rows']}/{counts['overnight_span_split_blocked_rows']}`",
            f"- Selected date segments / unique events: `{counts['selected_date_segment_rows']}/{counts['unique_selected_event_ids']}`",
            f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
            "",
            "## LLM Audit",
            "",
            "- The input row is the OIL year-boundary countdown case held back by the 12:21 source-date context recovery.",
            "- Existing report-local clusters support two adjacent date segments (`2019-12-31` and `2020-01-01`) with stable event ids and source refs, so this packet can move the row to readback-candidate status.",
            "- This packet does not accept graph facts and does not permit source/raw DB, serving, graph, vector, public, or memory writes.",
            "",
            "## Boundary",
            "",
            "- Report-only analysis over existing redacted JSONL artifacts.",
            "- No source/raw Atlas DB open or mutation, serving SQLite open/write/rebuild, OCR execution, model call, network fetch, graph fact acceptance, Neo4j/Qdrant/SQLite production write, public pointer, CloudRun/VPS deploy, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "",
            "## Next Cursor",
            "",
            f"Use `{summary['next_resume_cursor']}` for a separate DB-backed span-segment readback gate. Keep all writes closed until explicit source/raw target DB provenance, rollback, and postwrite evidence exist.",
            "",
        ]
    )


def build_packet(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()
    input_rows = read_jsonl(input_path)
    rows = [build_review_row(row, generated_at) for row in input_rows]
    rows.sort(key=lambda item: (item["source_account"], item["article_uid"], item["overnight_span_review_id"]))
    candidates = [row for row in rows if row["span_split_readback_candidate_report_only"]]
    blocked = [row for row in rows if not row["span_split_readback_candidate_report_only"]]
    segment_rows = [
        {
            "overnight_span_review_id": row["overnight_span_review_id"],
            "source_account": row["source_account"],
            "article_uid": row["article_uid"],
            "title": row["title"],
            **segment,
            **closed_flags(),
        }
        for row in candidates
        for segment in row["selected_date_segments_report_only"]
    ]
    by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_account[row["source_account"]].append(row)
    batches = [
        {
            "source_account": account,
            "review_rows": len(items),
            "candidate_rows": sum(1 for item in items if item["span_split_readback_candidate_report_only"]),
            "blocked_rows": sum(1 for item in items if not item["span_split_readback_candidate_report_only"]),
            "selected_date_segment_rows": sum(len(item["selected_date_segments_report_only"]) for item in items),
        }
        for account, items in sorted(by_account.items())
    ]

    output_payload = {"rows": rows, "segments": segment_rows, "batches": batches}
    leaks = scan_payload(output_payload)
    failed_checks = [key for key, value in leaks.items() if value]
    if blocked:
        failed_checks.append("blocked_rows_present")
    decision = (
        "atlas_social_manual_participant_overnight_span_review_failed_safety_scan"
        if any(key in failed_checks for key in ("public_url_hits", "sensitive_key_hits", "local_path_hits"))
        else "atlas_social_manual_participant_overnight_span_review_candidates_ready_report_only"
        if candidates and not blocked
        else "atlas_social_manual_participant_overnight_span_review_blocked_report_only"
    )
    paths = {
        "summary_json": out_dir / "overnight_span_review_summary.json",
        "summary_md": out_dir / "overnight_span_review_summary.md",
        "review_rows_jsonl": out_dir / "overnight_span_review_rows.jsonl",
        "candidate_rows_jsonl": out_dir / "overnight_span_readback_candidate_report_only.jsonl",
        "blocked_rows_jsonl": out_dir / "overnight_span_blocked_rows.jsonl",
        "segment_rows_jsonl": out_dir / "overnight_span_date_segment_readback_candidates.jsonl",
        "source_account_batches_jsonl": out_dir / "source_account_overnight_span_batches.jsonl",
        "report_md": report_path,
    }
    unique_events = sorted({event for row in candidates for event in row["selected_event_ids_report_only"]})
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {"overnight_or_span_review_required_rows": display_path(input_path)},
        "outputs": {key: display_path(value) for key, value in paths.items()},
        "counts": {
            "input_overnight_span_rows": len(input_rows),
            "overnight_span_review_rows": len(rows),
            "overnight_span_split_readback_candidate_rows": len(candidates),
            "overnight_span_split_blocked_rows": len(blocked),
            "selected_date_segment_rows": len(segment_rows),
            "unique_selected_event_ids": len(unique_events),
            "source_account_batches": len(batches),
            "accepted_for_graph_rows": 0,
            "source_sqlite_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "leak_scan": leaks,
        "write_guards": {
            "accepted_for_graph": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "safety": {
            "report_only": True,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_rebuild_executed": False,
            "ocr_executed": False,
            "network_fetch_executed": False,
            "model_call_executed": False,
            "public_pointer_updated": False,
            "memory_write_executed": False,
            "uses_9router": False,
            "scanned_d_root": False,
        },
        "llm_audit": {
            "finding": "year-boundary row can become a report-only two-segment readback candidate, but remains non-mutating evidence",
            "active_blockers": ["db_backed_span_segment_readback_gate", "source_raw_target_db_provenance_missing"],
        },
        "next_resume_cursor": display_path(paths["candidate_rows_jsonl"] if candidates else paths["blocked_rows_jsonl"]),
    }
    write_jsonl(paths["review_rows_jsonl"], rows)
    write_jsonl(paths["candidate_rows_jsonl"], candidates)
    write_jsonl(paths["blocked_rows_jsonl"], blocked)
    write_jsonl(paths["segment_rows_jsonl"], segment_rows)
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
    summary = build_packet(args.input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if any(key in summary["failed_checks"] for key in ("public_url_hits", "sensitive_key_hits", "local_path_hits")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
