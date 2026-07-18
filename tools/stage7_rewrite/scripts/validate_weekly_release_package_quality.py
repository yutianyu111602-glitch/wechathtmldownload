#!/usr/bin/env python
"""Validate release-package quality contracts that ReleaseGuard does not cover.

This gate is local and fail-closed. It reads a candidate API package and writes
one JSON report; it never deploys, uploads, or mutates the package.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from repair_weekly_release_conflicts import CITY_LABEL_BY_KEY, read_json, write_json


SCHEMA_VERSION = "weekly_release_package_quality.v1"
DEFAULT_SOURCE_POLICY = Path(__file__).resolve().parents[1] / "registries" / "weekly_sanji_source_policy.json"
INTERNAL_WEEKLY_POSTER_RE = re.compile(r"^cloud://[^/]+/weekly-posters/\d{8}/.+", re.I)
POSTER_FILE_ID_FIELDS = ("poster_file_id", "posterFileId", "cloudFileId", "cloud_file_id")
POSTER_STORAGE_FIELDS = ("poster_storage", "posterStorage")
POSTER_URL_FIELDS = (
    "poster",
    "poster_url",
    "posterUrl",
    "flyer_url",
    "cover_image_url",
    "cover_url",
    "raw_cover_url",
    "coverUrl",
    "cover_file_id",
    "coverFileId",
    "poster_file_id",
    "posterFileId",
    "cloudFileId",
    "cloud_file_id",
)
RUNTIME_ONLY_POSTER_FIELDS = (
    "posterTempUrl",
    "poster_temp_url",
    "tempFileURL",
    "tempFileUrl",
    "temp_file_url",
    "posterDownloadFallbackTried",
    "posterFileIdFallbackTried",
    "posterLoadFailed",
)
POSTER_SELECTION_EVIDENCE_FIELDS = (
    "poster_confidence",
    "posterConfidence",
    "poster_evidence",
    "posterEvidence",
    "poster_selection_evidence",
    "posterSelectionEvidence",
    "image_index",
    "imageIndex",
    "poster_image_index",
    "posterImageIndex",
    "poster_role",
    "posterRole",
)
PARENT_OVERVIEW_TITLE_RE = re.compile(
    r"("
    r"活动(?:一览|预告|预览|全览|安排|日程|指南|汇总|合集)"
    r"|(?:本周|这周|今周)\s*(?:活动)?(?:一览|预告|预览|安排|日程|指南|汇总|合集)"
    r"|(?:本月|这个月|当月)\s*(?:活动)?(?:一览|预告|预览|安排|日程|指南|汇总|合集)"
    r"|[0-9一二三四五六七八九十]{1,3}\s*月\s*(?:活动)?(?:一览|预告|预览|安排|日程|指南|汇总|合集)"
    r"|月度\s*(?:活动)?(?:一览|预告|预览|安排|日程|指南|汇总|合集)?"
    r"|(?:端午|假期|节日|holiday).*(?:三日|四日|三天|四天|多日|多天|活动|计划|一览|全览|预告|预览|周刊|日程)"
    r"|全部理由\s*\|\s*亮点内容与活动日程"
    r")",
    re.I,
)
FRONT_END_ADAPTATION_CONTRACT = {
    "backend_package_truth": "cloudbase_internal_file_id",
    "accepted_backend_file_id_fields": list(POSTER_FILE_ID_FIELDS),
    "frontend_runtime_resolution": "wx.cloud.getTempFileURL",
    "coverUrl_package_policy": "coverUrl may equal the same cloud:// fileId; frontend replaces it with a temp URL at runtime",
    "runtime_only_fields_forbidden_in_package": list(RUNTIME_ONLY_POSTER_FIELDS),
    "forbidden_package_poster_values": [
        "mmbiz.qpic.cn",
        "mmecoa.qpic.cn",
        "mp.weixin.qq.com",
        "http://",
        "https://",
        "wxfile://",
        "blob:",
        "/api/v1/weekly/poster/",
    ],
    "quality_targets": {
        "missing_internal_poster_count": 0,
        "invalid_internal_poster_file_id_count": 0,
        "invalid_poster_storage_count": 0,
        "public_or_temp_poster_url_count": 0,
        "public_wechat_or_qpic_poster_count": 0,
        "runtime_poster_state_count": 0,
        "main_poster_selection_review_required_count": 0,
    },
}
DEFAULT_NON_TARGET_ACTIVITY_TERMS = {
    "standup_comedy": ["脱口秀", "喜剧", "stand-up", "standup", "comedy"],
    "folk": ["民谣", "folk"],
    "rock": ["摇滚", "rock", "朋克", "punk", "后摇", "post-rock", "乐队专场"],
    "hiphop": ["hiphop", "hip-hop", "hip hop", "嘻哈", "说唱", "rap show", "rapper"],
    "quiet_bar": ["静吧", "清吧", "小酒馆", "民谣酒馆"],
    "classical_or_concert": ["古典", "交响", "管弦", "弦乐", "贝多芬", "莫扎特", "肖邦", "音乐会"],
    "jazz_swing": ["爵士大乐队", "爵士现场", "swing音乐", "swing dance", "jazz night"],
    "editorial_release": [
        "发布全新 ep",
        "全新 ep 发布",
        "新 ep 发布",
        "发布全新单曲",
        "全新单曲发布",
        "发布全新专辑",
        "全新专辑发布",
        "新专辑上线",
        "新单曲上线",
    ],
    "recruitment_notice": ["招募中", "招募 dj", "dj 招募", "open decks 招募", "open deck 招募"],
}
EDITORIAL_RELEASE_EVENT_KEEP_RE = re.compile(r"派对|演出|首发现场|发布会|release\s*party|showcase|dj\s*set", re.I)
DEFAULT_ELECTRONIC_KEEP_TERMS = [
    "techno",
    "house",
    "trance",
    "dnb",
    "drum and bass",
    "bass music",
    "breakbeat",
    "electro",
    "rave",
    "club night",
    "dj set",
    "open decks",
    "four on the floor",
    "disco",
    "reggae",
    "电子",
    "电音",
    "浩室",
    "锐舞",
    "雷鬼",
]


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple)) and not value:
            continue
        return value
    return ""


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def normalize_subject(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def load_source_policy(path: Path | None) -> dict[str, Any]:
    payload = read_json(path) if path and path.exists() else {}
    categories = payload.get("article_level_block_categories") if isinstance(payload.get("article_level_block_categories"), dict) else {}
    content_terms: dict[str, list[str]] = {}
    for key, fallback in DEFAULT_NON_TARGET_ACTIVITY_TERMS.items():
        values = categories.get(key) if isinstance(categories, dict) else None
        content_terms[key] = list_strings(values) or list(fallback)
    return {
        "blocked_source_hashes": {value.lower() for value in list_strings(payload.get("blocked_source_hashes")) if value},
        "blocked_account_fakeids": {value for value in list_strings(payload.get("blocked_account_fakeids")) if value},
        "blocked_accounts": {normalize_subject(value) for value in list_strings(payload.get("blocked_accounts")) if normalize_subject(value)},
        "blocked_venues": {normalize_subject(value) for value in list_strings(payload.get("blocked_venues")) if normalize_subject(value)},
        "content_terms": content_terms,
        "electronic_keep_terms": list_strings(payload.get("electronic_keep_terms")) or list(DEFAULT_ELECTRONIC_KEEP_TERMS),
    }


def subject_matches(value: str, blocked_values: set[str]) -> bool:
    normalized = normalize_subject(value)
    if not normalized:
        return False
    return any(normalized == blocked or blocked in normalized or normalized in blocked for blocked in blocked_values)


def policy_term_matches(blob: str, terms: list[str]) -> bool:
    haystack = " " + re.sub(r"\s+", " ", str(blob or "").casefold()) + " "
    normalized = normalize_subject(blob)
    for term in terms:
        text = str(term or "").strip()
        if not text:
            continue
        lower = re.sub(r"\s+", " ", text.casefold())
        if re.search(r"[a-z0-9]", lower):
            if re.search(r"(?<![a-z0-9])" + re.escape(lower) + r"(?![a-z0-9])", haystack):
                return True
        elif normalize_subject(text) and normalize_subject(text) in normalized:
            return True
    return False


def non_target_activity_reason(item: dict[str, Any], policy: dict[str, Any]) -> str:
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    source_hashes = {
        str(value).lower()
        for value in [
            first_non_empty(source_article.get("url_hash"), source_article.get("hash")),
            first_non_empty(source_action.get("url_hash"), source_action.get("hash")),
            first_non_empty(item.get("sourceHash"), item.get("source_hash"), item.get("source_url_hash"), item.get("article_hash")),
        ]
        if value
    }
    if source_hashes & (policy.get("blocked_source_hashes") or set()):
        return "source_policy_blocked_source_hash"
    if str(first_non_empty(item.get("account_fakeid")) or "") in (policy.get("blocked_account_fakeids") or set()):
        return "source_policy_blocked_account"
    account_values = [
        str(first_non_empty(item.get("source_account_name"), item.get("account_nickname"), item.get("account")) or ""),
        str(first_non_empty((item.get("source_article") or {}).get("account_name")) or ""),
    ]
    if any(subject_matches(value, policy.get("blocked_accounts") or set()) for value in account_values if value):
        return "source_policy_blocked_account"
    venue_values = [
        str(first_non_empty(item.get("venue_name")) or ""),
        *list_strings(item.get("venue")),
        str(first_non_empty(item.get("title_display"), item.get("title")) or ""),
    ]
    if any(subject_matches(value, policy.get("blocked_venues") or set()) for value in venue_values if value):
        return "source_policy_blocked_venue"
    evidence = item.get("poster_selection_evidence")
    strict_blob = "\n".join(
        value
        for value in [
            str(first_non_empty(item.get("title_display"), item.get("title")) or ""),
            str(first_non_empty(item.get("source_account_name"), item.get("account")) or ""),
            str(first_non_empty(item.get("venue_name")) or ""),
        ]
        if value.strip()
    )
    wide_parts = [
        strict_blob,
        " ".join(list_strings(item.get("music_styles"))),
        " ".join(list_strings(item.get("genres"))),
        " ".join(list_strings(item.get("lineup"))),
    ]
    if isinstance(evidence, dict):
        wide_parts.extend(list_strings(evidence.get("visible_text_lines")))
        wide_parts.extend(list_strings(evidence.get("risk_flags")))
    wide_blob = "\n".join(part for part in wide_parts if part)
    has_keep = policy_term_matches(wide_blob, policy.get("electronic_keep_terms") or [])
    for category, terms in (policy.get("content_terms") or {}).items():
        if category == "editorial_release":
            if policy_term_matches(strict_blob, terms) and not EDITORIAL_RELEASE_EVENT_KEEP_RE.search(strict_blob):
                return f"non_target_activity_{category}"
            continue
        if category == "hiphop":
            if policy_term_matches(strict_blob, terms) and not has_keep:
                return f"non_target_activity_{category}"
            if policy_term_matches(wide_blob, terms) and not has_keep:
                return f"non_target_activity_{category}"
            continue
        if policy_term_matches(strict_blob, terms):
            return f"non_target_activity_{category}"
        if category in {"standup_comedy", "folk", "rock", "quiet_bar", "classical_or_concert", "jazz_swing"}:
            if policy_term_matches(wide_blob, terms) and not has_keep:
                return f"non_target_activity_{category}"
    return ""


def is_http_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def is_public_wechat_image_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return ("mmbiz.qpic.cn" in text) or ("mmecoa.qpic.cn" in text) or ("mp.weixin.qq.com" in text)


def is_internal_poster_file_id(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(INTERNAL_WEEKLY_POSTER_RE.match(text))


def poster_file_id_value(item: dict[str, Any]) -> str:
    return str(first_non_empty(*(item.get(key) for key in POSTER_FILE_ID_FIELDS)) or "").strip()


def poster_storage_value(item: dict[str, Any]) -> str:
    return str(first_non_empty(*(item.get(key) for key in POSTER_STORAGE_FIELDS)) or "").strip()


def is_public_or_temp_poster_url(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower.startswith(("http://", "https://", "wxfile://", "blob:")):
        return True
    if "/api/v1/weekly/poster/" in lower:
        return True
    return is_public_wechat_image_url(text)


def is_aggregate_child_item(item: dict[str, Any]) -> bool:
    item_id = str(first_non_empty(item.get("id"), item.get("event_id")) or "").strip()
    return item_id.startswith("agg-child-") or item.get("aggregation_child") is True


def aggregate_child_poster_suppressed(item: dict[str, Any]) -> bool:
    return item.get("poster_suppressed") is True or item.get("main_poster_suppressed") is True


def aggregate_child_has_internal_activity_poster(item: dict[str, Any]) -> bool:
    return any(
        is_internal_poster_file_id(item.get(key))
        for key in (*POSTER_FILE_ID_FIELDS, *POSTER_URL_FIELDS)
    )


def source_action_is_enabled(item: dict[str, Any]) -> bool:
    source_action = item.get("source_action")
    if isinstance(source_action, dict) and source_action.get("available") is False:
        return False
    source_hash = first_non_empty(
        source_action.get("url_hash") if isinstance(source_action, dict) else "",
        source_action.get("url") if isinstance(source_action, dict) else "",
        item.get("sourceHash"),
        item.get("source_hash"),
        item.get("source_article", {}).get("url_hash") if isinstance(item.get("source_article"), dict) else "",
    )
    return bool(str(source_hash or "").strip())


def aggregate_child_source_hash_residue(item: dict[str, Any]) -> dict[str, Any] | None:
    if not is_aggregate_child_item(item):
        return None
    fields: list[str] = []
    for key in ("sourceHash", "source_hash", "sourceRefId", "source_ref_id"):
        if str(item.get(key) or "").strip():
            fields.append(key)
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    if str(source_article.get("url_hash") or "").strip():
        fields.append("source_article.url_hash")
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    if str(first_non_empty(source_action.get("url_hash"), source_action.get("url")) or "").strip():
        fields.append("source_action.url_hash")
    if not fields:
        return None
    identity = item_identity(item)
    identity["fields"] = sorted(set(fields))
    return identity


def aggregate_child_poster_suppressed_residue(item: dict[str, Any]) -> dict[str, Any] | None:
    if not is_aggregate_child_item(item):
        return None
    if not aggregate_child_poster_suppressed(item):
        return None
    identity = item_identity(item)
    identity["poster_file_id"] = poster_file_id_value(item)
    identity["reason"] = "aggregate_child_requires_real_cloudbase_activity_poster"
    return identity


def aggregate_child_poster_field_residue(item: dict[str, Any]) -> dict[str, Any] | None:
    if not is_aggregate_child_item(item):
        return None
    fields: list[str] = []
    has_internal_activity_poster = aggregate_child_has_internal_activity_poster(item)
    for key in POSTER_FILE_ID_FIELDS:
        value = str(item.get(key) or "").strip()
        if value and not is_internal_poster_file_id(value):
            fields.append(key)
    for key in POSTER_URL_FIELDS:
        value = str(item.get(key) or "").strip()
        if value and is_public_or_temp_poster_url(value):
            fields.append(key)
    for key in POSTER_STORAGE_FIELDS:
        value = str(item.get(key) or "").strip()
        if value and value.lower() != "cloudbase":
            fields.append(key)
    poster_source = str(item.get("poster_source") or "").strip()
    if poster_source:
        poster_source_lower = poster_source.lower()
        is_cloudbase_source = poster_source_lower == "cloudbase_storage" and has_internal_activity_poster
        is_internal_poster_path = "weekly-posters/" in poster_source
        if not is_cloudbase_source and not is_internal_poster_path:
            fields.append("poster_source")
    poster_cloud_path = str(item.get("poster_cloud_path") or "").strip()
    if poster_cloud_path and "weekly-posters/" not in poster_cloud_path:
        fields.append("poster_cloud_path")
    if not fields:
        return None
    identity = item_identity(item)
    identity["fields"] = sorted(set(fields))
    identity["reason"] = "aggregate_child_must_not_keep_public_or_parent_poster_fields"
    return identity


def item_text_values(value: Any, *, limit: int = 24) -> list[str]:
    out: list[str] = []
    if isinstance(value, list):
        for child in value:
            out.extend(item_text_values(child, limit=limit))
            if len(out) >= limit:
                break
    elif isinstance(value, dict):
        for key in ("text", "ocr_text", "poster_text", "body_text", "summary", "digest"):
            child = first_non_empty(value.get(key))
            if child:
                out.append(str(child))
            if len(out) >= limit:
                break
    else:
        text = first_non_empty(value)
        if text:
            out.append(str(text))
    return out[:limit]


def item_title_value(item: dict[str, Any]) -> str:
    return str(first_non_empty(item.get("title_display"), item.get("title"), item.get("event_title")) or "")


def item_has_value(item: dict[str, Any], *keys: str) -> bool:
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            if any(str(child or "").strip() for child in value):
                return True
        elif str(value or "").strip():
            return True
    return False


def has_strong_single_event_evidence(item: dict[str, Any]) -> bool:
    if not item_has_value(item, "event_date_start", "event_date", "date_start", "date"):
        return False
    return (
        item_has_value(item, "event_title", "title_display")
        and item_has_value(item, "venue", "venue_name")
        and item_has_value(item, "lineup", "lineup_artists", "artists")
    )


def llm_parent_overview_decision(item: dict[str, Any]) -> bool:
    decision = item.get("sanji_parent_overview_llm_decision")
    if not isinstance(decision, dict):
        return False
    return str(first_non_empty(decision.get("classification")) or "").strip().lower() in {
        "parent_overview",
        "club_overview",
        "roundup",
        "aggregate_parent",
        "overview",
    }


def is_parent_overview_feed_item(item: dict[str, Any]) -> bool:
    if is_aggregate_child_item(item):
        return False
    if item.get("record_type") == "club_overview_parent" or item.get("parent_aggregate") is True:
        return True
    if item.get("include_in_activity_feed") is False:
        return True
    if llm_parent_overview_decision(item):
        return True
    if has_strong_single_event_evidence(item):
        return False
    return bool(PARENT_OVERVIEW_TITLE_RE.search(item_title_value(item)))


def parent_overview_feed_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **item_identity(item),
            "record_type": item.get("record_type"),
            "parent_aggregate": item.get("parent_aggregate"),
            "include_in_activity_feed": item.get("include_in_activity_feed"),
            "llm_classification": (
                item.get("sanji_parent_overview_llm_decision", {}).get("classification")
                if isinstance(item.get("sanji_parent_overview_llm_decision"), dict)
                else ""
            ),
            "reason": "parent_overview_must_render_only_in_venue_overview",
        }
        for item in items
        if is_parent_overview_feed_item(item)
    ]


def aggregate_child_date_evidence_texts(item: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in (
        "title",
        "title_original",
        "title_display",
        "display_title",
        "evidence",
        "description_original_lines",
        "poster_ocr_text",
        "posterOcrText",
        "source_evidence_text",
    ):
        texts.extend(item_text_values(item.get(key)))
    return [text for text in texts if text]


def aggregate_child_has_strong_date_evidence(item: dict[str, Any]) -> bool:
    event_date = str(first_non_empty(item.get("event_date_start"), item.get("eventDateStart")) or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", event_date):
        return False
    try:
        parsed = datetime.strptime(event_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    year = str(parsed.year)
    month = parsed.month
    day = parsed.day
    month_0 = f"{month:02d}"
    day_0 = f"{day:02d}"
    explicit_patterns = [
        re.compile(rf"\b{year}[-./]{month:02d}[-./]{day:02d}\b"),
        re.compile(rf"\b{year}[-./]{month}[-./]{day}\b"),
        re.compile(rf"(?<!\d){month_0}[./·・•-]{day_0}(?!\d)"),
        re.compile(rf"(?<!\d){month}[./·・•-]{day}(?!\d)"),
        re.compile(rf"(?<!\d){month_0}{day_0}(?!\d)"),
        re.compile(rf"(?<!\d){month}\s*月\s*0?{day}\s*(?:日|号)?"),
    ]
    texts = aggregate_child_date_evidence_texts(item)
    for text in texts:
        if any(pattern.search(text) for pattern in explicit_patterns):
            return True

    post_date = str(first_non_empty(item.get("source_published_at"), item.get("post_date"), item.get("source_article", {}).get("published_at") if isinstance(item.get("source_article"), dict) else "") or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", post_date) and post_date[:7] == event_date[:7]:
        day_pattern = re.compile(rf"(?<!\d)0?{day}(?!\d)")
        return any(day_pattern.search(text) for text in texts)
    return False


def aggregate_child_weak_date_evidence(item: dict[str, Any]) -> dict[str, Any] | None:
    if not is_aggregate_child_item(item):
        return None
    if aggregate_child_has_strong_date_evidence(item):
        return None
    identity = item_identity(item)
    identity["source_published_at"] = first_non_empty(
        item.get("source_published_at"),
        item.get("post_date"),
        item.get("source_article", {}).get("published_at") if isinstance(item.get("source_article"), dict) else "",
    )
    identity["evidence"] = aggregate_child_date_evidence_texts(item)[:6]
    identity["reason"] = "aggregate_child_requires_explicit_month_day_evidence"
    return identity


def poster_url_values(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in POSTER_URL_FIELDS:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values


def runtime_poster_state_residue(item: dict[str, Any]) -> dict[str, Any] | None:
    fields: list[str] = []
    for key in RUNTIME_ONLY_POSTER_FIELDS:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if value is False:
            continue
        fields.append(key)
    if not fields:
        return None
    identity = item_identity(item)
    identity["fields"] = sorted(set(fields))
    identity["reason"] = "frontend_runtime_poster_state_must_not_be_persisted_in_release_package"
    return identity


def poster_public_source_hash_value(item: dict[str, Any]) -> str:
    return str(first_non_empty(
        item.get("poster_public_source_hash"),
        item.get("posterPublicSourceHash"),
        item.get("poster_source_hash"),
        item.get("posterSourceHash"),
    ) or "").strip()


def source_article_hash_value(item: dict[str, Any]) -> str:
    source_article = item.get("source_article") if isinstance(item.get("source_article"), dict) else {}
    source_action = item.get("source_action") if isinstance(item.get("source_action"), dict) else {}
    return str(first_non_empty(
        source_article.get("url_hash"),
        source_article.get("hash"),
        source_action.get("url_hash"),
        item.get("sourceHash"),
        item.get("source_hash"),
        item.get("source_url_hash"),
        item.get("article_hash"),
    ) or "").strip()


def has_poster_selection_evidence(item: dict[str, Any]) -> bool:
    for key in POSTER_SELECTION_EVIDENCE_FIELDS:
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return True
    return False


def is_schedule_split_item(item: dict[str, Any]) -> bool:
    item_id = str(first_non_empty(item.get("id"), item.get("event_id")) or "").strip()
    if ":schedule:" in item_id:
        return True
    if item.get("schedule_split") is True or item.get("schedule_item") is True:
        return True
    return False


def schedule_base_id(item: dict[str, Any]) -> str:
    """Base article id of a schedule item (text before ':schedule:').

    A non-split parent maps to its own id, so a parent and its dated splits
    collapse to one base id and form a single schedule family.
    """
    item_id = str(first_non_empty(item.get("id"), item.get("event_id")) or "").strip()
    return item_id.split(":schedule:", 1)[0]


def shared_poster_source_hash_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        source_hash = poster_public_source_hash_value(item)
        if not source_hash:
            continue
        by_hash.setdefault(source_hash, []).append(item)

    groups: list[dict[str, Any]] = []
    for source_hash, group_items in sorted(by_hash.items()):
        if len(group_items) < 2:
            continue
        article_hashes = sorted({source_article_hash_value(item) for item in group_items if source_article_hash_value(item)})
        all_same_article = len(article_hashes) <= 1
        all_schedule_splits = all(is_schedule_split_item(item) for item in group_items)
        # A schedule parent shares its poster with its own dated ':schedule:' splits.
        # The parent itself is not tagged as a split, which used to break
        # all_schedule_splits and force a false main-poster review. Treat
        # {parent + its splits} as one schedule family when every item collapses
        # to a single base article id and the group contains at least one split.
        base_ids = {schedule_base_id(item) for item in group_items if schedule_base_id(item)}
        schedule_family = len(base_ids) <= 1 and any(is_schedule_split_item(item) for item in group_items)
        evidence_items = [item for item in group_items if has_poster_selection_evidence(item)]
        missing_evidence_items = [item for item in group_items if not has_poster_selection_evidence(item)]
        has_complete_selection_evidence = len(evidence_items) == len(group_items)
        review_required = (
            not (schedule_family or (all_same_article and all_schedule_splits))
            and not has_complete_selection_evidence
        )
        if all_same_article and all_schedule_splits:
            reason = "same_article_schedule_split_shared_poster_hash"
        elif schedule_family:
            reason = "schedule_family_parent_plus_splits_shared_poster_hash"
        elif has_complete_selection_evidence:
            reason = "shared_original_poster_hash_has_explicit_selection_evidence"
        else:
            reason = "same_original_poster_hash_reused_across_distinct_activities"
        groups.append({
            "poster_public_source_hash": source_hash,
            "item_count": len(group_items),
            "source_article_hash_count": len(article_hashes),
            "source_article_hashes": article_hashes[:20],
            "poster_selection_evidence_count": len(evidence_items),
            "missing_poster_selection_evidence_count": len(missing_evidence_items),
            "review_required": review_required,
            "reason": reason,
            "items": [
                {
                    **item_identity(item),
                    "source_article_hash": source_article_hash_value(item),
                    "poster_source": item.get("poster_source"),
                    "has_poster_selection_evidence": has_poster_selection_evidence(item),
                    "quality_flags": item.get("quality_flags"),
                }
                for item in group_items[:20]
            ],
        })
    return groups


def missing_poster_selection_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **item_identity(item),
            "poster_public_source_hash": poster_public_source_hash_value(item),
            "poster_source": item.get("poster_source"),
            "reason": "main_poster_selection_has_no_image_index_confidence_or_evidence",
        }
        for item in items
        if poster_public_source_hash_value(item) and not has_poster_selection_evidence(item)
    ]


def has_geo(item: dict[str, Any]) -> bool:
    lat = first_non_empty(item.get("geo_lat"), item.get("venue_lat"))
    lng = first_non_empty(item.get("geo_lng"), item.get("venue_lng"))
    return lat not in ("", None) and lng not in ("", None)


def item_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": first_non_empty(item.get("id"), item.get("event_id"), item.get("article_id")),
        "title": first_non_empty(item.get("title_display"), item.get("title")),
        "event_date_start": first_non_empty(item.get("event_date_start"), item.get("eventDateStart")),
        "event_date_end": first_non_empty(item.get("event_date_end"), item.get("eventDateEnd")),
        "city": item.get("city"),
        "city_keys": item.get("city_keys"),
        "venue": first_non_empty(item.get("venue_name"), item.get("venue")),
    }


def outside_window_items(items: list[dict[str, Any]], window_start: str, window_end: str) -> list[dict[str, Any]]:
    if not window_start or not window_end:
        return []
    dropped: list[dict[str, Any]] = []
    for item in items:
        start = first_non_empty(item.get("event_date_start"), item.get("eventDateStart"))
        end = first_non_empty(item.get("event_date_end"), item.get("eventDateEnd")) or start
        if start and end and (end < window_start or start > window_end):
            dropped.append(item_identity(item))
    return dropped


def missing_event_date_start_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for item in items:
        start = first_non_empty(item.get("event_date_start"), item.get("eventDateStart"))
        if not str(start or "").strip():
            missing.append(item_identity(item))
    return missing


def city_route_mismatches(api_dir: Path) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    city_dir = api_dir / "by-city"
    if not city_dir.exists():
        return mismatches
    for path in sorted(city_dir.glob("*.json")):
        payload = read_json(path)
        city_key = str(payload.get("city_key") or path.stem).strip()
        city_label = str(payload.get("city") or "").strip()
        expected = CITY_LABEL_BY_KEY.get(city_key)
        if expected and city_label and city_label != expected:
            mismatches.append({
                "path": str(path),
                "city_key": city_key,
                "city": city_label,
                "expected_city": expected,
                "item_count": payload.get("item_count"),
            })
    return mismatches


def manifest_provenance_issues(api_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    manifest_out = str(manifest.get("out_dir") or "").strip()
    if manifest_out:
        try:
            if Path(manifest_out).resolve() != api_dir.resolve():
                issues.append({"field": "out_dir", "value": manifest_out, "expected": str(api_dir)})
        except OSError:
            issues.append({"field": "out_dir", "value": manifest_out, "expected": str(api_dir)})

    source_pack = str(manifest.get("source_pack_dir") or "").strip()
    base_pack = str(manifest.get("source_base_pack_dir") or "").strip()
    incremental_pack = str(manifest.get("source_incremental_pack_dir") or "").strip()
    if source_pack and base_pack and incremental_pack and source_pack == base_pack and source_pack != incremental_pack:
        issues.append({
            "field": "source_pack_dir",
            "value": source_pack,
            "expected": incremental_pack,
            "reason": "source_pack_dir still points at the base package after incremental merge",
        })
    return issues


def static_route_index_issues(api_dir: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    required_indexes = [
        ("by-city/index.json", "cities"),
        ("by-date/index.json", "dates"),
    ]
    for rel_path, list_field in required_indexes:
        path = api_dir / rel_path
        if not path.exists():
            issues.append({"path": rel_path, "reason": "missing"})
            continue
        payload = read_json(path)
        if not isinstance(payload.get(list_field), list):
            issues.append({"path": rel_path, "reason": f"{list_field}_must_be_list"})
    return issues


def validate(api_dir: Path, *, require_internal_posters: bool, enforce_window_start: bool, fail_on_missing_geo: bool, source_policy_path: Path | None = DEFAULT_SOURCE_POLICY) -> dict[str, Any]:
    current_path = api_dir / "current.json"
    manifest_path = api_dir / "manifest.json"
    if not current_path.exists():
        raise SystemExit(f"current.json not found: {current_path}")
    if not manifest_path.exists():
        raise SystemExit(f"manifest.json not found: {manifest_path}")
    current = read_json(current_path)
    manifest = read_json(manifest_path)
    items = current.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"current.json does not contain an item list: {current_path}")

    missing_internal_posters = []
    invalid_internal_posters = []
    invalid_poster_storage_items = []
    public_or_temp_poster_items = []
    public_wechat_or_qpic_poster_items = []
    public_or_temp_seen: set[str] = set()
    public_wechat_seen: set[str] = set()
    for item in items:
        file_id = poster_file_id_value(item)
        identity = item_identity(item)
        poster_required = True
        if poster_required and not is_internal_poster_file_id(file_id):
            missing_internal_posters.append(identity)
            if file_id:
                invalid_internal_posters.append({**identity, "poster_file_id": file_id})
        storage = poster_storage_value(item)
        if poster_required and storage.lower() != "cloudbase":
            invalid_poster_storage_items.append({**identity, "poster_storage": storage})
        for field in POSTER_URL_FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            value = value.strip()
            key = f"{identity.get('id')}::{field}::{value}"
            if is_public_or_temp_poster_url(value) and key not in public_or_temp_seen:
                public_or_temp_seen.add(key)
                public_or_temp_poster_items.append({**identity, "field": field, "value": value[:200]})
            if is_public_wechat_image_url(value) and key not in public_wechat_seen:
                public_wechat_seen.add(key)
                public_wechat_or_qpic_poster_items.append({**identity, "field": field, "value": value[:200]})
    public_poster_items = [
        item_identity(item)
        for item in items
        if any(is_public_wechat_image_url(value) for value in poster_url_values(item))
    ]
    aggregate_child_source_items = [
        item_identity(item)
        for item in items
        if is_aggregate_child_item(item) and source_action_is_enabled(item)
    ]
    aggregate_child_source_hash_items = [
        residue
        for item in items
        if (residue := aggregate_child_source_hash_residue(item)) is not None
    ]
    aggregate_child_poster_suppressed_items = [
        residue
        for item in items
        if (residue := aggregate_child_poster_suppressed_residue(item)) is not None
    ]
    aggregate_child_poster_residue_items = [
        residue
        for item in items
        if (residue := aggregate_child_poster_field_residue(item)) is not None
    ]
    aggregate_child_weak_date_items = [
        residue
        for item in items
        if (residue := aggregate_child_weak_date_evidence(item)) is not None
    ]
    runtime_poster_state_items = [
        residue
        for item in items
        if (residue := runtime_poster_state_residue(item)) is not None
    ]
    parent_overview_items = parent_overview_feed_items(items)
    shared_poster_groups = shared_poster_source_hash_groups(items)
    main_poster_review_groups = [group for group in shared_poster_groups if group.get("review_required")]
    main_poster_review_items = [
        item
        for group in main_poster_review_groups
        for item in group.get("items", [])
    ]
    missing_poster_selection_evidence = missing_poster_selection_evidence_items(items)
    missing_geo_items = [item_identity(item) for item in items if not has_geo(item)]
    source_policy = load_source_policy(source_policy_path)
    non_target_activity_items = [
        {
            **item_identity(item),
            "reason": reason,
        }
        for item in items
        if (reason := non_target_activity_reason(item, source_policy))
    ]
    outside_window = outside_window_items(
        items,
        str(first_non_empty(manifest.get("window_start")) or ""),
        str(first_non_empty(manifest.get("window_end")) or ""),
    ) if enforce_window_start else []
    missing_event_dates = missing_event_date_start_items(items) if enforce_window_start else []
    route_mismatches = city_route_mismatches(api_dir)
    provenance_issues = manifest_provenance_issues(api_dir, manifest)
    route_index_issues = static_route_index_issues(api_dir)

    hard_failures: list[str] = []
    if require_internal_posters and missing_internal_posters:
        hard_failures.append("missing_internal_poster_file_id")
    if require_internal_posters and invalid_internal_posters:
        hard_failures.append("invalid_internal_poster_file_id_format")
    if require_internal_posters and invalid_poster_storage_items:
        hard_failures.append("invalid_poster_storage")
    if require_internal_posters and public_or_temp_poster_items:
        hard_failures.append("public_or_temp_poster_url")
    if enforce_window_start and missing_event_dates:
        hard_failures.append("missing_event_date_start")
    if enforce_window_start and outside_window:
        hard_failures.append("event_date_start_outside_manifest_window")
    if route_mismatches:
        hard_failures.append("city_route_label_mismatch")
    if provenance_issues:
        hard_failures.append("manifest_provenance_stale")
    if route_index_issues:
        hard_failures.append("static_route_index_missing")
    if aggregate_child_source_items:
        hard_failures.append("aggregate_child_source_action_enabled")
    if aggregate_child_source_hash_items:
        hard_failures.append("aggregate_child_source_hash_present")
    if aggregate_child_poster_suppressed_items:
        hard_failures.append("aggregate_child_poster_suppressed")
    if aggregate_child_poster_residue_items:
        hard_failures.append("aggregate_child_poster_field_present")
    if aggregate_child_weak_date_items:
        hard_failures.append("aggregate_child_weak_date_evidence")
    if require_internal_posters and runtime_poster_state_items:
        hard_failures.append("runtime_poster_state_persisted")
    if parent_overview_items:
        hard_failures.append("parent_overview_in_activity_feed")
    if require_internal_posters and main_poster_review_groups:
        hard_failures.append("main_poster_selection_review_required")
    if fail_on_missing_geo and missing_geo_items:
        hard_failures.append("missing_geo")
    if non_target_activity_items:
        hard_failures.append("non_target_activity_in_feed")

    return {
        "schema_version": SCHEMA_VERSION,
        "api_dir": str(api_dir),
        "ok": not hard_failures,
        "hard_failures": hard_failures,
        "item_count": len(items),
        "manifest_item_count": manifest.get("item_count"),
        "window_start": manifest.get("window_start"),
        "window_end": manifest.get("window_end"),
        "require_internal_posters": require_internal_posters,
        "enforce_window_start": enforce_window_start,
        "fail_on_missing_geo": fail_on_missing_geo,
        "source_policy_path": str(source_policy_path) if source_policy_path else "",
        "front_end_adaptation_contract": FRONT_END_ADAPTATION_CONTRACT,
        "missing_internal_poster_count": len(missing_internal_posters),
        "missing_internal_poster_items": missing_internal_posters,
        "invalid_internal_poster_file_id_count": len(invalid_internal_posters),
        "invalid_internal_poster_file_id_items": invalid_internal_posters[:50],
        "invalid_poster_storage_count": len(invalid_poster_storage_items),
        "invalid_poster_storage_items": invalid_poster_storage_items[:50],
        "public_or_temp_poster_url_count": len(public_or_temp_poster_items),
        "public_or_temp_poster_url_items": public_or_temp_poster_items[:50],
        "public_wechat_or_qpic_poster_count": len(public_wechat_or_qpic_poster_items),
        "public_wechat_or_qpic_poster_items": public_wechat_or_qpic_poster_items[:50],
        "public_wechat_poster_url_count": len(public_poster_items),
        "public_wechat_poster_url_items": public_poster_items[:50],
        "aggregate_child_source_enabled_count": len(aggregate_child_source_items),
        "aggregate_child_source_enabled_items": aggregate_child_source_items[:50],
        "aggregate_child_source_hash_present_count": len(aggregate_child_source_hash_items),
        "aggregate_child_source_hash_present_items": aggregate_child_source_hash_items[:50],
        "aggregate_child_poster_not_suppressed_count": 0,
        "aggregate_child_poster_not_suppressed_items": [],
        "aggregate_child_poster_suppressed_count": len(aggregate_child_poster_suppressed_items),
        "aggregate_child_poster_suppressed_items": aggregate_child_poster_suppressed_items[:50],
        "aggregate_child_poster_field_present_count": len(aggregate_child_poster_residue_items),
        "aggregate_child_poster_field_present_items": aggregate_child_poster_residue_items[:50],
        "aggregate_child_weak_date_evidence_count": len(aggregate_child_weak_date_items),
        "aggregate_child_weak_date_evidence_items": aggregate_child_weak_date_items[:50],
        "runtime_poster_state_count": len(runtime_poster_state_items),
        "runtime_poster_state_items": runtime_poster_state_items[:50],
        "parent_overview_in_activity_feed_count": len(parent_overview_items),
        "parent_overview_in_activity_feed_items": parent_overview_items[:100],
        "shared_poster_source_hash_group_count": len(shared_poster_groups),
        "shared_poster_source_hash_groups": shared_poster_groups[:50],
        "main_poster_selection_review_required_count": len(main_poster_review_items),
        "main_poster_selection_review_required_items": main_poster_review_items[:100],
        "main_poster_selection_review_required_groups": main_poster_review_groups[:50],
        "missing_poster_selection_evidence_count": len(missing_poster_selection_evidence),
        "missing_poster_selection_evidence_items": missing_poster_selection_evidence[:100],
        "missing_geo_count": len(missing_geo_items),
        "missing_geo_items": missing_geo_items[:50],
        "non_target_activity_count": len(non_target_activity_items),
        "non_target_activity_items": non_target_activity_items[:100],
        "missing_event_date_start_count": len(missing_event_dates),
        "missing_event_date_start_items": missing_event_dates[:50],
        "outside_window_start_count": len(outside_window),
        "outside_window_start_items": outside_window[:50],
        "city_route_mismatch_count": len(route_mismatches),
        "city_route_mismatches": route_mismatches[:50],
        "manifest_provenance_issue_count": len(provenance_issues),
        "manifest_provenance_issues": provenance_issues,
        "static_route_index_issue_count": len(route_index_issues),
        "static_route_index_issues": route_index_issues,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--require-internal-posters", action="store_true")
    parser.add_argument("--enforce-window-start", action="store_true")
    parser.add_argument("--fail-on-missing-geo", action="store_true")
    parser.add_argument("--source-policy", default=str(DEFAULT_SOURCE_POLICY))
    args = parser.parse_args(argv)

    report = validate(
        args.api_dir,
        require_internal_posters=args.require_internal_posters,
        enforce_window_start=args.enforce_window_start,
        fail_on_missing_geo=args.fail_on_missing_geo,
        source_policy_path=Path(args.source_policy) if args.source_policy else None,
    )
    if args.report:
        write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
