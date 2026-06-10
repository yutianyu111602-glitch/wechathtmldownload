"""Validate bounded public social/music links for P1.

This is the P1e2 public-first link gate. It checks reachable public URLs from
the legacy radio/social assets and the staging social edge pack, filters known
non-track SoundCloud collection slugs such as /sets/, and writes reports only.

No login, cookies, graph/vector/DB writes, paid API calls, D: scans, or publish.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request


DEFAULT_ASSETS = Path("reports/p1_dj_dataset_import_20260514/radio_social_assets.jsonl")
DEFAULT_EDGE_PACK = Path("reports/p1_social_edge_pack_20260514/social_edge_pack.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_public_social_link_validation_20260515")
SCHEMA_VERSION = "stage7_p1_public_social_link_validation.v1"

DEFAULT_PLATFORMS = {
    "soundcloud",
    "bandcamp",
    "linktree",
    "residentadvisor",
    "youtube",
    "bilibili",
    "shorturl",
}
SOUNDCLOUD_NON_TRACK_SEGMENTS = {
    "sets",
    "albums",
    "tracks",
    "popular-tracks",
    "likes",
    "reposts",
    "followers",
    "following",
    "comments",
}
BLOCKED_RESPONSE_CONTENT_TYPES = (
    "audio/",
    "video/",
    "application/octet-stream",
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for public social link validation: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
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


def first_text(value: Any) -> str:
    return str(value or "").strip()


def media_or_attachment_block_reason(content_type: str, content_disposition: str = "") -> str:
    media_type = first_text(content_type).split(";", 1)[0].strip().casefold()
    disposition = first_text(content_disposition).casefold()
    if any(media_type.startswith(prefix) for prefix in BLOCKED_RESPONSE_CONTENT_TYPES):
        return "copyright_sensitive_media_content_type"
    if "attachment" in disposition:
        return "attachment_download_content_disposition"
    return ""


def normalize_url(url: str) -> str:
    parsed = parse.urlparse(first_text(url))
    if not parsed.scheme or not parsed.netloc:
        return first_text(url)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.rstrip("/") or "/"
    query = parsed.query
    return parse.urlunparse((scheme, host, path, "", query, ""))


def platform_from_url(url: str) -> str:
    host = parse.urlparse(first_text(url)).netloc.casefold().replace("www.", "")
    if host.startswith("m."):
        host = host[2:]
    if host == "on.soundcloud.com" or host.endswith("soundcloud.com"):
        return "soundcloud"
    if host.endswith("bandcamp.com"):
        return "bandcamp"
    if host in {"linktr.ee", "linktree.com"} or host.endswith(".linktr.ee"):
        return "linktree"
    if host in {"ra.co", "residentadvisor.net"} or host.endswith(".residentadvisor.net"):
        return "residentadvisor"
    if host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com"):
        return "youtube"
    if host.endswith("bilibili.com"):
        return "bilibili"
    if host == "shorturl.at":
        return "shorturl"
    if host.endswith("instagram.com"):
        return "instagram"
    return host or "unknown"


def link_kind(url: str) -> str:
    parsed = parse.urlparse(first_text(url))
    host = parsed.netloc.casefold().replace("www.", "")
    if host.startswith("m."):
        host = host[2:]
    path = parse.unquote(parsed.path or "").strip("/")
    parts = [part for part in path.split("/") if part]
    platform = platform_from_url(url)

    if platform == "soundcloud":
        if host == "on.soundcloud.com":
            return "shortlink"
        lowered = [part.casefold() for part in parts]
        if any(part in {"sets", "albums"} for part in lowered):
            return "non_track_collection"
        if not parts:
            return "homepage"
        if len(parts) == 1:
            return "profile"
        if len(parts) >= 2 and parts[1].casefold() in SOUNDCLOUD_NON_TRACK_SEGMENTS:
            return "profile_listing"
        return "track_candidate"
    if platform == "bandcamp":
        lowered_path = "/" + path.casefold() + "/"
        if "/track/" in lowered_path:
            return "track_candidate"
        if "/album/" in lowered_path:
            return "non_track_collection"
        return "profile"
    if platform == "youtube":
        if host == "youtu.be" or parsed.query.startswith("v=") or "/watch" in parsed.path or "/shorts/" in parsed.path:
            return "video_candidate"
        return "profile_or_channel"
    if platform == "bilibili":
        if "/video/" in parsed.path or "bvid=" in parsed.query.casefold():
            return "video_candidate"
        if "/space/" in parsed.path:
            return "profile"
        return "search_or_listing"
    if platform == "linktree":
        return "aggregator_profile"
    if platform == "residentadvisor":
        if parts and parts[0].casefold() in {"dj", "promoters", "club", "events"}:
            return "profile_or_event"
        return "residentadvisor_page"
    if platform == "shorturl":
        return "shortlink"
    return "public_link"


def should_filter_non_track(kind: str) -> bool:
    return kind in {"non_track_collection", "profile_listing"}


def collect_links(
    assets_path: Path,
    edge_pack_path: Path,
    platforms: set[str],
    per_platform: int,
    include_instagram: bool,
    include_non_track: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    raw_links: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for edge in read_jsonl(edge_pack_path):
        url = first_text(edge.get("object_url"))
        if url:
            raw_links.append(
                {
                    "url": url,
                    "source": "social_edge_pack",
                    "subject_name": first_text(edge.get("subject_name")),
                    "source_family": first_text(edge.get("source_family")),
                    "edge_id": first_text(edge.get("edge_id")),
                    "edge_type": first_text(edge.get("edge_type")),
                    "evidence_url": first_text(edge.get("evidence_url")),
                }
            )
    for asset in read_jsonl(assets_path):
        for url in asset.get("social_links") or []:
            if first_text(url):
                raw_links.append(
                    {
                        "url": first_text(url),
                        "source": "legacy_asset_social_links",
                        "subject_name": first_text(asset.get("artist_name") or asset.get("title")),
                        "source_family": first_text(asset.get("source_family")),
                        "asset_type": first_text(asset.get("asset_type")),
                        "evidence_url": first_text(asset.get("page_url")),
                    }
                )

    selected_by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for item in raw_links:
        url = item["url"]
        normalized = normalize_url(url)
        if normalized in seen:
            skipped["duplicate_url"] += 1
            continue
        seen.add(normalized)
        platform = platform_from_url(url)
        kind = link_kind(url)
        if platform == "instagram" and not include_instagram:
            skipped["instagram_skipped_no_login"] += 1
            continue
        if platform not in platforms:
            skipped[f"unsupported_platform:{platform}"] += 1
            continue
        if should_filter_non_track(kind) and not include_non_track:
            skipped["filtered_non_track_slug"] += 1
            continue
        enriched = dict(item)
        enriched.update({"normalized_url": normalized, "platform": platform, "link_kind": kind})
        if per_platform <= 0 or len(selected_by_platform[platform]) < per_platform:
            selected_by_platform[platform].append(enriched)
        else:
            skipped[f"over_per_platform_limit:{platform}"] += 1

    selected: list[dict[str, Any]] = []
    for platform in sorted(selected_by_platform):
        selected.extend(selected_by_platform[platform])
    return selected, dict(skipped)


def fetch_url(url: str, timeout_sec: float, max_bytes: int) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Stage7PublicSocialLinkValidation/1.0",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            content_type = response.headers.get("Content-Type", "")
            content_disposition = response.headers.get("Content-Disposition", "")
            media_block_reason = media_or_attachment_block_reason(content_type, content_disposition)
            if media_block_reason:
                return {
                    "ok": False,
                    "status_code": int(response.status),
                    "final_url": response.geturl(),
                    "content_type": content_type,
                    "content_disposition": content_disposition,
                    "body": "",
                    "error": media_block_reason,
                    "media_or_attachment_blocked": True,
                    "blocked_reason": media_block_reason,
                }
            body = response.read(max_bytes)
            charset = response.headers.get_content_charset() or "utf-8"
            return {
                "ok": 200 <= int(response.status) < 400,
                "status_code": int(response.status),
                "final_url": response.geturl(),
                "content_type": content_type,
                "content_disposition": content_disposition,
                "body": body.decode(charset, errors="replace"),
                "error": "",
            }
    except error.HTTPError as exc:
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
        content_disposition = exc.headers.get("Content-Disposition", "") if exc.headers else ""
        media_block_reason = media_or_attachment_block_reason(content_type, content_disposition)
        if media_block_reason:
            return {
                "ok": False,
                "status_code": int(exc.code),
                "final_url": exc.geturl(),
                "content_type": content_type,
                "content_disposition": content_disposition,
                "body": "",
                "error": media_block_reason,
                "media_or_attachment_blocked": True,
                "blocked_reason": media_block_reason,
            }
        body = exc.read(max_bytes).decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "ok": False,
            "status_code": int(exc.code),
            "final_url": exc.geturl(),
            "content_type": content_type,
            "content_disposition": content_disposition,
            "body": body,
            "error": f"HTTPError: {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001 - report-only gate captures network failures.
        return {
            "ok": False,
            "status_code": None,
            "final_url": url,
            "content_type": "",
            "body": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def extract_title(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.I | re.S)
    if not match:
        return ""
    text = re.sub(r"\s+", " ", match.group(1)).strip()
    return text[:180]


def looks_soft_not_found(status_code: Any, page_title: str, body: str) -> bool:
    text = f"{page_title} {body[:600]}".casefold()
    if status_code == 404:
        return True
    return any(
        marker in text
        for marker in [
            "404 page not found",
            "404 not found",
            "page not found",
            "this page is not available",
            "this page doesn't exist",
        ]
    )


def evaluate_link(item: dict[str, Any], fetched: dict[str, Any]) -> dict[str, Any]:
    body = first_text(fetched.get("body"))
    page_title = extract_title(body)
    soft_not_found = looks_soft_not_found(fetched.get("status_code"), page_title, body)
    media_or_attachment_blocked = bool(fetched.get("media_or_attachment_blocked"))
    accessible = bool(fetched.get("ok")) and not soft_not_found and not media_or_attachment_blocked
    status = "source_reachable" if accessible else "source_blocked_or_unreachable"
    final_url = first_text(fetched.get("final_url")) or item["url"]
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "checked_at": now_iso(),
        "source": item["source"],
        "source_family": item.get("source_family", ""),
        "subject_name": item.get("subject_name", ""),
        "edge_id": item.get("edge_id", ""),
        "edge_type": item.get("edge_type", ""),
        "evidence_url": item.get("evidence_url", ""),
        "url": item["url"],
        "normalized_url": item["normalized_url"],
        "platform": item["platform"],
        "link_kind": item["link_kind"],
        "accessible": accessible,
        "status_code": fetched.get("status_code"),
        "final_url": final_url,
        "final_platform": platform_from_url(final_url),
        "content_type": first_text(fetched.get("content_type")),
        "content_disposition": first_text(fetched.get("content_disposition")),
        "page_title": page_title,
        "soft_not_found": soft_not_found,
        "media_or_attachment_blocked": media_or_attachment_blocked,
        "blocked_reason": first_text(fetched.get("blocked_reason") or fetched.get("error")),
        "error": first_text(fetched.get("error")),
        "validation_status": status,
        "graph_ready": False,
        "identity_proof": False,
    }


def build_validation(
    assets_path: Path,
    edge_pack_path: Path,
    out_dir: Path,
    platforms: set[str],
    per_platform: int,
    timeout_sec: float,
    max_bytes: int,
    include_instagram: bool = False,
    include_non_track: bool = False,
    fetcher: Callable[[str, float, int], dict[str, Any]] = fetch_url,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    selected, skipped = collect_links(
        assets_path=assets_path,
        edge_pack_path=edge_pack_path,
        platforms=platforms,
        per_platform=per_platform,
        include_instagram=include_instagram,
        include_non_track=include_non_track,
    )
    results = [evaluate_link(item, fetcher(item["url"], timeout_sec, max_bytes)) for item in selected]
    status_counts = Counter(row["validation_status"] for row in results)
    platform_counts = Counter(row["platform"] for row in results)
    kind_counts = Counter(row["link_kind"] for row in results)
    reachable = status_counts.get("source_reachable", 0)
    if reachable:
        decision = "p1_public_social_link_validation_partial"
    elif results:
        decision = "p1_public_social_link_validation_blocked"
    else:
        decision = "p1_public_social_link_validation_empty"

    result_path = out_dir / "public_social_link_validation.jsonl"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": bool(results),
        "assets_path": str(assets_path),
        "edge_pack_path": str(edge_pack_path),
        "result_path": str(result_path),
        "checked_links": len(results),
        "reachable_links": reachable,
        "blocked_or_unreachable_links": status_counts.get("source_blocked_or_unreachable", 0),
        "graph_ready_links": 0,
        "identity_proof_links": 0,
        "platform_counts": dict(platform_counts),
        "kind_counts": dict(kind_counts),
        "status_counts": dict(status_counts),
        "skipped": skipped,
        "per_platform": per_platform,
        "include_instagram": include_instagram,
        "include_non_track": include_non_track,
        "safety": [
            "reports_only",
            "public_urls_only",
            "instagram_skipped_by_default",
            "no_login",
            "no_cookies",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
            "public_link_is_not_identity_proof",
            "copyright_audio_video_or_attachment_not_fetched",
        ],
    }
    write_jsonl(result_path, results)
    write_json(out_dir / "public_social_link_validation_summary.json", report)
    write_markdown(out_dir / "public_social_link_validation_summary.md", report, results)
    return report


def write_markdown(path: Path, report: dict[str, Any], results: list[dict[str, Any]]) -> None:
    lines = [
        "# P1 Public Social Link Validation",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- checked_links: `{report['checked_links']}`",
        f"- reachable_links: `{report['reachable_links']}`",
        f"- blocked_or_unreachable_links: `{report['blocked_or_unreachable_links']}`",
        f"- graph_ready_links: `{report['graph_ready_links']}`",
        f"- result_path: `{report['result_path']}`",
        "",
        "## Platform Counts",
        "",
    ]
    for key, value in sorted(report["platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Kind Counts", ""])
    for key, value in sorted(report["kind_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Skipped", ""])
    for key, value in sorted(report["skipped"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Checked Links",
            "",
            "| platform | kind | subject | status | http | url | final_url |",
            "|---|---|---|---|---:|---|---|",
        ]
    )
    for row in results:
        lines.append(
            "| {platform} | {kind} | {subject} | {status} | {http} | {url} | {final} |".format(
                platform=row["platform"],
                kind=row["link_kind"],
                subject=first_text(row.get("subject_name")).replace("|", "/"),
                status=row["validation_status"],
                http=row.get("status_code") or "",
                url=row["url"],
                final=row["final_url"],
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Instagram login/cookie crawling is skipped by default.",
            "- Public link reachability is not identity proof.",
            "- Audio/video/octet-stream/attachment responses are blocked before body read.",
            "- Non-track collection slugs such as SoundCloud `/sets/` are filtered unless explicitly included.",
            "- No graph/vector/DB write.",
            "- No paid API.",
            "- No D: scan.",
            "- No publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--edge-pack", type=Path, default=DEFAULT_EDGE_PACK)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--platform", action="append", default=[], help="Repeatable platform allow-list.")
    parser.add_argument("--per-platform", type=int, default=8)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    parser.add_argument("--max-bytes", type=int, default=256_000)
    parser.add_argument("--include-instagram", action="store_true")
    parser.add_argument("--include-non-track", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    platforms = {item.casefold() for item in args.platform} if args.platform else set(DEFAULT_PLATFORMS)
    report = build_validation(
        assets_path=args.assets,
        edge_pack_path=args.edge_pack,
        out_dir=args.out_dir,
        platforms=platforms,
        per_platform=args.per_platform,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
        include_instagram=args.include_instagram,
        include_non_track=args.include_non_track,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "checked_links": report["checked_links"],
                "reachable_links": report["reachable_links"],
                "summary": str(args.out_dir / "public_social_link_validation_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["checked_links"] else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
