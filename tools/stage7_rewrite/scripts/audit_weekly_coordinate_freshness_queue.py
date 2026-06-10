#!/usr/bin/env python3
"""Build a report-only queue for coordinate freshness and registry solidification.

This guard does not call Tencent, Amap, LLMs, or web search. It separates:
- current-release rows that still have no usable coordinate;
- current-release venue IDs that have trusted coordinates but are not yet frozen
  in the local venue registry;
- active registry rows whose verification date is older than the freshness
  policy.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CURRENT_JSON = ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_VENUE_REGISTRY = ROOT / "tools" / "stage7_rewrite" / "registries" / "weekly_venues_seed.json"
DEFAULT_REPORT_ROOT = ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_FRESH_AFTER = "2026-05-22"

CHINA_LNG_MIN = 73.0
CHINA_LNG_MAX = 135.5
CHINA_LAT_MIN = 18.0
CHINA_LAT_MAX = 54.5

TRUSTED_GEO_SOURCES = {
    "amap_geocoder",
    "amap_geocoder_crosscheck",
    "amap_place_search",
    "amap_place_search_crosscheck",
    "deepseek_web_resource_crosscheck",
    "frontend_verified_map_location_book",
    "manual_verified_map_location_book",
    "qqmap_geocoder",
    "qqmap_place_search",
    "tencent_geocoder",
    "tencent_place_search",
    "tencent_place_search_crosscheck",
    "venue_registry_verified",
}


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows_from_payload(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in keys:
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    return []


def first(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = str(item or "").strip()
                if text:
                    return text
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def coordinate(row: dict[str, Any]) -> tuple[float | None, float | None]:
    lng = finite_float(first(row.get("geo_lng"), row.get("lng"), row.get("longitude"), row.get("gcj02_lng"), row.get("venue_lng")))
    lat = finite_float(first(row.get("geo_lat"), row.get("lat"), row.get("latitude"), row.get("gcj02_lat"), row.get("venue_lat")))
    return lng, lat


def has_valid_china_geo(row: dict[str, Any]) -> bool:
    lng, lat = coordinate(row)
    return (
        lng is not None
        and lat is not None
        and lng != 0
        and lat != 0
        and CHINA_LNG_MIN <= lng <= CHINA_LNG_MAX
        and CHINA_LAT_MIN <= lat <= CHINA_LAT_MAX
    )


def normalized_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def has_trusted_geo_source(row: dict[str, Any]) -> bool:
    return any(
        normalized_token(value) in TRUSTED_GEO_SOURCES
        for value in (
            row.get("geo_source"),
            row.get("geo_provider"),
            row.get("coordinate_source"),
            row.get("map_source"),
        )
    )


def address(row: dict[str, Any]) -> str:
    return first(row.get("address_full"), row.get("address"), row.get("venue_address"))


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text[:10], text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def short_current_item(item: dict[str, Any]) -> dict[str, Any]:
    lng, lat = coordinate(item)
    return {
        "id": first(item.get("event_id"), item.get("id")),
        "venue_id": first(item.get("venue_id")),
        "venue_name": first(item.get("venue_name"), item.get("venue"), item.get("promoter"), item.get("account")),
        "city": first(item.get("city"), item.get("city_key")),
        "address": address(item),
        "geo_lng": lng,
        "geo_lat": lat,
        "geo_source": first(item.get("geo_source"), item.get("geo_provider")),
        "geo_verified_at": first(item.get("geo_verified_at"), item.get("last_verified_at")),
        "title": first(item.get("title")),
    }


def short_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    lng, lat = coordinate(row)
    return {
        "venue_id": first(row.get("venue_id")),
        "canonical_name": first(row.get("canonical_name"), row.get("name")),
        "city": first(row.get("city_name"), row.get("city_key")),
        "address_full": address(row),
        "geo_lng": lng,
        "geo_lat": lat,
        "geo_source": first(row.get("geo_source"), row.get("geo_provider")),
        "last_verified_at": first(row.get("last_verified_at"), row.get("geo_verified_at")),
        "status": first(row.get("status")),
    }


def group_current_items(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        venue_id = first(item.get("venue_id"))
        if venue_id:
            groups[venue_id].append(item)
    return groups


def summarize(
    current_payload: Any,
    registry_payload: Any,
    *,
    fresh_after: str = DEFAULT_FRESH_AFTER,
) -> dict[str, Any]:
    items = rows_from_payload(current_payload, "items", "activities")
    venues = rows_from_payload(registry_payload, "venues", "items", "data")
    registry_by_id = {first(row.get("venue_id")): row for row in venues if first(row.get("venue_id"))}
    fresh_after_date = parse_date(fresh_after)
    if fresh_after_date is None:
        raise ValueError(f"invalid fresh_after date: {fresh_after}")

    current_missing_geo: list[dict[str, Any]] = []
    current_unregistered_groups: list[dict[str, Any]] = []
    current_unregistered_untrusted: list[dict[str, Any]] = []

    for item in items:
        if not has_valid_china_geo(item):
            current_missing_geo.append(short_current_item(item))

    for venue_id, group in sorted(group_current_items(items).items()):
        if venue_id in registry_by_id:
            continue
        short_rows = [short_current_item(row) for row in group]
        trusted_rows = [row for row in group if has_valid_china_geo(row) and address(row) and has_trusted_geo_source(row)]
        unique_geo = sorted({
            (round(coordinate(row)[0] or 0, 6), round(coordinate(row)[1] or 0, 6))
            for row in trusted_rows
        })
        unique_addresses = sorted({address(row) for row in trusted_rows if address(row)})
        candidate = {
            "venue_id": venue_id,
            "venue_name": first(group[0].get("venue_name"), group[0].get("venue")),
            "city": first(group[0].get("city"), group[0].get("city_key")),
            "item_count": len(group),
            "trusted_item_count": len(trusted_rows),
            "unique_geo_count": len(unique_geo),
            "unique_address_count": len(unique_addresses),
            "unique_geo": [{"geo_lng": lng, "geo_lat": lat} for lng, lat in unique_geo],
            "addresses": unique_addresses,
            "geo_sources": sorted({first(row.get("geo_source"), row.get("geo_provider")) for row in trusted_rows if first(row.get("geo_source"), row.get("geo_provider"))}),
            "items": short_rows,
        }
        if len(trusted_rows) == len(group) and len(unique_geo) == 1 and len(unique_addresses) == 1:
            current_unregistered_groups.append(candidate)
        else:
            current_unregistered_untrusted.append(candidate)

    stale_registry_rows: list[dict[str, Any]] = []
    active_rows = [row for row in venues if first(row.get("status")) == "active"]
    for row in active_rows:
        verified_at = parse_date(first(row.get("last_verified_at"), row.get("geo_verified_at")))
        if verified_at is None or verified_at < fresh_after_date:
            stale_registry_rows.append(short_registry_row(row))

    safe_to_claim_latest = (
        not current_missing_geo
        and not current_unregistered_groups
        and not current_unregistered_untrusted
        and not stale_registry_rows
    )
    decision = (
        "weekly_coordinate_freshness_current_and_solidified"
        if safe_to_claim_latest
        else "weekly_coordinate_freshness_not_fully_latest"
    )

    return {
        "schema_version": "weekly_coordinate_freshness_queue.v1",
        "generated_at": now_cst(),
        "decision": decision,
        "safe_to_claim_all_latest": safe_to_claim_latest,
        "map_api_calls_performed": False,
        "freshness_policy": {
            "fresh_after": fresh_after,
            "meaning": "active registry rows verified before this date require external recheck before claiming all addresses are latest",
        },
        "summary": {
            "current_items": len(items),
            "current_items_missing_geo": len(current_missing_geo),
            "registry_total": len(venues),
            "registry_active": len(active_rows),
            "current_unregistered_venue_groups_ready_for_registry_review": len(current_unregistered_groups),
            "current_unregistered_venue_groups_untrusted": len(current_unregistered_untrusted),
            "stale_registry_active_rows": len(stale_registry_rows),
        },
        "current_missing_geo": current_missing_geo,
        "current_unregistered_ready_for_registry_review": current_unregistered_groups,
        "current_unregistered_untrusted": current_unregistered_untrusted,
        "stale_registry_active_rows": stale_registry_rows,
        "exit_code_policy": {
            "not_latest_returns_nonzero": True,
            "allow_not_latest_exit_zero": False,
        },
    }


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Coordinate Freshness And Solidification Queue",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- decision: `{report['decision']}`",
        f"- safe_to_claim_all_latest: `{str(report['safe_to_claim_all_latest']).lower()}`",
        f"- map_api_calls_performed: `{str(report['map_api_calls_performed']).lower()}`",
        f"- fresh_after: `{report['freshness_policy']['fresh_after']}`",
        "",
        "## Summary",
        "",
        f"- current_items: `{summary['current_items']}`",
        f"- current_items_missing_geo: `{summary['current_items_missing_geo']}`",
        f"- registry_active: `{summary['registry_active']}`",
        f"- unregistered ready-for-registry groups: `{summary['current_unregistered_venue_groups_ready_for_registry_review']}`",
        f"- unregistered untrusted groups: `{summary['current_unregistered_venue_groups_untrusted']}`",
        f"- stale active registry rows: `{summary['stale_registry_active_rows']}`",
        "",
        "## Missing Geo",
        "",
    ]
    if report["current_missing_geo"]:
        for row in report["current_missing_geo"][:50]:
            lines.append(f"- `{row['id']}` `{row['venue_id']}` `{row['venue_name']}` `{row['city']}`")
    else:
        lines.append("- none")

    lines.extend(["", "## Registry Review Candidates", ""])
    if report["current_unregistered_ready_for_registry_review"]:
        for row in report["current_unregistered_ready_for_registry_review"][:50]:
            address_text = row["addresses"][0] if row["addresses"] else ""
            geo = row["unique_geo"][0] if row["unique_geo"] else {}
            lines.append(
                f"- `{row['venue_id']}` `{row['venue_name']}` `{row['city']}` "
                f"items={row['item_count']} geo=({geo.get('geo_lng')},{geo.get('geo_lat')}) address=`{address_text}`"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Registry Rows Needing External Recheck Before Latest Claim", ""])
    if report["stale_registry_active_rows"]:
        for row in report["stale_registry_active_rows"][:100]:
            lines.append(f"- `{row['venue_id']}` `{row['canonical_name']}` `{row['city']}` verified=`{row['last_verified_at']}`")
    else:
        lines.append("- none")

    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-json", type=Path, default=DEFAULT_CURRENT_JSON)
    parser.add_argument("--venue-registry", type=Path, default=DEFAULT_VENUE_REGISTRY)
    parser.add_argument("--fresh-after", default=DEFAULT_FRESH_AFTER)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--allow-not-latest-exit-zero",
        action="store_true",
        help="Write a not-latest report but return exit code 0 for report collection jobs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = summarize(
        read_json(args.current_json),
        read_json(args.venue_registry),
        fresh_after=args.fresh_after,
    )
    report["exit_code_policy"]["allow_not_latest_exit_zero"] = args.allow_not_latest_exit_zero
    report["inputs"] = {
        "current_json": str(args.current_json),
        "venue_registry": str(args.venue_registry),
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir or DEFAULT_REPORT_ROOT / f"weekly_coordinate_freshness_queue_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_coordinate_freshness_queue.json"
    md_path = out_dir / "weekly_coordinate_freshness_queue.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({
        "ok": True,
        "decision": report["decision"],
        "safe_to_claim_all_latest": report["safe_to_claim_all_latest"],
        "summary": report["summary"],
        "out_dir": str(out_dir),
    }, ensure_ascii=False))
    if args.allow_not_latest_exit_zero:
        return 0
    return 0 if report["safe_to_claim_all_latest"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
