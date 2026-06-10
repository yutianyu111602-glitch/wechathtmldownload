"""Build a local Stage7 consumer release-pack draft from stable extracts.

The pack is a staging artifact for badDJ/weekly consumers. It does not publish,
write production SQLite, call paid APIs, touch Qdrant/Neo4j, or scan D:. The
default command builds a bounded canary so the mapping can be checked before a
full release-pack write.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO


DEFAULT_STABLE_ARTICLES = Path(
    "reports/fullmap_47k_ready_text_authok_20260513_174006/"
    "stable_extract_v1/stable_articles.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/consumer_release_pack_canary_20260514")
SCHEMA_VERSION = "stage7_consumer_release_pack.v1"
MIN_CONFIDENCE = 0.5


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for this release-pack builder: {path}")


def first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def clip(text: str, limit: int = 500) -> str:
    text = first_text(text)
    return text if len(text) <= limit else text[:limit]


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def first_evidence_quote(row: dict[str, Any]) -> str:
    evidence = row.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                quote = first_text(item.get("quote"), item.get("text"))
                if quote:
                    return quote
            else:
                quote = first_text(item)
                if quote:
                    return quote
    return ""


def publish_time(article: dict[str, Any]) -> str:
    return first_text(
        article.get("publish_time"),
        article.get("post_date"),
        article.get("publish_time_iso"),
        article.get("publish_time_text"),
    )


def load_date_index(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            uid = first_text(row.get("article_uid"))
            if uid:
                rows[uid] = row
    return rows


def apply_date_index(article: dict[str, Any], date_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    uid = first_text(article.get("article_uid"))
    date_row = date_index.get(uid) or {}
    if not date_row:
        return article
    out = dict(article)
    status = first_text(date_row.get("status"))
    source_archived_at = first_text(date_row.get("source_archived_at"))
    if status == "publish_time_found":
        out["publish_time"] = first_text(date_row.get("publish_time"))
        out["publish_time_source"] = first_text(date_row.get("publish_time_source"))
    if source_archived_at:
        out["source_archived_at"] = source_archived_at
        out["source_archived_at_source"] = first_text(date_row.get("source_archived_at_source"))
    out["publish_time_index_status"] = status
    return out


def article_card(article: dict[str, Any]) -> dict[str, Any]:
    source_account = first_text(article.get("source_account"))
    title = first_text(article.get("title"))
    entities = article.get("entities") if isinstance(article.get("entities"), list) else []
    events = article.get("events") if isinstance(article.get("events"), list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "card_type": "article",
        "article_uid": first_text(article.get("article_uid")),
        "article_id": first_text(article.get("article_id")),
        "source_account": source_account,
        "title": title,
        "publish_time": publish_time(article),
        "publish_time_status": "known" if publish_time(article) else "unknown",
        "publish_time_source": first_text(article.get("publish_time_source")),
        "source_archived_at": first_text(article.get("source_archived_at")),
        "source_archived_at_source": first_text(article.get("source_archived_at_source")),
        "publish_time_index_status": first_text(article.get("publish_time_index_status")),
        "city_label": first_text(article.get("city_label"), article.get("city")),
        "entity_count": len(entities),
        "event_count": len(events),
        "quality_grade": first_text(article.get("quality_grade")),
        "input_chars": int_value(article.get("input_chars")),
        "local_image_count": int_value(article.get("local_image_count")),
        "extract_version": "V6",
        "vector_text": clip(f"公众号:{source_account} | 标题:{title}"),
    }


def entity_card(article: dict[str, Any], entity: dict[str, Any], idx: int) -> dict[str, Any]:
    article_uid = first_text(article.get("article_uid"))
    name = first_text(entity.get("name"))
    entity_type = first_text(entity.get("type"), entity.get("entity_type"))
    bio = first_text(entity.get("bio"))
    city = first_text(entity.get("city"), article.get("city_label"), article.get("city"))
    aliases = entity.get("aliases") if isinstance(entity.get("aliases"), list) else []
    source_account = first_text(article.get("source_account"))
    return {
        "schema_version": SCHEMA_VERSION,
        "card_type": "entity",
        "eid": first_text(entity.get("entity_id"), entity.get("eid"), f"entity_{article_uid}_{idx}"),
        "name": name,
        "type": entity_type,
        "bio": clip(bio, 100),
        "aliases": [first_text(item) for item in aliases if first_text(item)],
        "confidence": float_value(entity.get("confidence")),
        "source_article_uid": article_uid,
        "source_kind": first_text(entity.get("source_kind"), "article_text"),
        "evidence_quote": first_evidence_quote(entity),
        "city": city,
        "vector_text": clip(f"实体:{name} | 类型:{entity_type} | 城市:{city} | 简介:{bio} | 账号:{source_account}"),
    }


def event_card(article: dict[str, Any], event: dict[str, Any], idx: int) -> dict[str, Any]:
    article_uid = first_text(article.get("article_uid"))
    name = first_text(event.get("name"), event.get("title"))
    time_text = first_text(event.get("time"), event.get("time_text"))
    place = first_text(event.get("place"), event.get("venue"))
    participants = event.get("participants") if isinstance(event.get("participants"), list) else []
    organizers = event.get("organizers") if isinstance(event.get("organizers"), list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "card_type": "event",
        "evid": first_text(event.get("event_id"), event.get("evid"), f"event_{article_uid}_{idx}"),
        "name": name,
        "time_text": time_text,
        "time_iso": first_text(event.get("time_iso"), event.get("date_iso")),
        "place": place,
        "city": first_text(event.get("city"), article.get("city_label"), article.get("city")),
        "participants": [first_text(item) for item in participants if first_text(item)],
        "organizers": [first_text(item) for item in organizers if first_text(item)],
        "confidence": float_value(event.get("confidence")),
        "source_article_uid": article_uid,
        "source_kind": first_text(event.get("source_kind"), "article_text"),
        "vector_text": clip(f"活动:{name} | 时间:{time_text} | 地点:{place} | 阵容:{'、'.join(map(str, participants))}"),
    }


def release_rows_for_article(article: dict[str, Any]) -> dict[str, Any]:
    rows = {"article": article_card(article), "entities": [], "events": []}
    low_confidence_skipped = 0
    for idx, entity in enumerate(article.get("entities") if isinstance(article.get("entities"), list) else [], start=1):
        card = entity_card(article, entity, idx)
        if card["confidence"] < MIN_CONFIDENCE:
            low_confidence_skipped += 1
            continue
        rows["entities"].append(card)
    for idx, event in enumerate(article.get("events") if isinstance(article.get("events"), list) else [], start=1):
        card = event_card(article, event, idx)
        if card["confidence"] < MIN_CONFIDENCE:
            low_confidence_skipped += 1
            continue
        rows["events"].append(card)
    rows["manifest"] = {"low_confidence_skipped": low_confidence_skipped}
    return rows


def write_jsonl(handle: TextIO, row: dict[str, Any]) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_manifest_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Consumer Release Pack Draft",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source: `{summary['source_stable_articles']}`",
        f"- limit: `{summary['limit']}`",
        f"- release_ready: `{summary['release_ready']}`",
        f"- decision: `{summary['decision']}`",
        "",
        "## Counts",
        "",
        f"- articles: `{summary['articles']}`",
        f"- entities: `{summary['entities']}`",
        f"- events: `{summary['events']}`",
        f"- low_confidence_skipped: `{summary['low_confidence_skipped']}`",
        f"- missing_publish_time_articles: `{summary['missing_publish_time_articles']}`",
        f"- allow_unknown_publish_time: `{summary.get('allow_unknown_publish_time', False)}`",
        "",
        "## Release Blockers",
        "",
    ]
    if summary["release_blockers"]:
        for item in summary["release_blockers"]:
            lines.append(f"- `{item}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Local staging artifact only.",
            "- No publish, no production SQLite, no Qdrant/Neo4j writes, no paid API, no D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_release_pack(
    stable_articles: Path,
    out_dir: Path,
    limit: int = 1000,
    date_index_path: Path | None = None,
    allow_unknown_publish_time: bool = False,
) -> dict[str, Any]:
    reject_d_path(stable_articles, "stable_articles")
    if date_index_path is not None:
        reject_d_path(date_index_path, "date_index")
    date_index = load_date_index(date_index_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_paths = {
        "articles": out_dir / "articles.jsonl.tmp",
        "entities": out_dir / "entities.jsonl.tmp",
        "events": out_dir / "events.jsonl.tmp",
    }
    final_paths = {
        "articles": out_dir / "articles.jsonl",
        "entities": out_dir / "entities.jsonl",
        "events": out_dir / "events.jsonl",
    }
    counts = {
        "articles": 0,
        "entities": 0,
        "events": 0,
        "low_confidence_skipped": 0,
        "missing_publish_time_articles": 0,
    }
    with stable_articles.open("r", encoding="utf-8") as source, tmp_paths["articles"].open(
        "w", encoding="utf-8"
    ) as article_out, tmp_paths["entities"].open("w", encoding="utf-8") as entity_out, tmp_paths["events"].open(
        "w", encoding="utf-8"
    ) as event_out:
        for line in source:
            if limit and counts["articles"] >= limit:
                break
            stripped = line.strip()
            if not stripped:
                continue
            article = apply_date_index(json.loads(stripped), date_index)
            rows = release_rows_for_article(article)
            write_jsonl(article_out, rows["article"])
            counts["articles"] += 1
            if not rows["article"].get("publish_time"):
                counts["missing_publish_time_articles"] += 1
            for entity in rows["entities"]:
                write_jsonl(entity_out, entity)
                counts["entities"] += 1
            for event in rows["events"]:
                write_jsonl(event_out, event)
                counts["events"] += 1
            counts["low_confidence_skipped"] += int_value(rows["manifest"].get("low_confidence_skipped"))
    for key, tmp_path in tmp_paths.items():
        tmp_path.replace(final_paths[key])
    release_blockers = []
    if counts["missing_publish_time_articles"] and not allow_unknown_publish_time:
        release_blockers.append("article.publish_time")
    decision = "ready_for_release_pack_smoke"
    if release_blockers:
        decision = "publish_time_mapping_required"
    elif counts["missing_publish_time_articles"]:
        decision = "staging_ready_with_unknown_publish_time"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source_stable_articles": str(stable_articles),
        "date_index_path": str(date_index_path) if date_index_path else "",
        "allow_unknown_publish_time": allow_unknown_publish_time,
        "out_dir": str(out_dir),
        "limit": limit,
        **counts,
        "release_ready": not release_blockers,
        "release_blockers": release_blockers,
        "decision": decision,
        "files": {key: str(path) for key, path in final_paths.items()},
        "writes": "local_release_pack_only",
    }
    manifest_tmp = out_dir / "manifest.json.tmp"
    manifest_tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    manifest_tmp.replace(out_dir / "manifest.json")
    write_manifest_md(out_dir / "manifest.md", summary)
    return summary


def run(args: argparse.Namespace) -> int:
    summary = build_release_pack(
        args.stable_articles,
        args.out_dir,
        args.limit,
        args.date_index,
        allow_unknown_publish_time=args.allow_unknown_publish_time,
    )
    print(
        json.dumps(
            {
                "articles": summary["articles"],
                "entities": summary["entities"],
                "events": summary["events"],
                "release_ready": summary["release_ready"],
                "decision": summary["decision"],
                "manifest": str(args.out_dir / "manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.strict_release and not summary["release_ready"]:
        return 2
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-articles", type=Path, default=DEFAULT_STABLE_ARTICLES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=1000, help="0 means all rows; default is a bounded canary")
    parser.add_argument("--date-index", type=Path, default=None)
    parser.add_argument(
        "--allow-unknown-publish-time",
        action="store_true",
        help="Allow staging release packs with publish_time_status=unknown and source_archived_at evidence.",
    )
    parser.add_argument("--strict-release", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
