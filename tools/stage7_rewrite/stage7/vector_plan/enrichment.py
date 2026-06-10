"""Deterministic enrichment helpers for vector cards."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any


LANE_PREFIX_RE = re.compile(
    r"^(latest_free|latest_dajiala_canary|full_empty_wave_\d+_recovered|"
    r"full_empty_wave_\d+_review|free_signed_reexported_recovered|"
    r"free_signed_reexported|latest_review)__"
)

CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "北京": ("北京", "Beijing", "DADA北京", "Dada Bar Beijing", "ZhaoDai", "招待"),
    "上海": ("上海", "Shanghai", "EXIT Shanghai", "ALL Club", "All俱乐部"),
    "昆明": ("昆明", "Kunming", "Dada Kunming", "DADA昆明"),
    "厦门": ("厦门", "Xiamen", "TwinKlab", "蜕壳"),
    "广州": ("广州", "Guangzhou"),
    "深圳": ("深圳", "Shenzhen", "Oil Club", "OIL"),
    "成都": ("成都", "Chengdu"),
    "杭州": ("杭州", "Hangzhou"),
    "南京": ("南京", "Nanjing"),
    "济南": ("济南", "Jinan", "KEY JINAN", "Key Jinan"),
}

VENUE_CUES = (
    "club",
    "bar",
    "livehouse",
    "space",
    "厂牌",
    "俱乐部",
    "酒吧",
    "场地",
    "音乐空间",
)


def clean_account(account: str) -> str:
    return LANE_PREFIX_RE.sub("", account or "").strip()


def evidence_quotes(obj: dict[str, Any], limit: int = 4) -> list[str]:
    quotes: list[str] = []
    for ev in obj.get("evidence", []) or []:
        quote = str(ev.get("quote", "")).strip()
        if quote and quote not in quotes:
            quotes.append(quote)
        if len(quotes) >= limit:
            break
    return quotes


def evidence_text(obj: dict[str, Any], limit: int = 4) -> str:
    return "；".join(evidence_quotes(obj, limit=limit))


def joined_article_text(article: dict[str, Any], obj: dict[str, Any] | None = None) -> str:
    parts = [
        article.get("source_account", ""),
        clean_account(article.get("source_account", "")),
        article.get("title", ""),
        article.get("summary", ""),
        " ".join(article.get("topics", []) or []),
    ]
    if obj:
        parts.extend(
            [
                obj.get("name", ""),
                obj.get("place", ""),
                obj.get("time", ""),
                obj.get("description", ""),
                " ".join(obj.get("aliases", []) or []),
                " ".join(obj.get("participants", []) or []),
                evidence_text(obj),
            ]
        )
    return " ".join(str(p) for p in parts if p)


def infer_city(article: dict[str, Any], obj: dict[str, Any] | None = None) -> str:
    text = joined_article_text(article, obj)
    for city, aliases in CITY_ALIASES.items():
        for alias in aliases:
            if alias and alias.lower() in text.lower():
                return city
    return ""


def infer_venue(article: dict[str, Any], obj: dict[str, Any] | None = None) -> str:
    candidates: list[str] = []
    if obj:
        for key in ("place", "venue", "name"):
            value = str(obj.get(key, "")).strip()
            if value:
                candidates.append(value)
    account_clean = clean_account(article.get("source_account", ""))
    if account_clean:
        candidates.append(account_clean)
    title = str(article.get("title", ""))
    at_match = re.search(r"[@＠]\s*([A-Za-z0-9\u4e00-\u9fff ._-]{2,32})", title)
    if at_match:
        candidates.insert(0, at_match.group(1).strip())
    for value in candidates:
        lower = value.lower()
        if any(cue in lower for cue in VENUE_CUES) or any(cue in value for cue in VENUE_CUES):
            return value
    return candidates[0] if candidates else ""


def normalize_event_date(article: dict[str, Any], obj: dict[str, Any] | None = None) -> str:
    text = joined_article_text(article, obj)
    year = datetime.now().year
    match = re.search(r"(?<!\d)(\d{1,2})[./月-](\d{1,2})(?:日)?", text)
    if not match:
        return ""
    month = int(match.group(1))
    day = int(match.group(2))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def canonical_key(name: str, city: str = "", etype: str = "") -> str:
    normalized = re.sub(r"[\s_\-·・.]+", "", (name or "").lower())
    suffix = ":".join(p for p in (city, etype) if p)
    return f"{normalized}:{suffix}" if suffix else normalized


def completeness_score(payload: dict[str, Any]) -> float:
    fields = ["city", "venue", "source_account", "account_clean", "title", "evidence_ref", "event_date_norm"]
    present = sum(1 for field in fields if payload.get(field))
    return round(0.8 + min(0.4, present / max(len(fields), 1) * 0.4), 3)


def card_payload(
    article: dict[str, Any],
    obj: dict[str, Any] | None,
    object_kind: str,
    card_kind: str,
    route_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route_metadata = route_metadata or {}
    account = article.get("source_account", "")
    city = infer_city(article, obj)
    venue = infer_venue(article, obj)
    payload = {
        **route_metadata,
        "object_kind": object_kind,
        "card_kind": card_kind,
        "article_uid": article.get("article_uid", ""),
        "source_account": account,
        "account": account,
        "account_clean": clean_account(account),
        "title": article.get("title", ""),
        "article_title": article.get("title", ""),
        "publish_time": article.get("publish_time", ""),
        "city": city,
        "venue": venue,
        "entity_type": obj.get("type", "") if obj else "",
        "event_type": obj.get("type", "") if obj else "",
        "event_time_text": obj.get("time", "") if obj else "",
        "event_date_norm": normalize_event_date(article, obj),
        "confidence": obj.get("confidence") if obj else None,
        "evidence_source": "text",
        "evidence_ref": evidence_text(obj or {}),
        "source_lane": LANE_PREFIX_RE.match(account).group(1) if LANE_PREFIX_RE.match(account) else "",
    }
    name = obj.get("name", "") if obj else article.get("title", "")
    payload["canonical_id"] = canonical_key(name, city, payload.get("entity_type", ""))
    payload["field_completeness_weight"] = completeness_score(payload)
    return payload
