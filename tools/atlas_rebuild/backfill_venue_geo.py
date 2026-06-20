#!/usr/bin/env python3
"""Backfill vetted venue coordinates into atlas_serving_v2.sqlite.

This is an additive Stage4.5 step for the static Atlas star map. It reads only
already-confirmed local products:
- services/weekly_activity_cloudrun/data/current_release/current.json
- apps/weekly_activity_miniprogram/utils/mapLocationBook.js

The script updates only null venue_profile.geo_lat/geo_lng values in the v2 DB.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent

DEFAULT_DB = SCRIPT_DIR / "_fleet_14w_g5_80k_increment_20260620" / "merged" / "atlas_serving_v2.sqlite"
DEFAULT_CURRENT_RELEASE = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_MAP_LOCATION_BOOK = REPO_ROOT / "apps" / "weekly_activity_miniprogram" / "utils" / "mapLocationBook.js"
DEFAULT_REPORT = SCRIPT_DIR / "_starmap_out" / "venue_geo_backfill_report.json"

PUNCT_RE = re.compile(r"[\s\-_.,，。:：;；|｜/\\()（）\[\]【】{}<>《》\"'“”‘’`·•!！?？@#*+]+")
VENUE_SUFFIXES = (
    "livehouse",
    "live",
    "club",
    "bar",
    "space",
    "music",
    "酒吧",
    "俱乐部",
    "空间",
    "音乐",
    "舞厅",
)
CITY_SUFFIXES = ("市", "省", "特别行政区", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区")
CITY_ALIASES = {
    "beijing": "北京",
    "shanghai": "上海",
    "guangzhou": "广州",
    "shenzhen": "深圳",
    "hangzhou": "杭州",
    "chengdu": "成都",
    "chongqing": "重庆",
    "kunming": "昆明",
    "dali": "大理",
    "xian": "西安",
    "xi'an": "西安",
    "nanjing": "南京",
    "suzhou": "苏州",
    "xiamen": "厦门",
    "qingdao": "青岛",
    "tianjin": "天津",
    "changsha": "长沙",
    "wuhan": "武汉",
    "jinan": "济南",
}


@dataclass(frozen=True)
class Candidate:
    source: str
    source_id: str
    name: str
    city: str
    address: str
    lat: float
    lng: float
    priority: int
    keys: tuple[tuple, ...] = field(default_factory=tuple)


def _as_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (Path.cwd() / p).resolve()


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _norm(value) -> str:
    text = unicodedata.normalize("NFKC", _clean_text(value)).lower()
    return PUNCT_RE.sub("", text)


def _norm_city(value) -> str:
    city = _norm(value)
    city = CITY_ALIASES.get(city, city)
    changed = True
    while changed:
        changed = False
        for suffix in CITY_SUFFIXES:
            ns = _norm(suffix)
            if city.endswith(ns) and len(city) > len(ns):
                city = city[: -len(ns)]
                changed = True
    return city


def _venue_norm_variants(value) -> set[str]:
    base = _norm(value)
    out = {base} if base else set()
    if not base:
        return out
    loose = base
    for suffix in VENUE_SUFFIXES:
        loose = loose.replace(_norm(suffix), "")
    if loose and len(loose) >= 2:
        out.add(loose)
    return out


def _listish(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _json_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _num(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(n):
        return n
    return None


def _valid_coord(lat, lng) -> bool:
    return lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180


def _same_coord(a: Candidate, b: Candidate) -> bool:
    return abs(a.lat - b.lat) <= 0.000001 and abs(a.lng - b.lng) <= 0.000001


def _split_city_alias(value) -> tuple[str, str] | None:
    text = _clean_text(value)
    if "|" in text:
        left, right = text.split("|", 1)
    elif "｜" in text:
        left, right = text.split("｜", 1)
    else:
        return None
    city = _norm_city(left)
    names = _venue_norm_variants(right)
    name = sorted(names, key=len, reverse=True)[0] if names else ""
    return (city, name) if city and name else None


def _add_name_keys(keys: set[tuple], names: list, cities: list) -> None:
    city_norms = sorted({_norm_city(c) for c in cities if _norm_city(c)})
    for raw in names:
        split = _split_city_alias(raw)
        if split:
            keys.add(("city_name", split[0], split[1]))
        for name in _venue_norm_variants(raw):
            if not name:
                continue
            keys.add(("name", name))
            for city in city_norms:
                keys.add(("city_name", city, name))


def _add_address_keys(keys: set[tuple], addresses: list) -> None:
    for raw in addresses:
        addr = _norm(raw)
        if len(addr) >= 8:
            keys.add(("address", addr))


def _pick_geo(record: dict) -> tuple[float | None, float | None]:
    pairs = (
        ("geo_lat", "geo_lng"),
        ("venue_lat", "venue_lng"),
        ("latitude", "longitude"),
        ("lat", "lng"),
    )
    for lat_key, lng_key in pairs:
        lat, lng = _num(record.get(lat_key)), _num(record.get(lng_key))
        if _valid_coord(lat, lng):
            return lat, lng
    geo = record.get("geo")
    if isinstance(geo, dict):
        lat, lng = _num(geo.get("lat")), _num(geo.get("lng"))
        if _valid_coord(lat, lng):
            return lat, lng
    return None, None


def _candidate_from_fields(source: str, source_id: str, record: dict, priority: int) -> Candidate | None:
    lat, lng = _pick_geo(record)
    if not _valid_coord(lat, lng):
        return None

    cities = []
    for key in ("city_name", "city", "city_key", "venue_city", "geo_provider_city"):
        cities.extend(_listish(record.get(key)))

    names = []
    for key in (
        "venue_name",
        "venue_id",
        "venue",
        "name",
        "title",
        "map_poi_name",
        "poi_name",
        "geo_provider_title",
        "geo_search_aliases",
        "map_search_aliases",
        "poi_aliases",
        "aliases",
        "keys",
    ):
        names.extend(_listish(record.get(key)))

    addresses = []
    for key in ("address", "address_full", "map_poi_address", "geo_provider_address"):
        addresses.extend(_listish(record.get(key)))

    keys: set[tuple] = set()
    _add_name_keys(keys, names, cities)
    _add_address_keys(keys, addresses)
    if not keys:
        return None

    display_name = next((_clean_text(n) for n in names if _clean_text(n)), "")
    city = next((_clean_text(c) for c in cities if _clean_text(c)), "")
    address = next((_clean_text(a) for a in addresses if _clean_text(a)), "")
    return Candidate(source, source_id, display_name, city, address, float(lat), float(lng), priority, tuple(sorted(keys)))


def load_current_release(path: Path) -> tuple[list[Candidate], int]:
    if not path.exists():
        return [], 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("items", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return [], 0
    candidates = []
    for i, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        source_id = _clean_text(record.get("id") or record.get("event_id") or record.get("venue_id") or i)
        candidate = _candidate_from_fields("current_release", source_id, record, priority=100)
        if candidate:
            candidates.append(candidate)
    return candidates, len(records)


def load_map_location_book(path: Path) -> tuple[list[Candidate], int]:
    if not path.exists():
        return [], 0
    js = (
        "const mod=require(process.argv[1]);"
        "const book=mod.VERIFIED_MAP_LOCATION_BOOK||mod.default||mod;"
        "process.stdout.write(JSON.stringify(book));"
    )
    result = subprocess.run(
        ["node", "-e", js, str(path)],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    records = json.loads(result.stdout or "[]")
    if not isinstance(records, list):
        return [], 0
    candidates = []
    for i, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        candidate = _candidate_from_fields("map_location_book", str(i), record, priority=80)
        if candidate:
            candidates.append(candidate)
    return candidates, len(records)


def build_index(candidates: list[Candidate]) -> tuple[dict[tuple, Candidate], dict[str, int]]:
    raw: dict[tuple, list[Candidate]] = {}
    for c in candidates:
        for key in c.keys:
            raw.setdefault(key, []).append(c)

    unique = {}
    ambiguous = 0
    for key, hits in raw.items():
        best = sorted(hits, key=lambda c: (-c.priority, c.source, c.source_id))[0]
        if all(_same_coord(best, other) for other in hits):
            unique[key] = best
        else:
            ambiguous += 1

    return unique, {
        "raw_keys": len(raw),
        "unique_keys": len(unique),
        "ambiguous_keys": ambiguous,
    }


def venue_probe_keys(row: sqlite3.Row) -> list[tuple]:
    cities = [row["subject_city"], row["profile_city"]]
    names = [
        row["display_name"],
        row["name_en"],
        row["subject_id"].split(":", 1)[-1].replace("_", " "),
    ]
    names.extend(_json_list(row["aliases_json"]))

    keys: set[tuple] = set()
    _add_address_keys(keys, [row["address"]])
    _add_name_keys(keys, names, cities)

    # Prefer exact address and city-qualified name matches before global names.
    return sorted(keys, key=lambda k: {"address": 0, "city_name": 1, "name": 2}.get(k[0], 9))


def city_matches(row: sqlite3.Row, candidate: Candidate) -> bool:
    row_cities = {_norm_city(row["subject_city"]), _norm_city(row["profile_city"])} - {""}
    cand_city = _norm_city(candidate.city)
    return not row_cities or not cand_city or cand_city in row_cities


def match_venue(row: sqlite3.Row, index: dict[tuple, Candidate]) -> tuple[Candidate | None, tuple | None]:
    seen = set()
    for key in venue_probe_keys(row):
        if key in seen:
            continue
        seen.add(key)
        candidate = index.get(key)
        if not candidate:
            continue
        if key[0] == "name" and not city_matches(row, candidate):
            continue
        return candidate, key
    return None, None


def backfill(db_path: Path, current_release: Path, map_location_book: Path, report_path: Path, dry_run: bool) -> dict:
    current_candidates, current_records = load_current_release(current_release)
    map_candidates, map_records = load_map_location_book(map_location_book)
    candidates = current_candidates + map_candidates
    index, key_counts = build_index(candidates)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT s.subject_id, s.display_name, s.name_en, s.aliases_json, s.city_primary AS subject_city, "
        "s.event_count, vp.city AS profile_city, vp.address, vp.geo_lat, vp.geo_lng "
        "FROM subject s JOIN venue_profile vp ON vp.subject_id=s.subject_id "
        "WHERE s.subject_type='venue' ORDER BY s.event_count DESC, s.display_name"
    ).fetchall()

    existing_geo = sum(1 for r in rows if r["geo_lat"] is not None and r["geo_lng"] is not None)
    updates = []
    unmatched = []
    source_counts: dict[str, int] = {}

    for row in rows:
        if row["geo_lat"] is not None and row["geo_lng"] is not None:
            continue
        candidate, key = match_venue(row, index)
        if candidate:
            updates.append((row, candidate, key))
            source_counts[candidate.source] = source_counts.get(candidate.source, 0) + 1
        else:
            unmatched.append(row)

    if not dry_run and updates:
        conn.executemany(
            "UPDATE venue_profile SET geo_lat=?, geo_lng=? WHERE subject_id=? AND geo_lat IS NULL AND geo_lng IS NULL",
            [(c.lat, c.lng, r["subject_id"]) for r, c, _ in updates],
        )
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", ("venue_geo_backfilled", str(len(updates))))
        conn.commit()

    after_geo = conn.execute(
        "SELECT COUNT(*) FROM venue_profile WHERE geo_lat IS NOT NULL AND geo_lng IS NOT NULL"
    ).fetchone()[0]
    conn.close()

    report = {
        "db": str(db_path),
        "report": str(report_path),
        "dry_run": dry_run,
        "current_release": str(current_release),
        "map_location_book": str(map_location_book),
        "source_records": {
            "current_release": current_records,
            "map_location_book": map_records,
        },
        "candidate_count": len(candidates),
        "key_counts": key_counts,
        "venue_count": len(rows),
        "existing_geo_count": existing_geo,
        "matched_null_geo_count": len(updates),
        "updated_count": 0 if dry_run else len(updates),
        "after_geo_count": after_geo,
        "match_source_counts": source_counts,
        "sample_matches": [
            {
                "subject_id": r["subject_id"],
                "name": r["display_name"],
                "city": r["subject_city"] or r["profile_city"] or "",
                "source": c.source,
                "source_id": c.source_id,
                "lat": c.lat,
                "lng": c.lng,
                "key": list(key) if key else None,
            }
            for r, c, key in updates[:20]
        ],
        "top_unmatched": [
            {
                "subject_id": r["subject_id"],
                "name": r["display_name"],
                "city": r["subject_city"] or r["profile_city"] or "",
                "address": r["address"] or "",
                "event_count": int(r["event_count"] or 0),
            }
            for r in unmatched[:40]
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--current-release", default=str(DEFAULT_CURRENT_RELEASE))
    ap.add_argument("--map-location-book", default=str(DEFAULT_MAP_LOCATION_BOOK))
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    report = backfill(
        _as_path(args.db),
        _as_path(args.current_release),
        _as_path(args.map_location_book),
        _as_path(args.report),
        args.dry_run,
    )
    print(
        "venue geo backfill:",
        json.dumps(
            {
                "dry_run": report["dry_run"],
                "venue_count": report["venue_count"],
                "existing_geo_count": report["existing_geo_count"],
                "matched_null_geo_count": report["matched_null_geo_count"],
                "updated_count": report["updated_count"],
                "after_geo_count": report["after_geo_count"],
                "match_source_counts": report["match_source_counts"],
                "report": report["report"],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )


if __name__ == "__main__":
    main()
