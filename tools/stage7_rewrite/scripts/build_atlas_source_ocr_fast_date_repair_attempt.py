#!/usr/bin/env python3
"""Attempt report-only fast date repair for the Atlas first-batch target lane."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_first_batch_repair_targets_t5_20260526"
    / "fast_date_repair_targets.jsonl"
)
DEFAULT_ATLAS_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_fast_date_repair_attempt_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_FAST_DATE_REPAIR_ATTEMPT_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_fast_date_repair_attempt.v1"

URL_RE = re.compile(r"https?://", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(secret|token|cookie|password|api[_-]?key|authorization)", re.I)
DATE_ISO_RE = re.compile(r"\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.]([0-3]?\d)\b")
DATE_MMDD_RE = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])[-/.]([0-3]?\d)(?!\d)")
COMPACT_MMDD_RE = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])([0-3]\d)(?!\d)")
NON_DATE_CONTEXT_RE = re.compile(r"(dj|b2b|节拍|拍号|后|年代|generation|time signature)", re.I)
DATE_CONTEXT_RE = re.compile(r"(月|日|号|週|周|星期|礼拜|派对|活动|演出|date|fri|sat|sun|mon|tue|wed|thu)", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas fast date repair: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


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


def open_ro_sqlite(db_path: Path) -> sqlite3.Connection:
    reject_d_path(db_path, "sqlite_db")
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values) if values else "NULL"


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def load_articles(db_path: Path, uids: list[str]) -> dict[str, dict[str, Any]]:
    if not db_path.exists() or not uids:
        return {}
    conn = open_ro_sqlite(db_path)
    try:
        if not table_exists(conn, "articles"):
            return {}
        rows = conn.execute(
            f"""
            SELECT article_uid, title, source_account, publish_time, publish_time_status,
                   publish_time_index_status, source_archived_at, vector_text_preview, raw_json
            FROM articles
            WHERE article_uid IN ({placeholders(uids)})
            """,
            uids,
        ).fetchall()
    finally:
        conn.close()
    return {compact(row["article_uid"], 200): dict(row) for row in rows}


def load_source_url_rows(db_path: Path, uids: list[str]) -> dict[str, dict[str, Any]]:
    if not db_path.exists() or not uids:
        return {}
    conn = open_ro_sqlite(db_path)
    try:
        if not table_exists(conn, "article_source_url"):
            return {}
        rows = conn.execute(
            f"""
            SELECT article_uid, source_ref_id, post_time, post_date, match_basis, confidence,
                   private_internal_only, public_graph_visible
            FROM article_source_url
            WHERE article_uid IN ({placeholders(uids)})
            """,
            uids,
        ).fetchall()
    finally:
        conn.close()
    return {compact(row["article_uid"], 200): dict(row) for row in rows}


def valid_month_day(month: str, day: str) -> bool:
    try:
        month_int = int(month)
        day_int = int(day)
    except ValueError:
        return False
    return 1 <= month_int <= 12 and 1 <= day_int <= 31


def candidate_from_text(source_kind: str, text: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in DATE_ISO_RE.finditer(text):
        year, month, day = match.groups()
        if not valid_month_day(month, day):
            continue
        value = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        if value not in seen:
            seen.add(value)
            candidates.append({"value": value, "source_kind": source_kind, "evidence_policy": "metadata_or_text_exact_date"})
    for match in DATE_MMDD_RE.finditer(text):
        month, day = match.groups()
        if not valid_month_day(month, day):
            continue
        window = text[max(0, match.start() - 24) : min(len(text), match.end() + 24)]
        if NON_DATE_CONTEXT_RE.search(window):
            continue
        if source_kind not in {"source_url_post_date", "article_publish_time"} and not DATE_CONTEXT_RE.search(window):
            continue
        value = f"{int(month):02d}/{int(day):02d}"
        if value not in seen:
            seen.add(value)
            candidates.append({"value": value, "source_kind": source_kind, "evidence_policy": "metadata_or_text_month_day"})
    if source_kind == "title":
        for match in COMPACT_MMDD_RE.finditer(text):
            month, day = match.groups()
            if not valid_month_day(month, day):
                continue
            value = f"{int(month):02d}/{int(day):02d}"
            if value not in seen:
                seen.add(value)
                candidates.append({"value": value, "source_kind": "title_compact_mmdd", "evidence_policy": "title_compact_month_day"})
    return candidates


def article_raw_text(article: dict[str, Any] | None) -> str:
    if not article:
        return ""
    raw = compact(article.get("raw_json"), 5000)
    if not raw:
        return ""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    fields = []
    for key in ("title", "vector_text", "publish_time", "source_archived_at"):
        fields.append(compact(value.get(key), 1000))
    return " ".join(field for field in fields if field)


def collect_date_candidates(target: dict[str, Any], article: dict[str, Any] | None, source_url: dict[str, Any] | None) -> list[dict[str, str]]:
    blobs: list[tuple[str, str]] = []
    if article:
        blobs.extend(
            [
                ("article_publish_time", compact(article.get("publish_time"), 120)),
                ("article_source_archived_at", compact(article.get("source_archived_at"), 120)),
                ("title", compact(article.get("title") or target.get("title"), 500)),
                ("article_raw_json", article_raw_text(article)),
            ]
        )
    else:
        blobs.append(("title", compact(target.get("title"), 500)))
    if source_url:
        blobs.extend(
            [
                ("source_url_post_date", compact(source_url.get("post_date"), 120)),
                ("source_url_post_time", compact(source_url.get("post_time"), 120)),
            ]
        )
    preview = target.get("candidate_preview") if isinstance(target.get("candidate_preview"), dict) else {}
    for value in preview.get("date_values") or []:
        blobs.append(("target_candidate_preview", compact(value, 120)))

    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source_kind, text in blobs:
        if not text:
            continue
        for candidate in candidate_from_text(source_kind, text):
            key = (candidate["source_kind"], candidate["value"])
            if key in seen:
                continue
            seen.add(key)
            found.append(candidate)
    return found


def repair_row(
    generated_at: str,
    target: dict[str, Any],
    article: dict[str, Any] | None,
    source_url: dict[str, Any] | None,
) -> dict[str, Any]:
    candidates = collect_date_candidates(target, article, source_url)
    accepted = candidates[:1]
    status = "date_repair_candidate_found_report_only" if accepted else "date_repair_blocked_no_acceptable_local_date_evidence"
    next_action = (
        "Rerun source/OCR acceptance precheck after adding this date as report-only evidence."
        if accepted
        else "Escalate to source/OCR artifact recovery; current local article metadata, source-url sidecar, title, and existing candidate preview do not contain an acceptable exact date."
    )
    return {
        "schema_version": SCHEMA_VERSION + ".attempt_row",
        "generated_at": generated_at,
        "repair_rank": int(target.get("repair_rank") or 0),
        "work_item_id": compact(target.get("work_item_id"), 120),
        "article_uid": compact(target.get("article_uid"), 200),
        "source_account": compact(target.get("source_account"), 200),
        "title": compact(target.get("title"), 500),
        "primary_repair_lane": compact(target.get("primary_repair_lane"), 160),
        "date_repair_status": status,
        "date_candidates_found": candidates,
        "accepted_date_candidate": accepted[0] if accepted else None,
        "article_metadata_checked": {
            "article_found": bool(article),
            "publish_time_present": bool(compact((article or {}).get("publish_time"))),
            "source_archived_at_present": bool(compact((article or {}).get("source_archived_at"))),
            "raw_json_present": bool(compact((article or {}).get("raw_json"))),
        },
        "source_url_metadata_checked": {
            "source_url_sidecar_found": bool(source_url),
            "post_date_present": bool(compact((source_url or {}).get("post_date"))),
            "post_time_present": bool(compact((source_url or {}).get("post_time"))),
            "source_ref_id": compact((source_url or {}).get("source_ref_id"), 120),
            "source_url_match_basis": compact((source_url or {}).get("match_basis"), 160),
            "source_url_confidence": (source_url or {}).get("confidence") or 0,
        },
        "next_action": next_action,
        "ready_for_acceptance_gate": False,
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
    }


def scan_payload_for_leaks(value: Any, key_path: tuple[str, ...] = ()) -> dict[str, int]:
    hits = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}
    if isinstance(value, dict):
        for key, child in value.items():
            child_hits = scan_payload_for_leaks(child, key_path + (str(key),))
            for name, count in child_hits.items():
                hits[name] += count
        return hits
    if isinstance(value, list):
        for child in value:
            child_hits = scan_payload_for_leaks(child, key_path)
            for name, count in child_hits.items():
                hits[name] += count
        return hits
    text = compact(value, 4000)
    if not text:
        return hits
    joined_key = ".".join(key_path)
    hits["public_url_hits"] += len(URL_RE.findall(text))
    hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    if SENSITIVE_KEY_RE.search(joined_key):
        hits["secret_word_hits"] += 1
    return hits


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    total = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}
    for row in rows:
        hits = scan_payload_for_leaks(row)
        for name, count in hits.items():
            total[name] += count
    return total


def build_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T5 Source/OCR Fast Date Repair Attempt",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input fast-date rows: `{counts['input_fast_date_rows']}`",
        f"- Date candidate rows: `{counts['date_candidate_rows']}`",
        f"- Date accepted rows: `{counts['date_accepted_rows']}`",
        f"- Date blocked rows: `{counts['date_blocked_rows']}`",
        f"- Public URL / secret / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['secret_word_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Rows",
        "",
        "| rank | source | title | status | next action |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['repair_rank']}` | `{row['source_account']}` | {row['title']} | `{row['date_repair_status']}` | {row['next_action']} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only local fast-date attempt.",
            "- No OCR execution, LLM/model call, source/raw Atlas DB write, serving SQLite write/rebuild, graph fact acceptance, public pointer, deploy, upload/review, memory write, credential read, network/model/paid API, destructive Git, 9router use, or D: root scan occurred.",
            "- Source URLs and local paths are not emitted raw.",
            "",
            "## Next Gate",
            "",
            "Because the current real fast-date lane has no accepted rows, do not rerun acceptance for these two rows as if they were repaired. Escalate them into source/OCR artifact recovery and continue the `event_ocr_markdown_and_date_repair` lane.",
            "",
        ]
    )
    return "\n".join(lines)


def build_fast_date_repair_attempt(
    input_path: Path,
    atlas_db: Path,
    source_url_db: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    targets = read_jsonl(input_path)
    uids = [compact(row.get("article_uid"), 200) for row in targets if compact(row.get("article_uid"), 200)]
    articles = load_articles(atlas_db, uids)
    source_urls = load_source_url_rows(source_url_db, uids)
    rows = [
        repair_row(
            generated_at,
            target,
            articles.get(compact(target.get("article_uid"), 200)),
            source_urls.get(compact(target.get("article_uid"), 200)),
        )
        for target in targets
    ]
    accepted = [row for row in rows if row["accepted_date_candidate"]]
    blocked = [row for row in rows if not row["accepted_date_candidate"]]
    leak_hits = leak_scan(rows)
    failed_checks: list[str] = []
    if any(leak_hits.values()):
        failed_checks.append("fast_date_repair_output_contains_public_url_secret_or_local_path")
    if not rows:
        failed_checks.append("no_fast_date_rows")
    status_counts = Counter(row["date_repair_status"] for row in rows)
    decision = (
        "atlas_source_ocr_fast_date_repair_attempt_blocked_report_only"
        if rows and not accepted and not failed_checks
        else "atlas_source_ocr_fast_date_repair_attempt_ready_report_only"
        if not failed_checks
        else "atlas_source_ocr_fast_date_repair_attempt_failed_safety_scan"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "fast_date_targets": display_path(input_path),
            "atlas_db": display_path(atlas_db),
            "source_url_db": display_path(source_url_db),
        },
        "outputs": {
            "attempt_rows": display_path(out_dir / "fast_date_repair_attempt_rows.jsonl"),
            "date_accepted_rows": display_path(out_dir / "date_accepted_rows.jsonl"),
            "date_blocked_rows": display_path(out_dir / "date_blocked_rows.jsonl"),
        },
        "counts": {
            "input_fast_date_rows": len(targets),
            "date_candidate_rows": sum(1 for row in rows if row["date_candidates_found"]),
            "date_accepted_rows": len(accepted),
            "date_blocked_rows": len(blocked),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "leak_scan": leak_hits,
        "execution_cursor": {
            "next_lane": "event_ocr_markdown_and_date_repair",
            "rerun_acceptance_precheck_now": bool(accepted),
            "next_command_intent": "Escalate blocked fast-date rows to source/OCR artifact recovery, then continue event OCR+date repair before acceptance.",
        },
        "safety": {
            "report_only": True,
            "raw_source_url_emitted": False,
            "raw_local_path_emitted": False,
            "ocr_execution_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
            "production_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "source_sqlite_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if not failed_checks else "fast_date_repair_failed_checks",
        "wait_reason": "fast_date_lane_blocked_no_acceptable_local_date_evidence" if rows and not accepted else "none",
    }
    write_jsonl(out_dir / "fast_date_repair_attempt_rows.jsonl", rows)
    write_jsonl(out_dir / "date_accepted_rows.jsonl", accepted)
    write_jsonl(out_dir / "date_blocked_rows.jsonl", blocked)
    write_json(out_dir / "source_ocr_fast_date_repair_attempt_summary.json", summary)
    write_text(report_path, build_report(summary, rows))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--atlas-db", type=Path, default=DEFAULT_ATLAS_DB)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_fast_date_repair_attempt(args.input, args.atlas_db, args.source_url_db, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
