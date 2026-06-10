#!/usr/bin/env python3
"""Expand public social profile outbound links for Atlas evidence review.

This report-only runner consumes Atlas public-search/Post-Filter review rows,
fetches public profile/aggregator pages such as Instagram, Linktree, SoundCloud,
Bandcamp, Mixcloud, and RA, extracts high-value outbound links, and writes a
follow-up queue. It never reads browser profiles or cookies and never writes
graph/vector/database state.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import ipaddress
import json
import re
import tempfile
import time
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request


STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_QUEUE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_entity_public_search_post_filter_full_138102_20260521"
    / "entity_public_search_review_queue.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_profile_outlinks_138102_20260521"
SCHEMA_VERSION = "stage7_atlas_social_profile_outlinks.v1"

SENSITIVE_QUERY_KEYS = {
    "access_token",
    "authkey",
    "code",
    "key",
    "openid",
    "pass_ticket",
    "poc_token",
    "signature",
    "sig",
    "token",
}
PROFILE_PLATFORMS = {
    "instagram",
    "linktree",
    "soundcloud",
    "bandcamp",
    "mixcloud",
    "residentadvisor",
    "youtube",
}
AGGREGATOR_PLATFORMS = {"linktree", "lnkbio", "beacons", "carrd"}
HIGH_VALUE_PLATFORMS = {
    "soundcloud",
    "bandcamp",
    "mixcloud",
    "residentadvisor",
    "youtube",
    "bilibili",
    "spotify",
    "beatport",
    "apple_music",
    "eventbrite",
    "linktree",
}
SOCIAL_OUTLINK_PLATFORMS = {"instagram", "x_twitter", "weibo", "douban"}
GENERIC_OUTLINK_HOSTS = {
    "about.instagram.com",
    "about.meta.com",
    "a-v2.sndcdn.com",
    "assets.production.linktr.ee",
    "apple.com",
    "cdn.cookielaw.org",
    "developers.facebook.com",
    "docs.datadome.co",
    "edge.browser-fp.production.linktr.ee",
    "enable-javascript.com",
    "facebook.com",
    "firefox.com",
    "graph.linktr.ee",
    "google.com",
    "help.instagram.com",
    "help.soundcloud.com",
    "ingress.linktr.ee",
    "itunes.apple.com",
    "link-types-assets.production.linktr.ee",
    "meta.ai",
    "microsoft.com",
    "onetrust.com",
    "play.google.com",
    "shopify-integrations.linktr.ee",
    "style.sndcdn.com",
    "threads.com",
    "w3.org",
}
MUSIC_WORDS = {
    "album",
    "bandcamp",
    "club",
    "dj",
    "electronic",
    "event",
    "gig",
    "house",
    "live",
    "mix",
    "mixcloud",
    "mixtape",
    "music",
    "playlist",
    "ra",
    "show",
    "soundcloud",
    "techno",
    "tour",
    "track",
}


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self._current_href = ""
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        attrs_dict = {key.casefold(): value or "" for key, value in attrs}
        href = attrs_dict.get("href", "").strip()
        if href:
            self._current_href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._current_href:
            self.anchors.append({"href": self._current_href, "text": compact(" ".join(self._text_parts), 200)})
            self._current_href = ""
            self._text_parts = []


Fetcher = Callable[[str, dict[str, Any]], dict[str, Any]]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas social outlinks: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 240).casefold())


def stable_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:24]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def host_is_public(hostname: str) -> bool:
    host = (hostname or "").strip().strip("[]")
    if not host or host.casefold() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved)


def unwrap_redirect_url(url: str) -> str:
    parsed = parse.urlsplit(compact(url, 3000))
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    params = dict(parse.parse_qsl(parsed.query, keep_blank_values=True))
    for key in ("u", "url", "target", "to"):
        value = params.get(key)
        if value and value.startswith(("http://", "https://")):
            return value
    return url


def sanitize_url(url: str) -> str:
    raw = html.unescape(unwrap_redirect_url(compact(url, 3000)).replace("\\/", "/"))
    parsed = parse.urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return compact(raw, 3000)
    safe_query = [
        (key, value)
        for key, value in parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in SENSITIVE_QUERY_KEYS
    ]
    host = parsed.netloc.casefold()
    return parse.urlunsplit((parsed.scheme.casefold(), host, parsed.path or "/", parse.urlencode(safe_query), ""))


def url_fetchable(url: str) -> tuple[bool, str]:
    parsed = parse.urlsplit(compact(url, 3000))
    if parsed.scheme not in {"http", "https"}:
        return False, "unsupported_scheme"
    if not parsed.netloc:
        return False, "missing_host"
    if not host_is_public(parsed.hostname or ""):
        return False, "non_public_host"
    return True, "fetchable"


def platform_from_url(url: str) -> str:
    parsed = parse.urlsplit(compact(url, 3000))
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    if host.endswith("instagram.com"):
        return "instagram"
    if host in {"linktr.ee", "linktree.com"} or host.endswith(".linktr.ee"):
        return "linktree"
    if host in {"lnk.bio", "bio.link"} or host.endswith(".lnk.bio"):
        return "lnkbio"
    if host.endswith("beacons.ai"):
        return "beacons"
    if host.endswith("carrd.co"):
        return "carrd"
    if host == "on.soundcloud.com" or host.endswith("soundcloud.com"):
        return "soundcloud"
    if host.endswith("bandcamp.com"):
        return "bandcamp"
    if host.endswith("mixcloud.com"):
        return "mixcloud"
    if host in {"ra.co", "residentadvisor.net"} or host.endswith(".residentadvisor.net"):
        return "residentadvisor"
    if host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        return "youtube"
    if host.endswith("bilibili.com"):
        return "bilibili"
    if host.endswith("spotify.com"):
        return "spotify"
    if host.endswith("beatport.com"):
        return "beatport"
    if host.endswith("music.apple.com"):
        return "apple_music"
    if host.endswith("eventbrite.com"):
        return "eventbrite"
    if host.endswith("douban.com"):
        return "douban"
    if host in {"x.com", "twitter.com"} or host.endswith(".twitter.com"):
        return "x_twitter"
    if host.endswith("weibo.com"):
        return "weibo"
    return host or "unknown"


def host_key(url: str) -> str:
    host = parse.urlsplit(compact(url, 3000)).netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    return host


def link_kind(url: str) -> str:
    parsed = parse.urlsplit(compact(url, 3000))
    platform = platform_from_url(url)
    path = parse.unquote(parsed.path or "").strip("/")
    parts = [part for part in path.split("/") if part]
    lowered = [part.casefold() for part in parts]
    if platform in AGGREGATOR_PLATFORMS:
        return "aggregator_profile"
    if platform == "soundcloud":
        if "sets" in lowered or "albums" in lowered:
            return "audio_collection_or_mixtape"
        if len(parts) >= 2 and lowered[1] not in {"tracks", "likes", "followers", "following"}:
            return "audio_track_candidate"
        return "audio_profile"
    if platform == "bandcamp":
        if "track" in lowered:
            return "audio_track_candidate"
        if "album" in lowered:
            return "audio_collection_or_mixtape"
        return "audio_profile"
    if platform == "mixcloud":
        if len(parts) >= 2:
            return "mix_or_show_candidate"
        return "audio_profile"
    if platform == "residentadvisor":
        if parts and lowered[0] == "events":
            return "event_candidate"
        if parts and lowered[0] in {"dj", "promoters", "club"}:
            return "profile_or_venue"
        return "residentadvisor_page"
    if platform == "youtube":
        if parsed.netloc.casefold().endswith("youtu.be") or "watch" in lowered or "shorts" in lowered:
            return "video_candidate"
        return "video_channel_or_profile"
    if platform == "eventbrite":
        return "event_candidate"
    if platform in {"instagram", "x_twitter", "weibo", "douban"}:
        return "social_crosslink"
    if platform in {"spotify", "beatport", "apple_music", "bilibili"}:
        return "music_or_video_candidate"
    return "public_outlink"


def score_outlink(url: str, text: str, subject_terms: list[str], source_layer: str) -> tuple[int, list[str]]:
    platform = platform_from_url(url)
    kind = link_kind(url)
    haystack = f"{url} {text}".casefold()
    score = 0
    reasons: list[str] = []
    if platform in HIGH_VALUE_PLATFORMS:
        score += 25
        reasons.append(f"platform:{platform}")
    if kind in {"audio_track_candidate", "audio_collection_or_mixtape", "mix_or_show_candidate", "event_candidate"}:
        score += 25
        reasons.append(f"kind:{kind}")
    elif kind in {"audio_profile", "profile_or_venue", "aggregator_profile"}:
        score += 15
        reasons.append(f"kind:{kind}")
    matched_terms = [term for term in subject_terms if normalize(term) and normalize(term) in normalize(haystack)]
    if matched_terms:
        score += 20
        reasons.append("subject_match")
    music_hits = sorted(word for word in MUSIC_WORDS if word in haystack)
    if music_hits:
        score += min(20, 5 * len(music_hits))
        reasons.append("music_terms:" + ",".join(music_hits[:5]))
    if source_layer == "aggregator_page":
        score += 5
        reasons.append("aggregator_second_hop")
    return score, reasons


def extract_links_from_html(page_html: str, base_url: str) -> list[dict[str, str]]:
    parser = AnchorParser()
    parser.feed(page_html or "")
    raw_links = list(parser.anchors)
    url_patterns = [
        r"https?:\\?/\\?/[^\"'\s<>\\]+",
        r"https?://[^\"'\s<>]+",
    ]
    for pattern in url_patterns:
        for match in re.findall(pattern, page_html or "", flags=re.I):
            raw_links.append({"href": match, "text": ""})
    seen: set[str] = set()
    links: list[dict[str, str]] = []
    for item in raw_links:
        href = item.get("href", "")
        if not href:
            continue
        url = sanitize_url(parse.urljoin(base_url, href))
        ok, _reason = url_fetchable(url)
        if not ok:
            continue
        if not is_useful_outlink(base_url, url):
            continue
        if url in seen:
            continue
        seen.add(url)
        links.append({"url": url, "text": compact(item.get("text"), 200)})
    return links


def is_useful_outlink(base_url: str, url: str) -> bool:
    base_host = host_key(base_url)
    host = host_key(url)
    if not host or (host == base_host and sanitize_url(url) == sanitize_url(base_url)):
        return False
    if host in GENERIC_OUTLINK_HOSTS or any(host.endswith("." + generic) for generic in GENERIC_OUTLINK_HOSTS):
        return False
    source_platform = platform_from_url(base_url)
    platform = platform_from_url(url)
    if source_platform == "instagram" and platform == "instagram":
        return False
    if source_platform in AGGREGATOR_PLATFORMS and platform in AGGREGATOR_PLATFORMS:
        return False
    if platform in HIGH_VALUE_PLATFORMS or platform in AGGREGATOR_PLATFORMS or platform in SOCIAL_OUTLINK_PLATFORMS:
        return True
    if source_platform in {"soundcloud", "bandcamp", "mixcloud", "residentadvisor"} and host == base_host:
        return link_kind(url) in {
            "audio_collection_or_mixtape",
            "audio_track_candidate",
            "event_candidate",
            "mix_or_show_candidate",
        }
    return False


def source_url(row: dict[str, Any]) -> str:
    top = row.get("top_result") if isinstance(row.get("top_result"), dict) else {}
    return sanitize_url(row.get("best_url") or row.get("final_url") or row.get("url") or top.get("url") or "")


def subject_terms(row: dict[str, Any]) -> list[str]:
    terms = [compact(row.get("name"), 160)]
    aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else []
    terms.extend(compact(alias, 160) for alias in aliases[:4])
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        key = normalize(term)
        if key and key not in seen:
            seen.add(key)
            result.append(term)
    return result


def fetch_http(url: str, row: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    ok, reason = url_fetchable(url)
    if not ok:
        return {"ok": False, "status": reason, "content": "", "error": reason}
    req = request.Request(
        url,
        headers={
            "User-Agent": "AtlasSocialOutlinksReportOnly/1.0 (+no-cookies; public-links)",
            "Accept": "text/html,text/plain,application/xhtml+xml",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:  # noqa: S310 - public URL guard is applied.
            raw = response.read(2_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
            content_type = response.headers.get("content-type", "")
    except error.HTTPError as exc:
        return {"ok": False, "status": f"http_{exc.code}", "content": "", "error": compact(exc.reason, 500)}
    except (error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "status": "fetch_error", "content": "", "error": compact(str(exc), 500)}
    return {
        "ok": True,
        "status": "fetched",
        "content": raw.decode(charset, errors="replace"),
        "content_type": content_type,
    }


def build_outlink_row(
    *,
    source_row: dict[str, Any],
    profile_url: str,
    profile_platform: str,
    link: dict[str, str],
    source_layer: str,
    generated_at: str,
    parent_link_url: str = "",
) -> dict[str, Any]:
    url = sanitize_url(link["url"])
    terms = subject_terms(source_row)
    score, reasons = score_outlink(url, link.get("text", ""), terms, source_layer)
    return {
        "schema_version": SCHEMA_VERSION + ".outlink",
        "generated_at": generated_at,
        "outlink_id": stable_id(str(source_row.get("entity_search_id")), profile_url, url, source_layer),
        "entity_search_id": source_row.get("entity_search_id"),
        "queue_index": source_row.get("queue_index"),
        "name": source_row.get("name"),
        "type": source_row.get("type"),
        "profile_url": profile_url,
        "profile_platform": profile_platform,
        "source_layer": source_layer,
        "parent_link_url": parent_link_url,
        "outlink_url": url,
        "outlink_platform": platform_from_url(url),
        "outlink_kind": link_kind(url),
        "anchor_text": compact(link.get("text"), 200),
        "priority_score": score,
        "priority_reasons": reasons,
        "review_required": True,
        "identity_proof": False,
        "accepted_for_graph": False,
        "graph_write_allowed": False,
        "next_action": "fetch_outlink_content_or_manual_review",
    }


def fetch_profile(
    *,
    row: dict[str, Any],
    url: str,
    fetch_mode: str,
    timeout_sec: float,
    injected_fetcher: Fetcher | None,
) -> dict[str, Any]:
    if fetch_mode == "dry-run":
        return {"ok": False, "status": "dry_run", "content": "", "error": "fetch skipped by dry-run"}
    if injected_fetcher is not None:
        return injected_fetcher(url, row)
    return fetch_http(url, row, timeout_sec)


def run_outlink_expansion(
    *,
    review_queue_path: Path,
    out_dir: Path,
    fetch_mode: str,
    limit: int,
    timeout_sec: float,
    sleep_sec: float,
    follow_aggregators: bool,
    max_aggregator_pages: int,
    include_platforms: set[str],
    injected_fetcher: Fetcher | None = None,
) -> dict[str, Any]:
    reject_d_path(review_queue_path, "review_queue_path")
    reject_d_path(out_dir, "out_dir")
    if fetch_mode not in {"dry-run", "http"}:
        raise ValueError(f"Unsupported fetch_mode: {fetch_mode}")
    rows = read_jsonl(review_queue_path)
    profile_rows = []
    for row in rows:
        url = source_url(row)
        platform = platform_from_url(url)
        if platform in include_platforms:
            profile_rows.append((row, url, platform))
    selected = profile_rows[:limit] if limit > 0 else profile_rows

    generated_at = now_iso()
    profile_fetch_rows: list[dict[str, Any]] = []
    outlink_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    profile_status_counts: Counter[str] = Counter()
    aggregator_fetch_count = 0

    for idx, (row, profile_url, profile_platform) in enumerate(selected):
        fetch_result = fetch_profile(
            row=row,
            url=profile_url,
            fetch_mode=fetch_mode,
            timeout_sec=timeout_sec,
            injected_fetcher=injected_fetcher,
        )
        status = compact(fetch_result.get("status"), 80) or "unknown"
        profile_status_counts[status] += 1
        links = extract_links_from_html(fetch_result.get("content", ""), profile_url) if fetch_result.get("ok") else []
        profile_fetch_rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".profile_fetch",
                "generated_at": generated_at,
                "entity_search_id": row.get("entity_search_id"),
                "queue_index": row.get("queue_index"),
                "name": row.get("name"),
                "profile_url": profile_url,
                "profile_platform": profile_platform,
                "fetch_status": status,
                "fetch_ok": bool(fetch_result.get("ok")),
                "fetch_error": compact(fetch_result.get("error"), 500),
                "outlink_count": len(links),
                "accepted_for_graph": False,
                "identity_proof": False,
                "graph_write_allowed": False,
            }
        )
        if not fetch_result.get("ok"):
            errors.append(
                {
                    "entity_search_id": row.get("entity_search_id"),
                    "queue_index": row.get("queue_index"),
                    "profile_url": profile_url,
                    "fetch_status": status,
                    "fetch_error": compact(fetch_result.get("error"), 500),
                }
            )
        for link in links:
            outlink_rows.append(
                build_outlink_row(
                    source_row=row,
                    profile_url=profile_url,
                    profile_platform=profile_platform,
                    link=link,
                    source_layer="profile_page",
                    generated_at=generated_at,
                )
            )
        if follow_aggregators and fetch_mode == "http":
            aggregator_links = [
                link
                for link in links
                if platform_from_url(link["url"]) in AGGREGATOR_PLATFORMS
            ]
            for link in aggregator_links:
                if aggregator_fetch_count >= max_aggregator_pages:
                    break
                aggregator_fetch_count += 1
                aggregator_result = fetch_profile(
                    row=row,
                    url=link["url"],
                    fetch_mode=fetch_mode,
                    timeout_sec=timeout_sec,
                    injected_fetcher=injected_fetcher,
                )
                if not aggregator_result.get("ok"):
                    errors.append(
                        {
                            "entity_search_id": row.get("entity_search_id"),
                            "queue_index": row.get("queue_index"),
                            "profile_url": link["url"],
                            "fetch_status": compact(aggregator_result.get("status"), 80),
                            "fetch_error": compact(aggregator_result.get("error"), 500),
                        }
                    )
                    continue
                for child_link in extract_links_from_html(aggregator_result.get("content", ""), link["url"]):
                    outlink_rows.append(
                        build_outlink_row(
                            source_row=row,
                            profile_url=profile_url,
                            profile_platform=profile_platform,
                            link=child_link,
                            source_layer="aggregator_page",
                            generated_at=generated_at,
                            parent_link_url=link["url"],
                        )
                    )
        if sleep_sec > 0 and idx < len(selected) - 1:
            time.sleep(sleep_sec)

    outlink_rows.sort(key=lambda item: (-int(item["priority_score"]), item["outlink_platform"], item["outlink_url"]))
    high_value_rows = [
        row
        for row in outlink_rows
        if row["outlink_platform"] in HIGH_VALUE_PLATFORMS and int(row["priority_score"]) >= 25
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    profile_path = out_dir / "atlas_social_profile_fetches.jsonl"
    outlinks_path = out_dir / "atlas_social_profile_outlinks.jsonl"
    next_queue_path = out_dir / "atlas_social_outlink_followup_queue.jsonl"
    errors_path = out_dir / "atlas_social_profile_outlink_errors.jsonl"
    summary_path = out_dir / "atlas_social_profile_outlinks_summary.json"
    write_jsonl(profile_path, profile_fetch_rows)
    write_jsonl(outlinks_path, outlink_rows)
    write_jsonl(next_queue_path, high_value_rows)
    write_jsonl(errors_path, errors)

    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_social_profile_outlinks_ready_report_only",
        "review_queue_path": str(review_queue_path),
        "out_dir": str(out_dir),
        "fetch_mode": fetch_mode,
        "input_rows": len(rows),
        "candidate_profile_rows": len(profile_rows),
        "selected_profile_rows": len(selected),
        "profile_fetch_status_counts": dict(sorted(profile_status_counts.items())),
        "outlink_rows": len(outlink_rows),
        "high_value_followup_rows": len(high_value_rows),
        "aggregator_pages_fetched": aggregator_fetch_count,
        "outlink_platform_counts": dict(sorted(Counter(row["outlink_platform"] for row in outlink_rows).items())),
        "outlink_kind_counts": dict(sorted(Counter(row["outlink_kind"] for row in outlink_rows).items())),
        "accepted_for_graph": 0,
        "paths": {
            "profile_fetches": str(profile_path),
            "outlinks": str(outlinks_path),
            "followup_queue": str(next_queue_path),
            "errors": str(errors_path),
            "summary": str(summary_path),
        },
        "safety": {
            "report_only": True,
            "no_browser_profile": True,
            "no_cookie_or_token_export": True,
            "no_graph_vector_sqlite_mem0_write": True,
            "no_d_scan": True,
            "no_9router": True,
            "no_model_call": True,
        },
    }
    write_json(summary_path, summary)
    return summary


def parse_platforms(raw: str) -> set[str]:
    values = {item.strip().casefold() for item in raw.split(",") if item.strip()}
    return values or set(PROFILE_PLATFORMS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--fetch-mode", choices=["dry-run", "http"], default="dry-run")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--timeout-sec", type=float, default=20.0)
    parser.add_argument("--sleep-sec", type=float, default=0.5)
    parser.add_argument("--follow-aggregators", action="store_true")
    parser.add_argument("--max-aggregator-pages", type=int, default=25)
    parser.add_argument("--include-platforms", default=",".join(sorted(PROFILE_PLATFORMS)))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_outlink_expansion(
        review_queue_path=args.review_queue,
        out_dir=args.out_dir,
        fetch_mode=args.fetch_mode,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        sleep_sec=args.sleep_sec,
        follow_aggregators=args.follow_aggregators,
        max_aggregator_pages=args.max_aggregator_pages,
        include_platforms=parse_platforms(args.include_platforms),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["candidate_profile_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
