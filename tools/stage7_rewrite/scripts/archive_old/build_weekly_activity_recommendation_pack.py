#!/usr/bin/env python3
"""Build a file-only weekly activity recommendation pack from Stage7 extracts.

The script is intentionally offline: it reads a bounded weekly queue and the
Stage7 output root, then writes JSONL/summary files. It does not fetch pages,
run LLM extraction, write vector stores, or scan D: roots.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
DEFAULT_WEEKLY_QUEUE = LONGRUN_ROOT / "WEEKLY_ACTIVITY_QUEUE_20260507" / "weekly_activity_queue.jsonl"
DEFAULT_STAGE7_OUTPUT = Path(r"D:\downstream_results\stage7_rewrite")
DEFAULT_OUT_DIR = LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_20260507"

ACTIVITY_ENTITY_TYPES = {"activity", "event"}
VENUE_ENTITY_TYPES = {"venue", "location"}
CITY_ENTITY_TYPES = {"city"}
LINEUP_ENTITY_TYPES = {"person", "organization", "brand"}
MIN_RECOMMENDATION_CONFIDENCE = 0.55
HIGH_CONFIDENCE_THRESHOLD = 0.70
PLACEHOLDER_VALUES = {"unknown", "未知", "不详", "na", "n/a", "none", "无", "待定", "tbd"}

ACTIVITY_TITLE_PATTERNS = [
    "演出",
    "派对",
    "音乐节",
    "专场",
    "巡演",
    "开票",
    "预售",
    "放票",
    "阵容",
    "活动",
    "市集",
    "展览",
    "周五",
    "周六",
    "周日",
    "party",
    "live",
    "show",
    "club",
    "festival",
    "lineup",
    "presale",
    "ticket",
    "tickets",
    "opening",
]

GENRE_PATTERNS = [
    "techno",
    "house",
    "bass",
    "drum and bass",
    "dnb",
    "trance",
    "ambient",
    "disco",
    "hiphop",
    "hip-hop",
    "jazz",
    "rock",
    "live",
    "experimental",
    "electro",
    "breakbeat",
    "dub",
]

PRICE_RE = re.compile(
    r"(?:"
    r"(?:预售|早鸟|双人|单人|现场|门票|票价|学生|presale|pre-sale|pre|advance|door|onsite|ticket|tickets?)"
    r"\s*[:：/]?\s*(?:¥|￥|RMB\s*|CNY\s*)?\s*\d+(?:\.\d+)?\s*(?:元|¥|￥|rmb|RMB|CNY|cny)?"
    r"|(?:RMB|rmb|CNY|cny|￥|¥)\s?\d+(?:\.\d+)?(?!\s*(?:am|pm)\b)"
    r"|(?<![:：\d])\d+(?:\.\d+)?\s?(?:元|¥|￥|rmb|RMB|CNY|cny)"
    r"|(?:[0-2]?\d\s*(?:am|pm)|[0-2]?\d[:：][0-5]\d|凌晨\s*[0-9]{1,2}\s*点(?:半)?)"
    r"\s*(?:后|之后|以后)\s*(?:免费入场|免票|free\s*entry)"
    r"|free\s?entry|免费入场|免票"
    r")",
    re.I,
)
DATE_TEXT_RE = re.compile(
    r"(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?|\d{1,2}\s?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*|周[一二三四五六日天]|星期[一二三四五六日天])",
    re.IGNORECASE,
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def queue_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    source_url = first_string(row.get("source_url"), row.get("url"), row.get("article_url"))
    token = first_string(row.get("token"))
    account = first_string(row.get("account_key"), row.get("source_account"), row.get("account_nickname"))
    title = first_string(row.get("title"))
    queue_id = first_string(row.get("queue_id"))
    if source_url:
        keys.add(f"url:{source_url}")
    if token:
        keys.add(f"token:{token}")
    if account and token:
        keys.add(f"account_token:{norm(account)}:{token}")
    if account and title:
        keys.add(f"account_title:{norm(account)}:{norm(title)}")
    if queue_id:
        keys.add(f"queue_id:{queue_id}")
    return keys


def extract_keys(data: dict[str, Any], path: Path) -> set[str]:
    keys: set[str] = set()
    source_url = first_string(
        data.get("source_url"),
        data.get("article_url"),
        data.get("url"),
        data.get("canonical_url"),
    )
    token = first_string(data.get("token"), data.get("article_id"))
    account = first_string(data.get("source_account"), data.get("account_key"), data.get("account"))
    title = first_string(data.get("title"))
    if source_url:
        keys.add(f"url:{source_url}")
        match = re.search(r"/s/([^?#]+)", source_url)
        if match:
            keys.add(f"token:{match.group(1)}")
    if token:
        keys.add(f"token:{token}")
    if account and token:
        keys.add(f"account_token:{norm(account)}:{token}")
    if account and title:
        keys.add(f"account_title:{norm(account)}:{norm(title)}")
    for part in path.parts[-3:]:
        if part and part != "extract.article.v1.json":
            keys.add(f"token:{part}")
    return keys


def iter_extract_files(stage7_output: Path, sample: int | None) -> list[Path]:
    extract_root = stage7_output / "llm_extract"
    if not extract_root.exists():
        return []
    files = sorted(extract_root.glob("*/*/extract.article.v1.json"))
    return files[:sample] if sample else files


def evidence_quotes(items: list[dict[str, Any]], limit: int = 12) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()
    for item in items:
        evidence = item.get("evidence")
        if not isinstance(evidence, list):
            continue
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            quote = first_string(ev.get("quote"), ev.get("text"))
            if not quote:
                continue
            key = norm(quote)
            if key in seen:
                continue
            seen.add(key)
            quotes.append(quote[:500])
            if len(quotes) >= limit:
                return quotes
    return quotes


def names_by_type(items: list[dict[str, Any]], types: set[str], limit: int = 20) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = first_string(item.get("type"), item.get("entity_type")).lower()
        if kind not in types:
            continue
        name = first_string(item.get("name"), item.get("label"))
        if not name:
            continue
        key = norm(name)
        if key in PLACEHOLDER_VALUES:
            continue
        if key in seen:
            continue
        seen.add(key)
        values.append(name)
        if len(values) >= limit:
            break
    return values


def find_patterns(texts: list[str], patterns: list[str]) -> list[str]:
    text = "\n".join(texts).lower()
    return [pattern for pattern in patterns if pattern.lower() in text]


def regex_values(texts: list[str], regex: re.Pattern[str], limit: int = 12) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in regex.findall(text or ""):
            value = match.strip()
            key = norm(value)
            if not key or key in seen:
                continue
            seen.add(key)
            values.append(value)
            if len(values) >= limit:
                return values
    return values


def event_rows(data: dict[str, Any], weekly: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in data.get("events", []) if isinstance(data.get("events"), list) else []:
        if not isinstance(event, dict):
            continue
        rows.append(
            {
                "article_id": first_string(data.get("article_id"), data.get("article_uid")),
                "queue_id": weekly.get("queue_id", ""),
                "account_key": weekly.get("account_key", data.get("source_account", "")),
                "title": weekly.get("title", data.get("title", "")),
                "event_id": event.get("event_id", ""),
                "name": event.get("name", ""),
                "time": first_string(event.get("time"), event.get("date")),
                "place": first_string(event.get("place"), event.get("venue")),
                "participants": event.get("participants", []),
                "description": event.get("description", ""),
                "evidence": evidence_quotes([event], limit=5),
            }
        )
    return rows


def entity_rows(data: dict[str, Any], weekly: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entity in data.get("entities", []) if isinstance(data.get("entities"), list) else []:
        if not isinstance(entity, dict):
            continue
        rows.append(
            {
                "article_id": first_string(data.get("article_id"), data.get("article_uid")),
                "queue_id": weekly.get("queue_id", ""),
                "account_key": weekly.get("account_key", data.get("source_account", "")),
                "title": weekly.get("title", data.get("title", "")),
                "entity_id": entity.get("entity_id", ""),
                "name": entity.get("name", ""),
                "type": first_string(entity.get("type"), entity.get("entity_type")),
                "description": entity.get("description", ""),
                "evidence": evidence_quotes([entity], limit=5),
            }
        )
    return rows


def build_candidate(data: dict[str, Any], weekly: dict[str, Any], extract_path: Path) -> dict[str, Any]:
    entities = data.get("entities", []) if isinstance(data.get("entities"), list) else []
    events = data.get("events", []) if isinstance(data.get("events"), list) else []
    claims = data.get("claims", []) if isinstance(data.get("claims"), list) else []
    relations = data.get("relations", []) if isinstance(data.get("relations"), list) else []
    all_items = [*entities, *events, *claims, *relations]

    title = first_string(weekly.get("title"), data.get("title"))
    event_names = [first_string(event.get("name")) for event in events if isinstance(event, dict)]
    event_names = [name for name in event_names if name]
    activity_names = names_by_type(entities, ACTIVITY_ENTITY_TYPES)
    venues = names_by_type(entities, VENUE_ENTITY_TYPES)
    cities = names_by_type(entities, CITY_ENTITY_TYPES)
    lineup = names_by_type(entities, LINEUP_ENTITY_TYPES)
    for event in events:
        if isinstance(event, dict):
            place = first_string(event.get("place"), event.get("venue"))
            if place and norm(place) not in PLACEHOLDER_VALUES and place not in venues:
                venues.append(place)
            participants = event.get("participants")
            if isinstance(participants, list):
                for participant in participants:
                    if isinstance(participant, str) and participant and participant not in lineup:
                        lineup.append(participant)

    quotes = evidence_quotes(all_items)
    searchable_texts = [title, data.get("summary", ""), *quotes, *event_names, *activity_names]
    genres = find_patterns(searchable_texts, GENRE_PATTERNS)
    price = regex_values(searchable_texts, PRICE_RE)
    date_text = []
    for event in events:
        if isinstance(event, dict):
            value = first_string(event.get("time"), event.get("date"))
            if value and value not in date_text:
                date_text.append(value)
    for value in regex_values(searchable_texts, DATE_TEXT_RE):
        if value not in date_text:
            date_text.append(value)

    score = 0.0
    reasons: list[str] = []
    if event_names or activity_names:
        score += 0.35
        reasons.append("stage7_event_or_activity_entity")
    if venues or cities:
        score += 0.15
        reasons.append("venue_or_city_detected")
    if date_text:
        score += 0.15
        reasons.append("date_text_detected")
    if price:
        score += 0.10
        reasons.append("price_text_detected")
    title_hits = find_patterns([title], ACTIVITY_TITLE_PATTERNS)
    if title_hits:
        score += 0.20
        reasons.append("activity_title_keyword")
    if quotes:
        score += 0.05
        reasons.append("evidence_present")
    score = min(score, 1.0)

    return {
        "schema_version": "weekly_activity_recommendation_candidate.v1",
        "article_id": first_string(data.get("article_id"), data.get("article_uid")),
        "queue_id": weekly.get("queue_id", ""),
        "account_key": weekly.get("account_key", data.get("source_account", "")),
        "title": title,
        "source_url": weekly.get("source_url", data.get("source_url", "")),
        "post_date": weekly.get("post_date", data.get("publish_time", "")),
        "activity_names": activity_names[:10],
        "event_names": event_names[:10],
        "city": cities[:5],
        "venue": venues[:8],
        "date_text": date_text[:8],
        "event_date_text": date_text[:8],
        "lineup": lineup[:20],
        "genres": genres[:10],
        "price": price[:8],
        "evidence": quotes,
        "confidence": round(score, 3),
        "recommendation_reason": reasons,
        "extract_path": str(extract_path),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Weekly Activity Recommendation Pack",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- weekly_queue_total: `{summary['weekly_queue_total']}`",
        f"- extract_files_scanned: `{summary['extract_files_scanned']}`",
        f"- matched_articles: `{summary['matched_articles']}`",
        f"- unmatched_weekly_rows: `{summary['unmatched_weekly_rows']}`",
        f"- candidates: `{summary['candidates']}`",
        f"- review_candidates: `{summary['review_candidates']}`",
        f"- min_recommendation_confidence: `{summary['min_recommendation_confidence']}`",
        f"- high_confidence_candidates: `{summary['high_confidence_candidates']}`",
        "",
        "## Output Files",
        "",
    ]
    for key, value in summary["paths"].items():
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build weekly activity recommendation pack from Stage7 extracts")
    parser.add_argument("--weekly-queue", default=str(DEFAULT_WEEKLY_QUEUE))
    parser.add_argument("--stage7-output", default=str(DEFAULT_STAGE7_OUTPUT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--sample", type=int, default=0)
    args = parser.parse_args()

    weekly_queue = Path(args.weekly_queue)
    stage7_output = Path(args.stage7_output)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    weekly_rows = read_jsonl(weekly_queue)
    weekly_index: dict[str, dict[str, Any]] = {}
    for row in weekly_rows:
        for key in queue_keys(row):
            weekly_index.setdefault(key, row)

    article_rows: list[dict[str, Any]] = []
    event_out: list[dict[str, Any]] = []
    entity_out: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    review_candidates: list[dict[str, Any]] = []
    matched_queue_ids: set[str] = set()
    source_counter: Counter[str] = Counter()

    sample = args.sample if args.sample > 0 else None
    extract_files = iter_extract_files(stage7_output, sample)
    for extract_path in extract_files:
        data = read_json(extract_path)
        if not data:
            continue
        matched = None
        for key in extract_keys(data, extract_path):
            if key in weekly_index:
                matched = weekly_index[key]
                break
        if not matched:
            continue
        queue_id = first_string(matched.get("queue_id"))
        if queue_id:
            matched_queue_ids.add(queue_id)
        source_counter[first_string(matched.get("account_key"), data.get("source_account"), "unknown")] += 1
        article_rows.append(
            {
                "article_id": first_string(data.get("article_id"), data.get("article_uid")),
                "queue_id": queue_id,
                "account_key": matched.get("account_key", data.get("source_account", "")),
                "title": matched.get("title", data.get("title", "")),
                "source_url": matched.get("source_url", data.get("source_url", "")),
                "post_date": matched.get("post_date", data.get("publish_time", "")),
                "extract_path": str(extract_path),
            }
        )
        event_out.extend(event_rows(data, matched))
        entity_out.extend(entity_rows(data, matched))
        candidate = build_candidate(data, matched, extract_path)
        if float(candidate.get("confidence") or 0) >= MIN_RECOMMENDATION_CONFIDENCE and candidate.get("evidence"):
            candidates.append(candidate)
        else:
            review_candidates.append(candidate)

    unmatched_rows = [row for row in weekly_rows if first_string(row.get("queue_id")) not in matched_queue_ids]
    candidates.sort(key=lambda row: (-float(row.get("confidence", 0)), row.get("post_date", ""), row.get("title", "")))
    review_candidates.sort(
        key=lambda row: (-float(row.get("confidence", 0)), row.get("post_date", ""), row.get("title", ""))
    )

    paths = {
        "articles": str(out_dir / "weekly_activity_articles.jsonl"),
        "events": str(out_dir / "weekly_activity_events.jsonl"),
        "entities": str(out_dir / "weekly_activity_entities.jsonl"),
        "candidates": str(out_dir / "weekly_activity_recommendation_candidates.jsonl"),
        "review_candidates": str(out_dir / "weekly_activity_recommendation_review_candidates.jsonl"),
        "unmatched": str(out_dir / "unmatched_weekly_queue.jsonl"),
        "summary_json": str(out_dir / "summary.json"),
        "summary_md": str(out_dir / "SUMMARY.md"),
    }
    write_jsonl(Path(paths["articles"]), article_rows)
    write_jsonl(Path(paths["events"]), event_out)
    write_jsonl(Path(paths["entities"]), entity_out)
    write_jsonl(Path(paths["candidates"]), candidates)
    write_jsonl(Path(paths["review_candidates"]), review_candidates)
    write_jsonl(Path(paths["unmatched"]), unmatched_rows)

    summary = {
        "schema_version": "weekly_activity_recommendation_pack.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "weekly_queue": str(weekly_queue),
        "stage7_output": str(stage7_output),
        "out_dir": str(out_dir),
        "weekly_queue_total": len(weekly_rows),
        "extract_files_scanned": len(extract_files),
        "matched_articles": len(article_rows),
        "unmatched_weekly_rows": len(unmatched_rows),
        "events": len(event_out),
        "entities": len(entity_out),
        "candidates": len(candidates),
        "review_candidates": len(review_candidates),
        "min_recommendation_confidence": MIN_RECOMMENDATION_CONFIDENCE,
        "high_confidence_threshold": HIGH_CONFIDENCE_THRESHOLD,
        "high_confidence_candidates": sum(
            1 for row in candidates if float(row.get("confidence", 0)) >= HIGH_CONFIDENCE_THRESHOLD
        ),
        "top_accounts": dict(source_counter.most_common(20)),
        "paths": paths,
    }
    Path(paths["summary_json"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_summary_md(Path(paths["summary_md"]), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
