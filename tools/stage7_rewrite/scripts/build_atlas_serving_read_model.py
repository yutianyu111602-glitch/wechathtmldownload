#!/usr/bin/env python3
"""Build the public-safe Atlas serving read model.

The source Atlas database is the private archive. This script materializes a
separate SQLite read model for web/mobile serving: DJ-first search, historical
events, venue/org rollups, collaboration edges, evidence hashes, and bounded
graph windows. It never mutates the source DB and never copies raw source URLs
or archived HTML paths into the serving database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_atlas_dj_first_canary import (  # noqa: E402
    DEFAULT_CURATED_RULES,
    DEFAULT_DB,
    NOISE_TERMS,
    classify_place_text,
    connect_readonly,
    load_curated_rules,
    norm_key,
    norm_text,
    normalize_venue_name,
    parse_json_list,
    source_scoped_id,
    stable_id,
    write_json,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPAIR_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_low_cost_repair_sidecar_20260522"
    / "atlas_dj_low_cost_repair_sidecar.sqlite"
)
DEFAULT_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_source_url_recovery_20260522"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_TIME_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_event_time_normalized_sidecar_20260522"
    / "atlas_event_time_normalized_sidecar.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_serving_read_model_20260522"
CONFIRM_TOKEN = "RUN_ATLAS_SERVING_FULL"
PARTICIPANT_ACCEPTANCE_MODES = {"strict", "balanced", "aggressive-private"}
PUBLIC_TIME_TIERS = {"auto_candidate", "source_exact", "raw"}
TIME_TIER_PRIORITY = {"source_exact": 4, "raw": 3, "auto_candidate": 2, "review_candidate": 1}


GENERIC_NOISE_KEYS = {
    "tba",
    "tbA".casefold(),
    "guest",
    "guests",
    "special guest",
    "lineup",
    "阵容",
    "嘉宾",
    "更多",
    "未公布",
    "待定",
    "unknown",
    "various artists",
}
EXTRA_PRODUCT_NOISE_TERMS = {
    "报名",
    "付款",
    "购买",
    "购票",
    "买票",
    "售票",
    "票务",
    "预售",
    "预售倒计时",
    "预售截止",
    "二维码",
    "扫码",
    "客服",
    "订座",
    "招募",
    "白葡萄酒",
    "红酒",
    "葡萄酒",
    "鸡尾酒",
    "酒单",
    "酒类",
    "酒品",
    "酒款",
    "品酒",
    "品鉴",
    "酒精",
    "酒水",
    "啤酒",
    "精酿",
    "威士忌",
    "香槟",
    "cocktail",
    "beer",
    "whisky",
    "whiskey",
    "champagne",
    "tasting",
    "mulled wine",
    "wine tasting",
    "wine night",
    "wine",
    "入门卡",
    "优惠时段",
}
PUBLIC_TIME_NOISE_TERMS = {
    "报名",
    "付款",
    "购买",
    "购票",
    "买票",
    "售票",
    "票务",
    "预售",
    "预售倒计时",
    "预售截止",
    "二维码",
    "扫码",
    "客服",
    "订座",
    "招聘",
    "招募",
}
PUBLIC_EVENT_TITLE_NOISE_TERMS = PUBLIC_TIME_NOISE_TERMS | {
    "白葡萄酒",
    "红酒",
    "葡萄酒",
    "鸡尾酒",
    "酒精",
    "酒水",
    "啤酒",
    "精酿",
    "威士忌",
    "香槟",
    "cocktail",
    "beer",
    "whisky",
    "whiskey",
    "champagne",
    "tasting",
    "mulled wine",
    "wine tasting",
    "wine night",
    "wine",
    "入门卡",
    "优惠时段",
}
PUBLIC_EVENT_PERFORMANCE_SIGNAL_TERMS = {
    "dj",
    "live",
    "set",
    "rave",
    "party",
    "festival",
    "fest",
    "club",
    "klub",
    "vinyl",
    "night",
    "techno",
    "house",
    "bass",
    "hiphop",
    "hip hop",
    "open deck",
    "dance",
    "disco",
    "electro",
    "electronic",
    "electronica",
    "派对",
    "派對",
    "电子",
    "电音",
    "音乐",
    "音樂",
    "舞池",
    "地下",
    "锐舞",
    "摇滚",
    "黑胶",
    "黑膠",
    "跳舞",
}
PUBLIC_EVENT_SCHEDULE_TERMS = {"课程表", "排期", "schedule", "timetable"}
PUBLIC_EVENT_HARD_ADMIN_PHRASES = {"入门卡", "酒精优惠", "优惠时段"}
PUBLIC_EVENT_HARD_NON_MUSIC_TERMS = {"瑜伽", "下午茶", "酒店推荐", "吃小龙虾比赛"}
NON_DJ_CURATED_KINDS = {"radio", "venue", "label_org", "noise", "context", "music_context"}
GRAPH_NODE_LIMITS = {
    "collaborator": 28,
    "event": 20,
    "venue": 12,
    "org": 8,
}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def safe_sha(*parts: Any, length: int = 24) -> str:
    body = "\x1f".join(norm_text(part) for part in parts if norm_text(part))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:length]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not table_exists(conn, table_name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and norm_text(row.get(key)):
            return row.get(key)
    return ""


def load_overlay_rows(path: Path | None) -> tuple[dict[tuple[str, str], dict[str, Any]], set[str]]:
    overlay: dict[tuple[str, str], dict[str, Any]] = {}
    noise_names: set[str] = set()
    if not path or not path.exists():
        return overlay, noise_names
    conn = connect_readonly(path)
    try:
        if table_exists(conn, "event_repair_overlay"):
            for row in conn.execute(
                """
                SELECT
                  source_article_uid,
                  event_id,
                  event_name,
                  inferred_participants_json,
                  inferred_place,
                  inferred_organizers_json,
                  normalized_date,
                  partial_date,
                  repair_tier,
                  ready_for_dj_rollup
                FROM event_repair_overlay
                """
            ):
                item = row_dict(row)
                source_uid = norm_text(item.get("source_article_uid"))
                event_id = norm_text(item.get("event_id"))
                if source_uid and event_id:
                    overlay[(source_uid, event_id)] = item
        if table_exists(conn, "entity_domain_quarantine"):
            columns = table_columns(conn, "entity_domain_quarantine")
            visibility_expr = "public_graph_visible"
            if "public_graph_visible" not in columns:
                visibility_expr = "0"
            for row in conn.execute(
                f"""
                SELECT name, type, quarantine_layer, {visibility_expr} AS public_graph_visible
                FROM entity_domain_quarantine
                """
            ):
                item = row_dict(row)
                key = norm_key(item.get("name"))
                layer = norm_key(item.get("quarantine_layer"))
                raw_type = norm_key(item.get("type"))
                visible = int(item.get("public_graph_visible") or 0)
                if key and (not visible or "noise" in layer or raw_type == "product"):
                    noise_names.add(key)
    finally:
        conn.close()
    return overlay, noise_names


def load_participant_candidate_rows(path: Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    if not path or not path.exists():
        return rows
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "event_participant_candidates"):
            return rows
        for row in conn.execute(
            """
            SELECT
              source_article_uid,
              event_id,
              candidate_names_json,
              confidence,
              tier,
              basis_json
            FROM event_participant_candidates
            """
        ):
            item = row_dict(row)
            source_uid = norm_text(item.get("source_article_uid"))
            event_id = norm_text(item.get("event_id"))
            if source_uid and event_id:
                rows[(source_uid, event_id)] = item
    finally:
        conn.close()
    return rows


def load_time_rows(path: Path | None) -> dict[tuple[str, str], dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    if not path or not path.exists():
        return rows
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "event_time_normalized"):
            return rows
        for row in conn.execute(
            """
            SELECT
              source_article_uid,
              event_id,
              time_text,
              normalized_date,
              partial_date,
              precision,
              parse_status,
              confidence,
              review_tier,
              public_graph_visible
            FROM event_time_normalized
            """
        ):
            item = row_dict(row)
            source_uid = norm_text(item.get("source_article_uid"))
            event_id = norm_text(item.get("event_id"))
            if source_uid and event_id:
                key = (source_uid, event_id)
                existing = rows.get(key)
                if existing is None or time_row_rank(item) > time_row_rank(existing):
                    rows[key] = item
    finally:
        conn.close()
    return rows


def time_row_rank(item: dict[str, Any]) -> tuple[int, int, int, int, float]:
    normalized = int(bool(norm_text(item.get("normalized_date"))))
    if "public_graph_visible" in item and item.get("public_graph_visible") is not None:
        public_visible = int(item.get("public_graph_visible") or 0)
    else:
        public_visible = 1
    review_tier = norm_key(item.get("review_tier"))
    public_usable = int(bool(normalized and public_visible and review_tier in PUBLIC_TIME_TIERS))
    try:
        confidence = float(item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return (
        public_usable,
        normalized,
        public_visible,
        TIME_TIER_PRIORITY.get(review_tier, 0),
        confidence,
    )


def load_source_refs(path: Path | None) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    if not path or not path.exists():
        return refs
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "article_source_url"):
            return refs
        columns = table_columns(conn, "article_source_url")
        select_cols = [
            column
            for column in [
                "article_uid",
                "article_id",
                "source_ref_id",
                "source_account",
                "title",
                "post_date",
                "post_time",
                "match_basis",
            ]
            if column in columns
        ]
        if not select_cols:
            return refs
        for row in conn.execute(f"SELECT {', '.join(select_cols)} FROM article_source_url"):
            item = row_dict(row)
            article_uid = norm_text(item.get("article_uid"))
            if not article_uid:
                continue
            title = norm_text(item.get("title"))
            source_account = norm_text(item.get("source_account"))
            post_date = norm_text(item.get("post_date") or item.get("post_time"))
            source_ref_id = stable_id("src", article_uid, title, source_account)
            refs[article_uid] = {
                "source_ref_id": source_ref_id,
                "source_hash": safe_sha(article_uid, item.get("article_id"), title, source_account),
                "source_account": source_account,
                "source_title": title,
                "post_date": post_date,
                "source_kind": norm_text(item.get("match_basis") or "source_url_recovery"),
                "public_snippet": "",
                "public_url_allowed": 0,
            }
    finally:
        conn.close()
    return refs


def load_place_city_map(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute(
            """
            SELECT label, normalized_place, city
            FROM map_geocode_places
            WHERE city IS NOT NULL
              AND trim(city) != ''
            ORDER BY event_count DESC, article_count DESC, entity_count DESC
            """
        )
    except sqlite3.OperationalError:
        return {}
    city_by_place: dict[str, str] = {}
    for row in rows:
        city = norm_text(row["city"])
        if not city:
            continue
        for value in (row["label"], row["normalized_place"], normalize_venue_name(row["label"])):
            key = norm_key(value)
            if key and key not in city_by_place:
                city_by_place[key] = city
    return city_by_place


def curated_kind(value: Any, curated_rules: dict[str, dict[str, Any]]) -> str:
    return norm_key(curated_rules.get(norm_key(value), {}).get("kind"))


def curated_city(value: Any, curated_rules: dict[str, dict[str, Any]]) -> str:
    row = curated_rules.get(norm_key(value), {})
    return norm_text(row.get("city") or row.get("city_primary") or row.get("scene_city"))


def likely_noise_name(name: str, noise_names: set[str], curated_rules: dict[str, dict[str, Any]]) -> bool:
    key = norm_key(name)
    if not key or key in noise_names or key in GENERIC_NOISE_KEYS:
        return True
    kind = curated_kind(name, curated_rules)
    if kind == "noise":
        return True
    haystack = key
    if has_product_noise_text(haystack):
        return True
    if len(name) > 96:
        return True
    return False


def has_product_noise_text(*values: Any) -> bool:
    haystack = norm_key(" ".join(norm_text(value) for value in values if norm_text(value)))
    if not haystack:
        return False
    terms = {norm_key(term) for term in NOISE_TERMS} | {norm_key(term) for term in EXTRA_PRODUCT_NOISE_TERMS}
    return any(term and term in haystack for term in terms)


def has_public_event_performance_signal(*values: Any) -> bool:
    haystack = norm_key(" ".join(norm_text(value) for value in values if norm_text(value)))
    if not haystack:
        return False
    return any(norm_key(term) in haystack for term in PUBLIC_EVENT_PERFORMANCE_SIGNAL_TERMS)


def has_public_event_schedule_signal(*values: Any) -> bool:
    haystack = norm_key(" ".join(norm_text(value) for value in values if norm_text(value)))
    if not haystack:
        return False
    return any(norm_key(term) in haystack for term in PUBLIC_EVENT_SCHEDULE_TERMS)


def is_strong_product_admin_event_noise(
    title: Any,
    venue_name: Any,
    *,
    participant_count: int = 0,
    source_title: Any = "",
) -> bool:
    if not has_product_noise_text(title, venue_name, source_title):
        return False
    haystack = norm_key(" ".join(norm_text(value) for value in (title, source_title) if norm_text(value)))
    if any(norm_key(term) in haystack for term in PUBLIC_EVENT_HARD_NON_MUSIC_TERMS):
        return True
    if any(norm_key(term) in haystack for term in PUBLIC_EVENT_HARD_ADMIN_PHRASES):
        return True
    if has_public_event_performance_signal(title, source_title):
        return False
    if participant_count >= 3 and has_public_event_performance_signal(venue_name):
        return False
    if participant_count >= 2 and norm_text(venue_name) and has_public_event_schedule_signal(title, source_title):
        return False
    return True


def clean_public_time_text(value: Any) -> str:
    text = norm_text(value)
    if not text or not has_product_noise_text(text):
        return text
    term_re = "|".join(re.escape(term) for term in sorted(PUBLIC_TIME_NOISE_TERMS, key=len, reverse=True))
    text = re.sub(rf"[\(（][^\)）]*({term_re})[^\)）]*[\)）]", "", text)
    text = re.sub(rf"({term_re}).*$", "", text)
    return norm_text(text.strip(" \t\r\n-_/|·:：,，;；()（）[]【】"))


def clean_public_event_title(value: Any) -> str:
    text = norm_text(value)
    if not text or not has_product_noise_text(text):
        return text
    term_re = "|".join(re.escape(term) for term in sorted(PUBLIC_EVENT_TITLE_NOISE_TERMS, key=len, reverse=True))
    text = re.sub(rf"[\(（][^\)）]*({term_re})[^\)）]*[\)）]", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"^\s*({term_re})\s*([|｜:：·\\/\-]+)?\s*", "", text, flags=re.IGNORECASE)
    for _ in range(3):
        next_text = re.sub(rf"\s*({term_re})(已开启|开启|中|倒计时|截止|开始)?\s*", " ", text, flags=re.IGNORECASE)
        if next_text == text:
            break
        text = next_text
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([!！?？,，.。:：;；])", r"\1", text)
    return norm_text(text.strip(" \t\r\n-_/|·:：,，;；!?！？.。()（）[]【】"))


def is_candidate_dj_name(name: Any, noise_names: set[str], curated_rules: dict[str, dict[str, Any]]) -> bool:
    text = norm_text(name)
    key = norm_key(text)
    if likely_noise_name(text, noise_names, curated_rules):
        return False
    kind = curated_kind(text, curated_rules)
    if kind == "dj":
        return True
    if kind in NON_DJ_CURATED_KINDS:
        return False
    if classify_place_text(text, curated_rules) in {"venue", "radio", "noise"}:
        return False
    if key in {"all", "oil", "tag", "dada", "exit", "potent", "loopy"}:
        return False
    return bool(text)


def clean_names(
    values: Iterable[Any],
    noise_names: set[str],
    curated_rules: dict[str, dict[str, Any]],
    *,
    dj_only: bool,
    limit: int = 0,
) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        text = norm_text(value)
        key = norm_key(text)
        if not key or key in seen:
            continue
        if dj_only and not is_candidate_dj_name(text, noise_names, curated_rules):
            continue
        if not dj_only and likely_noise_name(text, noise_names, curated_rules):
            continue
        seen.add(key)
        rows.append(text)
        if limit and len(rows) >= limit:
            break
    return rows


def choose_display_name(counter: Counter[str]) -> str:
    if not counter:
        return ""
    return sorted(counter.items(), key=lambda item: (-item[1], len(item[0]), item[0].casefold()))[0][0]


def merge_min_date(current: str, candidate: str) -> str:
    candidate = norm_text(candidate)
    if not candidate:
        return current
    if not current or candidate < current:
        return candidate
    return current


def merge_max_date(current: str, candidate: str) -> str:
    candidate = norm_text(candidate)
    if not candidate:
        return current
    if not current or candidate > current:
        return candidate
    return current


def create_schema(conn: sqlite3.Connection) -> str:
    conn.executescript(
        """
        PRAGMA page_size = 4096;
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;

        CREATE TABLE canonical_subject (
          subject_id TEXT PRIMARY KEY,
          subject_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          taxon_path TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          city_primary TEXT,
          confidence REAL NOT NULL DEFAULT 0,
          source_count INTEGER NOT NULL DEFAULT 0,
          event_count INTEGER NOT NULL DEFAULT 0,
          relation_count INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          public_state TEXT NOT NULL
        );

        CREATE TABLE dj_profile (
          dj_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          city_primary TEXT,
          avatar_asset_id TEXT,
          source_article_count INTEGER NOT NULL DEFAULT 0,
          event_count INTEGER NOT NULL DEFAULT 0,
          venue_count INTEGER NOT NULL DEFAULT 0,
          collaborator_count INTEGER NOT NULL DEFAULT 0,
          organization_count INTEGER NOT NULL DEFAULT 0,
          media_count INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          confidence REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE performance_event (
          event_id TEXT PRIMARY KEY,
          event_title TEXT NOT NULL,
          starts_at TEXT,
          time_text TEXT,
          venue_id TEXT,
          venue_name TEXT,
          city TEXT,
          source_ref_id TEXT,
          participant_count INTEGER NOT NULL DEFAULT 0,
          organizer_count INTEGER NOT NULL DEFAULT 0,
          confidence REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE dj_event (
          dj_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          starts_at TEXT,
          time_text TEXT,
          event_title TEXT NOT NULL,
          venue_id TEXT,
          venue_name TEXT,
          city TEXT,
          source_ref_id TEXT,
          confidence REAL NOT NULL DEFAULT 0,
          PRIMARY KEY (dj_id, event_id, source_ref_id)
        );

        CREATE TABLE dj_relation_rollup (
          src_dj_id TEXT NOT NULL,
          dst_dj_id TEXT NOT NULL,
          same_event_count INTEGER NOT NULL DEFAULT 0,
          same_label_count INTEGER NOT NULL DEFAULT 0,
          same_venue_count INTEGER NOT NULL DEFAULT 0,
          same_source_context_count INTEGER NOT NULL DEFAULT 0,
          source_diversity INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          relation_score REAL NOT NULL DEFAULT 0,
          relation_label_zh TEXT NOT NULL,
          sample_evidence_json TEXT NOT NULL,
          public_state TEXT NOT NULL,
          PRIMARY KEY (src_dj_id, dst_dj_id)
        );

        CREATE TABLE dj_venue_rollup (
          dj_id TEXT NOT NULL,
          venue_id TEXT NOT NULL,
          venue_name TEXT NOT NULL,
          city TEXT,
          event_count INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          score REAL NOT NULL DEFAULT 0,
          PRIMARY KEY (dj_id, venue_id)
        );

        CREATE TABLE dj_org_rollup (
          dj_id TEXT NOT NULL,
          org_id TEXT NOT NULL,
          org_name TEXT NOT NULL,
          org_type TEXT NOT NULL,
          evidence_count INTEGER NOT NULL DEFAULT 0,
          score REAL NOT NULL DEFAULT 0,
          sample_evidence_json TEXT NOT NULL,
          PRIMARY KEY (dj_id, org_id)
        );

        CREATE TABLE evidence_ref (
          source_ref_id TEXT PRIMARY KEY,
          source_hash TEXT NOT NULL,
          source_account TEXT,
          source_title TEXT,
          post_date TEXT,
          public_snippet TEXT,
          source_kind TEXT,
          public_url_allowed INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE activity_event_detail (
          event_id TEXT PRIMARY KEY,
          source_event_id TEXT,
          publish_package TEXT,
          title TEXT,
          event_date_start TEXT,
          event_date_end TEXT,
          event_time_text TEXT,
          time_start TEXT,
          time_end TEXT,
          venue_name TEXT,
          venue_id TEXT,
          address TEXT,
          city_name TEXT,
          lineup_artists_json TEXT,
          music_styles_json TEXT,
          genres_json TEXT,
          price_json TEXT,
          ticketing_text TEXT,
          source_ref_id TEXT,
          source_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          generated_at TEXT
        );

        CREATE TABLE activity_evidence_ref (
          evidence_ref_id TEXT PRIMARY KEY,
          event_id TEXT,
          field_path TEXT,
          field_value TEXT,
          support_type TEXT,
          source_kind TEXT,
          source_ref_id TEXT,
          source_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          quote TEXT,
          quote_policy TEXT,
          ocr_span_id TEXT,
          ocr_span_status TEXT,
          confidence REAL,
          created_at TEXT
        );

        CREATE TABLE search_document (
          doc_rowid INTEGER PRIMARY KEY,
          subject_id TEXT NOT NULL,
          subject_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_text TEXT,
          city_text TEXT,
          taxon_path TEXT NOT NULL,
          rank_score REAL NOT NULL DEFAULT 0,
          last_seen_at TEXT,
          public_state TEXT NOT NULL,
          search_text TEXT NOT NULL
        );

        CREATE TABLE graph_window_cache (
          window_key TEXT PRIMARY KEY,
          seed_subject_id TEXT NOT NULL,
          lens TEXT NOT NULL,
          depth INTEGER NOT NULL,
          node_count INTEGER NOT NULL DEFAULT 0,
          edge_count INTEGER NOT NULL DEFAULT 0,
          nodes_json TEXT NOT NULL,
          edges_json TEXT NOT NULL,
          generated_at TEXT NOT NULL
        );

        CREATE TABLE build_metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )
    tokenizer = "trigram"
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE search_document_fts USING fts5(
              display_name,
              normalized_name,
              aliases_text,
              city_text,
              taxon_path,
              search_text,
              content='search_document',
              content_rowid='doc_rowid',
              tokenize='trigram'
            )
            """
        )
    except sqlite3.OperationalError:
        tokenizer = "unicode61"
        conn.execute(
            """
            CREATE VIRTUAL TABLE search_document_fts USING fts5(
              display_name,
              normalized_name,
              aliases_text,
              city_text,
              taxon_path,
              search_text,
              content='search_document',
              content_rowid='doc_rowid',
              tokenize='unicode61'
            )
            """
        )
    return tokenizer


def add_sample(samples: list[dict[str, Any]], sample: dict[str, Any], limit: int = 8) -> None:
    key = json_text(sample)
    seen = {json_text(item) for item in samples}
    if key not in seen and len(samples) < limit:
        samples.append(sample)


def event_public_id(row: dict[str, Any]) -> str:
    return stable_id(
        "event",
        row.get("source_article_uid"),
        row.get("row_pk"),
        row.get("evid"),
        row.get("name"),
        row.get("time_text"),
        row.get("place"),
    )


def source_ref_for_event(
    row: dict[str, Any],
    source_refs: dict[str, dict[str, Any]],
    evidence_refs: dict[str, dict[str, Any]],
) -> str:
    source_uid = norm_text(row.get("source_article_uid"))
    title = norm_text(row.get("source_title"))
    account = norm_text(row.get("source_account"))
    if source_uid in source_refs:
        ref = dict(source_refs[source_uid])
    else:
        ref = {
            "source_ref_id": stable_id("src", source_uid, title, account),
            "source_hash": safe_sha(source_uid, title, account),
            "source_account": account,
            "source_title": title,
            "post_date": norm_text(row.get("publish_time")),
            "source_kind": "atlas_article",
            "public_snippet": "",
            "public_url_allowed": 0,
        }
    ref["source_account"] = ref.get("source_account") or account
    ref["source_title"] = ref.get("source_title") or title
    ref["post_date"] = ref.get("post_date") or norm_text(row.get("publish_time"))
    evidence_refs[ref["source_ref_id"]] = ref
    return ref["source_ref_id"]


def load_activity_sidecar_rows(
    conn: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    if not table_exists(conn, "atlas_activity_events"):
        return [], {}
    events = [
        row_dict(row)
        for row in conn.execute(
            """
            SELECT *
            FROM atlas_activity_events
            ORDER BY COALESCE(event_date_start, ''), COALESCE(event_time_text, ''), COALESCE(title, ''), activity_event_id
            """
        )
    ]
    refs_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if table_exists(conn, "atlas_activity_evidence_refs"):
        for row in conn.execute(
            """
            SELECT *
            FROM atlas_activity_evidence_refs
            ORDER BY activity_event_id, field_path, evidence_ref_id
            """
        ):
            item = row_dict(row)
            refs_by_event[norm_text(item.get("activity_event_id"))].append(item)
    return events, refs_by_event


def activity_source_ref(row: dict[str, Any], evidence_refs: dict[str, dict[str, Any]]) -> str:
    source_article = json_object(row.get("source_article_json"))
    source_hash = norm_text(row.get("source_hash") or row.get("source_url_hash") or row.get("source_url_map_key"))
    account = norm_text(source_article.get("account_name") or row.get("source_account_name"))
    post_date = norm_text(source_article.get("published_at") or row.get("source_published_at") or row.get("event_date_start"))
    title = norm_text(row.get("title"))
    source_ref_id = stable_id("activity_src", source_hash, account, title, post_date)
    evidence_refs[source_ref_id] = {
        "source_ref_id": source_ref_id,
        "source_hash": safe_sha(source_hash, account, title, post_date),
        "source_account": account,
        "source_title": title,
        "post_date": post_date,
        "source_kind": "atlas_activity_sidecar",
        "public_snippet": "",
        "public_url_allowed": 0,
    }
    return source_ref_id


def ensure_delta_source_ref(source_ref_id: str, evidence_refs: dict[str, dict[str, Any]], row: dict[str, Any]) -> str:
    source_ref_id = norm_text(source_ref_id) or stable_id("delta_src", row.get("event_id"), row.get("event_title"))
    if source_ref_id not in evidence_refs:
        evidence_refs[source_ref_id] = {
            "source_ref_id": source_ref_id,
            "source_hash": safe_sha(source_ref_id),
            "source_account": "",
            "source_title": norm_text(row.get("event_title")),
            "post_date": norm_text(row.get("starts_at")),
            "source_kind": "participant_graph_delta",
            "public_snippet": "",
            "public_url_allowed": 0,
        }
    return source_ref_id


def load_participant_graph_delta(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    empty = {"events": [], "profiles": [], "dj_events": [], "relations": []}
    if not path:
        return empty
    if not path.exists():
        raise FileNotFoundError(path)
    conn = connect_readonly(path)
    try:
        tables = {
            "events": "graph_delta_event",
            "profiles": "graph_delta_dj_profile",
            "dj_events": "graph_delta_dj_event",
            "relations": "graph_delta_relation",
        }
        if not all(table_exists(conn, table) for table in tables.values()):
            raise ValueError(f"{path} is not a participant_graph_delta SQLite")
        return {
            key: [row_dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
            for key, table in tables.items()
        }
    finally:
        conn.close()


def load_review_accepted_event_ids(path: Path | None) -> set[str]:
    if not path:
        return set()
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    if path.suffix.lower() == ".json":
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(value, dict):
            rows = [row for row in value.get("accepted_events") or value.get("rows") or [] if isinstance(row, dict)]
        elif isinstance(value, list):
            rows = [row for row in value if isinstance(row, dict)]
    else:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    accepted: set[str] = set()
    for row in rows:
        event_id = norm_text(row.get("event_id"))
        if not event_id:
            continue
        if row.get("accepted_for_public_candidate") is True or norm_key(row.get("review_acceptance")) == "accepted_for_public_candidate":
            accepted.add(event_id)
    return accepted


def resolved_time(
    row: dict[str, Any],
    overlay: dict[str, Any] | None,
    time_row: dict[str, Any] | None,
) -> tuple[str, str]:
    starts_at = norm_text(row.get("time_iso"))
    if not starts_at and time_row:
        if "public_graph_visible" in time_row and time_row.get("public_graph_visible") is not None:
            visible = int(time_row.get("public_graph_visible") or 0)
        else:
            visible = 1
        review_tier = norm_key(time_row.get("review_tier"))
        if visible and review_tier in {"auto_candidate", "source_exact", "raw"}:
            starts_at = norm_text(time_row.get("normalized_date"))
    if not starts_at and overlay and norm_key(overlay.get("repair_tier")) == "auto_candidate":
        starts_at = norm_text(overlay.get("normalized_date"))
    time_text = norm_text(
        row.get("time_text")
        or (time_row or {}).get("time_text")
        or (time_row or {}).get("partial_date")
        or (overlay or {}).get("partial_date")
    )
    return starts_at, time_text


def resolved_participants(
    row: dict[str, Any],
    overlay: dict[str, Any] | None,
    participant_candidate: dict[str, Any] | None,
    noise_names: set[str],
    curated_rules: dict[str, dict[str, Any]],
    participant_acceptance: str,
) -> tuple[list[str], str]:
    participants = clean_names(parse_json_list(row.get("participants_json")), noise_names, curated_rules, dj_only=True)
    if participants:
        return participants, "raw"
    if not overlay:
        return [], "missing"
    if int(overlay.get("ready_for_dj_rollup") or 0) != 1:
        return [], "not_ready"
    repair_tier = norm_key(overlay.get("repair_tier"))
    if repair_tier != "auto_candidate":
        if repair_tier != "review_candidate":
            return [], "review_only"
        participants = clean_names(
            parse_json_list(overlay.get("inferred_participants_json")),
            noise_names,
            curated_rules,
            dj_only=True,
        )
        if not participants:
            return [], "missing"
        if participant_acceptance == "balanced" and safe_review_participant_candidate(participant_candidate, participants):
            return participants, "review_repair_balanced"
        if participant_acceptance == "aggressive-private":
            return participants, "review_repair_private"
        return [], "review_only"
    participants = clean_names(
        parse_json_list(overlay.get("inferred_participants_json")),
        noise_names,
        curated_rules,
        dj_only=True,
    )
    return participants, "auto_repair" if participants else "missing"


def safe_review_participant_candidate(candidate: dict[str, Any] | None, participants: list[str]) -> bool:
    if not candidate:
        return False
    if len(participants) > 16:
        return False
    if confidence(candidate.get("confidence")) < 0.70:
        return False
    try:
        basis = json.loads(candidate.get("basis_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        basis = {}
    if norm_key(candidate.get("tier")) != "review_candidate":
        return False
    if norm_key(basis.get("method")) != "same_article_dj_person_entities":
        return False
    if norm_key(basis.get("source_kind")) not in {"venue", "radio", "label_or_crew"}:
        return False
    return bool(basis.get("event_has_place") or basis.get("event_has_time_text"))


def resolved_place(
    row: dict[str, Any],
    overlay: dict[str, Any] | None,
    curated_rules: dict[str, dict[str, Any]],
) -> tuple[str, str, str]:
    candidates: list[tuple[str, str]] = []
    raw_place = norm_text(row.get("place"))
    if raw_place:
        candidates.append((raw_place, "raw"))
    if overlay and norm_key(overlay.get("repair_tier")) == "auto_candidate":
        inferred_place = norm_text(overlay.get("inferred_place"))
        if inferred_place:
            candidates.append((inferred_place, "auto_repair"))
    source_account = norm_text(row.get("source_account"))
    if source_account and classify_place_text(source_account, curated_rules) == "venue":
        candidates.append((source_account, "source_account_venue"))

    last_source = candidates[0][1] if candidates else ""
    for place, source in candidates:
        venue_name = normalize_venue_name(place)
        venue_kind = classify_place_text(venue_name, curated_rules)
        if venue_kind == "venue":
            return stable_id("venue", norm_key(venue_name)), venue_name, source
        last_source = source
    return "", "", last_source


def resolved_city(
    row: dict[str, Any],
    venue_name: str,
    city_by_place: dict[str, str],
    curated_rules: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    city = norm_text(row.get("city") or row.get("city_label"))
    if city:
        return city, "raw"
    city = curated_city(venue_name, curated_rules)
    if city:
        return city, "curated_venue"
    city = city_by_place.get(norm_key(venue_name))
    if city:
        return city, "venue_geocode"
    source_account = norm_text(row.get("source_account"))
    city = curated_city(source_account, curated_rules)
    if city:
        return city, "curated_source_account"
    city = city_by_place.get(norm_key(source_account))
    if city:
        return city, "source_account_geocode"
    return "", "missing"


def resolved_organizers(
    row: dict[str, Any],
    overlay: dict[str, Any] | None,
    noise_names: set[str],
    curated_rules: dict[str, dict[str, Any]],
) -> tuple[list[str], str]:
    organizers = clean_names(parse_json_list(row.get("organizers_json")), noise_names, curated_rules, dj_only=False)
    if organizers:
        return organizers, "raw"
    if overlay and norm_key(overlay.get("repair_tier")) == "auto_candidate":
        organizers = clean_names(
            parse_json_list(overlay.get("inferred_organizers_json")),
            noise_names,
            curated_rules,
            dj_only=False,
        )
        if organizers:
            return organizers, "auto_repair"
    return [], ""


def org_type_for(name: str, curated_rules: dict[str, dict[str, Any]]) -> str:
    kind = curated_kind(name, curated_rules)
    if kind in {"radio", "label_org"}:
        return kind
    return "organizer"


def insert_many(conn: sqlite3.Connection, sql: str, rows: list[tuple[Any, ...]]) -> None:
    if rows:
        conn.executemany(sql, rows)
        rows.clear()


def build_search_text(*parts: Any) -> str:
    tokens: list[str] = []
    for part in parts:
        if isinstance(part, list):
            tokens.extend(norm_text(item) for item in part if norm_text(item))
        else:
            text = norm_text(part)
            if text:
                tokens.append(text)
    return " ".join(tokens)


def relation_label(score: float, same_event_count: int, same_label_count: int) -> str:
    if same_event_count >= 5 or score >= 26:
        return "高频同台"
    if same_label_count >= 2:
        return "厂牌/组织关联"
    if same_event_count >= 2:
        return "多次同台"
    return "同台出现"


def build_graph_window(
    seed_dj_id: str,
    dj_names: dict[str, str],
    dj_aliases: dict[str, set[str]],
    relations_by_dj: dict[str, list[dict[str, Any]]],
    events_by_dj: dict[str, list[dict[str, Any]]],
    venues_by_dj: dict[str, list[dict[str, Any]]],
    orgs_by_dj: dict[str, list[dict[str, Any]]],
    generated_at: str,
) -> tuple[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def add_node(node_id: str, node_type: str, label: str, **attrs: Any) -> None:
        if not node_id or node_id in nodes:
            return
        nodes[node_id] = {"id": node_id, "type": node_type, "label": label, **attrs}

    def add_edge(edge_id: str, source: str, target: str, edge_type: str, weight: float, **attrs: Any) -> None:
        if not source or not target or edge_id in edges:
            return
        edges[edge_id] = {
            "id": edge_id,
            "source": source,
            "target": target,
            "type": edge_type,
            "weight": round(float(weight), 4),
            **attrs,
        }

    add_node(
        seed_dj_id,
        "dj",
        dj_names.get(seed_dj_id, seed_dj_id),
        role="seed",
        aliases=sorted(dj_aliases.get(seed_dj_id, set()))[:8],
    )
    for row in relations_by_dj.get(seed_dj_id, [])[: GRAPH_NODE_LIMITS["collaborator"]]:
        dst = row["dst_dj_id"]
        add_node(dst, "dj", dj_names.get(dst, dst), role="collaborator")
        add_edge(
            f"rel:{seed_dj_id}:{dst}",
            seed_dj_id,
            dst,
            "dj_collaboration",
            row["relation_score"],
            label=row["relation_label_zh"],
            same_event_count=row["same_event_count"],
        )
    for row in events_by_dj.get(seed_dj_id, [])[: GRAPH_NODE_LIMITS["event"]]:
        event_id = row["event_id"]
        add_node(event_id, "event", row["event_title"], starts_at=row.get("starts_at"), city=row.get("city"))
        add_edge(f"played:{seed_dj_id}:{event_id}", seed_dj_id, event_id, "performed_at", 3.0)
        if row.get("venue_id") and row.get("venue_name"):
            add_node(row["venue_id"], "venue", row["venue_name"], city=row.get("city"))
            add_edge(f"hosted:{event_id}:{row['venue_id']}", event_id, row["venue_id"], "hosted_at", 2.0)
    for row in venues_by_dj.get(seed_dj_id, [])[: GRAPH_NODE_LIMITS["venue"]]:
        venue_id = row["venue_id"]
        add_node(venue_id, "venue", row["venue_name"], city=row.get("city"))
        add_edge(f"venue:{seed_dj_id}:{venue_id}", seed_dj_id, venue_id, "frequent_venue", row["score"])
    for row in orgs_by_dj.get(seed_dj_id, [])[: GRAPH_NODE_LIMITS["org"]]:
        org_id = row["org_id"]
        add_node(org_id, row["org_type"], row["org_name"])
        add_edge(f"org:{seed_dj_id}:{org_id}", seed_dj_id, org_id, "organized_by", row["score"])

    window_key = stable_id("window", seed_dj_id, "dj_core", 2)
    payload = {
        "window_key": window_key,
        "seed_subject_id": seed_dj_id,
        "lens": "dj_core",
        "depth": 2,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes_json": json_text(list(nodes.values())),
        "edges_json": json_text(list(edges.values())),
        "generated_at": generated_at,
    }
    return window_key, payload


def build_serving_read_model(
    source_db: Path,
    out_dir: Path,
    *,
    repair_db: Path | None = DEFAULT_REPAIR_DB,
    time_db: Path | None = DEFAULT_TIME_DB,
    source_url_db: Path | None = DEFAULT_SOURCE_URL_DB,
    participant_delta_db: Path | None = None,
    participant_delta_accepted_events: Path | None = None,
    curated_rules_path: Path | None = DEFAULT_CURATED_RULES,
    graph_window_limit: int = 2000,
    max_events: int = 0,
    force: bool = False,
    confirm_production_candidate: str = "",
    participant_acceptance: str = "strict",
) -> dict[str, Any]:
    start = time.perf_counter()
    if not source_db.exists():
        raise FileNotFoundError(source_db)
    if max_events == 0 and confirm_production_candidate != CONFIRM_TOKEN:
        raise ValueError(f"Full build requires --confirm-production-candidate {CONFIRM_TOKEN}")
    if participant_acceptance not in PARTICIPANT_ACCEPTANCE_MODES:
        raise ValueError(f"participant_acceptance must be one of {sorted(PARTICIPANT_ACCEPTANCE_MODES)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    serving_db = out_dir / "atlas_serving.sqlite"
    if serving_db.exists():
        if not force:
            raise FileExistsError(f"{serving_db} exists; pass --force to replace")
        serving_db.unlink()

    curated_rules = load_curated_rules(curated_rules_path)
    overlay_rows, quarantine_noise = load_overlay_rows(repair_db)
    participant_candidate_rows = load_participant_candidate_rows(repair_db)
    time_rows = load_time_rows(time_db)
    source_refs = load_source_refs(source_url_db)
    participant_delta = load_participant_graph_delta(participant_delta_db)
    review_accepted_event_ids = load_review_accepted_event_ids(participant_delta_accepted_events)
    rule_noise = {key for key, row in curated_rules.items() if norm_key(row.get("kind")) == "noise"}
    noise_names = quarantine_noise | rule_noise

    source_conn = connect_readonly(source_db)
    city_by_place = load_place_city_map(source_conn)
    activity_rows, activity_refs_by_event = load_activity_sidecar_rows(source_conn)
    serving_conn = sqlite3.connect(serving_db)
    serving_conn.row_factory = sqlite3.Row
    fts_tokenizer = create_schema(serving_conn)

    generated_at = now_iso()
    evidence_refs: dict[str, dict[str, Any]] = {}
    event_records: dict[str, dict[str, Any]] = {}
    seen_event_ids: set[str] = set()

    dj_name_counts: dict[str, Counter[str]] = defaultdict(Counter)
    dj_aliases: dict[str, set[str]] = defaultdict(set)
    dj_cities: dict[str, Counter[str]] = defaultdict(Counter)
    dj_sources: dict[str, set[str]] = defaultdict(set)
    dj_events: dict[str, set[str]] = defaultdict(set)
    dj_first: dict[str, str] = defaultdict(str)
    dj_last: dict[str, str] = defaultdict(str)
    dj_confidence: dict[str, list[float]] = defaultdict(list)

    venue_names: dict[str, Counter[str]] = defaultdict(Counter)
    venue_cities: dict[str, Counter[str]] = defaultdict(Counter)
    venue_events: dict[str, set[str]] = defaultdict(set)
    venue_first: dict[str, str] = defaultdict(str)
    venue_last: dict[str, str] = defaultdict(str)

    org_names: dict[str, Counter[str]] = defaultdict(Counter)
    org_types: dict[str, str] = {}
    org_events: dict[str, set[str]] = defaultdict(set)

    venue_rollups: dict[tuple[str, str], dict[str, Any]] = {}
    org_rollups: dict[tuple[str, str], dict[str, Any]] = {}
    relations: dict[tuple[str, str], dict[str, Any]] = {}
    events_by_dj: dict[str, list[dict[str, Any]]] = defaultdict(list)

    dj_event_batch: list[tuple[Any, ...]] = []
    event_batch: list[tuple[Any, ...]] = []
    activity_detail_rows: list[tuple[Any, ...]] = []
    activity_evidence_rows: list[tuple[Any, ...]] = []

    stats = Counter()
    select_sql = """
        SELECT
          ev.evid,
          ev.row_pk,
          ev.name,
          ev.place,
          ev.city,
          ev.time_iso,
          ev.time_text,
          ev.source_article_uid,
          ev.confidence,
          ev.participants_json,
          ev.organizers_json,
          a.title AS source_title,
          a.source_account,
          a.publish_time,
          a.city_label
        FROM events ev
        LEFT JOIN articles a ON a.article_uid = ev.source_article_uid
        ORDER BY ev.row_pk
    """
    if max_events:
        select_sql += " LIMIT ?"
        event_iter = source_conn.execute(select_sql, (max_events,))
    else:
        event_iter = source_conn.execute(select_sql)

    for row in event_iter:
        stats["raw_events_seen"] += 1
        raw = row_dict(row)
        source_uid = norm_text(raw.get("source_article_uid"))
        local_event_id = norm_text(raw.get("evid"))
        overlay = overlay_rows.get((source_uid, local_event_id))
        participant_candidate = participant_candidate_rows.get((source_uid, local_event_id))
        time_row = time_rows.get((source_uid, local_event_id))
        if has_product_noise_text(
            raw.get("name"),
            raw.get("place"),
            raw.get("source_title"),
            (overlay or {}).get("inferred_place"),
        ):
            stats["events_skipped_product_noise"] += 1
            continue
        event_id = event_public_id(raw)
        if event_id in seen_event_ids:
            stats["duplicate_event_ids_skipped"] += 1
            continue
        participants, participant_source = resolved_participants(
            raw,
            overlay,
            participant_candidate,
            noise_names,
            curated_rules,
            participant_acceptance,
        )
        if not participants:
            stats[f"events_without_public_participants_{participant_source}"] += 1
            continue
        seen_event_ids.add(event_id)
        stats["events_with_public_participants"] += 1
        if participant_source == "auto_repair":
            stats["events_recovered_participants_auto"] += 1
        elif participant_source == "review_repair_balanced":
            stats["events_recovered_participants_review_balanced"] += 1
        elif participant_source == "review_repair_private":
            stats["events_recovered_participants_review_private"] += 1

        starts_at, time_text = resolved_time(raw, overlay, time_row)
        venue_id, venue_name, venue_source = resolved_place(raw, overlay, curated_rules)
        if venue_source == "auto_repair":
            stats["events_recovered_venue_auto"] += 1
        elif venue_source == "source_account_venue":
            stats["events_recovered_venue_source_account"] += 1
        organizers, organizer_source = resolved_organizers(raw, overlay, noise_names, curated_rules)
        if organizer_source == "auto_repair":
            stats["events_recovered_organizer_auto"] += 1

        city, city_source = resolved_city(raw, venue_name, city_by_place, curated_rules)
        if city_source == "venue_geocode":
            stats["events_recovered_city_venue_geocode"] += 1
        elif city_source == "curated_venue":
            stats["events_recovered_city_curated_venue"] += 1
        elif city_source == "curated_source_account":
            stats["events_recovered_city_curated_source_account"] += 1
        elif city_source == "source_account_geocode":
            stats["events_recovered_city_source_account_geocode"] += 1
        source_ref_id = source_ref_for_event(raw, source_refs, evidence_refs)
        event_title = norm_text(raw.get("name")) or "未命名活动"
        event_confidence = confidence(raw.get("confidence"))
        event_row = {
            "event_id": event_id,
            "event_title": event_title,
            "starts_at": starts_at,
            "time_text": time_text,
            "venue_id": venue_id,
            "venue_name": venue_name,
            "city": city,
            "source_ref_id": source_ref_id,
            "participant_count": len(participants),
            "organizer_count": len(organizers),
            "confidence": event_confidence,
        }
        event_records[event_id] = event_row
        event_batch.append(
            (
                event_id,
                event_title,
                starts_at,
                time_text,
                venue_id,
                venue_name,
                city,
                source_ref_id,
                len(participants),
                len(organizers),
                event_confidence,
            )
        )

        dj_ids: list[str] = []
        for name in participants:
            dj_id = stable_id("dj", norm_key(name))
            dj_ids.append(dj_id)
            dj_name_counts[dj_id][name] += 1
            dj_aliases[dj_id].add(name)
            if city:
                dj_cities[dj_id][city] += 1
            dj_sources[dj_id].add(source_ref_id)
            dj_events[dj_id].add(event_id)
            if starts_at:
                dj_first[dj_id] = merge_min_date(dj_first[dj_id], starts_at)
                dj_last[dj_id] = merge_max_date(dj_last[dj_id], starts_at)
            dj_confidence[dj_id].append(event_confidence)
            dj_event_batch.append(
                (
                    dj_id,
                    event_id,
                    starts_at,
                    time_text,
                    event_title,
                    venue_id,
                    venue_name,
                    city,
                    source_ref_id,
                    event_confidence,
                )
            )
            events_by_dj[dj_id].append(event_row)
            if venue_id and venue_name:
                key = (dj_id, venue_id)
                rollup = venue_rollups.setdefault(
                    key,
                    {
                        "dj_id": dj_id,
                        "venue_id": venue_id,
                        "venue_name": venue_name,
                        "city": city,
                        "event_count": 0,
                        "first_seen_at": "",
                        "last_seen_at": "",
                    },
                )
                rollup["event_count"] += 1
                rollup["first_seen_at"] = merge_min_date(rollup["first_seen_at"], starts_at)
                rollup["last_seen_at"] = merge_max_date(rollup["last_seen_at"], starts_at)
        if venue_id and venue_name:
            venue_names[venue_id][venue_name] += 1
            if city:
                venue_cities[venue_id][city] += 1
            venue_events[venue_id].add(event_id)
            venue_first[venue_id] = merge_min_date(venue_first[venue_id], starts_at)
            venue_last[venue_id] = merge_max_date(venue_last[venue_id], starts_at)

        org_ids: list[str] = []
        for org_name in organizers:
            org_type = org_type_for(org_name, curated_rules)
            org_id = stable_id("org", org_type, norm_key(org_name))
            org_ids.append(org_id)
            org_names[org_id][org_name] += 1
            org_types[org_id] = org_type
            org_events[org_id].add(event_id)
            for dj_id in dj_ids:
                key = (dj_id, org_id)
                rollup = org_rollups.setdefault(
                    key,
                    {
                        "dj_id": dj_id,
                        "org_id": org_id,
                        "org_name": org_name,
                        "org_type": org_type,
                        "evidence_count": 0,
                        "sample_evidence": [],
                    },
                )
                rollup["evidence_count"] += 1
                add_sample(
                    rollup["sample_evidence"],
                    {
                        "event_id": event_id,
                        "event_title": event_title,
                        "source_ref_id": source_ref_id,
                        "starts_at": starts_at,
                    },
                    limit=5,
                )

        relation_dj_ids = sorted(set(dj_ids))
        if len(relation_dj_ids) > 48:
            relation_dj_ids = relation_dj_ids[:48]
            stats["events_pair_cap_applied"] += 1
        relation_sample = {
            "event_id": event_id,
            "event_title": event_title,
            "venue_name": venue_name,
            "city": city,
            "starts_at": starts_at,
            "source_ref_id": source_ref_id,
        }
        for a, b in combinations(relation_dj_ids, 2):
            key = (a, b)
            rel = relations.setdefault(
                key,
                {
                    "a": a,
                    "b": b,
                    "same_event_count": 0,
                    "same_label_count": 0,
                    "same_venue_count": 0,
                    "same_source_context_count": 0,
                    "source_refs": set(),
                    "first_seen_at": "",
                    "last_seen_at": "",
                    "sample_evidence": [],
                },
            )
            rel["same_event_count"] += 1
            if venue_id:
                rel["same_venue_count"] += 1
            if org_ids:
                rel["same_label_count"] += 1
            rel["same_source_context_count"] += 1
            rel["source_refs"].add(source_ref_id)
            rel["first_seen_at"] = merge_min_date(rel["first_seen_at"], starts_at)
            rel["last_seen_at"] = merge_max_date(rel["last_seen_at"], starts_at)
            add_sample(rel["sample_evidence"], relation_sample, limit=5)

        if len(event_batch) >= 5000:
            insert_many(
                serving_conn,
                """
                INSERT OR REPLACE INTO performance_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                event_batch,
            )
        if len(dj_event_batch) >= 20000:
            insert_many(
                serving_conn,
                """
                INSERT OR IGNORE INTO dj_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                dj_event_batch,
            )

    for activity in activity_rows:
        stats["activity_events_seen"] += 1
        activity_event_id = norm_text(activity.get("activity_event_id"))
        if not activity_event_id:
            stats["activity_events_skipped_missing_id"] += 1
            continue
        title = norm_text(activity.get("title")) or "未命名活动"
        venue_name = normalize_venue_name(activity.get("venue_name"))
        city = norm_text(activity.get("city_name") or activity.get("city_key"))
        if activity_event_id in seen_event_ids:
            stats["activity_events_skipped_duplicate_event_id"] += 1
            continue
        seen_event_ids.add(activity_event_id)
        source_ref_id = activity_source_ref(activity, evidence_refs)
        starts_at = norm_text(activity.get("event_date_start"))
        time_text = norm_text(activity.get("event_time_text"))
        if not time_text:
            date_texts = [norm_text(item) for item in json_list(activity.get("event_date_text_json")) if norm_text(item)]
            time_text = " / ".join(date_texts[:3])
        venue_source_id = norm_text(activity.get("venue_id"))
        venue_id = stable_id("venue", norm_key(venue_source_id or venue_name), norm_key(city or venue_name)) if venue_name else ""
        participants = clean_names(
            json_list(activity.get("lineup_artists_json")),
            noise_names,
            curated_rules,
            dj_only=True,
            limit=80,
        )
        organizers: list[str] = []
        event_confidence = 0.88
        event_row = {
            "event_id": activity_event_id,
            "event_title": title,
            "starts_at": starts_at,
            "time_text": time_text,
            "venue_id": venue_id,
            "venue_name": venue_name,
            "city": city,
            "source_ref_id": source_ref_id,
            "participant_count": len(participants),
            "organizer_count": 0,
            "confidence": event_confidence,
        }
        event_records[activity_event_id] = event_row
        event_batch.append(
            (
                activity_event_id,
                title,
                starts_at,
                time_text,
                venue_id,
                venue_name,
                city,
                source_ref_id,
                len(participants),
                0,
                event_confidence,
            )
        )
        source_article = json_object(activity.get("source_article_json"))
        source_hash = norm_text(activity.get("source_hash") or activity.get("source_url_hash") or activity.get("source_url_map_key"))
        source_account_name = norm_text(source_article.get("account_name") or activity.get("source_account_name"))
        source_published_at = norm_text(source_article.get("published_at") or activity.get("source_published_at") or starts_at)
        activity_detail_rows.append(
            (
                activity_event_id,
                norm_text(activity.get("event_id")),
                norm_text(activity.get("publish_package")),
                title,
                starts_at,
                norm_text(activity.get("event_date_end")),
                norm_text(activity.get("event_time_text")),
                norm_text(activity.get("time_start")),
                norm_text(activity.get("time_end")),
                venue_name,
                venue_source_id,
                norm_text(activity.get("address")),
                city,
                json_text(json_list(activity.get("lineup_artists_json"))),
                json_text(json_list(activity.get("music_styles_json"))),
                json_text(json_list(activity.get("genres_json"))),
                json_text(json_list(activity.get("price_json"))),
                norm_text(activity.get("ticketing_text")),
                source_ref_id,
                source_hash,
                source_account_name,
                source_published_at,
                norm_text(activity.get("generated_at")),
            )
        )
        for ref in activity_refs_by_event.get(activity_event_id, []):
            activity_evidence_rows.append(
                (
                    norm_text(ref.get("evidence_ref_id")),
                    activity_event_id,
                    norm_text(ref.get("field_path")),
                    norm_text(ref.get("field_value")),
                    norm_text(ref.get("support_type")),
                    norm_text(ref.get("source_kind")),
                    source_ref_id,
                    norm_text(ref.get("source_hash") or ref.get("source_url_hash") or ref.get("source_url_map_key")),
                    norm_text(ref.get("source_account_name")),
                    norm_text(ref.get("source_published_at")),
                    norm_text(ref.get("quote")),
                    norm_text(ref.get("quote_policy")),
                    norm_text(ref.get("ocr_span_id")),
                    norm_text(ref.get("ocr_span_status")),
                    confidence(ref.get("confidence")),
                    norm_text(ref.get("created_at")),
                )
            )
        stats["activity_events_indexed"] += 1
        stats["activity_evidence_refs_indexed"] += len(activity_refs_by_event.get(activity_event_id, []))
        if not participants:
            stats["activity_events_without_public_lineup_participants"] += 1

        dj_ids: list[str] = []
        for name in participants:
            dj_id = stable_id("dj", norm_key(name))
            dj_ids.append(dj_id)
            dj_name_counts[dj_id][name] += 1
            dj_aliases[dj_id].add(name)
            if city:
                dj_cities[dj_id][city] += 1
            dj_sources[dj_id].add(source_ref_id)
            dj_events[dj_id].add(activity_event_id)
            if starts_at:
                dj_first[dj_id] = merge_min_date(dj_first[dj_id], starts_at)
                dj_last[dj_id] = merge_max_date(dj_last[dj_id], starts_at)
            dj_confidence[dj_id].append(event_confidence)
            dj_event_batch.append(
                (
                    dj_id,
                    activity_event_id,
                    starts_at,
                    time_text,
                    title,
                    venue_id,
                    venue_name,
                    city,
                    source_ref_id,
                    event_confidence,
                )
            )
            events_by_dj[dj_id].append(event_row)
            if venue_id and venue_name:
                key = (dj_id, venue_id)
                rollup = venue_rollups.setdefault(
                    key,
                    {
                        "dj_id": dj_id,
                        "venue_id": venue_id,
                        "venue_name": venue_name,
                        "city": city,
                        "event_count": 0,
                        "first_seen_at": "",
                        "last_seen_at": "",
                    },
                )
                rollup["event_count"] += 1
                rollup["first_seen_at"] = merge_min_date(rollup["first_seen_at"], starts_at)
                rollup["last_seen_at"] = merge_max_date(rollup["last_seen_at"], starts_at)
        if venue_id and venue_name:
            venue_names[venue_id][venue_name] += 1
            if city:
                venue_cities[venue_id][city] += 1
            venue_events[venue_id].add(activity_event_id)
            venue_first[venue_id] = merge_min_date(venue_first[venue_id], starts_at)
            venue_last[venue_id] = merge_max_date(venue_last[venue_id], starts_at)

        org_ids: list[str] = []
        relation_dj_ids = sorted(set(dj_ids))
        if len(relation_dj_ids) > 48:
            relation_dj_ids = relation_dj_ids[:48]
            stats["events_pair_cap_applied"] += 1
        relation_sample = {
            "event_id": activity_event_id,
            "event_title": title,
            "venue_name": venue_name,
            "city": city,
            "starts_at": starts_at,
            "source_ref_id": source_ref_id,
        }
        for a, b in combinations(relation_dj_ids, 2):
            key = (a, b)
            rel = relations.setdefault(
                key,
                {
                    "a": a,
                    "b": b,
                    "same_event_count": 0,
                    "same_label_count": 0,
                    "same_venue_count": 0,
                    "same_source_context_count": 0,
                    "source_refs": set(),
                    "first_seen_at": "",
                    "last_seen_at": "",
                    "sample_evidence": [],
                },
            )
            rel["same_event_count"] += 1
            if venue_id:
                rel["same_venue_count"] += 1
            if org_ids:
                rel["same_label_count"] += 1
            rel["same_source_context_count"] += 1
            rel["source_refs"].add(source_ref_id)
            rel["first_seen_at"] = merge_min_date(rel["first_seen_at"], starts_at)
            rel["last_seen_at"] = merge_max_date(rel["last_seen_at"], starts_at)
            add_sample(rel["sample_evidence"], relation_sample, limit=5)

    if participant_delta["events"] or participant_delta["dj_events"]:
        delta_profile_by_id = {norm_text(row.get("dj_id")): row for row in participant_delta["profiles"]}
        normalized_dj_ids: dict[str, str] = {}
        for dj_id, counts in dj_name_counts.items():
            for name in counts:
                key = norm_key(name)
                if key and key not in normalized_dj_ids:
                    normalized_dj_ids[key] = dj_id
        delta_dj_map: dict[str, str] = {}
        for profile in participant_delta["profiles"]:
            original_dj_id = norm_text(profile.get("dj_id"))
            name_key = norm_key(profile.get("normalized_name") or profile.get("display_name"))
            target_dj_id = normalized_dj_ids.get(name_key) or original_dj_id
            delta_dj_map[original_dj_id] = target_dj_id
            if target_dj_id != original_dj_id:
                stats["participant_delta_profiles_remapped_by_name"] += 1
            display_name = norm_text(profile.get("display_name"))
            if display_name:
                dj_name_counts[target_dj_id][display_name] += 1
                dj_aliases[target_dj_id].add(display_name)
                normalized_dj_ids.setdefault(name_key, target_dj_id)
            for alias in json_list(profile.get("aliases_json")):
                alias_text = norm_text(alias)
                if alias_text:
                    dj_aliases[target_dj_id].add(alias_text)
            first_seen = norm_text(profile.get("first_seen_at"))
            last_seen = norm_text(profile.get("last_seen_at"))
            dj_first[target_dj_id] = merge_min_date(dj_first[target_dj_id], first_seen)
            dj_last[target_dj_id] = merge_max_date(dj_last[target_dj_id], last_seen)
            dj_confidence[target_dj_id].append(confidence(profile.get("confidence")))

        blocked_participant_delta_event_ids: set[str] = set()
        for delta_event in participant_delta["events"]:
            event_id = norm_text(delta_event.get("event_id"))
            if not event_id or event_id in seen_event_ids:
                continue
            raw_title = norm_text(delta_event.get("event_title")) or "未命名活动"
            venue_name = normalize_venue_name(delta_event.get("venue_name"))
            participant_delta_count = int(delta_event.get("participant_delta_count") or 0)
            review_accepted = event_id in review_accepted_event_ids
            if not review_accepted and is_strong_product_admin_event_noise(
                raw_title,
                venue_name,
                participant_count=participant_delta_count,
            ):
                blocked_participant_delta_event_ids.add(event_id)
                stats["participant_delta_events_skipped_product_noise"] += 1
                continue
            if review_accepted:
                stats["participant_delta_events_review_accepted"] += 1
            title = clean_public_event_title(raw_title) or raw_title
            source_ref_id = ensure_delta_source_ref(delta_event.get("source_ref_id"), evidence_refs, delta_event)
            event_row = {
                "event_id": event_id,
                "event_title": title,
                "starts_at": norm_text(delta_event.get("starts_at")),
                "time_text": clean_public_time_text(delta_event.get("time_text")),
                "venue_id": norm_text(delta_event.get("venue_id")),
                "venue_name": venue_name,
                "city": norm_text(delta_event.get("city")),
                "source_ref_id": source_ref_id,
                "participant_count": participant_delta_count,
                "organizer_count": 0,
                "confidence": confidence(delta_event.get("confidence")),
            }
            seen_event_ids.add(event_id)
            event_records[event_id] = event_row
            event_batch.append(
                (
                    event_id,
                    event_row["event_title"],
                    event_row["starts_at"],
                    event_row["time_text"],
                    event_row["venue_id"],
                    event_row["venue_name"],
                    event_row["city"],
                    event_row["source_ref_id"],
                    event_row["participant_count"],
                    0,
                    event_row["confidence"],
                )
            )
            if event_row["venue_id"] and event_row["venue_name"]:
                venue_names[event_row["venue_id"]][event_row["venue_name"]] += 1
                if event_row["city"]:
                    venue_cities[event_row["venue_id"]][event_row["city"]] += 1
                venue_events[event_row["venue_id"]].add(event_id)
                venue_first[event_row["venue_id"]] = merge_min_date(venue_first[event_row["venue_id"]], event_row["starts_at"])
                venue_last[event_row["venue_id"]] = merge_max_date(venue_last[event_row["venue_id"]], event_row["starts_at"])
            stats["participant_delta_events_indexed"] += 1

        for delta_edge in participant_delta["dj_events"]:
            original_dj_id = norm_text(delta_edge.get("dj_id"))
            dj_id = delta_dj_map.get(original_dj_id, original_dj_id)
            event_id = norm_text(delta_edge.get("event_id"))
            if not dj_id or not event_id:
                continue
            if event_id in blocked_participant_delta_event_ids:
                stats["participant_delta_dj_events_skipped_blocked_event"] += 1
                continue
            event_row = event_records.get(event_id)
            if not event_row:
                review_accepted = event_id in review_accepted_event_ids
                if not review_accepted and is_strong_product_admin_event_noise(
                    delta_edge.get("event_title"),
                    delta_edge.get("venue_name"),
                    participant_count=1,
                ):
                    blocked_participant_delta_event_ids.add(event_id)
                    stats["participant_delta_dj_events_skipped_product_noise"] += 1
                    continue
                if review_accepted:
                    stats["participant_delta_dj_events_review_accepted"] += 1
                source_ref_id = ensure_delta_source_ref(delta_edge.get("source_ref_id"), evidence_refs, delta_edge)
                raw_title = norm_text(delta_edge.get("event_title")) or "未命名活动"
                event_row = {
                    "event_id": event_id,
                    "event_title": clean_public_event_title(raw_title) or raw_title,
                    "starts_at": norm_text(delta_edge.get("starts_at")),
                    "time_text": clean_public_time_text(delta_edge.get("time_text")),
                    "venue_id": norm_text(delta_edge.get("venue_id")),
                    "venue_name": normalize_venue_name(delta_edge.get("venue_name")),
                    "city": norm_text(delta_edge.get("city")),
                    "source_ref_id": source_ref_id,
                    "participant_count": 1,
                    "organizer_count": 0,
                    "confidence": confidence(delta_edge.get("confidence")),
                }
                event_records[event_id] = event_row
                event_batch.append(
                    (
                        event_id,
                        event_row["event_title"],
                        event_row["starts_at"],
                        event_row["time_text"],
                        event_row["venue_id"],
                        event_row["venue_name"],
                        event_row["city"],
                        event_row["source_ref_id"],
                        event_row["participant_count"],
                        0,
                        event_row["confidence"],
                    )
                )
            profile = delta_profile_by_id.get(original_dj_id, {})
            display_name = norm_text(profile.get("display_name")) or dj_id
            dj_name_counts[dj_id][display_name] += 1
            dj_aliases[dj_id].add(display_name)
            if event_row.get("city"):
                dj_cities[dj_id][event_row["city"]] += 1
            source_ref_id = ensure_delta_source_ref(delta_edge.get("source_ref_id") or event_row.get("source_ref_id"), evidence_refs, delta_edge)
            dj_sources[dj_id].add(source_ref_id)
            dj_events[dj_id].add(event_id)
            dj_first[dj_id] = merge_min_date(dj_first[dj_id], event_row.get("starts_at", ""))
            dj_last[dj_id] = merge_max_date(dj_last[dj_id], event_row.get("starts_at", ""))
            dj_confidence[dj_id].append(confidence(delta_edge.get("confidence")))
            dj_event_batch.append(
                (
                    dj_id,
                    event_id,
                    event_row.get("starts_at", ""),
                    event_row.get("time_text", ""),
                    event_row.get("event_title", ""),
                    event_row.get("venue_id", ""),
                    event_row.get("venue_name", ""),
                    event_row.get("city", ""),
                    source_ref_id,
                    confidence(delta_edge.get("confidence")),
                )
            )
            events_by_dj[dj_id].append(event_row)
            if event_row.get("venue_id") and event_row.get("venue_name"):
                key = (dj_id, event_row["venue_id"])
                rollup = venue_rollups.setdefault(
                    key,
                    {
                        "dj_id": dj_id,
                        "venue_id": event_row["venue_id"],
                        "venue_name": event_row["venue_name"],
                        "city": event_row.get("city", ""),
                        "event_count": 0,
                        "first_seen_at": "",
                        "last_seen_at": "",
                    },
                )
                rollup["event_count"] += 1
                rollup["first_seen_at"] = merge_min_date(rollup["first_seen_at"], event_row.get("starts_at", ""))
                rollup["last_seen_at"] = merge_max_date(rollup["last_seen_at"], event_row.get("starts_at", ""))
            stats["participant_delta_dj_events_indexed"] += 1

        seen_delta_relation_pairs: set[tuple[str, str]] = set()
        for delta_relation in participant_delta["relations"]:
            src = delta_dj_map.get(norm_text(delta_relation.get("src_dj_id")), norm_text(delta_relation.get("src_dj_id")))
            dst = delta_dj_map.get(norm_text(delta_relation.get("dst_dj_id")), norm_text(delta_relation.get("dst_dj_id")))
            if not src or not dst or src == dst:
                stats["participant_delta_relation_self_edges_skipped"] += 1
                continue
            key = tuple(sorted((src, dst)))
            if key in seen_delta_relation_pairs:
                continue
            seen_delta_relation_pairs.add(key)
            samples = [sample for sample in json_list(delta_relation.get("sample_evidence_json"))[:5] if isinstance(sample, dict)]
            if any(norm_text(sample.get("event_id")) in blocked_participant_delta_event_ids for sample in samples):
                stats["participant_delta_relations_skipped_blocked_events"] += 1
                continue
            increment = int(delta_relation.get("same_event_increment") or 0)
            rel = relations.setdefault(
                key,
                {
                    "a": key[0],
                    "b": key[1],
                    "same_event_count": 0,
                    "same_label_count": 0,
                    "same_venue_count": 0,
                    "same_source_context_count": 0,
                    "source_refs": set(),
                    "first_seen_at": "",
                    "last_seen_at": "",
                    "sample_evidence": [],
                },
            )
            rel["same_event_count"] += increment
            rel["same_source_context_count"] += increment
            rel["first_seen_at"] = merge_min_date(rel["first_seen_at"], delta_relation.get("first_seen_at"))
            rel["last_seen_at"] = merge_max_date(rel["last_seen_at"], delta_relation.get("last_seen_at"))
            for sample in samples:
                source_ref_id = norm_text(sample.get("source_ref_id"))
                if source_ref_id:
                    rel["source_refs"].add(source_ref_id)
                add_sample(rel["sample_evidence"], sample, limit=5)
            stats["participant_delta_relations_indexed"] += 1

    insert_many(serving_conn, "INSERT OR REPLACE INTO performance_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", event_batch)
    insert_many(serving_conn, "INSERT OR IGNORE INTO dj_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", dj_event_batch)
    source_conn.close()

    dj_display_names = {dj_id: choose_display_name(counter) for dj_id, counter in dj_name_counts.items()}
    venue_display_names = {venue_id: choose_display_name(counter) for venue_id, counter in venue_names.items()}
    org_display_names = {org_id: choose_display_name(counter) for org_id, counter in org_names.items()}

    relation_rows: list[tuple[Any, ...]] = []
    relations_by_dj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rel in relations.values():
        source_diversity = len(rel["source_refs"])
        score = (
            rel["same_event_count"] * 4.0
            + rel["same_label_count"] * 2.5
            + rel["same_venue_count"] * 0.5
            + source_diversity * 2.0
        )
        label = relation_label(score, rel["same_event_count"], rel["same_label_count"])
        base = {
            "same_event_count": rel["same_event_count"],
            "same_label_count": rel["same_label_count"],
            "same_venue_count": rel["same_venue_count"],
            "same_source_context_count": rel["same_source_context_count"],
            "source_diversity": source_diversity,
            "first_seen_at": rel["first_seen_at"],
            "last_seen_at": rel["last_seen_at"],
            "relation_score": round(score, 4),
            "relation_label_zh": label,
            "sample_evidence_json": json_text(rel["sample_evidence"]),
            "public_state": "public_rollup",
        }
        for src, dst in [(rel["a"], rel["b"]), (rel["b"], rel["a"])]:
            row = {"src_dj_id": src, "dst_dj_id": dst, **base}
            relations_by_dj[src].append(row)
            relation_rows.append(
                (
                    src,
                    dst,
                    base["same_event_count"],
                    base["same_label_count"],
                    base["same_venue_count"],
                    base["same_source_context_count"],
                    base["source_diversity"],
                    base["first_seen_at"],
                    base["last_seen_at"],
                    base["relation_score"],
                    base["relation_label_zh"],
                    base["sample_evidence_json"],
                    base["public_state"],
                )
            )
    serving_conn.executemany(
        """
        INSERT INTO dj_relation_rollup VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        relation_rows,
    )
    for rows in relations_by_dj.values():
        rows.sort(key=lambda item: (-item["relation_score"], -item["same_event_count"], item["dst_dj_id"]))

    venue_rows: list[tuple[Any, ...]] = []
    venues_by_dj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in venue_rollups.values():
        row["score"] = round(row["event_count"] * 3.0, 4)
        venues_by_dj[row["dj_id"]].append(row)
        venue_rows.append(
            (
                row["dj_id"],
                row["venue_id"],
                row["venue_name"],
                row["city"],
                row["event_count"],
                row["first_seen_at"],
                row["last_seen_at"],
                row["score"],
            )
        )
    serving_conn.executemany("INSERT INTO dj_venue_rollup VALUES (?, ?, ?, ?, ?, ?, ?, ?)", venue_rows)
    for rows in venues_by_dj.values():
        rows.sort(key=lambda item: (-item["score"], item["venue_name"]))

    org_rows: list[tuple[Any, ...]] = []
    orgs_by_dj: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in org_rollups.values():
        row["score"] = round(row["evidence_count"] * 2.0, 4)
        orgs_by_dj[row["dj_id"]].append(row)
        org_rows.append(
            (
                row["dj_id"],
                row["org_id"],
                row["org_name"],
                row["org_type"],
                row["evidence_count"],
                row["score"],
                json_text(row["sample_evidence"]),
            )
        )
    serving_conn.executemany("INSERT INTO dj_org_rollup VALUES (?, ?, ?, ?, ?, ?, ?)", org_rows)
    for rows in orgs_by_dj.values():
        rows.sort(key=lambda item: (-item["score"], item["org_name"]))
    for rows in events_by_dj.values():
        rows.sort(key=lambda item: (item.get("starts_at") or "", item.get("event_title") or ""), reverse=True)

    evidence_rows = [
        (
            ref["source_ref_id"],
            ref["source_hash"],
            ref.get("source_account", ""),
            ref.get("source_title", ""),
            ref.get("post_date", ""),
            ref.get("public_snippet", ""),
            ref.get("source_kind", ""),
            int(ref.get("public_url_allowed") or 0),
        )
        for ref in evidence_refs.values()
    ]
    serving_conn.executemany("INSERT OR REPLACE INTO evidence_ref VALUES (?, ?, ?, ?, ?, ?, ?, ?)", evidence_rows)
    serving_conn.executemany(
        """
        INSERT OR REPLACE INTO activity_event_detail VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        activity_detail_rows,
    )
    serving_conn.executemany(
        """
        INSERT OR REPLACE INTO activity_evidence_ref VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        activity_evidence_rows,
    )

    subject_rows: list[tuple[Any, ...]] = []
    profile_rows: list[tuple[Any, ...]] = []
    search_rows: list[tuple[Any, ...]] = []
    doc_rowid = 0
    for dj_id, display_name in dj_display_names.items():
        aliases = sorted(dj_aliases[dj_id], key=lambda item: (item.casefold() != display_name.casefold(), item.casefold()))[:24]
        city = dj_cities[dj_id].most_common(1)[0][0] if dj_cities[dj_id] else ""
        relation_count = len(relations_by_dj.get(dj_id, []))
        event_count = len(dj_events[dj_id])
        confidence_avg = round(sum(dj_confidence[dj_id]) / max(len(dj_confidence[dj_id]), 1), 4)
        subject_rows.append(
            (
                dj_id,
                "dj",
                display_name,
                norm_key(display_name),
                "音乐人/DJ",
                json_text(aliases),
                city,
                confidence_avg,
                len(dj_sources[dj_id]),
                event_count,
                relation_count,
                dj_first[dj_id],
                dj_last[dj_id],
                "public_rollup",
            )
        )
        profile_rows.append(
            (
                dj_id,
                display_name,
                norm_key(display_name),
                json_text(aliases),
                city,
                "",
                len(dj_sources[dj_id]),
                event_count,
                len(venues_by_dj.get(dj_id, [])),
                relation_count,
                len(orgs_by_dj.get(dj_id, [])),
                0,
                dj_first[dj_id],
                dj_last[dj_id],
                confidence_avg,
            )
        )
        doc_rowid += 1
        search_text = build_search_text(display_name, aliases, city, "DJ 音乐人 artist performer", len(dj_events[dj_id]))
        search_rows.append(
            (
                doc_rowid,
                dj_id,
                "dj",
                display_name,
                norm_key(display_name),
                " ".join(aliases),
                city,
                "音乐人/DJ",
                event_count * 10 + relation_count * 2 + len(dj_sources[dj_id]),
                dj_last[dj_id],
                "public_rollup",
                search_text,
            )
        )

    for venue_id, display_name in venue_display_names.items():
        city = venue_cities[venue_id].most_common(1)[0][0] if venue_cities[venue_id] else ""
        event_count = len(venue_events[venue_id])
        subject_rows.append(
            (
                venue_id,
                "venue",
                display_name,
                norm_key(display_name),
                "场地/俱乐部",
                json_text(sorted(venue_names[venue_id].keys())[:16]),
                city,
                0.9,
                0,
                event_count,
                0,
                venue_first[venue_id],
                venue_last[venue_id],
                "public_rollup",
            )
        )
        doc_rowid += 1
        search_rows.append(
            (
                doc_rowid,
                venue_id,
                "venue",
                display_name,
                norm_key(display_name),
                " ".join(sorted(venue_names[venue_id].keys())[:16]),
                city,
                "场地/俱乐部",
                event_count * 8,
                venue_last[venue_id],
                "public_rollup",
                build_search_text(display_name, city, "俱乐部 场地 club venue"),
            )
        )

    for org_id, display_name in org_display_names.items():
        org_type = org_types.get(org_id, "organizer")
        event_count = len(org_events[org_id])
        taxon = "电台/媒体" if org_type == "radio" else "厂牌/Crew/主办"
        subject_rows.append(
            (
                org_id,
                org_type,
                display_name,
                norm_key(display_name),
                taxon,
                json_text(sorted(org_names[org_id].keys())[:16]),
                "",
                0.85,
                0,
                event_count,
                0,
                "",
                "",
                "public_rollup",
            )
        )
        doc_rowid += 1
        search_rows.append(
            (
                doc_rowid,
                org_id,
                org_type,
                display_name,
                norm_key(display_name),
                " ".join(sorted(org_names[org_id].keys())[:16]),
                "",
                taxon,
                event_count * 6,
                "",
                "public_rollup",
                build_search_text(display_name, taxon, "厂牌 crew label radio 主办"),
            )
        )

    # Event search documents are useful for historical archive lookup, but they
    # stay URL-free and evidence-hash backed.
    for event in event_records.values():
        doc_rowid += 1
        search_rows.append(
            (
                doc_rowid,
                event["event_id"],
                "event",
                event["event_title"],
                norm_key(event["event_title"]),
                event.get("venue_name", ""),
                event.get("city", ""),
                "历史活动/演出",
                2 + event.get("participant_count", 0),
                event.get("starts_at", ""),
                "public_rollup",
                build_search_text(
                    event["event_title"],
                    event.get("venue_name", ""),
                    event.get("city", ""),
                    "历史活动 演出 event party",
                ),
            )
        )

    serving_conn.executemany("INSERT INTO canonical_subject VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", subject_rows)
    serving_conn.executemany("INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", profile_rows)
    serving_conn.executemany(
        """
        INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        search_rows,
    )
    serving_conn.executemany(
        """
        INSERT INTO search_document_fts(
          rowid, display_name, normalized_name, aliases_text, city_text, taxon_path, search_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (row[0], row[3], row[4], row[5], row[6], row[7], row[11])
            for row in search_rows
        ],
    )

    graph_seed_ids = sorted(
        dj_display_names,
        key=lambda dj_id: (-len(dj_events[dj_id]), -len(relations_by_dj.get(dj_id, [])), dj_display_names[dj_id].casefold()),
    )
    if graph_window_limit > 0:
        graph_seed_ids = graph_seed_ids[:graph_window_limit]
    graph_rows: list[tuple[Any, ...]] = []
    for dj_id in graph_seed_ids:
        _, window = build_graph_window(
            dj_id,
            dj_display_names,
            dj_aliases,
            relations_by_dj,
            events_by_dj,
            venues_by_dj,
            orgs_by_dj,
            generated_at,
        )
        graph_rows.append(
            (
                window["window_key"],
                window["seed_subject_id"],
                window["lens"],
                window["depth"],
                window["node_count"],
                window["edge_count"],
                window["nodes_json"],
                window["edges_json"],
                window["generated_at"],
            )
        )
    serving_conn.executemany("INSERT INTO graph_window_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", graph_rows)
    deployable_public = 1 if participant_acceptance == "strict" else 0
    metadata_rows = [
        ("schema_version", "atlas_serving_read_model.v1"),
        ("generated_at", generated_at),
        ("participant_acceptance", participant_acceptance),
        ("deployable_public", str(deployable_public)),
        ("raw_source_url_columns_copied", "0"),
        ("archive_html_path_columns_copied", "0"),
        ("activity_sidecar_events", str(len(activity_detail_rows))),
        ("activity_sidecar_evidence_refs", str(len(activity_evidence_rows))),
    ]
    serving_conn.executemany("INSERT INTO build_metadata VALUES (?, ?)", metadata_rows)

    serving_conn.executescript(
        """
        CREATE INDEX idx_canonical_subject_type_name ON canonical_subject(subject_type, normalized_name);
        CREATE INDEX idx_dj_profile_name ON dj_profile(normalized_name);
        CREATE INDEX idx_performance_event_starts ON performance_event(starts_at);
        CREATE INDEX idx_performance_event_venue ON performance_event(venue_id, starts_at);
        CREATE INDEX idx_activity_event_source_event ON activity_event_detail(source_event_id);
        CREATE INDEX idx_activity_event_date ON activity_event_detail(event_date_start, event_time_text);
        CREATE INDEX idx_activity_evidence_event ON activity_evidence_ref(event_id);
        CREATE INDEX idx_activity_evidence_field ON activity_evidence_ref(field_path);
        CREATE INDEX idx_dj_event_dj_time ON dj_event(dj_id, starts_at);
        CREATE INDEX idx_dj_event_event ON dj_event(event_id);
        CREATE INDEX idx_relation_src_score ON dj_relation_rollup(src_dj_id, relation_score DESC);
        CREATE INDEX idx_relation_dst_score ON dj_relation_rollup(dst_dj_id, relation_score DESC);
        CREATE INDEX idx_venue_rollup_dj_score ON dj_venue_rollup(dj_id, score DESC);
        CREATE INDEX idx_org_rollup_dj_score ON dj_org_rollup(dj_id, score DESC);
        CREATE INDEX idx_search_subject_type ON search_document(subject_type, rank_score DESC);
        CREATE INDEX idx_graph_window_seed ON graph_window_cache(seed_subject_id, lens, depth);
        ANALYZE;
        PRAGMA optimize;
        """
    )
    serving_conn.commit()
    serving_conn.execute("VACUUM")
    serving_conn.close()

    def row_blank_counts(rows: Iterable[dict[str, Any]], fields: list[str]) -> dict[str, int]:
        return {
            field: sum(1 for row in rows if not norm_text(row.get(field)))
            for field in fields
        }

    dj_event_rows = [event for values in events_by_dj.values() for event in values]
    field_missing_counts = {
        "performance_event": row_blank_counts(
            event_records.values(),
            ["starts_at", "time_text", "venue_name", "city", "source_ref_id"],
        ),
        "dj_event": row_blank_counts(
            dj_event_rows,
            ["starts_at", "time_text", "venue_name", "city", "source_ref_id"],
        ),
        "dj_venue_rollup": row_blank_counts(
            venue_rollups.values(),
            ["venue_name", "city"],
        ),
    }

    elapsed = round(time.perf_counter() - start, 3)
    db_size = serving_db.stat().st_size if serving_db.exists() else 0
    summary = {
        "schema_version": "atlas_serving_read_model.v1",
        "generated_at": generated_at,
        "elapsed_seconds": elapsed,
        "paths": {
            "source_db": str(source_db),
            "serving_db": str(serving_db),
            "repair_db": str(repair_db) if repair_db else "",
            "time_db": str(time_db) if time_db else "",
            "source_url_db": str(source_url_db) if source_url_db else "",
            "participant_delta_db": str(participant_delta_db) if participant_delta_db else "",
            "participant_delta_accepted_events": str(participant_delta_accepted_events) if participant_delta_accepted_events else "",
            "curated_rules": str(curated_rules_path) if curated_rules_path else "",
        },
        "counts": {
            "raw_events_seen": int(stats["raw_events_seen"]),
            "events_with_public_participants": int(stats["events_with_public_participants"]),
            "events_recovered_participants_auto": int(stats["events_recovered_participants_auto"]),
            "events_recovered_participants_review_balanced": int(stats["events_recovered_participants_review_balanced"]),
            "events_recovered_participants_review_private": int(stats["events_recovered_participants_review_private"]),
            "events_recovered_venue_auto": int(stats["events_recovered_venue_auto"]),
            "events_recovered_venue_source_account": int(stats["events_recovered_venue_source_account"]),
            "events_recovered_organizer_auto": int(stats["events_recovered_organizer_auto"]),
            "events_recovered_city_venue_geocode": int(stats["events_recovered_city_venue_geocode"]),
            "events_skipped_product_noise": int(stats["events_skipped_product_noise"]),
            "duplicate_event_ids_skipped": int(stats["duplicate_event_ids_skipped"]),
            "activity_events_seen": int(stats["activity_events_seen"]),
            "activity_events_indexed": int(stats["activity_events_indexed"]),
            "activity_events_without_public_lineup_participants": int(stats["activity_events_without_public_lineup_participants"]),
            "activity_evidence_refs": len(activity_evidence_rows),
            "participant_delta_events_indexed": int(stats["participant_delta_events_indexed"]),
            "participant_delta_dj_events_indexed": int(stats["participant_delta_dj_events_indexed"]),
            "participant_delta_relations_indexed": int(stats["participant_delta_relations_indexed"]),
            "participant_delta_profiles_remapped_by_name": int(stats["participant_delta_profiles_remapped_by_name"]),
            "participant_delta_events_review_accepted": int(stats["participant_delta_events_review_accepted"]),
            "participant_delta_dj_events_review_accepted": int(stats["participant_delta_dj_events_review_accepted"]),
            "participant_delta_events_skipped_product_noise": int(stats["participant_delta_events_skipped_product_noise"]),
            "participant_delta_dj_events_skipped_product_noise": int(stats["participant_delta_dj_events_skipped_product_noise"]),
            "participant_delta_dj_events_skipped_blocked_event": int(stats["participant_delta_dj_events_skipped_blocked_event"]),
            "participant_delta_relations_skipped_blocked_events": int(stats["participant_delta_relations_skipped_blocked_events"]),
            "participant_delta_relation_self_edges_skipped": int(stats["participant_delta_relation_self_edges_skipped"]),
            "dj_profiles": len(profile_rows),
            "venue_subjects": len(venue_display_names),
            "org_subjects": len(org_display_names),
            "performance_events": len(event_records),
            "dj_event_edges": sum(len(values) for values in dj_events.values()),
            "dj_relation_edges_directed": len(relation_rows),
            "dj_venue_rollups": len(venue_rows),
            "dj_org_rollups": len(org_rows),
            "evidence_refs": len(evidence_rows),
            "search_documents": len(search_rows),
            "graph_windows": len(graph_rows),
            "serving_db_bytes": db_size,
        },
        "skip_counts": {key: int(value) for key, value in stats.items() if key.startswith("events_without_public_participants")},
        "field_missing_counts": field_missing_counts,
        "safety": {
            "source_sqlite_write_executed": False,
            "network_call_executed": False,
            "llm_call_executed": False,
            "raw_source_url_columns_copied": False,
            "archive_html_path_columns_copied": False,
            "public_url_allowed_default": 0,
            "serving_db_is_public_rollup_only": participant_acceptance == "strict",
            "deployable_public": participant_acceptance == "strict",
            "participant_acceptance": participant_acceptance,
            "review_candidates_included": participant_acceptance != "strict",
        },
        "search": {
            "fts_tokenizer": fts_tokenizer,
            "type_filter_required": False,
        },
    }
    write_json(out_dir / "manifest.json", summary)
    write_summary_md(out_dir / "summary.md", summary)
    return summary


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    counts = summary["counts"]
    safety = summary["safety"]
    lines = [
        "# Atlas Serving Read Model Production Candidate",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- elapsed_seconds: `{summary['elapsed_seconds']}`",
        f"- serving_db: `{summary['paths']['serving_db']}`",
        f"- participant_acceptance: `{safety['participant_acceptance']}`",
        f"- deployable_public: `{safety['deployable_public']}`",
        f"- raw_events_seen: `{counts['raw_events_seen']}`",
        f"- activity_events_indexed: `{counts['activity_events_indexed']}`",
        f"- activity_evidence_refs: `{counts['activity_evidence_refs']}`",
        f"- participant_delta_events_indexed: `{counts['participant_delta_events_indexed']}`",
        f"- participant_delta_dj_events_indexed: `{counts['participant_delta_dj_events_indexed']}`",
        f"- participant_delta_relations_indexed: `{counts['participant_delta_relations_indexed']}`",
        f"- participant_delta_profiles_remapped_by_name: `{counts['participant_delta_profiles_remapped_by_name']}`",
        f"- performance_events: `{counts['performance_events']}`",
        f"- dj_profiles: `{counts['dj_profiles']}`",
        f"- dj_event_edges: `{counts['dj_event_edges']}`",
        f"- dj_relation_edges_directed: `{counts['dj_relation_edges_directed']}`",
        f"- search_documents: `{counts['search_documents']}`",
        f"- graph_windows: `{counts['graph_windows']}`",
        "",
        "## Safety",
        "",
        f"- source_sqlite_write_executed: `{safety['source_sqlite_write_executed']}`",
        f"- raw_source_url_columns_copied: `{safety['raw_source_url_columns_copied']}`",
        f"- archive_html_path_columns_copied: `{safety['archive_html_path_columns_copied']}`",
        f"- public_url_allowed_default: `{safety['public_url_allowed_default']}`",
        f"- review_candidates_included: `{safety['review_candidates_included']}`",
        "",
        "## Skip Counts",
        "",
    ]
    for key, value in sorted(summary.get("skip_counts", {}).items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Field Missing Counts", ""])
    for table, fields in sorted(summary.get("field_missing_counts", {}).items()):
        lines.append(f"### {table}")
        for key, value in sorted(fields.items()):
            lines.append(f"- {key}: `{value}`")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--repair-db", type=Path, default=DEFAULT_REPAIR_DB)
    parser.add_argument("--time-db", type=Path, default=DEFAULT_TIME_DB)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--participant-delta-db", type=Path, default=None)
    parser.add_argument("--participant-delta-accepted-events", type=Path, default=None)
    parser.add_argument("--curated-rules", type=Path, default=DEFAULT_CURATED_RULES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--graph-window-limit", type=int, default=2000, help="0 means all DJ profiles")
    parser.add_argument("--max-events", type=int, default=0, help="test/dev cap; 0 means full")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--confirm-production-candidate", default=os.environ.get("ATLAS_SERVING_CONFIRM", ""))
    parser.add_argument(
        "--participant-acceptance",
        choices=sorted(PARTICIPANT_ACCEPTANCE_MODES),
        default="strict",
        help="strict is public deployable; balanced/aggressive-private are repair candidates only",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_serving_read_model(
        args.source_db,
        args.out_dir,
        repair_db=args.repair_db,
        time_db=args.time_db,
        source_url_db=args.source_url_db,
        participant_delta_db=args.participant_delta_db,
        participant_delta_accepted_events=args.participant_delta_accepted_events,
        curated_rules_path=args.curated_rules,
        graph_window_limit=args.graph_window_limit,
        max_events=args.max_events,
        force=args.force,
        confirm_production_candidate=args.confirm_production_candidate,
        participant_acceptance=args.participant_acceptance,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
