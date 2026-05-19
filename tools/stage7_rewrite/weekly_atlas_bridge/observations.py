"""Export weekly_entity_observations.jsonl for atlas ingest (observation only)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .snapshot import lineup_from_item, load_current_items


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitize_openid(text: str) -> str:
    if not text:
        return text
    # 1. 移除 ?openid=xxxx 或 &openid=xxxx 或 openid=xxxx (不区分大小写)
    cleaned = re.sub(r'(?i)([?&])openid=[^&]*(&|$)', r'\1', text)
    cleaned = re.sub(r'(?i)\bopenid=[^&]*', '', cleaned)
    # 2. 如果还有可能独立出现的 "openid" 字样，替换为 "id_sanitized"
    cleaned = re.sub(r'(?i)openid', 'id_sanitized', cleaned)
    # 3. 清理末尾和连接多余的 ? 和 &
    cleaned = cleaned.rstrip('?&').replace('?&', '?')
    return cleaned


def _sanitize_dict_or_list(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _sanitize_dict_or_list(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_sanitize_dict_or_list(x) for x in val]
    elif isinstance(val, str):
        return sanitize_openid(val)
    return val


def observation_id(event_id: str, publish_package: str) -> str:
    digest = _sha256(f"{publish_package}|{event_id}")[:16]
    return f"obs_{publish_package}_{digest}"


def build_observation_row(
    item: dict[str, Any],
    *,
    publish_package: str,
    window: dict[str, str] | None = None,
    lineup_resolved: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    event_id = str(item.get("event_id") or item.get("id") or "")
    source_url = str(item.get("source_url") or item.get("url") or "")
    
    # 严格洗涤并加密 source_url，并且不在 row 中存储明文 source_url
    cleaned_source_url = sanitize_openid(source_url)
    
    lineup_raw = lineup_from_item(item)
    evidence: list[dict[str, Any]] = []
    poster = item.get("poster_file_id") or item.get("cover_image_url")
    if poster:
        evidence.append({"type": "poster", "ref": str(poster)})
    for line in item.get("description_original_lines") or []:
        text = str(line).strip()
        if text:
            evidence.append({"type": "description_line", "quote": text[:240]})

    resolved_for_event = [
        row for row in (lineup_resolved or []) if row.get("event_id") == event_id
    ]
    vector_reviews = [
        row.get("vector_review")
        for row in resolved_for_event
        if row.get("match_method") == "vector_candidate" and row.get("vector_review")
    ]

    row = {
        "observation_id": observation_id(event_id, publish_package),
        "event_id": event_id,
        "observed_at": _utc_now(),
        "window": window or {},
        "lineup_raw": lineup_raw,
        "lineup_evidence": evidence,
        "lineup_resolved_summary": [
            {
                "raw": row.get("raw"),
                "artist_id": row.get("artist_id"),
                "match_method": row.get("match_method"),
                "match_score": row.get("match_score"),
            }
            for row in resolved_for_event
        ],
        "vector_review_candidates": vector_reviews,
        "venue_raw": str(item.get("venue") or item.get("venue_name") or ""),
        "source_url_hash": f"sha256:{_sha256(cleaned_source_url)}" if cleaned_source_url else None,
        "publish_package": publish_package,
        "city_key": item.get("city_key") or item.get("city"),
        "title": item.get("title"),
    }
    
    # 递归清洗字典中所有值中可能残留的 openid
    return _sanitize_dict_or_list(row)


def export_observations(
    items: list[dict[str, Any]],
    *,
    publish_package: str,
    window: dict[str, str] | None = None,
    lineup_resolved: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        build_observation_row(
            item,
            publish_package=publish_package,
            window=window,
            lineup_resolved=lineup_resolved,
        )
        for item in items
        if item.get("event_id") or item.get("id")
    ]


def write_observations_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
