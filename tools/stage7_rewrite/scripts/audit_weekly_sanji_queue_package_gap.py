#!/usr/bin/env python3
"""Audit whether recent Sanji daily source rows made it into a weekly package.

This is a source-to-package coverage gate. It intentionally focuses on
current/future single-event-looking Sanji rows and excludes club overview
parents, notices, closures, and other non-event rows. The output is report-only;
the caller decides whether a missing count should block deployment.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "weekly_sanji_queue_package_gap_audit.v2"
DEFAULT_SOURCE_POLICY = Path(__file__).resolve().parents[1] / "registries" / "weekly_sanji_source_policy.json"

EVENT_SIGNAL_RE = re.compile(
    r"今晚|今夜|今日|周[一二三四五六日天]|星期[一二三四五六日天]|派对|舞池|阵容|呈现|巡演|"
    r"pres\.?|presents?|w/|with|dj|live|club|party|rave|open\s*deck|免票|入场|唱机|"
    r"放映|纪录片|展映|影展|观影",
    re.I,
)
PARENT_OVERVIEW_RE = re.compile(
    r"活动(?:一览|全览|预览|预告|安排|日程)|本周活动|本周预览|本周信号|月活动|六月活动一览|"
    r"端午.*(?:三日|四日|三天|四天|多日|多天|一览|全览|周刊|计划|活动|日程)|假期活动一览|全部理由|亮点内容与活动日程|"
    r"schedule|timetable",
    re.I,
)
NON_EVENT_RE = re.compile(
    r"店休|不营业|请勿跑空|通知|公告|阵容调整|延期|取消|暂停|抱歉|回顾|照片|招聘|招募|兼职|简历|寻找.*伙伴|菜单|酒水单|请你去|送出|转发.*朋友圈",
    re.I,
)
# ponytail: removed 放映 from NON_EVENT_RE — film screenings from curated accounts (DONG) ARE events.
# Generic non-curated film articles are blocked via blocked_source_hashes in source policy instead.
DATE_MD_RE = re.compile(
    r"(?<!\d)(?:20)?(?:(26)[./-])?(\d{1,2})\s*[./月-]\s*(\d{1,2})(?:\s*[日号])?(?!\d)"
)
DATE_CHINESE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|号)?(?!\d)")
DATE_RANGE_RE = re.compile(
    r"(?<!\d)(?:20)?\d{0,2}[./月-]\d{1,2}\s*(?:[-~—–至到])\s*(?:20)?\d{0,2}[./月-]\d{1,2}(?!\d)|"
    r"(?<!\d)\d{1,2}\s*[./月-]\s*\d{1,2}\s*(?:[-~—–至到])\s*\d{1,2}\s*[./月-]\s*\d{1,2}(?!\d)"
)
PUBLISH_TIMESTAMP_RE = re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s+\d{1,2}:\d{2}")
EVENT_DATE_CONTEXT_RE = re.compile(r"排期|演出|放映|活动|开场|入场|时间|派对|party|live|dj", re.I)
WEEKDAY_RE = re.compile(r"(?:本周|这周|周|星期)([一二三四五六日天])")
HASH16_RE = re.compile(r"(?i)(?<![0-9a-f])([0-9a-f]{16})(?![0-9a-f])")
PACKAGE_HASH_FIELD_HINTS = {
    "id",
    "event_id",
    "article_id",
    "queue_id",
    "url_hash",
    "source_url_hash",
    "source_hash",
    "sourcehash",
    "sourceitemhash",
    "article_hash",
    "link_hash",
    "source_event_id",
    "source_queue_aliases",
    "_source_aliases",
    "source_aliases",
    "source_hashes",
    "source_alias_hashes",
    "merged_source_hashes",
}
REPAIR_REPORT_FILENAMES = (
    "repair_report.json",
    "release_conflict_repair.json",
    "release_conflict_repair_report.json",
    "source_policy_package_repair.json",
    "build_filter_dispositions.json",
)
REPAIR_DISPOSITION_ROW_FIELDS = (
    "filtered_items",
    "removed_items",
    "policy_removed",
    "policy_removed_history",
    "quarantined_conflict_items",
    "aggregate_child_source_suppressed_items",
    "aggregate_child_merge_sources_pruned",
)
ACCOUNTED_REVIEW_FLAGS = {
    "missing_lineup_visible",
    "not_music_event",
    "not_an_event_article",
    "not_a_specific_event",
    "parent_overview_article",
    "parent_overview_calendar",
    "recruitment_article_not_event",
    "venue_closed_on_date",
    "no_event_scheduled",
    "article_is_essay_not_event",
    "source_review_needed",
    "no_clean_main_poster_visible",
}
ACCOUNTED_STATUS_VALUES = {
    "blocked",
    "filtered",
    "rejected",
    "review",
    "not_event",
    "not_music_event",
    "not_an_event_article",
}
DISPOSITION_FIELDS = (
    "publish_block_reason",
    "filtered_reason",
    "drop_reason",
    "disposition_reason",
    "block_reason",
    "reject_reason",
    "status_reason",
    "publish_window_filter_reason",
)
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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def collect_strings(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(collect_strings(item))
        return strings
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(collect_strings(item))
        return strings
    return []


def normalize_subject(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def load_source_policy(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        payload: dict[str, Any] = {}
    else:
        try:
            payload = read_json(path)
        except Exception:
            payload = {}
    categories = payload.get("article_level_block_categories") if isinstance(payload.get("article_level_block_categories"), dict) else {}
    content_terms: dict[str, list[str]] = {}
    for key, fallback in DEFAULT_NON_TARGET_ACTIVITY_TERMS.items():
        values = categories.get(key) if isinstance(categories, dict) else None
        content_terms[key] = list_strings(values) or list(fallback)
    return {
        "path": str(path) if path else "",
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


def source_policy_exclude_reason(row: dict[str, Any], policy: dict[str, Any]) -> str:
    source_hash = row_source_hash(row).lower()
    if source_hash and source_hash in (policy.get("blocked_source_hashes") or set()):
        return "source_policy_blocked_source_hash"
    fakeid = first_string(row.get("account_fakeid"))
    if fakeid and fakeid in (policy.get("blocked_account_fakeids") or set()):
        return "source_policy_blocked_account"
    account = row_account(row)
    if account and subject_matches(account, policy.get("blocked_accounts") or set()):
        return "source_policy_blocked_account"
    title = first_string(row.get("title"), row.get("source_title"))
    if title and subject_matches(title, policy.get("blocked_venues") or set()):
        return "source_policy_blocked_venue"
    strict_blob = "\n".join(
        str(part or "")
        for part in [
            title,
            first_string(row.get("digest"), row.get("summary_digest")),
            first_string(row.get("account_key"), row.get("account")),
            account,
        ]
        if str(part or "").strip()
    )
    wide_blob = "\n".join(
        part
        for part in [
            strict_blob,
            first_string(row.get("body_text")),
        ]
        if part
    )
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


def parse_date_text(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_datetime_text(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and value > 1_000_000_000:
        return datetime.fromtimestamp(float(value))
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    parsed_date = parse_date_text(text)
    if parsed_date:
        return datetime.combine(parsed_date, datetime.max.time()).replace(microsecond=0)
    return None


def parse_title_date(title: str, *, base_year: int, post_date: date | None) -> date | None:
    title = title or ""
    for match in DATE_MD_RE.finditer(title):
        year_prefix, month_text, day_text = match.groups()
        month = int(month_text)
        day = int(day_text)
        year = 2000 + int(year_prefix) if year_prefix else base_year
        try:
            return date(year, month, day)
        except ValueError:
            continue
    for match in DATE_CHINESE_RE.finditer(title):
        month = int(match.group(1))
        day = int(match.group(2))
        try:
            return date(base_year, month, day)
        except ValueError:
            continue
    if post_date and re.search(r"今晚|今夜|今日", title):
        return post_date
    if post_date:
        weekday = WEEKDAY_RE.search(title)
        if weekday:
            target = "一二三四五六日天".index(weekday.group(1))
            if target == 7:
                target = 6
            delta = (target - post_date.weekday()) % 7
            return post_date + timedelta(days=delta)
    return None


def body_date_looks_like_publish_timestamp(text: str) -> bool:
    for match in PUBLISH_TIMESTAMP_RE.finditer(text or ""):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = len(text)
        window = text[line_start:line_end]
        if not EVENT_DATE_CONTEXT_RE.search(window):
            return True
    return False


def row_search_blob(row: dict[str, Any]) -> str:
    values = [
        first_string(row.get("title"), row.get("source_title")),
        first_string(row.get("digest")),
        first_string(row.get("summary_digest")),
        first_string(row.get("body_text")),
        first_string(row.get("content_text")),
        first_string(row.get("text")),
    ]
    return "\n".join(value for value in values if value)


def row_post_datetime(row: dict[str, Any]) -> datetime | None:
    for key in ("post_time", "publish_time_iso", "created_at", "updated_at", "post_date", "publish_time"):
        parsed = parse_datetime_text(row.get(key))
        if parsed:
            return parsed
    return None


def row_url(row: dict[str, Any]) -> str:
    return first_string(row.get("source_url"), row.get("url"), row.get("link"), row.get("original_url"))


def row_account(row: dict[str, Any]) -> str:
    return first_string(
        row.get("account_name"),
        row.get("source_account_name"),
        row.get("account_nickname"),
        row.get("account_key"),
        row.get("account"),
    )


def row_source_hash(row: dict[str, Any]) -> str:
    explicit = first_string(row.get("source_url_hash"), row.get("source_hash"), row.get("url_hash"))
    if explicit:
        return explicit
    url = row_url(row)
    return stable_hash(url) if url else ""


def hashes_from_text(value: Any) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    return [match.group(1).lower() for match in HASH16_RE.finditer(value)]


def trusted_hashes(value: Any, key_hint: str = "") -> list[str]:
    key = str(key_hint or "").strip().lower()
    if isinstance(value, dict):
        hashes: list[str] = []
        for child_key, child in value.items():
            hashes.extend(trusted_hashes(child, child_key))
        return hashes
    if isinstance(value, list):
        hashes = []
        for child in value:
            hashes.extend(trusted_hashes(child, key_hint))
        return hashes
    if key not in PACKAGE_HASH_FIELD_HINTS:
        return []
    return hashes_from_text(value)


def package_hashes(api_dir: Path) -> set[str]:
    payload = read_json(api_dir / "current.json")
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError(f"current.json has no item list: {api_dir / 'current.json'}")

    hashes: set[str] = set()

    def walk(value: Any, key_hint: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key_hint)
        elif isinstance(value, str):
            for source_hash in trusted_hashes(value, key_hint):
                hashes.add(source_hash)

    walk(items)
    source_map_path = api_dir / "source_actions" / "source_url_map.json"
    if source_map_path.exists():
        source_map = read_json(source_map_path)
        sources = source_map.get("sources") if isinstance(source_map, dict) else {}
        if isinstance(sources, dict):
            for key, value in sources.items():
                for source_hash in hashes_from_text(key):
                    hashes.add(source_hash)
                walk(value)
    return {value.lower() for value in hashes if value}


def repair_report_paths(api_dir: Path, extra_roots: list[Path] | None = None, explicit_reports: list[Path] | None = None) -> list[Path]:
    candidates: list[Path] = []

    def add_report_paths(root: Path) -> None:
        for filename in REPAIR_REPORT_FILENAMES:
            candidates.append(root / filename)
        if root.exists() and root.is_dir():
            candidates.extend(sorted(root.glob("release_conflict_repair_history_*.json")))

    add_report_paths(api_dir)
    for root in extra_roots or []:
        add_report_paths(root)
    for report in explicit_reports or []:
        candidates.append(report)
    manifest_path = api_dir / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = read_json(manifest_path)
        except Exception:
            manifest = {}
        if isinstance(manifest, dict):
            nested_dirs: list[Any] = [
                manifest.get("source_incremental_api_dir"),
            ]
            incremental_merge = manifest.get("incremental_merge")
            if isinstance(incremental_merge, dict):
                nested_dirs.append(incremental_merge.get("incremental_api_dir"))
            for value in nested_dirs:
                if not isinstance(value, str) or not value.strip():
                    continue
                nested = Path(value.strip())
                if not nested.is_absolute():
                    nested = (api_dir / nested).resolve()
                add_report_paths(nested)

    seen: set[Path] = set()
    out: list[Path] = []
    for path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.exists() and path.is_file():
            out.append(path)
    return out


def repair_report_dispositions(
    api_dir: Path,
    *,
    extra_roots: list[Path] | None = None,
    explicit_reports: list[Path] | None = None,
) -> tuple[dict[str, str], list[str]]:
    dispositions: dict[str, str] = {}
    paths = repair_report_paths(api_dir, extra_roots=extra_roots, explicit_reports=explicit_reports)
    for path in paths:
        try:
            payload = read_json(path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for field in REPAIR_DISPOSITION_ROW_FIELDS:
            rows = payload.get(field)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                hashes = set(trusted_hashes(row))
                for source_hash in row.get("removed_source_hashes") or []:
                    hashes.update(hashes_from_text(source_hash))
                reason = first_string(
                    row.get("reason"),
                    row.get("disposition_reason"),
                    row.get("note"),
                    field,
                )
                if not reason:
                    reason = field
                for source_hash in sorted(hashes):
                    dispositions.setdefault(source_hash.lower(), f"release_repair:{reason[:80]}")
    return dispositions, [str(path) for path in paths]


def pack_dir_from_api(api_dir: Path) -> Path | None:
    for name in ("manifest.json", "current.json"):
        path = api_dir / name
        if not path.exists():
            continue
        try:
            payload = read_json(path)
        except Exception:
            continue
        candidates: list[Any] = []
        if isinstance(payload, dict):
            candidates.extend(
                [
                    payload.get("source_pack_dir"),
                    payload.get("pack_dir"),
                    payload.get("recommendation_pack_dir"),
                ]
            )
            manifest = payload.get("manifest")
            if isinstance(manifest, dict):
                candidates.extend(
                    [
                        manifest.get("source_pack_dir"),
                        manifest.get("pack_dir"),
                        manifest.get("recommendation_pack_dir"),
                    ]
                )
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            pack_dir = Path(candidate.strip())
            if not pack_dir.is_absolute():
                pack_dir = (api_dir / pack_dir).resolve()
            if pack_dir.exists():
                return pack_dir
    return None


def row_accounted_disposition(row: dict[str, Any], *, source_name: str = "") -> str:
    if row.get("publish_blocked") is True:
        return "publish_blocked"
    if row.get("include_in_activity_feed") is False:
        return "include_in_activity_feed_false"

    for field in ("poster_vl_status", "status", "verdict", "publish_status", "content_type"):
        value = first_string(row.get(field)).casefold()
        if value in ACCOUNTED_STATUS_VALUES:
            return f"{field}:{value}"

    flags: list[str] = []
    for field in (
        "review_flags",
        "quality_flags",
        "llm_review_flags",
        "risk_flags",
        "filter_flags",
        "block_flags",
    ):
        flags.extend(collect_strings(row.get(field)))
    for field in ("poster_selection_evidence", "poster_vl_evidence", "vl_evidence"):
        nested = row.get(field)
        if isinstance(nested, dict):
            flags.extend(collect_strings(nested.get("risk_flags")))
            flags.extend(collect_strings(nested.get("review_flags")))
    for flag in flags:
        normalized = str(flag).strip().casefold()
        if normalized in ACCOUNTED_REVIEW_FLAGS:
            return f"review_flag:{normalized}"

    for field in DISPOSITION_FIELDS:
        value = first_string(row.get(field))
        if not value:
            continue
        normalized = value.casefold()
        if normalized in {"keep", "keep_in_window", "ready", "accepted", "published"}:
            continue
        return f"{field}:{value[:80]}"

    if "review" in source_name and row.get("poster_vl_status") == "not_event":
        return "review_candidate:not_event"
    return ""


def package_dispositions(
    api_dir: Path,
    *,
    extra_repair_roots: list[Path] | None = None,
    explicit_repair_reports: list[Path] | None = None,
) -> tuple[dict[str, str], str, list[str]]:
    pack_dir = pack_dir_from_api(api_dir)
    repair_dispositions, repair_paths = repair_report_dispositions(
        api_dir,
        extra_roots=extra_repair_roots,
        explicit_reports=explicit_repair_reports,
    )
    if not pack_dir:
        return repair_dispositions, "", repair_paths

    dispositions: dict[str, str] = dict(repair_dispositions)
    for filename in (
        "weekly_activity_recommendation_candidates.jsonl",
        "weekly_activity_recommendation_review_candidates.jsonl",
    ):
        path = pack_dir / filename
        if not path.exists():
            continue
        try:
            rows = read_jsonl(path)
        except Exception:
            continue
        for row in rows:
            source_hash = row_source_hash(row).lower()
            if not source_hash:
                continue
            reason = row_accounted_disposition(row, source_name=filename)
            if not reason:
                continue
            source_hashes = {source_hash}
            source_hashes.update(value.lower() for value in trusted_hashes(row))
            for candidate_hash in source_hashes:
                dispositions.setdefault(candidate_hash, reason)
    return dispositions, str(pack_dir), repair_paths


def classify_row(row: dict[str, Any], *, week_start: date, window_end: date, source_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    title = first_string(row.get("title"), row.get("source_title"))
    post_date = parse_date_text(first_string(row.get("post_date"), row.get("publish_time_iso"), row.get("publish_time")))
    search_blob = row_search_blob(row)
    title_event_date = parse_title_date(title, base_year=week_start.year, post_date=post_date)
    event_date = title_event_date
    if not event_date and search_blob != title:
        body_event_date = parse_title_date(search_blob, base_year=week_start.year, post_date=post_date)
        # Sanji digests often include the WeChat publish timestamp. Do not turn
        # that timestamp into a required event date when the title itself has no
        # concrete date signal.
        if not (body_event_date and post_date and body_event_date == post_date and body_date_looks_like_publish_timestamp(search_blob)):
            event_date = body_event_date
    reasons: list[str] = []
    if not row_url(row):
        reasons.append("missing_source_url")
    if not title:
        reasons.append("missing_title")
    policy_reason = source_policy_exclude_reason(row, source_policy or {})
    if policy_reason:
        reasons.append(policy_reason)
    if PARENT_OVERVIEW_RE.search(title):
        reasons.append("parent_overview_excluded")
    if DATE_RANGE_RE.search(title) and re.search(r"weekly|schedule|日程|安排|一览|预览|calendar", title, re.I):
        reasons.append("parent_overview_excluded")
    if NON_EVENT_RE.search(title):
        reasons.append("non_event_notice_excluded")
    if not event_date:
        reasons.append("no_current_future_event_date_signal")
    elif not (week_start <= event_date <= window_end):
        reasons.append("outside_release_window")
    if title and not EVENT_SIGNAL_RE.search(search_blob or title):
        reasons.append("weak_event_signal")
    include = not reasons
    return {
        "include": include,
        "title": title,
        "account": row_account(row),
        "source_url": row_url(row),
        "source_hash": row_source_hash(row),
        "post_date": post_date.isoformat() if post_date else "",
        "event_date": event_date.isoformat() if event_date else "",
        "exclude_reasons": reasons,
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue).resolve()
    api_dir = Path(args.api_dir).resolve()
    report_path = Path(args.report).resolve()
    week_start = datetime.strptime(args.week_start, "%Y-%m-%d").date()
    window_end = week_start + timedelta(days=max(0, args.window_days - 1))

    rows = read_jsonl(queue_path)
    hashes = package_hashes(api_dir)
    extra_repair_roots = [report_path.parent]
    if queue_path.parent.name == "sanji_source_snapshot":
        extra_repair_roots.append(queue_path.parent.parent)
    dispositions, disposition_pack_dir, disposition_repair_paths = package_dispositions(
        api_dir,
        extra_repair_roots=extra_repair_roots,
        explicit_repair_reports=[Path(value).resolve() for value in getattr(args, "repair_report", []) or []],
    )
    source_policy = load_source_policy(Path(args.source_policy) if args.source_policy else None)
    post_times = [value for value in (row_post_datetime(row) for row in rows) if value]
    queue_max_post_time = max(post_times) if post_times else None
    now_time = parse_datetime_text(args.now) if args.now else datetime.now()
    queue_staleness_hours: float | None = None
    if queue_max_post_time:
        queue_staleness_hours = max(0.0, (now_time - queue_max_post_time).total_seconds() / 3600.0)
    candidates: list[dict[str, Any]] = []
    excluded = Counter()
    for row in rows:
        classified = classify_row(row, week_start=week_start, window_end=window_end, source_policy=source_policy)
        if classified["include"]:
            source_hash = classified["source_hash"].lower()
            classified["in_package"] = source_hash in hashes
            classified["accounted_by_disposition"] = False
            classified["disposition_reason"] = ""
            if not classified["in_package"] and source_hash in dispositions:
                classified["accounted_by_disposition"] = True
                classified["disposition_reason"] = dispositions[source_hash]
            candidates.append(classified)
        else:
            for reason in classified["exclude_reasons"]:
                excluded[reason] += 1

    missing = [
        row
        for row in candidates
        if not row.get("in_package") and not row.get("accounted_by_disposition")
    ]
    missing_by_account = Counter(row["account"] for row in missing)
    present_by_account = Counter(row["account"] for row in candidates if row.get("in_package"))
    disposition_rows = [row for row in candidates if row.get("accounted_by_disposition")]
    disposition_by_reason = Counter(row["disposition_reason"] for row in disposition_rows)
    max_missing = max(0, args.max_missing)
    min_candidate_event_like = max(0, args.min_candidate_event_like)
    max_queue_staleness_hours = max(0.0, args.max_queue_staleness_hours)
    candidate_floor_ok = len(candidates) >= min_candidate_event_like
    freshness_ok = True
    if max_queue_staleness_hours > 0:
        freshness_ok = queue_staleness_hours is not None and queue_staleness_hours <= max_queue_staleness_hours
    failure_reasons: list[str] = []
    if not freshness_ok:
        failure_reasons.append("sanji_queue_stale")
    if not candidate_floor_ok:
        failure_reasons.append("sanji_candidate_floor")
    if len(missing) > max_missing:
        failure_reasons.append("sanji_queue_package_gap")
    ok = not failure_reasons
    report = {
        "schema_version": SCHEMA_VERSION,
        "ok": ok,
        "decision": "sanji_queue_package_gap_gate_pass" if ok else f"blocked_on_{failure_reasons[0]}",
        "queue": str(queue_path),
        "api_dir": str(api_dir),
        "week_start": week_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_days": args.window_days,
        "max_missing": max_missing,
        "source_policy_path": source_policy.get("path", ""),
        "disposition_source_pack_dir": disposition_pack_dir,
        "disposition_repair_report_paths": disposition_repair_paths,
        "queue_row_count": len(rows),
        "queue_max_post_time": queue_max_post_time.isoformat() if queue_max_post_time else "",
        "queue_staleness_hours": round(queue_staleness_hours, 3) if queue_staleness_hours is not None else None,
        "max_queue_staleness_hours": max_queue_staleness_hours,
        "queue_freshness_ok": freshness_ok,
        "candidate_event_like_row_count": len(candidates),
        "min_candidate_event_like": min_candidate_event_like,
        "candidate_floor_ok": candidate_floor_ok,
        "matched_row_count": len(candidates) - len(missing),
        "package_matched_row_count": len([row for row in candidates if row.get("in_package")]),
        "disposition_accounted_row_count": len(disposition_rows),
        "disposition_by_reason": dict(disposition_by_reason.most_common()),
        "missing_row_count": len(missing),
        "failure_reasons": failure_reasons,
        "affected_account_count": len(missing_by_account),
        "missing_by_account": dict(missing_by_account.most_common()),
        "present_by_account": dict(present_by_account.most_common()),
        "excluded_reason_counts": dict(excluded.most_common()),
        "disposition_accounted_rows": disposition_rows[:100],
        "missing_rows": missing[:200],
        "sample_candidates": candidates[:50],
        "rule": {
            "overview_parent_policy": "club overview/month/week/holiday parent rows are excluded here and should render only through club_overviews venue-page data",
            "single_event_policy": "current/future single-event-looking Sanji rows must be represented by source hash in current_release before backend/frontend upload",
            "old_pipeline_boundary": "docker_exporter/17300 queues are not accepted as default daily source after Sanji migration",
        },
    }
    write_json(report_path, report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", required=True, help="Sanji weekly-compatible latest_queue.jsonl.")
    parser.add_argument("--api-dir", required=True, help="Weekly API package directory containing current.json.")
    parser.add_argument("--report", required=True, help="Output JSON report path.")
    parser.add_argument("--week-start", required=True, help="Release window start YYYY-MM-DD.")
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--max-missing", type=int, default=0)
    parser.add_argument("--min-candidate-event-like", type=int, default=0)
    parser.add_argument("--max-queue-staleness-hours", type=float, default=0.0)
    parser.add_argument("--now", default="", help="Override current time for deterministic tests.")
    parser.add_argument("--source-policy", default=str(DEFAULT_SOURCE_POLICY))
    parser.add_argument("--repair-report", action="append", default=[], help="Additional release repair report JSON path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = audit(args)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "candidate_event_like_row_count": report["candidate_event_like_row_count"],
                "queue_max_post_time": report["queue_max_post_time"],
                "queue_staleness_hours": report["queue_staleness_hours"],
                "queue_freshness_ok": report["queue_freshness_ok"],
                "candidate_floor_ok": report["candidate_floor_ok"],
                "missing_row_count": report["missing_row_count"],
                "affected_account_count": report["affected_account_count"],
                "report": str(Path(args.report).resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
