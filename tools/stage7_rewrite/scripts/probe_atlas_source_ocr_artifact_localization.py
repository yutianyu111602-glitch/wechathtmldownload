#!/usr/bin/env python3
"""Report-only localization probe for Atlas source/OCR artifact recovery rows.

This narrows the post-recovery-packet cursor from "which rows need artifact
recovery" to "which local evidence is already present and which blocker remains."
It reads existing JSONL/SQLite artifacts only. It does not execute OCR, call
models, or write graph/serving/source state.
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
DEFAULT_WORK_ORDERS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_artifact_recovery_packet_t5_20260526"
    / "source_ocr_artifact_recovery_work_orders.jsonl"
)
DEFAULT_FIRST_BATCH_EVIDENCE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_first_batch_evidence_probe_t5_20260526"
    / "first_batch_evidence_probe_rows.jsonl"
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
DEFAULT_HOST_ARTIFACT_ROOT = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "host_html_artifacts"
    / "artifacts"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_artifact_localization_probe_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_ARTIFACT_LOCALIZATION_PROBE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_artifact_localization_probe.v1"
TARGET_LANES = {
    "source_ocr_artifact_recovery_fast_date_blocked",
    "event_ocr_markdown_and_date_repair",
}

URL_RE = re.compile(r"https?://", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(secret|token|cookie|password|api[_-]?key|authorization)", re.I)
DATE_ISO_RE = re.compile(r"\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.]([0-3]?\d)\b")
DATE_MMDD_RE = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])[-/.]([0-3]?\d)(?!\d)")
COMPACT_MMDD_RE = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])([0-3]\d)(?!\d)")
DATE_CONTEXT_RE = re.compile(
    r"(月|日|号|週|周|星期|礼拜|派对|活動|活动|演出|專場|专场|date|fri|sat|sun|mon|tue|wed|thu)",
    re.I,
)
NON_DATE_CONTEXT_RE = re.compile(r"(dj|b2b|节拍|拍号|后|年代|generation|time signature)", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas source/OCR artifact localization: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_hash(value: Any, length: int = 16) -> str:
    return hashlib.sha256(compact(value, 4000).encode("utf-8", errors="ignore")).hexdigest()[:length]


def scrub_sensitive_words(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit)
    return SENSITIVE_KEY_RE.sub("redacted-word", text)


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
                "publish_time_status",
                "publish_time_index_status",
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
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
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
                "city",
                "source_kind",
                "confidence",
                "aliases_json",
                "bio",
                "evidence_quote",
                "vector_text_preview",
                "raw_json",
            ],
        )
        if "source_article_uid" not in columns:
            return grouped
        order = " ORDER BY source_article_uid"
        if "confidence" in columns:
            order += ", confidence DESC"
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM entities WHERE source_article_uid IN ({placeholders(uids)}){order}",
            uids,
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        grouped[compact(row["source_article_uid"], 200)].append(dict(row))
    return grouped


def load_event_counts(db_path: Path, uids: list[str]) -> dict[str, int]:
    if not db_path.exists() or not uids:
        return {}
    conn = open_ro_sqlite(db_path)
    try:
        if not table_exists(conn, "events") or "source_article_uid" not in table_columns(conn, "events"):
            return {}
        rows = conn.execute(
            f"""
            SELECT source_article_uid, COUNT(*) AS count
            FROM events
            WHERE source_article_uid IN ({placeholders(uids)})
            GROUP BY source_article_uid
            """,
            uids,
        ).fetchall()
    finally:
        conn.close()
    return {compact(row["source_article_uid"], 200): int(row["count"] or 0) for row in rows}


def load_source_url_rows(db_path: Path, uids: list[str]) -> dict[str, dict[str, Any]]:
    if not db_path.exists() or not uids:
        return {}
    conn = open_ro_sqlite(db_path)
    try:
        if not table_exists(conn, "article_source_url"):
            return {}
        columns = select_existing(
            conn,
            "article_source_url",
            [
                "article_uid",
                "source_ref_id",
                "source_url",
                "post_time",
                "post_date",
                "match_basis",
                "confidence",
                "private_internal_only",
                "public_graph_visible",
                "local_image_count",
            ],
        )
        if "article_uid" not in columns:
            return {}
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM article_source_url WHERE article_uid IN ({placeholders(uids)})",
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


def add_date_candidate(candidates: list[dict[str, str]], seen: set[str], value: str, source_kind: str, window: str, policy: str) -> None:
    key = f"{value}|{source_kind}|{safe_hash(window)}"
    if key in seen:
        return
    seen.add(key)
    candidates.append(
        {
            "value": value,
            "source_kind": source_kind,
            "evidence_ref_id": safe_hash(window),
            "evidence_policy": policy,
        }
    )


def candidates_from_text(source_kind: str, text: str) -> list[dict[str, str]]:
    text = compact(text, 10000)
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    if not text:
        return candidates

    for match in DATE_ISO_RE.finditer(text):
        year, month, day = match.groups()
        if not valid_month_day(month, day):
            continue
        window = text[max(0, match.start() - 32) : min(len(text), match.end() + 32)]
        add_date_candidate(
            candidates,
            seen,
            f"{int(year):04d}-{int(month):02d}-{int(day):02d}",
            source_kind,
            window,
            "exact_yyyy_mm_dd_local_text",
        )

    for match in DATE_MMDD_RE.finditer(text):
        month, day = match.groups()
        if not valid_month_day(month, day):
            continue
        window = text[max(0, match.start() - 32) : min(len(text), match.end() + 32)]
        if NON_DATE_CONTEXT_RE.search(window):
            continue
        if source_kind not in {"source_url_post_date", "source_url_post_time", "article_publish_time"} and not DATE_CONTEXT_RE.search(window):
            continue
        add_date_candidate(
            candidates,
            seen,
            f"{int(month):02d}/{int(day):02d}",
            source_kind,
            window,
            "exact_month_day_with_event_context",
        )

    if source_kind == "title":
        for match in COMPACT_MMDD_RE.finditer(text):
            month, day = match.groups()
            if not valid_month_day(month, day):
                continue
            window = text[max(0, match.start() - 16) : min(len(text), match.end() + 24)]
            if NON_DATE_CONTEXT_RE.search(window):
                continue
            add_date_candidate(
                candidates,
                seen,
                f"{int(month):02d}/{int(day):02d}",
                "title_compact_mmdd",
                window,
                "title_compact_month_day",
            )
    return candidates


def raw_json_text(raw_json: Any) -> str:
    raw = compact(raw_json, 12000)
    if not raw:
        return ""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(value, dict):
        fields = []
        for key in ("title", "publish_time", "source_archived_at", "content", "text", "markdown", "vector_text"):
            fields.append(compact(value.get(key), 3000))
        return " ".join(field for field in fields if field)
    return raw


def collect_date_candidates(
    target: dict[str, Any],
    article: dict[str, Any] | None,
    source_url: dict[str, Any] | None,
    entities: list[dict[str, Any]],
) -> list[dict[str, str]]:
    blobs: list[tuple[str, str]] = [("title", compact(target.get("title"), 600))]
    if article:
        blobs.extend(
            [
                ("title", compact(article.get("title"), 600)),
                ("article_publish_time", compact(article.get("publish_time"), 160)),
                ("article_source_archived_at", compact(article.get("source_archived_at"), 160)),
                ("article_vector_preview", compact(article.get("vector_text_preview"), 3000)),
                ("article_raw_json", raw_json_text(article.get("raw_json"))),
            ]
        )
    if source_url:
        blobs.extend(
            [
                ("source_url_post_date", compact(source_url.get("post_date"), 160)),
                ("source_url_post_time", compact(source_url.get("post_time"), 160)),
            ]
        )
    preview = target.get("candidate_preview") if isinstance(target.get("candidate_preview"), dict) else {}
    for value in preview.get("date_values") or []:
        blobs.append(("recovery_packet_candidate_preview", compact(value, 160)))
    for entity in entities[:80]:
        kind = compact(entity.get("source_kind"), 120) or "entity"
        entity_text = " ".join(
            part
            for part in (
                compact(entity.get("evidence_quote"), 1200),
                compact(entity.get("vector_text_preview"), 1200),
                raw_json_text(entity.get("raw_json")),
            )
            if part
        )
        if entity_text:
            blobs.append((f"entity_{kind}", entity_text))

    found: list[dict[str, str]] = []
    seen_values: set[tuple[str, str, str]] = set()
    for source_kind, text in blobs:
        for candidate in candidates_from_text(source_kind, text):
            dedupe = (candidate["value"], candidate["source_kind"], candidate["evidence_ref_id"])
            if dedupe in seen_values:
                continue
            seen_values.add(dedupe)
            found.append(candidate)
    return found[:20]


def safe_source_url_evidence(target: dict[str, Any], source_url: dict[str, Any] | None) -> dict[str, Any]:
    packet = target.get("source_url_evidence") if isinstance(target.get("source_url_evidence"), dict) else {}
    source = source_url or {}
    source_url_text = compact(source.get("source_url"), 4000)
    return {
        "source_url_recovery_found": bool(packet.get("source_url_recovery_found") or source),
        "source_ref_id": compact(source.get("source_ref_id") or packet.get("source_ref_id"), 120),
        "source_url_sha256": hashlib.sha256(source_url_text.encode("utf-8", errors="ignore")).hexdigest()
        if source_url_text
        else compact(packet.get("source_url_sha256"), 80),
        "source_url_present": bool(source_url_text or packet.get("source_url_present")),
        "source_url_match_basis": scrub_sensitive_words(source.get("match_basis") or packet.get("source_url_match_basis"), 180),
        "source_url_confidence": source.get("confidence") or packet.get("source_url_confidence") or 0,
        "post_time_present": bool(source.get("post_time") or packet.get("post_time_present")),
        "post_date_present": bool(source.get("post_date") or packet.get("post_date_present")),
        "public_graph_visible": bool(source.get("public_graph_visible") or False),
    }


def evidence_by_uid(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {compact(row.get("article_uid"), 200): row for row in rows if compact(row.get("article_uid"), 200)}


def source_slug(source_account: str) -> str:
    text = compact(source_account, 180).casefold()
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return slug or safe_hash(source_account)


def host_artifact_scope(host_root: Path, source_account: str) -> dict[str, Any]:
    reject_d_path(host_root, "host_artifact_root")
    if not host_root.exists():
        return {
            "source_artifact_scope_status": "host_artifact_root_absent",
            "source_artifact_ref_id": safe_hash(source_account),
            "source_dir_present": False,
        }
    slug = source_slug(source_account)
    dirs = [child.name.casefold() for child in host_root.iterdir() if child.is_dir()]
    return {
        "source_artifact_scope_status": "source_dir_present" if slug in dirs else "source_dir_absent_in_current_host_html_artifact_batch",
        "source_artifact_ref_id": safe_hash(source_account),
        "source_dir_present": slug in dirs,
    }


def source_entity_kinds(target: dict[str, Any], entities: list[dict[str, Any]], evidence: dict[str, Any] | None) -> list[str]:
    kinds: set[str] = set()
    preview = target.get("candidate_preview") if isinstance(target.get("candidate_preview"), dict) else {}
    for value in preview.get("source_entity_kinds") or []:
        item = compact(value, 100)
        if item:
            kinds.add(item)
    if evidence:
        for value in evidence.get("source_entity_kinds") or []:
            item = compact(value, 100)
            if item:
                kinds.add(item)
    for entity in entities:
        item = compact(entity.get("source_kind"), 100)
        if item:
            kinds.add(item)
    return sorted(kinds)


def localization_status(*, has_date: bool, has_ocr: bool) -> str:
    if has_date and has_ocr:
        return "candidate_evidence_present_acceptance_still_closed"
    if not has_date and not has_ocr:
        return "blocked_missing_exact_date_and_ocr_markdown"
    if not has_date:
        return "blocked_missing_exact_date"
    return "blocked_missing_ocr_markdown"


def next_action(status: str) -> str:
    if status == "candidate_evidence_present_acceptance_still_closed":
        return "run_source_ocr_acceptance_precheck_only_after_reviewer_confirms_candidate_evidence_policy"
    if status == "blocked_missing_exact_date":
        return "inspect_existing_image_ocr_or_article_markdown_for_exact_event_date_before_acceptance"
    if status == "blocked_missing_ocr_markdown":
        return "locate_or_generate_ocr_markdown_then_rerun_source_ocr_acceptance_precheck"
    return "recover_ocr_markdown_first_then_extract_exact_date_from_recovered_artifacts"


def build_probe_row(
    *,
    generated_at: str,
    target: dict[str, Any],
    evidence: dict[str, Any] | None,
    article: dict[str, Any] | None,
    entities: list[dict[str, Any]],
    event_count: int,
    source_url: dict[str, Any] | None,
    host_root: Path,
) -> dict[str, Any]:
    source_account = compact(target.get("source_account") or (article or {}).get("source_account"), 240)
    article_uid = compact(target.get("article_uid"), 200)
    candidate_counts = target.get("candidate_field_counts") if isinstance(target.get("candidate_field_counts"), dict) else {}
    kinds = source_entity_kinds(target, entities, evidence)
    image_ocr_rows = sum(1 for entity in entities if "ocr" in compact(entity.get("source_kind"), 100).casefold())
    source_context_rows = sum(1 for entity in entities if compact(entity.get("source_kind"), 100).casefold() in {"article_text", "meta", "source_context"})
    first_batch_ocr = bool((evidence or {}).get("ocr_markdown_candidate_found"))
    packet_ocr = any("ocr" in kind.casefold() for kind in kinds)
    has_ocr = first_batch_ocr or packet_ocr or image_ocr_rows > 0
    date_candidates = collect_date_candidates(target, article, source_url, entities)
    has_date = bool(date_candidates)
    status = localization_status(has_date=has_date, has_ocr=has_ocr)
    source_url_safe = safe_source_url_evidence(target, source_url)
    row = {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "article_uid": article_uid,
        "work_item_id": compact(target.get("work_item_id"), 120),
        "source_account": source_account,
        "title": compact(target.get("title") or (article or {}).get("title"), 500),
        "recovery_lane": compact(target.get("recovery_lane"), 160),
        "blocking_fields": [compact(value, 120) for value in target.get("blocking_fields", []) if compact(value, 120)],
        "source_db_article_found": bool(article),
        "source_url_evidence": source_url_safe,
        "local_image_count": as_int((article or {}).get("local_image_count") or source_url_safe.get("local_image_count") or candidate_counts.get("local_image_count")),
        "source_entity_rows_found": len(entities),
        "source_context_entity_rows": source_context_rows,
        "image_ocr_entity_rows": image_ocr_rows,
        "source_event_rows_found": event_count,
        "source_entity_kinds": kinds,
        "first_batch_ocr_markdown_candidate_found": first_batch_ocr,
        "existing_ocr_markdown_candidate_found": has_ocr,
        "exact_date_candidate_found": has_date,
        "exact_date_candidate_count": len(date_candidates),
        "date_candidates": date_candidates,
        "localization_status": status,
        "next_action": next_action(status),
        "host_artifact_scope": host_artifact_scope(host_root, source_account),
        "accepted_date_candidate": None,
        "acceptance_precheck_allowed_now": False,
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
    }
    return row


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


def build_source_rollup(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"] or "UNKNOWN"].append(row)
    rollup = []
    for source, source_rows in sorted(grouped.items()):
        rollup.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_rollup",
                "generated_at": generated_at,
                "source_account": source,
                "target_rows": len(source_rows),
                "lane_counts": dict(sorted(Counter(row["recovery_lane"] for row in source_rows).items())),
                "localization_status_counts": dict(sorted(Counter(row["localization_status"] for row in source_rows).items())),
                "date_candidate_rows": sum(1 for row in source_rows if row["exact_date_candidate_found"]),
                "existing_ocr_markdown_candidate_rows": sum(1 for row in source_rows if row["existing_ocr_markdown_candidate_found"]),
                "write_status": "report_only",
            }
        )
    return rollup


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    lines = [
        "# Atlas T5 Source/OCR Artifact Localization Probe - 2026-05-26",
        "",
        "Status: `CURRENT_AUTHORITY`",
        "Mode: `report_only`",
        "",
        "## LLM Audit Finding",
        "",
        "The previous recovery packet correctly avoided rerunning the 0/2 fast-date acceptance attempt, but it still only described recovery work. This probe inspected the bounded fast-date and event OCR/date rows against local JSONL/SQLite evidence and keeps all public or graph-affecting gates closed.",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Target rows: `{counts['target_rows']}`",
        f"- Fast-date rows: `{counts['fast_date_rows']}`",
        f"- Event OCR/date rows: `{counts['event_ocr_markdown_and_date_rows']}`",
        f"- Existing OCR/Markdown candidate rows: `{counts['existing_ocr_markdown_candidate_rows']}`",
        f"- Missing OCR/Markdown rows: `{counts['missing_ocr_markdown_rows']}`",
        f"- Exact date candidate rows: `{counts['exact_date_candidate_rows']}`",
        f"- Acceptance-ready rows: `{counts['acceptance_ready_rows']}`",
        f"- Still blocked rows: `{counts['still_blocked_rows']}`",
        f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Outputs",
        "",
        f"- Summary JSON: `{outputs['summary_json']}`",
        f"- Probe rows: `{outputs['probe_rows_jsonl']}`",
        f"- OCR candidate present but date blocked: `{outputs['ocr_candidate_present_date_blocked_jsonl']}`",
        f"- OCR/Markdown missing queue: `{outputs['ocr_markdown_missing_generation_queue_jsonl']}`",
        f"- Date candidate present, acceptance closed: `{outputs['date_candidate_present_acceptance_closed_jsonl']}`",
        f"- Still blocked rows: `{outputs['still_blocked_rows_jsonl']}`",
        f"- Source rollup: `{outputs['source_rollup_jsonl']}`",
        "",
        "## Row Snapshot",
        "",
    ]
    for row in rows[:10]:
        lines.append(
            f"- `{row['article_uid']}` `{row['source_account']}` / {row['title']} -> `{row['localization_status']}`; date candidates `{row['exact_date_candidate_count']}`; OCR candidate `{row['existing_ocr_markdown_candidate_found']}`; next `{row['next_action']}`"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only local probe.",
            "- No OCR execution, model call, source/raw Atlas DB write, serving SQLite write or rebuild, public pointer, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "- Raw source URLs and local filesystem paths are not emitted. Artifact scope is represented by hashed refs and booleans.",
            "",
            "## Next Cursor",
            "",
            "Use the OCR candidate/date-blocked rows for exact-date artifact review, and use the OCR/Markdown missing queue for bounded localization or generation. Rerun source/OCR acceptance only after recovered exact date and OCR/Markdown evidence exists.",
            "",
        ]
    )
    return "\n".join(lines)


def build_artifact_localization_probe(
    *,
    work_orders_path: Path,
    first_batch_evidence_path: Path,
    atlas_db: Path,
    source_url_db: Path,
    host_artifact_root: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in (
        ("work_orders_path", work_orders_path),
        ("first_batch_evidence_path", first_batch_evidence_path),
        ("atlas_db", atlas_db),
        ("source_url_db", source_url_db),
        ("host_artifact_root", host_artifact_root),
        ("out_dir", out_dir),
        ("report_path", report_path),
    ):
        reject_d_path(path, label)

    generated_at = now_iso()
    work_orders = [row for row in read_jsonl(work_orders_path) if compact(row.get("recovery_lane"), 160) in TARGET_LANES]
    evidence_rows = evidence_by_uid(read_jsonl(first_batch_evidence_path, optional=True))
    uids = [compact(row.get("article_uid"), 200) for row in work_orders if compact(row.get("article_uid"), 200)]
    articles = load_articles(atlas_db, uids)
    entities = load_entities(atlas_db, uids)
    events = load_event_counts(atlas_db, uids)
    source_urls = load_source_url_rows(source_url_db, uids)

    rows = [
        build_probe_row(
            generated_at=generated_at,
            target=row,
            evidence=evidence_rows.get(compact(row.get("article_uid"), 200)),
            article=articles.get(compact(row.get("article_uid"), 200)),
            entities=entities.get(compact(row.get("article_uid"), 200), []),
            event_count=events.get(compact(row.get("article_uid"), 200), 0),
            source_url=source_urls.get(compact(row.get("article_uid"), 200)),
            host_root=host_artifact_root,
        )
        for row in work_orders
    ]
    ocr_present_date_blocked = [
        row
        for row in rows
        if row["existing_ocr_markdown_candidate_found"] and row["localization_status"] in {"blocked_missing_exact_date", "candidate_evidence_present_acceptance_still_closed"}
    ]
    ocr_missing = [row for row in rows if not row["existing_ocr_markdown_candidate_found"]]
    date_present_acceptance_closed = [row for row in rows if row["exact_date_candidate_found"]]
    still_blocked = [row for row in rows if not row["acceptance_precheck_allowed_now"]]
    rollup = build_source_rollup(rows, generated_at)

    write_jsonl(out_dir / "artifact_localization_probe_rows.jsonl", rows)
    write_jsonl(out_dir / "ocr_candidate_present_date_blocked.jsonl", ocr_present_date_blocked)
    write_jsonl(out_dir / "ocr_markdown_missing_generation_queue.jsonl", ocr_missing)
    write_jsonl(out_dir / "date_candidate_present_acceptance_closed.jsonl", date_present_acceptance_closed)
    write_jsonl(out_dir / "still_blocked_rows.jsonl", still_blocked)
    write_jsonl(out_dir / "source_rollup.jsonl", rollup)

    leak = leak_scan(rows + rollup)
    failed_checks = [key for key, value in leak.items() if value]
    counts = {
        "target_rows": len(rows),
        "fast_date_rows": sum(1 for row in rows if row["recovery_lane"] == "source_ocr_artifact_recovery_fast_date_blocked"),
        "event_ocr_markdown_and_date_rows": sum(1 for row in rows if row["recovery_lane"] == "event_ocr_markdown_and_date_repair"),
        "source_db_article_rows_found": sum(1 for row in rows if row["source_db_article_found"]),
        "source_url_rows_found": sum(1 for row in rows if row["source_url_evidence"].get("source_url_recovery_found")),
        "existing_ocr_markdown_candidate_rows": sum(1 for row in rows if row["existing_ocr_markdown_candidate_found"]),
        "missing_ocr_markdown_rows": len(ocr_missing),
        "exact_date_candidate_rows": sum(1 for row in rows if row["exact_date_candidate_found"]),
        "date_candidate_present_acceptance_closed_rows": len(date_present_acceptance_closed),
        "acceptance_ready_rows": sum(1 for row in rows if row["acceptance_precheck_allowed_now"]),
        "still_blocked_rows": len(still_blocked),
        "host_artifact_source_dir_present_rows": sum(1 for row in rows if row["host_artifact_scope"].get("source_dir_present")),
    }
    decision = (
        "atlas_source_ocr_artifact_localization_probe_failed_safety_scan"
        if failed_checks
        else "atlas_source_ocr_artifact_localization_probe_blocked_report_only"
        if still_blocked
        else "atlas_source_ocr_artifact_localization_probe_ready_for_later_acceptance_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "localization_status_counts": dict(sorted(Counter(row["localization_status"] for row in rows).items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] or "UNKNOWN" for row in rows).items())),
        "inputs": {
            "work_orders": display_path(work_orders_path),
            "first_batch_evidence": display_path(first_batch_evidence_path),
            "atlas_db": display_path(atlas_db),
            "source_url_db": display_path(source_url_db),
            "host_artifact_root": display_path(host_artifact_root),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "source_ocr_artifact_localization_probe_summary.json"),
            "probe_rows_jsonl": display_path(out_dir / "artifact_localization_probe_rows.jsonl"),
            "ocr_candidate_present_date_blocked_jsonl": display_path(out_dir / "ocr_candidate_present_date_blocked.jsonl"),
            "ocr_markdown_missing_generation_queue_jsonl": display_path(out_dir / "ocr_markdown_missing_generation_queue.jsonl"),
            "date_candidate_present_acceptance_closed_jsonl": display_path(out_dir / "date_candidate_present_acceptance_closed.jsonl"),
            "still_blocked_rows_jsonl": display_path(out_dir / "still_blocked_rows.jsonl"),
            "source_rollup_jsonl": display_path(out_dir / "source_rollup.jsonl"),
            "report_md": display_path(report_path),
        },
        "leak_scan": leak,
        "safety": {
            "report_only": True,
            "raw_source_url_emitted": False,
            "raw_local_path_emitted": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "ocr_execution_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "llm_audit": {
            "artifact_contradiction_found": False,
            "stale_loop_avoided": "did_not_rerun_fast_date_acceptance_after_zero_of_two_acceptance",
            "highest_leverage_lane": "bounded_local_artifact_localization_probe_for_fast_date_and_event_ocr_date_rows",
            "pipeline_improvement": "structured_status_split_between_ocr_candidate_present_date_blocked_and_ocr_markdown_missing_generation_queue",
        },
        "stop_reason": "blocked_report_only_until_exact_date_and_ocr_markdown_evidence_are_recovered",
        "wait_reason": "acceptance gates remain closed; probe produced next queues instead of public/graph writes.",
        "next_resume_cursor": "Process ocr_candidate_present_date_blocked.jsonl for exact-date review and ocr_markdown_missing_generation_queue.jsonl for bounded OCR/Markdown localization or generation; rerun source/OCR acceptance only after recovered evidence exists.",
    }
    write_json(out_dir / "source_ocr_artifact_localization_probe_summary.json", summary)
    write_text(report_path, render_report(summary, rows))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-orders", type=Path, default=DEFAULT_WORK_ORDERS)
    parser.add_argument("--first-batch-evidence", type=Path, default=DEFAULT_FIRST_BATCH_EVIDENCE)
    parser.add_argument("--atlas-db", type=Path, default=DEFAULT_ATLAS_DB)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--host-artifact-root", type=Path, default=DEFAULT_HOST_ARTIFACT_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_artifact_localization_probe(
        work_orders_path=args.work_orders,
        first_batch_evidence_path=args.first_batch_evidence,
        atlas_db=args.atlas_db,
        source_url_db=args.source_url_db,
        host_artifact_root=args.host_artifact_root,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
