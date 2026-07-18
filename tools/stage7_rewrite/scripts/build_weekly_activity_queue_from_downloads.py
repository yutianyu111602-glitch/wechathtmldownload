#!/usr/bin/env python3
"""Build the weekly activity prefetch queue from exported account downloads.

The daily downloader writes one ``_articles.json`` per account directory. This
script converts those account-level exports into the queue shape consumed by the
archived weekly activity pack builder, without scanning D: roots.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def platform_path(windows_path: str, wsl_path: str) -> Path:
    return Path(windows_path if os.name == "nt" else wsl_path)


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
DEFAULT_REGISTRY = platform_path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\registries\weekly_accounts_seed.json",
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/registries/weekly_accounts_seed.json",
)
DEFAULT_DOWNLOAD_DIR = platform_path(r"D:\DDownload", "/mnt/d/DDownload")
DEFAULT_OUT_DIR = platform_path(
    r"E:\weekly_activity_pipeline\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE",
    "/mnt/e/weekly_activity_pipeline/longrun/LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE",
)
DEFAULT_EXPORTER_ENDPOINT = "http://127.0.0.1:17300"
DEFAULT_COOKIE_DIR = REPO_ROOT / ".mptext-data" / "kv" / "cookie"
DEFAULT_AUTH_CACHE = REPO_ROOT / ".mptext-data" / "kv" / "auth-key-current.json"


def normalize_exporter_endpoint(value: str) -> str:
    return (value or DEFAULT_EXPORTER_ENDPOINT).rstrip("/")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def read_json_value(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return None


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029") + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def sanitize_path_part(value: str, limit: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().strip(".")
    return (cleaned or "account")[:limit]


def parse_epoch(value: Any) -> tuple[str, str]:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return "", ""
    if seconds <= 0:
        return "", ""
    dt = datetime.fromtimestamp(seconds)
    return dt.date().isoformat(), dt.isoformat(timespec="seconds")


def short_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:length]


def write_body_backfill_progress(
    progress_path: Path | None,
    state: Counter[str],
    *,
    account_id: str = "",
    title: str = "",
    limit: int = 0,
    final: bool = False,
) -> None:
    if progress_path is None:
        return
    keys = (
        "attempted",
        "ok",
        "failed",
        "short",
        "chars",
        "skipped_outside_date_range",
        "skipped_missing_url",
        "skipped_limit",
    )
    counts = {key: int(state.get(key) or 0) for key in keys}
    payload = {
        "schema_version": "weekly_activity_body_backfill_progress.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "final": bool(final),
        "limit": max(0, int(limit or 0)),
        "unlimited": max(0, int(limit or 0)) == 0,
        "current_account_id": account_id,
        "current_title_hash": short_hash(title, 12) if title else "",
        "counts": counts,
        **counts,
    }
    write_json(progress_path, payload)


def emit_body_backfill_progress(
    body_backfill: dict[str, Any],
    account_id: str,
    title: str,
    *,
    final: bool = False,
) -> None:
    state = body_backfill.setdefault("state", Counter())
    progress_path = body_backfill.get("progress_path")
    progress_path = progress_path if isinstance(progress_path, Path) else None
    limit = int(body_backfill.get("limit") or 0)
    write_body_backfill_progress(
        progress_path,
        state,
        account_id=account_id,
        title=title,
        limit=limit,
        final=final,
    )
    print(
        "[body-backfill] "
        f"attempted={int(state.get('attempted') or 0)} "
        f"ok={int(state.get('ok') or 0)} "
        f"failed={int(state.get('failed') or 0)} "
        f"short={int(state.get('short') or 0)} "
        f"skipped_limit={int(state.get('skipped_limit') or 0)} "
        f"limit={limit} "
        f"unlimited={limit == 0} "
        f"account={account_id} "
        f"title_hash={short_hash(title, 12) if title else ''}",
        file=sys.stderr,
        flush=True,
    )


def discover_latest_cookie_auth_key(cookie_dir: Path = DEFAULT_COOKIE_DIR) -> str:
    if not cookie_dir.exists():
        return ""
    candidates: list[tuple[float, str]] = []
    for child in cookie_dir.iterdir():
        if child.is_file() and re.fullmatch(r"[a-fA-F0-9]{32}", child.name):
            try:
                candidates.append((child.stat().st_mtime, child.name))
            except OSError:
                continue
    candidates.sort(reverse=True)
    return candidates[0][1] if candidates else ""


def discover_cached_auth_key(auth_cache: Path = DEFAULT_AUTH_CACHE) -> str:
    if not auth_cache.exists() or not auth_cache.is_file():
        return ""
    try:
        raw = auth_cache.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw if re.fullmatch(r"[A-Za-z0-9_-]{16,256}", raw) else ""
    if not isinstance(payload, dict):
        return ""
    return first_string(payload.get("api_key"), payload.get("auth_key"), payload.get("key"))


def resolve_exporter_auth_key(
    explicit_key: str,
    *,
    auth_env: str = "MPTEXT_AUTH_KEY",
    cookie_dir: Path = DEFAULT_COOKIE_DIR,
    auth_cache: Path = DEFAULT_AUTH_CACHE,
    prefer_env: bool = False,
) -> tuple[str, str]:
    if explicit_key:
        return explicit_key, "explicit"
    env_key = os.environ.get(auth_env, "")
    cache_key = discover_cached_auth_key(auth_cache)
    cookie_key = discover_latest_cookie_auth_key(cookie_dir)
    if prefer_env:
        key = env_key or cache_key or cookie_key
        source = "env" if env_key else ("runtime-cache" if cache_key else "docker-data")
        return key, source if key else ""
    key = cache_key or cookie_key or env_key
    source = "runtime-cache" if cache_key else ("docker-data" if cookie_key else "env")
    return key, source if key else ""


def article_identity(article: dict[str, Any]) -> str:
    return first_string(
        article.get("link"),
        article.get("url"),
        article.get("source_url"),
        str(article.get("aid") or ""),
        f"{article.get('appmsgid') or ''}:{article.get('itemidx') or ''}:{article.get('title') or ''}",
    )


def merge_articles(*article_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for articles in article_groups:
        for article in articles:
            if not isinstance(article, dict):
                continue
            key = article_identity(article)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(article)
    return merged


def exporter_base_resp_error_text(base_resp: dict[str, Any]) -> str:
    if not isinstance(base_resp, dict) or not base_resp:
        return ""
    ret_value = base_resp.get("ret")
    ret_ok = ret_value in (0, "0", None)
    err_msg = first_string(base_resp.get("err_msg"))
    if ret_ok:
        return "" if err_msg.lower() in {"", "ok", "success"} else err_msg
    if err_msg.lower() in {"ok", "success"}:
        err_msg = ""
    return first_string(err_msg, str(ret_value))


def fetch_exporter_articles(
    *,
    fakeid: str,
    endpoint: str,
    auth_key: str,
    max_articles: int,
    page_size: int,
    timeout_sec: int,
    request_delay_sec: float,
    max_retries: int,
    retry_backoff_sec: float,
    retry_freq_control: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: dict[str, Any] = {
        "requested": bool(fakeid),
        "ok": False,
        "pages": 0,
        "articles": 0,
        "error": "",
        "unlimited": max_articles <= 0,
    }
    if not fakeid:
        return [], stats
    endpoint = normalize_exporter_endpoint(endpoint)
    page_size = max(1, min(page_size, 20))
    articles: list[dict[str, Any]] = []
    begin = 0
    unlimited = max_articles <= 0
    while unlimited or len(articles) < max_articles:
        query = urlencode({"fakeid": fakeid, "begin": begin, "size": page_size})
        request = Request(f"{endpoint}/api/public/v1/article?{query}", method="GET")
        if auth_key:
            request.add_header("X-Auth-Key", auth_key)
        payload: dict[str, Any] = {}
        page_error = ""
        for attempt in range(max(0, max_retries) + 1):
            try:
                with urlopen(request, timeout=timeout_sec) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="ignore"))
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                page_error = str(exc)[:200]
            else:
                page_error = ""
                base_resp = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
                error_text = exporter_base_resp_error_text(base_resp)
                freq_control = "freq control" in error_text.lower()
                if not error_text:
                    break
                page_error = error_text
                if not freq_control or not retry_freq_control or attempt >= max_retries:
                    break
            if attempt < max_retries:
                time.sleep(max(0.0, retry_backoff_sec) * (attempt + 1))
        if page_error:
            stats["error"] = page_error
            break
        base_resp = payload.get("base_resp") if isinstance(payload.get("base_resp"), dict) else {}
        base_resp_error = exporter_base_resp_error_text(base_resp)
        if base_resp_error:
            stats["error"] = base_resp_error
            break
        page_articles = payload.get("articles") if isinstance(payload.get("articles"), list) else []
        stats["pages"] = int(stats["pages"]) + 1
        if not page_articles:
            break
        before = len(articles)
        articles = merge_articles(articles, [item for item in page_articles if isinstance(item, dict)])
        if len(articles) == before:
            break
        begin += page_size
        if request_delay_sec > 0:
            time.sleep(request_delay_sec)
    if articles:
        stats["ok"] = True
        stats["articles"] = len(articles if unlimited else articles[:max_articles])
    return (articles if unlimited else articles[:max_articles]), stats


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "svg"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = VisibleTextParser()
    try:
        parser.feed(value or "")
    except Exception:
        text = re.sub(r"<[^>]+>", " ", value or "")
    else:
        text = " ".join(parser.parts)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


ARTICLE_TEXT_KEY_RE = re.compile(
    r"(content_noencode|content_text|plain_text|article_text|raw_text|rich_media_content|content|正文|全文|text|plain|html|body|digest|summary|description)",
    re.IGNORECASE,
)
ARTICLE_TEXT_REJECT_KEY_RE = re.compile(r"(url|link|href|cover|image|avatar|biz|mid|idx|sn|id|time|date|title)", re.IGNORECASE)


def parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def in_date_range(value: str, since: date | None, until: date | None) -> bool:
    parsed = parse_iso_date(value)
    if not parsed:
        return False
    if since and parsed < since:
        return False
    if until and parsed > until:
        return False
    return True


def collapse_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<svg\b.*?</svg>", " ", text)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</p\s*>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_article_text_from_payload(value: Any, parent_key: str = "", depth: int = 0) -> str:
    if depth > 8 or value is None:
        return ""
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ""
        if parent_key and ARTICLE_TEXT_KEY_RE.search(parent_key) and not ARTICLE_TEXT_REJECT_KEY_RE.search(parent_key):
            return collapse_text(raw)
        if raw[:1] in {"{", "["}:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return extract_article_text_from_payload(parsed, parent_key, depth + 1)
        return collapse_text(raw) if "<" in raw and ">" in raw else raw
    if isinstance(value, list):
        parts = [extract_article_text_from_payload(item, parent_key, depth + 1) for item in value]
        return collapse_text("\n".join(part for part in parts if part))
    if isinstance(value, dict):
        candidates: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            text = extract_article_text_from_payload(item, key_text, depth + 1)
            if text and (ARTICLE_TEXT_KEY_RE.search(key_text) or isinstance(item, (dict, list)) or len(text) >= 80):
                candidates.append(text)
        if not candidates:
            return ""
        candidates.sort(key=len, reverse=True)
        return collapse_text(candidates[0])
    return ""


def article_text_is_usable(text: str, min_chars: int = 24) -> bool:
    return len(collapse_text(text)) >= min_chars


def download_text_cache_path(cache_dir: Path, url: str) -> Path:
    return cache_dir / f"{short_hash(url, 24)}.txt"


def fetch_download_body_text(
    *,
    url: str,
    endpoint: str,
    auth_key: str,
    timeout_sec: int,
    cache_dir: Path | None,
    min_chars: int,
) -> tuple[str, str]:
    if not url or not endpoint:
        return "", ""
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = download_text_cache_path(cache_dir, url)
        if cached.exists():
            text = cached.read_text(encoding="utf-8", errors="ignore")
            if article_text_is_usable(text, min_chars=min_chars):
                return collapse_text(text), "mptext_download_cache"
    request_url = normalize_exporter_endpoint(endpoint) + "?" + urlencode({"format": "json", "url": url})
    request = Request(request_url, headers={"Accept": "application/json,text/plain,*/*"}, method="GET")
    if auth_key:
        request.add_header("X-Auth-Key", auth_key)
    with urlopen(request, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8", errors="ignore")
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw
    text = extract_article_text_from_payload(payload)
    if not article_text_is_usable(text, min_chars=min_chars):
        return collapse_text(text), "mptext_download_short"
    text = collapse_text(text)
    if cache_dir is not None:
        download_text_cache_path(cache_dir, url).write_text(text, encoding="utf-8")
    return text, "mptext_download"


def article_dir_name(article: dict[str, Any], title_limit: int = 96) -> str:
    try:
        timestamp = int(article.get("update_time") or article.get("create_time") or 0)
    except (TypeError, ValueError):
        timestamp = 0
    date = datetime.fromtimestamp(timestamp).date().isoformat() if timestamp > 0 else "unknown-date"
    title = sanitize_path_part(first_string(article.get("title"), "untitled"), title_limit)
    aid = sanitize_path_part(first_string(str(article.get("aid") or ""), f"{article.get('appmsgid') or 'article'}_{article.get('itemidx') or 1}"), 48)
    return f"{date}_{title}_{aid}"


def article_dir_candidates(account_dir: Path, article: dict[str, Any]) -> list[Path]:
    """Support legacy long title dirs and current byte-safe short title dirs."""
    candidates: list[Path] = []
    for limit in (40, 96):
        path = account_dir / article_dir_name(article, title_limit=limit)
        if path not in candidates:
            candidates.append(path)
    aid = sanitize_path_part(first_string(str(article.get("aid") or ""), f"{article.get('appmsgid') or 'article'}_{article.get('itemidx') or 1}"), 48)
    try:
        timestamp = int(article.get("update_time") or article.get("create_time") or 0)
    except (TypeError, ValueError):
        timestamp = 0
    date = datetime.fromtimestamp(timestamp).date().isoformat() if timestamp > 0 else "unknown-date"
    if aid:
        candidates.extend(path for path in account_dir.glob(f"{date}_*_{aid}") if path not in candidates)
    return candidates


def downloaded_article_context(account_dir: Path, article: dict[str, Any], limit: int = 8000) -> tuple[str, str, dict[str, str]]:
    candidates = article_dir_candidates(account_dir, article)
    article_dir = candidates[0]
    for candidate in candidates:
        if (candidate / "download.json").exists():
            article_dir = candidate
            break
    download_path = article_dir / "download.json"
    if not download_path.exists():
        return "", str(article_dir), {}
    payload = read_json(download_path)
    chunks = [
        first_string(payload.get("desc")),
        html_to_text(first_string(payload.get("content_noencode"), payload.get("content"), payload.get("html"))),
    ]
    text = "\n".join(chunk for chunk in chunks if chunk)
    text = re.sub(r"\s+", " ", text).strip()
    poi: dict[str, str] = {}
    locations = payload.get("locationlist") if isinstance(payload.get("locationlist"), list) else []
    for location in locations:
        if not isinstance(location, dict):
            continue
        poi = {
            "poi_name": first_string(location.get("name")),
            "poi_address": first_string(location.get("address")),
            "poi_geo_lng": first_string(location.get("longitude"), location.get("geo_lng"), location.get("lng")),
            "poi_geo_lat": first_string(location.get("latitude"), location.get("geo_lat"), location.get("lat")),
        }
        if poi.get("poi_name") or poi.get("poi_address"):
            break
    return text[:limit], str(article_dir), poi


def load_accounts(registry_path: Path, accounts_filter: str, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    payload = read_json(registry_path)
    rows = payload.get("accounts") if isinstance(payload.get("accounts"), list) else []
    wanted = {item.strip() for item in accounts_filter.split(",") if item.strip()} if accounts_filter != "all" else set()
    accounts: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        account_id = first_string(row.get("account_id"), row.get("id"), row.get("key"))
        account_name = first_string(row.get("account_name"), row.get("name"), account_id)
        fakeid = first_string(row.get("fakeid"))
        explicitly_requested = bool(
            wanted and (account_id in wanted or account_name in wanted or fakeid in wanted)
        )
        status = first_string(row.get("status")).lower() or "active"
        if status != "active" and not explicitly_requested:
            if not (include_inactive and status == "inactive"):
                continue
        if wanted and account_id not in wanted and account_name not in wanted and fakeid not in wanted:
            continue
        if not account_id or not account_name:
            continue
        accounts.append(
            {
                "account_id": account_id,
                "account_name": account_name,
                "fakeid": fakeid,
                "city_key": first_string(row.get("city_key")),
                "sync_priority": row.get("sync_priority", 0),
            }
        )
    accounts.sort(key=lambda row: (-int(row.get("sync_priority") or 0), row["account_id"]))
    return accounts


def article_rows_from_articles(
    account: dict[str, Any],
    articles: list[dict[str, Any]],
    account_dir: Path,
    discovery_source: str,
    *,
    body_backfill: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = first_string(article.get("title"))
        link = first_string(article.get("link"), article.get("url"), article.get("source_url"))
        if not title and not link:
            continue
        digest = first_string(article.get("digest"))
        post_date, post_time = parse_epoch(article.get("create_time") or article.get("update_time"))
        body_text, article_dir, poi = downloaded_article_context(account_dir, article)
        body_source = "local_download" if body_text else ""
        if body_backfill and len(body_text) < int(body_backfill.get("min_chars") or 0):
            state = body_backfill.setdefault("state", Counter())
            if not in_date_range(post_date, body_backfill.get("since_date"), body_backfill.get("until_date")):
                state["skipped_outside_date_range"] += 1
            elif not link:
                state["skipped_missing_url"] += 1
            elif body_backfill.get("limit") and int(state.get("attempted") or 0) >= int(body_backfill["limit"]):
                state["skipped_limit"] += 1
            else:
                state["attempted"] += 1
                try:
                    fetched_text, fetched_source = fetch_download_body_text(
                        url=link,
                        endpoint=first_string(body_backfill.get("endpoint")),
                        auth_key=first_string(body_backfill.get("auth_key")),
                        timeout_sec=int(body_backfill.get("timeout_sec") or 20),
                        cache_dir=body_backfill.get("cache_dir"),
                        min_chars=max(24, int(body_backfill.get("min_chars") or 24)),
                    )
                except (OSError, URLError, TimeoutError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    state["failed"] += 1
                    errors = body_backfill.setdefault("errors", [])
                    if len(errors) < 20:
                        errors.append({"account_id": account["account_id"], "url": link, "error": str(exc)[:180]})
                else:
                    if article_text_is_usable(fetched_text, min_chars=max(24, int(body_backfill.get("min_chars") or 24))):
                        body_text = fetched_text[: int(body_backfill.get("text_limit") or 8000)]
                        body_source = fetched_source or "mptext_download"
                        state["ok"] += 1
                        state["chars"] += len(body_text)
                    else:
                        state["short"] += 1
                delay = float(body_backfill.get("delay_sec") or 0.0)
                if delay > 0:
                    time.sleep(delay)
                progress_every = int(body_backfill.get("progress_every") or 0)
                attempted = int(state.get("attempted") or 0)
                if progress_every > 0 and attempted > 0 and attempted % progress_every == 0:
                    emit_body_backfill_progress(body_backfill, account["account_id"], title)
        rich_digest = "\n".join(part for part in [digest, body_text] if part)
        token_source = first_string(
            link,
            str(article.get("aid") or ""),
            f"{account['account_id']}:{article.get('appmsgid') or ''}:{article.get('itemidx') or ''}:{title}",
        )
        queue_id = f"{account['account_id']}:{short_hash(token_source)}"
        rows.append(
            {
                "schema_version": "weekly_activity_prefetch_queue.v1",
                "queue_id": queue_id,
                "token": queue_id,
                "account_key": account["account_id"],
                "account_nickname": account["account_name"],
                "account_fakeid": account.get("fakeid", ""),
                "account_city_key": account.get("city_key", ""),
                "title": title,
                "digest": rich_digest,
                "summary_digest": digest,
                "body_text_chars": len(body_text),
                "body_text_source": body_source,
                "article_dir": article_dir,
                **poi,
                "source_url": link,
                "cover_url": first_string(
                    article.get("cover"),
                    article.get("pic_cdn_url_16_9"),
                    article.get("pic_cdn_url_1_1"),
                    article.get("pic_cdn_url_235_1"),
                ),
                "post_date": post_date,
                "post_time": post_time,
                "discovery_source": discovery_source,
            }
        )
    return rows


def article_rows(account: dict[str, Any], articles_path: Path) -> list[dict[str, Any]]:
    payload = read_json(articles_path)
    articles = payload.get("articles") if isinstance(payload.get("articles"), list) else []
    return article_rows_from_articles(account, articles, articles_path.parent, "huaidj-daily-download")


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = first_string(row.get("source_url"), row.get("token"), row.get("queue_id"))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(row)
    return sorted(out, key=lambda row: (row.get("post_date") or "", row.get("account_key") or "", row.get("title") or ""))


def build_queue(
    registry: Path,
    download_dir: Path,
    out_dir: Path,
    accounts_filter: str,
    *,
    include_inactive_accounts: bool = False,
    refresh_from_exporter: bool = False,
    exporter_endpoint: str = DEFAULT_EXPORTER_ENDPOINT,
    exporter_auth_key: str = "",
    articles_per_account: int = 80,
    exporter_page_size: int = 20,
    exporter_timeout_sec: int = 20,
    exporter_delay_sec: float = 0.15,
    exporter_retries: int = 3,
    exporter_backoff_sec: float = 8.0,
    exporter_retry_freq_control: bool = False,
    exporter_auth_source: str = "",
    body_backfill: bool = False,
    body_backfill_endpoint: str = "",
    body_backfill_auth_key: str = "",
    body_backfill_auth_source: str = "",
    body_backfill_cache_dir: Path | None = None,
    body_backfill_since_date: str = "",
    body_backfill_until_date: str = "",
    body_backfill_min_chars: int = 600,
    body_backfill_timeout_sec: int = 20,
    body_backfill_delay_sec: float = 0.05,
    body_backfill_limit: int = 0,
    body_backfill_progress_every: int = 25,
) -> dict[str, Any]:
    accounts = load_accounts(registry, accounts_filter, include_inactive=include_inactive_accounts)
    rows: list[dict[str, Any]] = []
    missing_dirs: list[str] = []
    account_counts: Counter[str] = Counter()
    date_counts: Counter[str] = Counter()
    exporter_counts: Counter[str] = Counter()
    exporter_errors: dict[str, str] = {}
    exporter_error_counts: Counter[str] = Counter()
    body_backfill_config: dict[str, Any] | None = None
    if body_backfill and body_backfill_endpoint:
        body_backfill_config = {
            "endpoint": body_backfill_endpoint,
            "auth_key": body_backfill_auth_key,
            "cache_dir": body_backfill_cache_dir,
            "since_date": parse_iso_date(body_backfill_since_date) if body_backfill_since_date else None,
            "until_date": parse_iso_date(body_backfill_until_date) if body_backfill_until_date else None,
            "min_chars": max(0, body_backfill_min_chars),
            "timeout_sec": body_backfill_timeout_sec,
            "delay_sec": max(0.0, body_backfill_delay_sec),
            "limit": max(0, body_backfill_limit),
            "progress_every": max(0, body_backfill_progress_every),
            "progress_path": out_dir / "body_backfill_progress.json",
            "text_limit": 8000,
            "state": Counter(),
            "errors": [],
        }

    for account in accounts:
        account_dir = download_dir / sanitize_path_part(account["account_name"])
        articles_path = account_dir / "_articles.json"
        local_articles: list[dict[str, Any]] = []
        if not articles_path.exists():
            missing_dirs.append(account["account_id"])
        else:
            payload = read_json(articles_path)
            local_articles = payload.get("articles") if isinstance(payload.get("articles"), list) else []
        exporter_articles: list[dict[str, Any]] = []
        if refresh_from_exporter and account.get("fakeid"):
            exporter_articles, exporter_stats = fetch_exporter_articles(
                fakeid=first_string(account.get("fakeid")),
                endpoint=exporter_endpoint,
                auth_key=exporter_auth_key,
                max_articles=max(0, articles_per_account),
                page_size=exporter_page_size,
                timeout_sec=exporter_timeout_sec,
                request_delay_sec=exporter_delay_sec,
                max_retries=exporter_retries,
                retry_backoff_sec=exporter_backoff_sec,
                retry_freq_control=exporter_retry_freq_control,
            )
            if exporter_stats.get("ok"):
                exporter_counts[account["account_id"]] = int(exporter_stats.get("articles") or 0)
            elif exporter_stats.get("requested"):
                error_text = first_string(exporter_stats.get("error"), "unknown_error")
                exporter_errors[account["account_id"]] = error_text
                exporter_error_counts[error_text] += 1
        merged_articles = merge_articles(exporter_articles, local_articles)
        discovery_source = "huaidj-exporter-api+daily-download" if exporter_articles else "huaidj-daily-download"
        account_rows = article_rows_from_articles(
            account,
            merged_articles,
            account_dir,
            discovery_source,
            body_backfill=body_backfill_config,
        )
        rows.extend(account_rows)
        account_counts[account["account_id"]] += len(account_rows)
        if body_backfill_config:
            emit_body_backfill_progress(body_backfill_config, account["account_id"], "", final=False)
        for row in account_rows:
            if row.get("post_date"):
                date_counts[str(row["post_date"])] += 1

    rows = dedupe_rows(rows)
    queue_path = out_dir / "latest_queue.jsonl"
    summary_path = out_dir / "summary.json"
    account_counts_path = out_dir / "account_counts.jsonl"
    if body_backfill_config:
        emit_body_backfill_progress(body_backfill_config, "", "", final=True)
    write_jsonl(queue_path, rows)
    write_jsonl(
        account_counts_path,
        [{"account_key": account, "count": count} for account, count in account_counts.most_common()],
    )
    summary = {
        "schema_version": "weekly_activity_prefetch_queue_from_downloads.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "registry": str(registry),
        "download_dir": str(download_dir),
        "out_dir": str(out_dir),
        "queue": str(queue_path),
        "account_scope": "active+inactive" if include_inactive_accounts else "active",
        "include_inactive_accounts": include_inactive_accounts,
        "accounts_requested": len(accounts),
        "account_dirs_missing": len(missing_dirs),
        "missing_account_ids": missing_dirs[:50],
        "exporter_refresh_requested": refresh_from_exporter,
        "exporter_endpoint": normalize_exporter_endpoint(exporter_endpoint) if refresh_from_exporter else "",
        "exporter_articles_per_account": articles_per_account if refresh_from_exporter else 0,
        "exporter_articles_per_account_unlimited": articles_per_account <= 0 if refresh_from_exporter else False,
        "exporter_accounts_ok": len(exporter_counts),
        "exporter_accounts_failed": len(exporter_errors),
        "exporter_article_rows": int(sum(exporter_counts.values())),
        "exporter_retries": exporter_retries if refresh_from_exporter else 0,
        "exporter_backoff_sec": exporter_backoff_sec if refresh_from_exporter else 0,
        "exporter_retry_freq_control": bool(exporter_retry_freq_control) if refresh_from_exporter else False,
        "exporter_auth_source": exporter_auth_source if refresh_from_exporter else "",
        "exporter_auth_key_hash": short_hash(exporter_auth_key, 12) if refresh_from_exporter and exporter_auth_key else "",
        "exporter_error_counts": dict(exporter_error_counts.most_common()),
        "exporter_errors_sample": dict(list(exporter_errors.items())[:20]),
        "body_backfill_requested": bool(body_backfill_config),
        "body_backfill_endpoint": normalize_exporter_endpoint(body_backfill_endpoint) if body_backfill_config else "",
        "body_backfill_auth_source": body_backfill_auth_source if body_backfill_config else "",
        "body_backfill_auth_key_hash": short_hash(body_backfill_auth_key, 12) if body_backfill_config and body_backfill_auth_key else "",
        "body_backfill_since_date": body_backfill_since_date if body_backfill_config else "",
        "body_backfill_until_date": body_backfill_until_date if body_backfill_config else "",
        "body_backfill_min_chars": body_backfill_min_chars if body_backfill_config else 0,
        "body_backfill_limit": body_backfill_limit if body_backfill_config else 0,
        "body_backfill_unlimited": body_backfill_limit == 0 if body_backfill_config else False,
        "body_backfill_progress_every": body_backfill_progress_every if body_backfill_config else 0,
        "body_backfill_progress_path": str((body_backfill_config or {}).get("progress_path") or ""),
        "body_backfill_counts": dict((body_backfill_config or {}).get("state", Counter())),
        "body_backfill_errors_sample": list((body_backfill_config or {}).get("errors", []))[:20],
        "rows_written": len(rows),
        "date_counts": dict(sorted(date_counts.items())),
        "account_counts": dict(account_counts.most_common()),
        "exporter_account_counts": dict(exporter_counts.most_common()),
    }
    write_json(summary_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build weekly activity queue from daily account downloads")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--download-dir", default=str(DEFAULT_DOWNLOAD_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--accounts", default="all", help="'all' or comma-separated account_id/account_name/fakeid")
    parser.add_argument("--include-inactive-accounts", action="store_true", help="Include inactive registry accounts when --accounts all is used; review accounts still require explicit selection")
    parser.add_argument("--active-only-accounts", action="store_true", help="Legacy escape hatch: limit --accounts all to active accounts only")
    parser.add_argument("--refresh-from-exporter", action="store_true", help="Merge paged article metadata from the local wechat-article-exporter API")
    parser.add_argument("--exporter-endpoint", default=DEFAULT_EXPORTER_ENDPOINT)
    parser.add_argument("--exporter-auth-key", default="")
    parser.add_argument("--exporter-auth-prefer-env", action="store_true", help="Prefer MPTEXT_AUTH_KEY over the latest Docker cookie key")
    parser.add_argument("--exporter-cookie-dir", default=str(DEFAULT_COOKIE_DIR))
    parser.add_argument("--exporter-auth-cache", default=str(DEFAULT_AUTH_CACHE))
    parser.add_argument("--articles-per-account", type=int, default=0, help="0 means no per-account exporter article limit")
    parser.add_argument("--exporter-page-size", type=int, default=20)
    parser.add_argument("--exporter-timeout-sec", type=int, default=20)
    parser.add_argument("--exporter-delay-sec", type=float, default=0.15)
    parser.add_argument("--exporter-retries", type=int, default=3)
    parser.add_argument("--exporter-backoff-sec", type=float, default=8.0)
    parser.add_argument("--exporter-retry-freq-control", action="store_true", help="Opt in to retrying WeChat freq-control responses; default is fast-fail and local queue fallback")
    parser.add_argument("--body-backfill", action="store_true", help="Fetch missing article body text before rules/LLM extraction")
    parser.add_argument("--body-backfill-endpoint", default=DEFAULT_EXPORTER_ENDPOINT + "/api/public/v1/download")
    parser.add_argument("--body-backfill-auth-key", default="")
    parser.add_argument("--body-backfill-auth-prefer-env", action="store_true", help="Prefer MPTEXT_AUTH_KEY over the latest Docker cookie key")
    parser.add_argument("--body-backfill-cache-dir", default="")
    parser.add_argument("--body-backfill-since-date", default="")
    parser.add_argument("--body-backfill-until-date", default="")
    parser.add_argument("--body-backfill-min-chars", type=int, default=600)
    parser.add_argument("--body-backfill-timeout-sec", type=int, default=20)
    parser.add_argument("--body-backfill-delay-sec", type=float, default=0.05)
    parser.add_argument("--body-backfill-limit", type=int, default=0, help="0 means no body backfill limit")
    parser.add_argument("--body-backfill-progress-every", type=int, default=25, help="Write body_backfill_progress.json every N attempted body fetches; 0 disables interval progress writes")
    args = parser.parse_args(argv)

    exporter_auth_key, exporter_auth_source = resolve_exporter_auth_key(
        args.exporter_auth_key,
        cookie_dir=Path(args.exporter_cookie_dir),
        auth_cache=Path(args.exporter_auth_cache),
        prefer_env=args.exporter_auth_prefer_env,
    )
    body_backfill_auth_key, body_backfill_auth_source = resolve_exporter_auth_key(
        args.body_backfill_auth_key,
        cookie_dir=Path(args.exporter_cookie_dir),
        auth_cache=Path(args.exporter_auth_cache),
        prefer_env=args.body_backfill_auth_prefer_env,
    )

    summary = build_queue(
        registry=Path(args.registry),
        download_dir=Path(args.download_dir),
        out_dir=Path(args.out_dir),
        accounts_filter=args.accounts,
        include_inactive_accounts=args.include_inactive_accounts or not args.active_only_accounts,
        refresh_from_exporter=args.refresh_from_exporter,
        exporter_endpoint=args.exporter_endpoint,
        exporter_auth_key=exporter_auth_key,
        articles_per_account=args.articles_per_account,
        exporter_page_size=args.exporter_page_size,
        exporter_timeout_sec=args.exporter_timeout_sec,
        exporter_delay_sec=args.exporter_delay_sec,
        exporter_retries=args.exporter_retries,
        exporter_backoff_sec=args.exporter_backoff_sec,
        exporter_retry_freq_control=args.exporter_retry_freq_control,
        exporter_auth_source=exporter_auth_source,
        body_backfill=args.body_backfill,
        body_backfill_endpoint=args.body_backfill_endpoint,
        body_backfill_auth_key=body_backfill_auth_key,
        body_backfill_auth_source=body_backfill_auth_source,
        body_backfill_cache_dir=Path(args.body_backfill_cache_dir) if args.body_backfill_cache_dir else None,
        body_backfill_since_date=args.body_backfill_since_date,
        body_backfill_until_date=args.body_backfill_until_date,
        body_backfill_min_chars=args.body_backfill_min_chars,
        body_backfill_timeout_sec=args.body_backfill_timeout_sec,
        body_backfill_delay_sec=args.body_backfill_delay_sec,
        body_backfill_limit=args.body_backfill_limit,
        body_backfill_progress_every=args.body_backfill_progress_every,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
