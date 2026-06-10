#!/usr/bin/env python3
"""Audit weekly venue-registry geo coverage against the current release packet.

This is a report-only guard. It reads the fixed venue registry and the current
weekly API packet, then reports whether live release rows still depend on
non-registry geo fallbacks or contain unexpected blank coordinates.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPT_ROOT.parents[1]
DEFAULT_REGISTRY = SCRIPT_ROOT / "registries" / "weekly_venues_seed.json"
DEFAULT_CURRENT_RELEASE = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_REPORT_DIR = SCRIPT_ROOT / "reports" / "weekly_venue_registry_geo_coverage_20260531"
DEFAULT_MISMATCH_METERS = 2500.0


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def has_geo(obj: dict[str, Any]) -> bool:
    lng = as_float(obj.get("geo_lng"))
    lat = as_float(obj.get("geo_lat"))
    return lng is not None and lat is not None and -180 <= lng <= 180 and -90 <= lat <= 90


def geo_pair(obj: dict[str, Any]) -> tuple[float, float] | None:
    if not has_geo(obj):
        return None
    return float(obj["geo_lng"]), float(obj["geo_lat"])


def haversine_meters(left: tuple[float, float], right: tuple[float, float]) -> float:
    left_lng, left_lat = left
    right_lng, right_lat = right
    radius_m = 6_371_000.0
    left_phi = math.radians(left_lat)
    right_phi = math.radians(right_lat)
    delta_phi = math.radians(right_lat - left_lat)
    delta_lambda = math.radians(right_lng - left_lng)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(left_phi) * math.cos(right_phi) * math.sin(delta_lambda / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(a))


def load_release_items(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("items") or payload.get("activities") or []
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def short_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id", ""),
        "venue_id": item.get("venue_id", ""),
        "venue_name": item.get("venue_name", ""),
        "city_key": item.get("city_key", ""),
        "city": item.get("city", ""),
        "address": item.get("address", ""),
        "geo_lng": item.get("geo_lng"),
        "geo_lat": item.get("geo_lat"),
        "geo_source": item.get("geo_source", ""),
        "title": item.get("title", ""),
    }


def short_venue(venue: dict[str, Any]) -> dict[str, Any]:
    return {
        "venue_id": venue.get("venue_id", ""),
        "canonical_name": venue.get("canonical_name", ""),
        "city_key": venue.get("city_key", ""),
        "status": venue.get("status", ""),
        "address_full": venue.get("address_full", ""),
        "geo_lng": venue.get("geo_lng"),
        "geo_lat": venue.get("geo_lat"),
        "geo_source": venue.get("geo_source", ""),
        "last_verified_at": venue.get("last_verified_at", ""),
    }


def summarize(registry_path: Path, current_release_path: Path, *, mismatch_meters: float) -> dict[str, Any]:
    registry_payload = read_json(registry_path)
    venues = [row for row in registry_payload.get("venues", []) if isinstance(row, dict)]
    registry_by_id = {str(row.get("venue_id", "")): row for row in venues if row.get("venue_id")}
    active_venues = [row for row in venues if row.get("status") == "active"]
    active_missing_geo = [row for row in active_venues if not has_geo(row)]
    pending_geocode = [row for row in venues if row.get("status") == "pending_geocode"]

    items = load_release_items(current_release_path)
    current_missing_geo: list[dict[str, Any]] = []
    current_missing_geo_known_blockers: list[dict[str, Any]] = []
    current_missing_geo_unexpected: list[dict[str, Any]] = []
    registry_backfill_candidates: list[dict[str, Any]] = []
    registry_geo_mismatches: list[dict[str, Any]] = []
    current_with_registry_geo = 0

    for item in items:
        venue = registry_by_id.get(str(item.get("venue_id", "")))
        if venue and has_geo(venue):
            current_with_registry_geo += 1
        if not has_geo(item):
            short = short_item(item)
            current_missing_geo.append(short)
            if venue and venue.get("status") == "pending_geocode":
                current_missing_geo_known_blockers.append(short)
            else:
                current_missing_geo_unexpected.append(short)
            continue
        if venue and not has_geo(venue):
            registry_backfill_candidates.append(
                {
                    "item": short_item(item),
                    "registry": short_venue(venue),
                }
            )
            continue
        if venue and has_geo(venue):
            item_geo = geo_pair(item)
            venue_geo = geo_pair(venue)
            if item_geo and venue_geo:
                distance = haversine_meters(item_geo, venue_geo)
                if distance > mismatch_meters:
                    registry_geo_mismatches.append(
                        {
                            "distance_m": round(distance, 2),
                            "item": short_item(item),
                            "registry": short_venue(venue),
                        }
                    )

    failed_checks = []
    if active_missing_geo:
        failed_checks.append("active_registry_venues_missing_geo")
    if current_missing_geo_unexpected:
        failed_checks.append("current_release_items_missing_geo_without_pending_registry_blocker")
    if registry_backfill_candidates:
        failed_checks.append("current_release_has_geo_but_registry_missing_geo")
    if registry_geo_mismatches:
        failed_checks.append("current_release_registry_geo_mismatch")

    if failed_checks:
        decision = "weekly_venue_registry_geo_coverage_attention_required"
    elif current_missing_geo_known_blockers:
        decision = "weekly_venue_registry_geo_coverage_passed_with_known_blockers"
    else:
        decision = "weekly_venue_registry_geo_coverage_passed"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "decision": decision,
        "failed_checks": failed_checks,
        "map_api_calls_performed": False,
        "inputs": {
            "registry_path": str(registry_path),
            "current_release_path": str(current_release_path),
            "mismatch_meters": mismatch_meters,
        },
        "counts": {
            "registry_total": len(venues),
            "registry_active": len(active_venues),
            "registry_active_with_geo": len(active_venues) - len(active_missing_geo),
            "registry_active_missing_geo": len(active_missing_geo),
            "registry_pending_geocode": len(pending_geocode),
            "current_release_items": len(items),
            "current_release_items_with_geo": len(items) - len(current_missing_geo),
            "current_release_items_missing_geo": len(current_missing_geo),
            "current_release_items_with_registry_geo": current_with_registry_geo,
            "current_missing_geo_known_blockers": len(current_missing_geo_known_blockers),
            "current_missing_geo_unexpected": len(current_missing_geo_unexpected),
            "registry_backfill_candidates": len(registry_backfill_candidates),
            "registry_geo_mismatches": len(registry_geo_mismatches),
        },
        "active_registry_missing_geo": [short_venue(row) for row in active_missing_geo],
        "pending_geocode_venues": [short_venue(row) for row in pending_geocode],
        "current_missing_geo": current_missing_geo,
        "current_missing_geo_known_blockers": current_missing_geo_known_blockers,
        "current_missing_geo_unexpected": current_missing_geo_unexpected,
        "registry_backfill_candidates": registry_backfill_candidates,
        "registry_geo_mismatches": registry_geo_mismatches,
    }


def write_reports(summary: dict[str, Any], report_dir: Path) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json = report_dir / "weekly_venue_registry_geo_coverage.json"
    report_md = report_dir / "weekly_venue_registry_geo_coverage.md"
    report_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = summary["counts"]
    lines = [
        "# Weekly Venue Registry Geo Coverage Audit",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{', '.join(summary['failed_checks']) if summary['failed_checks'] else '[]'}`",
        f"- Map API calls performed: `{str(summary['map_api_calls_performed']).lower()}`",
        f"- Registry active geo coverage: `{counts['registry_active_with_geo']}/{counts['registry_active']}`",
        f"- Current release geo coverage: `{counts['current_release_items_with_geo']}/{counts['current_release_items']}`",
        f"- Current release items using registry geo: `{counts['current_release_items_with_registry_geo']}/{counts['current_release_items']}`",
        f"- Pending geocode venues: `{counts['registry_pending_geocode']}`",
        "",
        "## Known Blockers",
    ]
    if summary["current_missing_geo_known_blockers"]:
        for item in summary["current_missing_geo_known_blockers"]:
            lines.append(
                f"- `{item['id']}` `{item['venue_id']}` `{item['venue_name']}`: missing address/geo; registry status is pending_geocode"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Attention Rows"])
    attention = (
        summary["active_registry_missing_geo"]
        or summary["current_missing_geo_unexpected"]
        or summary["registry_backfill_candidates"]
        or summary["registry_geo_mismatches"]
    )
    if attention:
        lines.append("See JSON report for structured rows.")
    else:
        lines.append("- None")
    lines.append("")
    report_md.write_text("\n".join(lines), encoding="utf-8")
    return report_json, report_md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit weekly venue registry geo coverage")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--current-release", type=Path, default=DEFAULT_CURRENT_RELEASE)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--mismatch-meters", type=float, default=DEFAULT_MISMATCH_METERS)
    args = parser.parse_args(argv)

    summary = summarize(args.registry, args.current_release, mismatch_meters=args.mismatch_meters)
    report_json, report_md = write_reports(summary, args.report_dir)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "counts": summary["counts"],
                "report_json": str(report_json),
                "report_markdown": str(report_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if summary["failed_checks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
