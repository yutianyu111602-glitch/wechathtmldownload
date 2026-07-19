#!/usr/bin/env python3
"""Compute and stamp the exact semantic generation of a weekly API package."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import tempfile
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any


BUILDER = Path(__file__).resolve().parent / "archive_old" / "build_weekly_activity_miniprogram_api.py"
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from weekly_public_projection import (  # noqa: E402
    assert_public_payload,
    project_public_source_map_payload,
    public_package_json_paths,
)


def _load_builder():
    spec = importlib.util.spec_from_file_location("weekly_api_generation_builder", BUILDER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.generation.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso_date(value: Any) -> str:
    text = _text(value)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _date_keys(item: dict[str, Any]) -> list[str]:
    """Mirror the final package's inclusive-range/discrete-date contract."""

    start = _iso_date(item.get("event_date_start"))
    end = _iso_date(item.get("event_date_end"))
    if start:
        if not end:
            return [start]
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        if end_date < start_date:
            raise ValueError(f"event date range is reversed for {_text(item.get('id'))}: {start}>{end}")
        return [
            (start_date + timedelta(days=offset)).isoformat()
            for offset in range((end_date - start_date).days + 1)
        ]

    values: list[Any] = []
    raw = item.get("event_date_iso_guesses")
    if isinstance(raw, list):
        values.extend(raw)
    values.append(item.get("event_date_iso_guess"))
    keys: list[str] = []
    for value in values:
        key = _iso_date(value)
        if key and key not in keys:
            keys.append(key)
    return keys


def _city_entries(item: dict[str, Any]) -> list[tuple[str, str]]:
    raw_keys = item.get("city_keys") if isinstance(item.get("city_keys"), list) else []
    raw_labels = item.get("city") if isinstance(item.get("city"), list) else []
    primary_key = _text(item.get("city_key"))
    primary_label = _text(item.get("city_name")) or (_text(raw_labels[0]) if raw_labels else "")
    label_by_key: dict[str, str] = {}
    for index, value in enumerate(raw_keys):
        key = _text(value)
        label = _text(raw_labels[index]) if index < len(raw_labels) else ""
        if key and label:
            label_by_key.setdefault(key, label)
    keys: list[str] = []
    for value in [primary_key, *raw_keys]:
        key = _text(value)
        if key and key not in keys:
            keys.append(key)
    if not keys and primary_label:
        keys.append(primary_label)
        label_by_key.setdefault(primary_label, primary_label)
    return [
        (key, label_by_key.get(key) or (primary_label if key == primary_key else "") or key)
        for key in keys
    ]


def _detail_relative_path(item: dict[str, Any], builder: Any) -> str:
    item_id = _text(item.get("id"))
    if not item_id:
        raise ValueError("current.json contains an item without id")
    expected = f"by-id/{builder.slugify(item_id, fallback='item')}.json"
    declared = _text(item.get("detail_path") or item.get("detail_url"))
    if declared and Path(declared).as_posix() != expected:
        raise ValueError(f"detail path does not match item id {item_id}: {declared} != {expected}")
    return expected


def _derived_route_payloads(
    current: dict[str, Any],
    manifest: dict[str, Any],
    builder: Any,
) -> dict[str, dict[str, Any]]:
    items = current.get("items")
    if not isinstance(items, list):
        raise ValueError("current.json items must be a list")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("current.json items must contain JSON objects only")
    item_ids = [_text(item.get("id")) for item in items]
    if any(not item_id for item_id in item_ids) or len(set(item_ids)) != len(item_ids):
        raise ValueError("current.json item ids must be present and unique")

    generated_at = _text(current.get("generated_at") or current.get("generatedAt"))
    if not generated_at:
        raise ValueError("current.json generated_at is required for derived route closure")
    sorted_items = builder.sort_items(items)
    cities: dict[str, dict[str, Any]] = {}
    dates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        for city_key, city_label in _city_entries(item):
            safe_city_key = builder.slugify(city_key, fallback="")
            if not safe_city_key or safe_city_key != city_key:
                raise ValueError(f"unsafe city route key for {_text(item.get('id'))}: {city_key}")
            row = cities.setdefault(city_key, {"city": city_label, "items": []})
            row["items"].append(item)
        for date_key in _date_keys(item):
            dates[date_key].append(item)

    payloads: dict[str, dict[str, Any]] = {}
    city_index_rows: list[dict[str, Any]] = []
    for city_key, row in sorted(cities.items()):
        city_items = builder.sort_items(row["items"])
        relative = f"by-city/{city_key}.json"
        payloads[relative] = {
            "schema_version": "weekly_activity_miniprogram_city.v1",
            "generated_at": generated_at,
            "scope": "package",
            "city_key": city_key,
            "city": row["city"],
            "item_count": len(city_items),
            "items": city_items,
        }
        city_index_rows.append({
            "city_key": city_key,
            "city": row["city"],
            "count": len(city_items),
            "path": relative,
            "url": relative,
        })
    payloads["by-city/index.json"] = {
        "schema_version": "weekly_activity_miniprogram_city_index.v1",
        "generated_at": generated_at,
        "scope": "package",
        "item_count": len(sorted_items),
        "window_start": _text(manifest.get("window_start")) or None,
        "window_end": _text(manifest.get("window_end")) or None,
        "city_count": len(city_index_rows),
        "cities": city_index_rows,
    }

    date_index_rows: list[dict[str, Any]] = []
    for date_key, date_items in sorted(dates.items()):
        route_items = builder.sort_items(date_items)
        relative = f"by-date/{date_key}.json"
        payloads[relative] = {
            "schema_version": "weekly_activity_miniprogram_date.v1",
            "generated_at": generated_at,
            "scope": "package",
            "date": date_key,
            "item_count": len(route_items),
            "items": route_items,
        }
        date_index_rows.append({
            "date": date_key,
            "count": len(route_items),
            "path": relative,
            "url": relative,
        })
    payloads["by-date/index.json"] = {
        "schema_version": "weekly_activity_miniprogram_date_index.v1",
        "generated_at": generated_at,
        "scope": "package",
        "item_count": len(sorted_items),
        "window_start": _text(manifest.get("window_start")) or None,
        "window_end": _text(manifest.get("window_end")) or None,
        "date_count": len(date_index_rows),
        "dates": date_index_rows,
    }

    for item in items:
        payloads[_detail_relative_path(item, builder)] = {
            "schema_version": "weekly_activity_miniprogram_detail.v1",
            "generated_at": generated_at,
            "item": item,
        }
    for relative in payloads:
        route = Path(relative)
        if (
            route.is_absolute()
            or ".." in route.parts
            or route.suffix.casefold() != ".json"
            or len(route.parts) != 2
            or route.parts[0] not in {"by-id", "by-city", "by-date"}
        ):
            raise ValueError(f"unsafe derived weekly route: {relative}")
    return payloads


def _semantic_route_payload(relative: str, payload: dict[str, Any]) -> Any:
    """Return the exact current-derived contract, excluding the stamp itself."""

    common = {
        "schema_version": payload.get("schema_version"),
        "generated_at": payload.get("generated_at") or payload.get("generatedAt"),
    }
    if relative.startswith("by-id/"):
        return {**common, "item": payload.get("item")}
    if relative == "by-city/index.json":
        rows = []
        for row in payload.get("cities") or []:
            rows.append({
                "city_key": row.get("city_key"),
                "city": row.get("city"),
                "count": row.get("count", row.get("item_count")),
                "path": row.get("path"),
            })
        return {
            **common,
            "scope": payload.get("scope"),
            "item_count": payload.get("item_count"),
            "city_count": payload.get("city_count"),
            "cities": rows,
        }
    if relative == "by-date/index.json":
        rows = []
        for row in payload.get("dates") or []:
            rows.append({
                "date": row.get("date"),
                "count": row.get("count", row.get("item_count")),
                "path": row.get("path"),
            })
        return {
            **common,
            "scope": payload.get("scope"),
            "item_count": payload.get("item_count"),
            "date_count": payload.get("date_count"),
            "dates": rows,
        }
    if relative.startswith("by-city/"):
        return {
            **common,
            "scope": payload.get("scope"),
            "city_key": payload.get("city_key"),
            "city": payload.get("city"),
            "item_count": payload.get("item_count"),
            "items": payload.get("items"),
        }
    return {
        **common,
        "scope": payload.get("scope"),
        "date": payload.get("date"),
        "item_count": payload.get("item_count"),
        "items": payload.get("items"),
    }


def _closure_report(api_dir: Path, expected: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected_files = set(expected)
    actual_files: set[str] = set()
    for directory in ("by-id", "by-city", "by-date"):
        root = api_dir / directory
        if root.exists():
            actual_files.update(path.relative_to(api_dir).as_posix() for path in root.glob("*.json") if path.is_file())
    missing = sorted(expected_files - actual_files)
    extra = sorted(actual_files - expected_files)
    mismatched: list[str] = []
    for relative in sorted(expected_files & actual_files):
        try:
            actual = read_json(api_dir / relative)
        except (OSError, json.JSONDecodeError, ValueError):
            mismatched.append(relative)
            continue
        if _canonical(_semantic_route_payload(relative, actual)) != _canonical(
            _semantic_route_payload(relative, expected[relative])
        ):
            mismatched.append(relative)
    return {
        "schema_version": "weekly_activity_derived_route_closure.v1",
        "ok": not missing and not extra and not mismatched,
        "expected_file_count": len(expected_files),
        "actual_file_count": len(actual_files),
        "missing_files": missing,
        "extra_files": extra,
        "mismatched_files": mismatched,
    }


def validate_derived_route_closure(api_dir: Path) -> dict[str, Any]:
    api_dir = api_dir.resolve()
    current = read_json(api_dir / "current.json")
    manifest = read_json(api_dir / "manifest.json")
    public_paths = public_package_json_paths(api_dir)
    for path in public_paths:
        payload = read_json(path)
        relative = path.relative_to(api_dir).as_posix()
        if relative == "source_actions/source_url_map.json":
            projected = project_public_source_map_payload(payload)
            if projected != payload:
                raise ValueError("weekly public source_url_map.json is not in canonical public form")
        assert_public_payload(payload, label=f"weekly public package route {relative}")
    expected = _derived_route_payloads(current, manifest, _load_builder())
    report = _closure_report(api_dir, expected)
    report["public_payload_file_count"] = len(public_paths)
    if not report["ok"]:
        raise ValueError(
            "weekly API derived route closure failed: "
            + json.dumps(report, ensure_ascii=False, sort_keys=True)
        )
    return report


def rebuild_derived_routes(api_dir: Path) -> dict[str, Any]:
    """Transactionally replace by-id/by-city/by-date from current.json."""

    api_dir = api_dir.resolve()
    current = read_json(api_dir / "current.json")
    manifest = read_json(api_dir / "manifest.json")
    expected = _derived_route_payloads(current, manifest, _load_builder())
    staging = Path(tempfile.mkdtemp(prefix=".derived-routes-staging-", dir=api_dir))
    backup = Path(tempfile.mkdtemp(prefix=".derived-routes-backup-", dir=api_dir))
    moved: list[tuple[str, bool]] = []
    try:
        for directory in ("by-id", "by-city", "by-date"):
            (staging / directory).mkdir(parents=True, exist_ok=True)
        for relative, payload in expected.items():
            write_json_atomic(staging / relative, payload)
        staged_report = _closure_report(staging, expected)
        if not staged_report["ok"]:
            raise ValueError("generated derived routes failed their own closure validation")
        for directory in ("by-id", "by-city", "by-date"):
            target = api_dir / directory
            had_existing = target.exists()
            if had_existing:
                target.replace(backup / directory)
            try:
                (staging / directory).replace(target)
            except Exception:
                saved = backup / directory
                if had_existing and saved.exists():
                    saved.replace(target)
                raise
            moved.append((directory, had_existing))
        report = _closure_report(api_dir, expected)
        if not report["ok"]:
            raise ValueError("installed derived routes failed closure validation")
        return report
    except Exception:
        for directory, had_existing in reversed(moved):
            target = api_dir / directory
            if target.exists():
                shutil.rmtree(target)
            saved = backup / directory
            if had_existing and saved.exists():
                saved.replace(target)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def generation_files(api_dir: Path) -> list[Path]:
    # Publish the handshake owners last. If the process is interrupted, old
    # current/manifest identities remain visible and readers fail closed rather
    # than accepting half-stamped derived routes.
    candidates = [
        api_dir / "source_actions" / "source_url_map.json",
        api_dir / "weekly_entity_snapshot.json",
        api_dir / "build_filter_dispositions.json",
    ]
    for directory in ("by-city", "by-date", "by-id"):
        root = api_dir / directory
        if root.exists():
            candidates.extend(sorted(root.glob("*.json")))
    candidates.extend([api_dir / "current.json", api_dir / "manifest.json"])
    seen: set[Path] = set()
    return [path for path in candidates if path.is_file() and not (path in seen or seen.add(path))]


def stamp_generation(api_dir: Path) -> dict[str, Any]:
    api_dir = api_dir.resolve()
    manifest_path = api_dir / "manifest.json"
    current_path = api_dir / "current.json"
    source_map_path = api_dir / "source_actions" / "source_url_map.json"
    for required in (manifest_path, current_path, source_map_path):
        if not required.is_file():
            raise FileNotFoundError(f"weekly API generation input is missing: {required}")

    manifest = read_json(manifest_path)
    current = read_json(current_path)
    source_map_payload = project_public_source_map_payload(read_json(source_map_path))
    write_json_atomic(source_map_path, source_map_payload)
    items = current.get("items")
    sources = source_map_payload.get("sources")
    window_start = str(manifest.get("window_start") or "").strip()
    window_end = str(manifest.get("window_end") or "").strip()
    if not isinstance(items, list):
        raise ValueError("current.json items must be a list")
    if not isinstance(sources, dict):
        raise ValueError("source_url_map.json sources must be an object")
    if not window_start or not window_end:
        raise ValueError("manifest window_start/window_end are required for deterministic generation")

    # Every derived public route is regenerated from the final current.json.
    # This removes stale extra files and prevents a generation stamp from ever
    # laundering an older detail/facet payload into the new package.
    rebuild_derived_routes(api_dir)
    closure = validate_derived_route_closure(api_dir)

    builder = _load_builder()
    generation_id = builder.compute_generation_id(
        items=items,
        source_map=sources,
        window_start=window_start,
        window_end=window_end,
    )
    stamped: list[str] = []
    for path in generation_files(api_dir):
        payload = read_json(path)
        payload["generation_id"] = generation_id
        write_json_atomic(path, payload)
        stamped.append(str(path))

    return {
        "schema_version": "weekly_activity_generation_stamp.v1",
        "generation_id": generation_id,
        "api_dir": str(api_dir),
        "item_count": len(items),
        "source_count": len(sources),
        "window_start": window_start,
        "window_end": window_end,
        "derived_route_closure": closure,
        "stamped_file_count": len(stamped),
        "stamped_files": stamped,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = stamp_generation(args.api_dir)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
