#!/usr/bin/env python3
"""Audit mini-program Atlas relation surface coverage.

Report-only. Reads the packaged ``atlas_index.json.gz`` and optionally probes a
public Weekly API base URL. It does not mutate data, call models, read secrets,
or write production state.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ATLAS_INDEX = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_index.json.gz"
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_atlas_relation_surface_audit_20260531"
DEFAULT_PUBLIC_BASE = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com"
DEFAULT_ARTIST_SAMPLES = ["Ozone"]
DEFAULT_VENUE_SAMPLES = ["OIL", "POOLS"]
SOURCE_REF_RE = re.compile(r"^(src|source|source_ref|evidence|activity_src|atlas_src):", re.I)


def read_atlas_index(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def text(value: Any) -> str:
    return str(value or "").strip()


def norm_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9一-鿿]", "", text(value).lower())


def build_subject_maps(idx: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for subject in idx.get("subjects") if isinstance(idx.get("subjects"), list) else []:
        if not isinstance(subject, dict):
            continue
        subject_id = text(subject.get("i"))
        if not subject_id:
            continue
        by_id[subject_id] = subject
        keys = [
            text(subject.get("nn")),
            norm_key(subject.get("n")),
            *[norm_key(alias) for alias in subject.get("a", []) if isinstance(alias, str)],
        ]
        for key in [key for key in keys if key]:
            by_name.setdefault(key, []).append(subject)
    return by_id, by_name


def search_subject(idx: dict[str, Any], by_name: dict[str, list[dict[str, Any]]], query: str, type_filter: str) -> dict[str, Any] | None:
    qk = norm_key(query)
    if not qk:
        return None
    exact = [row for row in by_name.get(qk, []) if row.get("t") == type_filter]
    if exact:
        return exact[0]
    for subject in idx.get("subjects") if isinstance(idx.get("subjects"), list) else []:
        if not isinstance(subject, dict) or subject.get("t") != type_filter:
            continue
        nn = text(subject.get("nn"))
        name = text(subject.get("n"))
        if nn.startswith(qk) or norm_key(name).startswith(qk) or qk in nn or qk in norm_key(name):
            return subject
    return None


def public_source_fields_ok(events: list[dict[str, Any]], source_refs: set[str]) -> tuple[int, int, int]:
    with_ref = 0
    missing_lookup = 0
    invalid_prefix = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        ref = text(event.get("sr"))
        if not ref:
            continue
        with_ref += 1
        if ref not in source_refs:
            missing_lookup += 1
        if not SOURCE_REF_RE.search(ref):
            invalid_prefix += 1
    return with_ref, missing_lookup, invalid_prefix


def audit_artist(idx: dict[str, Any], by_name: dict[str, list[dict[str, Any]]], source_refs: set[str], name: str) -> dict[str, Any]:
    subject = search_subject(idx, by_name, name, "dj")
    if not subject:
        return {"name": name, "found": False, "failed_checks": ["artist_not_found"]}
    dj_id = text(subject.get("i"))
    events = [row for row in (idx.get("events", {}) or {}).get(dj_id, []) if isinstance(row, dict)]
    venues = [row for row in (idx.get("dj_venues", {}) or {}).get(dj_id, []) if isinstance(row, dict)]
    collaborators = [row for row in (idx.get("collabs", {}) or {}).get(dj_id, []) if isinstance(row, dict)]
    event_refs, missing_refs, invalid_refs = public_source_fields_ok(events, source_refs)
    failed = []
    if not events:
        failed.append("artist_events_missing")
    if not venues:
        failed.append("artist_frequent_venues_missing")
    if not collaborators:
        failed.append("artist_collaborators_missing")
    if event_refs == 0:
        failed.append("artist_event_source_refs_missing")
    if missing_refs:
        failed.append("artist_event_source_ref_lookup_missing")
    if invalid_refs:
        failed.append("artist_event_source_ref_prefix_invalid")
    return {
        "name": name,
        "found": True,
        "subject_id": dj_id,
        "display_name": text(subject.get("n")),
        "event_count": len(events),
        "frequent_venue_count": len(venues),
        "collaborator_count": len(collaborators),
        "event_source_ref_count": event_refs,
        "event_missing_source_ref_lookup_count": missing_refs,
        "event_invalid_source_ref_prefix_count": invalid_refs,
        "top_venues": venues[:5],
        "top_collaborators": collaborators[:5],
        "failed_checks": failed,
    }


def merged_venue_events(idx: dict[str, Any], by_id: dict[str, dict[str, Any]], subject: dict[str, Any], query: str) -> list[dict[str, Any]]:
    primary_id = text(subject.get("i"))
    primary_city = text(subject.get("c")).lower()
    events = list((idx.get("venue_events", {}) or {}).get(primary_id, []))
    for venue_id in (idx.get("venue_by_name", {}) or {}).get(norm_key(query), []) or []:
        venue_id = text(venue_id)
        if not venue_id or venue_id == primary_id:
            continue
        candidate = by_id.get(venue_id) or {}
        candidate_city = text(candidate.get("c")).lower()
        if candidate_city and primary_city and candidate_city != primary_city:
            continue
        events.extend((idx.get("venue_events", {}) or {}).get(venue_id, []))
    deduped = []
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = text(event.get("eid")) or json.dumps(event, sort_keys=True, ensure_ascii=False)
        if event_id in seen:
            continue
        seen.add(event_id)
        deduped.append(event)
    return deduped


def audit_venue(
    idx: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    by_name: dict[str, list[dict[str, Any]]],
    source_refs: set[str],
    name: str,
) -> dict[str, Any]:
    subject = search_subject(idx, by_name, name, "venue") or search_subject(idx, by_name, name, "organizer")
    if not subject:
        return {"name": name, "found": False, "failed_checks": ["venue_not_found"]}
    events = merged_venue_events(idx, by_id, subject, name)
    dj_counts = Counter(text(event.get("di")) for event in events if text(event.get("di")))
    event_refs, missing_refs, invalid_refs = public_source_fields_ok(events, source_refs)
    failed = []
    if not events:
        failed.append("venue_events_missing")
    if not dj_counts:
        failed.append("venue_resident_djs_missing")
    if event_refs == 0:
        failed.append("venue_event_source_refs_missing")
    if missing_refs:
        failed.append("venue_event_source_ref_lookup_missing")
    if invalid_refs:
        failed.append("venue_event_source_ref_prefix_invalid")
    return {
        "name": name,
        "found": True,
        "subject_id": text(subject.get("i")),
        "display_name": text(subject.get("n")),
        "event_count": len(events),
        "resident_dj_count": len(dj_counts),
        "event_source_ref_count": event_refs,
        "event_missing_source_ref_lookup_count": missing_refs,
        "event_invalid_source_ref_prefix_count": invalid_refs,
        "top_resident_djs": [{"dj_id": dj_id, "event_count": count} for dj_id, count in dj_counts.most_common(5)],
        "failed_checks": failed,
    }


def fetch_public_json(base_url: str, path: str, params: dict[str, Any], *, retries: int = 2, timeout: float = 15.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
    last_error = ""
    for attempt in range(retries + 1):
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                raw = response.read()
                return {
                    "url": url,
                    "ok": 200 <= response.status < 300,
                    "status": response.status,
                    "ms": round((time.perf_counter() - start) * 1000),
                    "payload": json.loads(raw.decode("utf-8")),
                    "attempts": attempt + 1,
                }
        except Exception as exc:  # pragma: no cover - network diagnostic path
            last_error = str(exc)
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    return {"url": url, "ok": False, "error": last_error, "attempts": retries + 1}


def audit_public(base_url: str, artist_samples: list[str], venue_samples: list[str]) -> dict[str, Any]:
    artist_rows = []
    venue_rows = []
    failed = []
    for name in artist_samples:
        row = fetch_public_json(base_url, "/api/v1/weekly/atlas/artist", {
            "name": name,
            "eventLimit": 20,
            "collaboratorLimit": 10,
            "venueLimit": 10,
        })
        payload = row.get("payload") or {}
        summary = {
            "name": name,
            "ok": row.get("ok", False) and bool(payload.get("found")),
            "status": row.get("status"),
            "ms": row.get("ms"),
            "attempts": row.get("attempts"),
            "events": len(payload.get("events") or []),
            "collaborators": len(payload.get("collaborators") or []),
            "venues": len(payload.get("venues") or []),
            "error": row.get("error", ""),
        }
        if not summary["ok"] or not summary["events"] or not summary["collaborators"] or not summary["venues"]:
            failed.append({"surface": "public_artist", "name": name, "summary": summary})
        artist_rows.append(summary)
    for name in venue_samples:
        row = fetch_public_json(base_url, "/api/v1/weekly/atlas/venue", {"name": name, "eventLimit": 20})
        payload = row.get("payload") or {}
        summary = {
            "name": name,
            "ok": row.get("ok", False) and bool(payload.get("found")),
            "status": row.get("status"),
            "ms": row.get("ms"),
            "attempts": row.get("attempts"),
            "events": len(payload.get("events") or []),
            "residentDJs": len(payload.get("residentDJs") or []),
            "error": row.get("error", ""),
        }
        if not summary["ok"] or not summary["events"] or not summary["residentDJs"]:
            failed.append({"surface": "public_venue", "name": name, "summary": summary})
        venue_rows.append(summary)
    return {"base_url": base_url, "artists": artist_rows, "venues": venue_rows, "failed": failed}


def build_report(
    atlas_index_path: Path,
    artist_samples: list[str],
    venue_samples: list[str],
    *,
    public_base: str = "",
) -> dict[str, Any]:
    idx = read_atlas_index(atlas_index_path)
    by_id, by_name = build_subject_maps(idx)
    source_refs = set((idx.get("source_refs") or {}).keys())
    artists = [audit_artist(idx, by_name, source_refs, name) for name in artist_samples]
    venues = [audit_venue(idx, by_id, by_name, source_refs, name) for name in venue_samples]
    public = audit_public(public_base, artist_samples, venue_samples) if public_base else {"enabled": False}
    findings = []
    for row in artists:
        for check in row.get("failed_checks", []):
            findings.append({"surface": "local_artist", "name": row.get("name"), "check": check})
    for row in venues:
        for check in row.get("failed_checks", []):
            findings.append({"surface": "local_venue", "name": row.get("name"), "check": check})
    for row in public.get("failed", []) if isinstance(public, dict) else []:
        findings.append({"surface": row.get("surface"), "name": row.get("name"), "check": "public_probe_failed", "summary": row.get("summary")})
    decision = "weekly_atlas_relation_surface_passed" if not findings else "weekly_atlas_relation_surface_findings"
    return {
        "schema_version": "weekly_atlas_relation_surface_audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "report_only": True,
        "mutations_executed": False,
        "model_calls_performed": False,
        "atlas_index_path": str(atlas_index_path),
        "artist_samples": artists,
        "venue_samples": venues,
        "public_probe": public,
        "findings": findings,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Weekly Atlas Relation Surface Audit",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Findings: `{len(report['findings'])}`",
        f"- Report only: `{str(report['report_only']).lower()}`",
        f"- Mutations executed: `{str(report['mutations_executed']).lower()}`",
        f"- Model calls performed: `{str(report['model_calls_performed']).lower()}`",
        "",
        "## Local Artist Samples",
    ]
    for row in report["artist_samples"]:
        lines.append(
            f"- `{row['name']}` found `{row.get('found')}` events `{row.get('event_count', 0)}` "
            f"collaborators `{row.get('collaborator_count', 0)}` venues `{row.get('frequent_venue_count', 0)}` "
            f"source refs `{row.get('event_source_ref_count', 0)}` failed `{row.get('failed_checks', [])}`"
        )
    lines.append("")
    lines.append("## Local Venue Samples")
    for row in report["venue_samples"]:
        lines.append(
            f"- `{row['name']}` found `{row.get('found')}` events `{row.get('event_count', 0)}` "
            f"resident DJs `{row.get('resident_dj_count', 0)}` source refs `{row.get('event_source_ref_count', 0)}` "
            f"failed `{row.get('failed_checks', [])}`"
        )
    public = report.get("public_probe") or {}
    if public.get("base_url"):
        lines.extend(["", "## Public Probe"])
        for row in public.get("artists", []):
            lines.append(f"- artist `{row['name']}` ok `{row['ok']}` events `{row['events']}` collaborators `{row['collaborators']}` venues `{row['venues']}` ms `{row.get('ms')}` attempts `{row.get('attempts')}`")
        for row in public.get("venues", []):
            lines.append(f"- venue `{row['name']}` ok `{row['ok']}` events `{row['events']}` residentDJs `{row['residentDJs']}` ms `{row.get('ms')}` attempts `{row.get('attempts')}`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit mini-program Atlas relation surface")
    parser.add_argument("--atlas-index", type=Path, default=DEFAULT_ATLAS_INDEX)
    parser.add_argument("--artist", action="append", dest="artists", default=[])
    parser.add_argument("--venue", action="append", dest="venues", default=[])
    parser.add_argument("--public-base", default="", help="Optional public API base URL to probe")
    parser.add_argument("--default-public-base", action="store_true", help="Probe the configured CloudRun public default domain")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    artists = args.artists or DEFAULT_ARTIST_SAMPLES
    venues = args.venues or DEFAULT_VENUE_SAMPLES
    public_base = DEFAULT_PUBLIC_BASE if args.default_public_base else args.public_base.strip()
    report = build_report(args.atlas_index, artists, venues, public_base=public_base)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "weekly_atlas_relation_surface_audit.json"
    md_path = args.out_dir / "weekly_atlas_relation_surface_audit.md"
    write_json(json_path, report)
    write_markdown(md_path, report)
    print(json.dumps({
        "decision": report["decision"],
        "findings": len(report["findings"]),
        "json": str(json_path),
        "markdown": str(md_path),
    }, ensure_ascii=False, indent=2))
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
