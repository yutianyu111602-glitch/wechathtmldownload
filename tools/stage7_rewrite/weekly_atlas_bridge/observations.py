"""Export weekly_entity_observations.jsonl for atlas ingest (observation only)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .snapshot import lineup_from_item, load_current_items

CDN_URL_RE = re.compile(r"https?://|www\.|mmbiz\.qpic\.cn|qpic\.cn|wx_fmt=|from=appmsg|#imgIndex=", re.I)


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


def sanitize_observation_text(text: str) -> str:
    cleaned = sanitize_openid(text)
    if CDN_URL_RE.search(cleaned):
        return CDN_URL_RE.sub("[url_sanitized]", cleaned)
    return cleaned


def _sanitize_dict_or_list(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _sanitize_dict_or_list(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [_sanitize_dict_or_list(x) for x in val]
    elif isinstance(val, str):
        return sanitize_observation_text(val)
    return val


def observation_id(event_id: str, publish_package: str) -> str:
    digest = _sha256(f"{publish_package}|{event_id}")[:16]
    return f"obs_{publish_package}_{digest}"


def source_url_hash_for_item(
    item: dict[str, Any],
    source_url_map: dict[str, Any] | None = None,
) -> str | None:
    source_url = str(item.get("source_url") or item.get("url") or "")
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    source_hash = str(
        source_action.get("url_hash")
        or source_article.get("url_hash")
        or item.get("source_url_hash")
        or ""
    ).strip()

    if not source_url and source_hash and source_url_map:
        sources = source_url_map.get("sources") if isinstance(source_url_map.get("sources"), dict) else {}
        mapped = sources.get(source_hash)
        if isinstance(mapped, dict):
            source_url = str(mapped.get("url") or "")
        elif isinstance(mapped, str):
            source_url = mapped

    if source_url:
        cleaned_source_url = sanitize_openid(source_url)
        return f"sha256:{_sha256(cleaned_source_url)}" if cleaned_source_url else None

    if source_hash:
        return f"urlhash:{sanitize_observation_text(source_hash)}"

    return None


def build_observation_row(
    item: dict[str, Any],
    *,
    publish_package: str,
    window: dict[str, str] | None = None,
    lineup_resolved: list[dict[str, Any]] | None = None,
    source_url_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_id = str(item.get("event_id") or item.get("id") or "")
    
    lineup_raw = lineup_from_item(item)
    evidence: list[dict[str, Any]] = []
    poster = item.get("poster_file_id") or item.get("cover_image_url")
    if poster:
        poster_ref = sanitize_openid(str(poster))
        if CDN_URL_RE.search(poster_ref):
            evidence.append({"type": "poster", "ref_hash": f"sha256:{_sha256(poster_ref)}"})
        else:
            evidence.append({"type": "poster", "ref": poster_ref})
    for line in item.get("description_original_lines") or []:
        text = str(line).strip()
        if text:
            evidence.append({"type": "description_line", "quote": sanitize_observation_text(text[:240])})

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
        "source_url_hash": source_url_hash_for_item(item, source_url_map),
        "publish_package": publish_package,
        "city_key": item.get("city_key") or item.get("city"),
        "title": item.get("title"),
    }
    
    # 递归清洗字典中所有值中可能残留的 openid / CDN URL
    return _sanitize_dict_or_list(row)


def export_observations(
    items: list[dict[str, Any]],
    *,
    publish_package: str,
    window: dict[str, str] | None = None,
    lineup_resolved: list[dict[str, Any]] | None = None,
    source_url_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return [
        build_observation_row(
            item,
            publish_package=publish_package,
            window=window,
            lineup_resolved=lineup_resolved,
            source_url_map=source_url_map,
        )
        for item in items
        if item.get("event_id") or item.get("id")
    ]


def write_observations_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
