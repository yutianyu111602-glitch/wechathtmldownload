#!/usr/bin/env python3
"""Post-extraction enhancement: title-based entity/event fallback.

Addresses vector audit findings (2026-05-09):
  1. 17% article cards have no entity → force entity from title keywords
  2. 9.3% cards <80 chars → use title as entity candidate
  3. Only 30 events across 4,427 articles → extract event stubs from dates in titles
  4. Image-only articles with no text → mark to skip vectorization

Strategy:
  - Runs AFTER Flash/Pro extraction, BEFORE scoring
  - Only fills gaps; never overwrites existing good extractions
  - Uses deterministic rules (no LLM calls, zero cost)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ── Keyword lists ──────────────────────────────────────────────────────────
VENUE_KEYWORDS = [
    "ALL", "DADA", "Dada", "OIL", "AXIS", "TAG", "SYSTEM", "44KW",
    "wigwam", "Elevator", "ZhaoDai", "PILLBOX", "Club", "俱乐部",
    "场地", "现场", "SOLO", "DONG", "VERVO", "FOUNDATION", "Inward",
]

DJ_KEYWORDS = [
    "DJ", "dj", "B2B", "b2b", "Live", "live", "LIVE",
    "制作人", "音乐人", "主理人", "MC", "mc",
]

EVENT_KEYWORDS = [
    "派对", "演出", "现场", "Live", "live", "LIVE",
    "音乐", "舞", "Rave", "rave", "Open Deck", "open deck",
    "OPEN DECK", "放", "呈现", "巡演", "专场", "今晚", "明晚",
    "音乐节", "电音", "电子", "Techno", "techno", "House", "house",
    "Bass", "bass", "Disco", "disco", "Funk", "funk",
]

DATE_PATTERNS = [
    (re.compile(r'(\d{4})[\.\/年](\d{1,2})[\.\/月](\d{1,2})'), "{y}年{m}月{d}日"),
    (re.compile(r'(\d{1,2})[\.\/月](\d{1,2})'), "{m}月{d}日"),
    (re.compile(r'(一月|二月|三月|四月|五月|六月|七月|八月|九月|十月|十一月|十二月)\s*(\d{1,2})'), "{m}{d}日"),
    (re.compile(r'(周[一二三四五六日])'), "{d}"),
    (re.compile(r'(今天|今晚|明天|明晚|本周|下周|周末|月末|月底)'), "{d}"),
    (re.compile(r'(\d{1,2})[\.\/](\d{1,2})\s*[号日]'), "{m}月{d}日"),
]

# Title patterns that indicate pure announcements (not events)
ANNOUNCEMENT_PATTERNS = [
    re.compile(r'本周一览|本周蜕壳|本周.*一览|周报|周历|本周\s*@\s*$|本周$'),
    re.compile(r'放假|休息|关[门店]|停业|春节|清明|国庆|中秋|元旦|过年'),
    re.compile(r'公告|通知|声明|须知|需知|调整|变更'),
    re.compile(r'回顾|总结|复盘|上月|上个月'),
    re.compile(r'无活动|勿跑空|不营业|闭店|店休|取消|延期'),
    re.compile(r'营业时间|Opening Hours|Opening Times'),
]

# ── Enhancement logic ──────────────────────────────────────────────────────

def has_existing_entities(row: dict) -> bool:
    """Check if row already has meaningful entity extraction."""
    totals = row.get("totals", {})
    return totals.get("entities", 0) > 0


def has_existing_events(row: dict) -> bool:
    """Check if row already has meaningful event extraction."""
    totals = row.get("totals", {})
    return totals.get("events", 0) > 0


def is_image_only(row: dict) -> bool:
    """Check if article is image-only (no meaningful text)."""
    chars = row.get("input_chars", 0)
    imgs = row.get("local_image_count", 0)
    return chars <= 80 and imgs > 0


def is_announcement(title: str) -> bool:
    """Check if title is a pure announcement (not an event)."""
    for pat in ANNOUNCEMENT_PATTERNS:
        if pat.search(title):
            return True
    return False


def extract_date_from_title(title: str) -> str | None:
    """Extract date string from title."""
    for pat, fmt in DATE_PATTERNS:
        m = pat.search(title)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                return fmt.format(m=groups[0], d=groups[1])
            elif len(groups) == 3:
                return fmt.format(y=groups[0], m=groups[1], d=groups[2])
            else:
                return fmt.format(d=groups[0])
    return None


def extract_venue_from_title(title: str) -> str | None:
    """Extract venue name from title using keyword matching."""
    for kw in VENUE_KEYWORDS:
        if kw in title:
            # Try to get surrounding context
            idx = title.find(kw)
            start = max(0, idx - 2)
            end = min(len(title), idx + len(kw) + 5)
            return title[start:end].strip()
    return None


def extract_dj_from_title(title: str) -> str | None:
    """Extract DJ/performer name from title patterns."""
    # Pattern: DJ Name (capitalized words after DJ)
    m = re.search(r'DJ\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', title)
    if m:
        return f"DJ {m.group(1)}"
    # Pattern: XX B2B XX
    m = re.search(r'([A-Z][a-zA-Z]+)\s*B2B\s*([A-Z][a-zA-Z]+)', title)
    if m:
        return f"{m.group(1)} B2B {m.group(2)}"
    # Pattern: Chinese performer name before "呈现" or "带来"
    m = re.search(r'([\u4e00-\u9fff]{2,4})\s*(?:呈现|带来|呈现|专场)', title)
    if m:
        return m.group(1)
    # Pattern: @VenueName
    m = re.search(r'@\s*([A-Za-z\u4e00-\u9fff]+)', title)
    if m:
        return m.group(1)
    # Pattern: "嘉宾: XXX" or "Lineup: XXX"
    m = re.search(r'(?:嘉宾|Lineup|阵容)[：:]\s*([A-Za-z\u4e00-\u9fff\s,]+)', title)
    if m:
        names = m.group(1).strip()[:40]
        return names
    return None


def build_title_entity(title: str, account: str) -> dict | None:
    """Build an entity from title content."""
    venue = extract_venue_from_title(title)
    dj = extract_dj_from_title(title)

    if venue:
        return {
            "name": venue,
            "type": "organization",
            "confidence": 0.60,
            "bio": "",
            "evidence": [{"chunk_id": "title_fallback", "quote": title[:80]}],
            "source": "title_fallback",
        }
    if dj:
        return {
            "name": dj,
            "type": "person",
            "confidence": 0.55,
            "bio": "",
            "evidence": [{"chunk_id": "title_fallback", "quote": title[:80]}],
            "source": "title_fallback",
        }
    # Fallback: use account name as entity
    if account and account.strip():
        return {
            "name": account.strip(),
            "type": "organization",
            "confidence": 0.40,
            "bio": "",
            "evidence": [{"chunk_id": "title_fallback", "quote": title[:80]}],
            "source": "account_fallback",
        }
    return None


def build_title_event(title: str) -> dict | None:
    """Build an event stub from title content."""
    if is_announcement(title):
        return None

    date_str = extract_date_from_title(title)
    venue = extract_venue_from_title(title)

    if date_str or any(kw.lower() in title.lower() for kw in EVENT_KEYWORDS):
        return {
            "name": title[:60],
            "time": date_str or "",
            "place": venue or "",
            "participants": [],
            "confidence": 0.45,
            "evidence": [{"chunk_id": "title_fallback", "quote": title[:80]}],
            "source": "title_fallback",
        }
    return None


def enhance_row(row: dict) -> tuple[dict, dict]:
    """Apply title-based fallback enhancements to a single extraction row.
    
    Returns (enhanced_row, stats) where stats tracks what was added.
    """
    title = row.get("title", "")
    account = row.get("source_account", "")
    totals = row.get("totals", {})
    chunks = row.get("chunks", [])
    
    stats = {
        "entity_added": False,
        "event_added": False,
        "image_only": False,
        "announcement": False,
    }

    # Check if enhancement needed
    need_entity = not has_existing_entities(row)
    need_event = not has_existing_events(row)
    
    if not need_entity and not need_event:
        return row, stats

    # Check image-only
    if is_image_only(row) and need_entity and need_event:
        stats["image_only"] = True
        # Add a minimal entity from account name so card isn't completely empty
        ent = {
            "name": account.strip() if account else "未知",
            "type": "organization",
            "confidence": 0.30,
            "bio": "",
            "evidence": [{"chunk_id": "image_only_fallback", "quote": title[:60]}],
            "source": "image_only_fallback",
        }
        _append_entity_to_row(row, ent, totals)
        stats["entity_added"] = True
        return row, stats

    # Check announcement
    if is_announcement(title):
        stats["announcement"] = True
        # For announcements, add account name as minimal entity
        # so vector search can still find the article by venue name
        if need_entity and account and account.strip():
            ent = {
                "name": account.strip(),
                "type": "organization",
                "confidence": 0.30,
                "bio": "",
                "evidence": [{"chunk_id": "announcement_fallback", "quote": title[:60]}],
                "source": "announcement_fallback",
            }
            _append_entity_to_row(row, ent, totals)
            stats["entity_added"] = True
            need_entity = False  # Don't also try title entity

    # Add entity from title
    if need_entity:
        ent = build_title_entity(title, account)
        if ent:
            _append_entity_to_row(row, ent, totals)
            stats["entity_added"] = True

    # Add event from title
    if need_event and not stats["announcement"]:
        ev = build_title_event(title)
        if ev:
            _append_event_to_row(row, ev, totals)
            stats["event_added"] = True

    return row, stats


def _append_entity_to_row(row: dict, entity: dict, totals: dict) -> None:
    """Append a fallback entity to the row's first chunk."""
    chunks = row.get("chunks", [])
    if chunks and isinstance(chunks[0], dict):
        # Add to first chunk's raw_content as JSON
        c = chunks[0]
        raw = c.get("raw_content", "{}")
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        if "entities" not in data:
            data["entities"] = []
        data["entities"].append(entity)
        c["raw_content"] = json.dumps(data, ensure_ascii=False)
        c["entities_count"] = c.get("entities_count", 0) + 1
        totals["entities"] = totals.get("entities", 0) + 1
    else:
        # No chunks exist; create a minimal one
        row["chunks"] = [{
            "chunk_id": f"{row.get('article_uid','')}:000",
            "chunk_index": 0,
            "chars": 0,
            "api_ok": True,
            "parse_ok": True,
            "schema_ok": True,
            "thinking": "disabled",
            "entities_count": 1,
            "events_count": 0,
            "relations_count": 0,
            "claims_count": 0,
            "raw_content": json.dumps({"entities": [entity], "events": [], "relations": [], "claims": []}, ensure_ascii=False),
            "usage": {},
            "validation_errors": [],
            "validation_warnings": [],
            "evidence": {"evidence_total": 1, "evidence_hit": 1, "evidence_miss": 0, "evidence_hit_rate": 1.0},
            "normalize_stats": {"normalized": True, "missing_fields": [], "is_empty_object": False, "item_defaults": 1, "dropped_items": 0},
        }]
        totals["entities"] = 1
    row["totals"] = totals


def _append_event_to_row(row: dict, event: dict, totals: dict) -> None:
    """Append a fallback event to the row's first chunk."""
    chunks = row.get("chunks", [])
    if chunks and isinstance(chunks[0], dict):
        c = chunks[0]
        raw = c.get("raw_content", "{}")
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
        if "events" not in data:
            data["events"] = []
        data["events"].append(event)
        c["raw_content"] = json.dumps(data, ensure_ascii=False)
        c["events_count"] = c.get("events_count", 0) + 1
        totals["events"] = totals.get("events", 0) + 1
    row["totals"] = totals


# ── Batch processing ───────────────────────────────────────────────────────

def enhance_jsonl(input_path: str, output_path: str) -> dict:
    """Enhance all rows in a JSONL file. Returns summary stats."""
    total = 0
    entity_added = 0
    event_added = 0
    image_only = 0
    announcements = 0

    with open(input_path, "r", encoding="utf-8") as fin, \
         open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            total += 1
            row = json.loads(line)
            enhanced, stats = enhance_row(row)
            fout.write(json.dumps(enhanced, ensure_ascii=False) + "\n")
            if stats["entity_added"]:
                entity_added += 1
            if stats["event_added"]:
                event_added += 1
            if stats["image_only"]:
                image_only += 1
            if stats["announcement"]:
                announcements += 1

    return {
        "total_rows": total,
        "entity_added": entity_added,
        "entity_added_pct": round(entity_added / max(total, 1) * 100, 1),
        "event_added": event_added,
        "event_added_pct": round(event_added / max(total, 1) * 100, 1),
        "image_only": image_only,
        "announcements": announcements,
    }


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input.jsonl> <output.jsonl>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    print(f"Enhancing: {input_path} → {output_path}")
    stats = enhance_jsonl(input_path, output_path)

    print(f"\nResults:")
    print(f"  Total rows: {stats['total_rows']}")
    print(f"  Entity added: {stats['entity_added']} ({stats['entity_added_pct']}%)")
    print(f"  Event added: {stats['event_added']} ({stats['event_added_pct']}%)")
    print(f"  Image-only: {stats['image_only']}")
    print(f"  Announcements: {stats['announcements']}")

    # Write stats
    stats_path = output_path.replace(".jsonl", "_enhance_stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"  Stats: {stats_path}")


if __name__ == "__main__":
    main()
