#!/usr/bin/env python3
"""Build a derived public-safe Atlas serving candidate with participant delta.

This is a candidate-build step only. It copies the existing public serving
SQLite read model, merges the sidecar-only participant graph delta into that
copy, then runs scoped leak/noise/search checks. It never mutates the raw Atlas
SQLite, the base serving DB, Neo4j, Qdrant, CloudRun, or mini-program state.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent.parent

DEFAULT_BASE_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_recovered_public_v2_20260522"
    / "atlas_serving.sqlite"
)
DEFAULT_DELTA_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_graph_delta_candidate_20260522"
    / "participant_graph_delta.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_serving_participant_delta_public_candidate_20260522"

SCHEMA_VERSION = "atlas_serving_participant_delta_candidate.v1"
RAW_LEAK_RE = re.compile(
    r"https?://|www\.|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|qpic\.cn|"
    r"archive_html_path|archive_path|raw\.html|[A-Za-z]:\\|/mnt/|/home/|\\\\wsl",
    re.IGNORECASE,
)
NOISE_KEYS = {
    "tba",
    "guest",
    "guests",
    "special guest",
    "unknown",
    "various artists",
    "lineup",
    "阵容",
    "嘉宾",
    "更多",
    "未公布",
    "待定",
}
PLACEHOLDER_PLACE_KEYS = {"tba", "unknown", "待定", "未定", "未公布", "待公布"}
PRODUCT_NOISE_TERMS = {
    "白葡萄酒",
    "红酒",
    "葡萄酒",
    "鸡尾酒",
    "酒单",
    "品酒",
    "品鉴",
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
    "wine",
}
GRAPH_NODE_LIMITS = {
    "collaborator": 28,
    "event": 20,
    "venue": 12,
    "org": 8,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def norm_key(value: Any) -> str:
    return norm_text(value).casefold()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_json_list(value: Any) -> list[Any]:
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


def safe_min(current: str, candidate: str) -> str:
    current = norm_text(current)
    candidate = norm_text(candidate)
    if not current:
        return candidate
    if not candidate:
        return current
    return min(current, candidate)


def safe_max(current: str, candidate: str) -> str:
    current = norm_text(current)
    candidate = norm_text(candidate)
    if not current:
        return candidate
    if not candidate:
        return current
    return max(current, candidate)


def relation_label(score: float, same_event_count: int, same_label_count: int = 0) -> str:
    if same_event_count >= 5 or score >= 26:
        return "高频同台"
    if same_label_count >= 2:
        return "厂牌/组织关联"
    if same_event_count >= 2:
        return "多次同台"
    return "同台出现"


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


def count_table(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def text_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})")
        if str(row[2]).upper() in {"TEXT", ""}
    ]


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path or not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    checks = report["validation"]
    safety = report["safety"]
    lines = [
        "# Atlas Serving Participant Delta Public Candidate",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- base_serving_db: `{report['paths']['base_serving_db']}`",
        f"- delta_db: `{report['paths']['delta_db']}`",
        f"- candidate_db: `{report['paths']['candidate_db']}`",
        f"- elapsed_seconds: `{report['elapsed_seconds']}`",
        "",
        "## Counts",
        "",
        f"- dj_profiles: `{counts['candidate_after']['dj_profile']}` (`+{counts['delta_applied']['dj_profiles']}` delta rows)",
        f"- performance_events: `{counts['candidate_after']['performance_event']}` (`+{counts['delta_applied']['events']}` delta rows)",
        f"- dj_event_edges: `{counts['candidate_after']['dj_event']}` (`+{counts['delta_applied']['dj_event_edges']}` delta rows)",
        f"- dj_relation_edges_directed: `{counts['candidate_after']['dj_relation_rollup']}` (`+{counts['delta_applied']['relations_directed']}` delta rows)",
        f"- search_documents: `{counts['candidate_after']['search_document']}`",
        f"- graph_windows_rebuilt: `{counts['graph_windows_rebuilt']}`",
        "",
        "## Validation",
        "",
        f"- leak_hits: `{checks['leakage']['hit_count']}`",
        f"- noise_hits: `{checks['noise']['hit_count']}`",
        f"- search_sample_size: `{checks['search']['sample_size']}`",
        f"- search_like_missing: `{checks['search']['like_missing_count']}`",
        f"- search_fts_missing: `{checks['search']['fts_missing_count']}`",
        "",
        "## Safety",
        "",
        f"- copied_base_db: `{safety['copied_base_db']}`",
        f"- base_serving_db_mutated: `{safety['base_serving_db_mutated']}`",
        f"- raw_atlas_sqlite_mutated: `{safety['raw_atlas_sqlite_mutated']}`",
        f"- production_store_write_executed: `{safety['production_store_write_executed']}`",
        f"- neo4j_write_executed: `{safety['neo4j_write_executed']}`",
        f"- qdrant_write_executed: `{safety['qdrant_write_executed']}`",
        f"- deploy_or_upload_executed: `{safety['deploy_or_upload_executed']}`",
        f"- promotion_decision_required: `{safety['promotion_decision_required']}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: Path, report: dict[str, Any]) -> None:
    manifest = {
        "schema_version": "atlas_serving_participant_delta_candidate.manifest.v1",
        "generated_at": report["generated_at"],
        "candidate_db": report["paths"]["candidate_db"],
        "base_serving_db": report["paths"]["base_serving_db"],
        "delta_db": report["paths"]["delta_db"],
        "decision": report["decision"],
        "counts": report["counts"]["candidate_after"],
        "candidate_delta": report["counts"]["candidate_delta"],
        "field_missing_counts": {},
        "validation": report["validation"],
        "safety": {
            "deployable_public": report["decision"] == "public_safe_serving_candidate_built_and_validated",
            "serving_db_is_public_rollup_only": True,
            "raw_source_url_columns_copied": False,
            "archive_html_path_columns_copied": False,
            "base_serving_db_mutated": False,
            "raw_atlas_sqlite_mutated": False,
            "production_store_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "deploy_or_upload_executed": False,
        },
    }
    write_json(path, manifest)


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def create_temp_scope(conn: sqlite3.Connection, delta_db: Path) -> None:
    conn.execute("ATTACH DATABASE ? AS delta", (str(delta_db.resolve()),))
    conn.executescript(
        """
        CREATE TEMP TABLE tmp_delta_dj AS
          SELECT dj_id FROM delta.graph_delta_dj_profile
          UNION SELECT dj_id FROM delta.graph_delta_dj_event;

        CREATE TEMP TABLE tmp_affected_dj AS
          SELECT dj_id FROM tmp_delta_dj
          UNION SELECT src_dj_id FROM delta.graph_delta_relation
          UNION SELECT dst_dj_id FROM delta.graph_delta_relation;

        CREATE TEMP TABLE tmp_affected_event AS
          SELECT event_id FROM delta.graph_delta_event
          UNION SELECT event_id FROM delta.graph_delta_dj_event;
        """
    )


def detach_delta(conn: sqlite3.Connection) -> None:
    conn.execute("DETACH DATABASE delta")


def merge_delta_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        UPDATE performance_event
        SET
          participant_count = participant_count + (
            SELECT participant_delta_count
            FROM delta.graph_delta_event d
            WHERE d.event_id = performance_event.event_id
          ),
          confidence = MAX(confidence, (
            SELECT confidence
            FROM delta.graph_delta_event d
            WHERE d.event_id = performance_event.event_id
          )),
          event_title = COALESCE(NULLIF(event_title, ''), (
            SELECT event_title FROM delta.graph_delta_event d WHERE d.event_id = performance_event.event_id
          )),
          starts_at = COALESCE(NULLIF(starts_at, ''), (
            SELECT starts_at FROM delta.graph_delta_event d WHERE d.event_id = performance_event.event_id
          )),
          time_text = COALESCE(NULLIF(time_text, ''), (
            SELECT time_text FROM delta.graph_delta_event d WHERE d.event_id = performance_event.event_id
          )),
          venue_id = COALESCE(NULLIF(venue_id, ''), (
            SELECT venue_id FROM delta.graph_delta_event d WHERE d.event_id = performance_event.event_id
          )),
          venue_name = COALESCE(NULLIF(venue_name, ''), (
            SELECT venue_name FROM delta.graph_delta_event d WHERE d.event_id = performance_event.event_id
          )),
          city = COALESCE(NULLIF(city, ''), (
            SELECT city FROM delta.graph_delta_event d WHERE d.event_id = performance_event.event_id
          )),
          source_ref_id = COALESCE(NULLIF(source_ref_id, ''), (
            SELECT source_ref_id FROM delta.graph_delta_event d WHERE d.event_id = performance_event.event_id
          ))
        WHERE EXISTS (
          SELECT 1 FROM delta.graph_delta_event d
          WHERE d.event_id = performance_event.event_id
        );

        INSERT OR IGNORE INTO performance_event (
          event_id, event_title, starts_at, time_text, venue_id, venue_name, city,
          source_ref_id, participant_count, organizer_count, confidence
        )
        SELECT
          d.event_id, d.event_title, d.starts_at, d.time_text, d.venue_id, d.venue_name, d.city,
          d.source_ref_id, d.participant_delta_count, 0, d.confidence
        FROM delta.graph_delta_event d
        WHERE NOT EXISTS (
          SELECT 1 FROM performance_event existing WHERE existing.event_id = d.event_id
        );

        INSERT OR IGNORE INTO dj_profile (
          dj_id, display_name, normalized_name, aliases_json, city_primary,
          avatar_asset_id, source_article_count, event_count, venue_count,
          collaborator_count, organization_count, media_count, first_seen_at,
          last_seen_at, confidence
        )
        SELECT
          dj_id, display_name, normalized_name, aliases_json, '',
          '', event_delta_count, event_delta_count, 0,
          0, 0, 0, first_seen_at, last_seen_at, confidence
        FROM delta.graph_delta_dj_profile;

        UPDATE dj_profile
        SET
          confidence = MAX(confidence, (
            SELECT confidence FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id
          )),
          first_seen_at = CASE
            WHEN first_seen_at IS NULL OR first_seen_at = '' THEN (
              SELECT first_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id
            )
            WHEN (SELECT first_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id) IS NULL
              OR (SELECT first_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id) = '' THEN first_seen_at
            WHEN (SELECT first_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id) < first_seen_at
              THEN (SELECT first_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id)
            ELSE first_seen_at
          END,
          last_seen_at = CASE
            WHEN last_seen_at IS NULL OR last_seen_at = '' THEN (
              SELECT last_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id
            )
            WHEN (SELECT last_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id) IS NULL
              OR (SELECT last_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id) = '' THEN last_seen_at
            WHEN (SELECT last_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id) > last_seen_at
              THEN (SELECT last_seen_at FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id)
            ELSE last_seen_at
          END
        WHERE EXISTS (
          SELECT 1 FROM delta.graph_delta_dj_profile d WHERE d.dj_id = dj_profile.dj_id
        );

        INSERT OR IGNORE INTO dj_event (
          dj_id, event_id, starts_at, time_text, event_title, venue_id, venue_name,
          city, source_ref_id, confidence
        )
        SELECT
          d.dj_id, d.event_id, d.starts_at, d.time_text, d.event_title, d.venue_id,
          d.venue_name, d.city, d.source_ref_id, MAX(d.confidence)
        FROM delta.graph_delta_dj_event d
        WHERE NOT EXISTS (
          SELECT 1 FROM dj_event existing
          WHERE existing.dj_id = d.dj_id AND existing.event_id = d.event_id
        )
        GROUP BY d.dj_id, d.event_id, d.starts_at, d.time_text, d.event_title,
                 d.venue_id, d.venue_name, d.city, d.source_ref_id;

        UPDATE dj_relation_rollup
        SET
          same_event_count = same_event_count + (
            SELECT same_event_increment
            FROM delta.graph_delta_relation d
            WHERE d.src_dj_id = dj_relation_rollup.src_dj_id
              AND d.dst_dj_id = dj_relation_rollup.dst_dj_id
          ),
          source_diversity = source_diversity + (
            SELECT source_diversity_increment
            FROM delta.graph_delta_relation d
            WHERE d.src_dj_id = dj_relation_rollup.src_dj_id
              AND d.dst_dj_id = dj_relation_rollup.dst_dj_id
          ),
          first_seen_at = CASE
            WHEN first_seen_at IS NULL OR first_seen_at = '' THEN (
              SELECT first_seen_at FROM delta.graph_delta_relation d
              WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id
            )
            WHEN (SELECT first_seen_at FROM delta.graph_delta_relation d
                  WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id) IS NULL
              OR (SELECT first_seen_at FROM delta.graph_delta_relation d
                  WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id) = ''
              THEN first_seen_at
            WHEN (SELECT first_seen_at FROM delta.graph_delta_relation d
                  WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id) < first_seen_at
              THEN (SELECT first_seen_at FROM delta.graph_delta_relation d
                    WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id)
            ELSE first_seen_at
          END,
          last_seen_at = CASE
            WHEN last_seen_at IS NULL OR last_seen_at = '' THEN (
              SELECT last_seen_at FROM delta.graph_delta_relation d
              WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id
            )
            WHEN (SELECT last_seen_at FROM delta.graph_delta_relation d
                  WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id) IS NULL
              OR (SELECT last_seen_at FROM delta.graph_delta_relation d
                  WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id) = ''
              THEN last_seen_at
            WHEN (SELECT last_seen_at FROM delta.graph_delta_relation d
                  WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id) > last_seen_at
              THEN (SELECT last_seen_at FROM delta.graph_delta_relation d
                    WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id)
            ELSE last_seen_at
          END,
          relation_score = relation_score + (
            SELECT relation_score_increment
            FROM delta.graph_delta_relation d
            WHERE d.src_dj_id = dj_relation_rollup.src_dj_id
              AND d.dst_dj_id = dj_relation_rollup.dst_dj_id
          ),
          relation_label_zh = CASE
            WHEN same_event_count + (
              SELECT same_event_increment FROM delta.graph_delta_relation d
              WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id
            ) >= 5
              OR relation_score + (
                SELECT relation_score_increment FROM delta.graph_delta_relation d
                WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id
              ) >= 26 THEN '高频同台'
            WHEN same_label_count >= 2 THEN '厂牌/组织关联'
            WHEN same_event_count + (
              SELECT same_event_increment FROM delta.graph_delta_relation d
              WHERE d.src_dj_id = dj_relation_rollup.src_dj_id AND d.dst_dj_id = dj_relation_rollup.dst_dj_id
            ) >= 2 THEN '多次同台'
            ELSE '同台出现'
          END,
          public_state = 'public_rollup'
        WHERE EXISTS (
          SELECT 1 FROM delta.graph_delta_relation d
          WHERE d.src_dj_id = dj_relation_rollup.src_dj_id
            AND d.dst_dj_id = dj_relation_rollup.dst_dj_id
        );

        INSERT OR IGNORE INTO dj_relation_rollup (
          src_dj_id, dst_dj_id, same_event_count, same_label_count,
          same_venue_count, same_source_context_count, source_diversity,
          first_seen_at, last_seen_at, relation_score, relation_label_zh,
          sample_evidence_json, public_state
        )
        SELECT
          src_dj_id, dst_dj_id, same_event_increment, 0,
          0, 0, source_diversity_increment,
          first_seen_at, last_seen_at, relation_score_increment, relation_label_zh,
          sample_evidence_json, 'public_rollup'
        FROM delta.graph_delta_relation;
        """
    )


def recompute_affected_profile_rollups(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT dj_id
        FROM tmp_affected_dj
        WHERE dj_id IS NOT NULL AND dj_id != ''
        """
    ).fetchall()
    for row in rows:
        dj_id = row["dj_id"]
        aliases = parse_json_list(
            conn.execute("SELECT aliases_json FROM dj_profile WHERE dj_id = ?", (dj_id,)).fetchone()["aliases_json"]
        )
        profile_display = conn.execute("SELECT display_name FROM dj_profile WHERE dj_id = ?", (dj_id,)).fetchone()[0]
        aliases = sorted({norm_text(profile_display), *(norm_text(alias) for alias in aliases if norm_text(alias))}, key=str.casefold)
        stats = conn.execute(
            """
            SELECT
              COUNT(DISTINCT event_id) AS event_count,
              COUNT(DISTINCT NULLIF(source_ref_id, '')) AS source_count,
              COUNT(DISTINCT NULLIF(venue_id, '')) AS venue_count,
              MIN(NULLIF(starts_at, '')) AS first_seen_at,
              MAX(NULLIF(starts_at, '')) AS last_seen_at,
              AVG(confidence) AS confidence
            FROM dj_event
            WHERE dj_id = ?
            """,
            (dj_id,),
        ).fetchone()
        city_row = conn.execute(
            """
            SELECT city
            FROM dj_event
            WHERE dj_id = ? AND city IS NOT NULL AND city != ''
            GROUP BY city
            ORDER BY COUNT(*) DESC, MAX(starts_at) DESC
            LIMIT 1
            """,
            (dj_id,),
        ).fetchone()
        relation_count = conn.execute(
            "SELECT COUNT(*) FROM dj_relation_rollup WHERE src_dj_id = ?",
            (dj_id,),
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE dj_profile
            SET aliases_json = ?,
                city_primary = COALESCE(NULLIF(city_primary, ''), ?),
                source_article_count = ?,
                event_count = ?,
                venue_count = ?,
                collaborator_count = ?,
                first_seen_at = COALESCE(NULLIF(?, ''), first_seen_at),
                last_seen_at = COALESCE(NULLIF(?, ''), last_seen_at),
                confidence = MAX(confidence, ?)
            WHERE dj_id = ?
            """,
            (
                json_dumps(aliases[:24]),
                city_row["city"] if city_row else "",
                int(stats["source_count"] or 0),
                int(stats["event_count"] or 0),
                int(stats["venue_count"] or 0),
                int(relation_count or 0),
                stats["first_seen_at"] or "",
                stats["last_seen_at"] or "",
                round(float(stats["confidence"] or 0), 4),
                dj_id,
            ),
        )


def rebuild_canonical_subjects(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DELETE FROM canonical_subject
        WHERE subject_type = 'dj'
          AND subject_id IN (SELECT dj_id FROM tmp_affected_dj);

        INSERT INTO canonical_subject (
          subject_id, subject_type, display_name, normalized_name, taxon_path,
          aliases_json, city_primary, confidence, source_count, event_count,
          relation_count, first_seen_at, last_seen_at, public_state
        )
        SELECT
          dj_id, 'dj', display_name, normalized_name, '音乐人/DJ',
          aliases_json, city_primary, confidence, source_article_count,
          event_count, collaborator_count, first_seen_at, last_seen_at,
          'public_rollup'
        FROM dj_profile
        WHERE dj_id IN (SELECT dj_id FROM tmp_affected_dj);
        """
    )


def replace_search_documents(conn: sqlite3.Connection) -> int:
    conn.executescript(
        """
        DELETE FROM search_document
        WHERE (subject_type = 'dj' AND subject_id IN (SELECT dj_id FROM tmp_affected_dj))
           OR (subject_type = 'event' AND subject_id IN (SELECT event_id FROM tmp_affected_event));
        """
    )
    max_rowid = int(conn.execute("SELECT COALESCE(MAX(doc_rowid), 0) FROM search_document").fetchone()[0])
    search_rows: list[tuple[Any, ...]] = []

    for row in conn.execute(
        """
        SELECT *
        FROM dj_profile
        WHERE dj_id IN (SELECT dj_id FROM tmp_affected_dj)
        ORDER BY event_count DESC, display_name
        """
    ):
        aliases = [norm_text(item) for item in parse_json_list(row["aliases_json"]) if norm_text(item)]
        max_rowid += 1
        search_rows.append(
            (
                max_rowid,
                row["dj_id"],
                "dj",
                row["display_name"],
                row["normalized_name"],
                " ".join(aliases),
                row["city_primary"] or "",
                "音乐人/DJ",
                int(row["event_count"] or 0) * 10
                + int(row["collaborator_count"] or 0) * 2
                + int(row["source_article_count"] or 0),
                row["last_seen_at"] or "",
                "public_rollup",
                build_search_text(
                    row["display_name"],
                    aliases,
                    row["city_primary"] or "",
                    "DJ 音乐人 artist performer",
                    row["event_count"] or 0,
                ),
            )
        )

    for row in conn.execute(
        """
        SELECT *
        FROM performance_event
        WHERE event_id IN (SELECT event_id FROM tmp_affected_event)
        ORDER BY starts_at DESC, event_title
        """
    ):
        max_rowid += 1
        search_rows.append(
            (
                max_rowid,
                row["event_id"],
                "event",
                row["event_title"],
                norm_key(row["event_title"]),
                row["venue_name"] or "",
                row["city"] or "",
                "历史活动/演出",
                2 + int(row["participant_count"] or 0),
                row["starts_at"] or "",
                "public_rollup",
                build_search_text(
                    row["event_title"],
                    row["venue_name"] or "",
                    row["city"] or "",
                    "历史活动 演出 event party",
                ),
            )
        )

    conn.executemany(
        "INSERT INTO search_document VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        search_rows,
    )
    if table_exists(conn, "search_document_fts"):
        conn.execute("INSERT INTO search_document_fts(search_document_fts) VALUES('rebuild')")
    return len(search_rows)


def build_graph_window(conn: sqlite3.Connection, seed_dj_id: str, generated_at: str) -> tuple[Any, ...]:
    profile = conn.execute("SELECT * FROM dj_profile WHERE dj_id = ?", (seed_dj_id,)).fetchone()
    display_name = profile["display_name"] if profile else seed_dj_id
    aliases = parse_json_list(profile["aliases_json"] if profile else "[]")
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def add_node(node_id: str, node_type: str, label: str, **attrs: Any) -> None:
        safe_label = norm_text(label)
        if not is_public_graph_label(safe_label):
            return
        if node_id and node_id not in nodes:
            nodes[node_id] = {"id": node_id, "type": node_type, "label": safe_label, **attrs}

    def add_edge(edge_id: str, source: str, target: str, edge_type: str, weight: float, **attrs: Any) -> None:
        if source and target and source in nodes and target in nodes and edge_id not in edges:
            edges[edge_id] = {
                "id": edge_id,
                "source": source,
                "target": target,
                "type": edge_type,
                "weight": round(float(weight), 4),
                **attrs,
            }

    add_node(seed_dj_id, "dj", display_name, role="seed", aliases=aliases[:8])
    for row in conn.execute(
        """
        SELECT r.dst_dj_id, r.same_event_count, r.relation_score, r.relation_label_zh, p.display_name
        FROM dj_relation_rollup r
        LEFT JOIN dj_profile p ON p.dj_id = r.dst_dj_id
        WHERE r.src_dj_id = ?
        ORDER BY r.relation_score DESC
        LIMIT ?
        """,
        (seed_dj_id, GRAPH_NODE_LIMITS["collaborator"]),
    ):
        dst = row["dst_dj_id"]
        add_node(dst, "dj", row["display_name"] or dst, role="collaborator")
        add_edge(
            f"rel:{seed_dj_id}:{dst}",
            seed_dj_id,
            dst,
            "dj_collaboration",
            row["relation_score"],
            label=row["relation_label_zh"],
            same_event_count=row["same_event_count"],
        )

    for row in conn.execute(
        """
        SELECT event_id, event_title, starts_at, city, venue_id, venue_name
        FROM dj_event
        WHERE dj_id = ?
        ORDER BY starts_at DESC
        LIMIT ?
        """,
        (seed_dj_id, GRAPH_NODE_LIMITS["event"]),
    ):
        event_id = row["event_id"]
        add_node(event_id, "event", row["event_title"], starts_at=row["starts_at"], city=row["city"])
        add_edge(f"played:{seed_dj_id}:{event_id}", seed_dj_id, event_id, "performed_at", 3.0)
        if row["venue_id"] and row["venue_name"]:
            add_node(row["venue_id"], "venue", row["venue_name"], city=row["city"])
            add_edge(f"hosted:{event_id}:{row['venue_id']}", event_id, row["venue_id"], "hosted_at", 2.0)

    for row in conn.execute(
        """
        SELECT venue_id, venue_name, city, score
        FROM dj_venue_rollup
        WHERE dj_id = ?
        ORDER BY score DESC
        LIMIT ?
        """,
        (seed_dj_id, GRAPH_NODE_LIMITS["venue"]),
    ):
        add_node(row["venue_id"], "venue", row["venue_name"], city=row["city"])
        add_edge(f"venue:{seed_dj_id}:{row['venue_id']}", seed_dj_id, row["venue_id"], "frequent_venue", row["score"])

    for row in conn.execute(
        """
        SELECT org_id, org_name, org_type, score
        FROM dj_org_rollup
        WHERE dj_id = ?
        ORDER BY score DESC
        LIMIT ?
        """,
        (seed_dj_id, GRAPH_NODE_LIMITS["org"]),
    ):
        add_node(row["org_id"], row["org_type"], row["org_name"])
        add_edge(f"org:{seed_dj_id}:{row['org_id']}", seed_dj_id, row["org_id"], "organized_by", row["score"])

    window_key = f"window:{seed_dj_id}:dj_core:2"
    return (
        window_key,
        seed_dj_id,
        "dj_core",
        2,
        len(nodes),
        len(edges),
        json_dumps(list(nodes.values())),
        json_dumps(list(edges.values())),
        generated_at,
    )


def rebuild_delta_graph_windows(conn: sqlite3.Connection, generated_at: str, limit: int) -> int:
    query = """
        SELECT dj_id
        FROM tmp_delta_dj
        WHERE dj_id IS NOT NULL AND dj_id != ''
        ORDER BY dj_id
    """
    if limit > 0:
        query += f" LIMIT {int(limit)}"
    dj_ids = [row["dj_id"] for row in conn.execute(query)]
    if not dj_ids:
        return 0
    conn.executemany("DELETE FROM graph_window_cache WHERE seed_subject_id = ?", [(dj_id,) for dj_id in dj_ids])
    rows = [build_graph_window(conn, dj_id, generated_at) for dj_id in dj_ids]
    conn.executemany("INSERT INTO graph_window_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def scoped_text_values(conn: sqlite3.Connection, table: str, where_sql: str) -> Iterable[tuple[int, str, str]]:
    columns = text_columns(conn, table)
    if not columns:
        return []
    for column in columns:
        sql = (
            f"SELECT rowid AS scan_rowid, {column} AS value FROM {table} "
            f"WHERE ({where_sql}) AND {column} IS NOT NULL AND {column} != ''"
        )
        for row in conn.execute(sql):
            yield int(row["scan_rowid"]), column, str(row["value"])


def scan_leakage(conn: sqlite3.Connection, sample_limit: int = 50) -> dict[str, Any]:
    scopes = {
        "performance_event": "event_id IN (SELECT event_id FROM tmp_affected_event)",
        "dj_event": "dj_id IN (SELECT dj_id FROM tmp_affected_dj) OR event_id IN (SELECT event_id FROM tmp_affected_event)",
        "dj_profile": "dj_id IN (SELECT dj_id FROM tmp_affected_dj)",
        "dj_relation_rollup": "src_dj_id IN (SELECT dj_id FROM tmp_affected_dj) OR dst_dj_id IN (SELECT dj_id FROM tmp_affected_dj)",
        "canonical_subject": "subject_id IN (SELECT dj_id FROM tmp_affected_dj)",
        "search_document": "subject_id IN (SELECT dj_id FROM tmp_affected_dj) OR subject_id IN (SELECT event_id FROM tmp_affected_event)",
        "graph_window_cache": "seed_subject_id IN (SELECT dj_id FROM tmp_delta_dj)",
    }
    hit_count = 0
    samples: list[dict[str, Any]] = []
    for table, where_sql in scopes.items():
        for rowid, column, value in scoped_text_values(conn, table, where_sql):
            if RAW_LEAK_RE.search(value):
                hit_count += 1
                if len(samples) < sample_limit:
                    samples.append({"table": table, "column": column, "rowid": rowid})
    return {"hit_count": hit_count, "samples": samples, "scope": "delta-affected public serving tables"}


def has_noise(value: str) -> bool:
    key = norm_key(value)
    if not key:
        return False
    if key in NOISE_KEYS:
        return True
    return any(term in key for term in PRODUCT_NOISE_TERMS)


def scrub_placeholder_place(value: Any) -> str:
    cleaned = norm_text(value)
    if norm_key(cleaned) in PLACEHOLDER_PLACE_KEYS:
        return ""
    return cleaned


def is_public_graph_label(value: Any) -> bool:
    cleaned = norm_text(value)
    return bool(cleaned) and RAW_LEAK_RE.search(cleaned) is None


def scrub_affected_placeholder_venues(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT event_id, venue_name
        FROM performance_event
        WHERE event_id IN (SELECT event_id FROM tmp_affected_event)
          AND venue_name IS NOT NULL
          AND venue_name != ''
        """
    ).fetchall()
    changed = 0
    for row in rows:
        scrubbed = scrub_placeholder_place(row["venue_name"])
        if scrubbed != norm_text(row["venue_name"]):
            conn.execute(
                "UPDATE performance_event SET venue_id = '', venue_name = ? WHERE event_id = ?",
                (scrubbed, row["event_id"]),
            )
            conn.execute(
                "UPDATE dj_event SET venue_id = '', venue_name = ? WHERE event_id = ?",
                (scrubbed, row["event_id"]),
            )
            changed += 1
    return changed


def scan_noise(conn: sqlite3.Connection, sample_limit: int = 50) -> dict[str, Any]:
    scopes = [
        (
            "dj_profile",
            "dj_id IN (SELECT dj_id FROM tmp_affected_dj)",
            ["display_name", "normalized_name", "aliases_json"],
        ),
        (
            "performance_event",
            "event_id IN (SELECT event_id FROM tmp_affected_event)",
            ["event_title", "venue_name", "city"],
        ),
        (
            "search_document",
            "subject_id IN (SELECT dj_id FROM tmp_affected_dj) OR subject_id IN (SELECT event_id FROM tmp_affected_event)",
            ["display_name", "normalized_name", "aliases_text", "search_text"],
        ),
    ]
    hit_count = 0
    samples: list[dict[str, Any]] = []
    for table, where_sql, columns in scopes:
        for column in columns:
            for row in conn.execute(
                f"SELECT rowid AS scan_rowid, {column} AS value FROM {table} WHERE ({where_sql})"
            ):
                value = str(row["value"] or "")
                if has_noise(value):
                    hit_count += 1
                    if len(samples) < sample_limit:
                        samples.append({"table": table, "column": column, "rowid": int(row["scan_rowid"])})
    return {"hit_count": hit_count, "samples": samples, "scope": "delta-affected profile/event/search fields"}


def fts_phrase(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def run_search_smoke(conn: sqlite3.Connection, sample_size: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT dj_id, display_name
        FROM dj_profile
        WHERE dj_id IN (SELECT dj_id FROM tmp_delta_dj)
          AND LENGTH(display_name) >= 3
        ORDER BY event_count DESC, display_name
        LIMIT ?
        """,
        (sample_size,),
    ).fetchall()
    like_missing: list[dict[str, str]] = []
    fts_missing: list[dict[str, str]] = []
    fts_available = table_exists(conn, "search_document_fts")
    for row in rows:
        dj_id = row["dj_id"]
        name = row["display_name"]
        like_hits = conn.execute(
            """
            SELECT COUNT(*)
            FROM search_document
            WHERE subject_id = ? AND subject_type = 'dj' AND search_text LIKE ?
            """,
            (dj_id, f"%{name}%"),
        ).fetchone()[0]
        if not like_hits:
            like_missing.append({"dj_id": dj_id, "display_name": name})
        if fts_available:
            try:
                fts_hits = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM search_document_fts f
                    JOIN search_document d ON d.doc_rowid = f.rowid
                    WHERE search_document_fts MATCH ?
                      AND d.subject_id = ?
                      AND d.subject_type = 'dj'
                    """,
                    (fts_phrase(name), dj_id),
                ).fetchone()[0]
            except sqlite3.OperationalError:
                fts_hits = 0
            if not fts_hits:
                fts_missing.append({"dj_id": dj_id, "display_name": name})
    return {
        "sample_size": len(rows),
        "like_missing_count": len(like_missing),
        "fts_missing_count": len(fts_missing),
        "like_missing_samples": like_missing[:20],
        "fts_missing_samples": fts_missing[:20],
        "fts_available": fts_available,
    }


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "dj_profile": count_table(conn, "dj_profile"),
        "performance_event": count_table(conn, "performance_event"),
        "dj_event": count_table(conn, "dj_event"),
        "dj_relation_rollup": count_table(conn, "dj_relation_rollup"),
        "canonical_subject": count_table(conn, "canonical_subject"),
        "search_document": count_table(conn, "search_document"),
        "graph_window_cache": count_table(conn, "graph_window_cache"),
    }


def delta_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "events": count_table(conn, "graph_delta_event"),
        "dj_profiles": count_table(conn, "graph_delta_dj_profile"),
        "dj_event_edges": count_table(conn, "graph_delta_dj_event"),
        "relations_directed": count_table(conn, "graph_delta_relation"),
    }


def write_candidate_metadata(conn: sqlite3.Connection, report: dict[str, Any]) -> None:
    metadata = {
        "participant_delta_candidate_schema_version": SCHEMA_VERSION,
        "participant_delta_candidate_generated_at": report["generated_at"],
        "participant_delta_candidate_summary": json_dumps(
            {
                "decision": report["decision"],
                "delta_db": report["paths"]["delta_db"],
                "summary_json": report["paths"]["summary_json"],
                "promotion_decision_required": True,
            }
        ),
        "participant_delta_promoted_to_production": "false",
    }
    conn.executemany("INSERT OR REPLACE INTO build_metadata(key, value) VALUES (?, ?)", list(metadata.items()))


def build_candidate(
    base_serving_db: Path,
    delta_db: Path,
    out_dir: Path,
    *,
    overwrite: bool = False,
    graph_window_limit: int = 0,
    search_sample_size: int = 40,
    delta_summary_path: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if not base_serving_db.exists():
        raise FileNotFoundError(base_serving_db)
    if not delta_db.exists():
        raise FileNotFoundError(delta_db)

    out_dir.mkdir(parents=True, exist_ok=True)
    candidate_db = out_dir / "atlas_serving.sqlite"
    if candidate_db.resolve() == base_serving_db.resolve():
        raise ValueError("candidate output must be a derived path, not the base serving DB")
    if candidate_db.exists() and not overwrite:
        raise FileExistsError(candidate_db)
    if candidate_db.exists():
        candidate_db.unlink()
    shutil.copy2(base_serving_db, candidate_db)

    generated_at = utc_now()
    delta_summary = read_json(delta_summary_path, {}) if delta_summary_path else {}

    delta_conn = connect(delta_db)
    try:
        source_delta_counts = delta_counts(delta_conn)
    finally:
        delta_conn.close()

    base_conn = connect(base_serving_db)
    try:
        before_counts = table_counts(base_conn)
    finally:
        base_conn.close()

    conn = connect(candidate_db)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        create_temp_scope(conn, delta_db)
        merge_delta_tables(conn)
        placeholder_venues_scrubbed = scrub_affected_placeholder_venues(conn)
        recompute_affected_profile_rollups(conn)
        rebuild_canonical_subjects(conn)
        search_docs_replaced = replace_search_documents(conn)
        graph_windows_rebuilt = rebuild_delta_graph_windows(conn, generated_at, graph_window_limit)
        after_counts = table_counts(conn)
        validation = {
            "leakage": scan_leakage(conn),
            "noise": scan_noise(conn),
            "search": run_search_smoke(conn, search_sample_size),
        }
        report: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "decision": "pending",
            "paths": {
                "base_serving_db": str(base_serving_db),
                "delta_db": str(delta_db),
                "candidate_db": str(candidate_db),
                "manifest_json": str(out_dir / "manifest.json"),
                "summary_json": str(out_dir / "participant_delta_candidate_summary.json"),
                "summary_md": str(out_dir / "participant_delta_candidate_summary.md"),
            },
            "delta_summary": delta_summary,
            "counts": {
                "base_before": before_counts,
                "candidate_after": after_counts,
                "candidate_delta": {key: after_counts[key] - before_counts.get(key, 0) for key in after_counts},
                "delta_applied": source_delta_counts,
                "search_documents_replaced": search_docs_replaced,
                "graph_windows_rebuilt": graph_windows_rebuilt,
                "placeholder_venues_scrubbed": placeholder_venues_scrubbed,
            },
            "validation": validation,
            "safety": {
                "copied_base_db": True,
                "base_serving_db_mutated": False,
                "raw_atlas_sqlite_mutated": False,
                "production_store_write_executed": False,
                "neo4j_write_executed": False,
                "qdrant_write_executed": False,
                "deploy_or_upload_executed": False,
                "promotion_decision_required": True,
            },
        }
        validation_passed = (
            validation["leakage"]["hit_count"] == 0
            and validation["noise"]["hit_count"] == 0
            and validation["search"]["like_missing_count"] == 0
        )
        report["decision"] = (
            "public_safe_serving_candidate_built_and_validated"
            if validation_passed
            else "serving_candidate_needs_review"
        )
        write_candidate_metadata(conn, report)
        conn.commit()
        detach_delta(conn)
    finally:
        conn.close()

    write_json(out_dir / "participant_delta_candidate_summary.json", report)
    write_markdown(out_dir / "participant_delta_candidate_summary.md", report)
    write_manifest(out_dir / "manifest.json", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-serving-db", type=Path, default=DEFAULT_BASE_SERVING_DB)
    parser.add_argument("--delta-db", type=Path, default=DEFAULT_DELTA_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--delta-summary", type=Path, default=None)
    parser.add_argument("--graph-window-limit", type=int, default=0, help="0 means all delta DJ profiles")
    parser.add_argument("--search-sample-size", type=int, default=40)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_candidate(
        args.base_serving_db,
        args.delta_db,
        args.out_dir,
        overwrite=args.overwrite,
        graph_window_limit=args.graph_window_limit,
        search_sample_size=args.search_sample_size,
        delta_summary_path=args.delta_summary,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["decision"] == "public_safe_serving_candidate_built_and_validated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
