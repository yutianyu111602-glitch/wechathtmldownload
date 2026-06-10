#!/usr/bin/env python3
"""Build a report-only T6 year-context review packet for time-title blockers."""
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
UPSTREAM_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_year_span_recovery_20260527"
DEFAULT_INPUT = UPSTREAM_DIR / "year_span_context_review_required_rows.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_year_context_review_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_TIME_TITLE_YEAR_CONTEXT_REVIEW_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_time_title_year_context_review.v1"

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
FALSE_YEAR_CONTEXT_RE = re.compile(r"(?:since|成立于|founded|诞生于)\s*(20\d{2})", re.I)
GUIDE_OR_NEWS_RE = re.compile(r"NEWS|指南|guide|宣布|通知|合集|预告|营业时间|阵容公布|男装展|上映|签约", re.I)
CHINESE_FULL_DATE_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)?")
YEAR_DOT_DATE_RE = re.compile(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})")
DOT_YEAR_DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})")
MONTH_DAY_RE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*[./]\s*(3[01]|[12]\d|0?[1-9])(?!\d)")
CHINESE_MONTH_DAY_RE = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*月\s*(3[01]|[12]\d|0?[1-9])\s*(?:日|号)?")
EN_MONTH_RE = re.compile(
    r"(?:(\d{1,2})\s*(?:-|to|至|到|/)\s*)?(\d{1,2})\s+"
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(20\d{2})",
    re.I,
)
WEEKDAY_RE = re.compile(r"(?:周|星期|礼拜)\s*([一二三四五六日天1234567])")
EN_MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
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
MIN_CONTEXT_YEAR = 2010
MAX_CONTEXT_YEAR = 2026


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


def first_segment(row: dict[str, Any]) -> str:
    text = compact(row.get("sample_time_texts"), 1000)
    return compact(re.split(r"[,，;；]", text)[0] if text else "", 240)


def joined_text(row: dict[str, Any]) -> str:
    return " | ".join(
        compact(row.get(key), 1000)
        for key in ("source_title", "sample_event_titles", "sample_time_texts")
        if compact(row.get(key), 1000)
    )


def plausible_year(year: int) -> bool:
    return MIN_CONTEXT_YEAR <= year <= MAX_CONTEXT_YEAR


def context_years(text: str) -> list[int]:
    years = {int(match.group(1)) for match in YEAR_RE.finditer(text)}
    false_years = {int(match.group(1)) for match in FALSE_YEAR_CONTEXT_RE.finditer(text)}
    return sorted(year for year in years - false_years if plausible_year(year))


def parse_explicit_dates(text: str) -> list[date]:
    values: set[date] = set()
    for year, month, day in CHINESE_FULL_DATE_RE.findall(text):
        parsed = make_date(int(year), int(month), int(day))
        if parsed and plausible_year(parsed.year):
            values.add(parsed)
    for year, month, day in YEAR_DOT_DATE_RE.findall(text):
        parsed = make_date(int(year), int(month), int(day))
        if parsed and plausible_year(parsed.year):
            values.add(parsed)
    for month, day, year in DOT_YEAR_DATE_RE.findall(text):
        parsed = make_date(int(year), int(month), int(day))
        if parsed and plausible_year(parsed.year):
            values.add(parsed)
    for start_day, day, month_name, year in EN_MONTH_RE.findall(text):
        parsed = make_date(int(year), EN_MONTH_MAP[month_name.casefold()], int(start_day or day))
        if parsed and plausible_year(parsed.year):
            values.add(parsed)
    return sorted(values)


def parse_month_day(text: str) -> list[tuple[int, int]]:
    values: set[tuple[int, int]] = set()
    for month, day in MONTH_DAY_RE.findall(text):
        parsed = make_date(2024, int(month), int(day))
        if parsed:
            values.add((int(month), int(day)))
    for month, day in CHINESE_MONTH_DAY_RE.findall(text):
        parsed = make_date(2024, int(month), int(day))
        if parsed:
            values.add((int(month), int(day)))
    return sorted(values)


def weekday_markers(text: str) -> list[int]:
    return [WEEKDAY_MAP[match.group(1)] for match in WEEKDAY_RE.finditer(text) if match.group(1) in WEEKDAY_MAP]


def weekday_status(text: str, resolved: date) -> str:
    markers = weekday_markers(text)
    if not markers:
        return "not_present"
    if all(marker == resolved.weekday() for marker in markers):
        return "matched"
    if any(marker == resolved.weekday() for marker in markers):
        return "partially_matched"
    return "mismatch"


def is_multi_event_guide(row: dict[str, Any]) -> bool:
    title = compact(row.get("source_title"), 240)
    event_titles = [part.strip() for part in re.split(r"[,，]", compact(row.get("sample_event_titles"), 1000)) if part.strip()]
    return bool(GUIDE_OR_NEWS_RE.search(title)) and len(set(event_titles)) >= 3 and not re.search(r"店庆|anniversary", title, re.I)


def possible_weekday_years(month: int, day: int, markers: list[int]) -> list[int]:
    possible: list[int] = []
    for year in range(MIN_CONTEXT_YEAR, MAX_CONTEXT_YEAR + 1):
        parsed = make_date(year, month, day)
        if parsed and parsed.weekday() in markers:
            possible.append(year)
    return possible


def choose_candidate(row: dict[str, Any]) -> tuple[date | None, str, str, dict[str, Any]]:
    if is_multi_event_guide(row):
        return None, "multi_event_guide_or_news", "blocked", {}

    first = first_segment(row)
    title = compact(row.get("source_title"), 600)
    text = joined_text(row)

    full_first = parse_explicit_dates(first)
    if len(full_first) == 1:
        return full_first[0], "first_source_time_explicit_date_or_range_start", "date_from_first_source_time", {}
    if len(full_first) > 1:
        return None, "first_source_time_multiple_explicit_dates", "blocked", {"explicit_dates": [d.isoformat() for d in full_first]}

    full_title = parse_explicit_dates(title)
    if len(full_title) == 1:
        return full_title[0], "source_title_explicit_date_or_range_start", "date_from_source_title", {}
    if len(full_title) > 1:
        return None, "source_title_multiple_explicit_dates", "blocked", {"explicit_dates": [d.isoformat() for d in full_title]}

    years = context_years(text)
    title_md = parse_month_day(title)
    first_md = parse_month_day(first)
    all_md = parse_month_day(text)

    if len(years) == 1:
        year = years[0]
        if len(all_md) != 1:
            return None, "month_day_candidate_missing_or_multiple", "blocked", {"context_years": years, "month_days": all_md}
        for source_label, month_days in (("source_title", title_md), ("first_source_time", first_md), ("joined_text", all_md)):
            if len(month_days) != 1:
                continue
            month, day = month_days[0]
            resolved = make_date(year, month, day)
            if not resolved:
                return None, "invalid_resolved_date", "blocked", {}
            weekday = weekday_status(text, resolved)
            if weekday == "mismatch":
                return None, "weekday_mismatch", "blocked", {"candidate_event_date": resolved.isoformat()}
            policy = f"{source_label}_month_day_with_single_year_context"
            if weekday in {"matched", "partially_matched"}:
                policy += "_weekday_checked"
            return resolved, policy, "date_from_year_context", {}
        return None, "month_day_candidate_missing_or_multiple", "blocked", {"context_years": years, "month_days": all_md}

    if len(years) > 1:
        return None, "multi_year_context_review_required", "blocked", {"context_years": years, "month_days": all_md}

    markers = weekday_markers(text)
    unique_md = all_md
    if len(unique_md) == 1 and markers:
        month, day = unique_md[0]
        return (
            None,
            "weekday_year_candidate_review_required",
            "blocked",
            {"possible_years": possible_weekday_years(month, day, markers), "month_day": f"{month:02d}-{day:02d}"},
        )
    if len(unique_md) > 1:
        return None, "month_day_candidate_missing_or_multiple", "blocked", {"month_days": unique_md}
    return None, "source_artifact_required_for_year_context", "blocked", {}


def base_output_row(row: dict[str, Any]) -> dict[str, Any]:
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
        "upstream_blocked_reason": compact(row.get("blocked_reason"), 120),
        "missing_starts_at_rows": int(row.get("missing_starts_at_rows") or 0),
        "performance_event_rows": int(row.get("performance_event_rows") or 0),
        "dj_event_rows": int(row.get("dj_event_rows") or 0),
        "time_text_rows": int(row.get("time_text_rows") or 0),
        "sample_event_titles": compact(row.get("sample_event_titles"), 260),
        "sample_time_texts": compact(row.get("sample_time_texts"), 260),
        "review_lane": "year_context_review",
        "write_gate_allowed_now": False,
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
    }


def review_row(row: dict[str, Any]) -> dict[str, Any]:
    resolved, reason, precision, diagnostics = choose_candidate(row)
    out = base_output_row(row)
    if resolved:
        out.update(
            {
                "review_status": "year_context_date_candidate_ready_report_only",
                "blocked_reason": "",
                "candidate_event_date": resolved.isoformat(),
                "candidate_time_precision": precision,
                "accepted_date_candidate": {
                    "source_kind": "time_title_year_context_review",
                    "value": resolved.isoformat(),
                    "evidence_policy": reason,
                    "evidence_text": compact(
                        f"policy={reason} | date={resolved.isoformat()} | {row.get('source_title')} | {row.get('sample_time_texts')}",
                        500,
                    ),
                },
                "recovery_selector_hash": selector_hash("year_context", row.get("source_ref_id"), resolved.isoformat()),
                "readback_gate_allowed_next": True,
                "prewrite_snapshot_required": False,
                "rollback_required": False,
                "postwrite_readback_required": False,
            }
        )
    else:
        out.update(
            {
                "review_status": f"year_context_{reason}",
                "blocked_reason": reason,
                "candidate_event_date": "",
                "candidate_time_precision": "",
                "accepted_date_candidate": None,
                "diagnostics": diagnostics,
                "recovery_selector_hash": selector_hash("year_context", row.get("source_ref_id"), reason),
                "readback_gate_allowed_next": False,
            }
        )
    return out


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
            "# Atlas T6 Time-Title Year Context Review - 2026-05-27",
            "",
            "## Decision",
            "",
            f"`{summary['decision']}`",
            "",
            "## Scope",
            "",
            "Report-only review packet for time-title rows that still lack reliable year context after the first year/span pass. It only uses already-redacted local report rows and does not open or write source/raw DBs, serving SQLite, graph/vector stores, public pointers, remote services, mini-program state, or memory.",
            "",
            "## Counts",
            "",
            f"- Input / review rows: `{c['input_rows']}` / `{c['review_rows']}`",
            f"- Candidate-ready / blocked rows: `{c['candidate_ready_rows']}` / `{c['blocked_rows']}`",
            f"- Source-artifact / weekday-review / conflict-ambiguous rows: `{c['source_artifact_required_rows']}` / `{c['weekday_year_review_rows']}` / `{c['conflict_or_ambiguous_rows']}`",
            f"- Multi-event guide/news rows: `{c['multi_event_guide_or_news_rows']}`",
            f"- Missing starts_at rows covered by ready candidates: `{c['ready_missing_starts_at_rows']}`",
            f"- Source/raw write / serving rebuild / graph / public / memory allowed rows: `{c['source_raw_db_write_allowed_rows']}` / `{c['serving_rebuild_allowed_rows']}` / `{c['graph_write_allowed_rows']}` / `{c['public_serving_field_allowed_rows']}` / `{c['memory_write_allowed_rows']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{summary['outputs']['summary_json']}`",
            f"- Candidate-ready rows: `{summary['outputs']['candidate_ready_rows']}`",
            f"- Source artifact queue: `{summary['outputs']['source_artifact_required_rows']}`",
            f"- Weekday review queue: `{summary['outputs']['weekday_year_review_rows']}`",
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


def build_packet(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    rows = read_jsonl(input_path)
    review_rows = [review_row(row) for row in rows]
    ready_rows = [row for row in review_rows if row.get("readback_gate_allowed_next")]
    blocked_rows = [row for row in review_rows if not row.get("readback_gate_allowed_next")]
    source_artifact_rows = [row for row in blocked_rows if row.get("blocked_reason") == "source_artifact_required_for_year_context"]
    weekday_rows = [row for row in blocked_rows if row.get("blocked_reason") == "weekday_year_candidate_review_required"]
    conflict_rows = [
        row
        for row in blocked_rows
        if row.get("blocked_reason")
        in {
            "multi_year_context_review_required",
            "month_day_candidate_missing_or_multiple",
            "first_source_time_multiple_explicit_dates",
            "source_title_multiple_explicit_dates",
            "weekday_mismatch",
            "invalid_resolved_date",
            "multi_event_guide_or_news",
        }
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    all_path = out_dir / "year_context_review_rows.jsonl"
    ready_path = out_dir / "year_context_candidate_ready_report_only.jsonl"
    blocked_path = out_dir / "year_context_review_blocked_rows.jsonl"
    source_artifact_path = out_dir / "year_context_source_artifact_required_rows.jsonl"
    weekday_path = out_dir / "year_context_weekday_review_required_rows.jsonl"
    conflict_path = out_dir / "year_context_conflict_or_ambiguous_rows.jsonl"
    batches_path = out_dir / "source_account_year_context_batches.jsonl"
    contract_path = out_dir / "year_context_review_contract.json"
    summary_path = out_dir / "year_context_review_summary.json"

    batches = []
    for account in sorted({row["source_account"] for row in review_rows}):
        account_rows = [row for row in review_rows if row["source_account"] == account]
        batches.append(
            {
                "schema_version": f"{SCHEMA_VERSION}.source_account_batch",
                "source_account": account,
                "input_rows": len(account_rows),
                "candidate_ready_rows": sum(1 for row in account_rows if row.get("readback_gate_allowed_next")),
                "source_artifact_required_rows": sum(
                    1 for row in account_rows if row.get("blocked_reason") == "source_artifact_required_for_year_context"
                ),
                "weekday_year_review_rows": sum(
                    1 for row in account_rows if row.get("blocked_reason") == "weekday_year_candidate_review_required"
                ),
                "blocked_rows": sum(1 for row in account_rows if not row.get("readback_gate_allowed_next")),
                "candidate_event_dates": sorted(
                    {row.get("candidate_event_date", "") for row in account_rows if row.get("candidate_event_date")}
                ),
                "write_gate_allowed_now": False,
            }
        )

    write_jsonl(all_path, review_rows)
    write_jsonl(ready_path, ready_rows)
    write_jsonl(blocked_path, blocked_rows)
    write_jsonl(source_artifact_path, source_artifact_rows)
    write_jsonl(weekday_path, weekday_rows)
    write_jsonl(conflict_path, conflict_rows)
    write_jsonl(batches_path, batches)

    status_counts = Counter(row.get("blocked_reason") or row.get("review_status") for row in review_rows)
    duplicate_selectors = [
        selector for selector, count in Counter(row["recovery_selector_hash"] for row in ready_rows).items() if count > 1
    ]
    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "input": display_path(input_path),
        "readback_gate_allowed_next": bool(ready_rows),
        "readback_input": display_path(ready_path),
        "write_execution_allowed_now": False,
        "source_artifact_queue": display_path(source_artifact_path),
        "weekday_review_queue": display_path(weekday_path),
        "later_gate_requires": [
            "selected serving read-only readback for source_ref_id and missing starts_at counts",
            "explicit source/raw target DB provenance before any write",
            "prewrite row hashes and inverse rollback for every target row",
            "minimal source/raw write scope only after selector drift is zero",
            "postwrite source/raw and serving readback before graph/vector/public promotion",
        ],
    }
    leaks = leak_scan(review_rows + batches + [contract])
    failed_checks: list[str] = []
    if duplicate_selectors:
        failed_checks.append("duplicate_ready_selector_hashes")
    if any(leaks.values()):
        failed_checks.append("leak_hits_present")
    decision = "atlas_t6_time_title_year_context_review_ready_report_only"
    if not ready_rows:
        decision = "atlas_t6_time_title_year_context_review_blocked_report_only"

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {"year_span_context_review_required_rows": display_path(input_path)},
        "counts": {
            "input_rows": len(rows),
            "review_rows": len(review_rows),
            "candidate_ready_rows": len(ready_rows),
            "blocked_rows": len(blocked_rows),
            "source_artifact_required_rows": len(source_artifact_rows),
            "weekday_year_review_rows": len(weekday_rows),
            "conflict_or_ambiguous_rows": len(conflict_rows),
            "multi_event_guide_or_news_rows": status_counts["multi_event_guide_or_news"],
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
            "candidate_ready_rows": display_path(ready_path),
            "blocked_rows": display_path(blocked_path),
            "source_artifact_required_rows": display_path(source_artifact_path),
            "weekday_year_review_rows": display_path(weekday_path),
            "conflict_or_ambiguous_rows": display_path(conflict_path),
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
        "next_resume_pointer": display_path(ready_path) if ready_rows else display_path(source_artifact_path),
        "next_if_write_gate_closed": display_path(source_artifact_path),
    }
    write_json(contract_path, contract)
    write_json(summary_path, summary)
    write_text(report_path, render_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = build_packet(args.input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
