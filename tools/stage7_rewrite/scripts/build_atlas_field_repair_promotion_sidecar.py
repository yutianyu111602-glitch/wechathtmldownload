#!/usr/bin/env python3
"""Build local-only Atlas field repair promotion sidecars.

This script is the next deterministic loop after the information-gap packet:

* promote high-confidence source-account venue classes from residual serving
  gaps into a reviewable sidecar and a derived curated-rules JSON;
* rewrite event time candidates with explicit public visibility decisions so
  partial-date promotion is auditable before a serving rebuild;
* keep all output local and never mutate the private source Atlas DB, serving
  candidates, production pointers, Neo4j, Qdrant, or remote deployments.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_atlas_serving_read_model import (  # noqa: E402
    DEFAULT_CURATED_RULES,
    classify_place_text,
    event_public_id,
    load_curated_rules,
    norm_key,
    norm_text,
    normalize_venue_name,
    row_dict,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate"
    / "atlas.sqlite"
)
DEFAULT_GAP_SIDECAR = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_information_gap_closure_20260523"
    / "information_gap_review_sidecar.sqlite"
)
DEFAULT_TIME_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_event_time_normalized_sidecar_139123_candidate_20260522"
    / "atlas_event_time_normalized_sidecar.sqlite"
)
DEFAULT_REPAIR_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_low_cost_repair_sidecar_139123_candidate_20260522"
    / "atlas_dj_low_cost_repair_sidecar.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_field_repair_promotion_sidecar_20260523"

RAW_LEAK_RE = re.compile(
    r"https?://|mp\.weixin|openid|unionid|archive_raw_html_path|raw\.html|(?<![A-Za-z0-9])[A-Za-z]:[/\\][^\"'\s,}]",
    flags=re.IGNORECASE,
)
VENUE_REVIEW_SIGNAL_RE = re.compile(
    r"(club|live|bar|venue|space|system|heim|dada|elevator|pillbox|solo|44kw|wigwam|oil|tag|"
    r"俱乐部|酒吧|空间|剧场|现场|舞厅|舞池|北京|上海|beijing|shanghai|bj)",
    flags=re.IGNORECASE,
)
TIME_SCHEMA_COLUMNS = [
    "event_key",
    "source_article_uid",
    "event_id",
    "event_name",
    "source_account",
    "source_title",
    "time_text",
    "normalized_date",
    "partial_date",
    "time_of_day",
    "precision",
    "parse_status",
    "year_inference_status",
    "article_post_date",
    "source_url_match_basis",
    "confidence",
    "review_tier",
    "inferred_from",
    "private_internal_only",
    "public_graph_visible",
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [norm_text(item) for item in value if norm_text(item)]
    raw = norm_text(value)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [norm_text(item) for item in parsed if norm_text(item)]


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_field_missing_rows(path: Path) -> list[dict[str, Any]]:
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "field_missing_event"):
            raise ValueError(f"{path} does not contain field_missing_event")
        rows = []
        for row in conn.execute(
            """
            SELECT
              event_id,
              missing_fields_json,
              gap_bucket,
              event_title,
              starts_at,
              time_text,
              venue_name,
              city,
              source_ref_id,
              source_account,
              source_title,
              participant_count,
              confidence
            FROM field_missing_event
            ORDER BY event_id
            """
        ):
            item = row_dict(row)
            item["missing_fields"] = parse_json_list(item.get("missing_fields_json"))
            rows.append(item)
        return rows
    finally:
        conn.close()


def load_geocode_places(source_db: Path) -> dict[str, dict[str, Any]]:
    conn = connect_readonly(source_db)
    try:
        if not table_exists(conn, "map_geocode_places"):
            return {}
        rows = conn.execute(
            """
            SELECT
              label,
              normalized_place,
              city,
              geocode_status,
              geocode_source,
              precision,
              event_count,
              entity_count,
              article_count
            FROM map_geocode_places
            ORDER BY event_count DESC, article_count DESC, entity_count DESC
            """
        )
        by_key: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = row_dict(row)
            for value in (item.get("label"), item.get("normalized_place"), normalize_venue_name(item.get("label"))):
                key = norm_key(value)
                if key and key not in by_key:
                    by_key[key] = item
        return by_key
    finally:
        conn.close()


def build_raw_event_map(source_db: Path, public_event_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not public_event_ids:
        return {}
    conn = connect_readonly(source_db)
    try:
        rows = conn.execute(
            """
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
        )
        mapped: dict[str, dict[str, Any]] = {}
        for row in rows:
            raw = row_dict(row)
            public_id = event_public_id(raw)
            if public_id in public_event_ids:
                mapped[public_id] = raw
                if len(mapped) == len(public_event_ids):
                    break
        return mapped
    finally:
        conn.close()


def is_good_geocode(row: dict[str, Any] | None) -> bool:
    if not row or not norm_text(row.get("city")):
        return False
    status = norm_key(row.get("geocode_status"))
    return bool(status and "needs" not in status and "review" not in status)


def classify_source_account_candidate(
    source_account: str,
    missing_count: int,
    geocode_row: dict[str, Any] | None,
    curated_rules: dict[str, dict[str, Any]],
    min_auto_count: int,
) -> dict[str, Any]:
    candidate_place = normalize_venue_name(source_account)
    key = norm_key(candidate_place)
    before = classify_place_text(candidate_place, curated_rules)
    city = norm_text((geocode_row or {}).get("city"))
    geocode_status = norm_text((geocode_row or {}).get("geocode_status"))
    public_rule_emitted = 0
    tier = "manual_review"
    basis = "insufficient_local_venue_evidence"
    confidence = 0.0

    if not key:
        tier = "rejected"
        basis = "empty_source_account"
    elif before in {"radio", "noise"}:
        tier = "rejected"
        basis = f"existing_curated_kind_{before}"
    elif before == "venue":
        tier = "already_supported"
        basis = "existing_curated_or_lexical_venue"
        confidence = 0.98
    elif is_good_geocode(geocode_row) and missing_count >= min_auto_count:
        tier = "auto_candidate"
        basis = "source_account_geocoded_city_and_repeated_missing_venue_gap"
        confidence = 0.93
        public_rule_emitted = 1
    elif missing_count >= min_auto_count and VENUE_REVIEW_SIGNAL_RE.search(candidate_place):
        tier = "review_candidate"
        basis = "source_account_name_has_venue_signal_but_needs_geocode_or_curated_review"
        confidence = 0.76

    return {
        "source_account": source_account,
        "normalized_source_account": key,
        "candidate_place": candidate_place,
        "classification_before": before,
        "geocode_city": city,
        "geocode_status": geocode_status,
        "missing_event_count": missing_count,
        "promotion_tier": tier,
        "public_rule_emitted": public_rule_emitted,
        "confidence": confidence,
        "basis": basis,
    }


def build_venue_candidates(
    field_rows: list[dict[str, Any]],
    source_db: Path,
    geocode_places: dict[str, dict[str, Any]],
    curated_rules: dict[str, dict[str, Any]],
    min_auto_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    venue_gap_rows = [row for row in field_rows if "venue_name" in row.get("missing_fields", [])]
    by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in venue_gap_rows:
        account = norm_text(row.get("source_account"))
        if account:
            by_account[account].append(row)

    account_candidates: list[dict[str, Any]] = []
    account_by_name: dict[str, dict[str, Any]] = {}
    for account, rows in by_account.items():
        place = normalize_venue_name(account)
        geocode = geocode_places.get(norm_key(place)) or geocode_places.get(norm_key(account))
        candidate = classify_source_account_candidate(account, len(rows), geocode, curated_rules, min_auto_count)
        candidate["sample_event_ids_json"] = json_dumps([norm_text(row.get("event_id")) for row in rows[:12]])
        candidate["sample_titles_json"] = json_dumps([norm_text(row.get("event_title")) for row in rows[:12]])
        account_candidates.append(candidate)
        account_by_name[account] = candidate

    materialized_accounts = {
        row["source_account"]
        for row in account_candidates
        if row["promotion_tier"] in {"auto_candidate", "review_candidate"}
    }
    raw_map = build_raw_event_map(
        source_db,
        {norm_text(row.get("event_id")) for row in venue_gap_rows if norm_text(row.get("source_account")) in materialized_accounts},
    )
    event_candidates: list[dict[str, Any]] = []
    for row in venue_gap_rows:
        account = norm_text(row.get("source_account"))
        account_candidate = account_by_name.get(account)
        if not account_candidate or account_candidate["promotion_tier"] not in {"auto_candidate", "review_candidate"}:
            continue
        public_event_id = norm_text(row.get("event_id"))
        raw = raw_map.get(public_event_id, {})
        event_candidates.append(
            {
                "public_event_id": public_event_id,
                "source_article_uid": norm_text(raw.get("source_article_uid")),
                "raw_event_id": norm_text(raw.get("evid")),
                "event_title": norm_text(row.get("event_title")),
                "source_account": account,
                "source_title": norm_text(row.get("source_title")),
                "candidate_place": account_candidate["candidate_place"],
                "city": account_candidate["geocode_city"],
                "confidence": account_candidate["confidence"],
                "promotion_tier": account_candidate["promotion_tier"],
                "public_rule_emitted": int(account_candidate["public_rule_emitted"]),
                "basis": account_candidate["basis"],
            }
        )

    account_candidates.sort(key=lambda item: (-int(item["missing_event_count"]), item["source_account"]))
    event_candidates.sort(key=lambda item: (item["source_account"], item["public_event_id"]))
    return account_candidates, event_candidates


def public_time_decision(row: dict[str, Any]) -> tuple[int, int, str]:
    normalized_date = norm_text(row.get("normalized_date"))
    review_tier = norm_key(row.get("review_tier"))
    precision = norm_key(row.get("precision"))
    parse_status = norm_key(row.get("parse_status"))
    year_status = norm_key(row.get("year_inference_status"))
    conf = safe_float(row.get("confidence"))
    if not normalized_date:
        return 0, 1, "no_normalized_date"
    if review_tier not in {"auto_candidate", "source_exact", "raw"}:
        return 0, 1, "review_tier_not_public"
    if precision == "date" and parse_status == "full_date" and conf >= 0.82:
        return 1, 0, "direct_full_date_time_text"
    if (
        precision == "date_inferred_from_post_date"
        and parse_status == "partial_date_year_inferred"
        and year_status == "same_year_after_or_near_publish"
        and conf >= 0.80
    ):
        return 1, 0, "partial_date_with_explicit_publish_year_inference"
    if (
        precision == "date_inferred_from_article_post_relative_day"
        and parse_status in {"relative_today", "relative_tomorrow"}
        and year_status
        in {
            "relative_today_from_article_post_date",
            "relative_tomorrow_from_article_post_date",
        }
        and conf >= 0.68
    ):
        return 1, 0, "relative_day_with_explicit_article_post_date"
    if (
        precision == "date_inferred_from_article_post_weekday"
        and parse_status == "relative_weekday"
        and year_status == "relative_weekday_from_article_post_date"
        and conf >= 0.72
    ):
        return 1, 0, "relative_weekday_with_explicit_article_post_date"
    if (
        precision == "date_inferred_from_post_date"
        and parse_status == "partial_date_year_inferred"
        and year_status == "cross_year_forward_from_publish"
        and conf >= 0.78
    ):
        return 1, 0, "cross_year_partial_date_with_explicit_publish_year_inference"
    return 0, 1, "not_public_without_review"


def build_time_rows(base_time_db: Path | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not base_time_db or not base_time_db.exists():
        return [], []
    conn = connect_readonly(base_time_db)
    try:
        if not table_exists(conn, "event_time_normalized"):
            return [], []
        rows: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        select_columns = ",".join(TIME_SCHEMA_COLUMNS)
        for raw_row in conn.execute(f"SELECT {select_columns} FROM event_time_normalized"):
            row = row_dict(raw_row)
            public_visible, private_only, reason = public_time_decision(row)
            row["public_graph_visible"] = public_visible
            row["private_internal_only"] = private_only
            rows.append(row)
            decisions.append(
                {
                    "event_key": norm_text(row.get("event_key")),
                    "source_article_uid": norm_text(row.get("source_article_uid")),
                    "event_id": norm_text(row.get("event_id")),
                    "event_name": norm_text(row.get("event_name")),
                    "precision": norm_text(row.get("precision")),
                    "parse_status": norm_text(row.get("parse_status")),
                    "year_inference_status": norm_text(row.get("year_inference_status")),
                    "confidence": safe_float(row.get("confidence")),
                    "review_tier": norm_text(row.get("review_tier")),
                    "public_graph_visible": public_visible,
                    "promotion_reason": reason,
                }
            )
        return rows, decisions
    finally:
        conn.close()


def build_rule_additions(account_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    additions = []
    for row in account_candidates:
        if int(row.get("public_rule_emitted") or 0) != 1:
            continue
        additions.append(
            {
                "term": row["source_account"],
                "normalized_term": row["normalized_source_account"],
                "kind": "venue",
                "city": row["geocode_city"],
                "confidence": row["confidence"],
                "basis": "atlas_field_repair_geocoded_source_account",
                "sources": [],
                "notes": "Local report-only rule generated from map_geocode_places plus residual serving field gaps.",
            }
        )
    return additions


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
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)


def write_merged_curated_rules(base_rules_path: Path, out_path: Path, additions: list[dict[str, Any]]) -> int:
    payload = json.loads(base_rules_path.read_text(encoding="utf-8")) if base_rules_path.exists() else {"records": []}
    records = list(payload.get("records", []))
    existing = {norm_key(row.get("normalized_term") or row.get("term")) for row in records}
    added = 0
    for row in additions:
        key = norm_key(row.get("normalized_term") or row.get("term"))
        if key and key not in existing:
            records.append(row)
            existing.add(key)
            added += 1
    payload["records"] = records
    payload["schema_version"] = payload.get("schema_version", "atlas.curated_entity_rules.v1")
    payload["generated_at"] = now_iso()
    payload["write_policy"] = "report_only_field_repair_candidate_rules_no_source_db_write"
    write_json(out_path, payload)
    return added


def create_sidecar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE field_repair_promotion_run (
          generated_at TEXT NOT NULL,
          summary_json TEXT NOT NULL,
          safety_json TEXT NOT NULL
        );
        CREATE TABLE venue_source_account_candidate (
          source_account TEXT PRIMARY KEY,
          normalized_source_account TEXT,
          candidate_place TEXT,
          classification_before TEXT,
          geocode_city TEXT,
          geocode_status TEXT,
          missing_event_count INTEGER,
          promotion_tier TEXT,
          public_rule_emitted INTEGER,
          confidence REAL,
          basis TEXT,
          sample_event_ids_json TEXT,
          sample_titles_json TEXT
        );
        CREATE TABLE event_venue_field_candidate (
          public_event_id TEXT,
          source_article_uid TEXT,
          raw_event_id TEXT,
          event_title TEXT,
          source_account TEXT,
          source_title TEXT,
          candidate_place TEXT,
          city TEXT,
          confidence REAL,
          promotion_tier TEXT,
          public_rule_emitted INTEGER,
          basis TEXT
        );
        CREATE TABLE event_time_normalized (
          event_key TEXT PRIMARY KEY,
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
          parse_status TEXT,
          year_inference_status TEXT,
          article_post_date TEXT,
          source_url_match_basis TEXT,
          confidence REAL,
          review_tier TEXT,
          inferred_from TEXT,
          private_internal_only INTEGER,
          public_graph_visible INTEGER
        );
        CREATE TABLE time_public_promotion_decision (
          event_key TEXT PRIMARY KEY,
          source_article_uid TEXT,
          event_id TEXT,
          event_name TEXT,
          precision TEXT,
          parse_status TEXT,
          year_inference_status TEXT,
          confidence REAL,
          review_tier TEXT,
          public_graph_visible INTEGER,
          promotion_reason TEXT
        );
        CREATE INDEX idx_field_venue_candidate_tier ON venue_source_account_candidate(promotion_tier, public_rule_emitted);
        CREATE INDEX idx_field_venue_event_public ON event_venue_field_candidate(public_event_id);
        CREATE INDEX idx_field_time_public ON event_time_normalized(public_graph_visible, review_tier);
        CREATE INDEX idx_field_time_date ON event_time_normalized(normalized_date);
        """
    )


def insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    conn.executemany(sql, [[row.get(column) for column in columns] for row in rows])


def leak_hits(rows_by_name: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for name, rows in rows_by_name.items():
        hits = 0
        for row in rows:
            if RAW_LEAK_RE.search(json.dumps(row, ensure_ascii=False, sort_keys=True)):
                hits += 1
        result[name] = hits
    return result


def write_sidecar(path: Path, summary: dict[str, Any], rows_by_name: dict[str, list[dict[str, Any]]]) -> None:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    try:
        create_sidecar_schema(conn)
        insert_rows(conn, "venue_source_account_candidate", rows_by_name["venue_source_account_candidates"])
        insert_rows(conn, "event_venue_field_candidate", rows_by_name["event_venue_field_candidates"])
        insert_rows(conn, "event_time_normalized", rows_by_name["event_time_normalized"])
        insert_rows(conn, "time_public_promotion_decision", rows_by_name["time_public_promotion_decisions"])
        safety = {
            "source_sqlite_write_executed": False,
            "serving_sqlite_write_executed": False,
            "production_pointer_update_executed": False,
            "cloudrun_deploy_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
        }
        conn.execute(
            "INSERT INTO field_repair_promotion_run VALUES (?, ?, ?)",
            (summary["generated_at"], json.dumps(summary, ensure_ascii=False), json.dumps(safety, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def render_markdown(summary: dict[str, Any]) -> str:
    venue = summary["venue_promotion"]
    time = summary["time_promotion"]
    lines = [
        "# Atlas Field Repair Promotion Sidecar",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "## Decision",
        "",
        f"- decision: `{summary['decision']}`",
        f"- source_sqlite_write_executed: `{str(summary['boundary']['source_sqlite_write_executed']).lower()}`",
        f"- serving_sqlite_write_executed: `{str(summary['boundary']['serving_sqlite_write_executed']).lower()}`",
        f"- cloudrun_deploy_executed: `{str(summary['boundary']['cloudrun_deploy_executed']).lower()}`",
        f"- llm_call_executed: `{str(summary['boundary']['llm_call_executed']).lower()}`",
        "",
        "## Venue Promotion",
        "",
        f"- source-account groups reviewed: `{venue['source_account_groups']}`",
        f"- auto venue rule additions: `{venue['auto_rule_additions']}`",
        f"- auto event venue candidates: `{venue['auto_event_candidates']}`",
        f"- review-only event venue candidates: `{venue['review_event_candidates']}`",
        "",
        "## Time Promotion",
        "",
        f"- input time rows: `{time['input_time_rows']}`",
        f"- explicit public-visible rows: `{time['public_visible_rows']}`",
        f"- private/review rows retained: `{time['private_or_review_rows']}`",
        "",
        "## Outputs",
        "",
        f"- sidecar_sqlite: `{summary['outputs']['sidecar_sqlite']}`",
        f"- merged_curated_rules_json: `{summary['outputs']['merged_curated_rules_json']}`",
        f"- venue_source_account_candidates_jsonl: `{summary['outputs']['venue_source_account_candidates_jsonl']}`",
        f"- event_venue_field_candidates_jsonl: `{summary['outputs']['event_venue_field_candidates_jsonl']}`",
        f"- time_public_promotion_decisions_jsonl: `{summary['outputs']['time_public_promotion_decisions_jsonl']}`",
        "",
        "## Rebuild Inputs",
        "",
        f"- repair_db: `{summary['rebuild_inputs']['repair_db']}`",
        f"- time_db: `{summary['rebuild_inputs']['time_db']}`",
        f"- curated_rules_path: `{summary['rebuild_inputs']['curated_rules_path']}`",
        "",
        "## Leak Check",
        "",
    ]
    for name, value in sorted(summary["raw_leak_hits"].items()):
        lines.append(f"- {name}: `{value}`")
    lines.extend(["", "## Next Gate", ""])
    for item in summary["next_gate"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def build_field_repair_promotion_sidecar(
    source_db: Path,
    gap_sidecar: Path,
    base_time_db: Path,
    curated_rules_path: Path,
    out_dir: Path,
    *,
    min_auto_count: int = 20,
) -> dict[str, Any]:
    if not source_db.exists():
        raise FileNotFoundError(source_db)
    if not gap_sidecar.exists():
        raise FileNotFoundError(gap_sidecar)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_at = now_iso()
    field_rows = load_field_missing_rows(gap_sidecar)
    geocode_places = load_geocode_places(source_db)
    curated_rules = load_curated_rules(curated_rules_path)
    account_candidates, event_candidates = build_venue_candidates(
        field_rows,
        source_db,
        geocode_places,
        curated_rules,
        min_auto_count,
    )
    rule_additions = build_rule_additions(account_candidates)
    merged_rules_path = out_dir / "atlas_curated_entity_rules_field_repair_20260523.json"
    actual_rule_additions = write_merged_curated_rules(curated_rules_path, merged_rules_path, rule_additions)

    time_rows, time_decisions = build_time_rows(base_time_db)
    rows_by_name = {
        "venue_source_account_candidates": account_candidates,
        "event_venue_field_candidates": event_candidates,
        "event_time_normalized": time_rows,
        "time_public_promotion_decisions": time_decisions,
    }
    leaks = leak_hits(rows_by_name)

    tier_counts = Counter(row["promotion_tier"] for row in account_candidates)
    event_tier_counts = Counter(row["promotion_tier"] for row in event_candidates)
    time_reason_counts = Counter(row["promotion_reason"] for row in time_decisions)
    sidecar_path = out_dir / "atlas_field_repair_promotion_sidecar.sqlite"
    summary = {
        "schema_version": "atlas_field_repair_promotion_sidecar.v1",
        "generated_at": generated_at,
        "decision": "field_repair_promotion_sidecar_materialized_local_only",
        "source_db": str(source_db),
        "gap_sidecar": str(gap_sidecar),
        "base_time_db": str(base_time_db),
        "curated_rules_path": str(curated_rules_path),
        "min_auto_count": min_auto_count,
        "venue_promotion": {
            "source_account_groups": len(account_candidates),
            "source_account_tier_counts": dict(sorted(tier_counts.items())),
            "auto_rule_additions": actual_rule_additions,
            "auto_event_candidates": event_tier_counts.get("auto_candidate", 0),
            "review_event_candidates": event_tier_counts.get("review_candidate", 0),
        },
        "time_promotion": {
            "input_time_rows": len(time_rows),
            "public_visible_rows": sum(1 for row in time_rows if int(row.get("public_graph_visible") or 0) == 1),
            "private_or_review_rows": sum(1 for row in time_rows if int(row.get("public_graph_visible") or 0) == 0),
            "decision_reason_counts": dict(sorted(time_reason_counts.items())),
        },
        "raw_leak_hits": leaks,
        "outputs": {
            "sidecar_sqlite": str(sidecar_path),
            "merged_curated_rules_json": str(merged_rules_path),
            "venue_source_account_candidates_jsonl": str(out_dir / "venue_source_account_candidates.jsonl"),
            "event_venue_field_candidates_jsonl": str(out_dir / "event_venue_field_candidates.jsonl"),
            "time_public_promotion_decisions_jsonl": str(out_dir / "time_public_promotion_decisions.jsonl"),
            "summary_json": str(out_dir / "summary.json"),
            "summary_md": str(out_dir / "summary.md"),
        },
        "rebuild_inputs": {
            "repair_db": str(DEFAULT_REPAIR_DB),
            "time_db": str(sidecar_path),
            "curated_rules_path": str(merged_rules_path),
        },
        "boundary": {
            "source_sqlite_write_executed": False,
            "serving_sqlite_write_executed": False,
            "production_pointer_update_executed": False,
            "cloudrun_deploy_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
        },
        "next_gate": [
            "Rebuild strict and aggressive-private serving candidates from the source DB using the emitted curated rules and time sidecar.",
            "Compare field_missing_counts, raw leak checks, product/admin noise checks, and profile/search/browser smoke before writing a promotion packet.",
            "Keep production pointer, VPS/CloudRun, Neo4j/Qdrant, and mini-program upload as separate explicit gates.",
        ],
    }

    write_jsonl(out_dir / "venue_source_account_candidates.jsonl", account_candidates)
    write_jsonl(out_dir / "event_venue_field_candidates.jsonl", event_candidates)
    write_jsonl(out_dir / "time_public_promotion_decisions.jsonl", time_decisions)
    write_sidecar(sidecar_path, summary, rows_by_name)
    write_json(out_dir / "summary.json", summary)
    (out_dir / "summary.md").write_text(render_markdown(summary), encoding="utf-8", newline="\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--gap-sidecar", type=Path, default=DEFAULT_GAP_SIDECAR)
    parser.add_argument("--base-time-db", type=Path, default=DEFAULT_TIME_DB)
    parser.add_argument("--curated-rules", type=Path, default=DEFAULT_CURATED_RULES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-auto-count", type=int, default=20)
    args = parser.parse_args()
    summary = build_field_repair_promotion_sidecar(
        args.source_db,
        args.gap_sidecar,
        args.base_time_db,
        args.curated_rules,
        args.out_dir,
        min_auto_count=args.min_auto_count,
    )
    print(json.dumps({"ok": True, "summary": summary}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
