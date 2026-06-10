"""Build weekly_entity_snapshot.json from current publish items."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .indexes import load_atlas_alias_export, load_registry_seed
from .resolver import EntityResolver, build_resolver

CONTRACT_VERSION = "1.0.0"
SCHEMA_VERSION = "weekly_atlas_entity.v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def lineup_from_item(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("lineup", "lineup_artists"):
        raw = item.get(key)
        if isinstance(raw, list):
            values.extend(str(v).strip() for v in raw if str(v).strip())
        elif raw and str(raw).strip():
            values.append(str(raw).strip())
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def load_current_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    for key in ("items", "events", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def collect_artist_profiles(resolver: EntityResolver) -> list[dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for records in resolver.index.by_norm.values():
        for rec in records:
            if not rec.verified:
                continue
            if rec.artist_id in profiles:
                continue
            profiles[rec.artist_id] = {
                "artist_id": rec.artist_id,
                "canonical_name": rec.canonical_name,
                "verified": True,
                "bio_manual": rec.bio_manual,
                "avatar_url": rec.avatar_url,
                "source": rec.source,
                "last_updated": _utc_now()[:10],
            }
    return sorted(profiles.values(), key=lambda row: row["artist_id"])


def build_snapshot(
    items: list[dict[str, Any]],
    resolver: EntityResolver,
    *,
    publish_package: str = "",
) -> dict[str, Any]:
    lineup_resolved: list[dict[str, Any]] = []
    venue_resolved: list[dict[str, Any]] = []

    for item in items:
        event_id = str(item.get("event_id") or item.get("id") or "")
        if not event_id:
            continue
        for name in lineup_from_item(item):
            row = resolver.resolve(name).to_contract_row(event_id)
            lineup_resolved.append(row)
        venue = str(item.get("venue") or item.get("venue_name") or "").strip()
        if venue:
            venue_resolved.append(
                {
                    "event_id": event_id,
                    "venue_id": None,
                    "canonical_name": venue,
                    "match_score": 0.0,
                    "verified": False,
                }
            )

    return {
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "publish_package": publish_package,
        "artist_profiles": collect_artist_profiles(resolver),
        "lineup_resolved": lineup_resolved,
        "venue_resolved": venue_resolved,
        "stats": {
            "events": len(items),
            "lineup_rows": len(lineup_resolved),
            "methods": _method_counts(lineup_resolved),
        },
    }


def _method_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        method = str(row.get("match_method") or "unknown")
        counts[method] = counts.get(method, 0) + 1
    return counts


def build_snapshot_from_paths(
    current_path: Path,
    registry_path: Path,
    *,
    alias_export_path: Path | None = None,
    qdrant_url: str | None = None,
    publish_package: str = "",
) -> dict[str, Any]:
    registry = load_registry_seed(registry_path)
    alias = load_atlas_alias_export(alias_export_path) if alias_export_path else None
    resolver = build_resolver(registry, alias, qdrant_url=qdrant_url)
    items = load_current_items(current_path)
    pkg = publish_package or current_path.parent.name
    return build_snapshot(items, resolver, publish_package=pkg)
