#!/usr/bin/env python3
"""Export Sanji AppData cache into the ATLAS manifest contract.

Input is the local Sanji cache:
  <sanji-root>/sanji.db
  <sanji-root>/articles/<account_b64>/<aid>/index.html
  <sanji-root>/articles/<account_b64>/<aid>/assets/*

The exporter only reads `wechat_account` and `wechat_article` from sanji.db.
It never queries credential/cookie/token/license tables.

Outputs:
  manifest.json
  articles.jsonl
  assets.jsonl
  export_report.json

With `--formats md`, it also writes a compatibility archive under md_archive/.
Image assets are hardlinked by default; if hardlinking fails the archive keeps
path references and reports the fallback instead of copying large image trees.

With `--payload-copy-mode copy`, selected article cache directories are copied
to `<out>/payload/articles` and the manifest points there. This is intended for
daily delta exports so later extraction does not depend on mutable AppData
cache state.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SCHEMA = "sanji.cache.manifest.v1"
DEFAULT_SANJI_ROOT = os.path.join(os.environ.get("APPDATA", ""), "sanji")
ALLOWED_TABLES = {"wechat_account", "wechat_article"}
ACCOUNT_COLUMNS = [
    "fakeid",
    "nickname",
    "alias",
    "head_img",
    "service_type",
    "signature",
    "added_at",
    "last_sync_at",
    "total_messages",
    "synced_messages",
    "synced_articles",
    "last_begin",
    "is_complete",
    "complete_cutoff_ts",
    "last_error",
]
ARTICLE_COLUMNS = [
    "account_fakeid",
    "aid",
    "msgid",
    "itemidx",
    "link",
    "title",
    "cover",
    "digest",
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
    "paid_amount",
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
    "old_like_count",
    "share_count",
    "like_count",
    "comment_count",
    "html_path",
    "html_fetched_at",
    "resource_retry_count",
]
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}
SAFE_RE = re.compile(r"[^0-9A-Za-z._=-]+")


@dataclass
class ExportStats:
    account_count: int = 0
    db_article_count: int = 0
    emitted_article_count: int = 0
    html_found: int = 0
    missing_html: int = 0
    ignored_old_missing_html: int = 0
    actionable_missing_html: int = 0
    missing_assets: int = 0
    assets_count: int = 0
    publish_time_fill: int = 0
    md_articles: int = 0
    md_asset_hardlinks: int = 0
    md_asset_copies: int = 0
    md_asset_path_refs: int = 0
    md_asset_errors: int = 0
    exclude_token_count: int = 0
    excluded_seen_articles: int = 0
    payload_copied_articles: int = 0
    payload_copy_errors: int = 0
    missing_html_dispositions: list[dict] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def iso_from_epoch(value) -> str:
    if value in (None, "", 0):
        return ""
    try:
        ts = int(value)
    except Exception:
        return str(value)
    try:
        return datetime.fromtimestamp(ts).astimezone().replace(microsecond=0).isoformat()
    except Exception:
        return str(value)


def date_from_epoch(value) -> str:
    iso = iso_from_epoch(value)
    return iso[:10] if iso else ""


def safe_name(value: str, fallback: str = "unknown") -> str:
    value = (value or "").strip() or fallback
    value = SAFE_RE.sub("_", value)
    return value.strip("._ ") or fallback


def token_for(fakeid: str, aid: str) -> str:
    return "sanji_" + hashlib.sha1(f"{fakeid}:{aid}".encode("utf-8")).hexdigest()[:20]


def load_token_file(path: str | os.PathLike | None) -> set[str]:
    if not path:
        return set()
    token_path = Path(path)
    if not token_path.is_file():
        raise SystemExit(f"--exclude-token-file not found: {token_path}")
    tokens = set()
    with token_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            token = line.strip()
            if token and not token.startswith("#"):
                tokens.add(token)
    return tokens


def b64_account_dir(fakeid: str) -> str:
    return base64.b64encode((fakeid or "").encode("utf-8")).decode("ascii")


def rel_path(path: str | os.PathLike, root: str | os.PathLike) -> str:
    return os.path.relpath(os.path.abspath(path), os.path.abspath(root)).replace("\\", "/")


def is_under(path: Path, root: Path) -> bool:
    try:
        os.path.relpath(os.path.abspath(path), os.path.abspath(root))
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(root)]) == os.path.abspath(root)
    except ValueError:
        return False


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def atomic_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".jsonl", dir=str(path.parent))
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return count


def sqlite_columns(con: sqlite3.Connection, table: str) -> set[str]:
    if table not in ALLOWED_TABLES:
        raise RuntimeError(f"refuse to inspect non-whitelisted Sanji table: {table}")
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def select_existing(con: sqlite3.Connection, table: str, desired: list[str]) -> list[sqlite3.Row]:
    if table not in ALLOWED_TABLES:
        raise RuntimeError(f"refuse to query non-whitelisted Sanji table: {table}")
    cols = [c for c in desired if c in sqlite_columns(con, table)]
    if not cols:
        raise RuntimeError(f"no expected columns in {table}")
    quoted = ", ".join(cols)
    return con.execute(f"SELECT {quoted} FROM {table}").fetchall()


def row_dict(row: sqlite3.Row, cols: list[str]) -> dict:
    return {c: row[c] for c in cols if c in row.keys()}


def resolve_path(candidate: str, sanji_root: Path, articles_root: Path) -> Path | None:
    if not candidate:
        return None
    raw = Path(candidate)
    candidates = []
    source_articles_root = sanji_root / "articles"
    if raw.is_absolute():
        candidates.append(raw)
        if is_under(raw, source_articles_root):
            candidates.append(articles_root / rel_path(raw, source_articles_root))
    else:
        parts = raw.parts
        if parts and parts[0].lower() == "articles":
            candidates.append(articles_root.joinpath(*parts[1:]))
        candidates.extend([articles_root / raw, sanji_root / raw])
    for path in candidates:
        if path.is_file():
            return path
    return None


def resolve_article_html(article: dict, account: dict, sanji_root: Path, articles_root: Path) -> tuple[Path | None, str, Path]:
    fakeid = article.get("account_fakeid") or account.get("fakeid") or ""
    aid = str(article.get("aid") or "")
    article_dirs = [articles_root / fakeid / aid, articles_root / b64_account_dir(fakeid) / aid]
    for article_dir in article_dirs:
        computed = article_dir / "index.html"
        if computed.is_file():
            return computed, "computed_articles_root", article_dir
    for field in ("html_path", "content_path"):
        path = resolve_path(str(article.get(field) or ""), sanji_root, articles_root)
        if path and is_under(path, articles_root):
            return path, field, path.parent
    return None, "missing", article_dirs[0]


def iter_image_assets(article_dir: Path, fakeid: str, aid: str, articles_root: Path) -> list[dict]:
    assets_dir = article_dir / "assets"
    if not assets_dir.is_dir():
        return []
    rows = []
    try:
        entries = sorted(e for e in assets_dir.iterdir() if e.is_file() and e.suffix.lower() in IMG_EXT)
    except OSError:
        return []
    for order, path in enumerate(entries):
        stem = path.stem
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        rows.append({
            "kind": "image",
            "account_fakeid": fakeid,
            "aid": aid,
            "asset_id": f"{token_for(fakeid, aid)}#{order}",
            "cache_rel_path": rel_path(path, articles_root),
            "payload_rel_path": "",
            "bytes": path.stat().st_size,
            "mime": mime,
            "source_sha": stem,
            "filename": path.name,
            "source_url": "",
        })
    return rows


def crawl_status(article: dict) -> str:
    status = str(article.get("fetch_status") or "").strip()
    if status:
        return status
    if article.get("content_fetched"):
        return "content_fetched"
    if article.get("content_error"):
        return "content_error"
    return "unknown"


def missing_html_is_ignored_old(article: dict, ignore_missing_before_date: str) -> bool:
    if not ignore_missing_before_date:
        return False
    row_date = date_from_epoch(article.get("publish_time")) or date_from_epoch(article.get("create_time"))
    return bool(row_date and row_date < ignore_missing_before_date)


def missing_html_fetch_status_class(article: dict) -> str:
    """Return a bounded status class without copying raw errors into control artifacts."""
    raw = " ".join(
        str(article.get(name) or "").strip().lower()
        for name in ("fetch_status", "content_error")
    )
    if any(marker in raw for marker in ("captcha", "verify", "verification")):
        return "verification_required"
    if any(marker in raw for marker in ("timeout", "connection", "network")):
        return "transient_network_error"
    if any(marker in raw for marker in ("not fetched", "missing", "pending", "empty")):
        return "not_fetched"
    if any(marker in raw for marker in ("error", "fail")):
        return "fetch_error"
    return "unknown"


def missing_html_disposition(article: dict, ignore_missing_before_date: str) -> dict:
    ignored_old = missing_html_is_ignored_old(article, ignore_missing_before_date)
    fakeid = str(article.get("account_fakeid") or "")
    aid = str(article.get("aid") or "")
    retry_raw = article.get("fetch_retry_count")
    try:
        retry_count = max(0, int(retry_raw or 0))
    except (TypeError, ValueError):
        retry_count = 0
    return {
        # A one-way token is enough for retry correlation. Never place account
        # ids, article ids, titles, URLs, raw errors, body text, or paths here.
        "token": token_for(fakeid, aid),
        "post_date": date_from_epoch(article.get("publish_time"))
        or date_from_epoch(article.get("create_time")),
        "disposition": (
            "ignored_historical_before_cutoff" if ignored_old else "unresolved_retry_required"
        ),
        "reason": "html_not_found",
        "fetch_status_class": missing_html_fetch_status_class(article),
        "fetch_retry_count": retry_count,
    }


def normalize_account(account: dict) -> dict:
    return {
        "fakeid": account.get("fakeid") or "",
        "nickname": account.get("nickname") or "",
        "alias": account.get("alias") or "",
        "head_img": account.get("head_img") or "",
        "service_type": account.get("service_type"),
        "signature": account.get("signature") or "",
        "added_at": account.get("added_at"),
        "last_sync_at": account.get("last_sync_at"),
        "total_messages": account.get("total_messages"),
        "synced_messages": account.get("synced_messages"),
        "synced_articles": account.get("synced_articles"),
        "is_complete": account.get("is_complete"),
    }


def normalize_article(article: dict, html_path: Path, article_dir: Path, account: dict) -> dict:
    publish_iso = iso_from_epoch(article.get("publish_time"))
    create_iso = iso_from_epoch(article.get("create_time"))
    post_date = (publish_iso or create_iso)[:10]
    return {
        "account_fakeid": article.get("account_fakeid") or account.get("fakeid") or "",
        "aid": str(article.get("aid") or ""),
        "msgid": article.get("msgid"),
        "itemidx": article.get("itemidx"),
        "link": article.get("link") or "",
        "title": article.get("title") or "",
        "cover": article.get("cover") or "",
        "digest": article.get("digest") or "",
        "create_time": create_iso,
        "create_time_ts": article.get("create_time"),
        "publish_time": publish_iso,
        "publish_time_ts": article.get("publish_time"),
        "post_date": post_date,
        "article_type": article.get("article_type"),
        "is_deleted": article.get("is_deleted"),
        "author": article.get("author") or "",
        "is_original": article.get("is_original"),
        "media_duration": article.get("media_duration"),
        "album_id": article.get("album_id") or "",
        "album_name": article.get("album_name") or "",
        "is_paid": article.get("is_paid"),
        "paid_amount": article.get("paid_amount"),
        "fetched_at": iso_from_epoch(article.get("fetched_at")),
        "content_fetched": article.get("content_fetched"),
        "content_size": article.get("content_size"),
        "content_fetched_at": iso_from_epoch(article.get("content_fetched_at")),
        "content_error": article.get("content_error") or "",
        "fetch_status": article.get("fetch_status") or "",
        "fetch_retry_count": article.get("fetch_retry_count"),
        "content_resources_failed": article.get("content_resources_failed"),
        "comment_fetched": article.get("comment_fetched"),
        "read_count": article.get("read_num"),
        "like_count": article.get("like_count"),
        "old_like_count": article.get("old_like_count"),
        "share_count": article.get("share_count"),
        "comment_count": article.get("comment_count"),
        "crawl_status": crawl_status(article),
        "content_path": article.get("content_path") or "",
        "html_path": article.get("html_path") or "",
        "html_fetched_at": iso_from_epoch(article.get("html_fetched_at")),
        "resource_retry_count": article.get("resource_retry_count"),
        "html_bytes": html_path.stat().st_size,
        "cache_article_dir": str(article_dir),
    }


def copy_or_link_asset(src: Path, dst: Path, mode: str, stats: ExportStats) -> tuple[str, str]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "manifest-only":
        stats.md_asset_path_refs += 1
        return str(src), "path_ref"
    if dst.exists():
        return str(dst), "existing"
    if mode == "copy":
        shutil.copy2(src, dst)
        stats.md_asset_copies += 1
        return str(dst), "copy"
    try:
        os.link(src, dst)
        stats.md_asset_hardlinks += 1
        return str(dst), "hardlink"
    except OSError as exc:
        stats.md_asset_path_refs += 1
        stats.md_asset_errors += 1
        return str(src), f"hardlink_failed_path_ref:{exc.__class__.__name__}"


def copy_payload_article_dir(src_dir: Path, articles_root: Path, payload_root: Path, stats: ExportStats) -> bool:
    rel = rel_path(src_dir, articles_root)
    dst_dir = payload_root / rel
    try:
        shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True, copy_function=shutil.copy2)
        stats.payload_copied_articles += 1
        return True
    except OSError:
        stats.payload_copy_errors += 1
        return False


def write_md_article(
    out_root: Path,
    account: dict,
    article: dict,
    cache: dict,
    html_path: Path,
    assets: list[dict],
    articles_root: Path,
    md_asset_mode: str,
    md_html_mode: str,
    stats: ExportStats,
) -> None:
    fakeid = article["account_fakeid"]
    aid = article["aid"]
    token = token_for(fakeid, aid)
    account_name = safe_name(account.get("nickname") or fakeid)
    article_root = out_root / "md_archive" / account_name / token
    article_root.mkdir(parents=True, exist_ok=True)
    if md_html_mode == "copy":
        shutil.copyfile(html_path, article_root / "raw.html")
        raw_html_ref = "raw.html"
        raw_html_local_path = str(article_root / "raw.html")
    else:
        raw_html_ref = ""
        raw_html_local_path = str(html_path)

    asset_rows = []
    for item in assets:
        src = articles_root / item["cache_rel_path"]
        dst = article_root / "assets" / item["filename"]
        local_path, link_status = copy_or_link_asset(src, dst, md_asset_mode, stats)
        asset_rows.append({
            "asset_id": item["asset_id"],
            "local_path": local_path,
            "file_size": item["bytes"],
            "content_type": item["mime"],
            "status": "downloaded",
            "source_sha": item["source_sha"],
            "source_url": item.get("source_url", ""),
            "cache_rel_path": item["cache_rel_path"],
            "link_status": link_status,
        })

    atomic_json(article_root / "assets_local.json", {
        "schema": "atlas.assets_local.v1",
        "source": "sanji_appdata_export_md",
        "asset_mode": md_asset_mode,
        "images": asset_rows,
    })
    atomic_json(article_root / "archive_meta.json", {
        "schema": "atlas.archive_meta.v1",
        "source": "sanji_appdata_export_md",
        "title": article.get("title") or "",
        "source_url": article.get("link") or "",
        "archived_at": article.get("publish_time") or article.get("create_time") or "",
        "account": account,
        "article": article,
        "cache": cache,
        "raw_html": raw_html_ref,
        "raw_html_local_path": raw_html_local_path,
        "html_mode": md_html_mode,
    })
    md = [
        f"# {article.get('title') or token}",
        "",
        f"- token: {token}",
        f"- account: {account.get('nickname') or fakeid}",
        f"- source_url: {article.get('link') or ''}",
        f"- post_date: {article.get('post_date') or ''}",
        f"- raw_html: {raw_html_ref or raw_html_local_path}",
        f"- assets: {len(asset_rows)}",
        "",
    ]
    (article_root / "README.md").write_text("\n".join(md), encoding="utf-8", newline="\n")
    stats.md_articles += 1


def build_rows(
    db_path: Path,
    sanji_root: Path,
    articles_root: Path,
    out_root: Path,
    limit: int,
    formats: set[str],
    md_asset_mode: str,
    md_html_mode: str,
    stats: ExportStats,
    exclude_tokens: set[str] | None = None,
    payload_copy_mode: str = "none",
    ignore_missing_before_date: str = "2014-01-01",
) -> tuple[list[dict], list[dict], dict]:
    # Sanji may keep writing its WAL while the nightly Atlas job starts. Read a
    # SQLite backup snapshot so the long metadata scan sees one stable database
    # image and never races the Electron writer.
    with tempfile.TemporaryDirectory(prefix="atlas_sanji_snapshot_") as temp_dir:
        snapshot_path = Path(temp_dir) / "sanji.snapshot.db"
        source = sqlite3.connect(str(db_path))
        try:
            snapshot = sqlite3.connect(str(snapshot_path))
            try:
                source.backup(snapshot)
            finally:
                snapshot.close()
        finally:
            source.close()

        con = sqlite3.connect(str(snapshot_path))
        con.row_factory = sqlite3.Row
        try:
            account_cols = [c for c in ACCOUNT_COLUMNS if c in sqlite_columns(con, "wechat_account")]
            article_cols = [c for c in ARTICLE_COLUMNS if c in sqlite_columns(con, "wechat_article")]
            accounts = {
                row["fakeid"]: row_dict(row, account_cols)
                for row in select_existing(con, "wechat_account", ACCOUNT_COLUMNS)
                if row["fakeid"]
            }
            stats.account_count = len(accounts)
            articles = [
                row_dict(row, article_cols)
                for row in select_existing(con, "wechat_article", ARTICLE_COLUMNS)
            ]
        finally:
            con.close()

    rows = []
    asset_rows = []
    stats.db_article_count = len(articles)
    excluded = exclude_tokens or set()
    stats.exclude_token_count = len(excluded)
    payload_root = out_root / "payload" / "articles"
    for raw_article in articles:
        if raw_article.get("is_deleted"):
            continue
        fakeid = raw_article.get("account_fakeid") or ""
        aid = str(raw_article.get("aid") or "")
        if excluded and token_for(fakeid, aid) in excluded:
            stats.excluded_seen_articles += 1
            continue
        account = normalize_account(accounts.get(fakeid, {"fakeid": fakeid}))
        html_path, html_source, article_dir = resolve_article_html(raw_article, account, sanji_root, articles_root)
        if not html_path:
            stats.missing_html += 1
            disposition = missing_html_disposition(raw_article, ignore_missing_before_date)
            stats.missing_html_dispositions.append(disposition)
            if disposition["disposition"] == "ignored_historical_before_cutoff":
                stats.ignored_old_missing_html += 1
            else:
                stats.actionable_missing_html += 1
            continue
        # The processing limit must never hide a missing-HTML row later in the
        # unseen set. Continue scanning after the payload limit, but only emit
        # the requested number of complete articles.
        if limit and stats.emitted_article_count >= limit:
            continue
        stats.html_found += 1
        normalized_article = normalize_article(raw_article, html_path, article_dir, account)
        if normalized_article.get("post_date"):
            stats.publish_time_fill += 1
        if payload_copy_mode == "copy":
            if not copy_payload_article_dir(article_dir, articles_root, payload_root, stats):
                continue
        cache = {
            "html_rel_path": rel_path(html_path, articles_root),
            "payload_html_rel_path": "",
            "article_dir_rel_path": rel_path(article_dir, articles_root),
            "html_path_source": html_source,
        }
        article_assets = iter_image_assets(article_dir, fakeid, normalized_article["aid"], articles_root)
        if not article_assets:
            stats.missing_assets += 1
        stats.assets_count += len(article_assets)
        rows.append({"account": account, "article": normalized_article, "cache": cache})
        asset_rows.extend(article_assets)
        if "md" in formats:
            md_articles_root = payload_root if payload_copy_mode == "copy" else articles_root
            md_html_path = md_articles_root / rel_path(html_path, articles_root)
            write_md_article(out_root, account, normalized_article, cache, md_html_path, article_assets,
                             md_articles_root, md_asset_mode, md_html_mode, stats)
        stats.emitted_article_count += 1

    manifest = {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "source": "sanji_appdata",
        "sanji_root": str(sanji_root),
        "db_path": str(db_path),
        "db_snapshot_read": True,
        "snapshot_mechanism": "sqlite_backup_api",
        "cache_root": str(payload_root if payload_copy_mode == "copy" else articles_root),
        "articles_jsonl": "articles.jsonl",
        "assets_jsonl": "assets.jsonl",
        "article_count": len(rows),
        "asset_count": len(asset_rows),
        "account_count": stats.account_count,
        "formats": sorted(formats),
        "md_archive_rel_path": "md_archive" if "md" in formats else "",
        "md_asset_mode": md_asset_mode,
        "md_html_mode": md_html_mode if "md" in formats else "",
        "payload_copy_mode": payload_copy_mode,
        "old_missing_html_policy": f"missing HTML before {ignore_missing_before_date} is retained in reports but ignored as a non-blocking historical download gap",
        "metadata_policy": {
            "stage2_extracts": "article title plus cleaned body text plus selected poster images",
            "metadata_fields": "post_date/source_url/account/read_count/like_count/crawl_status from Sanji DB",
            "derived_fields": "relations/trust/scene downstream only",
            "same_label": "disabled",
            "b2b": "kept",
        },
    }
    return rows, asset_rows, manifest


def export_manifest(
    sanji_root: Path,
    db_path: Path,
    articles_root: Path,
    out_root: Path,
    limit: int,
    formats: set[str],
    md_asset_mode: str,
    md_html_mode: str,
    exclude_tokens: set[str] | None = None,
    payload_copy_mode: str = "none",
    ignore_missing_before_date: str = "2014-01-01",
) -> dict:
    if not db_path.is_file():
        raise SystemExit(f"sanji.db not found: {db_path}")
    if not articles_root.is_dir():
        raise SystemExit(f"Sanji articles root not found: {articles_root}")
    out_root.mkdir(parents=True, exist_ok=True)
    stats = ExportStats()
    rows, asset_rows, manifest = build_rows(
        db_path,
        sanji_root,
        articles_root,
        out_root,
        limit,
        formats,
        md_asset_mode,
        md_html_mode,
        stats,
        exclude_tokens=exclude_tokens,
        payload_copy_mode=payload_copy_mode,
        ignore_missing_before_date=ignore_missing_before_date,
    )
    atomic_jsonl(out_root / "articles.jsonl", rows)
    atomic_jsonl(out_root / "assets.jsonl", asset_rows)
    missing_ledger_name = "missing_html_dispositions.jsonl"
    missing_digest_name = "missing_html_digest.json"
    missing_ledger_path = out_root / missing_ledger_name
    atomic_jsonl(missing_ledger_path, stats.missing_html_dispositions)
    ledger_sha256 = hashlib.sha256(missing_ledger_path.read_bytes()).hexdigest()
    disposition_counts: dict[str, int] = {}
    for row in stats.missing_html_dispositions:
        disposition = str(row["disposition"])
        disposition_counts[disposition] = disposition_counts.get(disposition, 0) + 1
    missing_digest = {
        "schema": "sanji.missing_html_digest.v1",
        "generated_at": manifest["generated_at"],
        "total_missing_html": stats.missing_html,
        "unresolved_missing_html": stats.actionable_missing_html,
        "disposed_nonblocking_missing_html": stats.ignored_old_missing_html,
        "disposition_counts": disposition_counts,
        "ignore_missing_before_date": ignore_missing_before_date,
        "ledger_rel_path": missing_ledger_name,
        "ledger_sha256": ledger_sha256,
        "privacy_contract": (
            "token_date_disposition_only_no_account_ids_article_ids_titles_urls_errors_body_or_paths"
        ),
    }
    atomic_json(out_root / missing_digest_name, missing_digest)
    manifest["missing_html_contract"] = {
        "digest_rel_path": missing_digest_name,
        "ledger_rel_path": missing_ledger_name,
        "unresolved_missing_html": stats.actionable_missing_html,
    }
    atomic_json(out_root / "manifest.json", manifest)
    report = {
        "schema": "sanji.appdata.export_report.v1",
        "generated_at": manifest["generated_at"],
        "out_root": str(out_root),
        "sanji_root": str(sanji_root),
        "db_path": str(db_path),
        "articles_root": str(articles_root),
        "formats": sorted(formats),
        "md_asset_mode": md_asset_mode,
        "md_html_mode": md_html_mode if "md" in formats else "",
        "limit": limit,
        "tables_read": sorted(ALLOWED_TABLES),
        "secret_tables_read": [],
        "exclude_token_count": stats.exclude_token_count,
        "excluded_seen_articles": stats.excluded_seen_articles,
        "account_count": stats.account_count,
        "db_article_count": stats.db_article_count,
        "article_count": stats.emitted_article_count,
        "html_found": stats.html_found,
        "missing_html": stats.missing_html,
        "ignore_missing_before_date": ignore_missing_before_date,
        "ignored_old_missing_html": stats.ignored_old_missing_html,
        "actionable_missing_html": stats.actionable_missing_html,
        "unresolved_missing_html": stats.actionable_missing_html,
        "missing_html_ledger_rel_path": missing_ledger_name,
        "missing_html_ledger_sha256": ledger_sha256,
        "missing_html_digest_rel_path": missing_digest_name,
        "assets_count": stats.assets_count,
        "missing_assets": stats.missing_assets,
        "publish_time_fill": stats.publish_time_fill,
        "publish_time_fill_rate": round(stats.publish_time_fill / stats.emitted_article_count, 4) if stats.emitted_article_count else None,
        "md_articles": stats.md_articles,
        "md_asset_hardlinks": stats.md_asset_hardlinks,
        "md_asset_copies": stats.md_asset_copies,
        "md_asset_path_refs": stats.md_asset_path_refs,
        "md_asset_errors": stats.md_asset_errors,
        "payload_copy_mode": payload_copy_mode,
        "payload_copied_articles": stats.payload_copied_articles,
        "payload_copy_errors": stats.payload_copy_errors,
        "boundary": "candidate_only_no_production_write_no_secret_tables",
    }
    atomic_json(out_root / "export_report.json", report)
    return report


def parse_formats(value: str) -> set[str]:
    formats = {x.strip().lower() for x in value.split(",") if x.strip()}
    bad = formats - {"json", "md"}
    if bad:
        raise SystemExit(f"unsupported --formats value(s): {', '.join(sorted(bad))}")
    return formats or {"json"}


def create_self_check_fixture(root: Path) -> tuple[Path, Path, Path]:
    sanji_root = root / "sanji"
    articles_root = sanji_root / "articles"
    articles_root.mkdir(parents=True)
    db_path = sanji_root / "sanji.db"
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE wechat_account (fakeid TEXT PRIMARY KEY, nickname TEXT, alias TEXT)")
    con.execute("""CREATE TABLE wechat_article (
        account_fakeid TEXT, aid TEXT, msgid INTEGER, itemidx INTEGER, link TEXT, title TEXT,
        cover TEXT, digest TEXT, create_time INTEGER, publish_time INTEGER, article_type INTEGER,
        is_deleted INTEGER, author TEXT, is_original INTEGER, media_duration INTEGER,
        album_id TEXT, album_name TEXT, is_paid INTEGER, fetched_at INTEGER, paid_amount INTEGER,
        content_fetched INTEGER, content_path TEXT, content_size INTEGER, content_fetched_at INTEGER,
        content_error TEXT, fetch_status TEXT, fetch_retry_count INTEGER, content_resources_failed INTEGER,
        comment_fetched INTEGER, read_num INTEGER, old_like_count INTEGER, share_count INTEGER,
        like_count INTEGER, comment_count INTEGER, html_path TEXT, html_fetched_at INTEGER,
        resource_retry_count INTEGER
    )""")
    con.execute("CREATE TABLE credential_store (secret TEXT)")
    accounts = [("fakeid_a", "Account A", "a"), ("fakeid_b", "Account B", "b")]
    con.executemany("INSERT INTO wechat_account VALUES (?,?,?)", accounts)
    rows = [
        ("fakeid_a", "same_aid", 1, 1, "https://mp/a", "A Party", "", "digest", 1717200000, 1717286400, 1, 0, "author", 0, 0, "", "", 0, 1717286500, 0, 1, "", 123, 1717286600, "", "ok", 0, 0, 0, 11, 1, 2, 3, 4, "", 1717286600, 0),
        ("fakeid_b", "same_aid", 2, 1, "https://mp/b", "B Party", "", "", 1717200100, 1717286500, 1, 0, "", 0, 0, "", "", 0, 1717286500, 0, 1, "", 456, 1717286600, "", "ok", 0, 0, 0, 22, 2, 3, 4, 5, "", 1717286600, 0),
        ("fakeid_a", "no_image", 3, 1, "https://mp/c", "No Image", "", "", 1717200200, 0, 1, 0, "", 0, 0, "", "", 0, 1717286500, 0, 1, "", 100, 1717286600, "", "ok", 0, 0, 0, None, None, None, None, None, "", 1717286600, 0),
        ("fakeid_a", "missing_html", 4, 1, "https://mp/d", "Missing HTML", "", "", 1717200300, 1717286700, 1, 0, "", 0, 0, "", "", 0, 1717286500, 0, 0, "", 0, 0, "not fetched", "missing", 0, 1, 0, 0, 0, 0, 0, 0, "", 0, 0),
    ]
    con.executemany("INSERT INTO wechat_article VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    for fakeid, aid, asset_count in (("fakeid_a", "same_aid", 2), ("fakeid_b", "same_aid", 1), ("fakeid_a", "no_image", 0)):
        article_dir = articles_root / b64_account_dir(fakeid) / aid
        article_dir.mkdir(parents=True)
        (article_dir / "index.html").write_text(f"<html><title>{aid}</title><body>{fakeid} {aid}</body></html>", encoding="utf-8")
        if asset_count:
            asset_dir = article_dir / "assets"
            asset_dir.mkdir()
            for i in range(asset_count):
                (asset_dir / f"sha{i}.jpg").write_bytes(b"\xff\xd8\xff\xe0" + bytes([i]) * 256)
    return sanji_root, db_path, articles_root


def self_check() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_sanji_exporter_") as td:
        root = Path(td)
        sanji_root, db_path, articles_root = create_self_check_fixture(root)
        out = root / "out"
        report = export_manifest(sanji_root, db_path, articles_root, out, 0, {"json", "md"}, "hardlink", "copy")
        assert report["secret_tables_read"] == []
        assert report["account_count"] == 2
        assert report["article_count"] == 3
        assert report["html_found"] == 3
        assert report["missing_html"] == 1
        assert report["assets_count"] == 3
        assert report["missing_assets"] == 1
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["schema"] == SCHEMA
        article_rows = [json.loads(line) for line in (out / "articles.jsonl").read_text(encoding="utf-8").splitlines()]
        tokens = {token_for(r["article"]["account_fakeid"], r["article"]["aid"]) for r in article_rows}
        assert len(tokens) == 3, "aid must be unique across accounts through fakeid+aid token"
        assert all((r["article"].get("publish_time") or r["article"].get("create_time")) for r in article_rows)
        assets = [json.loads(line) for line in (out / "assets.jsonl").read_text(encoding="utf-8").splitlines()]
        assert all(a["cache_rel_path"] and a["bytes"] > 0 and a["mime"] for a in assets)
        assert report["md_articles"] == 3
        exclude_file = root / "exclude_tokens.txt"
        excluded_token = token_for("fakeid_a", "same_aid")
        exclude_file.write_text(excluded_token + "\n", encoding="utf-8", newline="\n")
        delta_out = root / "delta_out"
        delta_report = export_manifest(
            sanji_root,
            db_path,
            articles_root,
            delta_out,
            0,
            {"json"},
            "manifest-only",
            "path-ref",
            exclude_tokens=load_token_file(exclude_file),
            payload_copy_mode="copy",
        )
        assert delta_report["exclude_token_count"] == 1
        assert delta_report["excluded_seen_articles"] == 1
        assert delta_report["article_count"] == 2
        assert delta_report["payload_copy_mode"] == "copy"
        assert delta_report["payload_copied_articles"] == 2
        assert delta_report["actionable_missing_html"] == 1
        assert delta_report["ignored_old_missing_html"] == 0
        delta_manifest = json.loads((delta_out / "manifest.json").read_text(encoding="utf-8"))
        assert (Path(delta_manifest["cache_root"]) / b64_account_dir("fakeid_b") / "same_aid" / "index.html").is_file()
    print("self-check OK: exporter manifest/jsonl/md archive contracts")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-check", action="store_true")
    ap.add_argument("--sanji-root", default=DEFAULT_SANJI_ROOT)
    ap.add_argument("--db", default="")
    ap.add_argument("--articles-root", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--limit", type=int, default=0, help="0 = all html-backed articles")
    ap.add_argument("--formats", default="json", help="comma-separated: json,md")
    ap.add_argument("--md-asset-mode", choices=["hardlink", "manifest-only", "copy"], default="hardlink")
    ap.add_argument("--md-html-mode", choices=["copy", "path-ref"], default="copy")
    ap.add_argument("--exclude-token-file", default="", help="one exported token per line; skipped before HTML/assets resolution")
    ap.add_argument("--payload-copy-mode", choices=["none", "copy"], default="none", help="copy selected article cache dirs under <out>/payload/articles")
    ap.add_argument("--ignore-missing-before-date", default="2014-01-01", help="missing live HTML before this YYYY-MM-DD is counted but non-blocking")
    args = ap.parse_args()
    if args.self_check:
        self_check()
        return 0
    if not args.out:
        ap.error("--out is required unless --self-check is used")
    sanji_root = Path(args.sanji_root).resolve()
    db_path = Path(args.db).resolve() if args.db else sanji_root / "sanji.db"
    articles_root = Path(args.articles_root).resolve() if args.articles_root else sanji_root / "articles"
    formats = parse_formats(args.formats)
    report = export_manifest(
        sanji_root,
        db_path,
        articles_root,
        Path(args.out).resolve(),
        args.limit,
        formats,
        args.md_asset_mode,
        args.md_html_mode,
        exclude_tokens=load_token_file(args.exclude_token_file),
        payload_copy_mode=args.payload_copy_mode,
        ignore_missing_before_date=args.ignore_missing_before_date,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
