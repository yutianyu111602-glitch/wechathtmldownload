#!/usr/bin/env python3
"""Audit where Atlas DJ graph value is lost across the full-LLM pipeline.

This is an incident-style quality audit for the DJ-first Atlas product. It
reads existing local artifacts only: the release SQLite, stable merge summary,
consumer release manifest, SQLite build report, and graph promotion summaries.
It does not call LLMs, touch the network, or mutate production state.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
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
DEFAULT_STABLE_SUMMARY = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "stable_merge_all_full_llm_runs_127511_plus_legacy_v30_10591_20260520"
    / "stable_merge_summary.json"
)
DEFAULT_RELEASE_MANIFEST = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "consumer_release_pack_all_full_llm_runs_138102_20260520"
    / "manifest.json"
)
DEFAULT_SQLITE_REPORT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_local_sqlite_db_138102_20260521"
    / "atlas_local_sqlite_db_report.json"
)
DEFAULT_GRAPH_PROMOTION = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "graph_production_promotion_all_full_llm_138102_verify_20260520"
    / "promotion_report.json"
)
DEFAULT_DJ_COLLAB_SUMMARY = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "dj_collab_graph_all_full_llm_138102_20260520"
    / "dj_collab_graph_summary.json"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_product_loss_chain_20260522"

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
DJ_TYPE_TERMS = ["person", "dj", "artist"]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def scalar(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = ()) -> int:
    value = conn.execute(sql, tuple(args)).fetchone()[0]
    return int(value or 0)


def fetch_dicts(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [row_dict(row) for row in conn.execute(sql, tuple(args))]


def rate(part: int, total: int) -> float:
    if not total:
        return 0.0
    return round(part / total, 6)


def noise_predicate(column_expr: str) -> str:
    clauses = []
    for term in NOISE_TERMS:
        escaped = term.replace("'", "''")
        clauses.append(f"lower({column_expr}) LIKE '%{escaped.lower()}%'")
    return "(" + " OR ".join(clauses) + ")"


def collect_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {table: scalar(conn, f"SELECT COUNT(*) FROM {table}") for table in ["articles", "entities", "events"]}


def collect_article_quality(conn: sqlite3.Connection) -> dict[str, Any]:
    total = scalar(conn, "SELECT COUNT(*) FROM articles")
    row = row_dict(
        conn.execute(
            """
            SELECT
              SUM(CASE WHEN event_count = 0 THEN 1 ELSE 0 END) AS event_count_zero,
              SUM(CASE WHEN entity_count = 0 THEN 1 ELSE 0 END) AS entity_count_zero,
              SUM(CASE WHEN trim(COALESCE(publish_time, '')) = '' THEN 1 ELSE 0 END) AS publish_time_empty,
              SUM(CASE WHEN local_image_count > 0 AND event_count = 0 THEN 1 ELSE 0 END) AS image_with_no_event,
              SUM(CASE WHEN local_image_count >= 3 AND event_count = 0 THEN 1 ELSE 0 END) AS image_heavy_with_no_event,
              SUM(CASE WHEN lower(COALESCE(quality_grade, '')) = 'ready' AND event_count = 0 THEN 1 ELSE 0 END) AS ready_with_no_event
            FROM articles
            """
        ).fetchone()
    )
    return {
        "total": total,
        **{key: int(row.get(key) or 0) for key in row},
        "rates": {key: rate(int(row.get(key) or 0), total) for key in row},
    }


def collect_event_quality(conn: sqlite3.Connection) -> dict[str, Any]:
    total = scalar(conn, "SELECT COUNT(*) FROM events")
    row = row_dict(
        conn.execute(
            """
            SELECT
              SUM(CASE WHEN trim(COALESCE(name, '')) = '' THEN 1 ELSE 0 END) AS name_empty,
              SUM(CASE WHEN trim(COALESCE(participants_json, '')) IN ('', '[]') THEN 1 ELSE 0 END) AS participants_empty,
              SUM(CASE WHEN trim(COALESCE(organizers_json, '')) IN ('', '[]') THEN 1 ELSE 0 END) AS organizers_empty,
              SUM(CASE WHEN trim(COALESCE(place, '')) = '' THEN 1 ELSE 0 END) AS place_empty,
              SUM(CASE WHEN trim(COALESCE(time_iso, '')) = '' THEN 1 ELSE 0 END) AS time_iso_empty,
              SUM(CASE WHEN trim(COALESCE(time_text, '')) = '' THEN 1 ELSE 0 END) AS time_text_empty,
              SUM(CASE WHEN confidence < 0.8 THEN 1 ELSE 0 END) AS low_conf_lt_08
            FROM events
            """
        ).fetchone()
    )
    return {
        "total": total,
        **{key: int(row.get(key) or 0) for key in row},
        "rates": {key: rate(int(row.get(key) or 0), total) for key in row},
    }


def collect_entity_quality(conn: sqlite3.Connection) -> dict[str, Any]:
    total = scalar(conn, "SELECT COUNT(*) FROM entities")
    type_counts = {
        str(row["type_norm"] or ""): int(row["count"] or 0)
        for row in conn.execute(
            """
            SELECT lower(COALESCE(type, '')) AS type_norm, COUNT(*) AS count
            FROM entities
            GROUP BY lower(COALESCE(type, ''))
            ORDER BY count DESC
            """
        )
    }
    noise_expr = noise_predicate("COALESCE(name, '') || ' ' || COALESCE(bio, '') || ' ' || COALESCE(vector_text_preview, '')")
    product_rows = int(type_counts.get("product", 0))
    noise_rows = scalar(conn, f"SELECT COUNT(*) FROM entities WHERE lower(COALESCE(type, '')) = 'product' OR {noise_expr}")
    dj_like_rows = sum(type_counts.get(kind, 0) for kind in DJ_TYPE_TERMS)
    alias_nonempty = scalar(conn, "SELECT COUNT(*) FROM entities WHERE trim(COALESCE(aliases_json, '')) NOT IN ('', '[]')")
    bio_nonempty = scalar(conn, "SELECT COUNT(*) FROM entities WHERE trim(COALESCE(bio, '')) != ''")
    return {
        "total": total,
        "type_counts": type_counts,
        "dj_like_rows": dj_like_rows,
        "product_rows": product_rows,
        "noise_like_rows": noise_rows,
        "alias_nonempty": alias_nonempty,
        "bio_nonempty": bio_nonempty,
        "rates": {
            "dj_like_rows": rate(dj_like_rows, total),
            "product_rows": rate(product_rows, total),
            "noise_like_rows": rate(noise_rows, total),
            "alias_nonempty": rate(alias_nonempty, total),
            "bio_nonempty": rate(bio_nonempty, total),
        },
    }


def collect_article_entity_cross_quality(conn: sqlite3.Connection) -> dict[str, Any]:
    noise_expr = noise_predicate("COALESCE(e.name, '') || ' ' || COALESCE(e.bio, '') || ' ' || COALESCE(e.vector_text_preview, '')")
    row = row_dict(
        conn.execute(
            f"""
            WITH per_article AS (
              SELECT
                e.source_article_uid AS article_uid,
                COUNT(*) AS entity_rows,
                SUM(CASE WHEN lower(COALESCE(e.type, '')) IN ('person', 'dj', 'artist') THEN 1 ELSE 0 END) AS dj_like_rows,
                SUM(CASE WHEN lower(COALESCE(e.type, '')) = 'product' OR {noise_expr} THEN 1 ELSE 0 END) AS noise_like_rows
              FROM entities e
              GROUP BY e.source_article_uid
            )
            SELECT
              COUNT(*) AS articles_with_entities,
              SUM(CASE WHEN pa.noise_like_rows > 0 THEN 1 ELSE 0 END) AS articles_with_noise_like_entities,
              SUM(CASE WHEN pa.noise_like_rows > 0 AND COALESCE(pa.dj_like_rows, 0) = 0 THEN 1 ELSE 0 END) AS noise_without_dj_articles,
              SUM(CASE WHEN pa.noise_like_rows > 0 AND COALESCE(a.event_count, 0) = 0 THEN 1 ELSE 0 END) AS noise_no_event_articles,
              SUM(CASE WHEN pa.dj_like_rows > 0 AND COALESCE(a.event_count, 0) = 0 THEN 1 ELSE 0 END) AS dj_entity_no_event_articles
            FROM per_article pa
            LEFT JOIN articles a ON a.article_uid = pa.article_uid
            """
        ).fetchone()
    )
    total_articles = scalar(conn, "SELECT COUNT(*) FROM articles")
    return {
        **{key: int(row.get(key) or 0) for key in row},
        "rates_vs_articles": {key: rate(int(row.get(key) or 0), total_articles) for key in row},
    }


def collect_source_quality(conn: sqlite3.Connection) -> dict[str, Any]:
    noise_expr = noise_predicate("COALESCE(e.name, '') || ' ' || COALESCE(e.bio, '') || ' ' || COALESCE(e.vector_text_preview, '')")
    top_sources = fetch_dicts(
        conn,
        """
        SELECT
          source_account,
          COUNT(*) AS articles,
          SUM(entity_count) AS entity_rows,
          SUM(event_count) AS event_rows,
          SUM(CASE WHEN event_count = 0 THEN 1 ELSE 0 END) AS no_event_articles,
          SUM(local_image_count) AS local_images
        FROM articles
        GROUP BY source_account
        ORDER BY articles DESC, source_account
        LIMIT 25
        """,
    )
    noisy_sources = fetch_dicts(
        conn,
        f"""
        SELECT
          COALESCE(a.source_account, '') AS source_account,
          COUNT(*) AS noise_entity_rows,
          COUNT(DISTINCT e.source_article_uid) AS noise_articles
        FROM entities e
        LEFT JOIN articles a ON a.article_uid = e.source_article_uid
        WHERE lower(COALESCE(e.type, '')) = 'product' OR {noise_expr}
        GROUP BY COALESCE(a.source_account, '')
        ORDER BY noise_entity_rows DESC, source_account
        LIMIT 25
        """,
    )
    return {"top_sources": top_sources, "noisy_sources": noisy_sources}


def collect_samples(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    noise_expr = noise_predicate("COALESCE(e.name, '') || ' ' || COALESCE(e.bio, '') || ' ' || COALESCE(e.vector_text_preview, '')")
    return {
        "event_missing_participants": fetch_dicts(
            conn,
            """
            SELECT ev.evid, ev.name, ev.place, ev.time_text, ev.source_article_uid, a.title, a.source_account
            FROM events ev
            LEFT JOIN articles a ON a.article_uid = ev.source_article_uid
            WHERE trim(COALESCE(ev.participants_json, '')) IN ('', '[]')
            LIMIT 25
            """,
        ),
        "event_missing_place": fetch_dicts(
            conn,
            """
            SELECT ev.evid, ev.name, ev.participants_json, ev.time_text, ev.source_article_uid, a.title, a.source_account
            FROM events ev
            LEFT JOIN articles a ON a.article_uid = ev.source_article_uid
            WHERE trim(COALESCE(ev.place, '')) = ''
            LIMIT 25
            """,
        ),
        "noise_entities": fetch_dicts(
            conn,
            f"""
            SELECT e.eid, e.name, e.type, e.confidence, e.source_article_uid, a.title, a.source_account
            FROM entities e
            LEFT JOIN articles a ON a.article_uid = e.source_article_uid
            WHERE lower(COALESCE(e.type, '')) = 'product' OR {noise_expr}
            LIMIT 50
            """,
        ),
        "image_articles_without_events": fetch_dicts(
            conn,
            """
            SELECT article_uid, title, source_account, local_image_count, entity_count, event_count, quality_grade
            FROM articles
            WHERE local_image_count > 0 AND event_count = 0
            ORDER BY local_image_count DESC, article_uid
            LIMIT 50
            """,
        ),
        "dj_entity_without_events": fetch_dicts(
            conn,
            """
            SELECT DISTINCT a.article_uid, a.title, a.source_account, a.entity_count, a.event_count, a.local_image_count
            FROM articles a
            JOIN entities e ON e.source_article_uid = a.article_uid
            WHERE a.event_count = 0
              AND lower(COALESCE(e.type, '')) IN ('person', 'dj', 'artist')
            LIMIT 50
            """,
        ),
    }


def stable_release_deltas(stable_summary: dict[str, Any], release_manifest: dict[str, Any]) -> dict[str, Any]:
    totals = stable_summary.get("totals", {}) if isinstance(stable_summary, dict) else {}
    stable_entities = int(totals.get("entities") or 0)
    stable_events = int(totals.get("events") or 0)
    release_entities = int(release_manifest.get("entities") or 0)
    release_events = int(release_manifest.get("events") or 0)
    return {
        "stable_entities": stable_entities,
        "release_entities": release_entities,
        "entity_delta_stable_minus_release": stable_entities - release_entities,
        "stable_events": stable_events,
        "release_events": release_events,
        "event_delta_stable_minus_release": stable_events - release_events,
        "low_confidence_skipped": int(release_manifest.get("low_confidence_skipped") or 0),
        "missing_publish_time_articles": int(release_manifest.get("missing_publish_time_articles") or 0),
        "allow_unknown_publish_time": bool(release_manifest.get("allow_unknown_publish_time")),
        "date_index_path": release_manifest.get("date_index_path", ""),
    }


def graph_surface_deltas(
    release_manifest: dict[str, Any],
    graph_promotion: dict[str, Any],
    dj_collab_summary: dict[str, Any],
) -> dict[str, Any]:
    after = graph_promotion.get("after_counts", {}) if isinstance(graph_promotion, dict) else {}
    graph_entities = int(after.get("entity", {}).get("promoted") or after.get("entity", {}).get("staging") or 0)
    graph_events = int(after.get("event", {}).get("promoted") or after.get("event", {}).get("staging") or 0)
    release_entities = int(release_manifest.get("entities") or 0)
    release_events = int(release_manifest.get("events") or 0)
    usable_events = int(dj_collab_summary.get("usable_events") or 0)
    participant_mentions = int(dj_collab_summary.get("participant_mentions") or 0)
    return {
        "release_entities": release_entities,
        "graph_unique_entities": graph_entities,
        "release_minus_graph_entities": release_entities - graph_entities,
        "release_events": release_events,
        "graph_unique_events": graph_events,
        "release_minus_graph_events": release_events - graph_events,
        "dj_collab_event_rows": int(dj_collab_summary.get("event_rows") or 0),
        "dj_collab_usable_events": usable_events,
        "dj_collab_unusable_events": int(dj_collab_summary.get("event_rows") or 0) - usable_events,
        "participant_mentions": participant_mentions,
        "dj_collab_node_count": int(dj_collab_summary.get("node_count") or 0),
        "dj_collab_edge_count": int(dj_collab_summary.get("edge_count") or 0),
    }


def build_loss_findings(
    stable_summary: dict[str, Any],
    release_deltas: dict[str, Any],
    article_quality: dict[str, Any],
    event_quality: dict[str, Any],
    entity_quality: dict[str, Any],
    cross_quality: dict[str, Any],
    graph_deltas: dict[str, Any],
) -> list[dict[str, Any]]:
    lane_counts = stable_summary.get("lane_counts", {}) if isinstance(stable_summary, dict) else {}
    return [
        {
            "stage": "source_asset_and_ocr",
            "severity": "high",
            "finding": "Image/OCR evidence did not always become model input; full LLM only sees text that survived OCR-to-Markdown.",
            "evidence": {
                "empty_no_local_image": int(lane_counts.get("empty_no_local_image") or 0),
                "needs_ocr": int(lane_counts.get("needs_ocr") or 0),
                "short_text_review": int(lane_counts.get("short_text_review") or 0),
                "image_articles_without_events": article_quality.get("image_with_no_event"),
                "image_heavy_articles_without_events": article_quality.get("image_heavy_with_no_event"),
            },
            "impact_on_dj_product": "Poster/lineup-only DJ names can be absent before LLM extraction starts.",
        },
        {
            "stage": "llm_extraction_scope",
            "severity": "high",
            "finding": "Full LLM extraction produced a broad article atlas, not a DJ-first domain graph.",
            "evidence": {
                "product_rows": entity_quality.get("product_rows"),
                "noise_like_rows": entity_quality.get("noise_like_rows"),
                "noise_without_dj_articles": cross_quality.get("noise_without_dj_articles"),
                "noise_no_event_articles": cross_quality.get("noise_no_event_articles"),
            },
            "impact_on_dj_product": "Wine/menu/product rows can be accepted as ready while DJ history remains sparse.",
        },
        {
            "stage": "event_field_completeness",
            "severity": "critical",
            "finding": "Many event rows do not have the fields needed to build DJ history and same-event relations.",
            "evidence": {
                "events": event_quality.get("total"),
                "participants_empty": event_quality.get("participants_empty"),
                "place_empty": event_quality.get("place_empty"),
                "organizers_empty": event_quality.get("organizers_empty"),
                "time_text_empty": event_quality.get("time_text_empty"),
            },
            "impact_on_dj_product": "No participant list means no DJ-event edge; no place means no venue history; no organizer means weak label/crew inference.",
        },
        {
            "stage": "release_pack_normalization",
            "severity": "high",
            "finding": "Release mapping preserved raw time text but did not normalize publish/event dates into indexed ISO fields.",
            "evidence": {
                "time_iso_empty": event_quality.get("time_iso_empty"),
                "missing_publish_time_articles": release_deltas.get("missing_publish_time_articles"),
                "date_index_path": release_deltas.get("date_index_path"),
                "allow_unknown_publish_time": release_deltas.get("allow_unknown_publish_time"),
            },
            "impact_on_dj_product": "History timelines, future/past separation, and recency scoring are weak even when text mentions dates.",
        },
        {
            "stage": "stable_to_release_filtering",
            "severity": "medium",
            "finding": "Stable outputs were filtered before release, mostly by confidence gate.",
            "evidence": release_deltas,
            "impact_on_dj_product": "Some low-confidence facts disappear from the release surface instead of entering a review queue.",
        },
        {
            "stage": "graph_surface_materialization",
            "severity": "high",
            "finding": "Graph production unique node surface is smaller than the release row surface, and the DJ collaboration graph only uses participant-complete events.",
            "evidence": graph_deltas,
            "impact_on_dj_product": "A website wired to graph markers or old graph APIs can miss rows present in local SQLite/release packs.",
        },
    ]


def write_markdown(path: Path, audit: dict[str, Any]) -> None:
    summary = audit["summary"]
    article = audit["article_quality"]
    event = audit["event_quality"]
    entity = audit["entity_quality"]
    graph = audit["graph_surface_deltas"]
    release = audit["stable_release_deltas"]
    lines = [
        "# Atlas DJ Product Loss Chain Audit",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_db: `{summary['source_db']}`",
        f"- write_status: `{summary['write_status']}`",
        f"- safety: network `{summary['safety']['network_call_executed']}`, llm `{summary['safety']['llm_call_executed']}`, production write `{summary['safety']['production_write_executed']}`",
        "",
        "## Direct Answer",
        "",
        "Full LLM did run, but it produced a broad article-level atlas. It did not guarantee a DJ-first historical graph.",
        "The strongest losses are event participant sparsity, missing date normalization, OCR-to-Markdown evidence gaps, and domain noise entering the release surface.",
        "",
        "## Key Counts",
        "",
        "| Area | Count | Rate |",
        "|---|---:|---:|",
        f"| Articles | {article['total']} | 1.000000 |",
        f"| Articles with no events | {article['event_count_zero']} | {article['rates']['event_count_zero']:.6f} |",
        f"| Image articles with no events | {article['image_with_no_event']} | {article['rates']['image_with_no_event']:.6f} |",
        f"| Events | {event['total']} | 1.000000 |",
        f"| Events without participants | {event['participants_empty']} | {event['rates']['participants_empty']:.6f} |",
        f"| Events without place | {event['place_empty']} | {event['rates']['place_empty']:.6f} |",
        f"| Events without organizers | {event['organizers_empty']} | {event['rates']['organizers_empty']:.6f} |",
        f"| Events without time_iso | {event['time_iso_empty']} | {event['rates']['time_iso_empty']:.6f} |",
        f"| Events without time_text | {event['time_text_empty']} | {event['rates']['time_text_empty']:.6f} |",
        f"| Entity rows | {entity['total']} | 1.000000 |",
        f"| DJ-like entity rows | {entity['dj_like_rows']} | {entity['rates']['dj_like_rows']:.6f} |",
        f"| Product rows | {entity['product_rows']} | {entity['rates']['product_rows']:.6f} |",
        f"| Noise-like entity rows | {entity['noise_like_rows']} | {entity['rates']['noise_like_rows']:.6f} |",
        "",
        "## Release And Graph Deltas",
        "",
        "| Delta | Count |",
        "|---|---:|",
        f"| Stable events | {release['stable_events']} |",
        f"| Release events | {release['release_events']} |",
        f"| Stable minus release events | {release['event_delta_stable_minus_release']} |",
        f"| Stable entities | {release['stable_entities']} |",
        f"| Release entities | {release['release_entities']} |",
        f"| Stable minus release entities | {release['entity_delta_stable_minus_release']} |",
        f"| Low confidence skipped | {release['low_confidence_skipped']} |",
        f"| Missing publish time articles | {release['missing_publish_time_articles']} |",
        f"| Graph unique events | {graph['graph_unique_events']} |",
        f"| Release minus graph events | {graph['release_minus_graph_events']} |",
        f"| DJ collab usable events | {graph['dj_collab_usable_events']} |",
        f"| DJ collab unusable events | {graph['dj_collab_unusable_events']} |",
        "",
        "## Loss Chain",
        "",
    ]
    for finding in audit["loss_findings"]:
        lines.extend(
            [
                f"### {finding['stage']}",
                "",
                f"- severity: `{finding['severity']}`",
                f"- finding: {finding['finding']}",
                f"- impact: {finding['impact_on_dj_product']}",
                f"- evidence: `{json.dumps(finding['evidence'], ensure_ascii=False, sort_keys=True)}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Next Fix Order",
            "",
            "1. Build a DJ-first extraction audit queue: prioritize rows with DJ-like entities but zero events, and image/poster rows with zero events.",
            "2. Add release-pack date normalization: parse `time_text` and publish-time indexes into queryable ISO fields while preserving raw text.",
            "3. Add domain gating before public graph: route product/menu/wine rows to a noise layer, not the main DJ graph.",
            "4. Materialize DJ history sidecars from all participant-complete events, then backfill participant-empty music rows through review/OCR.",
            "5. Wire the web/API to DJ sidecars instead of the older generic graph marker surface.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)


def build_audit(
    db_path: Path,
    out_dir: Path,
    stable_summary_path: Path | None = DEFAULT_STABLE_SUMMARY,
    release_manifest_path: Path | None = DEFAULT_RELEASE_MANIFEST,
    sqlite_report_path: Path | None = DEFAULT_SQLITE_REPORT,
    graph_promotion_path: Path | None = DEFAULT_GRAPH_PROMOTION,
    dj_collab_summary_path: Path | None = DEFAULT_DJ_COLLAB_SUMMARY,
) -> dict[str, Any]:
    stable_summary = read_json(stable_summary_path)
    release_manifest = read_json(release_manifest_path)
    sqlite_report = read_json(sqlite_report_path)
    graph_promotion = read_json(graph_promotion_path)
    dj_collab_summary = read_json(dj_collab_summary_path)

    conn = connect_readonly(db_path)
    try:
        table_counts = collect_table_counts(conn)
        article_quality = collect_article_quality(conn)
        event_quality = collect_event_quality(conn)
        entity_quality = collect_entity_quality(conn)
        cross_quality = collect_article_entity_cross_quality(conn)
        source_quality = collect_source_quality(conn)
        samples = collect_samples(conn)
    finally:
        conn.close()

    release_deltas = stable_release_deltas(stable_summary, release_manifest)
    graph_deltas = graph_surface_deltas(release_manifest, graph_promotion, dj_collab_summary)
    loss_findings = build_loss_findings(
        stable_summary,
        release_deltas,
        article_quality,
        event_quality,
        entity_quality,
        cross_quality,
        graph_deltas,
    )
    audit = {
        "schema_version": "atlas_dj_product_loss_chain_audit.v1",
        "summary": {
            "generated_at": now_iso(),
            "source_db": str(db_path),
            "out_dir": str(out_dir),
            "write_status": "report_only",
            "safety": {
                "network_call_executed": False,
                "llm_call_executed": False,
                "paid_api_used": False,
                "source_archive_mutated": False,
                "sqlite_source_write_executed": False,
                "neo4j_write_executed": False,
                "qdrant_write_executed": False,
                "production_write_executed": False,
            },
            "artifact_inputs": {
                "stable_summary": str(stable_summary_path or ""),
                "release_manifest": str(release_manifest_path or ""),
                "sqlite_report": str(sqlite_report_path or ""),
                "graph_promotion": str(graph_promotion_path or ""),
                "dj_collab_summary": str(dj_collab_summary_path or ""),
            },
        },
        "table_counts": table_counts,
        "article_quality": article_quality,
        "event_quality": event_quality,
        "entity_quality": entity_quality,
        "article_entity_cross_quality": cross_quality,
        "source_quality": source_quality,
        "stable_release_deltas": release_deltas,
        "graph_surface_deltas": graph_deltas,
        "sqlite_report_counts": sqlite_report.get("actual_counts", {}),
        "stable_lane_counts": stable_summary.get("lane_counts", {}),
        "loss_findings": loss_findings,
        "outputs": {
            "summary_json": str(out_dir / "summary.json"),
            "audit_md": str(out_dir / "audit.md"),
            "event_missing_participants_jsonl": str(out_dir / "event_missing_participants_samples.jsonl"),
            "event_missing_place_jsonl": str(out_dir / "event_missing_place_samples.jsonl"),
            "noise_entities_jsonl": str(out_dir / "noise_entity_samples.jsonl"),
            "image_articles_without_events_jsonl": str(out_dir / "image_articles_without_events_samples.jsonl"),
            "dj_entity_without_events_jsonl": str(out_dir / "dj_entity_without_events_samples.jsonl"),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "summary.json", audit)
    write_markdown(out_dir / "audit.md", audit)
    write_jsonl(out_dir / "event_missing_participants_samples.jsonl", samples["event_missing_participants"])
    write_jsonl(out_dir / "event_missing_place_samples.jsonl", samples["event_missing_place"])
    write_jsonl(out_dir / "noise_entity_samples.jsonl", samples["noise_entities"])
    write_jsonl(out_dir / "image_articles_without_events_samples.jsonl", samples["image_articles_without_events"])
    write_jsonl(out_dir / "dj_entity_without_events_samples.jsonl", samples["dj_entity_without_events"])
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--stable-summary", type=Path, default=DEFAULT_STABLE_SUMMARY)
    parser.add_argument("--release-manifest", type=Path, default=DEFAULT_RELEASE_MANIFEST)
    parser.add_argument("--sqlite-report", type=Path, default=DEFAULT_SQLITE_REPORT)
    parser.add_argument("--graph-promotion", type=Path, default=DEFAULT_GRAPH_PROMOTION)
    parser.add_argument("--dj-collab-summary", type=Path, default=DEFAULT_DJ_COLLAB_SUMMARY)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = build_audit(
        args.db,
        args.out_dir,
        stable_summary_path=args.stable_summary,
        release_manifest_path=args.release_manifest,
        sqlite_report_path=args.sqlite_report,
        graph_promotion_path=args.graph_promotion,
        dj_collab_summary_path=args.dj_collab_summary,
    )
    print(json.dumps({"ok": True, "out_dir": str(args.out_dir), "summary": audit["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
