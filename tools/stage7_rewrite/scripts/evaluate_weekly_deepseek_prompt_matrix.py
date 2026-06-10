#!/usr/bin/env python3
"""Evaluate DeepSeek prompt/model combinations for weekly event extraction.

This script is report-only. It reads current mini-program release data and
weekly recommendation pack artifacts, calls DeepSeek for a bounded sample
matrix, scores the outputs against source-grounded heuristics, and writes
reports. It does not modify release data, CloudRun data, queues, or databases.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


DEFAULT_ENDPOINT = "https://api.deepseek.com"
DEFAULT_CURRENT = Path("services/weekly_activity_cloudrun/data/current_release/current.json")
DEFAULT_PACK = Path(
    r"D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_RECOMMENDATION_PACK_AGGREGATE_20260517"
)
DEFAULT_OUT = Path("tools/stage7_rewrite/reports/weekly_deepseek_prompt_matrix_20260518")
DEFAULT_WINDOW_START = "2026-05-18"
DEFAULT_WINDOW_DAYS = 15

MODEL_MATRIX = (
    ("flash_no_thinking", "deepseek-v4-flash", "disabled"),
    ("flash_thinking", "deepseek-v4-flash", "enabled"),
    ("pro_no_thinking", "deepseek-v4-pro", "disabled"),
    ("pro_thinking", "deepseek-v4-pro", "enabled"),
)

TEMPERATURE_MATRIX = (0.0, 0.1)

PROMPT_VARIANTS = (
    "baseline_v1",
    "yellowpage_strict_v2",
    "yellowpage_gate_v3",
    "keyword_squeeze_v4",
    "keyword_gate_v5",
)

LINEUP_UNCERTAIN_TEXT = "点击海报跳转公众号原文查看"

TICKET_KEYWORDS = (
    "票价",
    "门票",
    "预售",
    "早鸟",
    "现场",
    "双人",
    "入场",
    "免费",
    "免票",
    "售票",
    "ticket",
    "tickets",
    "entry",
    "door",
    "cover",
)

NON_TICKET_PRICE_TERMS = ("酒水", "drink", "drinks", "cocktail", "鸡尾酒", "啤酒", "套餐", "杯")

FREE_ENTRY_RE = re.compile(
    r"(?:(?:\d{1,2}\s*(?:am|pm)|\d{1,2}[:：]\d{2}|凌晨\s*\d{1,2}\s*点)\s*(?:后|以后|之后).{0,12}(?:免费|免票|free)(?:入场|admission|entry)?|"
    r"(?:免费|免票|free).{0,12}(?:入场|entry|admission))",
    re.I,
)

PRICE_AMOUNT_RE = re.compile(
    r"(?:[¥￥][ \t]*\d{1,4}(?:\.\d{1,2})?|\d{1,4}(?:\.\d{1,2})?[ \t]*(?:[¥￥]|元|rmb|RMB|块))"
)

THREE_AM_PRICE_RE = re.compile(r"(?:[¥￥][ \t]*3(?:\.0{1,2})?|(?<!\d)3(?:\.0{1,2})?[ \t]*(?:元|rmb|RMB|块))")


def squash(value: Any, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] if limit else text


def normalize_key(value: Any) -> str:
    text = squash(value).lower()
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[|｜:：·•,，。!！?？'\"“”‘’\[\]【】()（）/\\_-]+", "", text)
    return text


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
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
            if limit and len(rows) >= limit:
                break
    return rows


def load_current_items(path: Path) -> list[dict[str, Any]]:
    data = read_json(path)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [row for row in data["items"] if isinstance(row, dict)]
    return []


def _year_from_hint(*values: Any, default: int = 2026) -> int:
    for value in values:
        match = re.search(r"(20\d{2})", str(value or ""))
        if match:
            return int(match.group(1))
    return default


def _safe_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_explicit_dates(text: Any, *, year_hint: Any = None, default_year: int = 2026) -> list[str]:
    """Extract explicit calendar dates from titles/evidence.

    The weekly pipeline bug class is date-shifting, so this intentionally
    handles the compact formats common in WeChat event titles.
    """
    source = str(text or "")
    year = _year_from_hint(year_hint, source, default=default_year)
    dates: list[str] = []

    for match in re.finditer(r"(?<!\d)(20\d{2})[./\-\u5e74](\d{1,2})[./\-\u6708](\d{1,2})(?:\u65e5|\u53f7)?", source):
        value = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if value:
            dates.append(value)

    month_day_patterns = (
        r"(?<!\d)(\d{1,2})[./](\d{1,2})(?!\d)",
        r"(?<!\d)(\d{1,2})\s*\u6708\s*(\d{1,2})\s*(?:\u65e5|\u53f7)?",
    )
    for pattern in month_day_patterns:
        for match in re.finditer(pattern, source):
            month = int(match.group(1))
            day = int(match.group(2))
            value = _safe_date(year, month, day)
            if value:
                dates.append(value)

    for match in re.finditer(r"(?<!\d)(\d{1,2})[./](\d{1,2})\s*[-\u2013\u2014~]\s*(\d{1,2})[./](\d{1,2})(?!\d)", source):
        start_value = _safe_date(year, int(match.group(1)), int(match.group(2)))
        end_value = _safe_date(year, int(match.group(3)), int(match.group(4)))
        for value in (start_value, end_value):
            if value:
                dates.append(value)

    for match in re.finditer(r"(?<!\d)(\d{1,2})[./](\d{1,2})\s*[-\u2013\u2014~]\s*(\d{1,2})(?![./\d])", source):
        month = int(match.group(1))
        start_day = int(match.group(2))
        end_day = int(match.group(3))
        for day in (start_day, end_day):
            value = _safe_date(year, month, day)
            if value:
                dates.append(value)

    seen: set[str] = set()
    result: list[str] = []
    for value in dates:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


NOISE_TERMS = (
    "介绍",
    "成员",
    "见证",
    "面向",
    "欢迎",
    "一起",
    "活动",
    "演出",
    "工作坊",
    "主理人",
    "经理人",
    "展开合作",
    "检票",
    "售票",
    "现场的方式",
    "音乐制作人",
    "生活之中",
    "从业",
    "俱乐部",
    "公众号",
)


def is_noisy_lineup_value(value: Any) -> bool:
    text = squash(value)
    if not text:
        return False
    if len(text) >= 18 and re.search(r"[\u4e00-\u9fff]", text):
        return True
    if any(term in text for term in NOISE_TERMS):
        return True
    if re.search(r"[。；;，,].{4,}", text):
        return True
    return False


def has_lineup_noise(values: Any) -> bool:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return False
    return any(is_noisy_lineup_value(value) for value in values)


def _field_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [squash(v) for v in value if squash(v)]
    if squash(value):
        return [squash(value)]
    return []


def _has_ticket_context(text: Any) -> bool:
    source = squash(text).lower()
    return any(keyword.lower() in source for keyword in TICKET_KEYWORDS)


def _visible_ticket_amounts(text: Any) -> list[str]:
    source = str(text or "")
    values: list[str] = []
    for match in PRICE_AMOUNT_RE.finditer(source):
        context = source[max(0, match.start() - 12) : min(len(source), match.end() + 12)]
        if any(term.lower() in context.lower() for term in NON_TICKET_PRICE_TERMS):
            continue
        values.append(squash(match.group(0)))
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = re.sub(r"\D", "", value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _amount_digits(values: list[str]) -> set[str]:
    digits: set[str] = set()
    for value in values:
        for match in re.finditer(r"\d{1,4}(?:\.\d{1,2})?", value):
            raw = match.group(0)
            if raw:
                digits.add(raw.rstrip("0").rstrip("."))
    return digits


def _free_entry_clauses(text: Any) -> list[str]:
    source = str(text or "")
    return [squash(match.group(0)) for match in FREE_ENTRY_RE.finditer(source)]


def _ticket_values_from_events(events: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for event in events:
        values.extend(_field_list(event.get("price_text")))
        values.extend(_field_list(event.get("ticketing")))
        values.extend(_field_list(event.get("ticket_text")))
    return values


def _field_evidence_values(parsed: Any) -> list[str]:
    if not isinstance(parsed, dict):
        return []
    values: list[str] = []
    field_evidence = parsed.get("field_evidence")
    if isinstance(field_evidence, dict):
        for value in field_evidence.values():
            values.extend(_field_list(value))
    elif isinstance(field_evidence, list):
        values.extend(_field_list(field_evidence))
    keyword_hits = parsed.get("keyword_hits")
    if isinstance(keyword_hits, dict):
        for value in keyword_hits.values():
            values.extend(_field_list(value))
    elif isinstance(keyword_hits, list):
        values.extend(_field_list(keyword_hits))
    return values


def http_timeout_value(timeout: int | float | None) -> int | float | None:
    """Map CLI timeout value to httpx timeout.

    A value <= 0 means no application-level HTTP timeout for long-run evals.
    """
    if timeout is None:
        return None
    return None if float(timeout) <= 0 else timeout


def _candidate_lookup(candidates: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_title: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    for row in candidates:
        title_key = normalize_key(row.get("title"))
        if title_key and title_key not in by_title:
            by_title[title_key] = row
        url = squash(row.get("source_url"))
        if url and url not in by_url:
            by_url[url] = row
    return by_title, by_url


def _source_text(*parts: Any, limit: int = 9000) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, list):
            chunks.extend(squash(v) for v in part if squash(v))
        elif isinstance(part, dict):
            chunks.append(json.dumps(part, ensure_ascii=False))
        elif squash(part):
            chunks.append(squash(part))
    return "\n".join(chunks)[:limit]


def build_sample(
    *,
    category: str,
    source_id: str,
    item: dict[str, Any] | None = None,
    candidate: dict[str, Any] | None = None,
    ocr: dict[str, Any] | None = None,
    aggregate: dict[str, Any] | None = None,
    window_start: str = DEFAULT_WINDOW_START,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    item = item or {}
    candidate = candidate or {}
    ocr = ocr or {}
    aggregate = aggregate or {}
    title = squash(item.get("title") or candidate.get("title") or aggregate.get("parent_title"))
    post_date = item.get("post_date") or candidate.get("post_date") or item.get("source_published_at")
    text = _source_text(
        title,
        item.get("event_date_text"),
        candidate.get("event_date_text"),
        candidate.get("date_text"),
        candidate.get("event_time_text"),
        item.get("event_time_text"),
        item.get("price_text"),
        candidate.get("price_text"),
        item.get("ticketing"),
        candidate.get("ticketing"),
        item.get("evidence"),
        candidate.get("evidence"),
        ocr,
        aggregate,
    )
    title_dates = extract_explicit_dates(title, year_hint=post_date)
    evidence_dates = extract_explicit_dates(text, year_hint=post_date)
    expected_dates = title_dates or evidence_dates[:3]

    start = date.fromisoformat(window_start)
    end = start + timedelta(days=window_days - 1)
    expected_out_of_window = bool(expected_dates) and not any(
        start <= date.fromisoformat(value) <= end for value in expected_dates
    )

    expected_venue = squash(item.get("venue_name") or candidate.get("venue") or item.get("venue"))
    expected_address = squash(item.get("address") or candidate.get("address"))
    expected_city = squash(item.get("city_name") or item.get("city") or candidate.get("city"))
    current_lineup = _field_list(item.get("lineup"))
    source_lineup = _field_list(candidate.get("lineup"))
    noisy_lineup_expected = has_lineup_noise(current_lineup) or has_lineup_noise(source_lineup)

    if aggregate.get("events"):
        agg_dates: list[str] = []
        for event in aggregate.get("events", []):
            agg_dates.extend(extract_explicit_dates(event.get("event_date_text") or event.get("evidence"), year_hint=post_date))
        if agg_dates:
            expected_dates = sorted(set(agg_dates))
            expected_out_of_window = not any(
                start <= date.fromisoformat(value) <= end for value in expected_dates
            )

    ticket_amounts = _visible_ticket_amounts(text)
    free_entry = _free_entry_clauses(text)
    ticket_context = _has_ticket_context(text) or bool(ticket_amounts) or bool(free_entry)

    sample_id = f"{category}:{normalize_key(source_id or title)[:28] or len(title)}"
    return {
        "sample_id": sample_id,
        "category": category,
        "title": title,
        "post_date": post_date,
        "window_start": window_start,
        "window_days": window_days,
        "current": {
            "id": item.get("id"),
            "event_date_start": item.get("event_date_start"),
            "event_date_end": item.get("event_date_end"),
            "event_time_text": item.get("event_time_text"),
            "city": item.get("city_name") or item.get("city"),
            "venue": item.get("venue_name") or item.get("venue"),
            "address": item.get("address"),
            "lineup": current_lineup,
            "lineup_display_hint": item.get("lineup_display_hint"),
            "price_text": item.get("price_text"),
        },
        "candidate": {
            "source_url": candidate.get("source_url") or item.get("source_article"),
            "event_date_text": candidate.get("event_date_text") or candidate.get("date_text"),
            "event_time_text": candidate.get("event_time_text"),
            "city": candidate.get("city"),
            "venue": candidate.get("venue"),
            "address": candidate.get("address"),
            "lineup": source_lineup,
            "genres": candidate.get("genres"),
            "price_text": candidate.get("price_text"),
            "ticketing": candidate.get("ticketing"),
            "evidence": candidate.get("evidence"),
        },
        "ocr": ocr,
        "aggregate": aggregate,
        "source_text": text,
        "expected": {
            "dates": expected_dates,
            "out_of_window": expected_out_of_window,
            "venue": expected_venue,
            "address": expected_address,
            "city": expected_city,
            "lineup_should_be_conservative": noisy_lineup_expected or not source_lineup,
            "ticket_context": ticket_context,
            "visible_ticket_amounts": ticket_amounts,
            "free_entry": free_entry,
            "qr_only_ticketing": ticket_context and not ticket_amounts and not free_entry,
        },
    }


def select_samples(
    current_items: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    ocr_summary: dict[str, Any],
    child_extracts: list[dict[str, Any]],
    *,
    limit_per_category: int,
    window_start: str,
    window_days: int,
) -> list[dict[str, Any]]:
    by_title, by_url = _candidate_lookup(candidates)
    samples: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(sample: dict[str, Any]) -> None:
        key = sample["sample_id"]
        if key in seen:
            return
        seen.add(key)
        samples.append(sample)

    date_count = 0
    for item in current_items:
        title_dates = extract_explicit_dates(item.get("title"), year_hint=item.get("post_date"))
        current_date = squash(item.get("event_date_start"))
        if title_dates and current_date and current_date not in title_dates:
            candidate = by_title.get(normalize_key(item.get("title")), {})
            add(
                build_sample(
                    category="title_date_mismatch",
                    source_id=squash(item.get("id") or item.get("title")),
                    item=item,
                    candidate=candidate,
                    window_start=window_start,
                    window_days=window_days,
                )
            )
            date_count += 1
            if date_count >= limit_per_category:
                break

    noise_count = 0
    noise_title_seen: set[str] = set()
    for row in candidates:
        if has_lineup_noise(row.get("lineup")):
            title_key = normalize_key(row.get("title"))
            if title_key in noise_title_seen:
                continue
            noise_title_seen.add(title_key)
            add(
                build_sample(
                    category="lineup_noise",
                    source_id=squash(row.get("source_url") or row.get("title")),
                    candidate=row,
                    window_start=window_start,
                    window_days=window_days,
                )
            )
            noise_count += 1
            if noise_count >= limit_per_category:
                break

    image_count = 0
    for row in ocr_summary.get("debug_samples", []) if isinstance(ocr_summary, dict) else []:
        if int(row.get("image_count") or 0) < 3:
            continue
        candidate = by_url.get(squash(row.get("source_url"))) or by_title.get(normalize_key(row.get("title")), {})
        add(
            build_sample(
                category="image_heavy",
                source_id=squash(row.get("source_url") or row.get("title")),
                candidate=candidate,
                ocr=row,
                window_start=window_start,
                window_days=window_days,
            )
        )
        image_count += 1
        if image_count >= limit_per_category:
            break

    ticket_count = 0
    ticket_title_seen: set[str] = set()
    ticket_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in candidates:
        ticket_rows.append(({}, row))
    for item in current_items:
        ticket_rows.append((item, by_title.get(normalize_key(item.get("title")), {})))
    for item, row in ticket_rows:
        text = _source_text(
            item.get("title") or row.get("title"),
            item.get("price_text"),
            row.get("price_text"),
            item.get("ticketing"),
            row.get("ticketing"),
            row.get("evidence"),
            item.get("evidence"),
        )
        if not (_has_ticket_context(text) or _visible_ticket_amounts(text) or _free_entry_clauses(text)):
            continue
        title_key = normalize_key(item.get("title") or row.get("title") or row.get("source_url"))
        if title_key in ticket_title_seen:
            continue
        ticket_title_seen.add(title_key)
        add(
            build_sample(
                category="ticketing_edge",
                source_id=squash(row.get("source_url") or item.get("id") or row.get("title") or item.get("title")),
                item=item,
                candidate=row,
                window_start=window_start,
                window_days=window_days,
            )
        )
        ticket_count += 1
        if ticket_count >= limit_per_category:
            break

    aggregate_count = 0
    for row in child_extracts:
        if int(row.get("event_count") or 0) <= 0:
            continue
        add(
            build_sample(
                category="aggregate_child",
                source_id=squash(row.get("source_url") or row.get("parent_title")),
                aggregate=row,
                window_start=window_start,
                window_days=window_days,
            )
        )
        aggregate_count += 1
        if aggregate_count >= limit_per_category:
            break

    control_count = 0
    for item in current_items:
        title_dates = extract_explicit_dates(item.get("title"), year_hint=item.get("post_date"))
        current_date = squash(item.get("event_date_start"))
        if title_dates and current_date in title_dates and item.get("venue_name") and item.get("address"):
            candidate = by_title.get(normalize_key(item.get("title")), {})
            sample = build_sample(
                    category="complete_control",
                    source_id=squash(item.get("id") or item.get("title")),
                    item=item,
                    candidate=candidate,
                    window_start=window_start,
                    window_days=window_days,
                )
            if sample["expected"]["out_of_window"]:
                continue
            add(sample)
            control_count += 1
            if control_count >= limit_per_category:
                break

    return samples


def build_system_prompt(variant: str) -> str:
    schema = (
        "只输出 JSON 对象，字段为: is_event, publish_decision, events, keyword_hits, field_evidence, notes。"
        "events 中每个对象字段为 title, event_date_start, event_date_end, "
        "event_time_text, city, venue, address, lineup, genres, price_text, "
        "evidence_quote, uncertain_fields。"
    )
    if variant == "baseline_v1":
        return (
            "你是电子音乐活动信息抽取助手。根据输入材料抽取公开活动信息。"
            "尽量给出日期、时间、城市、场地、地址、阵容、风格和票价。"
            f"{schema}"
        )
    if variant == "yellowpage_strict_v2":
        return (
            "你是公开电子音乐活动黄页抽取器，只做来源材料中明确支持的信息整理。"
            "禁止猜测、补全、编造日期、时间、地址、阵容、艺人简介或场地信息。"
            "标题或正文里出现的明确日期优先；如果日期不在给定窗口内，标记 out_of_window，"
            "不能把它平移到窗口第一天或周末。"
            "只有当文本明确写出 DJ/lineup/嘉宾/阵容，且名字和该活动直接相邻时才填 lineup；"
            "介绍性句子、职业身份、公众号说明、主理人介绍、售票/检票/合作方不能当 lineup。"
            "如果没有把握，lineup 留空，并在 uncertain_fields 写 lineup。"
            "如果文章是月度/周度/多场安排，必须拆成多个 events；每个子活动各自保留日期和证据。"
            "地址、时间拿不准就填 null，不要用场地营业时间或默认时间。"
            "每条 evidence_quote 必须是输入原文中的连续短句。"
            f"{schema}"
        )
    if variant == "yellowpage_gate_v3":
        return (
            "你是公开电子音乐活动黄页抽取器。目标不是写文案，而是生成可审核的数据。"
            "只允许使用输入材料中明确出现的信息；禁止根据常识、场地习惯、标题氛围或当前管线结果补全。"
            "publish_decision 只能是 publish、review、out_of_window、not_event 四者之一。"
            "先识别每个活动的明确日期，再和输入 target_window 比较；日期早于窗口开始或晚于窗口结束时，"
            "必须标记 out_of_window，不能发布，也不能把日期平移到今天、周末或窗口第一天。"
            "如果文章含多个子活动，拆成多个 events；只有至少一个子活动在窗口内且证据完整时才可 publish，"
            "否则 out_of_window 或 review。"
            "lineup 只接受紧邻 DJ、阵容、嘉宾、w/、with、present、live、set 等活动阵容线索的名字；"
            "传记、介绍句、合作方、主理人、售票检票、职业描述、标题碎片、公众号说明都不能进入 lineup。"
            "拿不准的 lineup、时间、地址填 null 或空数组，并在 uncertain_fields 标记。"
            "每条 evidence_quote 必须是输入材料中的连续原句，不能改写。"
            f"{schema}"
        )
    if variant == "keyword_squeeze_v4":
        return (
            "你是公开电子音乐活动黄页抽取器，任务是把推文/OCR/已抓取文本中的可验证活动信息榨干，"
            "但只允许输出来源材料明确支持的信息。不要写文案，不要根据经验补全。"
            "处理顺序必须是：1) 关键词盘点；2) 给每个候选字段找到原文证据；"
            "3) 抽取活动字段；4) 标记不确定字段与拒绝发布原因。"
            "关键词族必须覆盖："
            "日期时间=日期、时间、周五、周六、tonight、open、start、late、3am；"
            "场地地址城市=地点、地址、Venue、Location、@、Add、map；"
            "阵容=阵容、Lineup、DJ、w/、with、live、set、guest、pres.；"
            "票务=票价、门票、预售、早鸟、现场、双人、入场、免费、免票、ticket、entry、door；"
            "来源=公众号、小程序、芋圆、二维码、原文；"
            "Atlas线索=艺人/场地/主办别名只写 entity_mentions 或 notes，不能把模糊别名提升成已验证 ID。"
            "ticketing 规则：3am、03:00、凌晨3点等是时间条件，不能抽成 3 元门票；"
            "“3am 后免费入场”应作为免费入场条件，不是价格；"
            "只看到芋圆/小程序码/Click for tickets 而没有可见金额时，price_text 留 null 或空，"
            "在 uncertain_fields 标记 ticket_price；酒水/套餐/饮品价格不能当门票。"
            "早鸟、预售、现场、双人、免费条件如果原文分别写出，必须保留层级差异。"
            "lineup 只接受紧邻 DJ、阵容、嘉宾、w/、with、present、live、set 等活动阵容线索的名字；"
            "传记、介绍句、合作方、主理人、售票检票、职业描述不能进入 lineup。"
            "publish_decision 只能是 publish、review、out_of_window、not_event。"
            "每个非空字段都要能在 field_evidence 里找到原文连续短句；keyword_hits 记录命中的关键词族和原文片段。"
            f"{schema}"
        )
    if variant == "keyword_gate_v5":
        return (
            "你是公开电子音乐活动黄页抽取器。目标是生成可审核数据，不是写文案。"
            "只允许使用输入材料中明确出现的信息；禁止根据常识、场地习惯、标题氛围或当前管线结果补全。"
            "先在心里扫描关键词族，再直接输出 JSON，不要输出推理过程。关键词族包括："
            "日期/时间(日期、周五、周六、tonight、open、start、late、3am)、"
            "地点(地点、地址、Venue、Location、@、map)、"
            "阵容(Lineup、DJ、w/、with、live、set、guest、pres.)、"
            "票务(票价、门票、预售、早鸟、现场、双人、免费、免票、ticket、entry、door)、"
            "来源(公众号、小程序、芋圆、二维码、原文)。"
            "publish_decision 只能是 publish、review、out_of_window、not_event。"
            "明确日期早于/晚于 target_window 必须 out_of_window，不能平移到今天、周末或窗口第一天。"
            "多子活动必须拆成多个 events；每个子活动保留自己的日期和证据。"
            "ticketing 规则：3am、03:00、凌晨3点是时间条件，不能抽成 3 元门票；"
            "3am 后免费入场是入场规则；芋圆/小程序码/Click for tickets 无可见金额时 price_text 留空；"
            "酒水/套餐/饮品价格不能当门票；早鸟、预售、现场、双人、免费条件要分开保留。"
            "lineup 只接受紧邻 DJ/阵容/嘉宾/w/with/live/set/pres. 的名字；"
            "传记、介绍句、合作方、主理人、售票检票、职业描述不能进入 lineup。"
            "每条 evidence_quote 必须是输入材料中的连续原句；field_evidence 只填已输出字段对应的短原文，"
            "keyword_hits 最多给每个关键词族 2 个短片段，避免长篇复制。"
            "Atlas 线索只可写入 notes/entity_mentions，不能把模糊别名当已验证 ID。"
            f"{schema}"
        )
    raise ValueError(f"unknown prompt variant: {variant}")


def build_user_prompt(sample: dict[str, Any], variant: str) -> str:
    payload = {
        "task": "extract_weekly_public_event_for_mini_program",
        "prompt_variant": variant,
        "target_window": {
            "start": sample["window_start"],
            "days": sample["window_days"],
        },
        "sample_category": sample["category"],
        "article_title": sample["title"],
        "publish_date": sample.get("post_date"),
        "current_pipeline_output_for_reference_only": sample.get("current"),
        "candidate_source_fields": sample.get("candidate"),
        "ocr_or_image_download_summary": sample.get("ocr"),
        "aggregate_child_context": sample.get("aggregate"),
        "source_text": sample.get("source_text"),
        "important": [
            "当前管线结果只作对照，可能是错的，不要盲从。",
            "如果只能看到大量图片但文本/OCR不足，标记 review，不要猜。",
            "输出 JSON，禁止解释。",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def extract_json_object(text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("empty response")
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    if raw[0] in "[{":
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    start_positions = [idx for idx in (raw.find("{"), raw.find("[")) if idx >= 0]
    if not start_positions:
        raise ValueError("no json start")
    start = min(start_positions)
    opener = raw[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : idx + 1])
    raise ValueError("unterminated json")


def _events_from_response(parsed: Any) -> list[dict[str, Any]]:
    if isinstance(parsed, list):
        return [row for row in parsed if isinstance(row, dict)]
    if not isinstance(parsed, dict):
        return []
    events = parsed.get("events")
    if isinstance(events, list):
        return [row for row in events if isinstance(row, dict)]
    if any(key in parsed for key in ("event_date_start", "venue", "lineup")):
        return [parsed]
    return []


def _response_decision(parsed: Any) -> str:
    if isinstance(parsed, dict):
        return squash(parsed.get("publish_decision")).lower()
    return ""


def _text_contains_rough(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    return normalize_key(needle) in normalize_key(haystack)


def score_response(sample: dict[str, Any], parsed: Any, prompt_text: str = "") -> dict[str, Any]:
    events = _events_from_response(parsed)
    response_text = json.dumps(parsed, ensure_ascii=False) if parsed is not None else ""
    expected = sample.get("expected", {})
    expected_dates = set(expected.get("dates") or [])
    returned_dates: set[str] = set()
    for event in events:
        for key in ("event_date_start", "event_date_end"):
            value = squash(event.get(key))
            if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value):
                returned_dates.add(value)
        returned_dates.update(extract_explicit_dates(event.get("event_date_text")))

    if expected_dates:
        date_score = 1.0 if returned_dates & expected_dates else 0.0
    else:
        date_score = 1.0 if not returned_dates else 0.6

    decision = _response_decision(parsed)
    if expected.get("out_of_window"):
        window_score = 1.0 if decision in {"out_of_window", "review", "not_event", "no_publish", "skip", "reject", "drop"} else 0.0
    else:
        window_score = 1.0 if decision not in {"out_of_window", "not_event"} else 0.0

    lineup_values: list[str] = []
    for event in events:
        lineup_values.extend(_field_list(event.get("lineup")))
    noisy_lineup = has_lineup_noise(lineup_values)
    if expected.get("lineup_should_be_conservative"):
        lineup_score = 1.0 if not lineup_values or not noisy_lineup else 0.0
    else:
        unsupported = [
            value
            for value in lineup_values
            if value and not _text_contains_rough(sample.get("source_text", ""), value)
        ]
        lineup_score = 1.0 if not noisy_lineup and not unsupported else 0.2

    evidence_values: list[str] = []
    for event in events:
        evidence_values.extend(_field_list(event.get("evidence_quote")))
    source_blob = "\n".join([sample.get("source_text", ""), prompt_text])
    if evidence_values:
        evidence_score = 1.0 if all(value in source_blob for value in evidence_values) else 0.0
    else:
        evidence_score = 0.4

    field_evidence_values = _field_evidence_values(parsed)
    if field_evidence_values:
        keyword_evidence_score = 1.0 if all(_text_contains_rough(source_blob, value) for value in field_evidence_values) else 0.0
    elif evidence_values:
        keyword_evidence_score = 0.6
    else:
        keyword_evidence_score = 0.3

    venue_needles = [expected.get("venue"), expected.get("address"), expected.get("city")]
    venue_needles = [squash(value) for value in venue_needles if squash(value)]
    if venue_needles:
        venue_score = 1.0 if any(_text_contains_rough(response_text, value) for value in venue_needles) else 0.0
    else:
        venue_score = 1.0

    if sample.get("category") == "aggregate_child":
        source_event_count = int((sample.get("aggregate") or {}).get("event_count") or 0)
        aggregate_score = 1.0 if len(events) >= min(source_event_count, 2) else 0.0
    else:
        aggregate_score = 1.0

    ticket_values = _ticket_values_from_events(events)
    ticket_text = "\n".join(ticket_values)
    returned_ticket_amounts = _visible_ticket_amounts(ticket_text)
    expected_ticket_amounts = _field_list(expected.get("visible_ticket_amounts"))
    expected_ticket_digits = _amount_digits(expected_ticket_amounts)
    returned_ticket_digits = _amount_digits(returned_ticket_amounts)
    expected_free = bool(expected.get("free_entry"))
    returned_free = bool(re.search(r"(免费|免票|free)", ticket_text, re.I))
    source_has_three_am = bool(re.search(r"(?:\b3\s*am\b|03[:：]00|凌晨\s*3\s*点)", sample.get("source_text", ""), re.I))
    false_three_am_price = (
        source_has_three_am
        and bool(THREE_AM_PRICE_RE.search(ticket_text))
        and "3" not in expected_ticket_digits
    )
    if false_three_am_price:
        ticket_score = 0.0
    elif expected_ticket_digits:
        amount_ok = bool(returned_ticket_digits & expected_ticket_digits)
        free_ok = not expected_free or returned_free
        if amount_ok and free_ok:
            ticket_score = 1.0
        elif amount_ok:
            ticket_score = 0.75
        elif not ticket_values:
            ticket_score = 0.25
        else:
            ticket_score = 0.1
    elif expected_free:
        ticket_score = 1.0 if returned_free and not returned_ticket_amounts else 0.2 if returned_ticket_amounts else 0.4
    elif expected.get("qr_only_ticketing"):
        ticket_score = 1.0 if not returned_ticket_amounts else 0.0
    elif expected.get("ticket_context"):
        ticket_score = 0.8 if not returned_ticket_amounts else 1.0
    else:
        ticket_score = 1.0 if not returned_ticket_amounts else 0.2

    total = (
        date_score * 0.22
        + window_score * 0.15
        + lineup_score * 0.16
        + evidence_score * 0.12
        + venue_score * 0.1
        + aggregate_score * 0.06
        + ticket_score * 0.12
        + keyword_evidence_score * 0.07
    )
    if expected.get("out_of_window") and window_score == 0.0:
        total = min(total, 0.55)
    return {
        "total_score": round(total, 4),
        "date_score": date_score,
        "window_score": window_score,
        "lineup_score": lineup_score,
        "evidence_score": evidence_score,
        "venue_score": venue_score,
        "aggregate_score": aggregate_score,
        "ticket_score": ticket_score,
        "keyword_evidence_score": keyword_evidence_score,
        "event_count": len(events),
        "expected_dates": sorted(expected_dates),
        "returned_dates": sorted(returned_dates),
        "lineup_values": lineup_values[:12],
        "ticket_values": ticket_values[:12],
        "expected_ticket_amounts": expected_ticket_amounts,
        "returned_ticket_amounts": returned_ticket_amounts,
        "false_three_am_price": false_three_am_price,
        "decision": decision,
    }


def deepseek_chat(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    thinking: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int | None,
    max_tokens: int,
    retries: int,
    temperature: float,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "thinking": {"type": thinking},
    }
    if thinking != "enabled":
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_error: dict[str, Any] = {}
    started = time.perf_counter()
    with httpx.Client() as client:
        for attempt in range(retries + 1):
            try:
                response = client.post(
                    f"{endpoint.rstrip('/')}/v1/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=http_timeout_value(timeout),
                )
                if response.status_code in {429, 500, 503} and attempt < retries:
                    time.sleep(min(20, 2**attempt * 3))
                    continue
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                return {
                    "ok": True,
                    "content": message.get("content") or "",
                    "usage": data.get("usage") or {},
                    "model_returned": data.get("model"),
                    "latency_sec": round(time.perf_counter() - started, 3),
                    "attempt": attempt + 1,
                }
            except Exception as exc:  # noqa: BLE001 - report-only diagnostics
                response = getattr(exc, "response", None)
                last_error = {
                    "type": type(exc).__name__,
                    "status": getattr(response, "status_code", None),
                    "message": str(exc)[:300],
                    "body": (getattr(response, "text", "") or "")[:500],
                }
                if attempt < retries:
                    time.sleep(min(20, 2**attempt * 3))
    return {
        "ok": False,
        "error": last_error,
        "latency_sec": round(time.perf_counter() - started, 3),
    }


def make_call_task(
    sample: dict[str, Any],
    *,
    prompt_variant: str,
    matrix_name: str,
    model: str,
    thinking: str,
    temperature: float,
) -> dict[str, Any]:
    system_prompt = build_system_prompt(prompt_variant)
    user_prompt = build_user_prompt(sample, prompt_variant)
    return {
        "sample_id": sample["sample_id"],
        "category": sample["category"],
        "prompt_variant": prompt_variant,
        "matrix_name": matrix_name,
        "model": model,
        "thinking": thinking,
        "temperature": temperature,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


def run_task(task: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    result = deepseek_chat(
        endpoint=args.endpoint,
        api_key=args.api_key,
        model=task["model"],
        thinking=task["thinking"],
        system_prompt=task["system_prompt"],
        user_prompt=task["user_prompt"],
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        retries=args.retries,
        temperature=float(task.get("temperature", 0.0)),
    )
    row = {key: value for key, value in task.items() if key not in {"system_prompt", "user_prompt"}}
    row.update(
        {
            "ok": result.get("ok"),
            "latency_sec": result.get("latency_sec"),
            "usage": result.get("usage") or {},
            "model_returned": result.get("model_returned"),
            "error": result.get("error"),
            "raw_content": (result.get("content") or "")[:8000],
        }
    )
    if result.get("ok"):
        try:
            parsed = extract_json_object(result.get("content") or "")
            row["json_ok"] = True
            row["parsed"] = parsed
        except Exception as exc:  # noqa: BLE001 - report parse failure
            row["json_ok"] = False
            row["parse_error"] = str(exc)[:240]
            row["parsed"] = None
    else:
        row["json_ok"] = False
        row["parsed"] = None
    return row


def summarize_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = f"{row.get('prompt_variant')}|{row.get('matrix_name')}|temp={row.get('temperature')}"
        groups.setdefault(key, []).append(row)
    summary: dict[str, Any] = {"group_count": len(groups), "groups": []}
    for key, group in sorted(groups.items()):
        scores = [float(row.get("score", {}).get("total_score", 0)) for row in group]
        usage_tokens = [
            int((row.get("usage") or {}).get("total_tokens") or 0)
            for row in group
            if isinstance(row.get("usage"), dict)
        ]
        latencies = [float(row.get("latency_sec") or 0) for row in group if row.get("latency_sec") is not None]
        summary["groups"].append(
            {
                "key": key,
                "prompt_variant": group[0].get("prompt_variant"),
                "matrix_name": group[0].get("matrix_name"),
                "model": group[0].get("model"),
                "thinking": group[0].get("thinking"),
                "temperature": group[0].get("temperature"),
                "count": len(group),
                "ok_count": sum(1 for row in group if row.get("ok")),
                "json_ok_count": sum(1 for row in group if row.get("json_ok")),
                "avg_score": round(statistics.mean(scores), 4) if scores else 0,
                "date_acc": round(statistics.mean(float(row.get("score", {}).get("date_score", 0)) for row in group), 4),
                "lineup_acc": round(statistics.mean(float(row.get("score", {}).get("lineup_score", 0)) for row in group), 4),
                "evidence_acc": round(statistics.mean(float(row.get("score", {}).get("evidence_score", 0)) for row in group), 4),
                "ticket_acc": round(statistics.mean(float(row.get("score", {}).get("ticket_score", 0)) for row in group), 4),
                "keyword_evidence_acc": round(
                    statistics.mean(float(row.get("score", {}).get("keyword_evidence_score", 0)) for row in group),
                    4,
                ),
                "avg_latency_sec": round(statistics.mean(latencies), 3) if latencies else 0,
                "total_tokens": sum(usage_tokens),
            }
        )
    summary["groups"].sort(key=lambda row: row["avg_score"], reverse=True)
    return summary


def write_markdown_report(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    lines = [
        "# Weekly DeepSeek Prompt Matrix",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- current: `{args.current}`",
        f"- pack_dir: `{args.pack_dir}`",
        f"- samples: {len({row['sample_id'] for row in rows})}",
        f"- calls: {len(rows)}",
        f"- window: {args.window_start} + {args.window_days} days",
        "",
        "## Ranking",
        "",
        "| rank | prompt | model combo | temp | calls | json ok | avg score | date | lineup | evidence | ticket | field evidence | latency | tokens |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for idx, group in enumerate(summary.get("groups", []), start=1):
        lines.append(
            "| {rank} | {prompt} | {combo} | {temp} | {count} | {json_ok}/{count} | {score:.4f} | {date:.2f} | {lineup:.2f} | {evidence:.2f} | {ticket:.2f} | {keyword:.2f} | {latency:.2f}s | {tokens} |".format(
                rank=idx,
                prompt=group["prompt_variant"],
                combo=group["matrix_name"],
                temp=group.get("temperature"),
                count=group["count"],
                json_ok=group["json_ok_count"],
                score=group["avg_score"],
                date=group["date_acc"],
                lineup=group["lineup_acc"],
                evidence=group["evidence_acc"],
                ticket=group["ticket_acc"],
                keyword=group["keyword_evidence_acc"],
                latency=group["avg_latency_sec"],
                tokens=group["total_tokens"],
            )
        )
    lines.extend(["", "## Lowest Scoring Calls", ""])
    low = sorted(rows, key=lambda row: float(row.get("score", {}).get("total_score", 0)))[:20]
    for row in low:
        score = row.get("score", {})
        lines.append(
                "- `{}` `{}` `{}` score={} date={} lineup={} ticket={} expected={} returned={} decision={} error={}".format(
                row.get("sample_id"),
                row.get("prompt_variant"),
                f"{row.get('matrix_name')} temp={row.get('temperature')}",
                score.get("total_score"),
                score.get("date_score"),
                score.get("lineup_score"),
                score.get("ticket_score"),
                score.get("expected_dates"),
                score.get("returned_dates"),
                score.get("decision"),
                row.get("error") or row.get("parse_error") or "",
            )
        )
    lines.extend(
        [
            "",
            "## Prompt Recommendation Rule",
            "",
            "- Favor the highest scoring group only if JSON compliance is 100% and date/lineup scores do not regress.",
            "- If thinking-enabled variants score higher but JSON compliance drops, keep them for audit/review lanes, not production materialization.",
            "- Prefer lower temperature when scores tie; public data extraction values repeatability over creative recall.",
            "- Keep source-grounded strict prompt rules: no date shifting, no guessed lineup, no guessed time/address.",
            "- Ticketing is only publishable when source-backed: 3am/free-entry clauses are conditions, not prices; QR-only ticketing without visible amounts stays uncertain.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def result_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            squash(row.get("sample_id")),
            squash(row.get("prompt_variant")),
            squash(row.get("matrix_name")),
            squash(row.get("temperature")),
        ]
    )


def prepare_samples(args: argparse.Namespace) -> list[dict[str, Any]]:
    current = load_current_items(args.current)
    candidates = read_jsonl(args.pack_dir / "weekly_activity_recommendation_candidates.jsonl")
    ocr_summary_path = args.pack_dir / "summary.json"
    ocr_summary = read_json(ocr_summary_path) if ocr_summary_path.exists() else {}
    child_extracts = read_jsonl(args.pack_dir / "aggregate_secondary_child_extracts.jsonl")
    return select_samples(
        current,
        candidates,
        ocr_summary,
        child_extracts,
        limit_per_category=args.limit_per_category,
        window_start=args.window_start,
        window_days=args.window_days,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--endpoint", default=os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_ENDPOINT)
    parser.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY"))
    parser.add_argument("--window-start", default=DEFAULT_WINDOW_START)
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--limit-per-category", type=int, default=2)
    parser.add_argument("--sample-limit", type=int, default=0)
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=90, help="HTTP timeout seconds; use 0 for no application timeout")
    parser.add_argument("--max-tokens", type=int, default=1400)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--select-only", action="store_true")
    parser.add_argument("--prompts", nargs="*", default=list(PROMPT_VARIANTS), choices=list(PROMPT_VARIANTS))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    samples = prepare_samples(args)
    if args.sample_limit:
        samples = samples[: args.sample_limit]
    (args.out_dir / "samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.select_only:
        print(json.dumps({"samples": len(samples), "out_dir": str(args.out_dir)}, ensure_ascii=False))
        return 0
    if not args.api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set")

    tasks = [
        make_call_task(
            sample,
            prompt_variant=prompt_variant,
            matrix_name=matrix_name,
            model=model,
            thinking=thinking,
            temperature=temperature,
        )
        for sample in samples
        for prompt_variant in args.prompts
        for matrix_name, model, thinking in MODEL_MATRIX
        for temperature in TEMPERATURE_MATRIX
    ]

    raw_path = args.out_dir / "raw_results.jsonl"
    raw_rows: list[dict[str, Any]] = read_jsonl(raw_path) if args.resume and raw_path.exists() else []
    completed_keys = {result_key(row) for row in raw_rows}
    tasks = [task for task in tasks if result_key(task) not in completed_keys]
    target_total = len(raw_rows) + len(tasks)
    sample_by_id = {sample["sample_id"]: sample for sample in samples}
    with raw_path.open("a", encoding="utf-8") as raw_handle, ThreadPoolExecutor(max_workers=max(1, args.max_concurrency)) as executor:
        futures = [executor.submit(run_task, task, args) for task in tasks]
        for future in as_completed(futures):
            row = future.result()
            sample = sample_by_id[row["sample_id"]]
            row["score"] = (
                score_response(sample, row.get("parsed"), build_user_prompt(sample, row["prompt_variant"]))
                if row.get("json_ok")
                else {
                    "total_score": 0,
                    "date_score": 0,
                    "lineup_score": 0,
                    "evidence_score": 0,
                    "venue_score": 0,
                    "aggregate_score": 0,
                }
            )
            raw_rows.append(row)
            raw_handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            raw_handle.flush()
            print(
                json.dumps(
                    {
                        "done": len(raw_rows),
                        "total": target_total,
                        "sample": row["sample_id"],
                        "variant": row["prompt_variant"],
                        "combo": row["matrix_name"],
                        "temperature": row.get("temperature"),
                        "ok": row.get("ok"),
                        "json": row.get("json_ok"),
                        "score": row["score"].get("total_score"),
                    },
                    ensure_ascii=False,
                )
            )

    raw_rows.sort(key=lambda row: (row["prompt_variant"], row["matrix_name"], row["sample_id"]))
    write_jsonl(raw_path, raw_rows)
    summary = summarize_results(raw_rows)
    (args.out_dir / "matrix_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(args.out_dir / "matrix_summary.md", summary, raw_rows, args)
    print(json.dumps({"out_dir": str(args.out_dir), "calls": len(raw_rows), "best": summary["groups"][0] if summary.get("groups") else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
