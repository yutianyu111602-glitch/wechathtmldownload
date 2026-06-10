#!/usr/bin/env python3
"""Build report-only repair queues for the DJ-first Atlas product.

The queue turns the loss-chain audit into actionable slices. It prioritizes
rows that can improve DJ history and relationship quality without blindly
rerunning the full LLM pipeline:

* DJ-like entities in articles with no events.
* Image/poster-heavy articles with no events.
* Music-looking events without participants.
* Participant-complete events without places.
* Time text that needs ISO normalization.
* Non-music/product rows that should be routed out of the main DJ graph.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
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
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_repair_priority_queue_20260522"

DJ_TYPES = {"person", "dj", "artist"}
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
VENUE_SOURCE_HINTS = [
    "oil",
    "dada",
    "all",
    "tag",
    "zhaodai",
    "招待",
    "dng",
    "dong",
    "bo live",
    "club",
    "bar",
    "live",
    "俱乐部",
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
TIME_SIGNAL_RE = re.compile(r"(\d{4}[-./年]\d{1,2}|\d{1,2}[-./月]\d{1,2}|\b\d{1,2}:\d{2}\b|周[一二三四五六日天]|星期[一二三四五六日天])")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def lower_blob(*values: Any) -> str:
    return " ".join(text(value).casefold() for value in values if text(value))


def contains_any(blob: str, terms: list[str]) -> bool:
    return any(term.casefold() in blob for term in terms)


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def fetch(conn: sqlite3.Connection, sql: str, args: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [row_dict(row) for row in conn.execute(sql, tuple(args))]


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


def queue_row(
    queue: str,
    priority_score: float,
    reason: str,
    recommended_action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    article_uid = text(payload.get("article_uid") or payload.get("source_article_uid"))
    event_id = text(payload.get("evid"))
    entity_id = text(payload.get("eid"))
    return {
        "schema_version": "atlas_dj_repair_priority_queue.row.v1",
        "queue": queue,
        "priority_score": round(priority_score, 4),
        "reason": reason,
        "recommended_action": recommended_action,
        "article_uid": article_uid,
        "event_id": event_id,
        "entity_id": entity_id,
        "title": text(payload.get("title")),
        "source_account": text(payload.get("source_account")),
        "name": text(payload.get("name")),
        "place": text(payload.get("place")),
        "time_text": text(payload.get("time_text")),
        "local_image_count": int(payload.get("local_image_count") or 0),
        "entity_count": int(payload.get("entity_count") or 0),
        "event_count": int(payload.get("event_count") or 0),
        "confidence": float(payload.get("confidence") or 0),
        "evidence": payload,
        "write_status": "report_only",
    }


def article_music_score(row: dict[str, Any]) -> float:
    blob = lower_blob(row.get("title"), row.get("source_account"), row.get("dj_names"), row.get("vector_text_preview"))
    score = 0.0
    if contains_any(blob, MUSIC_TERMS):
        score += 6.0
    if contains_any(blob, VENUE_SOURCE_HINTS):
        score += 4.0
    score += min(int(row.get("local_image_count") or 0), 8) * 0.8
    score += min(int(row.get("dj_entity_count") or 0), 12) * 0.6
    score += min(int(row.get("entity_count") or 0), 30) * 0.05
    return score


def event_music_score(row: dict[str, Any]) -> float:
    blob = lower_blob(row.get("name"), row.get("title"), row.get("source_account"), row.get("vector_text_preview"))
    score = 0.0
    if contains_any(blob, MUSIC_TERMS):
        score += 6.0
    if contains_any(blob, VENUE_SOURCE_HINTS):
        score += 4.0
    if TIME_SIGNAL_RE.search(text(row.get("time_text"))):
        score += 1.5
    score += float(row.get("confidence") or 0) * 2.0
    return score


def build_dj_entity_no_event_queue(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = fetch(
        conn,
        """
        SELECT
          a.article_uid,
          a.title,
          a.source_account,
          a.local_image_count,
          a.entity_count,
          a.event_count,
          GROUP_CONCAT(DISTINCT e.name) AS dj_names,
          COUNT(*) AS dj_entity_count,
          MAX(e.confidence) AS confidence
        FROM articles a
        JOIN entities e ON e.source_article_uid = a.article_uid
        WHERE a.event_count = 0
          AND lower(COALESCE(e.type, '')) IN ('person', 'dj', 'artist')
        GROUP BY a.article_uid
        LIMIT ?
        """,
        (limit * 8,),
    )
    out = []
    for row in rows:
        score = article_music_score(row)
        if score <= 0:
            score = 1 + min(int(row.get("dj_entity_count") or 0), 10) * 0.4
        out.append(
            queue_row(
                "dj_entity_no_event_article",
                score,
                "文章存在 DJ-like 实体但 event_count=0，可能是历史演出信息没有被抽成 event。",
                "优先复核原文/Markdown/OCR，生成 performance_event 和 DJ_PLAYED_EVENT。",
                row,
            )
        )
    out.sort(key=lambda item: (-item["priority_score"], item["source_account"], item["title"]))
    return out[:limit]


def build_image_no_event_queue(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = fetch(
        conn,
        """
        SELECT article_uid, title, source_account, local_image_count, entity_count, event_count, quality_grade, vector_text_preview
        FROM articles
        WHERE event_count = 0 AND local_image_count > 0
        ORDER BY local_image_count DESC, entity_count DESC, article_uid
        LIMIT ?
        """,
        (limit * 8,),
    )
    out = []
    for row in rows:
        score = article_music_score(row)
        if score <= 0 and int(row.get("local_image_count") or 0) < 3:
            continue
        out.append(
            queue_row(
                "image_or_poster_no_event_article",
                score,
                "文章有本地图片/海报但没有 event，可能是海报阵容没有进入 LLM 输入或没有抽取成活动。",
                "检查 image/GIF -> OCR -> Markdown merge；必要时只重跑该文章的 Flash/Pro 修复。",
                row,
            )
        )
    out.sort(key=lambda item: (-item["priority_score"], -item["local_image_count"], item["source_account"]))
    return out[:limit]


def build_participant_empty_event_queue(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = fetch(
        conn,
        """
        SELECT
          ev.evid,
          ev.name,
          ev.place,
          ev.time_text,
          ev.source_article_uid AS article_uid,
          ev.confidence,
          ev.vector_text_preview,
          a.title,
          a.source_account,
          a.local_image_count,
          a.entity_count,
          a.event_count
        FROM events ev
        LEFT JOIN articles a ON a.article_uid = ev.source_article_uid
        WHERE trim(COALESCE(ev.participants_json, '')) IN ('', '[]')
        LIMIT ?
        """,
        (limit * 20,),
    )
    out = []
    for row in rows:
        score = event_music_score(row)
        if score < 5:
            continue
        out.append(
            queue_row(
                "participant_empty_music_event",
                score,
                "活动像音乐/俱乐部事件但 participants 为空，无法生成 DJ 历史演出边。",
                "从同篇实体、标题、OCR 海报和原文阵容中补 participants_json。",
                row,
            )
        )
    out.sort(key=lambda item: (-item["priority_score"], item["source_account"], item["title"]))
    return out[:limit]


def build_missing_place_queue(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = fetch(
        conn,
        """
        SELECT
          ev.evid,
          ev.name,
          ev.place,
          ev.time_text,
          ev.participants_json,
          ev.source_article_uid AS article_uid,
          ev.confidence,
          ev.vector_text_preview,
          a.title,
          a.source_account,
          a.local_image_count,
          a.entity_count,
          a.event_count
        FROM events ev
        LEFT JOIN articles a ON a.article_uid = ev.source_article_uid
        WHERE trim(COALESCE(ev.place, '')) = ''
          AND trim(COALESCE(ev.participants_json, '')) NOT IN ('', '[]')
        LIMIT ?
        """,
        (limit * 12,),
    )
    out = []
    for row in rows:
        score = event_music_score(row) + 2.0
        if contains_any(lower_blob(row.get("source_account")), VENUE_SOURCE_HINTS):
            score += 4.0
        out.append(
            queue_row(
                "missing_place_with_participants",
                score,
                "活动已有 participants 但 place 为空，DJ 历史存在但俱乐部/场地边缺失。",
                "用 source_account、标题、正文地址、同篇 place 实体补 EVENT_AT_VENUE。",
                row,
            )
        )
    out.sort(key=lambda item: (-item["priority_score"], item["source_account"], item["title"]))
    return out[:limit]


def build_time_normalization_queue(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = fetch(
        conn,
        """
        SELECT
          ev.evid,
          ev.name,
          ev.place,
          ev.time_text,
          ev.source_article_uid AS article_uid,
          ev.confidence,
          a.title,
          a.source_account,
          a.local_image_count,
          a.entity_count,
          a.event_count
        FROM events ev
        LEFT JOIN articles a ON a.article_uid = ev.source_article_uid
        WHERE trim(COALESCE(ev.time_iso, '')) = ''
          AND trim(COALESCE(ev.time_text, '')) != ''
        LIMIT ?
        """,
        (limit * 20,),
    )
    out = []
    for row in rows:
        if not TIME_SIGNAL_RE.search(text(row.get("time_text"))):
            continue
        score = event_music_score(row) + 3.0
        out.append(
            queue_row(
                "time_iso_normalization_candidate",
                score,
                "event 有 time_text 但 time_iso 为空，历史时间线和未来/过去判断不可索引。",
                "解析 time_text + source publish/context，写入独立 date normalization sidecar，不覆盖原文。",
                row,
            )
        )
    out.sort(key=lambda item: (-item["priority_score"], item["time_text"], item["source_account"]))
    return out[:limit]


def build_noise_quarantine_queue(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    clauses = " OR ".join(["lower(COALESCE(e.name, '') || ' ' || COALESCE(e.bio, '') || ' ' || COALESCE(e.vector_text_preview, '')) LIKE ?" for _ in NOISE_TERMS])
    args = [f"%{term.casefold()}%" for term in NOISE_TERMS]
    rows = fetch(
        conn,
        f"""
        SELECT
          e.eid,
          e.name,
          e.type,
          e.confidence,
          e.source_article_uid AS article_uid,
          a.title,
          a.source_account,
          a.local_image_count,
          a.entity_count,
          a.event_count
        FROM entities e
        LEFT JOIN articles a ON a.article_uid = e.source_article_uid
        WHERE lower(COALESCE(e.type, '')) = 'product' OR {clauses}
        LIMIT ?
        """,
        [*args, limit * 4],
    )
    out = []
    for row in rows:
        score = 5.0
        if text(row.get("type")).casefold() == "product":
            score += 4.0
        if contains_any(lower_blob(row.get("name"), row.get("title")), NOISE_TERMS):
            score += 3.0
        out.append(
            queue_row(
                "noise_quarantine_candidate",
                score,
                "非音乐产品/菜单/酒水实体不应进入主 DJ 图谱。",
                "移入 noise/domain_quarantine 层；保留证据但不返回公共 DJ graph seed。",
                row,
            )
        )
    out.sort(key=lambda item: (-item["priority_score"], item["source_account"], item["name"]))
    return out[:limit]


def build_repair_priority_queue(db_path: Path, out_dir: Path, per_queue_limit: int = 500) -> dict[str, Any]:
    conn = connect_readonly(db_path)
    try:
        queues = {
            "dj_entity_no_event_article": build_dj_entity_no_event_queue(conn, per_queue_limit),
            "image_or_poster_no_event_article": build_image_no_event_queue(conn, per_queue_limit),
            "participant_empty_music_event": build_participant_empty_event_queue(conn, per_queue_limit),
            "missing_place_with_participants": build_missing_place_queue(conn, per_queue_limit),
            "time_iso_normalization_candidate": build_time_normalization_queue(conn, per_queue_limit),
            "noise_quarantine_candidate": build_noise_quarantine_queue(conn, per_queue_limit),
        }
    finally:
        conn.close()

    all_rows = []
    for rows in queues.values():
        all_rows.extend(rows)
    all_rows.sort(key=lambda item: (-item["priority_score"], item["queue"], item["source_account"], item["title"]))

    counts = {name: len(rows) for name, rows in queues.items()}
    top_sources = Counter(row["source_account"] for row in all_rows if row["source_account"]).most_common(30)
    summary = {
        "schema_version": "atlas_dj_repair_priority_queue.summary.v1",
        "generated_at": now_iso(),
        "source_db": str(db_path),
        "out_dir": str(out_dir),
        "per_queue_limit": per_queue_limit,
        "queue_counts": counts,
        "total_rows": len(all_rows),
        "top_sources": [{"source_account": key, "count": count} for key, count in top_sources],
        "priority_order": [
            "dj_entity_no_event_article",
            "image_or_poster_no_event_article",
            "participant_empty_music_event",
            "missing_place_with_participants",
            "time_iso_normalization_candidate",
            "noise_quarantine_candidate",
        ],
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
        "outputs": {
            "summary_json": str(out_dir / "summary.json"),
            "queue_jsonl": str(out_dir / "repair_priority_queue.jsonl"),
            "queue_dir": str(out_dir / "queues"),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "summary.json", summary)
    write_jsonl(out_dir / "repair_priority_queue.jsonl", all_rows)
    for name, rows in queues.items():
        write_jsonl(out_dir / "queues" / f"{name}.jsonl", rows)
    write_markdown(out_dir / "summary.md", summary, queues)
    return {"summary": summary, "queues": queues, "rows": all_rows}


def write_markdown(path: Path, summary: dict[str, Any], queues: dict[str, list[dict[str, Any]]]) -> None:
    lines = [
        "# Atlas DJ Repair Priority Queue",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_db: `{summary['source_db']}`",
        f"- total_rows: `{summary['total_rows']}`",
        f"- write_status: `report_only`",
        "",
        "## Queue Counts",
        "",
        "| Queue | Rows | Purpose |",
        "|---|---:|---|",
    ]
    purpose = {
        "dj_entity_no_event_article": "有 DJ 实体但没有活动，优先补历史演出",
        "image_or_poster_no_event_article": "海报/图片文章无活动，优先查 OCR-to-Markdown",
        "participant_empty_music_event": "活动缺阵容，无法形成 DJ 边",
        "missing_place_with_participants": "活动有阵容但缺场地，无法形成俱乐部历史",
        "time_iso_normalization_candidate": "有原始时间文本但缺 ISO 索引",
        "noise_quarantine_candidate": "酒水/菜单/产品等移出主图谱",
    }
    for name in summary["priority_order"]:
        lines.append(f"| `{name}` | {summary['queue_counts'].get(name, 0)} | {purpose[name]} |")
    lines.extend(["", "## Top Sources", "", "| Source | Count |", "|---|---:|"])
    for row in summary["top_sources"][:20]:
        lines.append(f"| `{row['source_account']}` | {row['count']} |")
    lines.extend(["", "## Top Samples", ""])
    for name in summary["priority_order"]:
        lines.extend([f"### {name}", "", "| Score | Source | Title / Name | Action |", "|---:|---|---|---|"])
        for row in queues.get(name, [])[:12]:
            label = row["title"] or row["name"]
            lines.append(f"| {row['priority_score']:.2f} | `{row['source_account']}` | `{label}` | {row['recommended_action']} |")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--per-queue-limit", type=int, default=500)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_repair_priority_queue(args.db, args.out_dir, max(1, args.per_queue_limit))
    print(json.dumps({"ok": True, "summary": result["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
