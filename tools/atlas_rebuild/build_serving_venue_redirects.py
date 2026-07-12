#!/usr/bin/env python3
"""Build conservative venue identity redirects from an Atlas serving snapshot."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "atlas_serving_venue_redirect.v1"
TYPE_WORDS = (
    "音乐厂牌",
    "livehouse",
    "live house",
    "live-house",
    "音乐空间",
    "俱乐部",
    "lounge",
    "space",
    "club",
    "酒吧",
    "bar",
    "场地",
    "venue",
    "the ",
)
UNKNOWN_CITIES = {"", "未知", "不详", "unknown", "none", "null"}
UNCERTAIN_RE = re.compile(
    r"[\(（\[【][^\)）\]】]*(?:推测|疑似|推断|可能|暂定|待确认)[^\)）\]】]*[\)）\]】]",
    re.IGNORECASE,
)
BOUNDARY_RE = re.compile(
    r"(?:\b(?:black\s+room|room\s*\d*|live\s*stage|stage\s*\d*|floor\s*\d*|gin\s*bar|on\s*wax|terrace)\b|"
    r"一楼|二楼|三楼|四楼|贰楼|楼层|大舞池|小舞池|舞池|露台|天台|主舞台|副舞台|房间|厅)",
    re.IGNORECASE,
)
COMPOUND_RE = re.compile(r"(?:\s[/|]\s|或(?:the\s+)?[a-z\u4e00-\u9fff]|以及)", re.IGNORECASE)
LATIN_TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
GENERIC_TOKENS = {"the", "club", "bar", "space", "venue", "live", "house", "music"}


class UnionFind:
    def __init__(self, values: list[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        while parent != self.parent[parent]:
            self.parent[parent] = self.parent[self.parent[parent]]
            parent = self.parent[parent]
        self.parent[value] = parent
        return parent

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            low, high = sorted((left_root, right_root))
            self.parent[high] = low


def _open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _text(value: str | None) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _city_key(value: str | None) -> str:
    city = re.sub(r"\s+", "", _text(value))
    return "" if city in UNKNOWN_CITIES else city


def _strip_uncertainty(value: str | None) -> str:
    return UNCERTAIN_RE.sub("", _text(value)).strip()


def _registry_key(value: str | None) -> str:
    return re.sub(r"\s+", "", _strip_uncertainty(value))


def core_key(value: str | None) -> str:
    text = _strip_uncertainty(value)
    for word in TYPE_WORDS:
        text = text.replace(word, "")
    return re.sub(r"[\s\-_·•|/\\:：,，.。()（）\[\]【】&'\"!?！？]+", "", text)


def _name_key(value: str | None) -> str:
    return re.sub(r"[\s\-_·•|/\\:：,，.。()（）\[\]【】&'\"!?！？]+", "", _strip_uncertainty(value))


def _has_boundary(value: str | None) -> bool:
    text = _text(value)
    return bool(BOUNDARY_RE.search(text) or COMPOUND_RE.search(text))


def _brand_tokens(value: str | None) -> set[str]:
    return {token for token in LATIN_TOKEN_RE.findall(_strip_uncertainty(value)) if token not in GENERIC_TOKENS}


def _brand_compatible(left: dict, right: dict) -> bool:
    left_core = left["core"]
    right_core = right["core"]
    if left_core and left_core == right_core:
        return True
    if min(len(left_core), len(right_core)) >= 3 and (
        left_core.startswith(right_core) or right_core.startswith(left_core)
    ):
        return True
    return bool(_brand_tokens(left["name"]) & _brand_tokens(right["name"]))


def _rank(record: dict) -> tuple:
    return (
        -int(record["event_count"] or 0),
        int(bool(UNCERTAIN_RE.search(_text(record["name"])))),
        int(record["source_kind"] != "canonical_subject"),
        len(_strip_uncertainty(record["name"])),
        record["venue_id"],
    )


def _load_geo(path: Path | None) -> tuple[dict[str, set[tuple[float, float]]], list[dict]]:
    if path is None:
        return {}, []
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    venues = payload.get("venues", payload)
    if not isinstance(venues, dict):
        raise ValueError(f"Historical geo registry has no venue map: {path}")
    aliases: dict[str, set[tuple[float, float]]] = defaultdict(set)
    digest_rows: list[dict] = []
    for key, raw in venues.items():
        if not isinstance(raw, dict):
            continue
        try:
            lat = float(raw.get("geo_lat"))
            lng = float(raw.get("geo_lng"))
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
            continue
        coord = (round(lat, 6), round(lng, 6))
        keys = {
            _registry_key(str(key)),
            _registry_key(raw.get("name")),
            core_key(str(key)),
            core_key(raw.get("name")),
        }
        for alias in keys:
            if alias:
                aliases[alias].add(coord)
        digest_rows.append({"key": str(key), "name": raw.get("name"), "lat": coord[0], "lng": coord[1]})
    return dict(aliases), sorted(digest_rows, key=lambda row: row["key"])


def _lookup_geo(record: dict, aliases: dict[str, set[tuple[float, float]]]) -> tuple[float, float] | None:
    coords: set[tuple[float, float]] = set()
    for key in {_registry_key(record["name"]), record["core"]}:
        if key:
            coords.update(aliases.get(key, set()))
    return next(iter(coords)) if len(coords) == 1 else None


def _load_accepted_review(path: Path | None) -> tuple[list[tuple[str, str]], list[dict]]:
    if path is None:
        return [], []
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    payload = json.loads(raw.decode("utf-8"))
    clusters = payload.get("clusters", [])
    mappings: list[tuple[str, str]] = []
    accepted_rows: list[dict] = []
    for cluster in clusters:
        confidence = str(cluster.get("confidence") or "")
        explicitly_accepted = cluster.get("accepted") is True or cluster.get("review_state") == "accepted"
        if confidence != "exact_core" and not explicitly_accepted:
            continue
        target = str(cluster.get("suggestedCanonical") or cluster.get("canonical_venue_id") or "")
        for member in cluster.get("members", []):
            source = str(member.get("venueId") or member.get("source_venue_id") or "")
            if source and target and source != target:
                mappings.append((source, target))
                accepted_rows.append({"source": source, "target": target, "confidence": confidence})
    return mappings, accepted_rows


def _load_records(con: sqlite3.Connection) -> list[dict]:
    records: dict[str, dict] = {}
    observed_cities: dict[str, set[str]] = defaultdict(set)
    for row in con.execute(
        """
        SELECT venue_id,COALESCE(city,'') AS city
          FROM dj_event
         WHERE venue_id IS NOT NULL AND venue_id<>''
         GROUP BY venue_id,city
        """
    ):
        city_key = _city_key(row["city"])
        if city_key:
            observed_cities[row["venue_id"]].add(city_key)
    for row in con.execute(
        """
        SELECT subject_id AS venue_id,display_name AS name,COALESCE(city_primary,'') AS city,
               COALESCE(event_count,0) AS event_count
          FROM canonical_subject
         WHERE subject_type='venue'
         ORDER BY subject_id
        """
    ):
        records[row["venue_id"]] = {
            **dict(row),
            "source_kind": "canonical_subject",
        }

    grouped = con.execute(
        """
        SELECT venue_id,COALESCE(venue_name,'') AS name,COALESCE(city,'') AS city,
               COUNT(DISTINCT event_id) AS event_count
          FROM dj_event
         WHERE venue_id IS NOT NULL AND venue_id<>''
         GROUP BY venue_id,name,city
         ORDER BY venue_id,event_count DESC,name ASC,city ASC
        """
    )
    seen_event_ids: set[str] = set()
    for row in grouped:
        venue_id = row["venue_id"]
        if venue_id in records or venue_id in seen_event_ids:
            continue
        seen_event_ids.add(venue_id)
        records[venue_id] = {
            **dict(row),
            "source_kind": "dj_event_only",
        }

    result: list[dict] = []
    for record in records.values():
        result.append(
            {
                **record,
                "core": core_key(record["name"]),
                "name_key": _name_key(record["name"]),
                "city_key": _city_key(record["city"]),
                "observed_city_keys": sorted(observed_cities.get(record["venue_id"], set())),
                "unsafe_boundary": _has_boundary(record["name"]),
            }
        )
    return sorted(result, key=lambda row: row["venue_id"])


def _digest(rows: list[dict]) -> str:
    hasher = hashlib.sha256()
    for row in rows:
        hasher.update(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def _timestamp(paths: list[Path]) -> str:
    return datetime.fromtimestamp(max(path.stat().st_mtime for path in paths), timezone.utc).replace(microsecond=0).isoformat()


def _write_output(out_db: Path, redirects: list[dict], reviews: list[dict], metadata: dict[str, str]) -> None:
    out_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = out_db.with_name(f"{out_db.name}.tmp")
    if tmp_db.exists():
        tmp_db.unlink()
    con = sqlite3.connect(tmp_db)
    try:
        con.executescript(
            """
            PRAGMA journal_mode=DELETE;
            CREATE TABLE venue_identity_redirect (
              source_venue_id TEXT PRIMARY KEY,
              source_city TEXT NOT NULL,
              source_city_key TEXT NOT NULL,
              canonical_venue_id TEXT NOT NULL,
              canonical_city TEXT NOT NULL,
              canonical_city_key TEXT NOT NULL,
              decision_method TEXT NOT NULL,
              decision_reason TEXT NOT NULL,
              confidence REAL NOT NULL,
              decided_at TEXT NOT NULL
            );
            CREATE INDEX idx_venue_identity_redirect_canonical
              ON venue_identity_redirect(canonical_venue_id);
            CREATE TABLE venue_identity_review_candidate (
              source_venue_id TEXT NOT NULL,
              candidate_venue_id TEXT NOT NULL,
              city TEXT,
              source_name TEXT NOT NULL,
              candidate_name TEXT NOT NULL,
              reason TEXT NOT NULL,
              review_state TEXT NOT NULL,
              PRIMARY KEY(source_venue_id,candidate_venue_id)
            );
            CREATE INDEX idx_venue_identity_review_state
              ON venue_identity_review_candidate(review_state,city);
            CREATE TABLE venue_identity_build_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )
        con.executemany(
            """
            INSERT INTO venue_identity_redirect
              (source_venue_id,source_city,source_city_key,canonical_venue_id,canonical_city,canonical_city_key,
               decision_method,decision_reason,confidence,decided_at)
            VALUES
              (:source_venue_id,:source_city,:source_city_key,:canonical_venue_id,:canonical_city,:canonical_city_key,
               :decision_method,:decision_reason,:confidence,:decided_at)
            """,
            redirects,
        )
        con.executemany(
            """
            INSERT INTO venue_identity_review_candidate
              (source_venue_id,candidate_venue_id,city,source_name,candidate_name,reason,review_state)
            VALUES
              (:source_venue_id,:candidate_venue_id,:city,:source_name,:candidate_name,:reason,:review_state)
            """,
            reviews,
        )
        con.executemany(
            "INSERT INTO venue_identity_build_metadata(key,value) VALUES (?,?)",
            sorted(metadata.items()),
        )
        con.commit()
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Generated venue sidecar failed PRAGMA quick_check")
    except Exception:
        con.close()
        if tmp_db.exists():
            tmp_db.unlink()
        raise
    else:
        con.close()
    os.replace(tmp_db, out_db)


def build_venue_redirects(
    source_serving_db: Path | str,
    out_db: Path | str,
    *,
    historical_geo: Path | str | None = None,
    accepted_review: Path | str | None = None,
    report_path: Path | str | None = None,
) -> dict:
    source_path = Path(source_serving_db).resolve()
    output_path = Path(out_db).resolve()
    geo_path = Path(historical_geo).resolve() if historical_geo else None
    review_path = Path(accepted_review).resolve() if accepted_review else None
    if source_path == output_path:
        raise ValueError("Venue sidecar output must not overwrite the source serving DB")

    con = _open_read_only(source_path)
    try:
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
        }
        missing = {"canonical_subject", "dj_event"} - tables
        if missing:
            raise ValueError(f"Source serving DB is missing required tables: {', '.join(sorted(missing))}")
        quick_check = con.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RuntimeError(f"Source serving DB failed PRAGMA quick_check: {quick_check}")
        records = _load_records(con)
    finally:
        con.close()

    by_id = {record["venue_id"]: record for record in records}
    geo_aliases, geo_rows = _load_geo(geo_path)
    accepted_mappings, accepted_rows = _load_accepted_review(review_path)
    for record in records:
        record["geo"] = _lookup_geo(record, geo_aliases)

    union = UnionFind(list(by_id))
    accepted_edges: set[frozenset[str]] = set()
    review_rows: dict[tuple[str, str], dict] = {}

    def add_review(left: dict, right: dict, reason: str) -> None:
        if left["venue_id"] == right["venue_id"]:
            return
        target, source = sorted((left, right), key=_rank)
        key = (source["venue_id"], target["venue_id"])
        current = review_rows.get(key)
        candidate = {
            "source_venue_id": source["venue_id"],
            "candidate_venue_id": target["venue_id"],
            "city": source["city"] or target["city"],
            "source_name": source["name"],
            "candidate_name": target["name"],
            "reason": reason,
            "review_state": "needs_review",
        }
        if current is None or candidate["reason"] < current["reason"]:
            review_rows[key] = candidate

    by_city_core: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_core: dict[str, list[dict]] = defaultdict(list)
    by_name_key: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record["name_key"]:
            by_name_key[record["name_key"]].append(record)
        if record["core"]:
            by_core[record["core"]].append(record)
        if record["core"] and record["city_key"]:
            by_city_core[(record["city_key"], record["core"])].append(record)

    for members in by_city_core.values():
        safe_members = [member for member in members if not member["unsafe_boundary"]]
        for index, left in enumerate(safe_members):
            for right in safe_members[index + 1 :]:
                union.union(left["venue_id"], right["venue_id"])
        unsafe_members = [member for member in members if member["unsafe_boundary"]]
        if safe_members:
            target = sorted(safe_members, key=_rank)[0]
            for member in unsafe_members:
                add_review(member, target, "room_stage_or_compound_boundary")

    by_city_geo: dict[tuple[str, tuple[float, float]], list[dict]] = defaultdict(list)
    for record in records:
        if record["city_key"] and record["geo"]:
            by_city_geo[(record["city_key"], record["geo"])].append(record)
    for members in by_city_geo.values():
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                if left["unsafe_boundary"] or right["unsafe_boundary"]:
                    if _brand_compatible(left, right):
                        add_review(left, right, "room_stage_or_compound_boundary")
                    continue
                if _brand_compatible(left, right):
                    union.union(left["venue_id"], right["venue_id"])
                else:
                    add_review(left, right, "same_coordinate_without_brand_identity")

    forced_targets: dict[str, str] = {}
    for source_id, target_id in accepted_mappings:
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if source is None or target is None:
            raise ValueError(f"Accepted venue mapping references an unknown ID: {source_id} -> {target_id}")
        if not source["city_key"] or source["city_key"] != target["city_key"]:
            raise ValueError(f"Accepted venue mapping crosses city boundary: {source_id} -> {target_id}")
        if source["unsafe_boundary"] or target["unsafe_boundary"]:
            add_review(source, target, "accepted_mapping_hits_room_stage_boundary")
            continue
        union.union(source_id, target_id)
        accepted_edges.add(frozenset((source_id, target_id)))
        forced_targets[source_id] = target_id

    for core, members in by_core.items():
        if len(members) < 2:
            continue
        target = sorted(members, key=_rank)[0]
        for member in members:
            if member["city_key"] != target["city_key"]:
                add_review(member, target, "cross_city_exact_core")

    for members in by_name_key.values():
        if len({member["city_key"] for member in members if member["city_key"]}) < 2:
            continue
        target = sorted(members, key=_rank)[0]
        for member in members:
            if member["city_key"] != target["city_key"]:
                add_review(member, target, "cross_city_exact_name")

    by_city: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record["city_key"] and len(record["core"]) >= 3:
            by_city[record["city_key"]].append(record)
    for members in by_city.values():
        members = sorted(members, key=lambda row: (len(row["core"]), row["core"], row["venue_id"]))
        for index, short in enumerate(members):
            for longer in members[index + 1 :]:
                if not longer["core"].startswith(short["core"]):
                    continue
                if longer["core"] == short["core"] or union.find(longer["venue_id"]) == union.find(short["venue_id"]):
                    continue
                reason = (
                    "room_stage_or_compound_boundary"
                    if short["unsafe_boundary"] or longer["unsafe_boundary"]
                    else "prefix_core_requires_review"
                )
                add_review(short, longer, reason)

    components: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        components[union.find(record["venue_id"])].append(record)

    redirects: list[dict] = []
    decided_at = _timestamp([path for path in (source_path, geo_path, review_path) if path is not None])
    for members in components.values():
        if len(members) < 2:
            continue
        member_ids = {member["venue_id"] for member in members}
        forced = {
            target
            for source, target in forced_targets.items()
            if source in member_ids and target in member_ids
        }
        if len(forced) > 1:
            raise ValueError(f"Conflicting accepted canonical venue targets: {sorted(forced)}")
        target = by_id[next(iter(forced))] if forced else sorted(members, key=_rank)[0]
        for source in members:
            if source["venue_id"] == target["venue_id"]:
                continue
            pair = frozenset((source["venue_id"], target["venue_id"]))
            if pair in accepted_edges:
                method = "accepted_plan"
                confidence = 1.0
            elif source["core"] == target["core"]:
                method = "exact_core"
                confidence = 0.99
            else:
                method = "historical_geo_exact_core"
                confidence = 0.97
            redirects.append(
                {
                    "source_venue_id": source["venue_id"],
                    "source_city": source["city"],
                    "source_city_key": source["city_key"],
                    "canonical_venue_id": target["venue_id"],
                    "canonical_city": target["city"],
                    "canonical_city_key": target["city_key"],
                    "decision_method": method,
                    "decision_reason": (
                        "same_city_exact_core"
                        if method == "exact_core"
                        else "same_city_same_historical_geo_and_brand_compatible"
                        if method == "historical_geo_exact_core"
                        else "accepted_review_artifact"
                    ),
                    "confidence": confidence,
                    "decided_at": decided_at,
                }
            )

    redirects.sort(key=lambda row: row["source_venue_id"])
    redirect_map = {row["source_venue_id"]: row["canonical_venue_id"] for row in redirects}
    redirect_sources = set(redirect_map)
    redirects = [
        row for row in redirects if row["canonical_venue_id"] not in redirect_sources
    ]
    if any(row["canonical_venue_id"] in {item["source_venue_id"] for item in redirects} for row in redirects):
        raise RuntimeError("Venue redirect output contains a non-root target")

    normalized_reviews: dict[tuple[str, str], dict] = {}
    for row in review_rows.values():
        source_id = redirect_map.get(row["source_venue_id"], row["source_venue_id"])
        candidate_id = redirect_map.get(row["candidate_venue_id"], row["candidate_venue_id"])
        if source_id == candidate_id or row["source_venue_id"] in redirect_sources:
            continue
        normalized = {
            **row,
            "source_venue_id": source_id,
            "candidate_venue_id": candidate_id,
            "source_name": by_id[source_id]["name"],
            "candidate_name": by_id[candidate_id]["name"],
        }
        key = (source_id, candidate_id)
        current = normalized_reviews.get(key)
        if current is None or normalized["reason"] < current["reason"]:
            normalized_reviews[key] = normalized
    reviews = sorted(
        normalized_reviews.values(),
        key=lambda row: (row["source_venue_id"], row["candidate_venue_id"]),
    )
    input_rows = [
        {
            key: value
            for key, value in record.items()
            if key not in {"geo", "unsafe_boundary"}
        }
        for record in records
    ] + [{"kind": "geo", **row} for row in geo_rows] + [{"kind": "accepted", **row} for row in accepted_rows]
    classification_rows = [
        {key: value for key, value in row.items() if key != "decided_at"} for row in redirects
    ] + reviews
    input_digest = _digest(input_rows)
    classification_digest = _digest(classification_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "decision": "READY",
        "source_serving_db": str(source_path),
        "out_db": str(output_path),
        "historical_geo": str(geo_path) if geo_path else None,
        "accepted_review": str(review_path) if review_path else None,
        "quick_check": quick_check,
        "venue_ids": len(records),
        "canonical_subject_venues": sum(record["source_kind"] == "canonical_subject" for record in records),
        "event_only_venues": sum(record["source_kind"] == "dj_event_only" for record in records),
        "redirects": len(redirects),
        "exact_core_redirects": sum(row["decision_method"] == "exact_core" for row in redirects),
        "historical_geo_redirects": sum(
            row["decision_method"] == "historical_geo_exact_core" for row in redirects
        ),
        "accepted_plan_redirects": sum(row["decision_method"] == "accepted_plan" for row in redirects),
        "review_candidates": len(reviews),
        "city_scoped_redirects": len(redirects),
        "observed_city_ambiguous_redirects": sum(
            len(by_id[row["source_venue_id"]]["observed_city_keys"]) > 1
            or len(by_id[row["canonical_venue_id"]]["observed_city_keys"]) > 1
            for row in redirects
        ),
        "input_digest": input_digest,
        "classification_digest": classification_digest,
        "safety": {
            "source_opened_read_only": True,
            "source_mutated": False,
            "candidate_only": True,
            "cross_city_redirects_allowed": False,
            "room_stage_redirects_allowed": False,
            "redirects_require_matching_city_scope": True,
        },
    }
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "source_serving_db": str(source_path),
        "historical_geo": str(geo_path) if geo_path else "",
        "accepted_review": str(review_path) if review_path else "",
        "input_digest": input_digest,
        "classification_digest": classification_digest,
        "counts_json": json.dumps(
            {"venue_ids": len(records), "redirects": len(redirects), "reviews": len(reviews)},
            sort_keys=True,
            separators=(",", ":"),
        ),
        "decided_at": decided_at,
    }
    _write_output(output_path, redirects, reviews, metadata)
    if report_path is not None:
        report_file = Path(report_path).resolve()
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _self_check() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_venue_selfcheck_") as tmp:
        root = Path(tmp)
        source = root / "source.sqlite"
        con = sqlite3.connect(source)
        con.executescript(
            """
            CREATE TABLE canonical_subject(subject_id TEXT PRIMARY KEY,subject_type TEXT,display_name TEXT,normalized_name TEXT,city_primary TEXT,event_count INT);
            CREATE TABLE dj_event(dj_id TEXT,event_id TEXT,starts_at TEXT,venue_id TEXT,venue_name TEXT,city TEXT);
            INSERT INTO canonical_subject VALUES('venue:oil','venue','OIL','oil','深圳',100);
            INSERT INTO canonical_subject VALUES('venue:oilclub','venue','OIL俱乐部','oil俱乐部','深圳',20);
            """
        )
        con.close()
        out = root / "venue.sqlite"
        report = build_venue_redirects(source, out)
        assert report["redirects"] == 1, report
        check = sqlite3.connect(out)
        try:
            assert check.execute("SELECT canonical_venue_id FROM venue_identity_redirect").fetchone()[0] == "venue:oil"
        finally:
            check.close()
    print("self-check OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-serving-db", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--historical-geo", type=Path)
    parser.add_argument("--accepted-review", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        _self_check()
        return
    if args.source_serving_db is None or args.out is None:
        parser.error("--source-serving-db and --out are required unless --self-check is used")
    report = build_venue_redirects(
        args.source_serving_db,
        args.out,
        historical_geo=args.historical_geo,
        accepted_review=args.accepted_review,
        report_path=args.report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
