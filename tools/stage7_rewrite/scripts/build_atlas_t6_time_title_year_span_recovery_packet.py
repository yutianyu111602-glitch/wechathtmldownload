#!/usr/bin/env python3
"""Build a report-only T6 year/span recovery packet for time-title blockers."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
UPSTREAM_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_exact_date_recovery_20260527"
DEFAULT_MONTH_DAY_INPUT = UPSTREAM_DIR / "month_day_year_required_rows.jsonl"
DEFAULT_SPAN_INPUT = UPSTREAM_DIR / "span_or_range_review_required_rows.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_year_span_recovery_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_TIME_TITLE_YEAR_SPAN_RECOVERY_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_time_title_year_span_recovery.v1"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_VALUE_RE = re.compile(
    r"api[_-]?key\s*[:=]|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"pass_ticket=|openid=|token\s*[:=]|cookie\s*[:=]|password\s*[:=]",
    re.I,
)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|"
    r"/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
MONTH_DAY_VALUE_RE = re.compile(r"^(0[1-9]|1[0-2])-([0-2]\d|3[01])$")
FULL_DATE_VALUE_RE = re.compile(r"^(20\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])$")
WEEKDAY_RE = re.compile(r"(?:周|星期|礼拜)\s*([一二三四五六日天1234567])")
RANGE_HINT_RE = re.compile(r"(?:-|~|至|到|—|–|&|/)\s*(?:\d{1,2}\s*(?:日|号)?|[一二三四五六日天])")
FALSE_YEAR_CONTEXT_RE = re.compile(r"(?:since|成立于|founded|诞生于)\s*(20\d{2})", re.I)

WEEKDAY_MAP = {
    "一": 0,
    "1": 0,
    "二": 1,
    "2": 1,
    "三": 2,
    "3": 2,
    "四": 3,
    "4": 3,
    "五": 4,
    "5": 4,
    "六": 5,
    "6": 5,
    "日": 6,
    "天": 6,
    "7": 6,
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path).replace("\\", "/").casefold()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} must not be an unbounded D: root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} must not scan cold D: roots: {path}")
    if raw.startswith("/mnt/d/ddownload") or raw.startswith("/mnt/d/aidata"):
        raise ValueError(f"{label} must not scan cold D: roots: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return path.name


def compact(value: Any, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = URL_RE.sub("[redacted_url]", text)
    text = LOCAL_PATH_RE.sub("[redacted_path]", text)
    return text[:limit].strip()


def short_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def selector_hash(*parts: Any) -> str:
    return "sel:" + short_hash("|".join(str(p or "") for p in parts), 20)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_root(path, "jsonl_input")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def make_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def joined_text(row: dict[str, Any]) -> str:
    return " | ".join(
        compact(row.get(key), 1000)
        for key in ("source_title", "sample_event_titles", "sample_time_texts")
        if compact(row.get(key), 1000)
    )


def extract_years(text: str) -> list[int]:
    years = [int(match.group(1)) for match in YEAR_RE.finditer(text)]
    false_years = {int(match.group(1)) for match in FALSE_YEAR_CONTEXT_RE.finditer(text)}
    return sorted({year for year in years if year not in false_years})


def month_day_values(row: dict[str, Any]) -> list[tuple[int, int, str]]:
    values: set[tuple[int, int, str]] = set()
    for item in row.get("date_candidates") or []:
        value = compact(item.get("value"), 40)
        full = FULL_DATE_VALUE_RE.match(value)
        if full:
            values.add((int(full.group(2)), int(full.group(3)), value))
            continue
        match = MONTH_DAY_VALUE_RE.match(value)
        if match:
            values.add((int(match.group(1)), int(match.group(2)), value))
    return sorted(values)


def full_date_values(row: dict[str, Any]) -> list[date]:
    values: set[date] = set()
    for item in row.get("date_candidates") or []:
        value = compact(item.get("value"), 40)
        match = FULL_DATE_VALUE_RE.match(value)
        if not match:
            continue
        parsed = make_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if parsed:
            values.add(parsed)
    return sorted(values)


def weekday_status(text: str, resolved: date) -> str:
    markers = [WEEKDAY_MAP[m.group(1)] for m in WEEKDAY_RE.finditer(text) if m.group(1) in WEEKDAY_MAP]
    if not markers:
        return "not_present"
    if all(marker == resolved.weekday() for marker in markers):
        return "matched"
    if any(marker == resolved.weekday() for marker in markers):
        return "partially_matched"
    return "mismatch"


def evidence_text(row: dict[str, Any], resolved: date, policy: str) -> str:
    pieces = [
        f"policy={policy}",
        f"date={resolved.isoformat()}",
        compact(row.get("source_title"), 180),
        compact(row.get("sample_time_texts"), 180),
    ]
    return " | ".join(piece for piece in pieces if piece)


def base_output_row(row: dict[str, Any], lane: str) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.row",
        "generated_at": now_iso(),
        "source_ref_id": compact(row.get("source_ref_id"), 160),
        "source_hash_prefix": compact(row.get("source_hash_prefix"), 80),
        "source_account": compact(row.get("source_account"), 120),
        "source_title": compact(row.get("source_title"), 220),
        "post_date": compact(row.get("post_date"), 40),
        "source_selector_hash": compact(row.get("source_selector_hash"), 120),
        "upstream_recovery_selector_hash": compact(row.get("recovery_selector_hash"), 120),
        "upstream_recovery_status": compact(row.get("recovery_status"), 120),
        "year_span_recovery_lane": lane,
        "missing_starts_at_rows": int(row.get("missing_starts_at_rows") or 0),
        "performance_event_rows": int(row.get("performance_event_rows") or 0),
        "dj_event_rows": int(row.get("dj_event_rows") or 0),
        "time_text_rows": int(row.get("time_text_rows") or 0),
        "sample_event_titles": compact(row.get("sample_event_titles"), 260),
        "sample_time_texts": compact(row.get("sample_time_texts"), 260),
        "write_gate_allowed_now": False,
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
    }


def ready_row(row: dict[str, Any], lane: str, resolved: date, policy: str, precision: str) -> dict[str, Any]:
    out = base_output_row(row, lane)
    out.update(
        {
            "recovery_status": f"{lane}_candidate_ready_report_only",
            "candidate_event_date": resolved.isoformat(),
            "candidate_time_precision": precision,
            "accepted_date_candidate": {
                "source_kind": lane,
                "value": resolved.isoformat(),
                "evidence_policy": policy,
                "evidence_text": evidence_text(row, resolved, policy),
            },
            "recovery_selector_hash": selector_hash(lane, row.get("source_ref_id"), resolved.isoformat()),
            "readback_gate_allowed_next": True,
            "prewrite_snapshot_required": False,
            "rollback_required": False,
            "postwrite_readback_required": False,
        }
    )
    return out


def blocked_row(row: dict[str, Any], lane: str, reason: str) -> dict[str, Any]:
    out = base_output_row(row, lane)
    out.update(
        {
            "recovery_status": f"{lane}_{reason}",
            "blocked_reason": reason,
            "candidate_event_date": "",
            "candidate_time_precision": "",
            "accepted_date_candidate": None,
            "recovery_selector_hash": selector_hash(lane, row.get("source_ref_id"), reason),
            "readback_gate_allowed_next": False,
        }
    )
    return out


def resolve_month_day_row(row: dict[str, Any]) -> dict[str, Any]:
    text = joined_text(row)
    years = extract_years(text)
    month_days = month_day_values(row)
    lane = "year_month_day"
    if len(years) != 1:
        return blocked_row(row, lane, "year_context_missing_or_multiple")
    unique_md = {(month, day) for month, day, _ in month_days}
    if len(unique_md) != 1:
        return blocked_row(row, lane, "month_day_candidate_missing_or_multiple")
    month, day = next(iter(unique_md))
    resolved = make_date(years[0], month, day)
    if not resolved:
        return blocked_row(row, lane, "invalid_resolved_date")
    weekday = weekday_status(text, resolved)
    if weekday == "mismatch":
        return blocked_row(row, lane, "weekday_mismatch")
    policy = "single_year_plus_single_month_day"
    if weekday in {"matched", "partially_matched"}:
        policy += "_weekday_checked"
    return ready_row(row, lane, resolved, policy, "date_from_year_month_day_context")


def resolve_span_row(row: dict[str, Any]) -> dict[str, Any]:
    text = joined_text(row)
    years = extract_years(text)
    lane = "span_start"
    full_dates = full_date_values(row)
    unique_md = {(month, day) for month, day, _ in month_day_values(row)}
    if len(full_dates) == 1 and len(unique_md) <= 1:
        resolved = full_dates[0]
        weekday = weekday_status(text, resolved)
        if weekday == "mismatch":
            return blocked_row(row, lane, "weekday_mismatch")
        return ready_row(row, lane, resolved, "full_date_range_start", "date_range_start")
    if len(years) != 1:
        return blocked_row(row, lane, "span_year_context_missing_or_multiple")
    if len(unique_md) != 1:
        return blocked_row(row, lane, "span_split_review_required")
    month, day = next(iter(unique_md))
    resolved = make_date(years[0], month, day)
    if not resolved:
        return blocked_row(row, lane, "invalid_resolved_date")
    if not RANGE_HINT_RE.search(text):
        return blocked_row(row, lane, "range_hint_missing")
    weekday = weekday_status(text, resolved)
    if weekday == "mismatch":
        return blocked_row(row, lane, "weekday_mismatch")
    return ready_row(row, lane, resolved, "single_year_plus_single_range_start", "date_range_start")


def scan_payload_for_leaks(value: Any) -> dict[str, int]:
    counts = {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0}
    if isinstance(value, dict):
        for child in value.values():
            hits = scan_payload_for_leaks(child)
            for key in counts:
                counts[key] += hits[key]
    elif isinstance(value, list):
        for child in value:
            hits = scan_payload_for_leaks(child)
            for key in counts:
                counts[key] += hits[key]
    elif isinstance(value, str):
        counts["public_url_hits"] += len(URL_RE.findall(value))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))
        counts["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(value))
    return counts


def leak_scan(values: Iterable[Any]) -> dict[str, int]:
    counts = {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0}
    for value in values:
        hits = scan_payload_for_leaks(value)
        for key in counts:
            counts[key] += hits[key]
    return counts


def render_report(summary: dict[str, Any]) -> str:
    c = summary["counts"]
    return "\n".join(
        [
            "# Atlas T6 Time-Title Year/Span Recovery - 2026-05-27",
            "",
            "## Decision",
            "",
            f"`{summary['decision']}`",
            "",
            "## Scope",
            "",
            "Report-only recovery packet for month/day rows with explicit year context and span/range rows with a deterministic range-start date. It does not open or write source/raw DBs, serving SQLite, graph/vector stores, public pointers, remote services, mini-program state, or memory.",
            "",
            "## Counts",
            "",
            f"- Input month/day-year / span rows: `{c['input_month_day_year_rows']}` / `{c['input_span_or_range_rows']}`",
            f"- Ready rows total / year-month-day / span-start: `{c['ready_rows']}` / `{c['year_month_day_ready_rows']}` / `{c['span_start_ready_rows']}`",
            f"- Still blocked rows total / split review / year context / weekday mismatch: `{c['blocked_rows']}` / `{c['span_split_review_required_rows']}` / `{c['year_context_blocked_rows']}` / `{c['weekday_mismatch_rows']}`",
            f"- Missing starts_at rows covered by ready candidates: `{c['ready_missing_starts_at_rows']}`",
            f"- Source/raw write / serving rebuild / graph / public / memory allowed rows: `{c['source_raw_db_write_allowed_rows']}` / `{c['serving_rebuild_allowed_rows']}` / `{c['graph_write_allowed_rows']}` / `{c['public_serving_field_allowed_rows']}` / `{c['memory_write_allowed_rows']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{summary['outputs']['summary_json']}`",
            f"- Ready rows: `{summary['outputs']['ready_rows']}`",
            f"- Blocked rows: `{summary['outputs']['blocked_rows']}`",
            f"- Contract: `{summary['outputs']['contract_json']}`",
            "",
            "## Boundary Truth",
            "",
            f"- Leak scan public URL / sensitive key / local path hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
            "- No source/raw DB, serving SQLite, graph/vector, public pointer, huaidj.club, CloudRun, mini-program, network/OCR/model, memory, 9router, destructive Git, or D-root action occurred.",
            "",
            "## Next Resume Pointer",
            "",
            f"`{summary['next_resume_pointer']}`",
            "",
        ]
    )


def build_packet(month_day_input: Path, span_input: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    month_rows = read_jsonl(month_day_input)
    span_rows = read_jsonl(span_input)
    year_rows = [resolve_month_day_row(row) for row in month_rows]
    span_resolved_rows = [resolve_span_row(row) for row in span_rows]
    all_rows = year_rows + span_resolved_rows
    ready_rows = [row for row in all_rows if row.get("readback_gate_allowed_next")]
    blocked_rows = [row for row in all_rows if not row.get("readback_gate_allowed_next")]
    year_ready = [row for row in ready_rows if row["year_span_recovery_lane"] == "year_month_day"]
    span_ready = [row for row in ready_rows if row["year_span_recovery_lane"] == "span_start"]
    split_rows = [row for row in blocked_rows if row.get("blocked_reason") == "span_split_review_required"]
    review_rows = [
        row
        for row in blocked_rows
        if row.get("blocked_reason")
        in {
            "year_context_missing_or_multiple",
            "span_year_context_missing_or_multiple",
            "month_day_candidate_missing_or_multiple",
            "range_hint_missing",
        }
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    all_path = out_dir / "time_title_year_span_recovery_rows.jsonl"
    ready_path = out_dir / "time_title_year_span_recovery_ready_report_only.jsonl"
    year_ready_path = out_dir / "year_month_day_candidate_ready_report_only.jsonl"
    span_ready_path = out_dir / "span_start_candidate_ready_report_only.jsonl"
    blocked_path = out_dir / "time_title_year_span_recovery_blocked_rows.jsonl"
    split_path = out_dir / "span_split_review_required_rows.jsonl"
    review_path = out_dir / "year_span_context_review_required_rows.jsonl"
    batches_path = out_dir / "source_account_year_span_recovery_batches.jsonl"
    contract_path = out_dir / "time_title_year_span_recovery_contract.json"
    summary_path = out_dir / "time_title_year_span_recovery_summary.json"

    batches = []
    for account in sorted({row["source_account"] for row in all_rows}):
        account_rows = [row for row in all_rows if row["source_account"] == account]
        batches.append(
            {
                "schema_version": f"{SCHEMA_VERSION}.source_account_batch",
                "source_account": account,
                "input_rows": len(account_rows),
                "ready_rows": sum(1 for row in account_rows if row.get("readback_gate_allowed_next")),
                "blocked_rows": sum(1 for row in account_rows if not row.get("readback_gate_allowed_next")),
                "candidate_event_dates": sorted(
                    {row.get("candidate_event_date", "") for row in account_rows if row.get("candidate_event_date")}
                ),
                "write_gate_allowed_now": False,
            }
        )

    write_jsonl(all_path, all_rows)
    write_jsonl(ready_path, ready_rows)
    write_jsonl(year_ready_path, year_ready)
    write_jsonl(span_ready_path, span_ready)
    write_jsonl(blocked_path, blocked_rows)
    write_jsonl(split_path, split_rows)
    write_jsonl(review_path, review_rows)
    write_jsonl(batches_path, batches)

    status_counts = Counter(row.get("blocked_reason") or row.get("recovery_status") for row in all_rows)
    duplicate_selectors = [
        selector for selector, count in Counter(row["recovery_selector_hash"] for row in ready_rows).items() if count > 1
    ]
    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "month_day_input": display_path(month_day_input),
        "span_input": display_path(span_input),
        "readback_gate_allowed_next": bool(ready_rows),
        "readback_input": display_path(ready_path),
        "write_execution_allowed_now": False,
        "later_gate_requires": [
            "selected serving read-only readback for source_ref_id and missing starts_at counts",
            "explicit source/raw target DB provenance before any write",
            "prewrite row hashes and inverse rollback for every target row",
            "minimal source/raw write scope only after selector drift is zero",
            "postwrite source/raw and serving readback before graph/vector/public promotion",
        ],
    }
    leaks = leak_scan(all_rows + batches + [contract])
    failed_checks: list[str] = []
    if duplicate_selectors:
        failed_checks.append("duplicate_ready_selector_hashes")
    if any(leaks.values()):
        failed_checks.append("leak_hits_present")
    decision = "atlas_t6_time_title_year_span_recovery_ready_report_only"
    if not ready_rows:
        decision = "atlas_t6_time_title_year_span_recovery_blocked_report_only"

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "month_day_year_required_rows": display_path(month_day_input),
            "span_or_range_review_required_rows": display_path(span_input),
        },
        "counts": {
            "input_month_day_year_rows": len(month_rows),
            "input_span_or_range_rows": len(span_rows),
            "ready_rows": len(ready_rows),
            "year_month_day_ready_rows": len(year_ready),
            "span_start_ready_rows": len(span_ready),
            "blocked_rows": len(blocked_rows),
            "span_split_review_required_rows": len(split_rows),
            "year_context_blocked_rows": sum(
                status_counts[reason]
                for reason in ("year_context_missing_or_multiple", "span_year_context_missing_or_multiple")
            ),
            "weekday_mismatch_rows": status_counts["weekday_mismatch"],
            "ready_missing_starts_at_rows": sum(int(row.get("missing_starts_at_rows") or 0) for row in ready_rows),
            "duplicate_ready_selector_hashes": len(duplicate_selectors),
            "write_execution_allowed_rows": 0,
            "source_raw_db_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "status_counts": dict(sorted(status_counts.items())),
        "leak_scan": leaks,
        "outputs": {
            "report": display_path(report_path),
            "summary_json": display_path(summary_path),
            "contract_json": display_path(contract_path),
            "all_rows": display_path(all_path),
            "ready_rows": display_path(ready_path),
            "year_month_day_ready_rows": display_path(year_ready_path),
            "span_start_ready_rows": display_path(span_ready_path),
            "blocked_rows": display_path(blocked_path),
            "span_split_review_required_rows": display_path(split_path),
            "year_span_context_review_required_rows": display_path(review_path),
            "source_account_batches": display_path(batches_path),
        },
        "boundary_truth": {
            "report_only": True,
            "serving_sqlite_opened": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "cloudrun_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "network_fetch_executed": False,
            "ocr_executed": False,
            "model_call_executed": False,
            "memory_write_executed": False,
            "write_execution_allowed_now": False,
        },
        "next_resume_pointer": display_path(ready_path) if ready_rows else display_path(blocked_path),
        "next_if_write_gate_closed": display_path(split_path),
    }
    write_json(contract_path, contract)
    write_json(summary_path, summary)
    write_text(report_path, render_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month-day-input", type=Path, default=DEFAULT_MONTH_DAY_INPUT)
    parser.add_argument("--span-input", type=Path, default=DEFAULT_SPAN_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = build_packet(args.month_day_input, args.span_input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
