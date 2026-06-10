#!/usr/bin/env python3
"""Build deterministic low-cost repair sidecars for the DJ-first Atlas.

The source ``atlas.sqlite`` is treated as immutable evidence. This script
creates a separate overlay database with cheap, explainable candidates for the
fields that matter to the DJ product:

* participants inferred from same-article DJ/person entities
* venue/place inferred from source accounts and same-article place entities
* organizers inferred from source accounts and same-article org entities
* time candidates parsed from raw time text
* product/menu/drink entities quarantined out of the public DJ graph

No source DB writes, LLM calls, network calls, paid APIs, Neo4j writes, Qdrant
writes, or production writes are performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_local_sqlite_db_138102_20260521"
    / "atlas.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_low_cost_repair_sidecar_20260522"

DJ_TYPES = {"person", "dj", "artist"}
PLACE_TYPES = {"place", "venue", "location"}
ORG_TYPES = {
    "organization",
    "organizations",
    "organisation",
    "organiation",
    "organiztion",
    "organzation",
    "organziation",
    "organizer",
    "label",
    "group",
}
RADIO_HINTS = ["shcr", "byyb", "baihui", "baihui电台", "cdcr", "radio", "电台"]
VENUE_HINTS = [
    "oil",
    "dada",
    "all",
    "tag",
    "zhaodai",
    "招待",
    "heim",
    "hum",
    "44kw",
    "dng",
    "dong",
    "bo live",
    "elevator",
    "the window",
    "vervo",
    "echobay",
    "echo bay",
    "axis",
    "jar",
    "jar这儿",
    "foundation",
    "system",
    "live",
    "club",
    "bar",
    "俱乐部",
    "院吧",
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
]
NOISE_TERMS = [
    "葡萄酒",
    "红葡萄酒",
    "白葡萄酒",
    "酒单",
    "菜单",
    "咖啡",
    "餐厅",
    "下午茶",
    "精酿",
    "啤酒",
    "威士忌",
    "cocktail",
    "wine",
]
GENERIC_PLACE_NAMES = {
    "上海",
    "北京",
    "广州",
    "深圳",
    "成都",
    "武汉",
    "厦门",
    "昆明",
    "杭州",
    "重庆",
    "长沙",
    "西安",
    "南京",
    "苏州",
    "宁波",
    "天津",
    "福州",
    "青岛",
    "郑州",
    "沈阳",
    "大连",
    "香港",
    "台北",
    "中国",
}

FULL_DATE_PATTERNS = [
    re.compile(r"(?P<year>20\d{2})\s*[年./-]\s*(?P<month>\d{1,2})\s*[月./-]\s*(?P<day>\d{1,2})"),
    re.compile(r"(?P<year>20\d{2})\s*(?P<month>\d{2})(?P<day>\d{2})"),
]
MONTH_DAY_PATTERNS = [
    re.compile(r"(?<!\d)(?P<month>\d{1,2})\s*[./-]\s*(?P<day>\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日?"),
]
TIME_OF_DAY_RE = re.compile(r"(?P<hour>[012]?\d):(?P<minute>[0-5]\d)")
RELATIVE_TODAY_RE = re.compile(r"(今晚|今天|今日|tonight|today)", flags=re.IGNORECASE)
RELATIVE_TOMORROW_RE = re.compile(r"(明晚|明天|明日|tomorrow)", flags=re.IGNORECASE)
WEEKDAY_TERMS = [
    ("周一", 1),
    ("星期一", 1),
    ("礼拜一", 1),
    ("monday", 1),
    ("mon", 1),
    ("周二", 2),
    ("星期二", 2),
    ("礼拜二", 2),
    ("tuesday", 2),
    ("tue", 2),
    ("周三", 3),
    ("星期三", 3),
    ("礼拜三", 3),
    ("wednesday", 3),
    ("wed", 3),
    ("周四", 4),
    ("星期四", 4),
    ("礼拜四", 4),
    ("thursday", 4),
    ("thu", 4),
    ("周五", 5),
    ("星期五", 5),
    ("礼拜五", 5),
    ("friday", 5),
    ("fri", 5),
    ("周六", 6),
    ("星期六", 6),
    ("礼拜六", 6),
    ("saturday", 6),
    ("sat", 6),
    ("周日", 7),
    ("周天", 7),
    ("星期日", 7),
    ("星期天", 7),
    ("礼拜日", 7),
    ("礼拜天", 7),
    ("sunday", 7),
    ("sun", 7),
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def norm_text(value: Any) -> str:
    return str(value or "").strip()


def norm_key(value: Any) -> str:
    return re.sub(r"\s+", " ", norm_text(value).casefold())


def lower_blob(*values: Any) -> str:
    return " ".join(norm_key(value) for value in values if norm_text(value))


def contains_any(blob: str, terms: Iterable[str]) -> bool:
    return any(term.casefold() in blob for term in terms)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def parse_json_list(value: Any) -> list[str]:
    raw = norm_text(value)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [norm_text(item) for item in payload if norm_text(item)]


def stable_key(prefix: str, *parts: Any) -> str:
    blob = "\u241f".join(norm_text(part) for part in parts if norm_text(part))
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def event_key(row: dict[str, Any]) -> str:
    return stable_key("event", row.get("source_article_uid"), row.get("evid"), row.get("name"), row.get("time_text"))


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def clamp(value: float) -> float:
    return max(0.0, min(0.99, round(value, 4)))


def source_kind(source_account: Any) -> str:
    blob = norm_key(source_account)
    if contains_any(blob, RADIO_HINTS):
        return "radio"
    if contains_any(blob, VENUE_HINTS):
        return "venue"
    if contains_any(blob, ["records", "label", "厂牌", "crew", "collective"]):
        return "label_or_crew"
    return "unknown"


def source_is_music_context(row: dict[str, Any]) -> bool:
    blob = lower_blob(row.get("source_account"), row.get("title"), row.get("name"), row.get("vector_text_preview"))
    return contains_any(blob, MUSIC_TERMS) or source_kind(row.get("source_account")) in {"venue", "radio", "label_or_crew"}


def is_noise_only_context(row: dict[str, Any]) -> bool:
    blob = lower_blob(row.get("title"), row.get("name"), row.get("vector_text_preview"))
    return contains_any(blob, NOISE_TERMS) and not contains_any(blob, MUSIC_TERMS)


def is_generic_place_name(value: Any) -> bool:
    name = norm_text(value)
    if not name:
        return True
    return name in GENERIC_PLACE_NAMES


def unique_entity_names(rows: Iterable[dict[str, Any]], limit: int = 64) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for row in rows:
        name = norm_text(row.get("name"))
        key = norm_key(name)
        if not name or key in seen:
            continue
        if len(name) > 80:
            continue
        if contains_any(norm_key(name), NOISE_TERMS):
            continue
        seen.add(key)
        names.append(name)
        if limit and len(names) >= limit:
            break
    return names


def parse_time_candidate(time_text: Any, title: Any = "") -> dict[str, Any] | None:
    raw_time = norm_text(time_text)
    raw_title = norm_text(title)
    if not raw_time and not raw_title:
        return None
    blob = f"{raw_time} {raw_title}".strip()
    tod = TIME_OF_DAY_RE.search(blob)
    time_of_day = f"{int(tod.group('hour')):02d}:{int(tod.group('minute')):02d}:00" if tod else ""

    for pattern in FULL_DATE_PATTERNS:
        match = pattern.search(blob)
        if not match:
            continue
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return {
                "normalized_date": f"{year:04d}-{month:02d}-{day:02d}",
                "partial_date": "",
                "time_of_day": time_of_day,
                "precision": "date",
                "confidence": 0.88 if raw_time else 0.75,
                "parse_status": "full_date",
            }

    for pattern in MONTH_DAY_PATTERNS:
        match = pattern.search(blob)
        if not match:
            continue
        month = int(match.group("month"))
        day = int(match.group("day"))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return {
                "normalized_date": "",
                "partial_date": f"{month:02d}-{day:02d}",
                "time_of_day": time_of_day,
                "precision": "month_day_no_year",
                "confidence": 0.62,
                "parse_status": "partial_date",
            }

    if RELATIVE_TODAY_RE.search(blob):
        return {
            "normalized_date": "",
            "partial_date": "",
            "time_of_day": time_of_day,
            "precision": "relative_day",
            "confidence": 0.72 if raw_time else 0.62,
            "parse_status": "relative_today",
        }

    if RELATIVE_TOMORROW_RE.search(blob):
        return {
            "normalized_date": "",
            "partial_date": "",
            "time_of_day": time_of_day,
            "precision": "relative_day",
            "confidence": 0.70 if raw_time else 0.60,
            "parse_status": "relative_tomorrow",
        }

    week_blob = norm_key(blob)
    for term, weekday in WEEKDAY_TERMS:
        if term in week_blob:
            return {
                "normalized_date": "",
                "partial_date": f"weekday:{weekday}",
                "time_of_day": time_of_day,
                "precision": "relative_weekday",
                "confidence": 0.60 if raw_time else 0.52,
                "parse_status": "relative_weekday",
            }

    if time_of_day:
        return {
            "normalized_date": "",
            "partial_date": "",
            "time_of_day": time_of_day,
            "precision": "time_only",
            "confidence": 0.35,
            "parse_status": "time_only",
        }
    return None


def participant_confidence(event: dict[str, Any], names: list[str]) -> tuple[float, str]:
    score = 0.42
    if source_kind(event.get("source_account")) in {"venue", "radio", "label_or_crew"}:
        score += 0.16
    if norm_text(event.get("place")):
        score += 0.09
    if norm_text(event.get("time_text")):
        score += 0.09
    if int(event.get("event_count") or 0) == 1:
        score += 0.08
    if source_is_music_context(event):
        score += 0.1
    if len(names) > 20:
        score -= 0.08
    if len(names) <= 2:
        score -= 0.04
    confidence = clamp(score)
    tier = "auto_candidate" if confidence >= 0.74 and 1 <= len(names) <= 24 else "review_candidate"
    return confidence, tier


def venue_confidence(event: dict[str, Any], venue: str, basis: str) -> tuple[float, str]:
    score = 0.5
    if basis == "same_article_place_entity":
        score += 0.16
    if basis == "venue_source_account":
        score += 0.22
    if norm_text(event.get("time_text")):
        score += 0.06
    if source_is_music_context(event):
        score += 0.08
    if source_kind(venue) == "radio":
        score -= 0.4
    confidence = clamp(score)
    tier = "auto_candidate" if confidence >= 0.74 else "review_candidate"
    return confidence, tier


def organizer_confidence(event: dict[str, Any], orgs: list[str], basis: str) -> tuple[float, str]:
    score = 0.44
    if basis == "same_article_org_entity":
        score += 0.12
    if source_kind(event.get("source_account")) in {"radio", "venue", "label_or_crew"}:
        score += 0.18
    if source_is_music_context(event):
        score += 0.08
    if len(orgs) > 12:
        score -= 0.08
    confidence = clamp(score)
    tier = "auto_candidate" if confidence >= 0.74 and len(orgs) <= 8 else "review_candidate"
    return confidence, tier


def load_entities_by_article(conn: sqlite3.Connection, types: set[str]) -> dict[str, list[dict[str, Any]]]:
    placeholders = ",".join("?" for _ in types)
    sql = f"""
        SELECT source_article_uid, name, type, confidence
        FROM entities
        WHERE lower(COALESCE(type, '')) IN ({placeholders})
          AND trim(COALESCE(name, '')) <> ''
          AND trim(COALESCE(source_article_uid, '')) <> ''
        ORDER BY confidence DESC, name
    """
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute(sql, tuple(sorted(types))):
        data = row_dict(row)
        rows[norm_text(data["source_article_uid"])].append(data)
    return rows


def iter_events(conn: sqlite3.Connection) -> Iterable[dict[str, Any]]:
    sql = """
        SELECT
          ev.row_pk,
          ev.evid,
          ev.name,
          ev.place,
          ev.city,
          ev.time_iso,
          ev.time_text,
          ev.source_article_uid,
          ev.confidence,
          ev.participants_json,
          ev.organizers_json,
          ev.vector_text_preview,
          a.title,
          a.source_account,
          a.city_label,
          a.entity_count,
          a.event_count,
          a.local_image_count
        FROM events ev
        LEFT JOIN articles a ON a.article_uid = ev.source_article_uid
    """
    for row in conn.execute(sql):
        yield row_dict(row)


def build_sidecar_rows(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    person_entities = load_entities_by_article(conn, DJ_TYPES)
    place_entities = load_entities_by_article(conn, PLACE_TYPES)
    org_entities = load_entities_by_article(conn, ORG_TYPES)

    participant_rows: list[dict[str, Any]] = []
    venue_rows: list[dict[str, Any]] = []
    organizer_rows: list[dict[str, Any]] = []
    time_rows: list[dict[str, Any]] = []
    overlay_by_event: dict[str, dict[str, Any]] = {}

    for event in iter_events(conn):
        key = event_key(event)
        source_uid = norm_text(event.get("source_article_uid"))
        participants = parse_json_list(event.get("participants_json"))
        organizers = parse_json_list(event.get("organizers_json"))
        noise_only = is_noise_only_context(event)
        overlay = {
            "event_key": key,
            "source_article_uid": source_uid,
            "event_id": norm_text(event.get("evid")),
            "event_name": norm_text(event.get("name")),
            "source_account": norm_text(event.get("source_account")),
            "source_title": norm_text(event.get("title")),
            "existing_participant_count": len(participants),
            "existing_place": norm_text(event.get("place")),
            "existing_organizer_count": len(organizers),
            "time_text": norm_text(event.get("time_text")),
            "inferred_participants_json": "[]",
            "inferred_place": "",
            "inferred_organizers_json": "[]",
            "normalized_date": "",
            "partial_date": "",
            "repair_tier": "none",
            "ready_for_dj_rollup": 0,
        }

        if not participants and not noise_only:
            names = unique_entity_names(person_entities.get(source_uid, []), limit=48)
            if names and source_is_music_context(event):
                conf, tier = participant_confidence(event, names)
                row = {
                    "event_key": key,
                    "source_article_uid": source_uid,
                    "event_id": norm_text(event.get("evid")),
                    "event_name": norm_text(event.get("name")),
                    "time_text": norm_text(event.get("time_text")),
                    "place": norm_text(event.get("place")),
                    "source_account": norm_text(event.get("source_account")),
                    "source_title": norm_text(event.get("title")),
                    "candidate_names_json": json_dumps(names),
                    "candidate_count": len(names),
                    "confidence": conf,
                    "tier": tier,
                    "basis_json": json_dumps(
                        {
                            "method": "same_article_dj_person_entities",
                            "event_has_time_text": bool(norm_text(event.get("time_text"))),
                            "event_has_place": bool(norm_text(event.get("place"))),
                            "source_kind": source_kind(event.get("source_account")),
                        }
                    ),
                }
                participant_rows.append(row)
                overlay["inferred_participants_json"] = row["candidate_names_json"]
                overlay["repair_tier"] = tier

        if not norm_text(event.get("place")) and not noise_only:
            basis = ""
            venue = ""
            place_names = [
                name
                for name in unique_entity_names(place_entities.get(source_uid, []), limit=16)
                if not is_generic_place_name(name)
            ][:8]
            if place_names:
                venue = place_names[0]
                basis = "same_article_place_entity"
            elif source_kind(event.get("source_account")) == "venue":
                venue = norm_text(event.get("source_account"))
                basis = "venue_source_account"
            if venue and source_kind(venue) != "radio":
                conf, tier = venue_confidence(event, venue, basis)
                row = {
                    "event_key": key,
                    "source_article_uid": source_uid,
                    "event_id": norm_text(event.get("evid")),
                    "event_name": norm_text(event.get("name")),
                    "source_account": norm_text(event.get("source_account")),
                    "source_title": norm_text(event.get("title")),
                    "candidate_place": venue,
                    "confidence": conf,
                    "tier": tier,
                    "basis": basis,
                }
                venue_rows.append(row)
                overlay["inferred_place"] = venue
                if overlay["repair_tier"] == "none":
                    overlay["repair_tier"] = tier

        if not organizers and not noise_only:
            org_names = unique_entity_names(org_entities.get(source_uid, []), limit=16)
            basis = "same_article_org_entity"
            if not org_names and source_kind(event.get("source_account")) in {"radio", "venue", "label_or_crew"}:
                org_names = [norm_text(event.get("source_account"))]
                basis = "source_account_org"
            if org_names and source_is_music_context(event):
                conf, tier = organizer_confidence(event, org_names, basis)
                row = {
                    "event_key": key,
                    "source_article_uid": source_uid,
                    "event_id": norm_text(event.get("evid")),
                    "event_name": norm_text(event.get("name")),
                    "source_account": norm_text(event.get("source_account")),
                    "source_title": norm_text(event.get("title")),
                    "candidate_organizers_json": json_dumps(org_names),
                    "candidate_count": len(org_names),
                    "confidence": conf,
                    "tier": tier,
                    "basis": basis,
                }
                organizer_rows.append(row)
                overlay["inferred_organizers_json"] = row["candidate_organizers_json"]
                if overlay["repair_tier"] == "none":
                    overlay["repair_tier"] = tier

        if not norm_text(event.get("time_iso")):
            time_candidate = parse_time_candidate(event.get("time_text"), event.get("title"))
            if time_candidate:
                row = {
                    "event_key": key,
                    "source_article_uid": source_uid,
                    "event_id": norm_text(event.get("evid")),
                    "event_name": norm_text(event.get("name")),
                    "source_account": norm_text(event.get("source_account")),
                    "source_title": norm_text(event.get("title")),
                    "time_text": norm_text(event.get("time_text")),
                    **time_candidate,
                }
                time_rows.append(row)
                overlay["normalized_date"] = row["normalized_date"]
                overlay["partial_date"] = row["partial_date"]
                if overlay["repair_tier"] == "none":
                    overlay["repair_tier"] = "review_candidate"

        inferred_participants = parse_json_list(overlay["inferred_participants_json"])
        has_participants = bool(participants or inferred_participants)
        has_place = bool(overlay["existing_place"] or overlay["inferred_place"])
        has_time = bool(overlay["normalized_date"] or overlay["partial_date"] or overlay["time_text"])
        overlay["ready_for_dj_rollup"] = int(has_participants and (has_place or has_time))
        if overlay["repair_tier"] != "none" or overlay["ready_for_dj_rollup"]:
            overlay_by_event[key] = overlay

    noise_rows = build_noise_rows(conn)
    return {
        "participants": participant_rows,
        "venues": venue_rows,
        "organizers": organizer_rows,
        "times": time_rows,
        "noise": noise_rows,
        "overlay": list(overlay_by_event.values()),
    }


def build_noise_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    clauses = ["lower(COALESCE(e.type, '')) = 'product'"]
    args: list[str] = []
    for term in NOISE_TERMS:
        clauses.append("lower(COALESCE(e.name, '')) LIKE ?")
        args.append(f"%{term.casefold()}%")
    sql = f"""
        SELECT
          e.eid,
          e.name,
          e.type,
          e.source_article_uid,
          e.confidence,
          a.title,
          a.source_account
        FROM entities e
        LEFT JOIN articles a ON a.article_uid = e.source_article_uid
        WHERE {" OR ".join(clauses)}
        ORDER BY e.confidence DESC, e.source_article_uid, e.name
    """
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in conn.execute(sql, tuple(args)):
        data = row_dict(row)
        key = (norm_text(data.get("source_article_uid")), norm_text(data.get("eid")), norm_key(data.get("name")))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "entity_id": norm_text(data.get("eid")),
                "source_article_uid": norm_text(data.get("source_article_uid")),
                "name": norm_text(data.get("name")),
                "type": norm_text(data.get("type")),
                "source_account": norm_text(data.get("source_account")),
                "source_title": norm_text(data.get("title")),
                "confidence": float(data.get("confidence") or 0),
                "quarantine_layer": "domain_noise",
                "public_graph_visible": 0,
                "basis": "product_type_or_drink_menu_term",
            }
        )
    return rows


def create_sidecar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS repair_run;
        DROP TABLE IF EXISTS event_participant_candidates;
        DROP TABLE IF EXISTS event_venue_candidates;
        DROP TABLE IF EXISTS event_organizer_candidates;
        DROP TABLE IF EXISTS event_time_candidates;
        DROP TABLE IF EXISTS entity_domain_quarantine;
        DROP TABLE IF EXISTS event_repair_overlay;

        CREATE TABLE repair_run (
          run_id TEXT PRIMARY KEY,
          generated_at TEXT NOT NULL,
          source_db TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          safety_json TEXT NOT NULL
        );
        CREATE TABLE event_participant_candidates (
          event_key TEXT,
          source_article_uid TEXT,
          event_id TEXT,
          event_name TEXT,
          time_text TEXT,
          place TEXT,
          source_account TEXT,
          source_title TEXT,
          candidate_names_json TEXT,
          candidate_count INTEGER,
          confidence REAL,
          tier TEXT,
          basis_json TEXT
        );
        CREATE TABLE event_venue_candidates (
          event_key TEXT,
          source_article_uid TEXT,
          event_id TEXT,
          event_name TEXT,
          source_account TEXT,
          source_title TEXT,
          candidate_place TEXT,
          confidence REAL,
          tier TEXT,
          basis TEXT
        );
        CREATE TABLE event_organizer_candidates (
          event_key TEXT,
          source_article_uid TEXT,
          event_id TEXT,
          event_name TEXT,
          source_account TEXT,
          source_title TEXT,
          candidate_organizers_json TEXT,
          candidate_count INTEGER,
          confidence REAL,
          tier TEXT,
          basis TEXT
        );
        CREATE TABLE event_time_candidates (
          event_key TEXT,
          source_article_uid TEXT,
          event_id TEXT,
          event_name TEXT,
          source_account TEXT,
          source_title TEXT,
          time_text TEXT,
          normalized_date TEXT,
          partial_date TEXT,
          time_of_day TEXT,
          precision TEXT,
          confidence REAL,
          parse_status TEXT
        );
        CREATE TABLE entity_domain_quarantine (
          entity_id TEXT,
          source_article_uid TEXT,
          name TEXT,
          type TEXT,
          source_account TEXT,
          source_title TEXT,
          confidence REAL,
          quarantine_layer TEXT,
          public_graph_visible INTEGER,
          basis TEXT
        );
        CREATE TABLE event_repair_overlay (
          event_key TEXT PRIMARY KEY,
          source_article_uid TEXT,
          event_id TEXT,
          event_name TEXT,
          source_account TEXT,
          source_title TEXT,
          existing_participant_count INTEGER,
          existing_place TEXT,
          existing_organizer_count INTEGER,
          time_text TEXT,
          inferred_participants_json TEXT,
          inferred_place TEXT,
          inferred_organizers_json TEXT,
          normalized_date TEXT,
          partial_date TEXT,
          repair_tier TEXT,
          ready_for_dj_rollup INTEGER
        );

        CREATE INDEX idx_repair_participants_event ON event_participant_candidates(event_key);
        CREATE INDEX idx_repair_participants_source ON event_participant_candidates(source_article_uid);
        CREATE INDEX idx_repair_venues_event ON event_venue_candidates(event_key);
        CREATE INDEX idx_repair_venues_place ON event_venue_candidates(candidate_place);
        CREATE INDEX idx_repair_orgs_event ON event_organizer_candidates(event_key);
        CREATE INDEX idx_repair_times_event ON event_time_candidates(event_key);
        CREATE INDEX idx_repair_times_date ON event_time_candidates(normalized_date, partial_date);
        CREATE INDEX idx_repair_noise_name ON entity_domain_quarantine(name);
        CREATE INDEX idx_repair_overlay_ready ON event_repair_overlay(ready_for_dj_rollup, repair_tier);
        """
    )


def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    conn.executemany(sql, [[row.get(column) for column in columns] for row in rows])


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json_dumps(row))
            handle.write("\n")
    tmp.replace(path)


def maybe_limit(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return rows
    return rows[:limit]


def build_summary(source_db: Path, out_dir: Path, rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    participant_tiers = Counter(row["tier"] for row in rows["participants"])
    venue_tiers = Counter(row["tier"] for row in rows["venues"])
    organizer_tiers = Counter(row["tier"] for row in rows["organizers"])
    time_status = Counter(row["parse_status"] for row in rows["times"])
    top_sources = Counter()
    for layer in ("participants", "venues", "organizers", "times", "noise"):
        for row in rows[layer]:
            source = norm_text(row.get("source_account"))
            if source:
                top_sources[source] += 1
    return {
        "schema_version": "atlas_dj_low_cost_repair_sidecar.summary.v1",
        "generated_at": now_iso(),
        "source_db": str(source_db),
        "out_dir": str(out_dir),
        "sidecar_sqlite": str(out_dir / "atlas_dj_low_cost_repair_sidecar.sqlite"),
        "counts": {
            "participant_candidates": len(rows["participants"]),
            "venue_candidates": len(rows["venues"]),
            "organizer_candidates": len(rows["organizers"]),
            "time_candidates": len(rows["times"]),
            "noise_quarantine": len(rows["noise"]),
            "event_repair_overlay": len(rows["overlay"]),
            "ready_for_dj_rollup_overlay": sum(int(row.get("ready_for_dj_rollup") or 0) for row in rows["overlay"]),
        },
        "tiers": {
            "participants": dict(participant_tiers),
            "venues": dict(venue_tiers),
            "organizers": dict(organizer_tiers),
        },
        "time_parse_status": dict(time_status),
        "top_sources": [{"source_account": source, "count": count} for source, count in top_sources.most_common(30)],
        "safety": {
            "report_only": True,
            "source_sqlite_write_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
            "paid_api_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
        },
        "next_gate": [
            "Use event_repair_overlay as the DJ-first read overlay in graph rollups.",
            "Auto-accept only auto_candidate rows after spot-check; keep review_candidate rows behind review UI.",
            "Keep entity_domain_quarantine out of public search/graph seeds by default.",
        ],
    }


def write_markdown(path: Path, summary: dict[str, Any], rows: dict[str, list[dict[str, Any]]]) -> None:
    lines = [
        "# Atlas DJ Low-Cost Repair Sidecar",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_db: `{summary['source_db']}`",
        f"- sidecar_sqlite: `{summary['sidecar_sqlite']}`",
        "- write_status: `report_only`",
        "",
        "## Counts",
        "",
        "| Layer | Rows | Meaning |",
        "|---|---:|---|",
        f"| participants | {summary['counts']['participant_candidates']} | same-article DJ/person candidates for events missing participants |",
        f"| venues | {summary['counts']['venue_candidates']} | place candidates for events missing place |",
        f"| organizers | {summary['counts']['organizer_candidates']} | organizer/label/venue/radio candidates for events missing organizers |",
        f"| times | {summary['counts']['time_candidates']} | parsed date/partial-date candidates from raw time_text |",
        f"| noise | {summary['counts']['noise_quarantine']} | product/menu/drink rows quarantined from public DJ graph |",
        f"| overlay ready | {summary['counts']['ready_for_dj_rollup_overlay']} | event overlays that can feed DJ rollups after acceptance gate |",
        "",
        "## Auto Candidate Tiers",
        "",
        f"- participants: `{summary['tiers']['participants']}`",
        f"- venues: `{summary['tiers']['venues']}`",
        f"- organizers: `{summary['tiers']['organizers']}`",
        f"- time_parse_status: `{summary['time_parse_status']}`",
        "",
        "## Top Sources",
        "",
        "| Source | Count |",
        "|---|---:|",
    ]
    for row in summary["top_sources"][:20]:
        lines.append(f"| `{row['source_account']}` | {row['count']} |")

    samples = [
        ("participants", "event_name", "candidate_names_json"),
        ("venues", "event_name", "candidate_place"),
        ("organizers", "event_name", "candidate_organizers_json"),
        ("times", "event_name", "time_text"),
        ("noise", "name", "source_title"),
    ]
    lines.extend(["", "## Samples"])
    for layer, label_key, value_key in samples:
        lines.extend(["", f"### {layer}", "", "| Source | Label | Candidate | Tier/Status |", "|---|---|---|---|"])
        for row in rows[layer][:10]:
            tier = norm_text(row.get("tier") or row.get("parse_status") or row.get("quarantine_layer"))
            candidate = norm_text(row.get(value_key))
            if len(candidate) > 120:
                candidate = candidate[:117] + "..."
            lines.append(
                f"| `{norm_text(row.get('source_account'))}` | `{norm_text(row.get(label_key))}` | `{candidate}` | `{tier}` |"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_low_cost_repair_sidecar(source_db: Path, out_dir: Path, max_rows_per_layer: int = 0) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_conn = connect_readonly(source_db)
    try:
        rows = build_sidecar_rows(source_conn)
    finally:
        source_conn.close()

    for key in list(rows):
        rows[key] = maybe_limit(rows[key], max_rows_per_layer)

    sidecar_path = out_dir / "atlas_dj_low_cost_repair_sidecar.sqlite"
    if sidecar_path.exists():
        sidecar_path.unlink()
    sidecar_conn = sqlite3.connect(sidecar_path)
    try:
        create_sidecar_schema(sidecar_conn)
        safety = {
            "source_sqlite_write_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
            "paid_api_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
        }
        sidecar_conn.execute(
            "INSERT INTO repair_run VALUES (?, ?, ?, ?, ?)",
            (
                stable_key("repair_run", source_db, now_iso()),
                now_iso(),
                str(source_db),
                "atlas_dj_low_cost_repair_sidecar.v1",
                json_dumps(safety),
            ),
        )
        insert_rows(sidecar_conn, "event_participant_candidates", rows["participants"])
        insert_rows(sidecar_conn, "event_venue_candidates", rows["venues"])
        insert_rows(sidecar_conn, "event_organizer_candidates", rows["organizers"])
        insert_rows(sidecar_conn, "event_time_candidates", rows["times"])
        insert_rows(sidecar_conn, "entity_domain_quarantine", rows["noise"])
        insert_rows(sidecar_conn, "event_repair_overlay", rows["overlay"])
        sidecar_conn.commit()
    finally:
        sidecar_conn.close()

    write_jsonl(out_dir / "event_participant_candidates.jsonl", rows["participants"])
    write_jsonl(out_dir / "event_venue_candidates.jsonl", rows["venues"])
    write_jsonl(out_dir / "event_organizer_candidates.jsonl", rows["organizers"])
    write_jsonl(out_dir / "event_time_candidates.jsonl", rows["times"])
    write_jsonl(out_dir / "entity_domain_quarantine.jsonl", rows["noise"])
    write_jsonl(out_dir / "event_repair_overlay.jsonl", rows["overlay"])
    summary = build_summary(source_db, out_dir, rows)
    write_json(out_dir / "summary.json", summary)
    write_markdown(out_dir / "summary.md", summary, rows)
    return {"summary": summary, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--max-rows-per-layer",
        type=int,
        default=0,
        help="0 means full deterministic sidecar; positive values are for smoke tests.",
    )
    args = parser.parse_args()
    result = build_low_cost_repair_sidecar(args.db, args.out_dir, args.max_rows_per_layer)
    print(json_dumps({"ok": True, "summary": result["summary"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
