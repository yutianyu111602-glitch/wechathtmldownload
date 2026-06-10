#!/usr/bin/env python3
"""Audit weekly mini-program coordinate quality without calling map providers."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CURRENT_JSON = ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_VENUE_REGISTRY = ROOT / "tools" / "stage7_rewrite" / "registries" / "weekly_venues_seed.json"
DEFAULT_REPORT_ROOT = ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_DISTANCE_THRESHOLD_METERS = 2500.0

CHINA_LNG_MIN = 73.0
CHINA_LNG_MAX = 135.5
CHINA_LAT_MIN = 18.0
CHINA_LAT_MAX = 54.5


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def finite_float(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def first(value: Any, default: str = "") -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return default
    text = str(value or "").strip()
    return text or default


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def current_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)]
    raise ValueError("current payload must be a list or contain an items list")


def venue_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("venues", "items", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
    raise ValueError("venue registry must be a list or contain venues/items/data")


def item_id(item: dict[str, Any], index: int) -> str:
    return first(item.get("event_id"), first(item.get("id"), f"item[{index}]"))


def venue_id(item: dict[str, Any]) -> str:
    return first(item.get("venue_id"))


def venue_name(item: dict[str, Any]) -> str:
    return first(item.get("venue_name"), first(item.get("venue"), first(item.get("promoter"), first(item.get("account")))))


def address(item: dict[str, Any]) -> str:
    return first(item.get("address"), first(item.get("address_full")))


def normalize_address(value: str) -> str:
    return re.sub(r"[\s,，.。;；:：|｜()（）\[\]【】\-_/\\]+", "", value.strip().lower())


ADDRESS_NUMBER_RE = re.compile(r"(\d+)\s*号", re.I)
ROAD_TOKEN_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]{1,12}(?:大道|公路|路|街|道|巷|弄))", re.I)
LANDMARK_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]{2,24}(?:大厦|中心|广场|创意园|科技园|产业园|园区|公寓|mall|plaza))", re.I)


def trim_address_prefix(value: str) -> str:
    text = value
    for token in ("街道", "社区", "园区", "镇", "区", "县", "市", "省"):
        if token in text and not text.endswith(token):
            text = text.split(token)[-1]
    return text


def road_number_signature(value: str) -> str:
    number_match = ADDRESS_NUMBER_RE.search(value)
    if not number_match:
        return ""
    prefix = value[: number_match.start()]
    road_tokens = ROAD_TOKEN_RE.findall(prefix)
    if not road_tokens:
        return ""
    road = normalize_address(trim_address_prefix(road_tokens[-1]))
    number = re.sub(r"\D", "", number_match.group(1))
    return "|".join(part for part in ("road_number", road, number) if part)


def compact_landmark(value: str) -> str:
    normalized = normalize_address(trim_address_prefix(value))
    return normalized[-10:] if len(normalized) > 10 else normalized


def address_signature(value: str) -> str:
    text = value.strip()
    normalized = normalize_address(text)
    if not normalized:
        return ""
    road_number = road_number_signature(text)
    landmarks = [compact_landmark(match.group(1)) for match in LANDMARK_RE.finditer(text)]
    if road_number:
        return "|".join(part for part in [road_number, landmarks[0] if landmarks else ""] if part)
    if landmarks:
        return "landmark|" + "|".join(sorted(set(landmarks))[:2])
    return normalized


def coordinate(item: dict[str, Any]) -> tuple[float | None, float | None]:
    lng = finite_float(
        item.get("geo_lng")
        if item.get("geo_lng") is not None
        else item.get("longitude")
        if item.get("longitude") is not None
        else item.get("lng")
        if item.get("lng") is not None
        else item.get("gcj02_lng")
        if item.get("gcj02_lng") is not None
        else item.get("venue_lng")
    )
    lat = finite_float(
        item.get("geo_lat")
        if item.get("geo_lat") is not None
        else item.get("latitude")
        if item.get("latitude") is not None
        else item.get("lat")
        if item.get("lat") is not None
        else item.get("gcj02_lat")
        if item.get("gcj02_lat") is not None
        else item.get("venue_lat")
    )
    return lng, lat


def has_zero_coordinate(lng: float | None, lat: float | None) -> bool:
    return lng == 0 or lat == 0


def in_china_bbox(lng: float, lat: float) -> bool:
    return CHINA_LNG_MIN <= lng <= CHINA_LNG_MAX and CHINA_LAT_MIN <= lat <= CHINA_LAT_MAX


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def registry_by_venue_id(payload: Any) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in venue_rows(payload):
        row_id = venue_id(row)
        if row_id and row_id not in rows:
            rows[row_id] = row
    return rows


def risk(
    risk_type: str,
    severity: str,
    item: dict[str, Any],
    index: int,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "risk_type": risk_type,
        "item_id": item_id(item, index),
        "venue_id": venue_id(item),
        "venue_name": venue_name(item),
        "city": first(item.get("city"), first(item.get("city_key"))),
        "message": message,
        **extra,
    }


def analyze_coordinate_quality(
    current_payload: Any,
    venue_registry_payload: Any,
    *,
    distance_threshold_meters: float = DEFAULT_DISTANCE_THRESHOLD_METERS,
) -> dict[str, Any]:
    items = current_items(current_payload)
    registry = registry_by_venue_id(venue_registry_payload)
    risks: list[dict[str, Any]] = []
    valid_by_venue: dict[str, list[tuple[int, dict[str, Any], float, float]]] = {}
    item_count_with_geo = 0
    item_count_missing_geo = 0

    for index, item in enumerate(items):
        lng, lat = coordinate(item)
        if lng is None or lat is None:
            item_count_missing_geo += 1
            risks.append(risk("missing_coordinate", "high", item, index, "geo_lng/geo_lat is missing or non-numeric"))
            continue
        if has_zero_coordinate(lng, lat):
            item_count_missing_geo += 1
            risks.append(risk("zero_coordinate", "high", item, index, "coordinate contains zero", geo_lng=lng, geo_lat=lat))
            continue

        item_count_with_geo += 1
        if not in_china_bbox(lng, lat):
            risks.append(risk("out_of_china", "high", item, index, "coordinate is outside the China bounding box", geo_lng=lng, geo_lat=lat))

        if not address(item) and (lng is not None or lat is not None or first(item.get("geo_source"), first(item.get("geo_provider")))):
            risks.append(
                risk(
                    "address_empty_with_geo",
                    "medium",
                    item,
                    index,
                    "item has coordinate/geo_source but no address",
                    geo_lng=lng,
                    geo_lat=lat,
                    geo_source=first(item.get("geo_source"), first(item.get("geo_provider"))),
                )
            )

        row = registry.get(venue_id(item))
        if row:
            reg_lng, reg_lat = coordinate(row)
            if reg_lng is None or reg_lat is None or has_zero_coordinate(reg_lng, reg_lat):
                risks.append(risk("registry_missing_coordinate", "medium", item, index, "venue registry row has no usable coordinate"))
            else:
                meters = haversine_meters(lat, lng, reg_lat, reg_lng)
                if meters > distance_threshold_meters:
                    risks.append(
                        risk(
                            "registry_distance_gt_2500m",
                            "high",
                            item,
                            index,
                            "item coordinate is far from registry coordinate",
                            distance_meters=round(meters, 1),
                            threshold_meters=distance_threshold_meters,
                            geo_lng=lng,
                            geo_lat=lat,
                            registry_geo_lng=reg_lng,
                            registry_geo_lat=reg_lat,
                        )
                    )
        elif venue_id(item):
            risks.append(risk("venue_id_missing_from_registry", "medium", item, index, "venue_id is not present in venue registry"))

        if venue_id(item):
            valid_by_venue.setdefault(venue_id(item), []).append((index, item, lng, lat))

    for group_venue_id, rows in valid_by_venue.items():
        if len(rows) < 2:
            continue
        rows_by_coord: dict[tuple[float, float], list[tuple[int, dict[str, Any], float, float]]] = {}
        for row in rows:
            rows_by_coord.setdefault((round(row[2], 6), round(row[3], 6)), []).append(row)
        for (lng, lat), coord_rows in rows_by_coord.items():
            address_groups: dict[str, list[tuple[int, dict[str, Any], float, float]]] = {}
            for row in coord_rows:
                address_key = address_signature(address(row[1]))
                if address_key:
                    address_groups.setdefault(address_key, []).append(row)
            if len(address_groups) < 2:
                continue
            sample_rows = [values[0] for _, values in sorted(address_groups.items())]
            risks.append(
                {
                    "severity": "high",
                    "risk_type": "venue_id_multiple_addresses_same_coordinate",
                    "venue_id": group_venue_id,
                    "message": "same venue_id has multiple source addresses sharing one coordinate",
                    "geo_lng": lng,
                    "geo_lat": lat,
                    "item_ids": [item_id(row[1], row[0]) for row in sample_rows],
                    "addresses": [address(row[1]) for row in sample_rows],
                }
            )
        max_pair: tuple[float, tuple[int, dict[str, Any], float, float], tuple[int, dict[str, Any], float, float]] | None = None
        for left_index in range(len(rows)):
            for right_index in range(left_index + 1, len(rows)):
                left = rows[left_index]
                right = rows[right_index]
                meters = haversine_meters(left[3], left[2], right[3], right[2])
                if max_pair is None or meters > max_pair[0]:
                    max_pair = (meters, left, right)
        if max_pair and max_pair[0] > distance_threshold_meters:
            meters, left, right = max_pair
            risks.append(
                {
                    "severity": "high",
                    "risk_type": "venue_id_coordinate_divergence_gt_2500m",
                    "venue_id": group_venue_id,
                    "message": "same venue_id has divergent coordinates across current release items",
                    "distance_meters": round(meters, 1),
                    "threshold_meters": distance_threshold_meters,
                    "left_item_id": item_id(left[1], left[0]),
                    "right_item_id": item_id(right[1], right[0]),
                    "left_geo_lng": left[2],
                    "left_geo_lat": left[3],
                    "right_geo_lng": right[2],
                    "right_geo_lat": right[3],
                }
            )

    severity_counts: dict[str, int] = {}
    risk_type_counts: dict[str, int] = {}
    for row in risks:
        severity_counts[row["severity"]] = severity_counts.get(row["severity"], 0) + 1
        risk_type_counts[row["risk_type"]] = risk_type_counts.get(row["risk_type"], 0) + 1

    high_risk_count = severity_counts.get("high", 0)
    return {
        "schema_version": "weekly_coordinate_quality_audit.v1",
        "generated_at": now_cst(),
        "decision": "not_ready" if high_risk_count else "ready",
        "policy": {
            "mode": "report_only",
            "provider_calls": "disabled",
            "distance_threshold_meters": distance_threshold_meters,
            "china_bbox": {
                "lng_min": CHINA_LNG_MIN,
                "lng_max": CHINA_LNG_MAX,
                "lat_min": CHINA_LAT_MIN,
                "lat_max": CHINA_LAT_MAX,
            },
        },
        "summary": {
            "item_count": len(items),
            "item_count_with_geo": item_count_with_geo,
            "item_count_missing_geo": item_count_missing_geo,
            "venue_registry_count": len(registry),
            "risk_count": len(risks),
            "high_risk_count": high_risk_count,
            "medium_risk_count": severity_counts.get("medium", 0),
            "low_risk_count": severity_counts.get("low", 0),
            "risk_type_counts": dict(sorted(risk_type_counts.items())),
        },
        "risks": sorted(risks, key=lambda row: (row["severity"] != "high", row["risk_type"], row.get("venue_id", ""), row.get("item_id", ""))),
    }


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Coordinate Quality Audit",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- decision: {report['decision']}",
        "- mode: report_only",
        "- provider_calls: disabled",
        f"- item_count: {summary['item_count']}",
        f"- risk_count: {summary['risk_count']}",
        f"- high_risk_count: {summary['high_risk_count']}",
        "",
        "## Risk Type Counts",
        "",
    ]
    for risk_type, count in summary["risk_type_counts"].items():
        lines.append(f"- {risk_type}: {count}")
    lines.extend(["", "## High Risks", ""])
    high_rows = [row for row in report["risks"] if row["severity"] == "high"]
    if not high_rows:
        lines.append("- none")
    for row in high_rows[:100]:
        label = row.get("item_id") or f"{row.get('left_item_id')} / {row.get('right_item_id')}"
        details = []
        if row.get("distance_meters") is not None:
            details.append(f"distance={row['distance_meters']}m")
        if row.get("venue_id"):
            details.append(f"venue_id={row['venue_id']}")
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"- {row['risk_type']}: {label}{suffix}")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-json", type=Path, default=DEFAULT_CURRENT_JSON)
    parser.add_argument("--venue-registry", type=Path, default=DEFAULT_VENUE_REGISTRY)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--distance-threshold-meters", type=float, default=DEFAULT_DISTANCE_THRESHOLD_METERS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    current_payload = load_json(args.current_json)
    venue_registry_payload = load_json(args.venue_registry)
    report = analyze_coordinate_quality(
        current_payload,
        venue_registry_payload,
        distance_threshold_meters=args.distance_threshold_meters,
    )
    report["inputs"] = {
        "current_json": str(args.current_json),
        "venue_registry": str(args.venue_registry),
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir or DEFAULT_REPORT_ROOT / f"weekly_coordinate_quality_audit_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_coordinate_quality_audit.json"
    md_path = out_dir / "weekly_coordinate_quality_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({"ok": True, "decision": report["decision"], "out_dir": str(out_dir), "high_risk_count": report["summary"]["high_risk_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
