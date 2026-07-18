#!/usr/bin/env python3
"""Apply strict-pass weekly geocodes to a mini-program API package.

The input geocode JSONL is produced by geocode_weekly_activity_places.py.
Only rows whose forward and reverse checks were accepted are applied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_API_DIR = ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release"
DEFAULT_REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports"))


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def first(value: Any, default: str = "") -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return default
    text = str(value or "").strip()
    return text or default


def stable_id(parts: list[str]) -> str:
    return hashlib.sha256("\t".join(parts).encode("utf-8")).hexdigest()[:16]


def candidate_id_from_item(item: dict[str, Any]) -> str:
    city = first(item.get("city"), first(item.get("city_key")))
    venue = first(item.get("venue_name"), first(item.get("venue"), first(item.get("promoter"), first(item.get("account")))))
    address = first(item.get("address"))
    return stable_id([city, venue, address])


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_accepted_geocodes(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    by_candidate: dict[str, dict[str, Any]] = {}
    by_item_id: dict[str, dict[str, Any]] = {}
    source_candidates: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        decision = row.get("decision") or {}
        candidate = row.get("candidate") or {}
        if not decision.get("accepted"):
            continue
        lat = decision.get("geo_lat")
        lng = decision.get("geo_lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
            continue
        entry = {
            "candidate_id": candidate.get("candidate_id") or "",
            "geo_lat": lat,
            "geo_lng": lng,
            "geo_coord_system": decision.get("geo_coord_system") or "GCJ-02",
            "geo_source": decision.get("geo_source") or row.get("provider") or "tencent_lbs",
            "geo_provider": row.get("provider") or "",
            "geo_reliability": decision.get("geo_reliability"),
            "geo_level": decision.get("geo_level"),
            "geo_provider_title": decision.get("provider_title") or "",
            "geo_provider_address": decision.get("provider_address") or "",
            "geo_reverse_address": (row.get("reverse_decision") or {}).get("reverse_address") or "",
        }
        candidate_id = entry["candidate_id"]
        if candidate_id:
            by_candidate[candidate_id] = entry
            source_candidates.append(candidate_id)
        for item_id in candidate.get("sample_item_ids") or []:
            if item_id:
                by_item_id[str(item_id)] = entry
    return by_candidate, by_item_id, sorted(set(source_candidates))


def has_existing_coord(item: dict[str, Any]) -> bool:
    lat = item.get("geo_lat")
    lng = item.get("geo_lng")
    return isinstance(lat, (int, float)) and isinstance(lng, (int, float)) and not (lat == 0 and lng == 0)


def item_id(item: dict[str, Any]) -> str:
    return first(item.get("id"), first(item.get("event_id")))


def geocode_for_item(
    item: dict[str, Any],
    by_candidate: dict[str, dict[str, Any]],
    by_item_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    ident = item_id(item)
    if ident in by_item_id:
        return by_item_id[ident]
    return by_candidate.get(candidate_id_from_item(item))


def apply_to_item(
    item: dict[str, Any],
    by_candidate: dict[str, dict[str, Any]],
    by_item_id: dict[str, dict[str, Any]],
    *,
    overwrite_existing: bool,
) -> bool:
    entry = geocode_for_item(item, by_candidate, by_item_id)
    if not entry:
        return False
    if has_existing_coord(item) and not overwrite_existing:
        return False
    for key in (
        "geo_lat",
        "geo_lng",
        "geo_coord_system",
        "geo_source",
        "geo_provider",
        "geo_reliability",
        "geo_level",
        "geo_provider_title",
        "geo_provider_address",
        "geo_reverse_address",
    ):
        value = entry.get(key)
        if value is not None:
            item[key] = value
    item["venue_lat"] = entry["geo_lat"]
    item["venue_lng"] = entry["geo_lng"]
    item["geo_verified_at"] = now_cst()
    item["geo_candidate_id"] = entry.get("candidate_id") or candidate_id_from_item(item)
    return True


def apply_to_payload(
    payload: Any,
    by_candidate: dict[str, dict[str, Any]],
    by_item_id: dict[str, dict[str, Any]],
    *,
    overwrite_existing: bool,
) -> set[str]:
    changed: set[str] = set()
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        for item in payload["items"]:
            if isinstance(item, dict) and apply_to_item(item, by_candidate, by_item_id, overwrite_existing=overwrite_existing):
                changed.add(item_id(item))
    elif isinstance(payload, dict) and isinstance(payload.get("item"), dict):
        item = payload["item"]
        if apply_to_item(item, by_candidate, by_item_id, overwrite_existing=overwrite_existing):
            changed.add(item_id(item))
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and apply_to_item(item, by_candidate, by_item_id, overwrite_existing=overwrite_existing):
                changed.add(item_id(item))
    return {ident for ident in changed if ident}


def backup_package(api_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in ("current.json", "manifest.json"):
        src = api_dir / name
        if src.exists():
            shutil.copy2(src, backup_dir / name)
    for name in ("by-id", "by-city", "by-date"):
        src = api_dir / name
        if src.exists():
            dst = backup_dir / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)


def apply_package(
    api_dir: Path,
    accepted_geocodes: Path,
    backup_dir: Path,
    *,
    overwrite_existing: bool = False,
) -> dict[str, Any]:
    by_candidate, by_item_id, source_candidates = load_accepted_geocodes(accepted_geocodes)
    backup_package(api_dir, backup_dir)
    files: list[Path] = [api_dir / "current.json"]
    for dirname in ("by-id", "by-city", "by-date"):
        directory = api_dir / dirname
        if directory.exists():
            files.extend(sorted(path for path in directory.glob("*.json") if path.name != "index.json"))

    changed_by_file: dict[str, int] = {}
    changed_item_ids: set[str] = set()
    for path in files:
        if not path.exists():
            continue
        payload = load_json(path)
        changed = apply_to_payload(payload, by_candidate, by_item_id, overwrite_existing=overwrite_existing)
        if changed:
            write_json(path, payload)
            changed_by_file[str(path.relative_to(api_dir))] = len(changed)
            changed_item_ids.update(changed)

    manifest_path = api_dir / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        manifest["geocode_enrichment"] = {
            "schema_version": "weekly_geocode_enrichment.v1",
            "applied_at": now_cst(),
            "accepted_place_count": len(by_candidate),
            "updated_item_count": len(changed_item_ids),
            "coord_system": "GCJ-02",
            "accepted_geocodes_path": str(accepted_geocodes),
            "backup_dir": str(backup_dir),
        }
        write_json(manifest_path, manifest)

    report = {
        "schema_version": "weekly_geocode_apply_report.v1",
        "applied_at": now_cst(),
        "api_dir": str(api_dir),
        "accepted_geocodes_path": str(accepted_geocodes),
        "backup_dir": str(backup_dir),
        "accepted_place_count": len(by_candidate),
        "source_candidate_ids": source_candidates,
        "updated_item_count": len(changed_item_ids),
        "updated_item_ids": sorted(changed_item_ids),
        "changed_by_file": changed_by_file,
        "overwrite_existing": overwrite_existing,
    }
    write_json(api_dir / "geocode_apply_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-dir", type=Path, default=DEFAULT_API_DIR)
    parser.add_argument("--accepted-geocodes", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--overwrite-existing", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = args.backup_dir or DEFAULT_REPORT_ROOT / f"weekly_geocode_apply_backup_{stamp}"
    report = apply_package(args.api_dir, args.accepted_geocodes, backup_dir, overwrite_existing=args.overwrite_existing)
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
