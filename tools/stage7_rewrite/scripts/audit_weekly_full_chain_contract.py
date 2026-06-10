#!/usr/bin/env python3
"""Audit the weekly mini-program release contract end to end.

Report-only. This does not call models, read secrets, mutate CloudRun state, or
write database rows. It checks the currently packaged weekly API data, the
miniapp Atlas JSON index, and the source files that consume Atlas source refs.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RELEASE_DIR = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release"
DEFAULT_ATLAS_INDEX = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_index.json.gz"
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_full_chain_contract_audit_20260531"

ATLAS_REF_RE = re.compile(r"^(src|source|source_ref|evidence|activity_src|atlas_src):", re.I)
CORE_FIELDS = [
    "id",
    "event_id",
    "article_id",
    "title",
    "title_display",
    "event_date_start",
    "city_key",
    "city_keys",
    "venue_id",
    "venue_name",
    "address",
    "geo_lat",
    "geo_lng",
    "source_action",
    "source_article",
    "cover_url",
    "poster_url",
    "lineup_artists",
    "music_styles",
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_text(value: Any) -> str:
    return str(value or "").strip()


def is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(is_present(item) for item in value)
    if isinstance(value, dict):
        return any(is_present(item) for item in value.values())
    return True


def canonical_city_keys(item: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    city_key = safe_text(item.get("city_key"))
    if city_key:
        keys.add(city_key)
    for value in item.get("city_keys") if isinstance(item.get("city_keys"), list) else []:
        value_text = safe_text(value)
        if value_text:
            keys.add(value_text)
    return keys


def audit_current_release(release_dir: Path) -> dict[str, Any]:
    manifest = read_json(release_dir / "manifest.json")
    current = read_json(release_dir / "current.json")
    items = current.get("items") if isinstance(current.get("items"), list) else []
    ids = [safe_text(item.get("id")) for item in items if isinstance(item, dict)]
    id_counts = Counter(ids)
    duplicate_ids = sorted([item_id for item_id, count in id_counts.items() if item_id and count > 1])

    by_id_dir = release_dir / "by-id"
    by_id_files = sorted(by_id_dir.glob("*.json")) if by_id_dir.exists() else []
    by_id_item_ids: set[str] = set()
    by_id_parse_errors: list[str] = []
    for path in by_id_files:
        try:
            payload = read_json(path)
        except Exception as exc:  # pragma: no cover - diagnostic path
            by_id_parse_errors.append(f"{path.name}: {exc}")
            continue
        item = payload.get("item") if isinstance(payload.get("item"), dict) else payload
        item_id = safe_text(item.get("id") or item.get("event_id")) if isinstance(item, dict) else ""
        if item_id:
            by_id_item_ids.add(item_id)
    current_ids = {item_id for item_id in ids if item_id}

    city_item_ids: dict[str, set[str]] = {}
    by_city_dir = release_dir / "by-city"
    by_city_parse_errors: list[str] = []
    if by_city_dir.exists():
        for path in sorted(by_city_dir.glob("*.json")):
            try:
                payload = read_json(path)
            except Exception as exc:  # pragma: no cover - diagnostic path
                by_city_parse_errors.append(f"{path.name}: {exc}")
                continue
            city_key = safe_text(payload.get("city_key") or path.stem)
            rows = payload.get("items") if isinstance(payload.get("items"), list) else []
            city_item_ids[city_key] = {safe_text(item.get("id")) for item in rows if isinstance(item, dict) and safe_text(item.get("id"))}

    city_mismatches: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = safe_text(item.get("id"))
        keys = canonical_city_keys(item)
        if not item_id:
            continue
        for key in keys:
            if item_id not in city_item_ids.get(key, set()):
                city_mismatches.append({"id": item_id, "city_key": key, "problem": "missing_from_by_city"})
        for key, city_ids in city_item_ids.items():
            if item_id in city_ids and key not in keys:
                city_mismatches.append({"id": item_id, "city_key": key, "problem": "extra_in_by_city"})

    field_coverage: dict[str, dict[str, int]] = {}
    for field in CORE_FIELDS:
        present = sum(1 for item in items if isinstance(item, dict) and field in item)
        non_empty = sum(1 for item in items if isinstance(item, dict) and is_present(item.get(field)))
        field_coverage[field] = {"present": present, "non_empty": non_empty, "empty": present - non_empty}

    source_prefixes = Counter()
    source_ref_missing = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        source_ref = safe_text(item.get("sourceRefId") or item.get("source_ref_id"))
        source_hash = safe_text(item.get("sourceHash") or item.get("source_hash") or (item.get("source_action") or {}).get("url_hash"))
        if source_ref:
            source_prefixes[source_ref.split(":", 1)[0] if ":" in source_ref else "no_prefix"] += 1
        elif source_hash:
            source_ref_missing += 1

    return {
        "manifest_item_count": manifest.get("item_count"),
        "current_item_count": len(items),
        "manifest_matches_current": manifest.get("item_count") == len(items),
        "duplicate_ids": duplicate_ids[:50],
        "duplicate_id_count": len(duplicate_ids),
        "by_id_file_count": len(by_id_files),
        "by_id_missing_ids": sorted(current_ids - by_id_item_ids)[:50],
        "by_id_extra_ids": sorted(by_id_item_ids - current_ids)[:50],
        "by_id_parse_error_count": len(by_id_parse_errors),
        "by_id_parse_errors": by_id_parse_errors[:20],
        "by_city_file_count": len(city_item_ids),
        "by_city_mismatch_count": len(city_mismatches),
        "by_city_mismatches": city_mismatches[:80],
        "field_coverage": field_coverage,
        "source_ref_prefix_counts": dict(source_prefixes.most_common()),
        "source_ref_missing_but_hash_present": source_ref_missing,
    }


def audit_atlas_index(index_path: Path) -> dict[str, Any]:
    if not index_path.exists():
        return {"exists": False}
    with gzip.open(index_path, "rt", encoding="utf-8") as handle:
        idx = json.load(handle)

    event_source_prefixes = Counter()
    unrecognized_refs: list[str] = []
    source_ref_ids = set((idx.get("source_refs") or {}).keys())
    missing_source_refs = 0
    event_rows = 0
    for bucket_name in ("events", "venue_events"):
        buckets = idx.get(bucket_name) if isinstance(idx.get(bucket_name), dict) else {}
        for rows in buckets.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                event_rows += 1
                ref = safe_text(row.get("sr"))
                if not ref:
                    continue
                event_source_prefixes[ref.split(":", 1)[0] if ":" in ref else "no_prefix"] += 1
                if not ATLAS_REF_RE.search(ref):
                    unrecognized_refs.append(ref)
                if ref not in source_ref_ids:
                    missing_source_refs += 1

    subjects = idx.get("subjects") if isinstance(idx.get("subjects"), list) else []
    profiles = idx.get("profiles") if isinstance(idx.get("profiles"), dict) else {}
    events = idx.get("events") if isinstance(idx.get("events"), dict) else {}
    dj_venues = idx.get("dj_venues") if isinstance(idx.get("dj_venues"), dict) else {}
    collabs = idx.get("collabs") if isinstance(idx.get("collabs"), dict) else {}
    venue_events = idx.get("venue_events") if isinstance(idx.get("venue_events"), dict) else {}

    return {
        "exists": True,
        "version": idx.get("v"),
        "subjects": len(subjects),
        "profiles": len(profiles),
        "dj_event_buckets": len(events),
        "dj_venue_buckets": len(dj_venues),
        "collab_buckets": len(collabs),
        "venue_event_buckets": len(venue_events),
        "source_refs": len(source_ref_ids),
        "event_rows_scanned": event_rows,
        "event_source_ref_prefix_counts": dict(event_source_prefixes.most_common()),
        "unrecognized_source_ref_count": len(set(unrecognized_refs)),
        "unrecognized_source_ref_samples": sorted(set(unrecognized_refs))[:20],
        "missing_source_ref_lookup_count": missing_source_refs,
        "collab_profile_coverage_rate": round(len(collabs) / max(len(profiles), 1), 4),
        "venue_event_subject_coverage_rate": round(len(venue_events) / max(len(subjects), 1), 4),
    }


def audit_source_consumers(repo_root: Path) -> dict[str, Any]:
    files = {
        "sourceAction": repo_root / "apps" / "weekly_activity_miniprogram" / "utils" / "sourceAction.js",
        "sourceArticles": repo_root / "apps" / "weekly_activity_miniprogram" / "utils" / "sourceArticles.js",
        "sourcePage": repo_root / "apps" / "weekly_activity_miniprogram" / "pages" / "source" / "source.js",
        "artistPage": repo_root / "apps" / "weekly_activity_miniprogram" / "pages" / "artist" / "artist.js",
        "artistWxml": repo_root / "apps" / "weekly_activity_miniprogram" / "pages" / "artist" / "artist.wxml",
        "venuePage": repo_root / "apps" / "weekly_activity_miniprogram" / "pages" / "venue" / "venue.js",
        "venueWxml": repo_root / "apps" / "weekly_activity_miniprogram" / "pages" / "venue" / "venue.wxml",
    }
    contents = {name: path.read_text(encoding="utf-8", errors="ignore") for name, path in files.items()}
    return {
        "activity_src_supported_in_sourceAction": "activity_src" in contents["sourceAction"],
        "activity_src_supported_in_sourceArticles": "activity_src" in contents["sourceArticles"],
        "activity_src_supported_in_sourcePage": "activity_src" in contents["sourcePage"],
        "source_ref_supported_in_sourceAction": "source_ref" in contents["sourceAction"],
        "source_ref_supported_in_sourceArticles": "source_ref" in contents["sourceArticles"],
        "source_ref_supported_in_sourcePage": "source_ref" in contents["sourcePage"],
        "artist_history_source_tap": "openAtlasEventSource" in contents["artistPage"] and "data-source-hash" in contents["artistWxml"],
        "venue_atlas_event_source_tap": "isAtlasEvent" in contents["venuePage"] and "data-is-atlas" in contents["venueWxml"],
    }


def build_findings(current: dict[str, Any], atlas: dict[str, Any], consumers: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    checks = [
        ("manifest_matches_current", current.get("manifest_matches_current"), "current_release manifest item_count must match current.json"),
        ("no_duplicate_current_ids", current.get("duplicate_id_count") == 0, "weekly current item ids must be unique"),
        ("by_city_consistent", current.get("by_city_mismatch_count") == 0, "by-city indexes must match item city_key/city_keys"),
        ("activity_src_source_action_supported", consumers.get("activity_src_supported_in_sourceAction"), "activity_src refs must open as Atlas evidence"),
        ("activity_src_source_articles_supported", consumers.get("activity_src_supported_in_sourceArticles"), "source article grouping must keep activity_src refs"),
        ("source_ref_source_action_supported", consumers.get("source_ref_supported_in_sourceAction"), "source_ref refs must open as Atlas evidence"),
        ("source_ref_source_articles_supported", consumers.get("source_ref_supported_in_sourceArticles"), "source article grouping must keep source_ref refs"),
        ("artist_history_source_tap", consumers.get("artist_history_source_tap"), "artist Atlas history rows must open evidence"),
        ("venue_atlas_event_source_tap", consumers.get("venue_atlas_event_source_tap"), "venue Atlas history rows must open evidence"),
        ("atlas_source_refs_recognized", atlas.get("unrecognized_source_ref_count", 0) == 0, "Atlas miniapp source ref prefixes must be recognized"),
    ]
    for key, passed, message in checks:
        if not passed:
            findings.append({"check": key, "severity": "high", "message": message})
    if atlas.get("collab_profile_coverage_rate", 0) < 0.05:
        findings.append({
            "check": "atlas_collab_coverage_low",
            "severity": "medium",
            "message": "Only a small fraction of DJ profiles have collaborator buckets in atlas_index; this may be intentional package slimming but affects obscure DJ relationship pages.",
            "value": atlas.get("collab_profile_coverage_rate"),
        })
    return findings


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    findings = report["findings"]
    lines = [
        "# Weekly Full Chain Contract Audit",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- findings: `{len(findings)}`",
        "",
        "## Findings",
    ]
    if findings:
        for finding in findings:
            lines.append(f"- `{finding['severity']}` `{finding['check']}`: {finding['message']}")
    else:
        lines.append("- None.")
    current = report["current_release"]
    atlas = report["atlas_index"]
    consumers = report["miniapp_consumers"]
    lines += [
        "",
        "## Current Release",
        f"- items: `{current['current_item_count']}` / manifest `{current['manifest_item_count']}`",
        f"- duplicate ids: `{current['duplicate_id_count']}`",
        f"- by-id files: `{current['by_id_file_count']}`; missing ids `{len(current['by_id_missing_ids'])}`; extra ids `{len(current['by_id_extra_ids'])}`",
        f"- by-city mismatches: `{current['by_city_mismatch_count']}`",
        f"- source ref prefixes: `{current['source_ref_prefix_counts']}`",
        "",
        "## Atlas Index",
        f"- subjects/profiles: `{atlas.get('subjects')}` / `{atlas.get('profiles')}`",
        f"- DJ event buckets / venue event buckets: `{atlas.get('dj_event_buckets')}` / `{atlas.get('venue_event_buckets')}`",
        f"- collab buckets: `{atlas.get('collab_buckets')}`; profile coverage `{atlas.get('collab_profile_coverage_rate')}`",
        f"- source refs: `{atlas.get('source_refs')}`; prefix counts `{atlas.get('event_source_ref_prefix_counts')}`",
        f"- missing source ref lookups: `{atlas.get('missing_source_ref_lookup_count')}`",
        "",
        "## Miniapp Consumers",
    ]
    for key, value in consumers.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    parser.add_argument("--atlas-index", type=Path, default=DEFAULT_ATLAS_INDEX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    current = audit_current_release(args.release_dir)
    atlas = audit_atlas_index(args.atlas_index)
    consumers = audit_source_consumers(REPO_ROOT)
    findings = build_findings(current, atlas, consumers)
    report = {
        "schema_version": "weekly_full_chain_contract_audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": "weekly_full_chain_contract_audit_passed" if not findings else "weekly_full_chain_contract_audit_findings",
        "report_only": True,
        "mutations_executed": False,
        "current_release": current,
        "atlas_index": atlas,
        "miniapp_consumers": consumers,
        "findings": findings,
    }
    write_json(args.out_dir / "weekly_full_chain_contract_audit.json", report)
    write_markdown(args.out_dir / "weekly_full_chain_contract_audit.md", report)
    print(json.dumps({
        "decision": report["decision"],
        "findings": len(findings),
        "json": str(args.out_dir / "weekly_full_chain_contract_audit.json"),
        "markdown": str(args.out_dir / "weekly_full_chain_contract_audit.md"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
