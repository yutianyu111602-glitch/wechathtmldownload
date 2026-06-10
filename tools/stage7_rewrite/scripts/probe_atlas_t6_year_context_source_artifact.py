#!/usr/bin/env python3
"""Report-only probe for T6 year-context source artifact blockers.

The input rows already failed conservative time-title year-context review. This
probe checks whether bounded local artifacts can bind those rows to source
article evidence and whether any full-date evidence is already present. It does
not execute OCR, fetch network content, call models, or write Atlas databases,
serving SQLite, graph/vector stores, public pointers, remote services, or
memory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
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
    / "atlas_t6_time_title_year_context_review_20260527"
    / "year_context_source_artifact_required_rows.jsonl"
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
DEFAULT_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018"
    / "atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_year_context_source_artifact_probe_20260527"
)
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_YEAR_CONTEXT_SOURCE_ARTIFACT_PROBE_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_year_context_source_artifact_probe.v1"

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
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
FALSE_DATE_CONTEXT_RE = re.compile(
    r"(?:\bv\d+\.\d+\b|version|vol\.?|volume|b2b|20/20|4/4|"
    r"generation|年代|节拍|拍号)",
    re.I,
)


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


def compact(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = URL_RE.sub("[redacted_url]", text)
    text = LOCAL_PATH_RE.sub("[redacted_path]", text)
    return text[:limit].strip()


def short_hash(value: Any, length: int = 16) -> str:
    return hashlib.sha256(compact(value, 4000).encode("utf-8", errors="replace")).hexdigest()[:length]


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


def open_ro_sqlite(path: Path, label: str) -> sqlite3.Connection | None:
    reject_d_root(path, label)
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def selected_columns(conn: sqlite3.Connection, table: str, wanted: list[str]) -> list[str]:
    available = columns(conn, table)
    return [column for column in wanted if column in available]


def load_table_by_account_title(db_path: Path, table: str, wanted: list[str], label: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    conn = open_ro_sqlite(db_path, label)
    if not conn:
        return {}
    try:
        if not table_exists(conn, table):
            return {}
        cols = selected_columns(conn, table, wanted)
        if "source_account" not in cols or "title" not in cols:
            return {}
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in conn.execute(f"SELECT {', '.join(cols)} FROM {table}"):
            data = dict(row)
            key = (compact(data.get("source_account"), 240).casefold(), compact(data.get("title"), 600))
            grouped[key].append(data)
        return grouped
    finally:
        conn.close()


def load_articles_map(atlas_db: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    return load_table_by_account_title(
        atlas_db,
        "articles",
        [
            "article_uid",
            "article_id",
            "source_account",
            "title",
            "publish_time",
            "publish_time_status",
            "source_archived_at",
            "local_image_count",
            "event_count",
            "entity_count",
            "vector_text_preview",
            "raw_json",
        ],
        "atlas_db",
    )


def load_source_url_map(source_url_db: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    return load_table_by_account_title(
        source_url_db,
        "article_source_url",
        [
            "source_ref_id",
            "article_uid",
            "article_id",
            "source_account",
            "title",
            "source_url",
            "post_time",
            "post_date",
            "match_basis",
            "confidence",
            "local_image_count",
            "public_graph_visible",
        ],
        "source_url_db",
    )


def placeholders(values: list[Any]) -> str:
    return ",".join("?" for _ in values) if values else "NULL"


def load_entities(atlas_db: Path, uids: list[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not uids:
        return grouped
    conn = open_ro_sqlite(atlas_db, "atlas_db")
    if not conn:
        return grouped
    try:
        if not table_exists(conn, "entities"):
            return grouped
        cols = selected_columns(
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
        if "source_article_uid" not in cols:
            return grouped
        for start in range(0, len(uids), 500):
            batch = uids[start : start + 500]
            for row in conn.execute(
                f"SELECT {', '.join(cols)} FROM entities WHERE source_article_uid IN ({placeholders(batch)})",
                batch,
            ):
                data = dict(row)
                grouped[compact(data.get("source_article_uid"), 200)].append(data)
        return grouped
    finally:
        conn.close()


def load_event_counts(atlas_db: Path, uids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    if not uids:
        return counts
    conn = open_ro_sqlite(atlas_db, "atlas_db")
    if not conn:
        return counts
    try:
        if not table_exists(conn, "events") or "source_article_uid" not in columns(conn, "events"):
            return counts
        for start in range(0, len(uids), 500):
            batch = uids[start : start + 500]
            for row in conn.execute(
                f"SELECT source_article_uid, COUNT(*) FROM events WHERE source_article_uid IN ({placeholders(batch)}) GROUP BY source_article_uid",
                batch,
            ):
                counts[compact(row[0], 200)] = int(row[1] or 0)
        return counts
    finally:
        conn.close()


def load_serving_refs(serving_db: Path, source_ref_ids: list[str]) -> set[str]:
    conn = open_ro_sqlite(serving_db, "serving_db")
    if not conn:
        return set()
    try:
        if not table_exists(conn, "evidence_ref") or "source_ref_id" not in columns(conn, "evidence_ref"):
            return set()
        found: set[str] = set()
        for start in range(0, len(source_ref_ids), 500):
            batch = source_ref_ids[start : start + 500]
            for row in conn.execute(
                f"SELECT source_ref_id FROM evidence_ref WHERE source_ref_id IN ({placeholders(batch)})",
                batch,
            ):
                found.add(compact(row[0], 160))
        return found
    finally:
        conn.close()


def raw_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value[:6000]
    try:
        return json.dumps(value, ensure_ascii=False)[:6000]
    except TypeError:
        return ""


def text_blobs(row: dict[str, Any], article: dict[str, Any] | None, source_url: dict[str, Any] | None, entities: list[dict[str, Any]]) -> list[tuple[str, str]]:
    blobs = [
        ("source_title", compact(row.get("source_title"), 1000)),
        ("sample_event_titles", compact(row.get("sample_event_titles"), 1000)),
        ("sample_time_texts", compact(row.get("sample_time_texts"), 1000)),
    ]
    if article:
        blobs.extend(
            [
                ("article_title", compact(article.get("title"), 1000)),
                ("article_publish_time", compact(article.get("publish_time"), 240)),
                ("article_source_archived_at", compact(article.get("source_archived_at"), 240)),
                ("article_vector_preview", compact(article.get("vector_text_preview"), 4000)),
                ("article_raw_json", raw_json_text(article.get("raw_json"))),
            ]
        )
    if source_url:
        blobs.extend(
            [
                ("source_url_post_date", compact(source_url.get("post_date"), 240)),
                ("source_url_post_time", compact(source_url.get("post_time"), 240)),
            ]
        )
    for entity in entities[:100]:
        kind = compact(entity.get("source_kind"), 120) or "entity"
        text = " ".join(
            part
            for part in (
                compact(entity.get("evidence_quote"), 1500),
                compact(entity.get("vector_text_preview"), 1500),
                raw_json_text(entity.get("raw_json")),
            )
            if part
        )
        if text:
            blobs.append((f"entity_{kind}", text))
    return [(kind, text) for kind, text in blobs if text]


def candidate_id(value: str, source_kind: str, window: str) -> str:
    return short_hash(f"{value}|{source_kind}|{window}", 16)


def extract_date_context(blobs: list[tuple[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[int]]:
    full_dates: list[dict[str, str]] = []
    month_days: list[dict[str, str]] = []
    years: set[int] = set()
    seen_full: set[tuple[str, str, str]] = set()
    seen_md: set[tuple[str, str, str]] = set()
    for source_kind, text in blobs:
        for match in YEAR_RE.finditer(text):
            year = int(match.group(1))
            if 1990 <= year <= 2035:
                years.add(year)
        for match in FULL_DATE_RE.finditer(text):
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if not (1990 <= year <= 2035):
                continue
            value = f"{year:04d}-{month:02d}-{day:02d}"
            window = compact(text[max(0, match.start() - 36) : min(len(text), match.end() + 36)], 160)
            key = (value, source_kind, candidate_id(value, source_kind, window))
            if key in seen_full:
                continue
            seen_full.add(key)
            full_dates.append(
                {
                    "value": value,
                    "source_kind": source_kind,
                    "evidence_ref_id": key[2],
                    "evidence_policy": "exact_full_date_from_local_source_artifact",
                }
            )
        for match in MONTH_DAY_RE.finditer(text):
            month, day = int(match.group("month")), int(match.group("day"))
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            window = text[max(0, match.start() - 24) : min(len(text), match.end() + 24)]
            if FALSE_DATE_CONTEXT_RE.search(window):
                continue
            value = f"{month:02d}/{day:02d}"
            key = (value, source_kind, candidate_id(value, source_kind, compact(window, 160)))
            if key in seen_md:
                continue
            seen_md.add(key)
            month_days.append(
                {
                    "value": value,
                    "source_kind": source_kind,
                    "evidence_ref_id": key[2],
                    "evidence_policy": "month_day_only_from_local_source_artifact",
                }
            )
    return full_dates[:20], month_days[:20], sorted(years)


def safe_source_url(source_url: dict[str, Any] | None) -> dict[str, Any]:
    if not source_url:
        return {
            "source_url_artifact_found": False,
            "source_url_sha256": "",
            "post_date_present": False,
            "post_time_present": False,
            "source_url_public_graph_visible": False,
        }
    raw_url = compact(source_url.get("source_url"), 4000)
    return {
        "source_url_artifact_found": True,
        "source_url_ref_id": compact(source_url.get("source_ref_id"), 120),
        "source_url_sha256": hashlib.sha256(raw_url.encode("utf-8", errors="ignore")).hexdigest() if raw_url else "",
        "source_url_match_basis": compact(source_url.get("match_basis"), 160),
        "source_url_confidence": source_url.get("confidence") or 0,
        "post_date_present": bool(source_url.get("post_date")),
        "post_time_present": bool(source_url.get("post_time")),
        "local_image_count": int(source_url.get("local_image_count") or 0),
        "source_url_public_graph_visible": bool(source_url.get("public_graph_visible")),
    }


def choose_binding(row: dict[str, Any], article_map: dict[tuple[str, str], list[dict[str, Any]]], source_url_map: dict[tuple[str, str], list[dict[str, Any]]]) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None, int, int]:
    key = (compact(row.get("source_account"), 240).casefold(), compact(row.get("source_title"), 600))
    article_matches = article_map.get(key, [])
    source_url_matches = source_url_map.get(key, [])
    article = article_matches[0] if len(article_matches) == 1 else None
    source_url = source_url_matches[0] if len(source_url_matches) == 1 else None
    if source_url and not article:
        uid = compact(source_url.get("article_uid"), 200)
        same_uid = [candidate for candidate in article_matches if compact(candidate.get("article_uid"), 200) == uid]
        if len(same_uid) == 1:
            article = same_uid[0]
    if article and not source_url:
        uid = compact(article.get("article_uid"), 200)
        same_uid = [candidate for candidate in source_url_matches if compact(candidate.get("article_uid"), 200) == uid]
        if len(same_uid) == 1:
            source_url = same_uid[0]
    if article and source_url:
        return "local_source_artifact_bound", article, source_url, len(article_matches), len(source_url_matches)
    if article_matches or source_url_matches:
        return "ambiguous_or_partial_local_source_artifact_binding", article, source_url, len(article_matches), len(source_url_matches)
    return "local_source_artifact_binding_missing", None, None, 0, 0


def row_status(
    *,
    serving_ref_found: bool,
    binding_status: str,
    full_dates: list[dict[str, str]],
    month_days: list[dict[str, str]],
    years: list[int],
    image_ocr_rows: int,
    source_context_rows: int,
) -> str:
    if not serving_ref_found:
        return "blocked_serving_source_ref_missing"
    if binding_status == "local_source_artifact_binding_missing":
        return "blocked_no_local_source_artifact_binding"
    if binding_status == "ambiguous_or_partial_local_source_artifact_binding":
        return "blocked_ambiguous_or_partial_source_artifact_binding"
    if len({item["value"] for item in full_dates}) == 1:
        return "candidate_full_date_present_report_only"
    if len({item["value"] for item in full_dates}) > 1:
        return "blocked_multiple_full_date_candidates"
    if month_days and years:
        return "blocked_local_year_context_manual_review_required"
    if month_days:
        return "blocked_missing_year_from_local_source_artifact"
    if not image_ocr_rows and not source_context_rows:
        return "blocked_no_ocr_or_source_context_text"
    return "blocked_no_date_evidence_in_local_source_artifact"


def build_probe_row(
    *,
    generated_at: str,
    row: dict[str, Any],
    article: dict[str, Any] | None,
    source_url: dict[str, Any] | None,
    article_match_count: int,
    source_url_match_count: int,
    binding_status: str,
    entities: list[dict[str, Any]],
    event_count: int,
    serving_ref_found: bool,
) -> dict[str, Any]:
    blobs = text_blobs(row, article, source_url, entities)
    full_dates, month_days, years = extract_date_context(blobs)
    source_kinds = sorted({compact(entity.get("source_kind"), 100) for entity in entities if compact(entity.get("source_kind"), 100)})
    image_ocr_rows = sum(1 for entity in entities if "ocr" in compact(entity.get("source_kind"), 100).casefold())
    source_context_rows = sum(
        1
        for entity in entities
        if compact(entity.get("source_kind"), 100).casefold() in {"article_text", "meta", "source_context"}
    )
    status = row_status(
        serving_ref_found=serving_ref_found,
        binding_status=binding_status,
        full_dates=full_dates,
        month_days=month_days,
        years=years,
        image_ocr_rows=image_ocr_rows,
        source_context_rows=source_context_rows,
    )
    candidate_date = ""
    precision = ""
    if status == "candidate_full_date_present_report_only":
        candidate_date = full_dates[0]["value"]
        precision = "day"
    safe_url = safe_source_url(source_url)
    local_image_count = int((article or {}).get("local_image_count") or safe_url.get("local_image_count") or 0)
    article_uid = compact((article or {}).get("article_uid") or (source_url or {}).get("article_uid"), 200)
    return {
        "schema_version": f"{SCHEMA_VERSION}.row",
        "generated_at": generated_at,
        "source_ref_id": compact(row.get("source_ref_id"), 160),
        "source_hash_prefix": compact(row.get("source_hash_prefix"), 80),
        "source_account": compact(row.get("source_account"), 240),
        "source_title": compact(row.get("source_title"), 600),
        "source_selector_hash": compact(row.get("source_selector_hash"), 120),
        "recovery_selector_hash": compact(row.get("recovery_selector_hash"), 120),
        "upstream_recovery_selector_hash": compact(row.get("upstream_recovery_selector_hash"), 120),
        "upstream_blocked_reason": compact(row.get("upstream_blocked_reason"), 160),
        "serving_evidence_ref_found": serving_ref_found,
        "binding_status": binding_status,
        "article_match_count": article_match_count,
        "source_url_match_count": source_url_match_count,
        "article_uid_ref": short_hash(article_uid) if article_uid else "",
        "source_url_evidence": safe_url,
        "source_db_article_found": bool(article),
        "source_db_event_rows_found": event_count,
        "source_entity_rows_found": len(entities),
        "source_context_entity_rows": source_context_rows,
        "image_ocr_entity_rows": image_ocr_rows,
        "local_image_count": local_image_count,
        "source_entity_kinds": source_kinds[:16],
        "full_date_candidate_count": len(full_dates),
        "full_date_candidates": full_dates,
        "month_day_candidate_count": len(month_days),
        "month_day_candidates": month_days[:8],
        "local_year_context_values": years[:12],
        "probe_status": status,
        "accepted_date_candidate": candidate_date,
        "candidate_time_precision": precision,
        "readback_gate_allowed_next": status == "candidate_full_date_present_report_only",
        "write_gate_allowed_now": False,
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
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
    hits["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(text))
    return hits


def leak_scan(rows: Iterable[Any]) -> dict[str, int]:
    total = {"local_path_hits": 0, "public_url_hits": 0, "sensitive_key_hits": 0}
    for row in rows:
        hits = scan_payload_for_leaks(row)
        for key, count in hits.items():
            total[key] += count
    return total


def source_account_batches(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"]].append(row)
    for account, account_rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        status_counts = Counter(row["probe_status"] for row in account_rows)
        batches.append(
            {
                "schema_version": f"{SCHEMA_VERSION}.source_account_batch",
                "generated_at": generated_at,
                "source_account": account,
                "source_account_ref": short_hash(account),
                "row_count": len(account_rows),
                "bound_rows": sum(1 for row in account_rows if row["binding_status"] == "local_source_artifact_bound"),
                "candidate_ready_rows": sum(1 for row in account_rows if row["readback_gate_allowed_next"]),
                "probe_status_counts": dict(sorted(status_counts.items())),
                "write_gate_allowed_now": False,
                "memory_write_allowed": False,
            }
        )
    return batches


def render_report(summary: dict[str, Any]) -> str:
    c = summary["counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T6 Year-Context Source Artifact Probe - 2026-05-27",
            "",
            "## Decision",
            "",
            f"`{summary['decision']}`",
            "",
            "## Scope",
            "",
            "Report-only probe for T6 time-title rows that still require source artifacts for year context. It binds rows to local source/article evidence where possible and keeps all write/public gates closed.",
            "",
            "## Counts",
            "",
            f"- Input / probe rows: `{c['input_rows']}` / `{c['probe_rows']}`",
            f"- Serving evidence-ref bound rows: `{c['serving_evidence_ref_bound_rows']}`",
            f"- Local source artifact bound / ambiguous-or-partial / missing rows: `{c['local_source_artifact_bound_rows']}` / `{c['ambiguous_or_partial_binding_rows']}` / `{c['missing_binding_rows']}`",
            f"- Existing local-image / image-OCR rows: `{c['local_image_rows']}` / `{c['image_ocr_rows']}`",
            f"- Full-date candidate / month-day-only / local-year-context rows: `{c['full_date_candidate_rows']}` / `{c['month_day_only_rows']}` / `{c['local_year_context_rows']}`",
            f"- Candidate-ready / still-blocked rows: `{c['candidate_ready_rows']}` / `{c['still_blocked_rows']}`",
            f"- Leak scan public URL / sensitive-key / local path hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
            "",
            "## Outputs",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- Probe rows: `{outputs['probe_rows']}`",
            f"- Candidate-ready rows: `{outputs['candidate_ready_rows']}`",
            f"- Bound but missing-year rows: `{outputs['bound_missing_year_rows']}`",
            f"- Binding-blocked rows: `{outputs['binding_blocked_rows']}`",
            f"- Manual year-review rows: `{outputs['manual_year_review_rows']}`",
            f"- Source-account batches: `{outputs['source_account_batches']}`",
            "",
            "## LLM Audit Finding",
            "",
            "Binding to a local article or source-url row is useful evidence, but it is not sufficient to infer the event year. The only rows allowed to move toward a later readback gate are rows with exactly one full-date candidate from local source artifacts; month/day-only evidence stays blocked.",
            "",
            "## Boundary Truth",
            "",
            "- Selected serving SQLite, source-url SQLite, and Atlas source SQLite are opened read-only only.",
            "- No source/raw DB write, serving write/rebuild, OCR, network fetch, model call, graph/vector/public mutation, huaidj.club upload, CloudRun/VPS deploy, mini-program upload/review, memory write, credential read, 9router, destructive Git, or D-root scan occurs.",
            "",
            "## Next Resume Pointer",
            "",
            f"`{summary['next_resume_pointer']}`",
            "",
        ]
    )


def build_probe(
    *,
    input_path: Path,
    atlas_db: Path,
    source_url_db: Path,
    serving_db: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    rows = read_jsonl(input_path)
    generated_at = now_iso()
    article_map = load_articles_map(atlas_db)
    source_url_map = load_source_url_map(source_url_db)
    serving_refs = load_serving_refs(serving_db, [compact(row.get("source_ref_id"), 160) for row in rows])

    preliminary: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, str, int, int]] = []
    uids: list[str] = []
    for row in rows:
        binding_status, article, source_url, article_match_count, source_url_match_count = choose_binding(
            row, article_map, source_url_map
        )
        preliminary.append((row, article, source_url, binding_status, article_match_count, source_url_match_count))
        uid = compact((article or {}).get("article_uid") or (source_url or {}).get("article_uid"), 200)
        if uid:
            uids.append(uid)

    uids = sorted(set(uids))
    entity_map = load_entities(atlas_db, uids)
    event_counts = load_event_counts(atlas_db, uids)

    probe_rows: list[dict[str, Any]] = []
    for row, article, source_url, binding_status, article_match_count, source_url_match_count in preliminary:
        uid = compact((article or {}).get("article_uid") or (source_url or {}).get("article_uid"), 200)
        probe_rows.append(
            build_probe_row(
                generated_at=generated_at,
                row=row,
                article=article,
                source_url=source_url,
                article_match_count=article_match_count,
                source_url_match_count=source_url_match_count,
                binding_status=binding_status,
                entities=entity_map.get(uid, []),
                event_count=event_counts.get(uid, 0),
                serving_ref_found=compact(row.get("source_ref_id"), 160) in serving_refs,
            )
        )

    candidate_ready = [row for row in probe_rows if row["readback_gate_allowed_next"]]
    still_blocked = [row for row in probe_rows if not row["readback_gate_allowed_next"]]
    binding_blocked = [
        row
        for row in still_blocked
        if row["probe_status"]
        in {
            "blocked_serving_source_ref_missing",
            "blocked_no_local_source_artifact_binding",
            "blocked_ambiguous_or_partial_source_artifact_binding",
        }
    ]
    bound_missing_year = [
        row
        for row in still_blocked
        if row["probe_status"]
        in {
            "blocked_missing_year_from_local_source_artifact",
            "blocked_no_date_evidence_in_local_source_artifact",
            "blocked_no_ocr_or_source_context_text",
        }
    ]
    manual_year_review = [
        row
        for row in still_blocked
        if row["probe_status"] in {"blocked_local_year_context_manual_review_required", "blocked_multiple_full_date_candidates"}
    ]
    ocr_or_text_missing = [row for row in still_blocked if row["probe_status"] == "blocked_no_ocr_or_source_context_text"]
    batches = source_account_batches(probe_rows, generated_at)

    write_jsonl(out_dir / "year_context_source_artifact_probe_rows.jsonl", probe_rows)
    write_jsonl(out_dir / "year_context_source_artifact_candidate_ready_report_only.jsonl", candidate_ready)
    write_jsonl(out_dir / "year_context_source_artifact_still_blocked_rows.jsonl", still_blocked)
    write_jsonl(out_dir / "year_context_source_artifact_binding_blocked_rows.jsonl", binding_blocked)
    write_jsonl(out_dir / "year_context_source_artifact_bound_missing_year_rows.jsonl", bound_missing_year)
    write_jsonl(out_dir / "year_context_source_artifact_manual_year_review_rows.jsonl", manual_year_review)
    write_jsonl(out_dir / "year_context_source_artifact_ocr_or_text_missing_rows.jsonl", ocr_or_text_missing)
    write_jsonl(out_dir / "source_account_year_context_source_artifact_batches.jsonl", batches)

    status_counts = Counter(row["probe_status"] for row in probe_rows)
    leak = leak_scan(probe_rows + batches)
    failed_checks: list[str] = []
    if any(leak.values()):
        failed_checks.append("redaction_leak_detected")
    if candidate_ready and any(row["source_raw_db_write_allowed"] or row["write_gate_allowed_now"] for row in candidate_ready):
        failed_checks.append("write_gate_unexpectedly_open")

    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "generated_at": generated_at,
        "input": display_path(input_path),
        "source_artifact_probe_rows": display_path(out_dir / "year_context_source_artifact_probe_rows.jsonl"),
        "candidate_ready_rows": display_path(out_dir / "year_context_source_artifact_candidate_ready_report_only.jsonl"),
        "binding_blocked_rows": display_path(out_dir / "year_context_source_artifact_binding_blocked_rows.jsonl"),
        "bound_missing_year_rows": display_path(out_dir / "year_context_source_artifact_bound_missing_year_rows.jsonl"),
        "manual_year_review_rows": display_path(out_dir / "year_context_source_artifact_manual_year_review_rows.jsonl"),
        "write_gate_allowed_now": False,
        "readback_gate_requires_separate_packet": True,
        "acceptance_rule": "only_single_full_date_from_local_source_artifact_can_move_to_later_readback_gate",
    }
    write_json(out_dir / "year_context_source_artifact_contract.json", contract)

    decision = (
        "atlas_t6_year_context_source_artifact_probe_failed_safety_scan"
        if failed_checks
        else "atlas_t6_year_context_source_artifact_probe_ready_report_only"
        if candidate_ready and not still_blocked
        else "atlas_t6_year_context_source_artifact_probe_partial_ready_report_only"
        if candidate_ready
        else "atlas_t6_year_context_source_artifact_probe_blocked_report_only"
    )
    outputs = {
        "summary_json": display_path(out_dir / "year_context_source_artifact_probe_summary.json"),
        "contract_json": display_path(out_dir / "year_context_source_artifact_contract.json"),
        "report": display_path(report_path),
        "probe_rows": display_path(out_dir / "year_context_source_artifact_probe_rows.jsonl"),
        "candidate_ready_rows": display_path(out_dir / "year_context_source_artifact_candidate_ready_report_only.jsonl"),
        "still_blocked_rows": display_path(out_dir / "year_context_source_artifact_still_blocked_rows.jsonl"),
        "binding_blocked_rows": display_path(out_dir / "year_context_source_artifact_binding_blocked_rows.jsonl"),
        "bound_missing_year_rows": display_path(out_dir / "year_context_source_artifact_bound_missing_year_rows.jsonl"),
        "manual_year_review_rows": display_path(out_dir / "year_context_source_artifact_manual_year_review_rows.jsonl"),
        "ocr_or_text_missing_rows": display_path(out_dir / "year_context_source_artifact_ocr_or_text_missing_rows.jsonl"),
        "source_account_batches": display_path(out_dir / "source_account_year_context_source_artifact_batches.jsonl"),
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "source_artifact_required_rows": display_path(input_path),
            "atlas_db": display_path(atlas_db),
            "source_url_db": display_path(source_url_db),
            "serving_db": display_path(serving_db),
        },
        "counts": {
            "input_rows": len(rows),
            "probe_rows": len(probe_rows),
            "serving_evidence_ref_bound_rows": sum(1 for row in probe_rows if row["serving_evidence_ref_found"]),
            "local_source_artifact_bound_rows": sum(1 for row in probe_rows if row["binding_status"] == "local_source_artifact_bound"),
            "ambiguous_or_partial_binding_rows": sum(
                1 for row in probe_rows if row["binding_status"] == "ambiguous_or_partial_local_source_artifact_binding"
            ),
            "missing_binding_rows": sum(1 for row in probe_rows if row["binding_status"] == "local_source_artifact_binding_missing"),
            "local_image_rows": sum(1 for row in probe_rows if row["local_image_count"] > 0),
            "image_ocr_rows": sum(1 for row in probe_rows if row["image_ocr_entity_rows"] > 0),
            "source_context_rows": sum(1 for row in probe_rows if row["source_context_entity_rows"] > 0),
            "full_date_candidate_rows": sum(1 for row in probe_rows if row["full_date_candidate_count"] > 0),
            "month_day_only_rows": sum(
                1 for row in probe_rows if row["month_day_candidate_count"] > 0 and row["full_date_candidate_count"] == 0
            ),
            "local_year_context_rows": sum(1 for row in probe_rows if row["local_year_context_values"]),
            "candidate_ready_rows": len(candidate_ready),
            "still_blocked_rows": len(still_blocked),
            "binding_blocked_rows": len(binding_blocked),
            "bound_missing_year_rows": len(bound_missing_year),
            "manual_year_review_rows": len(manual_year_review),
            "ocr_or_text_missing_rows": len(ocr_or_text_missing),
            "source_account_batches": len(batches),
            "write_execution_allowed_rows": 0,
            "source_raw_db_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "status_counts": dict(sorted(status_counts.items())),
        "leak_scan": leak,
        "outputs": outputs,
        "boundary_truth": {
            "report_only": True,
            "serving_sqlite_opened_read_only": bool(serving_refs),
            "atlas_source_sqlite_opened_read_only": atlas_db.exists(),
            "source_url_sqlite_opened_read_only": source_url_db.exists(),
            "source_raw_db_write_executed": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "network_fetch_executed": False,
            "ocr_executed": False,
            "model_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "cloudrun_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_executed": False,
            "write_execution_allowed_now": False,
        },
        "next_resume_pointer": outputs["candidate_ready_rows"] if candidate_ready else outputs["bound_missing_year_rows"],
        "next_if_write_gate_closed": outputs["bound_missing_year_rows"],
    }
    write_json(out_dir / "year_context_source_artifact_probe_summary.json", summary)
    write_text(report_path, render_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--atlas-db", type=Path, default=DEFAULT_ATLAS_DB)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = build_probe(
        input_path=args.input,
        atlas_db=args.atlas_db,
        source_url_db=args.source_url_db,
        serving_db=args.serving_db,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
