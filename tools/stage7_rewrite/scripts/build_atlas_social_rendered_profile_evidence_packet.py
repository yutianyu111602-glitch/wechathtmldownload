#!/usr/bin/env python3
"""Build a report-only rendered public-profile evidence packet for Atlas T6.

This gate consumes the T6 manual acceptance queue and the previous bounded
SoundCloud metadata fetch. It uses OpenCLI to render only bounded public profile
URLs, stores sanitized metadata/hash evidence, and keeps all graph/product write
guards closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib import parse


DEFAULT_MANUAL_QUEUE = Path(
    "tools/stage7_rewrite/reports/"
    "atlas_social_identity_acceptance_gate_q6_20260524_0224/"
    "atlas_social_identity_manual_acceptance_review_queue.jsonl"
)
DEFAULT_BOUNDED_FETCH = Path(
    "tools/stage7_rewrite/reports/"
    "atlas_social_outlink_bounded_fetch_q6_20260523_2327/"
    "atlas_social_outlink_bounded_fetch_results.jsonl"
)
DEFAULT_OUT_DIR = Path("tools/stage7_rewrite/reports/atlas_social_rendered_profile_evidence_q6_20260524_0328")
DEFAULT_REPORT = Path("reports/ATLAS_T6_RENDERED_PROFILE_EVIDENCE_PACKET_20260524.md")
DEFAULT_PROFILE = "ejk3c3qe"
DEFAULT_SESSION = "stage7-social-rendered-profile"
SCHEMA_VERSION = "stage7_atlas_social_rendered_profile_evidence.v1"

PAGE_EVAL_JS = (
    "(() => { const q=s=>document.querySelector(s); "
    "const g=s=>{const n=q(s); return n ? String(n.content||n.href||n.textContent||'').trim() : '';}; "
    "const text=((document.body&&document.body.innerText)||'').replace(/\\s+/g,' ').trim(); "
    "return {url:location.href,title:document.title||'',canonical:g('link[rel=canonical]'),"
    "ogTitle:g('meta[property=\"og:title\"]')||g('meta[name=\"og:title\"]'),"
    "description:g('meta[property=\"og:description\"]')||g('meta[name=description]'),"
    "image:g('meta[property=\"og:image\"]')||g('meta[name=\"twitter:image\"]'),"
    "textSample:text.slice(0,500),"
    "anchors:Array.from(document.querySelectorAll('a[href]')).slice(0,80).map(a=>({href:a.href||'',"
    "text:(a.innerText||a.textContent||'').replace(/\\s+/g,' ').trim().slice(0,120)}))}; })()"
)

GENERIC_HOSTS = {
    "about.soundcloud.com",
    "artists.soundcloud.com",
    "community.soundcloud.com",
    "developers.soundcloud.com",
    "help.soundcloud.com",
    "itunes.apple.com",
    "play.google.com",
}
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


Runner = Callable[[list[str], float], CommandResult]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for rendered profile evidence: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
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
        return CommandResult(127, "", f"command not found: {args[0]}")
    except subprocess.TimeoutExpired as exc:
        return CommandResult(124, first_text(exc.stdout), f"timeout after {timeout_sec}s", timed_out=True)
    return CommandResult(completed.returncode, completed.stdout or "", completed.stderr or "")


def parse_json_output(result: CommandResult) -> tuple[dict[str, Any] | None, str]:
    raw = first_text(result.stdout)
    if not raw:
        return None, first_text(result.stderr) or "empty stdout"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"non-json stdout: {exc}"
    if not isinstance(payload, dict):
        return None, "stdout json is not an object"
    return payload, ""


def normalize_compact(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())


def normalize_url(url: str) -> str:
    parsed = parse.urlparse(first_text(url))
    if not parsed.scheme or not parsed.netloc:
        return first_text(url)
    host = parsed.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    path = parse.unquote(parsed.path or "/")
    path = re.sub(r"/+", "/", path).rstrip("/") or "/"
    return parse.urlunparse((parsed.scheme.casefold(), host, path, "", "", ""))


def host_of(url: str) -> str:
    host = parse.urlparse(first_text(url)).netloc.casefold()
    return host[4:] if host.startswith("www.") else host


def image_hash(value: str) -> str:
    raw = first_text(value)
    if not raw:
        return ""
    parsed = parse.urlparse(raw)
    safe_basis = parse.urlunparse((parsed.scheme, parsed.netloc.casefold(), parsed.path, "", "", ""))
    digest = hashlib.sha256(safe_basis.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def safe_external_links(anchors: list[Any], base_url: str) -> list[dict[str, str]]:
    own_host = host_of(base_url)
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in anchors[:80]:
        if not isinstance(anchor, dict):
            continue
        raw_href = first_text(anchor.get("href"))
        if not raw_href:
            continue
        absolute = parse.urljoin(base_url, raw_href)
        parsed = parse.urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        domain = host_of(absolute)
        path = parsed.path or "/"
        if domain == own_host or domain in GENERIC_HOSTS:
            continue
        if Path(path).suffix.casefold() in IMAGE_EXTENSIONS:
            continue
        normalized = normalize_url(absolute)
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(
            {
                "url": normalized,
                "domain": domain,
                "text": first_text(anchor.get("text"))[:120],
            }
        )
    return links[:20]


def fetch_by_entity(fetch_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_entity: dict[str, dict[str, Any]] = {}
    for row in fetch_rows:
        if first_text(row.get("target_kind")) != "profile_page":
            continue
        key = first_text(row.get("entity_search_id"))
        if key and key not in by_entity:
            by_entity[key] = row
    return by_entity


def join_candidates(manual_rows: list[dict[str, Any]], fetch_rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    fetch_lookup = fetch_by_entity(fetch_rows)
    candidates: list[dict[str, Any]] = []
    for manual in manual_rows:
        entity = first_text(manual.get("entity_search_id"))
        fetch = fetch_lookup.get(entity, {})
        url = first_text(fetch.get("target_url") or fetch.get("canonical_url"))
        if not url:
            continue
        candidates.append(
            {
                "manual": manual,
                "fetch": fetch,
                "entity_search_id": entity,
                "name": first_text(manual.get("name") or manual.get("atlas_display_name")),
                "target_url": url,
                "normalized_url": normalize_url(url),
            }
        )
        if limit > 0 and len(candidates) >= limit:
            break
    return candidates


def opencli_eval(url: str, *, opencli_bin: str, profile: str, session: str, timeout_sec: float, wait_sec: float, runner: Runner) -> tuple[dict[str, Any], str]:
    open_result = runner([opencli_bin, "--profile", profile, "browser", session, "open", url], timeout_sec)
    if open_result.returncode != 0 or open_result.timed_out:
        return {}, first_text(open_result.stderr) or "opencli open failed"
    if wait_sec > 0:
        wait_result = runner([opencli_bin, "--profile", profile, "browser", session, "wait", "time", str(wait_sec)], max(timeout_sec, wait_sec + 5))
        if wait_result.returncode != 0 or wait_result.timed_out:
            return {}, first_text(wait_result.stderr) or "opencli wait failed"
    eval_result = runner([opencli_bin, "--profile", profile, "browser", session, "eval", PAGE_EVAL_JS], timeout_sec)
    payload, error = parse_json_output(eval_result)
    if eval_result.returncode != 0 or eval_result.timed_out:
        error = error or first_text(eval_result.stderr) or "opencli eval failed"
    return payload or {}, error


def evidence_row(candidate: dict[str, Any], metadata: dict[str, Any], error: str) -> dict[str, Any]:
    manual = candidate["manual"]
    fetch = candidate["fetch"]
    name = first_text(candidate.get("name"))
    final_url = first_text(metadata.get("url") or candidate.get("target_url"))
    canonical = first_text(metadata.get("canonical") or final_url)
    title = first_text(metadata.get("title") or metadata.get("ogTitle"))
    og_title = first_text(metadata.get("ogTitle"))
    description = first_text(metadata.get("description"))
    text_sample = first_text(metadata.get("textSample"))[:500]
    haystack = " ".join([title, og_title, description, text_sample, canonical])
    name_compact = normalize_compact(name)
    rendered_profile_metadata_present = bool(title or og_title or description)
    subject_match = bool(name_compact and name_compact in normalize_compact(haystack))
    url_match = normalize_url(canonical) == normalize_url(candidate["target_url"]) or host_of(canonical).endswith("soundcloud.com")
    profile_image_hash = image_hash(first_text(metadata.get("image")))
    external_links = safe_external_links(metadata.get("anchors") if isinstance(metadata.get("anchors"), list) else [], final_url)
    row_decision = "rendered_profile_evidence_review_ready" if not error and rendered_profile_metadata_present else "rendered_profile_evidence_blocked"
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": now_iso(),
        "decision": row_decision,
        "opencli_error": first_text(error)[:400],
        "entity_search_id": first_text(manual.get("entity_search_id")),
        "atlas_dj_id": first_text(manual.get("atlas_dj_id")),
        "name": name,
        "atlas_display_name": first_text(manual.get("atlas_display_name")),
        "target_url": first_text(candidate.get("target_url")),
        "canonical_url": canonical,
        "final_url": final_url,
        "rendered_title": title,
        "rendered_og_title": og_title,
        "description_excerpt": description[:400],
        "text_sample_excerpt": text_sample,
        "profile_image_url_or_hash": profile_image_hash,
        "profile_image_host": host_of(first_text(metadata.get("image"))),
        "external_links": external_links,
        "bounded_fetch_page_title": first_text(fetch.get("page_title")),
        "bounded_fetch_og_title": first_text(fetch.get("og_title")),
        "signals": {
            "rendered_profile_metadata_present": rendered_profile_metadata_present,
            "subject_in_rendered_public_profile": subject_match,
            "profile_url_public_soundcloud": host_of(final_url).endswith("soundcloud.com"),
            "canonical_or_final_url_matches_candidate": url_match,
            "profile_image_hash_present": bool(profile_image_hash),
            "external_links_present": bool(external_links),
        },
        "accepted_for_graph": False,
        "identity_proof": False,
        "identity_proof_promoted": False,
        "avatar_display_allowed": False,
        "public_serving_field_allowed": False,
        "graph_write_allowed": False,
        "next_gate": "T5/T7 manual acceptance decision plus separate graph/write gate; this rendered evidence alone is not product truth.",
    }


def build_packet(
    *,
    manual_queue: Path,
    bounded_fetch: Path,
    out_dir: Path,
    report_path: Path,
    opencli_bin: str,
    profile: str,
    session: str,
    limit: int,
    timeout_sec: float,
    wait_sec: float,
    runner: Runner = command_runner,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    manual_rows = read_jsonl(manual_queue)
    fetch_rows = read_jsonl(bounded_fetch)
    candidates = join_candidates(manual_rows, fetch_rows, limit=limit)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        metadata, error = opencli_eval(
            candidate["target_url"],
            opencli_bin=opencli_bin,
            profile=profile,
            session=session,
            timeout_sec=timeout_sec,
            wait_sec=wait_sec,
            runner=runner,
        )
        rows.append(evidence_row(candidate, metadata, error))

    decisions = Counter(first_text(row.get("decision")) for row in rows)
    review_ready = decisions.get("rendered_profile_evidence_review_ready", 0)
    blocked = decisions.get("rendered_profile_evidence_blocked", 0)
    if rows and review_ready == len(rows):
        decision = "atlas_social_rendered_profile_evidence_review_ready"
    elif rows and review_ready:
        decision = "atlas_social_rendered_profile_evidence_partial"
    elif rows:
        decision = "atlas_social_rendered_profile_evidence_blocked_external_gate"
    else:
        decision = "atlas_social_rendered_profile_evidence_empty"

    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = out_dir / "atlas_social_rendered_profile_evidence.jsonl"
    summary_path = out_dir / "atlas_social_rendered_profile_evidence_summary.json"
    write_jsonl(evidence_path, rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": bool(rows),
        "decision": decision,
        "manual_queue_path": str(manual_queue),
        "bounded_fetch_path": str(bounded_fetch),
        "out_dir": str(out_dir),
        "evidence_path": str(evidence_path),
        "report_path": str(report_path),
        "manual_rows": len(manual_rows),
        "bounded_fetch_rows": len(fetch_rows),
        "candidate_rows": len(candidates),
        "rendered_evidence_rows": len(rows),
        "review_ready_rows": review_ready,
        "blocked_rows": blocked,
        "decision_counts": dict(decisions),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "avatar_display_allowed": 0,
        "public_serving_field_allowed": 0,
        "graph_write_allowed": 0,
        "safety": {
            "report_only": True,
            "public_urls_only": True,
            "secret_value_read_or_printed": False,
            "page_body_persisted": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "graph_write_executed": False,
            "mem0_write_executed": False,
            "d_scan_executed": False,
        },
        "next_gate": "T5/T7 strict manual acceptance review; separate graph/write gate remains required before any production mutation.",
    }
    write_json(summary_path, summary)
    write_report(report_path, summary, rows)
    return summary


def write_report(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Atlas T6 Rendered Profile Evidence Packet",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- manual_rows: `{summary['manual_rows']}`",
        f"- candidate_rows: `{summary['candidate_rows']}`",
        f"- rendered_evidence_rows: `{summary['rendered_evidence_rows']}`",
        f"- review_ready_rows: `{summary['review_ready_rows']}`",
        f"- blocked_rows: `{summary['blocked_rows']}`",
        f"- evidence_path: `{summary['evidence_path']}`",
        "",
        "## Rows",
        "",
        "| entity | decision | subject match | image hash | external links | url |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        signals = row.get("signals") if isinstance(row.get("signals"), dict) else {}
        lines.append(
            "| {name} | {decision} | {subject} | {image} | {links} | {url} |".format(
                name=first_text(row.get("name")).replace("|", "/"),
                decision=first_text(row.get("decision")),
                subject=str(bool(signals.get("subject_in_rendered_public_profile"))).lower(),
                image=str(bool(signals.get("profile_image_hash_present"))).lower(),
                links=len(row.get("external_links") if isinstance(row.get("external_links"), list) else []),
                url=first_text(row.get("target_url")),
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only rendered public profile evidence.",
            "- No product truth, avatar display, public serving field, graph/vector/DB write, memory write, model call, paid API, secret read, or D: root scan.",
            "- Profile image URLs are reduced to hashes; only bounded public metadata and a short rendered text sample are persisted.",
            "",
            "## Next Gate",
            "",
            summary["next_gate"],
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manual-queue", type=Path, default=DEFAULT_MANUAL_QUEUE)
    parser.add_argument("--bounded-fetch", type=Path, default=DEFAULT_BOUNDED_FETCH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--opencli-bin", default="opencli")
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=35.0)
    parser.add_argument("--wait-sec", type=float, default=3.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build_packet(
        manual_queue=args.manual_queue,
        bounded_fetch=args.bounded_fetch,
        out_dir=args.out_dir,
        report_path=args.report,
        opencli_bin=args.opencli_bin,
        profile=args.profile,
        session=args.session,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        wait_sec=args.wait_sec,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
