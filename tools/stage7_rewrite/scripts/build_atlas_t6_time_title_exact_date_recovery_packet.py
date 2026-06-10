#!/usr/bin/env python3
"""Build a report-only T6 time/title exact-date recovery packet.

This consumes the T5 time/city/venue gap-closure time-title work orders and
separates conservative date evidence from rows that still need source/OCR or
manual context. It never writes source/raw DBs, serving SQLite, graph/vector
stores, public pointers, remote services, or memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_time_city_venue_gap_closure_20260527"
    / "time_title_recovery_work_orders.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_exact_date_recovery_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_TIME_TITLE_EXACT_DATE_RECOVERY_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_time_title_exact_date_recovery.v1"

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
FULL_DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})\s*(?:年|[./-])\s*(0?[1-9]|1[0-2])\s*"
    r"(?:月|[./-])\s*(0?[1-9]|[12]\d|3[01])\s*(?:日|号)?(?!\d)"
)
MONTH_DAY_RE = re.compile(
    r"(?<![\dA-Za-z])(?P<month>0?[1-9]|1[0-2])\s*(?P<sep>[./月])\s*"
    r"(?P<day>0?[1-9]|[12]\d|3[01])\s*(?:日|号)?(?![\dA-Za-z])"
)
RANGE_RE = re.compile(
    r"\d{1,2}\s*(?:[./月])\s*\d{1,2}\s*(?:日|号)?\s*(?:-|~|至|到|—|–)\s*"
    r"(?:\d{1,2}\s*(?:[./月])?)?\d{1,2}\s*(?:日|号)?",
    re.I,
)
RELATIVE_RE = re.compile(r"(今晚|今夜|今天|今日|明晚|明天|明日|本晚|当晚)")
WEEKDAY_RE = re.compile(r"(?:本周|这周|周|星期|礼拜)\s*([一二三四五六日天1234567])")
FALSE_DATE_CONTEXT_RE = re.compile(
    r"(?:\bv\d+\.\d+\b|version|vol\.?|volume|b2b|20/20|4/4|confidence|score|"
    r"generation|年代|节拍|拍号)",
    re.I,
)
FALSE_TOKEN_RE = re.compile(r"\bv\d+\.\d+\b|20/20|4/4", re.I)

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
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL row: {exc}") from exc
            if isinstance(parsed, dict):
                rows.append(parsed)
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


def parse_post_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def make_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def context_window(text: str, start: int, end: int, radius: int = 28) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def is_range_context(text: str, start: int, end: int) -> bool:
    window = context_window(text, start, end, 18)
    return bool(RANGE_RE.search(window))


def candidate(source_kind: str, value: date, evidence_text: str, policy: str) -> dict[str, Any]:
    return {
        "source_kind": source_kind,
        "value": value.isoformat(),
        "evidence_policy": policy,
        "evidence_text": compact(evidence_text, 120),
    }


def resolve_month_day(month: int, day: int, post: date) -> date | None:
    resolved = make_date(post.year, month, day)
    if not resolved:
        return None
    if resolved < post - timedelta(days=3):
        resolved = make_date(post.year + 1, month, day)
    if not resolved:
        return None
    delta = (resolved - post).days
    if -3 <= delta <= 370:
        return resolved
    return None


def relative_candidates(text: str, post: date | None, source_kind: str) -> tuple[list[dict[str, Any]], bool]:
    found_relative = bool(RELATIVE_RE.search(text) or WEEKDAY_RE.search(text))
    if not post:
        return [], found_relative

    rows: list[dict[str, Any]] = []
    for match in RELATIVE_RE.finditer(text):
        token = match.group(1)
        if token in {"今晚", "今夜", "今天", "今日", "本晚", "当晚"}:
            rows.append(candidate(source_kind, post, token, "relative_title_token_from_post_date"))
        elif token in {"明晚", "明天", "明日"}:
            rows.append(candidate(source_kind, post + timedelta(days=1), token, "relative_title_token_from_post_date"))

    for match in WEEKDAY_RE.finditer(text):
        weekday = WEEKDAY_MAP.get(match.group(1))
        if weekday is None:
            continue
        days = (weekday - post.weekday()) % 7
        rows.append(
            candidate(
                source_kind,
                post + timedelta(days=days),
                match.group(0),
                "weekday_title_token_from_post_date",
            )
        )
    return rows, found_relative


def extract_date_evidence(row: dict[str, Any]) -> dict[str, Any]:
    post = parse_post_date(row.get("post_date"))
    blobs = [
        ("source_title", str(row.get("source_title") or "")),
        ("sample_event_titles", str(row.get("sample_event_titles") or "")),
        ("sample_time_texts", str(row.get("sample_time_texts") or "")),
    ]

    full: list[dict[str, Any]] = []
    month_day: list[dict[str, Any]] = []
    relative: list[dict[str, Any]] = []
    false_tokens: list[str] = []
    found_relative_without_context = False
    has_range = False

    for source_kind, text in blobs:
        if not text:
            continue
        if RANGE_RE.search(text):
            has_range = True
        for false_match in FALSE_TOKEN_RE.finditer(text):
            false_tokens.append(compact(false_match.group(0), 40))

        occupied: list[tuple[int, int]] = []
        for match in FULL_DATE_RE.finditer(text):
            resolved = make_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            if not resolved:
                continue
            occupied.append(match.span())
            if is_range_context(text, match.start(), match.end()):
                has_range = True
            full.append(candidate(source_kind, resolved, match.group(0), "exact_full_date_from_title_or_time_text"))

        rel_rows, saw_relative = relative_candidates(text, post, source_kind)
        relative.extend(rel_rows)
        found_relative_without_context = found_relative_without_context or (saw_relative and post is None)

        for match in MONTH_DAY_RE.finditer(text):
            if any(start <= match.start() < end for start, end in occupied):
                continue
            window = context_window(text, match.start(), match.end(), 24)
            raw = match.group(0)
            if FALSE_DATE_CONTEXT_RE.search(window):
                false_tokens.append(compact(raw, 40))
                continue
            if is_range_context(text, match.start(), match.end()):
                has_range = True
            month = int(match.group("month"))
            day = int(match.group("day"))
            if post:
                resolved = resolve_month_day(month, day, post)
                if resolved:
                    month_day.append(
                        candidate(source_kind, resolved, raw, "month_day_title_token_resolved_from_post_date")
                    )
            else:
                month_day.append(
                    {
                        "source_kind": source_kind,
                        "value": f"{month:02d}-{day:02d}",
                        "evidence_policy": "month_day_title_token_missing_year",
                        "evidence_text": compact(raw, 120),
                    }
                )

    all_resolved = full + relative + [row for row in month_day if re.match(r"20\d{2}-", str(row.get("value", "")))]
    distinct_dates = sorted({str(item["value"]) for item in all_resolved})
    month_day_needs_year = [row for row in month_day if not re.match(r"20\d{2}-", str(row.get("value", "")))]

    if has_range:
        status = "span_or_range_review_required"
        accepted = None
        reason = "date_range_or_multi_day_span_present"
    elif len(distinct_dates) == 1:
        selected = next(item for item in all_resolved if item["value"] == distinct_dates[0])
        selected_mmdd = selected["value"][5:]
        conflicting_month_days = [
            item for item in month_day_needs_year if str(item.get("value", "")) != selected_mmdd
        ]
        if conflicting_month_days:
            status = "ambiguous_multiple_dates_review_required"
            accepted = None
            reason = "month_day_candidates_conflict_with_single_full_date"
        elif selected["evidence_policy"].startswith("exact_full_date"):
            accepted = selected
            status = "exact_date_candidate_ready_report_only"
            reason = "single_conservative_date_candidate"
        elif selected["evidence_policy"].startswith("relative") or selected["evidence_policy"].startswith("weekday"):
            accepted = selected
            status = "relative_post_date_candidate_ready_report_only"
            reason = "single_conservative_date_candidate"
        else:
            accepted = selected
            status = "month_day_with_post_date_candidate_ready_report_only"
            reason = "single_conservative_date_candidate"
    elif len(distinct_dates) > 1:
        status = "ambiguous_multiple_dates_review_required"
        accepted = None
        reason = "multiple_distinct_date_candidates_present"
    elif month_day_needs_year:
        status = "month_day_year_required"
        accepted = None
        reason = "month_day_token_without_post_date_year_context"
    elif found_relative_without_context:
        status = "relative_date_source_context_required"
        accepted = None
        reason = "relative_date_token_without_post_date_context"
    elif false_tokens:
        status = "blocked_false_or_weak_date_token"
        accepted = None
        reason = "only_false_or_weak_date_tokens_detected"
    else:
        status = "source_ocr_or_manual_date_recovery_required"
        accepted = None
        reason = "no_conservative_date_candidate_in_title_or_time_text"

    return {
        "status": status,
        "accepted_date_candidate": accepted,
        "date_candidates": full + relative + month_day,
        "false_or_weak_tokens": sorted(set(false_tokens)),
        "blocked_reason": reason,
    }


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    evidence = extract_date_evidence(row)
    accepted = evidence["accepted_date_candidate"]
    return {
        "schema_version": f"{SCHEMA_VERSION}.row",
        "source_ref_id": row.get("source_ref_id", ""),
        "source_hash_prefix": compact(row.get("source_hash_prefix"), 40),
        "source_account": compact(row.get("source_account"), 120),
        "source_title": compact(row.get("source_title"), 220),
        "post_date": compact(row.get("post_date"), 40),
        "source_selector_hash": row.get("source_selector_hash")
        or selector_hash("time_title", row.get("source_ref_id"), row.get("source_hash_prefix")),
        "recovery_selector_hash": selector_hash(
            "time_title_exact_date_recovery",
            row.get("source_ref_id"),
            row.get("source_hash_prefix"),
            evidence["status"],
            accepted.get("value") if accepted else "",
        ),
        "missing_starts_at_rows": int(row.get("missing_starts_at_rows") or 0),
        "performance_event_rows": int(row.get("performance_event_rows") or 0),
        "dj_event_rows": int(row.get("dj_event_rows") or 0),
        "time_text_rows": int(row.get("time_text_rows") or 0),
        "sample_event_titles": compact(row.get("sample_event_titles"), 320),
        "sample_time_texts": compact(row.get("sample_time_texts"), 180),
        "input_date_tokens_observed": row.get("date_tokens_observed") or [],
        "recovery_status": evidence["status"],
        "blocked_reason": evidence["blocked_reason"],
        "accepted_date_candidate": accepted,
        "candidate_event_date": accepted.get("value") if accepted else "",
        "candidate_time_precision": "date_only" if accepted else "",
        "date_candidates": evidence["date_candidates"],
        "false_or_weak_tokens": evidence["false_or_weak_tokens"],
        "readback_gate_allowed_next": bool(accepted),
        "write_gate_allowed_now": False,
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "rollback_required": bool(accepted),
        "prewrite_snapshot_required": bool(accepted),
        "postwrite_readback_required": bool(accepted),
    }


def scan_payload_for_leaks(value: Any) -> dict[str, int]:
    counts = {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0}
    if isinstance(value, dict):
        for child in value.values():
            child_hits = scan_payload_for_leaks(child)
            for key in counts:
                counts[key] += child_hits[key]
    elif isinstance(value, list):
        for child in value:
            child_hits = scan_payload_for_leaks(child)
            for key in counts:
                counts[key] += child_hits[key]
    elif isinstance(value, str):
        counts["public_url_hits"] += len(URL_RE.findall(value))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))
        counts["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(value))
    return counts


def leak_scan(rows: Iterable[dict[str, Any]], extras: Iterable[Any] = ()) -> dict[str, int]:
    counts = {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0}
    for value in list(rows) + list(extras):
        hits = scan_payload_for_leaks(value)
        for key in counts:
            counts[key] += hits[key]
    return counts


def render_report(summary: dict[str, Any]) -> str:
    c = summary["counts"]
    lines = [
        "# Atlas T6 Time-Title Exact-Date Recovery Packet - 2026-05-27",
        "",
        "## Decision",
        "",
        f"`{summary['decision']}`",
        "",
        "## Scope",
        "",
        "Report-only T6 recovery packet over the T5 time-title queue. It classifies conservative title/time-text date evidence and keeps all source/raw, serving, graph, vector, public, and memory writes disabled.",
        "",
        "## Counts",
        "",
        f"- Input work-order rows: `{c['input_work_order_rows']}`",
        f"- Candidate-ready rows: `{c['candidate_ready_rows']}`",
        f"- Exact full-date ready rows: `{c['exact_full_date_ready_rows']}`",
        f"- Relative/post-date ready rows: `{c['relative_post_date_ready_rows']}`",
        f"- Month/day with post-date ready rows: `{c['month_day_with_post_date_ready_rows']}`",
        f"- Month/day year-required rows: `{c['month_day_year_required_rows']}`",
        f"- Span/range review rows: `{c['span_or_range_review_required_rows']}`",
        f"- Relative source-context required rows: `{c['relative_date_source_context_required_rows']}`",
        f"- Ambiguous multi-date review rows: `{c['ambiguous_multiple_dates_review_required_rows']}`",
        f"- False/weak token blocked rows: `{c['blocked_false_or_weak_date_token_rows']}`",
        f"- Source/OCR/manual recovery rows: `{c['source_ocr_or_manual_date_recovery_required_rows']}`",
        "",
        "## Evidence",
        "",
        f"- Summary JSON: `{summary['outputs']['summary_json']}`",
        f"- Ready candidates: `{summary['outputs']['exact_date_candidate_ready_report_only']}`",
        f"- Month/day year-required queue: `{summary['outputs']['month_day_year_required_rows']}`",
        f"- Span/range review queue: `{summary['outputs']['span_or_range_review_required_rows']}`",
        f"- Contract: `{summary['outputs']['contract_json']}`",
        "",
        "## Boundary Truth",
        "",
        f"- Leak scan public URL / sensitive key / local path hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "- No source/raw DB, serving SQLite, graph/vector, production/public pointer, huaidj.club, CloudRun, mini-program, network/OCR/model, memory, 9router, or D-root action occurred.",
        "",
        "## Next Resume Pointer",
        "",
        f"`{summary['next_resume_pointer']}`",
        "",
    ]
    return "\n".join(lines)


def build_packet(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_root(input_path, "input")
    rows = [normalize_row(row) for row in read_jsonl(input_path)]
    ready = [row for row in rows if row["accepted_date_candidate"]]
    status_counts = Counter(row["recovery_status"] for row in rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    all_path = out_dir / "time_title_exact_date_recovery_rows.jsonl"
    ready_path = out_dir / "exact_date_candidate_ready_report_only.jsonl"
    month_day_path = out_dir / "month_day_year_required_rows.jsonl"
    span_path = out_dir / "span_or_range_review_required_rows.jsonl"
    relative_path = out_dir / "relative_date_source_context_required_rows.jsonl"
    ambiguous_path = out_dir / "ambiguous_multiple_dates_review_required_rows.jsonl"
    weak_path = out_dir / "blocked_or_weak_date_token_rows.jsonl"
    source_ocr_path = out_dir / "source_ocr_or_manual_date_recovery_required_rows.jsonl"
    contract_path = out_dir / "time_title_exact_date_recovery_contract.json"
    summary_path = out_dir / "time_title_exact_date_recovery_summary.json"

    write_jsonl(all_path, rows)
    write_jsonl(ready_path, ready)
    write_jsonl(month_day_path, [row for row in rows if row["recovery_status"] == "month_day_year_required"])
    write_jsonl(span_path, [row for row in rows if row["recovery_status"] == "span_or_range_review_required"])
    write_jsonl(relative_path, [row for row in rows if row["recovery_status"] == "relative_date_source_context_required"])
    write_jsonl(ambiguous_path, [row for row in rows if row["recovery_status"] == "ambiguous_multiple_dates_review_required"])
    write_jsonl(weak_path, [row for row in rows if row["recovery_status"] == "blocked_false_or_weak_date_token"])
    write_jsonl(
        source_ocr_path,
        [row for row in rows if row["recovery_status"] == "source_ocr_or_manual_date_recovery_required"],
    )

    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "input_work_orders": display_path(input_path),
        "readback_gate_allowed_next_rows": len(ready),
        "write_execution_allowed_now": False,
        "prewrite_snapshot_required_for_ready_rows": True,
        "rollback_required_for_ready_rows": True,
        "postwrite_readback_required_for_ready_rows": True,
        "ready_row_contract": {
            "selector": "source_ref_id + source_hash_prefix + accepted_date_candidate.value",
            "target_fields": ["event date only; starts_at write remains a later explicit gate"],
            "blocked_from_current_packet": [
                "source_raw_db_write",
                "serving_rebuild",
                "graph_write",
                "vector_write",
                "public_serving",
                "memory_write",
            ],
        },
    }
    write_json(contract_path, contract)

    leak_hits = leak_scan(rows, [contract])
    decision = "atlas_t6_time_title_exact_date_recovery_ready_report_only"
    failed_checks: list[str] = []
    if any(leak_hits.values()):
        decision = "atlas_t6_time_title_exact_date_recovery_blocked_report_only"
        failed_checks.append("leak_scan_hits_present")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "time_title_recovery_work_orders": display_path(input_path),
        },
        "counts": {
            "input_work_order_rows": len(rows),
            "candidate_ready_rows": len(ready),
            "exact_full_date_ready_rows": status_counts["exact_date_candidate_ready_report_only"],
            "relative_post_date_ready_rows": status_counts["relative_post_date_candidate_ready_report_only"],
            "month_day_with_post_date_ready_rows": status_counts["month_day_with_post_date_candidate_ready_report_only"],
            "month_day_year_required_rows": status_counts["month_day_year_required"],
            "span_or_range_review_required_rows": status_counts["span_or_range_review_required"],
            "relative_date_source_context_required_rows": status_counts["relative_date_source_context_required"],
            "ambiguous_multiple_dates_review_required_rows": status_counts["ambiguous_multiple_dates_review_required"],
            "blocked_false_or_weak_date_token_rows": status_counts["blocked_false_or_weak_date_token"],
            "source_ocr_or_manual_date_recovery_required_rows": status_counts[
                "source_ocr_or_manual_date_recovery_required"
            ],
            "write_execution_allowed_rows": 0,
            "source_raw_db_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "leak_scan": leak_hits,
        "outputs": {
            "report": display_path(report_path),
            "summary_json": display_path(summary_path),
            "contract_json": display_path(contract_path),
            "all_rows": display_path(all_path),
            "exact_date_candidate_ready_report_only": display_path(ready_path),
            "month_day_year_required_rows": display_path(month_day_path),
            "span_or_range_review_required_rows": display_path(span_path),
            "relative_date_source_context_required_rows": display_path(relative_path),
            "ambiguous_multiple_dates_review_required_rows": display_path(ambiguous_path),
            "blocked_or_weak_date_token_rows": display_path(weak_path),
            "source_ocr_or_manual_date_recovery_required_rows": display_path(source_ocr_path),
        },
        "boundary_truth": {
            "report_only": True,
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_write_or_rebuild_executed": False,
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
        "next_resume_pointer": display_path(ready_path) if ready else display_path(month_day_path),
        "next_if_write_gate_closed": display_path(span_path),
    }
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
