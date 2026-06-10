#!/usr/bin/env python3
"""Probe local evidence for the first Atlas source/OCR repair batch.

This is a report-only bridge between the blocked source/OCR repair queue and a
future acceptance gate. It reads local SQLite/source-url sidecars, extracts
candidate article/entity evidence, and keeps every graph/public write flag
closed until source context, OCR/Markdown, date, venue, and lineup evidence are
verified by a later gate.
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
    / "atlas_source_ocr_repair_batch_plan_t5_20260526"
    / "first_active_batch.jsonl"
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
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_first_batch_evidence_probe_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_FIRST_BATCH_EVIDENCE_PROBE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_first_batch_evidence_probe.v1"

URL_RE = re.compile(r"https?://", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(secret|token|cookie|password|api[_-]?key|authorization)", re.I)
EVENT_HINT_RE = re.compile(
    r"(派对|活动|现场|演出|专场|狂欢|本周|一览|live|club|party|session|show|festival|rave|\b\d{1,2}[./-]\d{1,2}\b)",
    re.I,
)
EDITORIAL_HINT_RE = re.compile(
    r"(研究|理论|发展|历史|启蒙|采访|访谈|歌单|playlist|艺术|神话|周边|美学|电影|指南|闲谈)",
    re.I,
)
VENUE_HINT_RE = re.compile(
    r"(club|俱乐部|bar|酒吧|livehouse|live house|dada|oil|tag|\\.tag|jar|all|vervo|44kw|gong|工|between)",
    re.I,
)
DATE_RE = re.compile(
    r"(?<!\d)(?:20\d{2}[./-])?\d{1,2}[./-]\d{1,2}(?:\s*[-~至]\s*(?:20\d{2}[./-])?\d{1,2}[./-]\d{1,2})?(?!\d)"
)
COMPACT_MMDD_RE = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])([0-3]\d)(?!\d)")
DATE_CONTEXT_RE = re.compile(
    r"(月|日|号|週|周|星期|礼拜|入场|开场|开始|派对|活动|演出|doors?|date|fri|sat|sun|mon|tue|wed|thu)",
    re.I,
)
NON_DATE_CONTEXT_RE = re.compile(r"(dj|b2b|节拍|拍号|后|年代|generation|time signature)", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas first-batch evidence probe: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def open_ro_sqlite(db_path: Path) -> sqlite3.Connection:
    reject_d_path(db_path, "sqlite_db")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def placeholders(values: list[str]) -> str:
    if not values:
        return "NULL"
    return ",".join("?" for _ in values)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def load_article_rows(db_path: Path, uids: list[str]) -> dict[str, dict[str, Any]]:
    if not db_path.exists() or not uids:
        return {}
    conn = open_ro_sqlite(db_path)
    try:
        if not table_exists(conn, "articles"):
            return {}
        rows = conn.execute(
            f"""
            SELECT article_uid, title, source_account, publish_time, publish_time_status,
                   city_label, entity_count, event_count, local_image_count, quality_grade,
                   source_archived_at, input_chars, vector_text_preview
            FROM articles
            WHERE article_uid IN ({placeholders(uids)})
            """,
            uids,
        ).fetchall()
    finally:
        conn.close()
    return {compact(row["article_uid"], 200): dict(row) for row in rows}


def load_entity_rows(db_path: Path, uids: list[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not db_path.exists() or not uids:
        return grouped
    conn = open_ro_sqlite(db_path)
    try:
        if not table_exists(conn, "entities"):
            return grouped
        rows = conn.execute(
            f"""
            SELECT source_article_uid, name, type, city, source_kind, confidence,
                   aliases_json, bio, evidence_quote, vector_text_preview
            FROM entities
            WHERE source_article_uid IN ({placeholders(uids)})
            ORDER BY source_article_uid, confidence DESC, row_pk
            """,
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
        if not table_exists(conn, "events"):
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
        rows = conn.execute(
            f"""
            SELECT source_ref_id, article_uid, source_account, title, source_url, post_time,
                   post_date, match_basis, confidence, private_internal_only,
                   public_graph_visible
            FROM article_source_url
            WHERE article_uid IN ({placeholders(uids)})
            """,
            uids,
        ).fetchall()
    finally:
        conn.close()
    return {compact(row["article_uid"], 200): dict(row) for row in rows}


def parse_aliases(row: dict[str, Any]) -> list[str]:
    raw = row.get("aliases_json")
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [compact(item, 120) for item in value if compact(item, 120)]


def unique_by_name(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        key = compact(candidate.get("name"), 160).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= limit:
            break
    return result


def candidate_snippet(row: dict[str, Any]) -> str:
    for key in ("evidence_quote", "bio", "vector_text_preview"):
        value = compact(row.get(key), 240)
        if value:
            return value
    return ""


def extract_lineup_candidates(entity_rows: list[dict[str, Any]], limit: int = 16) -> list[dict[str, Any]]:
    people = []
    for row in entity_rows:
        if compact(row.get("type"), 80).casefold() != "person":
            continue
        people.append(
            {
                "name": compact(row.get("name"), 160),
                "confidence": round(as_float(row.get("confidence")), 3),
                "source_kind": compact(row.get("source_kind"), 80),
                "evidence_quote": candidate_snippet(row),
            }
        )
    return unique_by_name(people, limit)


def extract_venue_candidates(
    source_account: str, title: str, entity_rows: list[dict[str, Any]], limit: int = 10
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in entity_rows:
        entity_type = compact(row.get("type"), 80).casefold()
        name = compact(row.get("name"), 160)
        aliases = parse_aliases(row)
        blob = " ".join([source_account, title, name, " ".join(aliases), candidate_snippet(row)])
        if entity_type in {"place", "organization"} and VENUE_HINT_RE.search(blob):
            candidates.append(
                {
                    "name": name,
                    "type": compact(row.get("type"), 80),
                    "aliases": aliases[:5],
                    "confidence": round(as_float(row.get("confidence")), 3),
                    "source_kind": compact(row.get("source_kind"), 80),
                    "evidence_quote": candidate_snippet(row),
                }
            )
    if VENUE_HINT_RE.search(source_account) and not any(
        compact(candidate.get("name")).casefold() == source_account.casefold() for candidate in candidates
    ):
        candidates.append(
            {
                "name": source_account,
                "type": "source_account_venue_hint",
                "aliases": [],
                "confidence": 0.5,
                "source_kind": "source_account",
                "evidence_quote": f"source_account/title venue hint: {source_account} | {title}",
            }
        )
    return unique_by_name(candidates, limit)


def extract_date_candidates(title: str, entity_rows: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    blobs = [("title", title)]
    for row in entity_rows[:80]:
        snippet = candidate_snippet(row)
        if snippet:
            blobs.append(("entity_evidence", snippet))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, text in blobs:
        for match in DATE_RE.finditer(text):
            value = match.group(0)
            if not valid_date_candidate(value):
                continue
            window = text[max(0, match.start() - 24) : min(len(text), match.end() + 24)]
            if NON_DATE_CONTEXT_RE.search(window):
                continue
            if source != "title":
                if not DATE_CONTEXT_RE.search(window):
                    continue
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                candidates.append({"value": value, "source": source, "evidence_quote": compact(text, 240)})
        if source == "title":
            for match in COMPACT_MMDD_RE.finditer(text):
                mm = match.group(1).zfill(2)
                dd = match.group(2)
                value = f"{mm}/{dd}"
                if value not in seen and 1 <= int(dd) <= 31:
                    seen.add(value)
                    candidates.append({"value": value, "source": "title_compact_mmdd", "evidence_quote": compact(text, 240)})
        if len(candidates) >= limit:
            break
    return candidates[:limit]


def valid_date_candidate(value: str) -> bool:
    parts = re.findall(r"\d+", value)
    if len(parts) < 2:
        return False
    pairs: list[tuple[int, int]] = []
    if len(parts) == 2:
        pairs.append((int(parts[0]), int(parts[1])))
    elif len(parts) == 3:
        pairs.append((int(parts[1]), int(parts[2])))
    elif len(parts) >= 4:
        pairs.append((int(parts[0]), int(parts[1])))
        pairs.append((int(parts[-2]), int(parts[-1])))
    for month, day in pairs:
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return False
    return True


def classify_content(title: str, source_account: str, article: dict[str, Any] | None) -> str:
    blob = f"{title} {source_account}"
    if EVENT_HINT_RE.search(blob):
        return "event_like_candidate"
    if EDITORIAL_HINT_RE.search(blob):
        return "editorial_or_profile_candidate"
    if article and as_int(article.get("local_image_count")) >= 20:
        return "image_rich_entity_relation_candidate"
    return "entity_relation_candidate"


def source_url_safe_fields(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"source_url_recovery_found": False}
    source_url = compact(row.get("source_url"), 2000)
    return {
        "source_url_recovery_found": True,
        "source_ref_id": compact(row.get("source_ref_id"), 120),
        "source_url_sha256": hashlib.sha256(source_url.encode("utf-8")).hexdigest() if source_url else "",
        "source_url_present": bool(source_url),
        "source_url_match_basis": compact(row.get("match_basis"), 160),
        "source_url_confidence": round(as_float(row.get("confidence")), 3),
        "source_url_private_internal_only": bool(row.get("private_internal_only")),
        "source_url_public_graph_visible": bool(row.get("public_graph_visible")),
        "post_time_present": bool(compact(row.get("post_time"))),
        "post_date_present": bool(compact(row.get("post_date"))),
    }


def probe_row(
    generated_at: str,
    row: dict[str, Any],
    article: dict[str, Any] | None,
    entities: list[dict[str, Any]],
    event_count: int,
    source_url: dict[str, Any] | None,
) -> dict[str, Any]:
    article_uid = compact(row.get("article_uid"), 200)
    title = compact(row.get("title") or (article or {}).get("title"), 500)
    source_account = compact(row.get("source_account") or (article or {}).get("source_account"), 200)
    source_kinds = sorted({compact(entity.get("source_kind"), 80) for entity in entities if compact(entity.get("source_kind"), 80)})
    lineup_candidates = extract_lineup_candidates(entities)
    venue_candidates = extract_venue_candidates(source_account, title, entities)
    date_candidates = extract_date_candidates(title, entities)
    source_context_candidate_found = bool(article and entities)
    ocr_markdown_candidate_found = any("ocr" in kind.casefold() for kind in source_kinds)
    local_image_count = as_int((article or {}).get("local_image_count") or row.get("local_image_count"))
    content_class = classify_content(title, source_account, article)
    missing_after_probe = []
    if not date_candidates:
        missing_after_probe.append("date_verified")
    if not venue_candidates:
        missing_after_probe.append("venue_verified")
    if not lineup_candidates:
        missing_after_probe.append("lineup_verified")
    if not source_context_candidate_found:
        missing_after_probe.append("source_context_verified")
    if not ocr_markdown_candidate_found:
        missing_after_probe.append("ocr_markdown_verified")

    candidate_status = "still_blocked_needs_source_ocr_verification"
    if content_class == "editorial_or_profile_candidate":
        candidate_status = "defer_event_acceptance_route_entity_relation_review"
    elif date_candidates and venue_candidates and lineup_candidates and source_context_candidate_found:
        candidate_status = "candidate_fields_found_still_needs_ocr_or_acceptance_gate"

    return {
        "schema_version": SCHEMA_VERSION + ".probe_row",
        "generated_at": generated_at,
        "work_item_id": compact(row.get("work_item_id"), 120),
        "article_uid": article_uid,
        "source_account": source_account,
        "title": title,
        "batch_id": compact(row.get("batch_id"), 120),
        "repair_lane": compact(row.get("repair_lane"), 120),
        "content_classification": content_class,
        "candidate_status": candidate_status,
        "source_db_article_found": bool(article),
        "source_context_candidate_found": source_context_candidate_found,
        "ocr_markdown_candidate_found": ocr_markdown_candidate_found,
        "local_image_count": local_image_count,
        "article_entity_count": as_int((article or {}).get("entity_count") or row.get("entity_count")),
        "source_entity_rows_found": len(entities),
        "source_event_rows_found": event_count,
        "source_entity_kinds": source_kinds,
        "date_candidates": date_candidates,
        "venue_candidates": venue_candidates,
        "lineup_candidates": lineup_candidates,
        "missing_after_probe": missing_after_probe,
        "next_action": next_action_for(content_class, missing_after_probe, local_image_count),
        "source_url_evidence": source_url_safe_fields(source_url),
        "ready_for_acceptance_gate": False,
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
    }


def next_action_for(content_class: str, missing: list[str], local_image_count: int) -> str:
    if content_class == "editorial_or_profile_candidate":
        return "Keep out of performance_event acceptance; review as entity/profile/scene relationship evidence first."
    if "ocr_markdown_verified" in missing and local_image_count > 0:
        return "Locate or regenerate OCR/Markdown for the article images, then rerun source/OCR acceptance precheck."
    if "source_context_verified" in missing:
        return "Locate original article/Markdown context before date, venue, or lineup acceptance."
    if any(field in missing for field in ("date_verified", "venue_verified", "lineup_verified")):
        return "Verify missing date, venue, and lineup fields against local source/OCR evidence before rerunning acceptance."
    return "Run the source/OCR acceptance precheck; current row only has candidate fields, not accepted graph facts."


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


def build_report(summary: dict[str, Any], sample_rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T5 Source/OCR First-Batch Evidence Probe",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input rows: `{counts['input_rows']}`",
        f"- Source DB article rows found: `{counts['source_db_article_rows_found']}`",
        f"- Source URL sidecar rows found: `{counts['source_url_rows_found']}`",
        f"- Source entity rows found: `{counts['source_entity_rows_found']}`",
        f"- Source event rows found: `{counts['source_event_rows_found']}`",
        f"- Event-like candidates: `{counts['event_like_candidate_rows']}`",
        f"- Editorial/profile candidates: `{counts['editorial_or_profile_candidate_rows']}`",
        f"- Date candidate rows: `{counts['date_candidate_rows']}`",
        f"- Venue candidate rows: `{counts['venue_candidate_rows']}`",
        f"- Lineup candidate rows: `{counts['lineup_candidate_rows']}`",
        f"- OCR/Markdown candidate rows: `{counts['ocr_markdown_candidate_rows']}`",
        f"- Acceptance-ready rows: `{counts['acceptance_ready_rows']}`",
        f"- Public URL / secret / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['secret_word_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Boundary",
        "",
        "- Report-only local evidence probe.",
        "- No OCR execution, LLM/model call, source/raw Atlas DB write, serving SQLite write/rebuild, public pointer, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D: root scan occurred.",
        "- Source URLs are not emitted raw; rows only keep source URL presence, match basis, source ref, and SHA256.",
        "",
        "## Sample Rows",
        "",
    ]
    for row in sample_rows[:10]:
        lineup = ", ".join(candidate["name"] for candidate in row["lineup_candidates"][:6])
        venues = ", ".join(candidate["name"] for candidate in row["venue_candidates"][:4])
        dates = ", ".join(candidate["value"] for candidate in row["date_candidates"][:4])
        lines.append(
            f"- `{row['article_uid']}` `{row['source_account']}` / {row['title']} -> `{row['content_classification']}`; dates `{dates or '-'}`; venues `{venues or '-'}`; lineup `{lineup or '-'}`; missing `{row['missing_after_probe']}`"
        )
    lines.extend(
        [
            "",
            "## Next Gate",
            "",
            "Run source/OCR repair or artifact localization for rows that have candidate fields but still lack OCR/Markdown verification, then rerun the T5 source/OCR acceptance precheck before any graph acceptance or serving rebuild.",
            "",
        ]
    )
    return "\n".join(lines)


def build_first_batch_evidence_probe(
    input_path: Path,
    atlas_db: Path,
    source_url_db: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    rows = read_jsonl(input_path)
    uids = [compact(row.get("article_uid"), 200) for row in rows if compact(row.get("article_uid"), 200)]
    article_rows = load_article_rows(atlas_db, uids)
    entity_rows = load_entity_rows(atlas_db, uids)
    event_counts = load_event_counts(atlas_db, uids)
    source_url_rows = load_source_url_rows(source_url_db, uids)

    probe_rows = [
        probe_row(
            generated_at=generated_at,
            row=row,
            article=article_rows.get(compact(row.get("article_uid"), 200)),
            entities=entity_rows.get(compact(row.get("article_uid"), 200), []),
            event_count=event_counts.get(compact(row.get("article_uid"), 200), 0),
            source_url=source_url_rows.get(compact(row.get("article_uid"), 200)),
        )
        for row in rows
    ]
    event_like_rows = [row for row in probe_rows if row["content_classification"] == "event_like_candidate"]
    entity_relation_rows = [
        row
        for row in probe_rows
        if row["source_context_candidate_found"] and row["content_classification"] != "event_like_candidate"
    ]
    still_blocked_rows = [row for row in probe_rows if row["missing_after_probe"]]
    source_rollup = [
        {
            "schema_version": SCHEMA_VERSION + ".source_rollup",
            "source_account": source,
            "rows": len(source_rows),
            "content_classifications": dict(sorted(Counter(row["content_classification"] for row in source_rows).items())),
            "date_candidate_rows": sum(1 for row in source_rows if row["date_candidates"]),
            "venue_candidate_rows": sum(1 for row in source_rows if row["venue_candidates"]),
            "lineup_candidate_rows": sum(1 for row in source_rows if row["lineup_candidates"]),
            "write_status": "report_only",
        }
        for source, source_rows in sorted(
            defaultdict(list, {source: [row for row in probe_rows if row["source_account"] == source] for source in {row["source_account"] for row in probe_rows}}).items()
        )
    ]
    leak_hits = leak_scan(probe_rows)
    failed_checks: list[str] = []
    if any(leak_hits.values()):
        failed_checks.append("probe_output_contains_public_url_secret_or_local_path")

    counts = {
        "input_rows": len(rows),
        "source_db_article_rows_found": sum(1 for row in probe_rows if row["source_db_article_found"]),
        "source_url_rows_found": sum(1 for row in probe_rows if row["source_url_evidence"].get("source_url_recovery_found")),
        "source_entity_rows_found": sum(row["source_entity_rows_found"] for row in probe_rows),
        "source_event_rows_found": sum(row["source_event_rows_found"] for row in probe_rows),
        "source_context_candidate_rows": sum(1 for row in probe_rows if row["source_context_candidate_found"]),
        "ocr_markdown_candidate_rows": sum(1 for row in probe_rows if row["ocr_markdown_candidate_found"]),
        "event_like_candidate_rows": len(event_like_rows),
        "editorial_or_profile_candidate_rows": sum(
            1 for row in probe_rows if row["content_classification"] == "editorial_or_profile_candidate"
        ),
        "date_candidate_rows": sum(1 for row in probe_rows if row["date_candidates"]),
        "venue_candidate_rows": sum(1 for row in probe_rows if row["venue_candidates"]),
        "lineup_candidate_rows": sum(1 for row in probe_rows if row["lineup_candidates"]),
        "acceptance_ready_rows": sum(1 for row in probe_rows if row["ready_for_acceptance_gate"]),
        "still_blocked_rows": len(still_blocked_rows),
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_source_ocr_first_batch_evidence_probe_ready_report_only"
        if not failed_checks
        else "atlas_source_ocr_first_batch_evidence_probe_failed_safety_scan",
        "failed_checks": failed_checks,
        "inputs": {
            "first_active_batch": display_path(input_path),
            "atlas_db": display_path(atlas_db),
            "source_url_db": display_path(source_url_db),
        },
        "outputs": {
            "probe_rows": display_path(out_dir / "first_batch_evidence_probe_rows.jsonl"),
            "event_like_candidate_rows": display_path(out_dir / "event_like_candidate_rows.jsonl"),
            "entity_relation_candidate_rows": display_path(out_dir / "entity_relation_candidate_rows.jsonl"),
            "still_blocked_rows": display_path(out_dir / "still_blocked_rows.jsonl"),
            "source_rollup": display_path(out_dir / "source_rollup.jsonl"),
        },
        "counts": counts,
        "classification_counts": dict(sorted(Counter(row["content_classification"] for row in probe_rows).items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] for row in probe_rows).items())),
        "leak_scan": leak_hits,
        "safety": {
            "report_only": True,
            "raw_source_url_emitted": False,
            "accepted_for_graph": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "source_db_write": False,
            "serving_sqlite_write": False,
            "production_write": False,
            "credential_read": False,
            "network_or_model_call": False,
            "d_root_scan": False,
        },
    }

    write_jsonl(out_dir / "first_batch_evidence_probe_rows.jsonl", probe_rows)
    write_jsonl(out_dir / "event_like_candidate_rows.jsonl", event_like_rows)
    write_jsonl(out_dir / "entity_relation_candidate_rows.jsonl", entity_relation_rows)
    write_jsonl(out_dir / "still_blocked_rows.jsonl", still_blocked_rows)
    write_jsonl(out_dir / "source_rollup.jsonl", source_rollup)
    write_json(out_dir / "source_ocr_first_batch_evidence_probe_summary.json", summary)
    write_text(report_path, build_report(summary, probe_rows))
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
    summary = build_first_batch_evidence_probe(args.input, args.atlas_db, args.source_url_db, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
