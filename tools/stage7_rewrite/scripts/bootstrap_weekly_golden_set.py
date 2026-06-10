#!/usr/bin/env python3
"""Bootstrap weekly golden_set_v1.jsonl from a published API release package.

Report-only on release data; writes a new golden file for human annotation.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from weekly_golden_lib import (  # noqa: E402
    SCHEMA_VERSION,
    backend_url_lines,
    empty_gold,
    lineup_values,
    load_current_items,
    pipeline_snapshot,
    read_json,
    squash,
    write_jsonl,
)


def load_missing_lineup_ids(audit_path: Path) -> set[str]:
    if not audit_path.exists():
        return set()
    payload = read_json(audit_path)
    issues = payload.get("issues") if isinstance(payload, dict) else {}
    rows = issues.get("missing_lineup") if isinstance(issues, dict) else []
    return {squash(row.get("id")) for row in rows if isinstance(row, dict) and squash(row.get("id"))}


def classify_item(item: dict[str, Any], missing_ids: set[str]) -> tuple[str, str]:
    """Return (stratum, sample_category)."""
    eid = squash(item.get("event_id") or item.get("id"))
    lineup = lineup_values(item)
    url_count = len(backend_url_lines(item))
    desc_count = len(item.get("description_original_lines") or [])

    if url_count > 0:
        return "url_backend", "url_backend"
    if eid in missing_ids:
        return "missing_lineup", "missing_lineup"
    if lineup:
        return "lineup_present", "complete_control"
    if desc_count <= 2 and squash(item.get("cover_image_url") or item.get("cover_url")):
        return "image_heavy", "image_heavy"
    return "complete_control", "complete_control"


def pick_stratified(
    items: list[dict[str, Any]],
    missing_ids: set[str],
    target: int,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "lineup_present": [],
        "missing_lineup": [],
        "url_backend": [],
        "image_heavy": [],
        "complete_control": [],
    }
    for item in items:
        stratum, _ = classify_item(item, missing_ids)
        if stratum in buckets:
            buckets[stratum].append(item)

    quotas = {
        "lineup_present": min(22, len(buckets["lineup_present"])),
        "missing_lineup": min(28, len(buckets["missing_lineup"])),
        "url_backend": min(18, len(buckets["url_backend"])),
        "image_heavy": min(12, len(buckets["image_heavy"])),
        "complete_control": min(10, len(buckets["complete_control"])),
    }
    total_quota = sum(quotas.values())
    if total_quota < target:
        remaining = target - total_quota
        for key in ("missing_lineup", "lineup_present", "url_backend"):
            room = len(buckets[key]) - quotas[key]
            add = min(room, remaining)
            quotas[key] += add
            remaining -= add
            if remaining <= 0:
                break

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    city_counts: dict[str, int] = {}

    def take_from(bucket: str, count: int) -> None:
        nonlocal selected
        for item in buckets[bucket]:
            if len([x for x in selected if classify_item(x, missing_ids)[0] == bucket]) >= count:
                break
            eid = squash(item.get("event_id") or item.get("id"))
            if not eid or eid in seen:
                continue
            city = squash(item.get("city_key") or item.get("city")) or "unknown"
            if city_counts.get(city, 0) >= 25:
                continue
            seen.add(eid)
            city_counts[city] = city_counts.get(city, 0) + 1
            selected.append(item)

    for bucket, count in quotas.items():
        take_from(bucket, count)

    if len(selected) < target:
        for bucket in ("complete_control", "image_heavy", "missing_lineup", "lineup_present"):
            need = quotas.get(bucket, 0) - len(
                [x for x in selected if classify_item(x, missing_ids)[0] == bucket]
            )
            if need > 0 and bucket in buckets:
                take_from(bucket, quotas.get(bucket, 0) + need)
            if len(selected) >= target:
                break
    return selected[:target]


def build_row(item: dict[str, Any], missing_ids: set[str]) -> dict[str, Any]:
    eid = squash(item.get("event_id") or item.get("id"))
    stratum, sample_category = classify_item(item, missing_ids)
    return {
        "golden_id": f"golden_v1_{eid.replace(':', '_')}",
        "event_id": eid,
        "schema_version": SCHEMA_VERSION,
        "stratum": stratum,
        "sample_category": sample_category,
        "annotation_status": "pending",
        "annotator": None,
        "annotated_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gold": empty_gold(),
        "pipeline_snapshot": pipeline_snapshot(item),
        "source_hints": {
            "title": squash(item.get("title")),
            "venue": squash(item.get("venue") or item.get("venue_name")),
            "account": squash(item.get("account")),
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    default_release = Path(
        r"D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519"
    )
    parser.add_argument("--current", type=Path, default=default_release / "current.json")
    parser.add_argument("--audit", type=Path, default=default_release / "lineup_address_time_audit.json")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(r"D:\downstream_results\golden\golden_set_v1.jsonl"),
    )
    parser.add_argument(
        "--repo-copy",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "golden" / "golden_set_v1.jsonl",
    )
    parser.add_argument("--no-repo-copy", action="store_true", help="Skip writing repo golden copy")
    parser.add_argument("--target-count", type=int, default=88)
    parser.add_argument("--manifest", type=Path, default=None, help="Optional manifest JSON path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    items = load_current_items(args.current)
    if not items:
        raise SystemExit(f"No items in {args.current}")

    missing_ids = load_missing_lineup_ids(args.audit)
    picked = pick_stratified(items, missing_ids, args.target_count)
    rows = [build_row(item, missing_ids) for item in picked]

    write_jsonl(args.out, rows)
    if not args.no_repo_copy:
        write_jsonl(args.repo_copy, rows)

    stratum_counts: dict[str, int] = {}
    for row in rows:
        stratum_counts[row["stratum"]] = stratum_counts.get(row["stratum"], 0) + 1

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema_version": SCHEMA_VERSION,
        "source_current": str(args.current),
        "source_audit": str(args.audit),
        "item_count_source": len(items),
        "golden_count": len(rows),
        "stratum_counts": stratum_counts,
        "annotation_pending": len(rows),
        "annotation_verified": 0,
        "out_path": str(args.out),
        "repo_copy": str(args.repo_copy) if args.repo_copy else None,
    }
    manifest_path = args.manifest or args.out.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
