#!/usr/bin/env python3
"""Build PRD-16 OpenCLI social profile evidence canary reports.

This canary uses the Browser Bridge profile named by --profile to inspect only
bounded public social profile pages. It does not export cookies/tokens, perform
account actions, crawl private/follower-only content, write graph/vector/DB
state, or publish anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import parse


DEFAULT_GRAPH_CANDIDATES = Path("reports/p1_social_graph_acceptance_pack_20260515/graph_acceptance_candidates.jsonl")
DEFAULT_IDENTITY_REVIEW = Path("reports/social_identity_cross_evidence_20260515/identity_cross_evidence_review.jsonl")
DEFAULT_SOCIAL_DEEP_DIR = Path("reports/social_deep_candidates_20260515")
DEFAULT_OUT_DIR = Path("reports/opencli_social_profile_evidence_20260516")
DEFAULT_PROFILE = "ejk3c3qe"
DEFAULT_SESSION = "stage7-social"
SCHEMA_VERSION = "stage7_prd16_opencli_social_profile_evidence.v1"

ALLOWED_PLATFORMS = {"instagram", "linktree", "soundcloud", "bandcamp"}
INSTAGRAM_NON_PROFILE = {
    "accounts",
    "direct",
    "explore",
    "p",
    "reel",
    "reels",
    "stories",
    "tv",
}
SOUNDCLOUD_NON_PROFILE = {
    "albums",
    "comments",
    "followers",
    "following",
    "likes",
    "popular-tracks",
    "reposts",
    "sets",
    "tracks",
}
BANDCAMP_NON_PROFILE_SEGMENTS = {"album", "track", "merch", "community"}
PRIVATE_OR_ACTION_SEGMENTS = {
    "accounts",
    "checkout",
    "direct",
    "followers",
    "following",
    "login",
    "messages",
    "p",
    "payment",
    "reel",
    "reels",
    "save",
    "settings",
    "stories",
    "subscribe",
    "tv",
}
GENERIC_EXTERNAL_HOSTS = {
    "about.instagram.com",
    "about.meta.com",
    "developers.facebook.com",
    "help.instagram.com",
    "itunes.apple.com",
    "meta.ai",
    "onetrust.com",
    "play.google.com",
}
GENERIC_BANDCAMP_PATH_PREFIXES = {"/", "/cart", "/discover", "/help"}
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}

PAGE_EVAL_JS = (
    "(() => { const q=s=>document.querySelector(s); "
    "const g=s=>{const n=q(s); return n ? String(n.content||n.href||n.textContent||'').trim() : '';}; "
    "const text=((document.body&&document.body.innerText)||'').replace(/\\s+/g,' ').trim(); "
    "return {url:location.href,title:document.title||'',canonical:g('link[rel=canonical]'),"
    "ogTitle:g('meta[property=\"og:title\"]')||g('meta[name=\"og:title\"]'),"
    "description:g('meta[property=\"og:description\"]')||g('meta[name=description]'),"
    "image:g('meta[property=\"og:image\"]')||g('meta[name=\"twitter:image\"]'),"
    "textSample:text.slice(0,800),"
    "anchors:Array.from(document.querySelectorAll('a[href]')).slice(0,120).map(a=>({href:a.href||'',"
    "text:(a.innerText||a.textContent||'').replace(/\\s+/g,' ').trim().slice(0,160)}))}; })()"
)


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


Runner = Callable[[list[str], float], CommandResult]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for PRD-16 OpenCLI evidence: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
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


def command_runner(args: list[str], timeout_sec: float) -> CommandResult:
    executable = shutil.which(args[0])
    if executable is None and not Path(args[0]).suffix:
        executable = shutil.which(args[0] + ".cmd")
    command = [executable or args[0], *args[1:]]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
    except FileNotFoundError:
        return CommandResult(
            returncode=127,
            stdout="",
            stderr=f"command not found: {args[0]}",
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=first_text(exc.stdout),
            stderr=f"timeout after {timeout_sec}s",
            timed_out=True,
        )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        timed_out=False,
    )


def normalize_url(url: str) -> str:
    raw = first_text(url)
    parsed = parse.urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parse.unquote(parsed.path or "/")
    path = re.sub(r"/+", "/", path).rstrip("/") or "/"
    return parse.urlunparse((scheme, host, path, "", "", ""))


def platform_from_url(url: str) -> str:
    parsed = parse.urlparse(first_text(url))
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    if host.endswith("instagram.com"):
        return "instagram"
    if host in {"linktr.ee", "linktree.com"} or host.endswith(".linktr.ee"):
        return "linktree"
    if host == "on.soundcloud.com" or host.endswith("soundcloud.com"):
        return "soundcloud"
    if host.endswith("bandcamp.com"):
        return "bandcamp"
    return host or "unknown"


def url_parts(url: str) -> list[str]:
    parsed = parse.urlparse(first_text(url))
    return [part for part in parse.unquote(parsed.path or "").strip("/").split("/") if part]


def profile_handle_from_url(url: str, platform: str) -> str:
    parsed = parse.urlparse(first_text(url))
    host = parsed.netloc.casefold()
    parts = url_parts(url)
    if platform in {"instagram", "linktree", "soundcloud"} and parts:
        return parts[0].strip("@")
    if platform == "bandcamp" and host.endswith(".bandcamp.com"):
        prefix = host.removesuffix(".bandcamp.com")
        return prefix.removeprefix("www.").strip()
    return ""


def is_allowed_profile_url(url: str, allowed_platforms: set[str]) -> tuple[bool, str, str]:
    parsed = parse.urlparse(first_text(url))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "not_http_url", "unknown"
    platform = platform_from_url(url)
    if platform not in allowed_platforms:
        return False, f"unsupported_platform:{platform}", platform
    parts = [part.casefold() for part in url_parts(url)]
    if any(part in PRIVATE_OR_ACTION_SEGMENTS for part in parts):
        return False, "private_or_action_path", platform
    if platform == "instagram":
        if not parts or parts[0] in INSTAGRAM_NON_PROFILE:
            return False, "non_profile_path", platform
        return True, "profile", platform
    if platform == "linktree":
        if not parts:
            return False, "non_profile_path", platform
        return True, "aggregator_profile", platform
    if platform == "soundcloud":
        if parsed.netloc.casefold().replace("www.", "") == "on.soundcloud.com":
            return False, "shortlink_not_profile", platform
        if not parts:
            return False, "non_profile_path", platform
        if len(parts) > 1:
            return False, "soundcloud_track_or_collection_not_profile", platform
        if parts[0] in SOUNDCLOUD_NON_PROFILE or "soundcloud.com" in parts[0]:
            return False, "soundcloud_non_profile_slug", platform
        return True, "profile", platform
    if platform == "bandcamp":
        if any(part in BANDCAMP_NON_PROFILE_SEGMENTS for part in parts):
            return False, "bandcamp_track_or_collection_not_profile", platform
        return True, "profile", platform
    return False, "unsupported_profile_platform", platform


def graph_evidence_url(row: dict[str, Any]) -> str:
    source_row = row.get("source_row") if isinstance(row.get("source_row"), dict) else {}
    for evidence in source_row.get("candidate_evidence") or []:
        if isinstance(evidence, dict) and first_text(evidence.get("evidence_url")):
            return first_text(evidence.get("evidence_url"))
    return first_text(row.get("evidence_url") or row.get("source_url"))


def candidate_id(platform: str, subject: str, url: str) -> str:
    raw = f"{platform}|{subject}|{normalize_url(url)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def make_candidate(
    *,
    source_report: str,
    subject_name: str,
    input_url: str,
    evidence_url: str,
    source_family: str,
    source_row_id: str,
    source_status: str,
    allowed_platforms: set[str],
    priority: int,
) -> tuple[dict[str, Any] | None, str]:
    ok, reason, platform = is_allowed_profile_url(input_url, allowed_platforms)
    if not ok:
        return None, reason
    normalized = normalize_url(input_url)
    handle = profile_handle_from_url(normalized, platform)
    row = {
        "schema_version": SCHEMA_VERSION + ".candidate",
        "source_prd": "PRD-16",
        "source_report": source_report,
        "source_row_id": source_row_id,
        "source_status": source_status,
        "candidate_id": candidate_id(platform, subject_name, normalized),
        "subject_name": first_text(subject_name),
        "input_url": first_text(input_url),
        "canonical_url": normalized,
        "platform": platform,
        "profile_handle": handle,
        "source_family": first_text(source_family),
        "evidence_url": first_text(evidence_url),
        "priority": priority,
        "staging_only": True,
        "unsafe_action": False,
    }
    return row, "selected"


def collect_candidates(
    graph_candidates: Path,
    identity_review: Path,
    social_deep_dir: Path,
    allowed_platforms: set[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    reject_d_path(graph_candidates, "graph_candidates")
    reject_d_path(identity_review, "identity_review")
    reject_d_path(social_deep_dir, "social_deep_dir")

    rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()

    for row in read_jsonl(graph_candidates):
        candidate, reason = make_candidate(
            source_report="p1_social_graph_acceptance_pack_20260515",
            subject_name=first_text(row.get("subject_name")),
            input_url=first_text(row.get("final_url") or row.get("source_url")),
            evidence_url=graph_evidence_url(row),
            source_family=first_text(row.get("source_family")),
            source_row_id=first_text(row.get("candidate_id")),
            source_status=first_text(row.get("acceptance_status")),
            allowed_platforms=allowed_platforms,
            priority=10,
        )
        if candidate:
            rows.append(candidate)
        else:
            skipped[f"graph:{reason}"] += 1

    for row in read_jsonl(identity_review):
        candidate, reason = make_candidate(
            source_report="social_identity_cross_evidence_20260515",
            subject_name=first_text(row.get("subject_name")),
            input_url=first_text(row.get("object_url")),
            evidence_url=first_text(row.get("evidence_url")),
            source_family=first_text(row.get("source_family")),
            source_row_id=first_text(row.get("edge_id")),
            source_status=first_text(row.get("review_tier")),
            allowed_platforms=allowed_platforms,
            priority=20,
        )
        if candidate:
            rows.append(candidate)
        else:
            skipped[f"identity:{reason}"] += 1

    for path in sorted(social_deep_dir.glob("*_urls.jsonl")) if social_deep_dir.exists() else []:
        source_name = path.stem
        for row in read_jsonl(path):
            candidate, reason = make_candidate(
                source_report=f"social_deep_candidates_20260515/{path.name}",
                subject_name=first_text(row.get("subject_name")),
                input_url=first_text(row.get("normalized_url") or row.get("url")),
                evidence_url=first_text(row.get("evidence_url")),
                source_family=first_text(row.get("source_family")),
                source_row_id=first_text(row.get("edge_id") or row.get("title") or source_name),
                source_status=first_text(row.get("link_kind")),
                allowed_platforms=allowed_platforms,
                priority=30,
            )
            if candidate:
                rows.append(candidate)
            else:
                skipped[f"deep:{reason}"] += 1

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: (item["priority"], item["platform"], item["canonical_url"])):
        key = first_text(row.get("canonical_url")).casefold()
        if key in seen:
            skipped["duplicate_canonical_url"] += 1
            continue
        seen.add(key)
        deduped.append(row)
    return deduped, dict(skipped)


def select_candidates(candidates: list[dict[str, Any]], limit: int, per_platform: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return candidates
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_platform[first_text(row.get("platform"))].append(row)

    for platform in sorted(by_platform):
        count = 0
        for row in by_platform[platform]:
            if len(selected) >= limit or (per_platform > 0 and count >= per_platform):
                break
            key = first_text(row.get("canonical_url")).casefold()
            selected.append(row)
            selected_keys.add(key)
            count += 1

    for row in candidates:
        if len(selected) >= limit:
            break
        key = first_text(row.get("canonical_url")).casefold()
        if key not in selected_keys:
            selected.append(row)
            selected_keys.add(key)
    return selected


def excerpt(value: str, limit: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", first_text(value))
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def parse_json_output(result: CommandResult) -> tuple[dict[str, Any] | None, str]:
    if result.returncode != 0:
        return None, excerpt(result.stderr or result.stdout, 400)
    text = result.stdout.strip()
    if not text:
        return None, "empty stdout"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"json parse failed: {exc}"
    if not isinstance(payload, dict):
        return None, "json output was not an object"
    return payload, ""


def safe_external_links(anchors: list[Any], page_url: str, limit: int = 20) -> list[dict[str, str]]:
    page_host = parse.urlparse(page_url).netloc.casefold().replace("www.", "")
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        href = unwrap_redirect_url(first_text(anchor.get("href")))
        parsed = parse.urlparse(href)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        host = parsed.netloc.casefold().replace("www.", "")
        if any(marker in host for marker in ("checkout", "login", "accounts")):
            continue
        if host == page_host:
            continue
        parts = {part.casefold() for part in url_parts(href)}
        if parts & PRIVATE_OR_ACTION_SEGMENTS:
            continue
        if is_generic_external(parsed, host):
            continue
        normalized = normalize_url(href)
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(
            {
                "url": normalized,
                "domain": host,
                "text": excerpt(first_text(anchor.get("text")), 120),
            }
        )
        if len(links) >= limit:
            break
    return links


def unwrap_redirect_url(href: str) -> str:
    parsed = parse.urlparse(first_text(href))
    host = parsed.netloc.casefold().replace("www.", "")
    if host in {"l.instagram.com", "gate.sc"}:
        query = parse.parse_qs(parsed.query)
        for key in ("u", "url", "target"):
            value = query.get(key, [""])[0]
            if value:
                decoded = parse.unquote(value)
                if parse.urlparse(decoded).scheme in {"http", "https"}:
                    return decoded
    return first_text(href)


def is_generic_external(parsed: parse.ParseResult, host: str) -> bool:
    path = parsed.path or "/"
    lowered_path = path.casefold()
    suffix = Path(parse.urlparse(parse.urlunparse(parsed)).path).suffix.casefold()
    if host in GENERIC_EXTERNAL_HOSTS:
        return True
    if suffix in IMAGE_EXTENSIONS:
        return True
    if host == "bandcamp.com" and any(
        lowered_path == prefix or lowered_path.startswith(prefix + "/")
        for prefix in GENERIC_BANDCAMP_PATH_PREFIXES
    ):
        return True
    if host.endswith(".bandcamp.com") and any(
        segment in lowered_path for segment in ("/album/", "/track/")
    ):
        return True
    if host == "facebook.com" and lowered_path.startswith("/help"):
        return True
    if host in {"instagram.com", "soundcloud.com", "threads.com", "youtube.com"} and lowered_path in {"", "/"}:
        return True
    if host in {"soundcloud.com", "instagram.com", "threads.com", "youtube.com", "youtu.be"}:
        return False
    if host.endswith(".bandcamp.com") or host.endswith("residentadvisor.net") or host in {"ra.co", "linktr.ee", "linktree.com"}:
        return False
    return not bool(first_text(parsed.netloc))


def image_hash(value: str) -> str:
    raw = first_text(value)
    if not raw:
        return ""
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def image_host(value: str) -> str:
    parsed = parse.urlparse(first_text(value))
    return parsed.netloc.casefold().replace("www.", "")


def display_name_from_title(candidate: dict[str, Any], metadata: dict[str, Any]) -> str:
    title = first_text(metadata.get("ogTitle") or metadata.get("title"))
    platform = first_text(candidate.get("platform"))
    handle = first_text(candidate.get("profile_handle"))
    if platform == "instagram":
        title = re.sub(r"\s*\(@" + re.escape(handle) + r"\).*$", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\s*•\s*Instagram.*$", "", title, flags=re.IGNORECASE).strip()
    elif platform == "soundcloud":
        title = re.sub(r"^Stream\s+", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"\s+music\s*\|.*$", "", title, flags=re.IGNORECASE).strip()
    elif platform == "bandcamp":
        if "|" in title:
            title = title.split("|")[-1].strip()
    elif platform == "linktree":
        title = re.sub(r"\s*\|\s*Linktree.*$", "", title, flags=re.IGNORECASE).strip()
    return excerpt(title, 160)


def classify_decision(candidate: dict[str, Any], metadata: dict[str, Any], error: str) -> str:
    if error:
        return "blocked_external_gate"
    title = first_text(metadata.get("title") or metadata.get("ogTitle"))
    text = first_text(metadata.get("textSample") or metadata.get("description"))
    if not title and not text:
        return "blocked_external_gate"
    lower = f"{title} {text}".casefold()
    if "log in" in lower and "profile" not in lower and "instagram" in first_text(candidate.get("platform")):
        return "blocked_external_gate"
    return "report_ready"


def evidence_row_from_metadata(
    candidate: dict[str, Any],
    metadata: dict[str, Any],
    *,
    profile: str,
    session: str,
    error: str = "",
) -> dict[str, Any]:
    final_url = first_text(metadata.get("url")) or first_text(candidate.get("canonical_url"))
    canonical = first_text(metadata.get("canonical")) or normalize_url(final_url)
    row = {
        "schema_version": SCHEMA_VERSION + ".row",
        "source_prd": "PRD-16",
        "source_report": first_text(candidate.get("source_report")),
        "source_row_id": first_text(candidate.get("source_row_id")),
        "source_status": first_text(candidate.get("source_status")),
        "subject_name": first_text(candidate.get("subject_name")),
        "input_url": first_text(candidate.get("input_url")),
        "final_url": final_url,
        "canonical_url": normalize_url(canonical),
        "domain": parse.urlparse(final_url).netloc.casefold().replace("www.", ""),
        "platform": first_text(candidate.get("platform")),
        "access_mode": "opencli_browser_profile",
        "browser_profile": profile,
        "browser_session": session,
        "render_needed": True,
        "rendered_title": excerpt(first_text(metadata.get("title") or metadata.get("ogTitle")), 240),
        "profile_display_name": display_name_from_title(candidate, metadata),
        "profile_handle": first_text(candidate.get("profile_handle")),
        "bio_excerpt": excerpt(first_text(metadata.get("description") or metadata.get("textSample")), 500),
        "external_links": safe_external_links(metadata.get("anchors") if isinstance(metadata.get("anchors"), list) else [], final_url),
        "profile_image_url_or_hash": image_hash(first_text(metadata.get("image"))),
        "profile_image_host": image_host(first_text(metadata.get("image"))),
        "evidence_url": first_text(candidate.get("evidence_url")),
        "identity_proof": False,
        "graph_ready": False,
        "staging_only": True,
        "unsafe_action": False,
        "write_scope": "reports_only",
        "safety_notes": [
            "no_cookie_or_token_export",
            "no_account_action",
            "no_private_or_follower_only_collection",
            "no_graph_vector_db_write",
            "report_only",
        ],
        "opencli_error": excerpt(error, 400),
    }
    row["decision"] = classify_decision(candidate, metadata, error)
    return row


def run_opencli_json(args: list[str], runner: Runner, timeout_sec: float) -> tuple[dict[str, Any] | None, str, CommandResult]:
    result = runner(args, timeout_sec)
    payload, error = parse_json_output(result)
    if result.timed_out:
        error = result.stderr or "timeout"
    return payload, error, result


def probe_candidate(
    candidate: dict[str, Any],
    *,
    opencli_bin: str,
    profile: str,
    session: str,
    timeout_sec: float,
    wait_sec: float,
    runner: Runner,
) -> dict[str, Any]:
    url = first_text(candidate.get("input_url"))
    open_args = [opencli_bin, "--profile", profile, "browser", session, "open", url]
    open_result = runner(open_args, timeout_sec)
    if open_result.returncode != 0 or open_result.timed_out:
        return evidence_row_from_metadata(
            candidate,
            {},
            profile=profile,
            session=session,
            error=first_text(open_result.stderr or open_result.stdout or "opencli open failed"),
        )

    if wait_sec > 0:
        wait_args = [opencli_bin, "--profile", profile, "browser", session, "wait", "time", str(wait_sec)]
        wait_result = runner(wait_args, max(timeout_sec, wait_sec + 5))
        if wait_result.returncode != 0 or wait_result.timed_out:
            return evidence_row_from_metadata(
                candidate,
                {},
                profile=profile,
                session=session,
                error=first_text(wait_result.stderr or wait_result.stdout or "opencli wait failed"),
            )

    eval_args = [opencli_bin, "--profile", profile, "browser", session, "eval", PAGE_EVAL_JS]
    metadata, error, _ = run_opencli_json(eval_args, runner, timeout_sec)
    return evidence_row_from_metadata(
        candidate,
        metadata or {},
        profile=profile,
        session=session,
        error=error,
    )


def run_health_checks(
    *,
    opencli_bin: str,
    profile: str,
    runner: Runner,
    timeout_sec: float,
    skip_profile_use: bool,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "opencli_bin": opencli_bin,
        "browser_profile": profile,
        "profile_use": {"skipped": skip_profile_use},
        "doctor": {},
    }
    if not skip_profile_use:
        result = runner([opencli_bin, "profile", "use", profile], timeout_sec)
        checks["profile_use"] = {
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "stdout_excerpt": excerpt(result.stdout, 300),
            "stderr_excerpt": excerpt(result.stderr, 300),
        }
    result = runner([opencli_bin, "doctor"], timeout_sec)
    checks["doctor"] = {
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "stdout_excerpt": excerpt(result.stdout, 600),
        "stderr_excerpt": excerpt(result.stderr, 300),
    }
    return checks


def build_canary(
    *,
    graph_candidates: Path,
    identity_review: Path,
    social_deep_dir: Path,
    out_dir: Path,
    allowed_platforms: set[str],
    limit: int,
    per_platform: int,
    profile: str,
    session: str,
    opencli_bin: str,
    timeout_sec: float,
    wait_sec: float,
    dry_run: bool,
    skip_profile_use: bool,
    runner: Runner = command_runner,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    collected, skipped = collect_candidates(
        graph_candidates=graph_candidates,
        identity_review=identity_review,
        social_deep_dir=social_deep_dir,
        allowed_platforms=allowed_platforms,
    )
    selected = select_candidates(collected, limit=limit, per_platform=per_platform)

    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "social_profile_evidence_queue.jsonl", selected)

    health = run_health_checks(
        opencli_bin=opencli_bin,
        profile=profile,
        runner=runner,
        timeout_sec=timeout_sec,
        skip_profile_use=skip_profile_use,
    )
    write_json(out_dir / "opencli_health.json", health)

    rows: list[dict[str, Any]] = []
    if dry_run:
        rows = [
            evidence_row_from_metadata(
                candidate,
                {},
                profile=profile,
                session=session,
                error="dry_run_no_browser_probe",
            )
            for candidate in selected
        ]
    else:
        for candidate in selected:
            rows.append(
                probe_candidate(
                    candidate,
                    opencli_bin=opencli_bin,
                    profile=profile,
                    session=session,
                    timeout_sec=timeout_sec,
                    wait_sec=wait_sec,
                    runner=runner,
                )
            )

    write_jsonl(out_dir / "social_profile_evidence.jsonl", rows)

    decisions = Counter(first_text(row.get("decision")) for row in rows)
    platform_counts = Counter(first_text(row.get("platform")) for row in rows)
    external_link_rows = sum(1 for row in rows if row.get("external_links"))
    if not selected:
        decision = "blocked_external_gate"
    elif rows and decisions and all(key == "report_ready" for key in decisions):
        decision = "report_ready"
    elif decisions.get("report_ready", 0) > 0:
        decision = "report_ready_with_blocked_rows"
    else:
        decision = "blocked_external_gate"

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": bool(selected),
        "source_prd": "PRD-16",
        "out_dir": str(out_dir),
        "queue_path": str(out_dir / "social_profile_evidence_queue.jsonl"),
        "evidence_path": str(out_dir / "social_profile_evidence.jsonl"),
        "health_path": str(out_dir / "opencli_health.json"),
        "browser_profile": profile,
        "browser_session": session,
        "dry_run": dry_run,
        "candidate_rows_collected": len(collected),
        "candidate_rows_selected": len(selected),
        "evidence_rows": len(rows),
        "decision_counts": dict(decisions),
        "platform_counts": dict(platform_counts),
        "rows_with_external_links": external_link_rows,
        "skipped": skipped,
        "safety": [
            "reports_only",
            "browser_profile_handle_only_no_cookie_token_export",
            "no_account_action",
            "no_private_or_follower_only_collection",
            "no_graph_vector_db_write",
            "no_production_label",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
    }
    write_json(out_dir / "social_profile_evidence_summary.json", summary)
    write_markdown(out_dir / "social_profile_evidence_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-16 OpenCLI Social Profile Evidence Canary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- browser_profile: `{summary['browser_profile']}`",
        f"- browser_session: `{summary['browser_session']}`",
        f"- candidate_rows_collected: `{summary['candidate_rows_collected']}`",
        f"- candidate_rows_selected: `{summary['candidate_rows_selected']}`",
        f"- evidence_rows: `{summary['evidence_rows']}`",
        f"- rows_with_external_links: `{summary['rows_with_external_links']}`",
        f"- queue_path: `{summary['queue_path']}`",
        f"- evidence_path: `{summary['evidence_path']}`",
        f"- health_path: `{summary['health_path']}`",
        "",
        "## Decisions",
        "",
    ]
    for key, value in sorted(summary["decision_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Platforms", ""])
    for key, value in sorted(summary["platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Skipped", ""])
    for key, value in sorted(summary["skipped"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- Browser profile is referenced by handle only; no cookie/token export.",
            "- No account actions, private/follower-only collection, graph/vector/DB writes, production labels, paid API, D: scan, or publish.",
            "- Rows remain review evidence only: `identity_proof=false`, `graph_ready=false`, `staging_only=true`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_platforms(value: str) -> set[str]:
    platforms = {part.strip().casefold() for part in value.split(",") if part.strip()}
    return platforms or set(ALLOWED_PLATFORMS)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-candidates", type=Path, default=DEFAULT_GRAPH_CANDIDATES)
    parser.add_argument("--identity-review", type=Path, default=DEFAULT_IDENTITY_REVIEW)
    parser.add_argument("--social-deep-dir", type=Path, default=DEFAULT_SOCIAL_DEEP_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--platforms", default=",".join(sorted(ALLOWED_PLATFORMS)))
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--per-platform", type=int, default=3)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--opencli-bin", default="opencli")
    parser.add_argument("--timeout-sec", type=float, default=35.0)
    parser.add_argument("--wait-sec", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-profile-use", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build_canary(
        graph_candidates=args.graph_candidates,
        identity_review=args.identity_review,
        social_deep_dir=args.social_deep_dir,
        out_dir=args.out_dir,
        allowed_platforms=parse_platforms(args.platforms),
        limit=args.limit,
        per_platform=args.per_platform,
        profile=args.profile,
        session=args.session,
        opencli_bin=args.opencli_bin,
        timeout_sec=args.timeout_sec,
        wait_sec=args.wait_sec,
        dry_run=args.dry_run,
        skip_profile_use=args.skip_profile_use,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
