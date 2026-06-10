#!/usr/bin/env python3
"""Build a report-only midnight-boundary correction packet for overnight Q6 rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_overnight_span_review_q6_20260526"
    / "overnight_span_readback_candidate_report_only.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_overnight_midnight_correction_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_OVERNIGHT_MIDNIGHT_CORRECTION_20260526.md"
DEFAULT_MANUAL_NOTE = "实际上应该是今天半夜"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_overnight_midnight_correction.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
OVERNIGHT_RE = re.compile(r"跨年|countdown|new\s*year|迎新年|半夜", re.I)


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
        raise ValueError(f"{label} must not point to D: for midnight correction: {path}")


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


def list_strings(value: Any, limit: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


def parse_iso_date(value: Any) -> date | None:
    text = compact(value, 32)
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


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


def segment_dates(row: dict[str, Any]) -> list[date]:
    parsed = [
        parse_iso_date(segment.get("selected_date_report_only"))
        for segment in row.get("selected_date_segments_report_only", [])
        if isinstance(segment, dict)
    ]
    return sorted(item for item in parsed if item)


def adjacent_year_boundary(dates: list[date]) -> bool:
    return any((right - left).days == 1 and left.year != right.year for left, right in zip(dates, dates[1:]))


def normalized_boundary(row: dict[str, Any]) -> dict[str, Any]:
    dates = segment_dates(row)
    start = dates[0].isoformat() if dates else ""
    boundary = dates[1].isoformat() if len(dates) > 1 else ""
    return {
        "date_model_report_only": "single_overnight_event_midnight_boundary",
        "start_date_report_only": start,
        "midnight_boundary_date_report_only": boundary,
        "midnight_boundary_time_report_only": "00:00",
        "venue_local_timezone_assumption_report_only": "Asia/Shanghai",
        "normalized_boundary_label_report_only": f"{start}_to_{boundary}_midnight" if start and boundary else "",
        "relative_text_interpretation_report_only": "user_today_midnight_in_article_context_not_runtime_date",
        "runtime_date_not_used_as_event_date": True,
    }


def row_blockers(row: dict[str, Any], manual_note: str) -> list[str]:
    blockers: list[str] = []
    dates = segment_dates(row)
    title_blob = " ".join([compact(row.get("title"), 600), compact(row.get("name"), 300), compact(manual_note, 200)])
    if compact(row.get("review_status")) != "overnight_span_split_readback_candidate_report_only":
        blockers.append("upstream_not_span_readback_candidate")
    if len(dates) != 2:
        blockers.append("expected_two_adjacent_boundary_dates")
    if len(set(dates)) != len(dates):
        blockers.append("duplicate_boundary_dates")
    if not adjacent_year_boundary(dates):
        blockers.append("not_adjacent_year_boundary")
    if not OVERNIGHT_RE.search(title_blob):
        blockers.append("overnight_or_midnight_signal_missing")
    if not compact(manual_note):
        blockers.append("manual_correction_note_missing")
    if not list_strings(row.get("selected_event_ids_report_only"), 180):
        blockers.append("selected_event_ids_missing")
    return sorted(set(blockers))


def build_correction_row(row: dict[str, Any], generated_at: str, manual_note: str) -> dict[str, Any]:
    blockers = row_blockers(row, manual_note)
    status = (
        "overnight_midnight_boundary_candidate_report_only"
        if not blockers
        else "overnight_midnight_boundary_blocked_report_only"
    )
    boundary = normalized_boundary(row)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "overnight_midnight_correction_id": stable_id(
            "overnightmidnight",
            [row.get("overnight_span_review_id"), row.get("article_uid"), manual_note, boundary],
        ),
        "upstream_overnight_span_review_id": compact(row.get("overnight_span_review_id"), 180),
        "upstream_source_date_context_review_id": compact(row.get("upstream_source_date_context_review_id"), 180),
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
        "human_correction_text_report_only": compact(manual_note, 240),
        "human_correction_interpretation_report_only": (
            "manual correction says the event should be modeled as the article-context midnight boundary, "
            "not as two separate activity dates"
        ),
        "previous_span_split_status_report_only": "superseded_to_upstream_evidence_by_manual_midnight_correction",
        "supersedes_prior_two_segment_interpretation_report_only": not blockers,
        "midnight_boundary_candidate_report_only": not blockers,
        "requires_db_readback_before_write": True,
        "requires_source_raw_target_db_provenance": True,
        "requires_time_source_evidence_before_public_display": True,
        "selected_event_ids_report_only": list_strings(row.get("selected_event_ids_report_only"), 180),
        "selected_cluster_ids_report_only": list_strings(row.get("selected_cluster_ids_report_only"), 180),
        "prior_selected_dates_report_only": list_strings(row.get("selected_dates_report_only"), 80),
        "normalized_boundary_report_only": boundary,
        "source_date_segments_upstream_evidence_report_only": row.get("selected_date_segments_report_only", []),
        "next_required_gates": [
            "db_backed_midnight_boundary_readback_gate",
            "manual_date_context_acceptance_gate",
            "source_raw_target_db_provenance_gate",
            "rollback_and_postwrite_readback_contract",
        ],
        "llm_audit_judgment": "report_only_manual_midnight_correction; not accepted graph facts and not a write approval",
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
            "# Manual Participant Overnight Midnight Correction Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Input correction rows: `{counts['input_overnight_span_candidate_rows']}`",
            f"- Midnight boundary candidates: `{counts['midnight_boundary_candidate_rows']}`",
            f"- Blocked rows: `{counts['midnight_boundary_blocked_rows']}`",
            f"- Superseded split rows: `{counts['superseded_prior_split_rows']}`",
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
            "# Atlas T6 Manual Participant Overnight Midnight Correction",
            "",
            f"Generated: `{summary['generated_at']}`",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Input/candidate/blocked rows: `{counts['input_overnight_span_candidate_rows']}/{counts['midnight_boundary_candidate_rows']}/{counts['midnight_boundary_blocked_rows']}`",
            f"- Superseded prior split rows / unique events: `{counts['superseded_prior_split_rows']}/{counts['unique_selected_event_ids']}`",
            f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
            "",
            "## LLM Audit",
            "",
            "- User correction says the OIL Countdown to 2020 row should be treated as the article-context midnight boundary, not as two separate activity dates.",
            "- Normalized concrete boundary is `2019-12-31` crossing to `2020-01-01 00:00` in venue-local China time; the runtime date is not used as an event date.",
            "- The previous overnight/span split packet is retained only as upstream segment evidence and is superseded by this manual-midnight correction for the next readback gate.",
            "- This packet does not accept graph facts and does not permit source/raw DB, serving, graph, vector, public, or memory writes.",
            "",
            "## Boundary",
            "",
            "- Report-only correction over existing redacted JSONL artifacts plus current-thread user correction.",
            "- No source/raw Atlas DB open or mutation, serving SQLite open/write/rebuild, OCR execution, model call, network fetch, graph fact acceptance, Neo4j/Qdrant/SQLite production write, public pointer, CloudRun/VPS deploy, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "",
            "## Next Cursor",
            "",
            f"Use `{summary['next_resume_cursor']}` for a separate DB-backed midnight-boundary readback gate. Keep all writes closed until explicit source/raw target DB provenance, rollback, and postwrite evidence exist.",
            "",
        ]
    )


def build_packet(input_path: Path, out_dir: Path, report_path: Path, manual_note: str) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()
    input_rows = read_jsonl(input_path)
    rows = [build_correction_row(row, generated_at, manual_note) for row in input_rows]
    rows.sort(key=lambda item: (item["source_account"], item["article_uid"], item["overnight_midnight_correction_id"]))
    candidates = [row for row in rows if row["midnight_boundary_candidate_report_only"]]
    blocked = [row for row in rows if not row["midnight_boundary_candidate_report_only"]]
    boundary_rows = [
        {
            "overnight_midnight_correction_id": row["overnight_midnight_correction_id"],
            "source_account": row["source_account"],
            "article_uid": row["article_uid"],
            "title": row["title"],
            "selected_event_ids_report_only": row["selected_event_ids_report_only"],
            **row["normalized_boundary_report_only"],
            **closed_flags(),
        }
        for row in candidates
    ]
    by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_account[row["source_account"]].append(row)
    batches = [
        {
            "source_account": account,
            "correction_rows": len(items),
            "midnight_boundary_candidate_rows": sum(1 for item in items if item["midnight_boundary_candidate_report_only"]),
            "blocked_rows": sum(1 for item in items if not item["midnight_boundary_candidate_report_only"]),
        }
        for account, items in sorted(by_account.items())
    ]
    output_payload = {"rows": rows, "boundary_rows": boundary_rows, "batches": batches}
    leaks = scan_payload(output_payload)
    failed_checks = [key for key, value in leaks.items() if value]
    if blocked:
        failed_checks.append("blocked_rows_present")
    decision = (
        "atlas_social_manual_participant_overnight_midnight_correction_failed_safety_scan"
        if any(key in failed_checks for key in ("public_url_hits", "sensitive_key_hits", "local_path_hits"))
        else "atlas_social_manual_participant_overnight_midnight_correction_ready_report_only"
        if candidates and not blocked
        else "atlas_social_manual_participant_overnight_midnight_correction_blocked_report_only"
    )
    paths = {
        "summary_json": out_dir / "overnight_midnight_correction_summary.json",
        "summary_md": out_dir / "overnight_midnight_correction_summary.md",
        "correction_rows_jsonl": out_dir / "overnight_midnight_correction_rows.jsonl",
        "candidate_rows_jsonl": out_dir / "overnight_midnight_boundary_candidate_report_only.jsonl",
        "blocked_rows_jsonl": out_dir / "overnight_midnight_boundary_blocked_rows.jsonl",
        "boundary_rows_jsonl": out_dir / "overnight_midnight_boundary_readback_candidates.jsonl",
        "source_account_batches_jsonl": out_dir / "source_account_overnight_midnight_batches.jsonl",
        "report_md": report_path,
    }
    unique_events = sorted({event for row in candidates for event in row["selected_event_ids_report_only"]})
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {"overnight_span_readback_candidate_report_only": display_path(input_path)},
        "outputs": {key: display_path(value) for key, value in paths.items()},
        "counts": {
            "input_overnight_span_candidate_rows": len(input_rows),
            "overnight_midnight_correction_rows": len(rows),
            "midnight_boundary_candidate_rows": len(candidates),
            "midnight_boundary_blocked_rows": len(blocked),
            "superseded_prior_split_rows": sum(
                1 for row in rows if row["supersedes_prior_two_segment_interpretation_report_only"]
            ),
            "unique_selected_event_ids": len(unique_events),
            "source_account_batches": len(batches),
            "accepted_for_graph_rows": 0,
            "source_sqlite_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "manual_correction": {
            "text_report_only": compact(manual_note, 240),
            "normalized_interpretation": "article-context midnight boundary; not runtime-date event assignment",
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
            "finding": "manual correction supersedes two-date split interpretation with a single midnight-boundary model",
            "concrete_boundary": "2019-12-31 to 2020-01-01 00:00 Asia/Shanghai",
            "active_blockers": ["db_backed_midnight_boundary_readback_gate", "source_raw_target_db_provenance_missing"],
        },
        "next_resume_cursor": display_path(paths["candidate_rows_jsonl"] if candidates else paths["blocked_rows_jsonl"]),
    }
    write_jsonl(paths["correction_rows_jsonl"], rows)
    write_jsonl(paths["candidate_rows_jsonl"], candidates)
    write_jsonl(paths["blocked_rows_jsonl"], blocked)
    write_jsonl(paths["boundary_rows_jsonl"], boundary_rows)
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
    parser.add_argument("--manual-correction-note", default=DEFAULT_MANUAL_NOTE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.input, args.out_dir, args.report, args.manual_correction_note)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if any(key in summary["failed_checks"] for key in ("public_url_hits", "sensitive_key_hits", "local_path_hits")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
