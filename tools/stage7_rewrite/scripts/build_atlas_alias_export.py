#!/usr/bin/env python3
"""Build a report-only Atlas alias export for weekly entity linking.

The export is a read-only bridge artifact. It does not write Neo4j, Qdrant,
SQLite, CloudRun, or mini-program release state.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENTITIES = PROJECT_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "stage7_atlas" / "entities.jsonl.gz"
DEFAULT_OUT_DIR = Path("tools/stage7_rewrite/reports") / f"atlas_alias_export_138102_{datetime.now().strftime('%Y%m%d')}"
SCHEMA_VERSION = "atlas_alias_export.v1"

STRIP_RE = re.compile(r"[\s\-_./\\'\u2018\u2019\u201c\u201d\u300c\u300d\uff08\uff09()\[\]{}]")
DATE_OR_TIME_RE = re.compile(r"^\d{1,4}([./:-]\d{1,2}){1,3}$")
URL_RE = re.compile(r"https?://|www\.|mmbiz\.qpic\.cn|qpic\.cn|wx_fmt=", re.I)
GENERIC_ALIAS_RE = re.compile(
    r"^(?:dj|mc|live|set|lineup|guest|special|club|bar|party|music|sound|"
    r"ticket|tickets|wechat|公众号|二维码|购票|门票|地址|时间|地点|阵容|嘉宾|"
    r"周一|周二|周三|周四|周五|周六|周日|今天|今晚)$",
    re.I,
)


def compact_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = STRIP_RE.sub("", text)
    return text.strip()


def display_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def useful_alias(value: str) -> bool:
    text = display_name(value)
    key = compact_key(text)
    if not text or not key:
        return False
    if URL_RE.search(text) or DATE_OR_TIME_RE.match(key):
        return False
    if GENERIC_ALIAS_RE.match(key):
        return False
    if len(key) < 2 or len(text) > 80:
        return False
    if key.isdigit():
        return False
    return True


def stable_ceid(entity_type: str, key: str) -> str:
    digest = hashlib.sha1(f"{entity_type}|{key}".encode("utf-8")).hexdigest()[:12]
    return f"ceid:{entity_type}:{digest}"


def open_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def group_entities(
    rows: Iterable[dict[str, Any]],
    *,
    include_types: set[str],
    min_confidence: float,
) -> dict[tuple[str, str], dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        entity_type = display_name(row.get("type") or row.get("entity_type") or "").lower()
        if entity_type not in include_types:
            continue
        name = display_name(row.get("name"))
        name_key = compact_key(name)
        if not useful_alias(name):
            continue
        confidence = float(row.get("confidence") or 0)
        if confidence < min_confidence:
            continue
        key = (entity_type, name_key)
        group = groups.setdefault(
            key,
            {
                "entity_type": entity_type,
                "name_key": name_key,
                "display_names": Counter(),
                "aliases": Counter(),
                "source_articles": set(),
                "confidence_sum": 0.0,
                "mention_count": 0,
                "sample_eids": [],
            },
        )
        group["display_names"][name] += 1
        group["aliases"][name] += 1
        for alias in row.get("aliases") or []:
            alias_text = display_name(alias)
            if useful_alias(alias_text):
                group["aliases"][alias_text] += 1
        source_uid = display_name(row.get("source_article_uid"))
        if source_uid:
            group["source_articles"].add(source_uid)
        group["confidence_sum"] += confidence
        group["mention_count"] += 1
        eid = display_name(row.get("eid"))
        if eid and len(group["sample_eids"]) < 5:
            group["sample_eids"].append(eid)
    return groups


def build_export_rows(
    groups: dict[tuple[str, str], dict[str, Any]],
    *,
    min_mentions: int,
    max_aliases_per_entity: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    exported_entities = 0
    skipped_low_mentions = 0
    type_counts: Counter[str] = Counter()
    alias_count_by_entity: Counter[str] = Counter()

    for (_entity_type, _name_key), group in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        mention_count = int(group["mention_count"])
        if mention_count < min_mentions:
            skipped_low_mentions += 1
            continue
        entity_type = str(group["entity_type"])
        canonical_name = group["display_names"].most_common(1)[0][0]
        ceid = stable_ceid(entity_type, str(group["name_key"]))
        artist_id = f"atlas:entity:{ceid}"
        avg_confidence = round(float(group["confidence_sum"]) / max(mention_count, 1), 4)
        aliases: list[str] = []
        seen_alias_keys: set[str] = set()
        for alias, _count in group["aliases"].most_common():
            alias_key = compact_key(alias)
            if not alias_key or alias_key in seen_alias_keys:
                continue
            seen_alias_keys.add(alias_key)
            aliases.append(alias)
            if len(aliases) >= max_aliases_per_entity:
                break
        for alias in aliases:
            rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ceid": ceid,
                    "artist_id": artist_id,
                    "entity_type": entity_type,
                    "canonical_name": canonical_name,
                    "alias": alias,
                    "alias_norm": compact_key(alias),
                    "verified": True,
                    "verification_basis": "atlas_entity_name_group",
                    "mention_count": mention_count,
                    "source_article_count": len(group["source_articles"]),
                    "avg_confidence": avg_confidence,
                    "sample_eids": group["sample_eids"],
                }
            )
        exported_entities += 1
        type_counts[entity_type] += 1
        alias_count_by_entity[ceid] = len(aliases)

    summary = {
        "schema_version": "atlas_alias_export_summary.v1",
        "decision": "atlas_alias_export_ready_report_only",
        "ok": bool(rows),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "export_schema_version": SCHEMA_VERSION,
        "exported_entities": exported_entities,
        "exported_alias_rows": len(rows),
        "skipped_low_mentions": skipped_low_mentions,
        "type_counts": dict(type_counts),
        "max_aliases_per_entity": max(alias_count_by_entity.values() or [0]),
        "safety": {
            "report_only": True,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "sqlite_write_executed": False,
            "cloudrun_deploy_executed": False,
            "miniprogram_upload_executed": False,
            "llm_call_executed": False,
        },
    }
    return rows, summary


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def render_markdown(summary: dict[str, Any], out_dir: Path) -> str:
    lines = [
        "# Atlas Alias Export",
        "",
        f"- decision: `{summary['decision']}`",
        f"- ok: `{summary['ok']}`",
        f"- exported_entities: `{summary['exported_entities']}`",
        f"- exported_alias_rows: `{summary['exported_alias_rows']}`",
        f"- skipped_low_mentions: `{summary['skipped_low_mentions']}`",
        f"- export: `{out_dir / 'atlas_alias_export.v1.jsonl'}`",
        "",
        "## Type Counts",
        "",
        "| type | entities |",
        "|---|---:|",
    ]
    for key, value in sorted((summary.get("type_counts") or {}).items()):
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "Report-only export. No Neo4j, Qdrant, SQLite, CloudRun, mini-program upload, or LLM call was executed.",
            "",
        ]
    )
    return "\n".join(lines)


def build_alias_export(
    entities_jsonl: Path,
    out_dir: Path,
    *,
    include_types: set[str],
    min_mentions: int,
    min_confidence: float,
    max_aliases_per_entity: int,
) -> dict[str, Any]:
    groups = group_entities(open_jsonl(entities_jsonl), include_types=include_types, min_confidence=min_confidence)
    rows, summary = build_export_rows(groups, min_mentions=min_mentions, max_aliases_per_entity=max_aliases_per_entity)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "atlas_alias_export.v1.jsonl", rows)
    write_json(out_dir / "atlas_alias_export_summary.json", summary)
    (out_dir / "atlas_alias_export_summary.md").write_text(render_markdown(summary, out_dir), encoding="utf-8")
    summary["out_dir"] = str(out_dir)
    summary["export_path"] = str(out_dir / "atlas_alias_export.v1.jsonl")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build report-only Atlas alias export for weekly entity linking.")
    parser.add_argument("--entities-jsonl", type=Path, default=DEFAULT_ENTITIES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--include-types", default="person,group")
    parser.add_argument("--min-mentions", type=int, default=2)
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--max-aliases-per-entity", type=int, default=12)
    args = parser.parse_args()

    include_types = {part.strip().lower() for part in args.include_types.split(",") if part.strip()}
    summary = build_alias_export(
        args.entities_jsonl,
        args.out_dir,
        include_types=include_types,
        min_mentions=args.min_mentions,
        min_confidence=args.min_confidence,
        max_aliases_per_entity=args.max_aliases_per_entity,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
