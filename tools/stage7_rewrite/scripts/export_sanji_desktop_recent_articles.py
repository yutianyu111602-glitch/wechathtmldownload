#!/usr/bin/env python3
"""Export recent Sanji desktop WeChat articles as a safe manifest.

This script reads only article/account metadata from the Sanji desktop SQLite
database. It intentionally does not read identity, cookie, token, license, or
credential tables.
"""

from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
from html.parser import HTMLParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
from typing import Any, Iterable


DEFAULT_SANJI_ROOT = Path(
    os.environ.get("SANJI_ROOT")
    or (Path(os.environ.get("APPDATA", r"C:\Users\pc\AppData\Roaming")) / "sanji")
)
DEFAULT_OUT_ROOT = Path(os.environ.get("SANJI_EXPORT_OUT_ROOT", r"E:\公众号\sanji-daily-export"))
DEFAULT_HOT_ARTICLES_ROOT = Path(os.environ.get("SANJI_HOT_ARTICLES_ROOT", r"E:\sanji_hot\articles"))
DEFAULT_COLD_ARCHIVE_ROOT = Path(os.environ.get("SANJI_COLD_ARCHIVE_ROOT", r"D:\sanji_cold_archive"))
DEFAULT_WEEKLY_REGISTRY = (
    Path(__file__).resolve().parents[1] / "registries" / "weekly_accounts_seed.json"
)
DEFAULT_SOURCE_POLICY = (
    Path(__file__).resolve().parents[1] / "registries" / "weekly_sanji_source_policy.json"
)
OLD_WECHAT_CUTOFF_TS = int(dt.datetime(2014, 1, 1, tzinfo=dt.timezone.utc).timestamp())
ARTICLE_TIME_EXPR = "COALESCE(NULLIF(publish_time, 0), NULLIF(create_time, 0), 0)"
UNAVAILABLE_FETCH_STATUSES = {"deleted", "removed", "not_found"}


ARTICLE_COLUMNS = [
    "account_fakeid",
    "aid",
    "msgid",
    "itemidx",
    "link",
    "title",
    "digest",
    "cover",
    "create_time",
    "publish_time",
    "article_type",
    "is_deleted",
    "author",
    "is_original",
    "media_duration",
    "album_id",
    "album_name",
    "is_paid",
    "fetched_at",
    "content_fetched",
    "content_path",
    "content_size",
    "content_fetched_at",
    "content_error",
    "fetch_status",
    "fetch_retry_count",
    "content_resources_failed",
    "comment_fetched",
    "read_num",
    "like_num",
    "old_like_num",
    "share_num",
    "comment_count",
    "reward_num",
    "html_path",
    "html_fetched_at",
    "resource_retry_count",
    "via_client",
    "client_offset",
]

ARTICLE_COLUMN_ALIASES = {
    "like_num": "like_count",
    "old_like_num": "old_like_count",
    "share_num": "share_count",
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sanji-root", type=Path, default=DEFAULT_SANJI_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--hot-articles-root", type=Path, default=DEFAULT_HOT_ARTICLES_ROOT)
    parser.add_argument("--cold-archive-root", type=Path, default=DEFAULT_COLD_ARCHIVE_ROOT)
    parser.add_argument("--weekly-registry", type=Path, default=DEFAULT_WEEKLY_REGISTRY)
    parser.add_argument("--source-policy", type=Path, default=DEFAULT_SOURCE_POLICY)
    parser.add_argument("--lookback-days", type=float, default=2.0)
    parser.add_argument("--since-date", help="Use local date YYYY-MM-DD instead of lookback-days.")
    parser.add_argument("--run-label", help="Output directory name. Defaults to local timestamp.")
    parser.add_argument("--write-latest", action="store_true", help="Refresh latest_* files in out-root.")
    parser.add_argument(
        "--write-prefetch-queue",
        action="store_true",
        help="Also write weekly pipeline-compatible latest_queue.jsonl from the Sanji/RSS manifest.",
    )
    parser.add_argument("--body-text-limit", type=int, default=8000)
    parser.add_argument(
        "--copy-mode",
        choices=("none", "html", "full"),
        default="none",
        help="Optional materialization. none writes manifest only; html copies index/meta; full copies article dirs.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Debug limit after filtering. 0 means no limit.")
    parser.add_argument(
        "--include-unfetched",
        action="store_true",
        help="Include unfetched rows in manifest. Default exports only rows with local HTML.",
    )
    return parser.parse_args(argv)


def local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def to_epoch_seconds(value: Any) -> int | None:
    if value is None:
        return None
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    if raw > 10_000_000_000:
        raw //= 1000
    return raw


def iso_from_epoch(value: Any) -> str | None:
    raw = to_epoch_seconds(value)
    if raw is None:
        return None
    return dt.datetime.fromtimestamp(raw, tz=dt.timezone.utc).astimezone().isoformat()


def stable_hash(text: str | None, length: int = 16) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()[:length]


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def normalize_subject(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def truthy_int(value: Any) -> bool:
    try:
        return int(value or 0) != 0
    except (TypeError, ValueError):
        return False


def is_unavailable_article(row: dict[str, Any]) -> bool:
    status = str(row.get("fetch_status") or "").strip().lower()
    return truthy_int(row.get("is_deleted")) or status in UNAVAILABLE_FETCH_STATUSES


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in {"script", "style", "noscript"}:
            self._skip_depth += 1
        elif tag_lower in {"br", "p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag_lower in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data:
            self.parts.append(data)


def collapse_text(value: str) -> str:
    text = (value or "").replace("\u2028", "\n").replace("\u2029", "\n")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(value: str, limit: int = 8000) -> str:
    if not value:
        return ""
    parser = _ArticleTextParser()
    try:
        parser.feed(value)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", value)
    else:
        text = "".join(parser.parts)
    return collapse_text(text)[: max(0, limit)]


def local_html_text(path_text: str | None, limit: int = 8000) -> str:
    if not path_text:
        return ""
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return ""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return html_to_text(raw, limit=limit)


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def is_reparse_point(path: Path) -> bool:
    try:
        attributes = os.stat(path, follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return path.is_symlink()
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def jsonl_dump(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(sanitize_jsonl_value(row), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def sanitize_jsonl_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\u2028", "\n").replace("\u2029", "\n")
    if isinstance(value, list):
        return [sanitize_jsonl_value(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_jsonl_value(item) for key, item in value.items()}
    return value


def load_weekly_registry(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    accounts = payload.get("accounts") if isinstance(payload, dict) else None
    if not isinstance(accounts, list):
        return {}

    by_fakeid: dict[str, dict[str, str]] = {}
    for row in accounts:
        if not isinstance(row, dict):
            continue
        fakeid = first_string(row.get("fakeid"))
        if not fakeid:
            continue
        account_id = first_string(row.get("account_id"), row.get("id"), row.get("key"))
        by_fakeid[fakeid] = {
            "account_id": account_id,
            "account_name": first_string(row.get("account_name"), row.get("name"), account_id),
            "city_key": first_string(row.get("city_key")),
            "status": first_string(row.get("status"), "active").lower(),
        }
    return by_fakeid


def load_source_policy(path: Path | None) -> dict[str, set[str]]:
    if not path or not path.exists():
        return {"account_fakeids": set(), "accounts": set(), "venues": set()}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"account_fakeids": set(), "accounts": set(), "venues": set()}
    accounts = {
        normalize_subject(value)
        for value in list_strings(payload.get("blocked_accounts"))
        if normalize_subject(value)
    }
    venues = {
        normalize_subject(value)
        for value in list_strings(payload.get("blocked_venues"))
        if normalize_subject(value)
    }
    fakeids = {value for value in list_strings(payload.get("blocked_account_fakeids")) if value}
    return {"account_fakeids": fakeids, "accounts": accounts, "venues": venues}


def source_policy_exclude_reason(row: dict[str, Any], policy: dict[str, set[str]]) -> str:
    fakeid = first_string(row.get("account_fakeid"))
    if fakeid and fakeid in policy.get("account_fakeids", set()):
        return "source_policy_blocked_account"
    account_values = [
        first_string(row.get("account_nickname")),
        first_string(row.get("account_alias")),
    ]
    normalized_accounts = [normalize_subject(value) for value in account_values if normalize_subject(value)]
    for account in normalized_accounts:
        if any(account == blocked or account in blocked or blocked in account for blocked in policy.get("accounts", set())):
            return "source_policy_blocked_account"
    title = normalize_subject(first_string(row.get("title")))
    if title and any(blocked and blocked in title for blocked in policy.get("venues", set())):
        return "source_policy_blocked_venue"
    return ""


def article_post_date_time(row: dict[str, Any]) -> tuple[str, str]:
    post_time = first_string(row.get("publish_time_iso"), row.get("create_time_iso"))
    if post_time:
        return post_time[:10], post_time[:19]
    epoch_value = row.get("publish_time") or row.get("create_time")
    post_time = iso_from_epoch(epoch_value) or ""
    return post_time[:10], post_time[:19]


def build_prefetch_rows(
    manifest: list[dict[str, Any]],
    registry_by_fakeid: dict[str, dict[str, str]],
    body_text_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    counters: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in manifest:
        title = first_string(item.get("title"))
        source_url = first_string(item.get("link"))
        if not title and not source_url:
            counters["missing_title_and_source_url"] += 1
            continue

        fakeid = first_string(item.get("account_fakeid"))
        registry_row = registry_by_fakeid.get(fakeid, {})
        account_key = first_string(
            registry_row.get("account_id"),
            item.get("account_alias"),
            item.get("account_nickname"),
            fakeid,
            "unknown",
        )
        account_nickname = first_string(item.get("account_nickname"), registry_row.get("account_name"), account_key)
        digest = first_string(item.get("digest"))
        body_text = local_html_text(item.get("html_abs_path"), limit=body_text_limit)
        rich_digest = "\n".join(part for part in (digest, body_text) if part)
        post_date, post_time = article_post_date_time(item)
        if not post_date:
            counters["missing_post_date"] += 1

        token_source = first_string(source_url, item.get("aid"), item.get("source_url_hash"), f"{fakeid}:{title}")
        queue_id = f"{account_key}:{stable_hash(token_source)}"
        dedupe_key = source_url or queue_id
        if dedupe_key in seen:
            counters["duplicate_source_url_or_queue_id"] += 1
            continue
        seen.add(dedupe_key)

        rows.append(
            {
                "schema_version": "weekly_activity_prefetch_queue.v1",
                "queue_id": queue_id,
                "token": queue_id,
                "account_key": account_key,
                "account": account_key,
                "account_nickname": account_nickname,
                "account_fakeid": fakeid,
                "account_city_key": first_string(registry_row.get("city_key")),
                "account_registry_status": first_string(registry_row.get("status")),
                "title": title,
                "digest": rich_digest,
                "summary_digest": digest,
                "body_text_chars": len(body_text),
                "body_text_source": "sanji_desktop_html" if body_text else "",
                "article_dir": first_string(item.get("article_dir")),
                "source_url": source_url,
                "cover_url": first_string(item.get("cover")),
                "post_date": post_date,
                "post_time": post_time,
                "discovery_source": "sanji-desktop-client",
                "legacy_discovery_source_alias": "sanji-desktop-rss",
                "acquisition_channel": item.get("acquisition_channel"),
                "coverage_scope": "broadcast_only",
                "source_url_hash": item.get("source_url_hash"),
                "sanji_aid": item.get("aid"),
                "sanji_msgid": item.get("msgid"),
            }
        )
        counters["registry_matched" if registry_row else "registry_unmatched"] += 1
        counters["body_text_present" if body_text else "body_text_missing"] += 1

    rows.sort(key=lambda row: (row.get("post_date") or "", row.get("account_key") or "", row.get("title") or ""))
    return rows, {
        "input_manifest_rows": len(manifest),
        "rows_written": len(rows),
        "counts": dict(counters),
    }


def backup_live_db(db_path: Path, snapshot_path: Path) -> None:
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(snapshot_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def connect_snapshot(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def epoch_cutoff(args: argparse.Namespace, now: dt.datetime) -> int:
    if args.since_date:
        local_date = dt.datetime.strptime(args.since_date, "%Y-%m-%d").date()
        local_start = dt.datetime.combine(local_date, dt.time.min, tzinfo=now.tzinfo)
        return int(local_start.timestamp())
    return int((now - dt.timedelta(days=args.lookback_days)).timestamp())


def fetch_status_counts(con: sqlite3.Connection, cutoff_ts: int | None = None) -> dict[str, int]:
    where = ""
    params: tuple[Any, ...] = ()
    if cutoff_ts is not None:
        where = f"WHERE {ARTICLE_TIME_EXPR} >= ?"
        params = (cutoff_ts,)
    rows = con.execute(
        f"""
        SELECT COALESCE(fetch_status, 'NULL') AS fetch_status, COUNT(*) AS n
        FROM wechat_article
        {where}
        GROUP BY COALESCE(fetch_status, 'NULL')
        ORDER BY n DESC
        """,
        params,
    ).fetchall()
    return {str(row["fetch_status"]): int(row["n"]) for row in rows}


def old_unfetched_counts(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute(
        f"""
        SELECT COALESCE(fetch_status, 'NULL') AS fetch_status, COUNT(*) AS n
        FROM wechat_article
        WHERE {ARTICLE_TIME_EXPR} < ?
          AND COALESCE(content_fetched, 0) = 0
        GROUP BY COALESCE(fetch_status, 'NULL')
        ORDER BY n DESC
        """,
        (OLD_WECHAT_CUTOFF_TS,),
    ).fetchall()
    return {str(row["fetch_status"]): int(row["n"]) for row in rows}


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def article_select_expressions(con: sqlite3.Connection) -> str:
    available = table_columns(con, "wechat_article")
    expressions = []
    for name in ARTICLE_COLUMNS:
        source_name = name if name in available else ARTICLE_COLUMN_ALIASES.get(name)
        if source_name and source_name in available:
            expressions.append(f"a.{source_name} AS {name}")
        else:
            expressions.append(f"NULL AS {name}")
    return ", ".join(expressions)


def recent_article_rows(con: sqlite3.Connection, cutoff_ts: int, limit: int) -> list[sqlite3.Row]:
    limit_sql = "LIMIT ?" if limit > 0 else ""
    params: list[Any] = [cutoff_ts]
    if limit > 0:
        params.append(limit)
    columns = article_select_expressions(con)
    return con.execute(
        f"""
        SELECT
          {columns},
          acc.nickname AS account_nickname,
          acc.alias AS account_alias
        FROM wechat_article AS a
        LEFT JOIN wechat_account AS acc
          ON acc.fakeid = a.account_fakeid
        WHERE COALESCE(NULLIF(a.publish_time, 0), NULLIF(a.create_time, 0), 0) >= ?
        ORDER BY COALESCE(NULLIF(a.publish_time, 0), NULLIF(a.create_time, 0), 0) DESC, a.rowid DESC
        {limit_sql}
        """,
        tuple(params),
    ).fetchall()


def count_path_entries(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    try:
        return sum(1 for child in path.iterdir() if child.is_file())
    except OSError:
        return 0


def resolve_source_html_path(
    sanji_root: Path,
    hot_articles_root: Path,
    content_path: str | None,
) -> Path | None:
    if not content_path:
        return None
    relative = Path(content_path)
    primary = sanji_root / relative
    if primary.exists():
        return primary
    parts = relative.parts
    if parts and parts[0].casefold() == "articles":
        hot_candidate = hot_articles_root.joinpath(*parts[1:])
    else:
        hot_candidate = hot_articles_root / relative
    return hot_candidate if hot_candidate.exists() else primary


def source_article_dir(
    sanji_root: Path,
    hot_articles_root: Path,
    content_path: str | None,
) -> Path | None:
    html_path = resolve_source_html_path(sanji_root, hot_articles_root, content_path)
    return html_path.parent if html_path else None


def copy_article(row: dict[str, Any], out_dir: Path, mode: str) -> dict[str, Any]:
    if mode == "none":
        return {}
    src_dir_text = row.get("article_dir")
    if not src_dir_text:
        return {"copy_error": "missing_article_dir"}
    src_dir = Path(src_dir_text)
    if not src_dir.exists():
        return {"copy_error": "missing_source_dir"}

    fakeid = row.get("account_fakeid") or "unknown_fakeid"
    aid = row.get("aid") or stable_hash(row.get("link"))
    dest_dir = out_dir / "articles" / str(fakeid) / str(aid)
    dest_dir.parent.mkdir(parents=True, exist_ok=True)

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        if mode == "full":
            shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)
        else:
            for filename in ("index.html", "index.html.meta.json"):
                src_file = src_dir / filename
                if src_file.exists():
                    shutil.copy2(src_file, dest_dir / filename)
    except OSError as exc:
        return {"copy_error": str(exc)}

    return {"exported_article_dir": str(dest_dir)}


def build_manifest_rows(
    raw_rows: list[sqlite3.Row],
    sanji_root: Path,
    hot_articles_root: Path,
    out_dir: Path,
    copy_mode: str,
    include_unfetched: bool,
    source_policy: dict[str, set[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    manifest: list[dict[str, Any]] = []
    skipped = {
        "unfetched": 0,
        "missing_content_path": 0,
        "missing_html_file": 0,
        "deleted_or_unavailable": 0,
        "source_policy_blocked_account": 0,
        "source_policy_blocked_venue": 0,
    }

    for raw in raw_rows:
        row = dict(raw)
        policy_reason = source_policy_exclude_reason(row, source_policy or {})
        if policy_reason:
            skipped[policy_reason] += 1
            continue
        if is_unavailable_article(row):
            skipped["deleted_or_unavailable"] += 1
            continue
        content_path = row.get("content_path")
        html_path = resolve_source_html_path(sanji_root, hot_articles_root, content_path)
        article_dir = source_article_dir(sanji_root, hot_articles_root, content_path)
        meta_path = html_path.with_name("index.html.meta.json") if html_path else None
        assets_dir = html_path.with_name("assets") if html_path else None
        fetched = int(row.get("content_fetched") or 0) == 1
        html_exists = bool(html_path and html_path.exists())

        if not include_unfetched:
            if not fetched:
                skipped["unfetched"] += 1
                continue
            if not content_path:
                skipped["missing_content_path"] += 1
                continue
            if not html_exists:
                skipped["missing_html_file"] += 1
                continue

        item = {
            "source": "sanji_desktop",
            "source_contract_version": "sanji_wechat_client.v1",
            "acquisition_channel": "wechat_client" if int(row.get("via_client") or 0) == 1 else "legacy_or_unknown",
            "coverage_scope": "broadcast_only",
            "via_client": row.get("via_client"),
            "client_offset": row.get("client_offset"),
            "id": f"sanji:{row.get('account_fakeid') or ''}:{row.get('aid') or ''}",
            "source_url_hash": stable_hash(row.get("link")),
            "account_fakeid": row.get("account_fakeid"),
            "account_nickname": row.get("account_nickname"),
            "account_alias": row.get("account_alias"),
            "aid": row.get("aid"),
            "msgid": row.get("msgid"),
            "itemidx": row.get("itemidx"),
            "title": row.get("title"),
            "digest": row.get("digest"),
            "author": row.get("author"),
            "link": row.get("link"),
            "cover": row.get("cover"),
            "publish_time": to_epoch_seconds(row.get("publish_time")),
            "publish_time_iso": iso_from_epoch(row.get("publish_time")),
            "create_time": to_epoch_seconds(row.get("create_time")),
            "create_time_iso": iso_from_epoch(row.get("create_time")),
            "article_type": row.get("article_type"),
            "is_deleted": row.get("is_deleted"),
            "is_original": row.get("is_original"),
            "is_paid": row.get("is_paid"),
            "fetch_status": row.get("fetch_status"),
            "content_fetched": row.get("content_fetched"),
            "content_size": row.get("content_size"),
            "content_fetched_at": to_epoch_seconds(row.get("content_fetched_at")),
            "content_fetched_at_iso": iso_from_epoch(row.get("content_fetched_at")),
            "content_resources_failed": row.get("content_resources_failed"),
            "fetch_retry_count": row.get("fetch_retry_count"),
            "resource_retry_count": row.get("resource_retry_count"),
            "read_num": row.get("read_num"),
            "like_num": row.get("like_num"),
            "share_num": row.get("share_num"),
            "comment_count": row.get("comment_count"),
            "content_path": content_path,
            "html_abs_path": str(html_path) if html_path else None,
            "html_exists": html_exists,
            "meta_abs_path": str(meta_path) if meta_path and meta_path.exists() else None,
            "assets_dir": str(assets_dir) if assets_dir and assets_dir.exists() else None,
            "assets_file_count": count_path_entries(assets_dir) if assets_dir else 0,
            "article_dir": str(article_dir) if article_dir else None,
        }
        item.update(copy_article(item, out_dir, copy_mode))
        manifest.append(item)

    return manifest, skipped


def write_latest(out_root: Path, out_dir: Path) -> None:
    latest_map = [
        ("manifest.jsonl", "latest_manifest.jsonl"),
        ("summary.json", "latest_summary.json"),
        ("summary.json", "summary.json"),
        ("source_url_map.json", "latest_source_url_map.json"),
        ("latest_queue.jsonl", "latest_queue.jsonl"),
    ]
    for src_name, latest_name in latest_map:
        src = out_dir / src_name
        if src.exists():
            shutil.copy2(src, out_root / latest_name)
    (out_root / "LATEST.txt").write_text(str(out_dir), encoding="utf-8")


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    now = local_now()
    sanji_root = args.sanji_root
    db_path = sanji_root / "sanji.db"
    if not db_path.exists():
        print(f"Sanji DB not found: {db_path}", file=sys.stderr)
        return 2

    run_label = args.run_label or now.strftime("%Y%m%d_%H%M%S")
    out_root = args.out_root
    out_dir = out_root / run_label
    out_dir.mkdir(parents=True, exist_ok=True)

    cutoff_ts = epoch_cutoff(args, now)

    with tempfile.TemporaryDirectory(prefix="sanji_export_") as tmp:
        snapshot_path = Path(tmp) / "sanji.snapshot.db"
        backup_live_db(db_path, snapshot_path)
        con = connect_snapshot(snapshot_path)
        try:
            status_counts_all = fetch_status_counts(con)
            status_counts_window = fetch_status_counts(con, cutoff_ts)
            old_counts = old_unfetched_counts(con)
            raw_rows = recent_article_rows(con, cutoff_ts, args.limit)
        finally:
            con.close()

    source_policy = load_source_policy(args.source_policy)
    manifest, skipped = build_manifest_rows(
        raw_rows=raw_rows,
        sanji_root=sanji_root,
        hot_articles_root=args.hot_articles_root,
        out_dir=out_dir,
        copy_mode=args.copy_mode,
        include_unfetched=args.include_unfetched,
        source_policy=source_policy,
    )

    manifest_path = out_dir / "manifest.jsonl"
    manifest_count = jsonl_dump(manifest_path, manifest)
    source_url_map = {
        row["source_url_hash"]: {
            "link": row.get("link"),
            "title": row.get("title"),
            "account_fakeid": row.get("account_fakeid"),
            "account_nickname": row.get("account_nickname"),
            "aid": row.get("aid"),
            "publish_time_iso": row.get("publish_time_iso"),
            "html_abs_path": row.get("html_abs_path"),
        }
        for row in manifest
        if row.get("source_url_hash")
    }
    json_dump(out_dir / "source_url_map.json", source_url_map)

    prefetch_queue_path = out_dir / "latest_queue.jsonl"
    prefetch_rows: list[dict[str, Any]] = []
    prefetch_summary: dict[str, Any] = {}
    if args.write_prefetch_queue:
        registry_by_fakeid = load_weekly_registry(args.weekly_registry)
        prefetch_rows, prefetch_summary = build_prefetch_rows(
            manifest=manifest,
            registry_by_fakeid=registry_by_fakeid,
            body_text_limit=max(0, args.body_text_limit),
        )
        jsonl_dump(prefetch_queue_path, prefetch_rows)

    sanji_refresh_summary_path = Path(os.environ["SANJI_CDP_FETCH_REFS_SUMMARY"]) if os.environ.get("SANJI_CDP_FETCH_REFS_SUMMARY") else None
    sanji_refresh_log_path = Path(os.environ["SANJI_CDP_REFRESH_LOG"]) if os.environ.get("SANJI_CDP_REFRESH_LOG") else None
    sanji_account_scope_path = Path(os.environ["SANJI_ACCOUNT_SCOPE_PATH"]) if os.environ.get("SANJI_ACCOUNT_SCOPE_PATH") else None
    sanji_completion_ledger_path = Path(os.environ["SANJI_COMPLETION_LEDGER_PATH"]) if os.environ.get("SANJI_COMPLETION_LEDGER_PATH") else None
    sanji_account_scope = read_json(sanji_account_scope_path) if sanji_account_scope_path else {}
    account_scope_counts = sanji_account_scope.get("counts") if isinstance(sanji_account_scope.get("counts"), dict) else {}
    account_scope_gate_passed = sanji_account_scope.get("gate_pass") is True
    sanji_refresh_report = read_json(sanji_refresh_log_path) if sanji_refresh_log_path else {}
    sanji_refresh_first = sanji_refresh_report.get("first") if isinstance(sanji_refresh_report.get("first"), dict) else {}
    sanji_refresh_credentials = sanji_refresh_first.get("credentials") if isinstance(sanji_refresh_first.get("credentials"), dict) else {}
    sequential_sync = sanji_refresh_report.get("sequential_sync") if isinstance(sanji_refresh_report.get("sequential_sync"), dict) else {}
    completion_ledger = read_json(sanji_completion_ledger_path) if sanji_completion_ledger_path else {}
    completion_summary = completion_ledger.get("summary") if isinstance(completion_ledger.get("summary"), dict) else {}
    refresh_channel = first_string(sanji_refresh_first.get("channel"))
    active_account_count = int(account_scope_counts.get("eligible_active_present") or 0)
    completed_account_count = int(completion_summary.get("completed_count") or sequential_sync.get("completed_count") or 0)
    full_scope_sync_completed = (
        completion_summary.get("cycle_complete") is True
        and completion_ledger.get("status") == "complete"
        and active_account_count > 0
        and completed_account_count == active_account_count
        and first_string(completion_ledger.get("account_scope_sha256"))
        == first_string(sanji_account_scope.get("eligible_fakeids_sha256"))
    )
    credential_gate_passed = (
        refresh_channel == "client"
        and account_scope_gate_passed
        and full_scope_sync_completed
    )
    sanji_refresh = {
        "enabled": os.environ.get("SANJI_CDP_REFRESH_ENABLED") == "1",
        "mode": first_string(os.environ.get("SANJI_CDP_REFRESH_MODE")),
        "cdp_port": first_string(os.environ.get("SANJI_CDP_PORT")),
        "refresh_log_path": first_string(os.environ.get("SANJI_CDP_REFRESH_LOG")),
        "fetch_log_path": first_string(os.environ.get("SANJI_CDP_FETCH_LOG")),
        "fetch_refs_path": first_string(os.environ.get("SANJI_CDP_FETCH_REFS")),
        "fetch_refs_summary_path": str(sanji_refresh_summary_path) if sanji_refresh_summary_path else "",
        "fetch_refs_summary": read_json(sanji_refresh_summary_path) if sanji_refresh_summary_path else {},
        "max_staleness_hours": first_string(os.environ.get("SANJI_CDP_MAX_STALENESS_HOURS")),
        "source_contract_version": first_string(os.environ.get("SANJI_SOURCE_CONTRACT")),
        "channel": refresh_channel,
        "coverage_scope": first_string(sanji_refresh_first.get("coverage_scope")),
        "ready_account_count_at_run_start": int(sanji_refresh_credentials.get("ready_count") or 0),
        "completed_account_count": completed_account_count,
        "full_scope_sync_completed": full_scope_sync_completed,
        "credential_gate_passed": credential_gate_passed,
        "account_scope_path": str(sanji_account_scope_path) if sanji_account_scope_path else "",
        "account_scope_gate_passed": account_scope_gate_passed,
        "account_scope_counts": account_scope_counts,
        "completion_ledger_path": str(sanji_completion_ledger_path) if sanji_completion_ledger_path else "",
        "completion_ledger_status": first_string(completion_ledger.get("status")),
        "completion_cycle_id": first_string(completion_ledger.get("cycle_id")),
        "secret_tables_read": False,
    }
    articles_path = sanji_root / "articles"
    client_channel_rows = sum(1 for row in manifest if row.get("acquisition_channel") == "wechat_client")
    legacy_or_unknown_rows = len(manifest) - client_channel_rows

    summary = {
        "ok": True,
        "source": "sanji_desktop",
        "source_mode": "sanji_desktop_client" if args.write_prefetch_queue else "sanji_desktop",
        "legacy_source_mode_alias": "sanji_desktop_rss" if args.write_prefetch_queue else "",
        "source_contract_version": "sanji_wechat_client.v1",
        "snapshot_source": "sanji_desktop_sqlite_backup",
        "sanji_db_snapshot_export": True,
        "snapshot_db_path": str(db_path),
        "generated_at": now.isoformat(),
        "sanji_root": str(sanji_root),
        "db_path": str(db_path),
        "storage_layout": {
            "schema_version": "sanji_storage_layout.v1",
            "tiering": "hot_articles_on_e_cold_archive_on_d",
            "sanji_root": str(sanji_root),
            "articles_path": str(articles_path),
            "articles_path_exists": articles_path.exists(),
            "articles_path_is_symlink": articles_path.is_symlink(),
            "articles_path_is_reparse_point": is_reparse_point(articles_path),
            "hot_articles_root": str(args.hot_articles_root),
            "hot_articles_root_exists": args.hot_articles_root.exists(),
            "cold_archive_root": str(args.cold_archive_root),
            "cold_archive_root_exists": args.cold_archive_root.exists(),
            "out_root": str(out_root),
            "note": "Keep Sanji DB and small app metadata on C; place the high-churn articles directory on fast E; keep old full copies and historical archives on cold D.",
        },
        "out_dir": str(out_dir),
        "weekly_registry": str(args.weekly_registry),
        "source_policy": str(args.source_policy) if args.source_policy else "",
        "source_policy_blocked_account_count": skipped.get("source_policy_blocked_account", 0),
        "source_policy_blocked_venue_count": skipped.get("source_policy_blocked_venue", 0),
        "lookback_days": args.lookback_days,
        "since_date": args.since_date,
        "cutoff_ts": cutoff_ts,
        "cutoff_iso": iso_from_epoch(cutoff_ts),
        "copy_mode": args.copy_mode,
        "include_unfetched": args.include_unfetched,
        "raw_window_rows": len(raw_rows),
        "exported_rows": manifest_count,
        "skipped_rows": skipped,
        "status_counts_all": status_counts_all,
        "status_counts_window": status_counts_window,
        "old_pre_2014_unfetched_counts": old_counts,
        "old_article_note": "Pre-2014 WeChat articles often require verification; unfetched/captcha rows are recorded but do not block daily exports.",
        "manifest_path": str(manifest_path),
        "source_url_map_path": str(out_dir / "source_url_map.json"),
        "prefetch_queue_written": bool(args.write_prefetch_queue),
        "prefetch_queue_path": str(prefetch_queue_path) if args.write_prefetch_queue else "",
        "prefetch_queue_rows": len(prefetch_rows),
        "prefetch_queue_summary": prefetch_summary,
        "acquisition_contract": {
            "schema_version": "sanji_wechat_client.v1",
            "channel": "wechat_client",
            "sanji_minimum_version": "1.1.0",
            "coverage_scope": "broadcast_only",
            "coverage_note": "The WeChat client channel lists group-broadcast articles; published but non-broadcast articles require explicit link ingestion.",
            "default_sync_window_hours": 168,
            "credential_scope": "per_public_account",
            "credential_list_ttl_minutes": 30,
            "credential_interaction_ttl_minutes": 90,
            "active_account_count": active_account_count,
            "completed_account_count": completed_account_count,
            "full_scope_sync_completed": full_scope_sync_completed,
            "client_channel_rows": client_channel_rows,
            "legacy_or_unknown_rows": legacy_or_unknown_rows,
            "refresh_channel": refresh_channel,
            "credential_gate_passed": credential_gate_passed,
            "account_scope_policy": first_string(sanji_account_scope.get("policy")),
            "account_scope_gate_passed": account_scope_gate_passed,
            "account_scope_counts": account_scope_counts,
            "inactive_accounts_excluded": int(account_scope_counts.get("excluded_inactive_present") or 0),
            "active_accounts_missing_from_sanji": int(account_scope_counts.get("active_missing_from_sanji") or 0),
            "completion_cycle_id": first_string(completion_ledger.get("cycle_id")),
            "completion_ledger_status": first_string(completion_ledger.get("status")),
            "backend_channel_enabled": False,
            "direct_rss_feed_fetch": False,
            "secret_tables_read": False,
        },
        "rss_contract": {
            "deprecated_compatibility_alias": True,
            "source": "Sanji desktop local SQLite snapshot after optional bounded renderer refresh",
            "direct_rss_feed_fetch": False,
            "direct_rss_feed_fetch_note": "false means this pipeline does not directly fetch public RSS/WeChat feeds; it exports from the local Sanji SQLite snapshot.",
            "sanji_desktop_refresh_invoked": sanji_refresh["enabled"],
            "sanji_db_snapshot_export": True,
            "snapshot_db_path": str(db_path),
            "snapshot_mechanism": "sqlite_backup_api",
            "secret_tables_read": False,
        },
        "sanji_refresh": sanji_refresh,
    }
    json_dump(out_dir / "summary.json", summary)

    readme = (
        "# Sanji Desktop Daily Export\n\n"
        f"- generated_at: `{summary['generated_at']}`\n"
        f"- exported_rows: `{manifest_count}`\n"
        f"- manifest: `{manifest_path}`\n"
        f"- source_url_map: `{out_dir / 'source_url_map.json'}`\n"
        f"- prefetch_queue: `{prefetch_queue_path if args.write_prefetch_queue else ''}`\n"
        f"- storage_layout: `{summary['storage_layout']['tiering']}` hot=`{args.hot_articles_root}` cold=`{args.cold_archive_root}`\n"
        "- secret policy: only article/account metadata is exported; Sanji identity, cookie, token, license, and credential tables are not read.\n"
        "- source contract: Sanji 1.1.x WeChat client channel, active-only per-account completion ledger, broadcast-only list coverage, exported through a local SQLite snapshot.\n"
        "- compatibility: rss_contract and sanji_desktop_rss remain output aliases only; no RSS or closed appmsgpublish endpoint is called.\n"
        "- old articles: pre-2014 unfetched/captcha rows are counted in summary and should not block daily automation.\n"
    )
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    if args.write_latest:
        write_latest(out_root, out_dir)

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
