#!/usr/bin/env python3
"""
Yuanbao utility module for weekly pipeline integration.

Uses opencli yuanbao CLI to read WeChat articles and extract structured event data.
Provides:
- find_overview_urls(): search download queue for weekly/monthly overview articles
- yuanbao_extract_events(): call yuanbao to extract events from an article URL
- yuanbao_extract_children(): replacement for deepseek_extract_children() for overview parents
"""
import json, re, subprocess, time, pathlib
from collections import OrderedDict
from typing import Any

# Cache for yuanbao results to avoid repeated calls
_yuanbao_cache: dict[str, dict[str, Any]] = OrderedDict()
_yuanbao_cache_max = 20

YUANBAO_TIMEOUT = 180  # seconds per yuanbao call
YUANBAO_RATE_LIMIT = 3  # seconds between calls


def find_overview_urls(
    queue_path: str | pathlib.Path,
    accounts: set[str] | None = None,
    date_range: tuple[str, str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """
    Search the download queue for weekly/monthly overview article URLs.
    
    Returns: {account_name: [{title, url, date}, ...]}
    """
    overview_keywords = ["本周", "一览", "预告", "活动日历", "排期", "WEEKLY", "周报", "月报"]
    results: dict[str, list[dict[str, str]]] = {}
    
    with open(queue_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            nick = str(entry.get("account_nickname", ""))
            if accounts and not any(a in nick for a in accounts):
                continue
            
            title = str(entry.get("title", ""))
            url = entry.get("source_url", "")
            pdate = str(entry.get("post_date", ""))[:10]
            
            if date_range:
                start, end = date_range
                if not (start <= pdate <= end):
                    continue
            
            if any(kw in title for kw in overview_keywords):
                if nick not in results:
                    results[nick] = []
                results[nick].append({"title": title, "url": url, "date": pdate})
    
    return results


def yuanbao_extract_events(
    article_url: str,
    account_hint: str = "",
    timeout: int = YUANBAO_TIMEOUT,
    use_cache: bool = True,
) -> dict[str, Any]:
    """
    Call yuanbao to extract events from a WeChat article.
    
    Returns: {"events": [{date, title, dj, ticket, poster_desc}, ...]}
    """
    cache_key = article_url
    if use_cache and cache_key in _yuanbao_cache:
        return _yuanbao_cache[cache_key]
    
    prompt = (
        "请读取并分析这篇微信公众号文章。"
    )
    if account_hint:
        prompt += f"这是一个{account_hint}的每周活动预告/本周活动一览文章。"
    prompt += (
        "提取文章中列出的每一个活动，包括：\n"
        "1. 活动日期（YYYY-MM-DD格式）\n"
        "2. 活动标题\n"
        "3. DJ/嘉宾名单（数组）\n"
        "4. 票价信息\n"
        "5. 海报图片描述（颜色、图案、风格特征）\n\n"
        "用严格的JSON格式输出，不要补充文章外的信息。\n"
        '输出格式：{"events":[{"date":"YYYY-MM-DD","title":"标题","dj":["DJ1"],"ticket":"票价","poster_desc":"海报描述"}]}\n\n'
        f"文章链接：{article_url}"
    )
    
    try:
        result = subprocess.run(
            ["opencli", "yuanbao", "ask", "--think", "true", "--search", "true", prompt],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(pathlib.Path(__file__).resolve().parent.parent.parent),
        )
        text = result.stdout + "\n" + result.stderr
        
        # Extract JSON from yuanbao response
        json_blocks = re.findall(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        for block in json_blocks:
            try:
                parsed = json.loads(block)
                if "events" in parsed:
                    _yuanbao_cache[cache_key] = parsed
                    return parsed
            except json.JSONDecodeError:
                continue
        
        # Try inline JSON
        json_matches = re.findall(r'\{[^{}]*"events"\s*:\s*\[[^\]]*\][^{}]*\}', text, re.DOTALL)
        for m in json_matches:
            try:
                parsed = json.loads(m)
                if "events" in parsed:
                    _yuanbao_cache[cache_key] = parsed
                    return parsed
            except json.JSONDecodeError:
                continue
    
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    
    result = {"events": [], "_error": "yuanbao_extract_failed"}
    _yuanbao_cache[cache_key] = result
    return result


def yuanbao_extract_children(
    parent_row: dict[str, Any],
    queue_row: dict[str, Any] | None = None,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    timeout: int = YUANBAO_TIMEOUT,
) -> dict[str, Any]:
    """
    Replacement for deepseek_extract_children() that uses yuanbao.
    
    Takes the parent article URL from queue_row and extracts child events via yuanbao.
    Returns an extraction dict compatible with the aggregate expansion pipeline.
    """
    article_url = ""
    if queue_row:
        article_url = str(queue_row.get("source_url", ""))
    
    if not article_url:
        return {
            "_error": "no_article_url",
            "children": [],
            "extraction_status": "yuanbao_no_url",
        }
    
    account = str(parent_row.get("source_account_name", ""))
    result = yuanbao_extract_events(article_url, account_hint=account, timeout=timeout)
    
    if result.get("_error"):
        return {
            "_error": result["_error"],
            "children": [],
            "extraction_status": "yuanbao_failed",
            "_provider": "yuanbao",
        }
    
    events = result.get("events", [])
    children = []
    for ev in events:
        children.append({
            "title": ev.get("title", ""),
            "title_display": ev.get("title", ""),
            "event_date_start": ev.get("date", ""),
            "event_date_end": ev.get("date", ""),
            "city": [],
            "city_keys": [],
            "venue": "",
            "lineup_artists": [{"name": d} for d in ev.get("dj", [])],
            "ticket_price": ev.get("ticket", ""),
            "poster_desc": ev.get("poster_desc", ""),
            "source_kind": "yuanbao_extracted",
            "extraction_confidence": "yuanbao",
        })
    
    # Trim cache
    while len(_yuanbao_cache) > _yuanbao_cache_max:
        _yuanbao_cache.popitem(last=False)
    
    return {
        "children": children,
        "child_count": len(children),
        "extraction_status": "yuanbao_ok",
        "_provider": "yuanbao",
        "_article_url": article_url,
    }
