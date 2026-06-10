"""Shared helpers for weekly golden set bootstrap and baseline evaluation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "weekly_golden_set.v1"

DISPLAY_URL_RE = re.compile(
    r"https?://|www\.|mmbiz\.qpic\.cn|qpic\.cn|wx_fmt=|from=appmsg|#imgIndex=",
    re.IGNORECASE,
)

SAMPLE_CATEGORIES = (
    "complete_control",
    "missing_lineup",
    "lineup_noise",
    "image_heavy",
    "aggregate_child",
    "title_date_mismatch",
    "url_backend",
    "lineup_present",
)


def squash(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_name(value: Any) -> str:
    text = squash(value).lower()
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[|｜:：·•,，。!！?？'\"“”‘’\[\]【】()（）/\\_-]+", "", text)
    return text


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_current_items(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("items", "events", "data"):
            values = payload.get(key)
            if isinstance(values, list):
                return [row for row in values if isinstance(row, dict)]
    return []


def lineup_values(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("lineup", "lineup_artists"):
        raw = item.get(key)
        if isinstance(raw, list):
            values.extend(squash(v) for v in raw if squash(v))
        elif squash(raw):
            values.append(squash(raw))
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = normalize_name(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def backend_url_lines(item: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    for key in ("description_original_lines", "dj_bio_lines", "summary", "description"):
        raw = item.get(key)
        if isinstance(raw, list):
            for line in raw:
                text = squash(line)
                if text and DISPLAY_URL_RE.search(text):
                    hits.append(text)
        else:
            text = squash(raw)
            if text and DISPLAY_URL_RE.search(text):
                hits.append(text)
    return hits


def empty_gold() -> dict[str, Any]:
    return {
        "display_tier": None,
        "event_date_start": None,
        "event_date_end": None,
        "event_time_text": None,
        "lineup": None,
        "address": None,
        "venue": None,
        "artist_id": None,
        "hard_error": False,
        "notes": "",
    }


def pipeline_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    url_lines = backend_url_lines(item)
    return {
        "title": squash(item.get("title")),
        "city_key": squash(item.get("city_key") or item.get("city")),
        "venue": squash(item.get("venue") or item.get("venue_name")),
        "address": squash(item.get("address") or item.get("address_full")),
        "event_date_start": squash(item.get("event_date_start")),
        "event_date_end": squash(item.get("event_date_end")),
        "event_time_text": squash(item.get("event_time_text") or item.get("time_text")),
        "lineup": lineup_values(item),
        "lineup_display_hint": squash(item.get("lineup_display_hint")),
        "description_original_lines_count": len(item.get("description_original_lines") or []),
        "backend_url_line_count": len(url_lines),
        "publish_status": squash(item.get("publish_status")),
    }


def compare_lineup(shown: list[str], gold: list[str] | None) -> dict[str, Any]:
    shown_norm = {normalize_name(v) for v in shown if normalize_name(v)}
    gold_norm = {normalize_name(v) for v in (gold or []) if normalize_name(v)}
    if not gold_norm and not shown_norm:
        return {"precision": 1.0, "recall": 1.0, "intersection": 0, "shown": 0, "gold": 0}
    precision = len(shown_norm & gold_norm) / len(shown_norm) if shown_norm else (1.0 if not gold_norm else 0.0)
    recall = len(shown_norm & gold_norm) / len(gold_norm) if gold_norm else (1.0 if not shown_norm else 0.0)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "intersection": len(shown_norm & gold_norm),
        "shown": len(shown_norm),
        "gold": len(gold_norm),
    }
