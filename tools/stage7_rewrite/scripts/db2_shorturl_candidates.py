from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any, Iterable
from urllib.parse import urlsplit

import build_db2_outlink_lineage_reconcile_s125 as lineage


REDIRECT_SHORTENER_HOSTS = frozenset(
    {
        "bit.ly",
        "buff.ly",
        "is.gd",
        "ow.ly",
        "rebrand.ly",
        "shorturl.at",
        "shrtco.de",
        "t.co",
        "tiny.cc",
        "tinyurl.com",
        "urlgeni.us",
        "v.gd",
    }
)

LINK_IN_BIO_LANDING_HOSTS = frozenset(
    {
        "allmylinks.com",
        "beacons.ai",
        "bento.me",
        "bio.fm",
        "bio.link",
        "campsite.bio",
        "direct.me",
        "ffm.bio",
        "hoo.be",
        "hyperurl.co",
        "iglink.io",
        "later.com",
        "layer.bio",
        "liinks.co",
        "link.space",
        "linkin.bio",
        "li.sten.to",
        "lnk.to",
        "lynxinbio.com",
        "msha.ke",
        "myurls.co",
        "piff.me",
        "shor.by",
        "solo.to",
        "taplink.cc",
        "withkoji.com",
    }
)

SHORT_URL_HOSTS = REDIRECT_SHORTENER_HOSTS | LINK_IN_BIO_LANDING_HOSTS


def normalized_host(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value.lstrip("/")
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def host_matches(host: str, domains: Iterable[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def classify_shorturl_host(host: str) -> str:
    if host_matches(host, REDIRECT_SHORTENER_HOSTS):
        return "redirect_shortener"
    if host_matches(host, LINK_IN_BIO_LANDING_HOSTS):
        return "link_in_bio_landing"
    return ""


def classify_shorturl_url(url: str) -> str:
    return classify_shorturl_host(normalized_host(url))


def is_shorturl_like(url: str, *, include_landing: bool = True) -> bool:
    category = classify_shorturl_url(url)
    if include_landing:
        return bool(category)
    return category == "redirect_shortener"


def legacy_substring_match(url: str, domains: Iterable[str] = SHORT_URL_HOSTS) -> bool:
    lower = (url or "").lower()
    return any(domain in lower for domain in domains)


def read_unresolved_rows(conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    return list(
        conn.execute(
            """
            SELECT DISTINCT ol.outlink_url, ol.entity_name, ol.eid, ol.outlink_platform
            FROM dj_outlinks ol
            WHERE COALESCE(ol.outlink_url, '') != ''
              AND NOT EXISTS (
                SELECT 1 FROM dj_outlinks done
                WHERE done.source_layer = 'shorturl_resolve'
                  AND done.source_profile_url = ol.outlink_url
              )
            ORDER BY ol.outlink_url
            """
        ).fetchall()
    )


def select_shorturl_candidates(
    conn: sqlite3.Connection,
    *,
    limit: int = 0,
    include_landing: bool = False,
) -> list[tuple[str, str, str, str]]:
    categories = {"redirect_shortener"}
    if include_landing:
        categories.add("link_in_bio_landing")
    selected: list[tuple[str, str, str, str]] = []
    for row in read_unresolved_rows(conn):
        category = classify_shorturl_url(str(row[0] or ""))
        if category not in categories:
            continue
        selected.append(row)
        if limit > 0 and len(selected) >= limit:
            break
    return selected


def _top_hosts(rows: Iterable[tuple[str, str, str, str]], *, limit: int = 10) -> list[dict[str, Any]]:
    counter = Counter(normalized_host(str(row[0] or "")) or "invalid" for row in rows)
    return [{"host": host, "count": count} for host, count in counter.most_common(limit)]


def audit_shorturl_candidates(
    conn: sqlite3.Connection,
    *,
    limit: int = 0,
    cache_lookup: Any | None = None,
) -> dict[str, Any]:
    rows = read_unresolved_rows(conn)
    legacy_like = [row for row in rows if legacy_substring_match(str(row[0] or ""))]
    host_matched = [row for row in rows if classify_shorturl_url(str(row[0] or ""))]
    redirect_rows = [row for row in host_matched if classify_shorturl_url(str(row[0] or "")) == "redirect_shortener"]
    landing_rows = [row for row in host_matched if classify_shorturl_url(str(row[0] or "")) == "link_in_bio_landing"]
    selected = redirect_rows[:limit] if limit > 0 else list(redirect_rows)
    source_processed_hits = 0
    if cache_lookup is not None:
        for row in selected:
            if cache_lookup.source_processed("shorturl_resolve", str(row[0] or "")):
                source_processed_hits += 1
    false_positive_rows = [row for row in legacy_like if not classify_shorturl_url(str(row[0] or ""))]
    return {
        "would_write": False,
        "prints_raw_urls": False,
        "legacy_substring_total": len(legacy_like),
        "host_matched_total": len(host_matched),
        "redirect_shortener_total": len(redirect_rows),
        "link_in_bio_landing_total": len(landing_rows),
        "selected_redirect_total": len(selected),
        "selected_after_source_processed_skip": max(len(selected) - source_processed_hits, 0),
        "source_processed_hits": source_processed_hits,
        "false_positive_total": len(false_positive_rows),
        "false_positive_top_hosts": _top_hosts(false_positive_rows),
        "redirect_top_hosts": _top_hosts(redirect_rows),
        "landing_top_hosts": _top_hosts(landing_rows),
        "sample_hashes": [lineage.url_key_hash(str(row[0] or "")) for row in selected[:5]],
    }
