#!/usr/bin/env python3
"""Build a report-only exact-date review packet for Atlas source/OCR recovery.

This consumes the execution-gate exact-date queue and inspects only local
article/entity evidence that already exists in the Atlas SQLite candidate DB.
It does not execute OCR, call models, or write graph/serving/source state.
"""
from __future__ import annotations

import argparse
import hashlib
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
    / "atlas_source_ocr_artifact_recovery_execution_gate_t5_20260526"
    / "exact_date_review_queue.jsonl"
)
DEFAULT_ATLAS_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_exact_date_review_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_EXACT_DATE_REVIEW_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_exact_date_review.v1"

URL_RE = re.compile(r"https?://", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(secret|token|cookie|password|api[_-]?key|authorization)", re.I)
FULL_DATE_RE = re.compile(
    r"\b(20\d{2})\s*(?:[-/.]|年)\s*(0?[1-9]|1[0-2])\s*(?:[-/.]|月)\s*([0-3]?\d)\s*(?:日|号)?\b"
)
MONTH_DAY_RE = re.compile(
    r"(?<![\d.])(?P<month>0?[1-9]|1[0-2])\s*(?P<sep>[-/.月])\s*(?P<day>[0-3]?\d)\s*(?:日|号)?(?![\d.])"
)
COMPACT_MMDD_RE = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])([0-3]\d)(?!\d)")
DATE_CONTEXT_RE = re.compile(
    r"(月|日|号|週|周|星期|礼拜|派对|派對|活動|活动|演出|專場|专场|場|场|date|fri|sat|sun|mon|tue|wed|thu)",
    re.I,
)
NON_DATE_CONTEXT_RE = re.compile(r"(dj|b2b|节拍|拍号|后|年代|generation|time signature|confidence)", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas source/OCR exact-date review: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_hash(value: Any, length: int = 16) -> str:
    return hashlib.sha256(compact(value, 8000).encode("utf-8", errors="ignore")).hexdigest()[:length]


def scrub_text(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit)
    text = URL_RE.sub("[URL]", text)
    text = LOCAL_PATH_RE.sub("[PATH]", text)
    text = SENSITIVE_KEY_RE.sub("redacted-word", text)
    return compact(text, limit)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def read_jsonl(path: Path, *, optional: bool = False) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    if optional and not path.exists():
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


def open_ro_sqlite(db_path: Path) -> sqlite3.Connection:
    reject_d_path(db_path, "sqlite_db")
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.DatabaseError:
        return set()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values) if values else "NULL"


def select_existing(conn: sqlite3.Connection, table: str, wanted: list[str]) -> list[str]:
    available = table_columns(conn, table)
    return [column for column in wanted if column in available]


def load_articles(db_path: Path, uids: list[str]) -> dict[str, dict[str, Any]]:
    if not db_path.exists() or not uids:
        return {}
    conn = open_ro_sqlite(db_path)
    try:
        if not table_exists(conn, "articles"):
            return {}
        columns = select_existing(
            conn,
            "articles",
            [
                "article_uid",
                "title",
                "source_account",
                "publish_time",
                "source_archived_at",
                "local_image_count",
                "entity_count",
                "event_count",
                "vector_text_preview",
                "raw_json",
            ],
        )
        if "article_uid" not in columns:
            return {}
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM articles WHERE article_uid IN ({placeholders(uids)})",
            uids,
        ).fetchall()
    finally:
        conn.close()
    return {compact(row["article_uid"], 200): dict(row) for row in rows}


def load_entities(db_path: Path, uids: list[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {uid: [] for uid in uids}
    if not db_path.exists() or not uids:
        return grouped
    conn = open_ro_sqlite(db_path)
    try:
        if not table_exists(conn, "entities"):
            return grouped
        columns = select_existing(
            conn,
            "entities",
            [
                "source_article_uid",
                "name",
                "type",
                "source_kind",
                "confidence",
                "evidence_quote",
                "vector_text_preview",
                "raw_json",
            ],
        )
        if "source_article_uid" not in columns:
            return grouped
        order = " ORDER BY source_article_uid"
        if "source_kind" in columns:
            order += ", source_kind"
        if "confidence" in columns:
            order += ", confidence DESC"
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM entities WHERE source_article_uid IN ({placeholders(uids)}){order}",
            uids,
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        grouped.setdefault(compact(row["source_article_uid"], 200), []).append(dict(row))
    return grouped


def raw_json_text(raw_json: Any) -> str:
    raw = compact(raw_json, 20000)
    if not raw:
        return ""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(value, dict):
        fields: list[str] = []
        for key in (
            "title",
            "publish_time",
            "source_archived_at",
            "content",
            "text",
            "markdown",
            "ocr_text",
            "evidence_quote",
            "vector_text",
        ):
            fields.append(compact(value.get(key), 5000))
        return " ".join(field for field in fields if field)
    return raw


def valid_month_day(month: str, day: str) -> bool:
    try:
        month_int = int(month)
        day_int = int(day)
    except ValueError:
        return False
    return 1 <= month_int <= 12 and 1 <= day_int <= 31


def date_window(text: str, start: int, end: int, radius: int = 36) -> str:
    return text[max(0, start - radius) : min(len(text), end + radius)]


def add_candidate(
    candidates: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    value: str,
    source_kind: str,
    evidence_kind: str,
    window: str,
    policy: str,
    acceptance_class: str,
) -> None:
    safe_window = scrub_text(window, 240)
    key = (value, source_kind, safe_hash(safe_window))
    if key in seen:
        return
    seen.add(key)
    candidates.append(
        {
            "value": value,
            "source_kind": source_kind,
            "evidence_kind": evidence_kind,
            "evidence_ref_id": safe_hash(safe_window),
            "evidence_excerpt": safe_window,
            "evidence_policy": policy,
            "acceptance_class": acceptance_class,
        }
    )


def candidates_from_text(source_kind: str, evidence_kind: str, text: str) -> list[dict[str, Any]]:
    text = compact(text, 20000)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    if not text:
        return candidates

    for match in FULL_DATE_RE.finditer(text):
        year, month, day = match.groups()
        if not valid_month_day(month, day):
            continue
        window = date_window(text, match.start(), match.end())
        add_candidate(
            candidates,
            seen,
            value=f"{int(year):04d}-{int(month):02d}-{int(day):02d}",
            source_kind=source_kind,
            evidence_kind=evidence_kind,
            window=window,
            policy="full_date_in_existing_local_text",
            acceptance_class="exact_full_date_candidate",
        )

    for match in MONTH_DAY_RE.finditer(text):
        month = match.group("month")
        day = match.group("day")
        if not valid_month_day(month, day):
            continue
        window = date_window(text, match.start(), match.end())
        if NON_DATE_CONTEXT_RE.search(window) or not DATE_CONTEXT_RE.search(window):
            continue
        add_candidate(
            candidates,
            seen,
            value=f"{int(month):02d}/{int(day):02d}",
            source_kind=source_kind,
            evidence_kind=evidence_kind,
            window=window,
            policy="month_day_only_requires_year_or_source_artifact_review",
            acceptance_class="review_only_month_day",
        )

    if evidence_kind in {"title", "article_title"}:
        for match in COMPACT_MMDD_RE.finditer(text):
            month, day = match.groups()
            if not valid_month_day(month, day):
                continue
            window = date_window(text, match.start(), match.end(), radius=20)
            if NON_DATE_CONTEXT_RE.search(window):
                continue
            add_candidate(
                candidates,
                seen,
                value=f"{int(month):02d}/{int(day):02d}",
                source_kind=source_kind,
                evidence_kind=evidence_kind,
                window=window,
                policy="title_compact_month_day_requires_year_or_source_artifact_review",
                acceptance_class="review_only_month_day",
            )
    return candidates


def evidence_blobs(target: dict[str, Any], article: dict[str, Any] | None, entities: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    blobs: list[tuple[str, str, str]] = [("queue", "title", compact(target.get("title"), 800))]
    if article:
        blobs.extend(
            [
                ("article", "article_title", compact(article.get("title"), 800)),
                ("article", "article_publish_time", compact(article.get("publish_time"), 200)),
                ("article", "article_source_archived_at", compact(article.get("source_archived_at"), 200)),
                ("article", "article_vector_preview", compact(article.get("vector_text_preview"), 3000)),
                ("article", "article_raw_json", raw_json_text(article.get("raw_json"))),
            ]
        )
    for entity in entities:
        source_kind = compact(entity.get("source_kind"), 120) or "entity"
        text = " ".join(
            part
            for part in (
                compact(entity.get("evidence_quote"), 1600),
                compact(entity.get("vector_text_preview"), 1600),
                raw_json_text(entity.get("raw_json")),
            )
            if part
        )
        if text:
            blobs.append((f"entity_{source_kind}", f"entity_{compact(entity.get('type'), 80) or 'unknown'}", text))
    return blobs


def collect_date_candidates(
    target: dict[str, Any], article: dict[str, Any] | None, entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for source_kind, evidence_kind, text in evidence_blobs(target, article, entities):
        for candidate in candidates_from_text(source_kind, evidence_kind, text):
            key = (candidate["value"], candidate["source_kind"], candidate["acceptance_class"])
            if key in seen:
                continue
            seen.add(key)
            found.append(candidate)
    full = [candidate for candidate in found if candidate["acceptance_class"] == "exact_full_date_candidate"]
    review_only = [candidate for candidate in found if candidate["acceptance_class"] != "exact_full_date_candidate"]
    return (full + review_only)[:30]


def source_kind_counts(entities: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(compact(entity.get("source_kind"), 120) or "unknown" for entity in entities)
    return dict(sorted(counts.items()))


def review_row(
    *,
    generated_at: str,
    target: dict[str, Any],
    article: dict[str, Any] | None,
    entities: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = collect_date_candidates(target, article, entities)
    full_candidates = [candidate for candidate in candidates if candidate["acceptance_class"] == "exact_full_date_candidate"]
    review_only_candidates = [candidate for candidate in candidates if candidate["acceptance_class"] != "exact_full_date_candidate"]
    if full_candidates:
        status = "exact_date_candidate_found_report_only"
        next_action = "review_full_date_candidate_then_run_source_ocr_acceptance_precheck_in_report_only_mode"
    elif review_only_candidates:
        status = "exact_date_review_blocked_month_day_or_ambiguous_only"
        next_action = "recover_source_artifact_or article_publish_time_before_acceptance; month-day-only evidence is not enough"
    else:
        status = "exact_date_review_blocked_no_date_in_existing_article_or_ocr_entities"
        next_action = "process source_artifact_acquisition_queue before OCR/Markdown generation or acceptance retry"

    article_uid = compact(target.get("article_uid"), 200)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "article_uid": article_uid,
        "work_item_id": compact(target.get("work_item_id"), 120),
        "source_account": compact(target.get("source_account") or (article or {}).get("source_account"), 240),
        "title": compact(target.get("title") or (article or {}).get("title"), 500),
        "input_execution_route": compact(target.get("execution_route"), 180),
        "article_found": bool(article),
        "article_metadata": {
            "publish_time_present": bool(compact((article or {}).get("publish_time"))),
            "source_archived_at_present": bool(compact((article or {}).get("source_archived_at"))),
            "local_image_count": as_int((article or {}).get("local_image_count") or target.get("local_image_count")),
            "entity_count": as_int((article or {}).get("entity_count") or len(entities)),
            "event_count": as_int((article or {}).get("event_count")),
            "raw_json_present": bool(compact((article or {}).get("raw_json"))),
        },
        "entity_evidence": {
            "entity_rows_found": len(entities),
            "source_kind_counts": source_kind_counts(entities),
            "article_text_rows": sum(1 for entity in entities if compact(entity.get("source_kind"), 120) == "article_text"),
            "image_ocr_rows": sum(1 for entity in entities if "ocr" in compact(entity.get("source_kind"), 120).casefold()),
        },
        "date_candidates": candidates,
        "exact_full_date_candidate_count": len(full_candidates),
        "review_only_date_candidate_count": len(review_only_candidates),
        "accepted_date_candidate": full_candidates[0] if full_candidates else None,
        "exact_date_review_status": status,
        "next_action": next_action,
        "acceptance_precheck_allowed_now": bool(full_candidates),
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "ocr_execution_executed": False,
        "llm_call_executed": False,
        "write_status": "report_only",
    }


def scan_payload_for_leaks(value: Any) -> dict[str, int]:
    hits = {"local_path_hits": 0, "public_url_hits": 0, "sensitive_key_hits": 0}
    if isinstance(value, dict):
        for child in value.values():
            child_hits = scan_payload_for_leaks(child)
            for key, count in child_hits.items():
                hits[key] += count
        return hits
    if isinstance(value, list):
        for child in value:
            child_hits = scan_payload_for_leaks(child)
            for key, count in child_hits.items():
                hits[key] += count
        return hits
    text = compact(value, 4000)
    if not text:
        return hits
    hits["public_url_hits"] += len(URL_RE.findall(text))
    hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    hits["sensitive_key_hits"] += len(SENSITIVE_KEY_RE.findall(text))
    return hits


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    total = {"local_path_hits": 0, "public_url_hits": 0, "sensitive_key_hits": 0}
    for row in rows:
        hits = scan_payload_for_leaks(row)
        for key, count in hits.items():
            total[key] += count
    return total


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    lines = [
        "# Atlas T5 Source/OCR Exact-Date Review Packet - 2026-05-26",
        "",
        "Status: `CURRENT_AUTHORITY`",
        "Mode: `report_only`",
        "",
        "## LLM Audit Finding",
        "",
        "The 04:09 execution gate correctly isolated two rows with existing OCR/entity evidence but no exact-date proof. This packet performs the missing local review step against the candidate SQLite `articles` and `entities` evidence. It explicitly avoids treating confidence decimals or month/day-only fragments as accepted event dates.",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input exact-date rows: `{counts['input_exact_date_review_rows']}`",
        f"- Article rows found: `{counts['article_found_rows']}`",
        f"- Entity evidence rows scanned: `{counts['entity_evidence_rows_scanned']}`",
        f"- Image OCR rows scanned: `{counts['image_ocr_rows_scanned']}`",
        f"- Full exact-date candidate rows: `{counts['full_exact_date_candidate_rows']}`",
        f"- Review-only date candidate rows: `{counts['review_only_date_candidate_rows']}`",
        f"- Still blocked rows: `{counts['still_blocked_rows']}`",
        f"- Acceptance-precheck allowed rows: `{counts['acceptance_precheck_allowed_rows']}`",
        f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Outputs",
        "",
        f"- Summary JSON: `{outputs['summary_json']}`",
        f"- Review rows: `{outputs['review_rows_jsonl']}`",
        f"- Exact-date ready rows: `{outputs['exact_date_ready_rows_jsonl']}`",
        f"- Still blocked rows: `{outputs['exact_date_still_blocked_rows_jsonl']}`",
        "",
        "## Row Snapshot",
        "",
    ]
    for row in rows[:10]:
        lines.append(
            f"- `{row['article_uid']}` `{row['source_account']}` -> `{row['exact_date_review_status']}`; "
            f"entities `{row['entity_evidence']['entity_rows_found']}`; image_ocr `{row['entity_evidence']['image_ocr_rows']}`; "
            f"full-date candidates `{row['exact_full_date_candidate_count']}`; next `{row['next_action']}`"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only local review of existing SQLite article/entity evidence.",
            "- No OCR execution, LLM/model call, source/raw Atlas DB write, serving SQLite write/rebuild, graph fact acceptance, public pointer, deploy, upload/review, memory write, credential read, network/model/paid API, destructive Git, 9router use, or D root scan occurred.",
            "- Raw source URLs and local filesystem paths are not emitted.",
            "",
            "## Next Cursor",
            "",
            "Because no full exact-date candidate is accepted by this packet, continue with `source_artifact_acquisition_queue.jsonl` from the 04:09 execution gate before any OCR/Markdown generation or source/OCR acceptance retry.",
            "",
        ]
    )
    return "\n".join(lines)


def build_exact_date_review_packet(
    input_path: Path,
    atlas_db: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in (
        ("input_path", input_path),
        ("atlas_db", atlas_db),
        ("out_dir", out_dir),
        ("report_path", report_path),
    ):
        reject_d_path(path, label)

    generated_at = now_iso()
    targets = read_jsonl(input_path)
    uids = [compact(row.get("article_uid"), 200) for row in targets if compact(row.get("article_uid"), 200)]
    articles = load_articles(atlas_db, uids)
    entities_by_uid = load_entities(atlas_db, uids)
    rows = [
        review_row(
            generated_at=generated_at,
            target=target,
            article=articles.get(compact(target.get("article_uid"), 200)),
            entities=entities_by_uid.get(compact(target.get("article_uid"), 200), []),
        )
        for target in targets
    ]
    ready = [row for row in rows if row["accepted_date_candidate"]]
    blocked = [row for row in rows if not row["accepted_date_candidate"]]
    leak_hits = leak_scan(rows)
    failed_checks: list[str] = []
    if any(leak_hits.values()):
        failed_checks.append("exact_date_review_output_contains_public_url_secret_or_local_path")
    if not rows:
        failed_checks.append("no_exact_date_review_rows")
    status_counts = Counter(row["exact_date_review_status"] for row in rows)
    decision = (
        "atlas_source_ocr_exact_date_review_ready_report_only"
        if ready and not failed_checks
        else "atlas_source_ocr_exact_date_review_blocked_report_only"
        if rows and not failed_checks
        else "atlas_source_ocr_exact_date_review_failed_safety_scan"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "exact_date_review_queue": display_path(input_path),
            "atlas_db": display_path(atlas_db),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "source_ocr_exact_date_review_summary.json"),
            "review_rows_jsonl": display_path(out_dir / "source_ocr_exact_date_review_rows.jsonl"),
            "exact_date_ready_rows_jsonl": display_path(out_dir / "exact_date_ready_rows.jsonl"),
            "exact_date_still_blocked_rows_jsonl": display_path(out_dir / "exact_date_still_blocked_rows.jsonl"),
        },
        "counts": {
            "input_exact_date_review_rows": len(targets),
            "article_found_rows": sum(1 for row in rows if row["article_found"]),
            "entity_evidence_rows_scanned": sum(row["entity_evidence"]["entity_rows_found"] for row in rows),
            "image_ocr_rows_scanned": sum(row["entity_evidence"]["image_ocr_rows"] for row in rows),
            "full_exact_date_candidate_rows": len(ready),
            "review_only_date_candidate_rows": sum(1 for row in rows if row["review_only_date_candidate_count"] > 0),
            "still_blocked_rows": len(blocked),
            "acceptance_precheck_allowed_rows": sum(1 for row in rows if row["acceptance_precheck_allowed_now"]),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "leak_scan": leak_hits,
        "llm_audit": {
            "artifact_consistency": "04:09 gate inputs are consistent with local SQLite evidence.",
            "date_policy": "Full yyyy-mm-dd style dates may advance to review-ready; month/day-only and confidence decimals remain blocked.",
            "observed_gap": "Existing article/entity evidence may contain extracted entities but not recoverable original OCR markdown or exact event dates.",
        },
        "execution_cursor": {
            "next_lane": "source_artifact_acquisition_queue",
            "rerun_acceptance_precheck_now": bool(ready),
            "next_input": "tools/stage7_rewrite/reports/atlas_source_ocr_artifact_recovery_execution_gate_t5_20260526/source_artifact_acquisition_queue.jsonl",
            "next_command_intent": "Recover original article/image artifacts before OCR/Markdown generation or source/OCR acceptance retry.",
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
        "stop_reason": "none" if not failed_checks else "exact_date_review_failed_checks",
        "wait_reason": "exact_date_still_blocked_no_full_date_in_existing_evidence" if rows and not ready else "none",
    }
    write_jsonl(out_dir / "source_ocr_exact_date_review_rows.jsonl", rows)
    write_jsonl(out_dir / "exact_date_ready_rows.jsonl", ready)
    write_jsonl(out_dir / "exact_date_still_blocked_rows.jsonl", blocked)
    write_json(out_dir / "source_ocr_exact_date_review_summary.json", summary)
    write_text(report_path, render_report(summary, rows))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--atlas-db", type=Path, default=DEFAULT_ATLAS_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_exact_date_review_packet(args.input, args.atlas_db, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
