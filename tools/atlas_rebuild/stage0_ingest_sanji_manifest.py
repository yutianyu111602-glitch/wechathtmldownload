"""Stage 0 adapter for Sanji JSONL cache manifests.

Converts a Sanji export directory:
  manifest.json
  articles.jsonl
  assets.jsonl

into the existing ATLAS Stage0 contract:
  ingest_index.sqlite
  sanji_manifest_archive/<account>/<token>/raw.html
  sanji_manifest_archive/<account>/<token>/assets_local.json
  sanji_manifest_archive/<account>/<token>/archive_meta.json

Images are not copied by default. assets_local.json points at the existing
Sanji payload/cache files, and Stage1 copies only the selected poster
candidates into ATLAS_WORK_DIR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from stage0_ingest import SCHEMA


_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._=-]+")


def _load_json(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def _iter_jsonl(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"bad jsonl at {path}:{line_no}: {exc}") from exc


def _safe_name(value, fallback="unknown"):
    value = (value or "").strip() or fallback
    value = _SAFE_NAME_RE.sub("_", value)
    return value.strip("._ ") or fallback


def _token(fakeid, aid):
    raw = f"{fakeid}:{aid}"
    return "sanji_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _resolve_rel(root, rel):
    if not rel:
        return ""
    path = os.path.abspath(os.path.join(root, rel))
    return path if os.path.isfile(path) else ""


def _resolve_payload_or_cache(manifest_root, cache_root, payload_rel, cache_rel):
    payload_path = _resolve_rel(manifest_root, payload_rel)
    if payload_path:
        return payload_path
    return _resolve_rel(cache_root, cache_rel)


def _article_key(article_row):
    article = article_row.get("article") or {}
    fakeid = article.get("account_fakeid") or (article_row.get("account") or {}).get("fakeid") or ""
    aid = article.get("aid") or ""
    return fakeid, aid


def _load_skip_tokens(path):
    if not path:
        return set()
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise SystemExit(f"skip token file not found: {path}")
    tokens = set()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            token = line.strip()
            if not token or token.startswith("#"):
                continue
            tokens.add(token)
    return tokens


def _load_assets_by_article(manifest_root, cache_root, assets_path, article_keys=None):
    by_article = defaultdict(list)
    if not os.path.isfile(assets_path):
        return by_article
    wanted_keys = set(article_keys or [])
    for row in _iter_jsonl(assets_path):
        if row.get("kind") and row.get("kind") != "image":
            continue
        fakeid = row.get("account_fakeid") or ""
        aid = row.get("aid") or ""
        key = (fakeid, aid)
        if wanted_keys and key not in wanted_keys:
            continue
        src = _resolve_payload_or_cache(
            manifest_root,
            cache_root,
            row.get("payload_rel_path"),
            row.get("cache_rel_path"),
        )
        if not src:
            continue
        by_article[(fakeid, aid)].append({
            "asset_id": row.get("asset_id") or row.get("source_sha") or os.path.basename(src),
            "local_path": src,
            "file_size": row.get("bytes") or os.path.getsize(src),
            "content_type": row.get("mime") or "application/octet-stream",
            "status": "downloaded",
            "source_url": row.get("source_url") or "",
            "source_sha": row.get("source_sha") or "",
            "cache_rel_path": row.get("cache_rel_path") or "",
            "payload_rel_path": row.get("payload_rel_path") or "",
        })
    return by_article


def _atomic_write_json(path, payload):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _copy_html(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _want_account(account, wanted):
    if not wanted:
        return True
    fakeid = account.get("fakeid") or ""
    nickname = account.get("nickname") or ""
    alias = account.get("alias") or ""
    return fakeid in wanted or nickname in wanted or alias in wanted


def ingest_manifest(manifest_root, accounts="", limit=0, materialized_root="", skip_tokens_file=""):
    manifest_root = os.path.abspath(manifest_root)
    manifest_path = os.path.join(manifest_root, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise SystemExit(f"manifest.json not found: {manifest_path}")
    manifest = _load_json(manifest_path)
    if manifest.get("schema") != "sanji.cache.manifest.v1":
        raise SystemExit(f"unsupported Sanji manifest schema: {manifest.get('schema')}")

    cache_root = os.path.abspath(manifest.get("cache_root") or manifest_root)
    articles_path = os.path.join(manifest_root, manifest.get("articles_jsonl") or "articles.jsonl")
    assets_path = os.path.join(manifest_root, manifest.get("assets_jsonl") or "assets.jsonl")
    if not os.path.isfile(articles_path):
        raise SystemExit(f"articles.jsonl not found: {articles_path}")

    config.ensure_dirs()
    out_root = os.path.abspath(materialized_root or os.path.join(config.WORK_DIR, "sanji_manifest_archive"))
    if os.path.commonpath([os.path.abspath(config.WORK_DIR), out_root]) != os.path.abspath(config.WORK_DIR):
        raise SystemExit(f"refuse to materialize outside ATLAS_WORK_DIR: {out_root}")

    wanted = {x.strip() for x in accounts.split(",") if x.strip()}
    skip_tokens = _load_skip_tokens(skip_tokens_file)
    selected_rows = []
    skipped_no_html = skipped_account = skipped_token = 0
    for row in _iter_jsonl(articles_path):
        account = row.get("account") or {}
        article = row.get("article") or {}
        cache = row.get("cache") or {}
        if not _want_account(account, wanted):
            skipped_account += 1
            continue

        fakeid, aid = _article_key(row)
        if not fakeid or not aid:
            skipped_no_html += 1
            continue
        token = _token(fakeid, aid)
        if token in skip_tokens:
            skipped_token += 1
            continue
        html_src = _resolve_payload_or_cache(
            manifest_root,
            cache_root,
            cache.get("payload_html_rel_path"),
            cache.get("html_rel_path") or article.get("content_path"),
        )
        if not html_src:
            skipped_no_html += 1
            continue

        selected_rows.append((row, fakeid, aid, html_src))
        if limit and len(selected_rows) >= limit:
            break

    selected_keys = {(fakeid, aid) for _, fakeid, aid, _ in selected_rows}
    assets_by_article = (
        _load_assets_by_article(manifest_root, cache_root, assets_path, selected_keys)
        if selected_keys
        else {}
    )

    con = sqlite3.connect(config.DB_INGEST)
    con.executescript(SCHEMA)
    inserted = 0
    total_assets = 0
    for row, fakeid, aid, html_src in selected_rows:
        account = row.get("account") or {}
        article = row.get("article") or {}
        cache = row.get("cache") or {}
        token = _token(fakeid, aid)
        account_key = account.get("nickname") or fakeid
        article_dir = os.path.join(out_root, _safe_name(account_key), token)
        raw_html = os.path.join(article_dir, "raw.html")
        assets_json = os.path.join(article_dir, "assets_local.json")
        meta_json = os.path.join(article_dir, "archive_meta.json")

        _copy_html(html_src, raw_html)
        images = assets_by_article.get((fakeid, aid), [])
        _atomic_write_json(assets_json, {
            "schema": "atlas.assets_local.v1",
            "source": "sanji_manifest",
            "manifest_root": manifest_root,
            "cache_root": cache_root,
            "images": images,
        })
        archived_at = str(article.get("publish_time") or article.get("create_time") or "")
        _atomic_write_json(meta_json, {
            "schema": "atlas.archive_meta.v1",
            "source": "sanji_manifest",
            "title": article.get("title") or "",
            "source_url": article.get("link") or "",
            "archived_at": archived_at,
            "raw_html_bytes": os.path.getsize(raw_html),
            "account": account,
            "article": article,
            "cache": cache,
        })

        con.execute(
            "INSERT OR REPLACE INTO ingest VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                token,
                account_key,
                article.get("title") or "",
                article.get("link") or "",
                archived_at,
                raw_html,
                assets_json,
                len(images),
                os.path.getsize(raw_html),
                "ingested_sanji_manifest",
            ),
        )
        inserted += 1
        total_assets += len(images)
        if inserted % 200 == 0:
            con.commit()
            print(f"  ingested {inserted}...")

    con.commit()
    table_total = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
    con.close()
    print(
        "Stage0 Sanji manifest done: "
        f"+{inserted} articles assets={total_assets} "
        f"(skipped_account={skipped_account}, skipped_token={skipped_token}, "
        f"skipped_no_html={skipped_no_html}), "
        f"ingest table total={table_total}"
    )
    print(f"  manifest_root={manifest_root}")
    print(f"  materialized_root={out_root}")
    print(f"  -> {config.DB_INGEST}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest-root", required=True, help="directory containing Sanji manifest.json")
    ap.add_argument("--accounts", default="", help="comma-separated nickname/fakeid/alias filter")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    ap.add_argument("--materialized-root", default="", help="default: ATLAS_WORK_DIR/sanji_manifest_archive")
    ap.add_argument("--skip-tokens-file", default="", help="one token per line; skipped before limit counting")
    args = ap.parse_args()
    ingest_manifest(args.manifest_root, args.accounts, args.limit, args.materialized_root, args.skip_tokens_file)


if __name__ == "__main__":
    main()
