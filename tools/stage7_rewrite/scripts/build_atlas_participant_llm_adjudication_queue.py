#!/usr/bin/env python3
"""Build the full LLM adjudication queue for Atlas participant recovery.

This is the no-human path for the DJ-first Atlas blocker: events without
public-safe participants. It consumes immutable local evidence and sidecars,
then writes a private, report-only LLM input package. It does not call models,
does not mutate the source Atlas SQLite, and does not expose raw URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "atlas_participant_llm_adjudication_queue.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_DB = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_local_sqlite_db_138102_20260521"
    / "atlas.sqlite"
)
DEFAULT_REPAIR_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_low_cost_repair_sidecar_v2_20260522"
    / "atlas_dj_low_cost_repair_sidecar.sqlite"
)
DEFAULT_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_source_url_recovery_20260522"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_participant_llm_adjudication_queue_v2_20260522"

DJ_ENTITY_TYPES = {"person", "dj", "artist"}
NOISE_TERMS = [
    "葡萄酒",
    "红葡萄酒",
    "白葡萄酒",
    "红酒",
    "酒单",
    "菜单",
    "咖啡",
    "下午茶",
    "威士忌",
    "香槟",
    "cocktail",
    "wine",
]
MUSIC_TERMS = [
    "dj",
    "producer",
    "live",
    "lineup",
    "b2b",
    "club",
    "rave",
    "techno",
    "house",
    "bass",
    "electronic",
    "ambient",
    "mixtape",
    "set",
    "厂牌",
    "俱乐部",
    "电子",
    "电音",
    "派对",
    "演出",
    "阵容",
    "嘉宾",
    "主办",
    "音乐",
    "舞池",
]
KNOWN_NON_DJ_NAMES = {
    "all",
    "oil",
    "dada",
    "tag",
    "shcr",
    "byyb",
    "baihui",
    "cdcr",
    "bo live",
    "elevator",
    "the window",
    "echobay",
    "echo bay",
    "axis",
    "jar",
    "foundation",
    "system",
    "zhaodai",
    "heim",
    "hum",
    "44kw",
    "potent",
    "院吧",
    "油",
    "招待",
    "百会",
    "成都社区电台",
}
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", text(value).casefold())


def norm_name(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text(value).casefold())


KNOWN_NON_DJ_KEYS = {norm_name(value) for value in KNOWN_NON_DJ_NAMES}


def is_known_non_dj_name(value: Any) -> bool:
    key = norm_name(value)
    return bool(key and key in KNOWN_NON_DJ_KEYS)


def stable_id(prefix: str, *parts: Any) -> str:
    blob = "\u241f".join(text(part) for part in parts if text(part))
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:18]
    return f"{prefix}:{digest}"


def source_hash(value: Any) -> str:
    raw = text(value)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16] if raw else ""


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def parse_json_list(value: Any) -> list[str]:
    raw = text(value)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        item_text = text(item)
        key = norm_name(item_text)
        if not item_text or not key or key in seen:
            continue
        seen.add(key)
        out.append(item_text)
    return out


def parse_json_object(value: Any) -> dict[str, Any]:
    raw = text(value)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def has_any(value: str, terms: Iterable[str]) -> bool:
    low = norm(value)
    return any(term.casefold() in low for term in terms)


def is_noise_event(*values: Any) -> bool:
    return has_any(" | ".join(text(value) for value in values if text(value)), NOISE_TERMS)


def is_music_like(*values: Any) -> bool:
    return has_any(" | ".join(text(value) for value in values if text(value)), MUSIC_TERMS)


def strip_html(raw_html: str, *, max_chars: int) -> str:
    if not raw_html:
        return ""
    cleaned = SCRIPT_STYLE_RE.sub(" ", raw_html)
    cleaned = TAG_RE.sub(" ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = SPACE_RE.sub(" ", cleaned).strip()
    return cleaned[:max_chars]


def read_raw_html_excerpt(path_text: str, *, max_chars: int) -> tuple[str, bool]:
    path = Path(path_text)
    try:
        if not path.exists() or not path.is_file():
            return "", False
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "", False
    return strip_html(raw, max_chars=max_chars), True


def first_json_text(raw_json: Any, *keys: str) -> str:
    payload = parse_json_object(raw_json)
    for key in keys:
        value = text(payload.get(key))
        if value:
            return value
    return ""


def create_output_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE article_context (
            article_context_id TEXT PRIMARY KEY,
            source_article_uid TEXT NOT NULL,
            source_ref_id TEXT,
            source_hash TEXT,
            source_account TEXT,
            source_title TEXT,
            post_date TEXT,
            match_basis TEXT,
            source_url_available INTEGER,
            raw_html_text_available INTEGER,
            article_vector_text TEXT,
            article_text_excerpt TEXT,
            same_article_entities_json TEXT,
            context_chars INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE participant_llm_queue (
            queue_id TEXT PRIMARY KEY,
            llm_lane TEXT NOT NULL,
            priority_score REAL NOT NULL,
            source_article_uid TEXT NOT NULL,
            event_key TEXT,
            event_id TEXT,
            event_name TEXT,
            time_text TEXT,
            place TEXT,
            city TEXT,
            source_account TEXT,
            source_title TEXT,
            candidate_names_json TEXT,
            candidate_count INTEGER,
            sidecar_confidence REAL,
            sidecar_tier TEXT,
            basis_json TEXT,
            same_article_entities_json TEXT,
            article_context_id TEXT,
            event_vector_text TEXT,
            decision_schema_json TEXT,
            write_status TEXT,
            generated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE queue_run (
            generated_at TEXT,
            schema_version TEXT,
            source_db TEXT,
            repair_db TEXT,
            source_url_db TEXT,
            summary_json TEXT,
            safety_json TEXT
        )
        """
    )
    conn.execute("CREATE INDEX idx_queue_lane ON participant_llm_queue(llm_lane)")
    conn.execute("CREATE INDEX idx_queue_article ON participant_llm_queue(source_article_uid)")
    return conn


def load_source_url_index(source_url_db: Path | None) -> dict[str, dict[str, Any]]:
    if not source_url_db or not source_url_db.exists():
        return {}
    conn = connect_readonly(source_url_db)
    rows: dict[str, dict[str, Any]] = {}
    try:
        for row in conn.execute(
            """
            SELECT article_uid, source_ref_id, source_url, post_date, match_basis,
                   archive_raw_html_path, confidence
            FROM article_source_url
            """
        ):
            item = row_dict(row)
            rows[text(item.get("article_uid"))] = item
    finally:
        conn.close()
    return rows


def load_same_article_dj_entities(source_db: Path, article_uids: set[str]) -> dict[str, list[str]]:
    if not article_uids:
        return {}
    conn = connect_readonly(source_db)
    result: dict[str, list[str]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    try:
        sql = """
            SELECT source_article_uid, name
            FROM entities
            WHERE lower(type) IN ('person','dj','artist')
              AND name IS NOT NULL
              AND name != ''
        """
        for row in conn.execute(sql):
            uid = text(row["source_article_uid"])
            if uid not in article_uids:
                continue
            name = text(row["name"])
            key = norm_name(name)
            if not key or key in seen[uid]:
                continue
            if is_noise_event(name):
                continue
            if is_known_non_dj_name(name):
                continue
            seen[uid].add(key)
            if len(result[uid]) < 80:
                result[uid].append(name)
    finally:
        conn.close()
    return result


def iter_review_candidate_rows(repair_db: Path) -> Iterable[dict[str, Any]]:
    conn = connect_readonly(repair_db)
    try:
        sql = """
            SELECT *
            FROM event_participant_candidates
            WHERE tier = 'review_candidate'
            ORDER BY confidence DESC, candidate_count ASC, source_article_uid, event_id
        """
        for row in conn.execute(sql):
            yield row_dict(row)
    finally:
        conn.close()


def load_sidecar_event_keys(repair_db: Path) -> set[tuple[str, str, str, str]]:
    conn = connect_readonly(repair_db)
    keys: set[tuple[str, str, str, str]] = set()
    try:
        for row in conn.execute(
            """
            SELECT source_article_uid, event_id, event_name, time_text
            FROM event_participant_candidates
            """
        ):
            keys.add(
                (
                    text(row["source_article_uid"]),
                    text(row["event_id"]),
                    text(row["event_name"]),
                    text(row["time_text"]),
                )
            )
    finally:
        conn.close()
    return keys


def participant_count(participants_json: Any) -> int:
    return len(parse_json_list(participants_json))


def iter_no_candidate_events(
    source_db: Path,
    candidate_keys: set[tuple[str, str, str, str]],
    *,
    max_rows: int | None = None,
) -> Iterable[dict[str, Any]]:
    conn = connect_readonly(source_db)
    emitted = 0
    try:
        sql = """
            SELECT source_article_uid, evid, name, place, city, time_text,
                   source_kind, confidence, participants_json,
                   vector_text_preview, raw_json
            FROM events
            WHERE COALESCE(participants_json, '') IN ('', '[]')
            ORDER BY row_pk
        """
        for row in conn.execute(sql):
            item = row_dict(row)
            key = (
                text(item.get("source_article_uid")),
                text(item.get("evid")),
                text(item.get("name")),
                text(item.get("time_text")),
            )
            if key in candidate_keys:
                continue
            if participant_count(item.get("participants_json")):
                continue
            event_vector = first_json_text(item.get("raw_json"), "vector_text") or text(
                item.get("vector_text_preview")
            )
            if is_noise_event(item.get("name"), item.get("place"), event_vector):
                continue
            if not is_music_like(item.get("name"), item.get("place"), item.get("time_text"), event_vector):
                continue
            item["event_vector_text"] = event_vector
            emitted += 1
            yield item
            if max_rows is not None and emitted >= max_rows:
                break
    finally:
        conn.close()


def lane_for_candidate(row: dict[str, Any]) -> str:
    basis = parse_json_object(row.get("basis_json"))
    source_kind = text(basis.get("source_kind")) or "unknown"
    candidate_count_value = int(row.get("candidate_count") or 0)
    if candidate_count_value >= 10:
        return "llm_ambiguous_many_candidates"
    if source_kind == "venue":
        return "llm_same_article_event_candidate"
    if source_kind == "radio":
        return "llm_radio_source_candidate"
    return "llm_unknown_source_candidate"


def priority_for_candidate(row: dict[str, Any]) -> float:
    basis = parse_json_object(row.get("basis_json"))
    source_kind = text(basis.get("source_kind"))
    score = float(row.get("confidence") or 0.0) * 100
    if basis.get("event_has_place"):
        score += 8
    if basis.get("event_has_time_text"):
        score += 8
    if source_kind == "venue":
        score += 12
    elif source_kind == "radio":
        score -= 4
    elif source_kind == "unknown":
        score -= 8
    candidate_count_value = int(row.get("candidate_count") or 0)
    if candidate_count_value > 8:
        score -= (candidate_count_value - 8) * 3
    return round(score, 3)


def priority_for_reextract(row: dict[str, Any], article_entities: list[str]) -> float:
    score = 35.0
    if text(row.get("place")):
        score += 8
    if text(row.get("time_text")):
        score += 8
    if article_entities:
        score += min(len(article_entities), 12)
    if is_music_like(row.get("name"), row.get("event_vector_text")):
        score += 12
    return round(score, 3)


def decision_schema_for_lane(lane: str) -> dict[str, Any]:
    base = {
        "schema": "atlas.participant_llm_decision.v1",
        "decision": "accept|reject|needs_more_context",
        "confidence": "0.0-1.0",
        "accepted_participants": ["DJ names that are explicit event participants"],
        "rejected_candidates": ["names that are only co-mentioned or unsupported"],
        "relationship_basis": "same_event|lineup_text|same_article_only|not_participant",
        "public_graph_ready": "boolean; true only when accepted_participants has event evidence",
        "evidence_quote": "short source-grounded quote, no raw URL",
        "risk_flags": ["ambiguous_name", "same_article_only", "non_music_noise", "weak_text"],
        "reasoning_zh": "short Chinese explanation",
    }
    if lane == "llm_reextract_no_candidate":
        base["task"] = "extract missing DJ/person participants for this event from article context"
    else:
        base["task"] = "adjudicate whether candidate names are actual participants of this event"
    return base


def source_article_info(source_db: Path, article_uids: set[str]) -> dict[str, dict[str, Any]]:
    if not article_uids:
        return {}
    conn = connect_readonly(source_db)
    result: dict[str, dict[str, Any]] = {}
    try:
        for row in conn.execute(
            """
            SELECT article_uid, title, source_account, publish_time,
                   vector_text_preview, raw_json
            FROM articles
            """
        ):
            uid = text(row["article_uid"])
            if uid not in article_uids:
                continue
            item = row_dict(row)
            item["article_vector_text"] = first_json_text(item.get("raw_json"), "vector_text") or text(
                item.get("vector_text_preview")
            )
            result[uid] = item
    finally:
        conn.close()
    return result


def collect_article_uids(
    source_db: Path,
    repair_db: Path,
    *,
    max_no_candidate_rows: int | None,
) -> tuple[set[str], list[dict[str, Any]]]:
    article_uids: set[str] = set()
    for row in iter_review_candidate_rows(repair_db):
        uid = text(row.get("source_article_uid"))
        if uid:
            article_uids.add(uid)
    candidate_keys = load_sidecar_event_keys(repair_db)
    no_candidate_rows = list(
        iter_no_candidate_events(source_db, candidate_keys, max_rows=max_no_candidate_rows)
    )
    for row in no_candidate_rows:
        uid = text(row.get("source_article_uid"))
        if uid:
            article_uids.add(uid)
    return article_uids, no_candidate_rows


def build_article_context_rows(
    *,
    source_db: Path,
    source_url_db: Path | None,
    article_uids: set[str],
    same_article_entities: dict[str, list[str]],
    max_article_text_chars: int,
) -> list[dict[str, Any]]:
    article_info = source_article_info(source_db, article_uids)
    source_url_index = load_source_url_index(source_url_db)
    rows: list[dict[str, Any]] = []
    for uid in sorted(article_uids):
        article = article_info.get(uid, {})
        source = source_url_index.get(uid, {})
        excerpt = ""
        raw_available = 0
        raw_path = text(source.get("archive_raw_html_path"))
        if raw_path and max_article_text_chars > 0:
            excerpt, ok = read_raw_html_excerpt(raw_path, max_chars=max_article_text_chars)
            raw_available = 1 if ok and excerpt else 0
        article_vector = text(article.get("article_vector_text"))
        context_chars = len(excerpt or article_vector)
        rows.append(
            {
                "article_context_id": stable_id("article_context", uid),
                "source_article_uid": uid,
                "source_ref_id": text(source.get("source_ref_id")),
                "source_hash": source_hash(source.get("source_url")),
                "source_account": text(article.get("source_account")) or text(uid.split("/", 1)[0]),
                "source_title": text(article.get("title")) or text(source.get("title")),
                "post_date": text(source.get("post_date")) or text(article.get("publish_time"))[:10],
                "match_basis": text(source.get("match_basis")),
                "source_url_available": 1 if text(source.get("source_url")) else 0,
                "raw_html_text_available": raw_available,
                "article_vector_text": article_vector,
                "article_text_excerpt": excerpt,
                "same_article_entities_json": json_dumps(same_article_entities.get(uid, [])),
                "context_chars": context_chars,
            }
        )
    return rows


def insert_article_contexts(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    conn.executemany(
        """
        INSERT INTO article_context (
            article_context_id, source_article_uid, source_ref_id, source_hash,
            source_account, source_title, post_date, match_basis,
            source_url_available, raw_html_text_available, article_vector_text,
            article_text_excerpt, same_article_entities_json, context_chars
        )
        VALUES (
            :article_context_id, :source_article_uid, :source_ref_id, :source_hash,
            :source_account, :source_title, :post_date, :match_basis,
            :source_url_available, :raw_html_text_available, :article_vector_text,
            :article_text_excerpt, :same_article_entities_json, :context_chars
        )
        """,
        rows,
    )


def queue_row_from_candidate(
    row: dict[str, Any],
    same_article_entities: dict[str, list[str]],
    generated_at: str,
) -> dict[str, Any] | None:
    candidate_names = parse_json_list(row.get("candidate_names_json"))
    candidate_names = [name for name in candidate_names if not is_known_non_dj_name(name)]
    if not candidate_names:
        return None
    if is_noise_event(row.get("event_name"), row.get("source_title"), " ".join(candidate_names)):
        return None
    lane = lane_for_candidate(row)
    uid = text(row.get("source_article_uid"))
    queue_id = stable_id(
        "participant_llm",
        lane,
        uid,
        row.get("event_id"),
        row.get("event_name"),
        row.get("time_text"),
        "|".join(candidate_names),
    )
    entities = same_article_entities.get(uid, [])
    return {
        "queue_id": queue_id,
        "llm_lane": lane,
        "priority_score": priority_for_candidate(row),
        "source_article_uid": uid,
        "event_key": text(row.get("event_key")),
        "event_id": text(row.get("event_id")),
        "event_name": text(row.get("event_name")),
        "time_text": text(row.get("time_text")),
        "place": text(row.get("place")),
        "city": "",
        "source_account": text(row.get("source_account")),
        "source_title": text(row.get("source_title")),
        "candidate_names_json": json_dumps(candidate_names),
        "candidate_count": len(candidate_names),
        "sidecar_confidence": float(row.get("confidence") or 0.0),
        "sidecar_tier": text(row.get("tier")),
        "basis_json": text(row.get("basis_json")),
        "same_article_entities_json": json_dumps(entities),
        "article_context_id": stable_id("article_context", uid),
        "event_vector_text": "",
        "decision_schema_json": json_dumps(decision_schema_for_lane(lane)),
        "write_status": "report_only_llm_input",
        "generated_at": generated_at,
    }


def queue_row_from_reextract(
    row: dict[str, Any],
    same_article_entities: dict[str, list[str]],
    generated_at: str,
) -> dict[str, Any]:
    uid = text(row.get("source_article_uid"))
    entities = same_article_entities.get(uid, [])
    lane = "llm_reextract_no_candidate"
    queue_id = stable_id(
        "participant_llm",
        lane,
        uid,
        row.get("evid"),
        row.get("name"),
        row.get("time_text"),
    )
    basis = {
        "method": "llm_reextract_from_article_context",
        "source_kind": text(row.get("source_kind")),
        "event_has_place": bool(text(row.get("place"))),
        "event_has_time_text": bool(text(row.get("time_text"))),
        "same_article_entity_count": len(entities),
    }
    return {
        "queue_id": queue_id,
        "llm_lane": lane,
        "priority_score": priority_for_reextract(row, entities),
        "source_article_uid": uid,
        "event_key": stable_id("event", uid, row.get("evid"), row.get("name"), row.get("time_text")),
        "event_id": text(row.get("evid")),
        "event_name": text(row.get("name")),
        "time_text": text(row.get("time_text")),
        "place": text(row.get("place")),
        "city": text(row.get("city")),
        "source_account": "",
        "source_title": "",
        "candidate_names_json": "[]",
        "candidate_count": 0,
        "sidecar_confidence": float(row.get("confidence") or 0.0),
        "sidecar_tier": "no_candidate",
        "basis_json": json_dumps(basis),
        "same_article_entities_json": json_dumps(entities),
        "article_context_id": stable_id("article_context", uid),
        "event_vector_text": text(row.get("event_vector_text")),
        "decision_schema_json": json_dumps(decision_schema_for_lane(lane)),
        "write_status": "report_only_llm_input",
        "generated_at": generated_at,
    }


def insert_queue_rows(conn: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> tuple[int, Counter]:
    lane_counts: Counter = Counter()
    inserted = 0
    sql = """
        INSERT OR IGNORE INTO participant_llm_queue (
            queue_id, llm_lane, priority_score, source_article_uid, event_key,
            event_id, event_name, time_text, place, city, source_account,
            source_title, candidate_names_json, candidate_count,
            sidecar_confidence, sidecar_tier, basis_json,
            same_article_entities_json, article_context_id, event_vector_text,
            decision_schema_json, write_status, generated_at
        )
        VALUES (
            :queue_id, :llm_lane, :priority_score, :source_article_uid, :event_key,
            :event_id, :event_name, :time_text, :place, :city, :source_account,
            :source_title, :candidate_names_json, :candidate_count,
            :sidecar_confidence, :sidecar_tier, :basis_json,
            :same_article_entities_json, :article_context_id, :event_vector_text,
            :decision_schema_json, :write_status, :generated_at
        )
    """
    for row in rows:
        before = conn.total_changes
        conn.execute(sql, row)
        if conn.total_changes > before:
            inserted += 1
            lane_counts[row["llm_lane"]] += 1
    return inserted, lane_counts


def export_table_jsonl(db_path: Path, table: str, out_path: Path, order_by: str) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = (row_dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}"))
        return write_jsonl(out_path, rows)
    finally:
        conn.close()


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Participant LLM Adjudication Queue V2",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "## Result",
        "",
        f"- Queue rows: `{summary['queue_rows']}`",
        f"- Article contexts: `{summary['article_context_rows']}`",
        f"- Review-candidate LLM rows: `{summary['review_candidate_rows']}`",
        f"- Re-extract no-candidate rows: `{summary['reextract_no_candidate_rows']}`",
        f"- Raw URL/path exposure in queue JSONL: `{summary['safety']['raw_url_or_path_exposure_hits']}`",
        "",
        "## Lane Counts",
        "",
    ]
    for lane, count in sorted(summary["lane_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- `{lane}`: `{count}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This is private/report-only LLM input.",
            "- No model/API call is made by this builder.",
            "- No source SQLite mutation, production write, graph/vector write, deploy, or upload is performed.",
            "- Raw article URLs and raw archive paths are not written to queue JSONL; only source hashes and article text excerpts are stored for private LLM use.",
            "",
            "## Next Gate",
            "",
            "Run `run_atlas_participant_llm_adjudication.py --execute --max-rows N` for a canary, then scale by lane after JSON schema and precision checks pass.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def count_raw_leaks(path: Path) -> int:
    if not path.exists():
        return 0
    pattern = re.compile(r"(mp\.weixin|raw\.html|D:\\|/mnt/d|archive_raw_html_path)", re.I)
    hits = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if pattern.search(line):
                hits += 1
    return hits


def build_queue(args: argparse.Namespace) -> dict[str, Any]:
    source_db = Path(args.source_db)
    repair_db = Path(args.repair_db)
    source_url_db = Path(args.source_url_db) if args.source_url_db else None
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = now_iso()

    article_uids, no_candidate_rows = collect_article_uids(
        source_db,
        repair_db,
        max_no_candidate_rows=args.max_no_candidate_rows,
    )
    same_article_entities = load_same_article_dj_entities(source_db, article_uids)
    article_context_rows = build_article_context_rows(
        source_db=source_db,
        source_url_db=source_url_db,
        article_uids=article_uids,
        same_article_entities=same_article_entities,
        max_article_text_chars=args.max_article_text_chars,
    )

    db_path = out_dir / "participant_llm_queue.sqlite"
    conn = create_output_db(db_path)
    review_rows = 0
    reextract_rows = 0
    lane_counts: Counter = Counter()
    try:
        insert_article_contexts(conn, article_context_rows)

        def candidate_rows() -> Iterable[dict[str, Any]]:
            nonlocal review_rows
            for row in iter_review_candidate_rows(repair_db):
                queued = queue_row_from_candidate(row, same_article_entities, generated_at)
                if not queued:
                    continue
                review_rows += 1
                yield queued

        inserted, candidate_lanes = insert_queue_rows(conn, candidate_rows())
        lane_counts.update(candidate_lanes)

        def reextract_queue_rows() -> Iterable[dict[str, Any]]:
            nonlocal reextract_rows
            for row in no_candidate_rows:
                queued = queue_row_from_reextract(row, same_article_entities, generated_at)
                reextract_rows += 1
                yield queued

        inserted_reextract, reextract_lanes = insert_queue_rows(conn, reextract_queue_rows())
        lane_counts.update(reextract_lanes)
        conn.commit()

        queue_rows = inserted + inserted_reextract
        safety = {
            "report_only": True,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "source_sqlite_write_executed": False,
            "production_write_executed": False,
            "graph_vector_write_executed": False,
            "deploy_or_upload_executed": False,
            "raw_url_or_path_exposure_hits": 0,
        }
        summary = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "source_db": str(source_db),
            "repair_db": str(repair_db),
            "source_url_db": str(source_url_db) if source_url_db else "",
            "out_dir": str(out_dir),
            "queue_sqlite": str(db_path),
            "queue_jsonl": str(out_dir / "participant_llm_queue.jsonl"),
            "article_context_jsonl": str(out_dir / "article_context.jsonl"),
            "article_context_rows": len(article_context_rows),
            "queue_rows": queue_rows,
            "review_candidate_rows": inserted,
            "reextract_no_candidate_rows": inserted_reextract,
            "lane_counts": dict(lane_counts),
            "safety": safety,
        }
        conn.execute(
            """
            INSERT INTO queue_run (
                generated_at, schema_version, source_db, repair_db,
                source_url_db, summary_json, safety_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generated_at,
                SCHEMA_VERSION,
                str(source_db),
                str(repair_db),
                str(source_url_db) if source_url_db else "",
                json_dumps(summary),
                json_dumps(safety),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    queue_jsonl = out_dir / "participant_llm_queue.jsonl"
    context_jsonl = out_dir / "article_context.jsonl"
    export_table_jsonl(db_path, "participant_llm_queue", queue_jsonl, "priority_score DESC, queue_id")
    export_table_jsonl(db_path, "article_context", context_jsonl, "source_article_uid")
    leaks = count_raw_leaks(queue_jsonl)
    summary["safety"]["raw_url_or_path_exposure_hits"] = leaks
    write_json(out_dir / "summary.json", summary)
    write_summary_md(out_dir / "summary.md", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB))
    parser.add_argument("--repair-db", default=str(DEFAULT_REPAIR_DB))
    parser.add_argument("--source-url-db", default=str(DEFAULT_SOURCE_URL_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--max-article-text-chars", type=int, default=6000)
    parser.add_argument("--max-no-candidate-rows", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_queue(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
