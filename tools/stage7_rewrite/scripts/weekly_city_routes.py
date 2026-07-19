#!/usr/bin/env python3
"""Shared static ``by-city`` route membership for weekly activity packages.

The serving API treats an event as belonging to the union of ``city_key`` and
``city_keys``. Post-build repair scripts must use that same contract when they
regenerate static routes, or a legitimate secondary-city event disappears
from the corresponding route and facet count.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def text(value: Any) -> str:
    return str(value or "").strip()


def item_city_entries(
    item: Mapping[str, Any],
    *,
    fallback_city_keys: Mapping[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Return ordered, deduplicated ``(city_key, label)`` memberships."""

    raw_keys = item.get("city_keys") if isinstance(item.get("city_keys"), list) else []
    raw_labels = item.get("city") if isinstance(item.get("city"), list) else []
    label_by_key: dict[str, str] = {}
    for index, value in enumerate(raw_keys):
        key = text(value)
        label = text(raw_labels[index]) if index < len(raw_labels) else ""
        if key and label and key not in label_by_key:
            label_by_key[key] = label

    primary_key = text(item.get("city_key"))
    ordered_keys: list[str] = []
    for value in [primary_key, *raw_keys]:
        key = text(value)
        if key and key not in ordered_keys:
            ordered_keys.append(key)

    primary_label = text(item.get("city_name"))
    if not primary_label:
        city_value = item.get("city")
        primary_label = text(city_value[0]) if isinstance(city_value, list) and city_value else text(city_value)

    if not ordered_keys and primary_label:
        fallback_key = text((fallback_city_keys or {}).get(primary_label)) or primary_label
        ordered_keys.append(fallback_key)
        label_by_key.setdefault(fallback_key, primary_label)

    entries: list[tuple[str, str]] = []
    for key in ordered_keys:
        label = label_by_key.get(key) or (primary_label if key == primary_key else "") or key
        entries.append((key, label))
    return entries


def group_items_by_city(
    items: Iterable[Any],
    *,
    fallback_city_keys: Mapping[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Group each item into every city membership exactly once."""

    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for city_key, city_label in item_city_entries(item, fallback_city_keys=fallback_city_keys):
            row = grouped.setdefault(city_key, {"city": city_label, "items": []})
            row["items"].append(item)
    return grouped
