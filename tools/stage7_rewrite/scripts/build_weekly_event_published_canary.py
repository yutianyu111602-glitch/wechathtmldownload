#!/usr/bin/env python3
"""Report-only canary adapter from Stage7 consumer events to weekly_event_published.v1.

This script intentionally does not publish. It only attempts a bounded,
source-backed mapping and reports which fields block publication.

Important policy:
* `event_date_start` is filled only from an existing ISO `time_iso`.
* `time_text` such as "7月1日 周六" is not promoted to a date because the year
  is not source-backed in the current consumer release pack.
* venue city/address is filled only by exact registry alias match.
* no raw source URL is invented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_weekly_schema_compat import read_json, validate_value  # noqa: E402


DEFAULT_RELEASE_PACK = Path("reports/consumer_release_pack_full_unknown_time_20260514")
DEFAULT_SCHEMA = Path("schemas/weekly_event_published.v1.schema.json")
DEFAULT_VENUE_REGISTRY = Path("registries/weekly_venues_seed.json")
DEFAULT_OUT_DIR = Path("reports/weekly_event_published_canary_20260515")
ISO_DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"(\d{1,2}:\d{2})(?:\s*[-~至]\s*(\d{1,2}:\d{2}|Late|late))?")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for weekly event canary: {path}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(path)


def normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s·・|@:,，.。()（）\[\]【】\-_/\\]+", "", text)


def list_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    raw = str(value or "").strip()
    return [raw] if raw else []


def iter_jsonl(path: Path, limit: int):
    with path.open("r", encoding="utf-8") as handle:
        count = 0
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                yield row
                count += 1
            if limit > 0 and count >= limit:
                break


def source_account_from_uid(uid: str) -> str:
    if "/" in uid:
        return uid.split("/", 1)[0].strip()
    return ""


def article_id_from_uid(uid: str) -> str:
    if "/" in uid:
        return uid.rsplit("/", 1)[-1].strip()
    return uid.strip()


def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:length]


def load_venue_index(path: Path) -> dict[str, dict[str, Any]]:
    registry = read_json(path)
    index: dict[str, dict[str, Any]] = {}
    for row in registry.get("venues") or []:
        if not isinstance(row, dict):
            continue
        names = [row.get("venue_id"), row.get("canonical_name"), *list_strings(row.get("aliases"))]
        for name in names:
            key = normalize_key(name)
            if key:
                index[key] = row
    return index


def match_venue(place: str, venue_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = normalize_key(place)
    if not key:
        return None
    return venue_index.get(key)


def extract_time_parts(time_text: str) -> tuple[str, str, str]:
    match = TIME_RE.search(time_text or "")
    if not match:
        return "", "", ""
    start = match.group(1) or ""
    end = match.group(2) or ""
    running = f"{start} - {end}" if end else start
    return start, end, running


def dedupe_key(candidate: dict[str, Any]) -> str:
    parts = [
        candidate.get("event_date_start"),
        candidate.get("city_key"),
        candidate.get("venue_id") or candidate.get("venue_name"),
        candidate.get("title_display"),
    ]
    return "|".join(normalize_key(part) for part in parts if normalize_key(part))


def build_candidate(row: dict[str, Any], venue_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    source_uid = str(row.get("source_article_uid") or "").strip()
    source_account = source_account_from_uid(source_uid)
    article_id = article_id_from_uid(source_uid)
    source_hash = stable_hash(source_uid or json.dumps(row, ensure_ascii=False))
    event_name = str(row.get("name") or "").strip()
    place = str(row.get("place") or "").strip()
    time_iso = str(row.get("time_iso") or "").strip()
    time_text = str(row.get("time_text") or "").strip()
    venue = match_venue(place, venue_index)
    start_time, end_time, running_hours = extract_time_parts(time_text)

    if not event_name:
        blockers.append("missing_event_name")
    if not source_uid:
        blockers.append("missing_source_article_uid")
    if not source_account:
        blockers.append("missing_source_account_name")
    if not ISO_DATE_RE.match(time_iso):
        blockers.append("missing_source_backed_event_date_start")
        if time_text:
            warnings.append("time_text_not_promoted_to_date_without_year")
    if venue is None:
        blockers.append("venue_not_matched_in_registry")

    city_key = str((venue or {}).get("city_key") or "").strip()
    city_name = str((venue or {}).get("city_name") or "").strip()
    venue_id = str((venue or {}).get("venue_id") or "").strip()
    venue_name = str((venue or {}).get("canonical_name") or place).strip()
    address_full = str((venue or {}).get("address_full") or "").strip()
    if not city_key:
        blockers.append("missing_city_key")
    if not city_name:
        blockers.append("missing_city_name")
    if not venue_name:
        blockers.append("missing_venue_name")
    if not address_full:
        blockers.append("missing_address_full")

    candidate = {
        "schema_version": "weekly_event_published.v1",
        "event_id": f"stage7:{stable_hash(source_uid + '|' + str(row.get('evid') or '') + '|' + event_name)}",
        "title_display": event_name,
        "title_original": event_name,
        "event_date_start": time_iso if ISO_DATE_RE.match(time_iso) else "",
        "event_date_end": time_iso if ISO_DATE_RE.match(time_iso) else "",
        "time_start": start_time,
        "time_end": end_time,
        "running_hours_text": running_hours,
        "city_key": city_key,
        "city_name": city_name,
        "venue_id": venue_id,
        "venue_name": venue_name,
        "address_full": address_full,
        "geo_lng": (venue or {}).get("geo_lng"),
        "geo_lat": (venue or {}).get("geo_lat"),
        "cover_image_url": "",
        "poster_file_id": "",
        "poster_source": "",
        "lineup_artists": list_strings(row.get("participants")),
        "music_styles": [],
        "price_text": "",
        "ticketing_text": "",
        "description_original_lines": [str(row.get("vector_text") or "").strip()] if row.get("vector_text") else [],
        "dj_bio_lines": [],
        "artist_profiles": [],
        "source_account_name": source_account,
        "source_published_at": "",
        "source_article": {
            "url_hash": article_id or source_hash,
            "account_name": source_account,
            "published_at": "",
        },
        "source_action": {
            "type": "wechat_article",
            "label": "source unavailable in consumer release pack",
            "available": False,
            "url_hash": article_id or source_hash,
        },
        "quality_status": "READY",
        "publish_status": "published",
        "dedupe_key": "",
    }
    candidate["dedupe_key"] = dedupe_key(candidate)
    if not candidate["dedupe_key"]:
        blockers.append("missing_dedupe_key")
    if blockers:
        candidate["quality_status"] = "BLOCKED"
        candidate["publish_status"] = "blocked"
    return {
        "source_event_id": row.get("evid"),
        "source_article_uid": source_uid,
        "source_place": place,
        "source_time_iso": time_iso,
        "source_time_text": time_text,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "candidate": candidate,
    }


def evaluate_candidates(rows: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    ready_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}
    warning_counts: dict[str, int] = {}
    schema_issue_counts: dict[str, int] = {}
    for row in rows:
        for blocker in row["blockers"]:
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        for warning in row["warnings"]:
            warning_counts[warning] = warning_counts.get(warning, 0) + 1
        issues = validate_value(row["candidate"], schema, "candidate")
        row["schema_issues"] = issues
        if row["blockers"] or issues:
            blocked_rows.append(row)
            for issue in issues:
                key = re.sub(r"\[\d+\]", "[]", f"{issue.get('path')}: {issue.get('message')}")
                schema_issue_counts[key] = schema_issue_counts.get(key, 0) + 1
        else:
            ready_rows.append(row)
    return {
        "ready_rows": ready_rows,
        "blocked_rows": blocked_rows,
        "blocker_counts": dict(sorted(blocker_counts.items(), key=lambda item: (-item[1], item[0]))),
        "warning_counts": dict(sorted(warning_counts.items(), key=lambda item: (-item[1], item[0]))),
        "schema_issue_counts": dict(sorted(schema_issue_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reject_d_path(args.release_pack, "release_pack")
    reject_d_path(args.schema, "schema")
    reject_d_path(args.venue_registry, "venue_registry")
    schema = read_json(args.schema)
    venue_index = load_venue_index(args.venue_registry)
    source_rows = list(iter_jsonl(args.release_pack / "events.jsonl", args.sample_count))
    candidate_rows = [build_candidate(row, venue_index) for row in source_rows]
    evaluated = evaluate_candidates(candidate_rows, schema)
    ready_count = len(evaluated["ready_rows"])
    blocked_count = len(evaluated["blocked_rows"])
    decision = (
        "weekly_event_published_canary_ready"
        if ready_count > 0 and blocked_count == 0
        else "weekly_event_published_canary_blocked_by_source_gaps"
    )
    report = {
        "schema_version": "stage7_weekly_event_published_canary.v1",
        "generated_at": now_iso(),
        "ok": ready_count > 0 and blocked_count == 0,
        "decision": decision,
        "release_pack": str(args.release_pack),
        "schema": str(args.schema),
        "venue_registry": str(args.venue_registry),
        "sample_count": len(source_rows),
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "blocker_counts": evaluated["blocker_counts"],
        "warning_counts": evaluated["warning_counts"],
        "schema_issue_counts": evaluated["schema_issue_counts"],
        "ready_examples": evaluated["ready_rows"][: args.example_limit],
        "blocked_examples": evaluated["blocked_rows"][: args.example_limit],
        "field_policy": {
            "event_date_start": "time_iso_only; no year inference from time_text",
            "venue_city_address": "exact registry alias match only",
            "source_action_url": "not invented; available=false when raw/canonical URL is absent",
        },
        "writes": "reports_only",
        "safety": [
            "no production publish",
            "no production SQLite write",
            "no Qdrant or Neo4j write",
            "no paid API call",
            "no D: scan",
        ],
    }
    return report, candidate_rows


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Weekly Event Published Canary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- sample_count: `{report['sample_count']}`",
        f"- ready_count: `{report['ready_count']}`",
        f"- blocked_count: `{report['blocked_count']}`",
        "",
        "## Blockers",
        "",
    ]
    if report["blocker_counts"]:
        for key, count in report["blocker_counts"].items():
            lines.append(f"- `{key}`: `{count}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if report["warning_counts"]:
        for key, count in report["warning_counts"].items():
            lines.append(f"- `{key}`: `{count}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Schema Issues", ""])
    if report["schema_issue_counts"]:
        for key, count in report["schema_issue_counts"].items():
            lines.append(f"- `{key}`: `{count}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Field Policy",
            "",
            f"- event_date_start: `{report['field_policy']['event_date_start']}`",
            f"- venue_city_address: `{report['field_policy']['venue_city_address']}`",
            f"- source_action_url: `{report['field_policy']['source_action_url']}`",
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- No production publish.",
            "- No production SQLite write.",
            "- No Qdrant or Neo4j write.",
            "- No paid API call.",
            "- No D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report, candidates = build_report(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "weekly_event_published_canary.json", report)
    write_jsonl(args.out_dir / "weekly_event_published_candidates.jsonl", candidates)
    write_markdown(args.out_dir / "weekly_event_published_canary.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "ready_count": report["ready_count"],
                "blocked_count": report["blocked_count"],
                "report": str(args.out_dir / "weekly_event_published_canary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-pack", type=Path, default=DEFAULT_RELEASE_PACK)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--venue-registry", type=Path, default=DEFAULT_VENUE_REGISTRY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-count", type=int, default=200)
    parser.add_argument("--example-limit", type=int, default=5)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
