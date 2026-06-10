#!/usr/bin/env python3
"""Build a full-entity-name DeepSeek merge queue for Atlas serving subjects.

This is report-only. It reads every public serving subject name, builds alias
candidate clusters by deterministic blocking, and writes LLM-ready evidence
packs. It does not call DeepSeek and never mutates Atlas SQLite.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "atlas_entity_merge_deepseek_queue.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_queue_current"
SUBJECT_TYPES = {"dj", "venue", "organizer", "radio"}
GENERIC_TOKENS = {
    "club",
    "clubs",
    "clubhouse",
    "venue",
    "bar",
    "live",
    "livehouse",
    "house",
    "room",
    "main",
    "label",
    "crew",
    "radio",
    "aka",
    "pres",
    "present",
    "presents",
    "record",
    "records",
    "music",
    "sound",
    "sounds",
    "studio",
    "studios",
    "official",
    "china",
    "the",
    "and",
    "of",
    "dj",
    "djs",
    "artist",
    "artists",
    "performer",
    "performers",
    "party",
    "rave",
    "event",
    "events",
    "俱乐部",
    "场地",
    "厂牌",
    "主办",
    "电台",
    "现场",
    "音乐人",
    "艺人",
    "艺术家",
    "演出",
    "活动",
    "派对",
    "唱片",
    "工作室",
}
CITY_TOKENS = {
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
    "shanghai",
    "beijing",
    "guangzhou",
    "shenzhen",
    "chengdu",
    "wuhan",
    "xiamen",
    "kunming",
    "hangzhou",
    "chongqing",
    "changsha",
    "xian",
    "nanjing",
    "suzhou",
    "ningbo",
    "tianjin",
    "fuzhou",
    "qingdao",
    "zhengzhou",
    "shenyang",
    "dalian",
    "hongkong",
    "taipei",
}
TOKEN_BOUNDARIES = sorted(GENERIC_TOKENS | CITY_TOKENS, key=len, reverse=True)
OCR_CONFUSABLE_GROUPS = [
    ("0", "o"),
    ("1", "l", "i"),
    ("5", "s"),
    ("8", "b"),
    ("2", "z"),
]
OCR_CONFUSABLE_TRANSLATION = str.maketrans({
    "0": "o",
    "1": "l",
    "i": "l",
    "5": "s",
    "8": "b",
    "2": "z",
})


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def key(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", unicodedata.normalize("NFKC", text(value)).casefold())


def ocr_skeleton(value: str) -> str:
    raw = key(value)
    if not raw or not re.search(r"[0-9a-z]", raw):
        return raw
    return raw.translate(OCR_CONFUSABLE_TRANSLATION)


def ocr_confusable_variants(value: str, limit: int = 16) -> list[str]:
    raw = key(value)
    if len(raw) < 3 or not re.search(r"[0-9a-z]", raw):
        return []
    variants = {raw, ocr_skeleton(raw)}
    positions: list[tuple[int, tuple[str, ...]]] = []
    for index, char in enumerate(raw):
        for group in OCR_CONFUSABLE_GROUPS:
            if char in group:
                positions.append((index, group))
                break
        if len(positions) >= 6:
            break
    queue = [raw]
    for index, group in positions:
        next_queue = list(queue)
        for item in queue:
            for replacement in group:
                if replacement == item[index]:
                    continue
                candidate = item[:index] + replacement + item[index + 1 :]
                if len(candidate) >= 3:
                    variants.add(candidate)
                    next_queue.append(candidate)
                    if len(variants) >= limit:
                        return sorted(variants)
        queue = next_queue[:limit]
    return sorted(variants)


def token_split(value: Any) -> list[str]:
    return [key(part) for part in re.split(r"[^0-9a-z\u4e00-\u9fff]+", text(value).casefold()) if key(part)]


def strip_boundary(value: str) -> list[str]:
    out: list[str] = []
    for token in TOKEN_BOUNDARIES:
        token_key = key(token)
        if not token_key or value == token_key or len(value) <= len(token_key):
            continue
        if value.startswith(token_key):
            out.append(value[len(token_key) :])
        if value.endswith(token_key):
            out.append(value[: -len(token_key)])
    return out


def alias_keys(*values: Any) -> list[str]:
    seen: set[str] = set()
    expandable: list[str] = []
    out: list[str] = []

    def add(value: Any, *, expand: bool = False) -> None:
        item = key(value)
        if not item or item in seen:
            return
        seen.add(item)
        out.append(item)
        if expand:
            expandable.append(item)

    for value in values:
        add(value, expand=True)
        for token in token_split(value):
            add(token, expand=True)
    for item in expandable[:32]:
        for stripped in strip_boundary(item):
            add(stripped)
        for variant in ocr_confusable_variants(item):
            add(variant)
    return [item for item in out if usable_block_key(item)]


def usable_block_key(value: str) -> bool:
    if not value or value in {key(item) for item in GENERIC_TOKENS} or value in CITY_TOKENS:
        return False
    if re.fullmatch(r"[a-z0-9]+", value):
        return len(value) >= 2
    return len(value) >= 2


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1", (table,)).fetchone()
    return bool(row)


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {name: row[name] for name in row.keys()}


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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


def load_subjects(conn: sqlite3.Connection, subject_types: set[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in subject_types)
    rows = conn.execute(
        f"""
        SELECT doc_rowid, subject_id, subject_type, display_name, normalized_name,
               aliases_text, city_text, taxon_path, rank_score, last_seen_at,
               public_state, search_text
        FROM search_document
        WHERE subject_type IN ({placeholders})
        ORDER BY rank_score DESC, doc_rowid
        """,
        tuple(sorted(subject_types)),
    ).fetchall()
    return [row_dict(row) for row in rows]


def parse_aliases(row: dict[str, Any]) -> list[str]:
    aliases = []
    for value in [row.get("aliases_text"), row.get("normalized_name"), row.get("search_text")]:
        for part in re.split(r"\s+", text(value)):
            part_text = text(part)
            if part_text and part_text not in aliases:
                aliases.append(part_text)
    return aliases[:24]


def subject_metrics(conn: sqlite3.Connection, row: dict[str, Any], *, include_rollup_metrics: bool) -> dict[str, Any]:
    subject_id = text(row.get("subject_id"))
    subject_type = text(row.get("subject_type"))
    metrics: dict[str, Any] = {"rank_score": int(row.get("rank_score") or 0)}
    if not include_rollup_metrics:
        return metrics
    if subject_type == "dj" and table_exists(conn, "dj_profile"):
        profile = conn.execute("SELECT event_count, venue_count, collaborator_count, organization_count, source_article_count, confidence FROM dj_profile WHERE dj_id = ? LIMIT 1", (subject_id,)).fetchone()
        if profile:
            metrics.update(row_dict(profile))
    if subject_type == "venue" and table_exists(conn, "performance_event"):
        event_count = conn.execute("SELECT COUNT(*) AS count FROM performance_event WHERE venue_id = ?", (subject_id,)).fetchone()["count"]
        metrics["event_count"] = int(event_count or 0)
    if subject_type == "venue" and table_exists(conn, "dj_venue_rollup"):
        rollup = conn.execute("SELECT COUNT(*) AS dj_count, COALESCE(SUM(event_count),0) AS linked_event_count FROM dj_venue_rollup WHERE venue_id = ?", (subject_id,)).fetchone()
        metrics.update({"linked_dj_count": int(rollup["dj_count"] or 0), "linked_event_count": int(rollup["linked_event_count"] or 0)})
    if subject_type in {"organizer", "radio"} and table_exists(conn, "dj_org_rollup"):
        rollup = conn.execute("SELECT COUNT(*) AS dj_count, COALESCE(SUM(evidence_count),0) AS evidence_count FROM dj_org_rollup WHERE org_id = ?", (subject_id,)).fetchone()
        metrics.update({"linked_dj_count": int(rollup["dj_count"] or 0), "evidence_count": int(rollup["evidence_count"] or 0)})
    return metrics


def build_metrics_cache(conn: sqlite3.Connection, subjects: list[dict[str, Any]], *, include_rollup_metrics: bool) -> dict[str, dict[str, Any]]:
    subject_type_by_id = {text(row.get("subject_id")): text(row.get("subject_type")) for row in subjects}
    cache: dict[str, dict[str, Any]] = {
        text(row.get("subject_id")): {"rank_score": int(row.get("rank_score") or 0)}
        for row in subjects
        if text(row.get("subject_id"))
    }
    if not include_rollup_metrics:
        return cache

    if table_exists(conn, "dj_profile"):
        rows = conn.execute(
            """
            SELECT dj_id, event_count, venue_count, collaborator_count,
                   organization_count, source_article_count, confidence
            FROM dj_profile
            """
        ).fetchall()
        for row in rows:
            subject_id = text(row["dj_id"])
            if subject_type_by_id.get(subject_id) == "dj":
                cache.setdefault(subject_id, {"rank_score": 0}).update(row_dict(row))

    if table_exists(conn, "performance_event"):
        rows = conn.execute(
            """
            SELECT venue_id, COUNT(*) AS event_count
            FROM performance_event
            WHERE venue_id <> ''
            GROUP BY venue_id
            """
        ).fetchall()
        for row in rows:
            subject_id = text(row["venue_id"])
            if subject_type_by_id.get(subject_id) == "venue":
                cache.setdefault(subject_id, {"rank_score": 0})["event_count"] = int(row["event_count"] or 0)

    if table_exists(conn, "dj_venue_rollup"):
        rows = conn.execute(
            """
            SELECT venue_id, COUNT(*) AS linked_dj_count,
                   COALESCE(SUM(event_count),0) AS linked_event_count
            FROM dj_venue_rollup
            WHERE venue_id <> ''
            GROUP BY venue_id
            """
        ).fetchall()
        for row in rows:
            subject_id = text(row["venue_id"])
            if subject_type_by_id.get(subject_id) == "venue":
                cache.setdefault(subject_id, {"rank_score": 0}).update(
                    {
                        "linked_dj_count": int(row["linked_dj_count"] or 0),
                        "linked_event_count": int(row["linked_event_count"] or 0),
                    }
                )

    if table_exists(conn, "dj_org_rollup"):
        rows = conn.execute(
            """
            SELECT org_id, COUNT(*) AS linked_dj_count,
                   COALESCE(SUM(evidence_count),0) AS evidence_count
            FROM dj_org_rollup
            WHERE org_id <> ''
            GROUP BY org_id
            """
        ).fetchall()
        for row in rows:
            subject_id = text(row["org_id"])
            if subject_type_by_id.get(subject_id) in {"organizer", "radio"}:
                cache.setdefault(subject_id, {"rank_score": 0}).update(
                    {
                        "linked_dj_count": int(row["linked_dj_count"] or 0),
                        "evidence_count": int(row["evidence_count"] or 0),
                    }
                )

    return cache


def evidence_samples(conn: sqlite3.Connection, row: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    subject_id = text(row.get("subject_id"))
    subject_type = text(row.get("subject_type"))
    source_refs: list[str] = []
    if subject_type == "dj" and table_exists(conn, "dj_event"):
        source_refs.extend(
            text(item["source_ref_id"])
            for item in conn.execute("SELECT DISTINCT source_ref_id FROM dj_event WHERE dj_id = ? AND source_ref_id <> '' LIMIT ?", (subject_id, limit)).fetchall()
        )
    if subject_type == "venue" and table_exists(conn, "performance_event"):
        source_refs.extend(
            text(item["source_ref_id"])
            for item in conn.execute("SELECT DISTINCT source_ref_id FROM performance_event WHERE venue_id = ? AND source_ref_id <> '' LIMIT ?", (subject_id, limit)).fetchall()
        )
    source_refs = [item for item in dict.fromkeys(source_refs) if item][:limit]
    if not source_refs or not table_exists(conn, "evidence_ref"):
        return []
    placeholders = ",".join("?" for _ in source_refs)
    rows = conn.execute(
        f"""
        SELECT source_ref_id, source_account, source_title, post_date, public_snippet
        FROM evidence_ref
        WHERE source_ref_id IN ({placeholders})
        ORDER BY post_date DESC
        LIMIT ?
        """,
        (*source_refs, limit),
    ).fetchall()
    return [row_dict(item) for item in rows]


def member_pack(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    *,
    include_rollup_metrics: bool,
    include_evidence_samples: bool,
    metrics_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    subject_id = text(row.get("subject_id"))
    return {
        "subject_id": subject_id,
        "subject_type": text(row.get("subject_type")),
        "display_name": text(row.get("display_name")),
        "city_text": text(row.get("city_text")),
        "taxon_path": text(row.get("taxon_path")),
        "aliases": parse_aliases(row),
        "metrics": dict(metrics_cache.get(subject_id, {})) if metrics_cache is not None else subject_metrics(conn, row, include_rollup_metrics=include_rollup_metrics),
        "evidence_samples": evidence_samples(conn, row) if include_evidence_samples else [],
    }


def risk_flags(members: list[dict[str, Any]], block_key: str) -> list[str]:
    flags: list[str] = []
    types = {text(item.get("subject_type")) for item in members}
    labels = [text(item.get("display_name")) for item in members]
    if len(types) > 1:
        flags.append("mixed_subject_types")
    if "dj" in types and ({"venue", "organizer", "radio"} & types):
        flags.append("dj_place_org_mix")
    if len(block_key) <= 3:
        flags.append("short_alias_key")
    if block_key != ocr_skeleton(block_key) or any(ocr_skeleton(label) == block_key and key(label) != block_key for label in labels):
        flags.append("ocr_confusable_key")
    if len(members) >= 12:
        flags.append("large_cluster")
    if any("遗孀" in label or "一员" in label for label in labels):
        flags.append("member_or_memorial_suffix")
    return flags


def build_clusters(
    conn: sqlite3.Connection,
    subjects: list[dict[str, Any]],
    max_members: int,
    *,
    include_rollup_metrics: bool,
    include_evidence_samples: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    inventory: list[dict[str, Any]] = []
    metrics_cache = build_metrics_cache(conn, subjects, include_rollup_metrics=include_rollup_metrics)
    for row in subjects:
        keys = alias_keys(row.get("display_name"), row.get("normalized_name"), row.get("aliases_text"))
        inventory.append(
            {
                "subject_id": text(row.get("subject_id")),
                "subject_type": text(row.get("subject_type")),
                "display_name": text(row.get("display_name")),
                "city_text": text(row.get("city_text")),
                "rank_score": int(row.get("rank_score") or 0),
                "analysis_keys": keys,
            }
        )
        for item in keys:
            blocks[item].append(row)

    clusters: list[dict[str, Any]] = []
    seen_signatures: set[tuple[str, ...]] = set()
    for block_key, rows in blocks.items():
        deduped = list({text(row.get("subject_id")): row for row in rows if text(row.get("subject_id"))}.values())
        if len(deduped) < 2:
            continue
        deduped.sort(key=lambda row: (int(row.get("rank_score") or 0), -int(row.get("doc_rowid") or 0)), reverse=True)
        signature = tuple(sorted(text(row.get("subject_id")) for row in deduped))
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        if len(deduped) <= max_members:
            chunks = [deduped]
        else:
            anchor = deduped[0]
            chunk_size = max(2, max_members)
            chunks = []
            for start in range(1, len(deduped), chunk_size - 1):
                chunks.append([anchor, *deduped[start : start + chunk_size - 1]])
        full_risk_flags = risk_flags(deduped, block_key)
        for part_index, chunk in enumerate(chunks):
            members = [
                member_pack(
                    conn,
                    row,
                    include_rollup_metrics=include_rollup_metrics,
                    include_evidence_samples=include_evidence_samples,
                    metrics_cache=metrics_cache,
                )
                for row in chunk
            ]
            part_suffix = f":part{part_index:04d}" if len(chunks) > 1 else ""
            clusters.append(
                {
                    "schema_version": SCHEMA_VERSION + ".cluster",
                    "cluster_id": f"entity-merge:{block_key}{part_suffix}",
                    "block_key": block_key,
                    "canonical_hint": {
                        "subject_id": text(deduped[0].get("subject_id")),
                        "display_name": text(deduped[0].get("display_name")),
                        "subject_type": text(deduped[0].get("subject_type")),
                        "rank_score": int(deduped[0].get("rank_score") or 0),
                    },
                    "member_count": len(chunk),
                    "block_member_count": len(deduped),
                    "cluster_part_index": part_index,
                    "cluster_part_count": len(chunks),
                    "members": members,
                    "risk_flags": sorted(set(full_risk_flags) | set(risk_flags(chunk, block_key))),
                    "llm_task": "Decide whether these Atlas subjects are the same real-world DJ, venue, organizer, or radio entity. Return merge, split, or review.",
                    "output_contract": {
                        "decision": "merge|split|review",
                        "canonical_subject_id": "string",
                        "canonical_name": "string",
                        "confidence": 0.0,
                        "merged_subject_ids": ["string"],
                        "blocked_subject_ids": ["string"],
                        "reason_zh": "string",
                        "risk_flags": ["string"],
                    },
                }
            )
    clusters.sort(
        key=lambda item: (
            item.get("block_member_count", item["member_count"]),
            item["canonical_hint"]["rank_score"],
            -item.get("cluster_part_index", 0),
        ),
        reverse=True,
    )
    return clusters, inventory


def build_queue(args: argparse.Namespace) -> dict[str, Any]:
    serving_db = Path(args.serving_db)
    out_dir = Path(args.out_dir)
    subject_types = {text(item) for item in str(args.subject_types).split(",") if text(item)} & SUBJECT_TYPES
    if not subject_types:
        subject_types = SUBJECT_TYPES
    with connect_readonly(serving_db) as conn:
        subjects = load_subjects(conn, subject_types)
        clusters, inventory = build_clusters(
            conn,
            subjects,
            max_members=max(2, int(args.max_members)),
            include_rollup_metrics=bool(args.include_rollup_metrics),
            include_evidence_samples=bool(args.include_evidence_samples),
        )
    if args.max_clusters and int(args.max_clusters) > 0:
        clusters = clusters[: int(args.max_clusters)]

    out_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = out_dir / "entity_name_inventory.jsonl"
    queue_path = out_dir / "entity_merge_llm_queue.jsonl"
    write_jsonl(inventory_path, inventory)
    write_jsonl(queue_path, clusters)
    type_counts = Counter(item["subject_type"] for item in inventory)
    subjects_in_clusters = len({member["subject_id"] for cluster in clusters for member in cluster["members"]})
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_merge_deepseek_queue_ready_report_only",
        "serving_db": str(serving_db),
        "out_dir": str(out_dir),
        "all_entity_names_analyzed": len(inventory),
        "subject_type_counts": dict(type_counts),
        "candidate_clusters": len(clusters),
        "subjects_in_candidate_clusters": subjects_in_clusters,
        "queue_path": str(queue_path),
        "inventory_path": str(inventory_path),
        "safety": {
            "report_only": True,
            "llm_call_executed": False,
            "sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "raw_secret_read": False,
        },
        "queue_mode": {
            "include_rollup_metrics": bool(args.include_rollup_metrics),
            "include_evidence_samples": bool(args.include_evidence_samples),
        },
    }
    write_json(out_dir / "entity_merge_queue_summary.json", summary)
    write_markdown(out_dir / "entity_merge_queue_report.md", summary, clusters[:20])
    return summary


def write_markdown(path: Path, summary: dict[str, Any], clusters: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas Entity Merge DeepSeek Queue",
        "",
        f"- decision: `{summary['decision']}`",
        f"- all_entity_names_analyzed: `{summary['all_entity_names_analyzed']}`",
        f"- candidate_clusters: `{summary['candidate_clusters']}`",
        f"- subjects_in_candidate_clusters: `{summary['subjects_in_candidate_clusters']}`",
        f"- queue: `{summary['queue_path']}`",
        "",
        "## Top Candidate Clusters",
        "",
    ]
    for cluster in clusters:
        labels = ", ".join(member["display_name"] for member in cluster["members"][:8])
        lines.append(f"- `{cluster['block_key']}` -> {labels}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving-db", default=os.environ.get("ATLAS_SERVING_SQLITE_DB") or str(DEFAULT_SERVING_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--subject-types", default="dj,venue,organizer,radio")
    parser.add_argument("--max-members", type=int, default=24)
    parser.add_argument("--max-clusters", type=int, default=0)
    parser.add_argument("--include-rollup-metrics", action="store_true")
    parser.add_argument("--include-evidence-samples", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = build_queue(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
