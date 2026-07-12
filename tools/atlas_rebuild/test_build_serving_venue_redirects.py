#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from build_serving_venue_redirects import build_venue_redirects


def build_fixture(root: Path, venues: list[tuple[str, str, str, int]], events: list[tuple] | None = None) -> Path:
    source = root / "source.sqlite"
    con = sqlite3.connect(source)
    con.executescript(
        """
        CREATE TABLE canonical_subject (
          subject_id TEXT PRIMARY KEY,
          subject_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          city_primary TEXT,
          event_count INTEGER NOT NULL
        );
        CREATE TABLE dj_event (
          dj_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          starts_at TEXT,
          venue_id TEXT,
          venue_name TEXT,
          city TEXT,
          PRIMARY KEY (dj_id,event_id)
        );
        """
    )
    con.executemany(
        "INSERT INTO canonical_subject VALUES (?, 'venue', ?, lower(?), ?, ?)",
        [(venue_id, name, name, city, event_count) for venue_id, name, city, event_count in venues],
    )
    if events:
        con.executemany("INSERT INTO dj_event VALUES (?,?,?,?,?,?)", events)
    con.commit()
    con.close()
    return source


def write_geo(root: Path, rows: dict[str, tuple[float, float]]) -> Path:
    path = root / "historical_venue_geo.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "weekly_venue_geo_registry.v1",
                "venues": {
                    key: {"name": key, "geo_lat": coords[0], "geo_lng": coords[1]}
                    for key, coords in rows.items()
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def read_redirects(path: Path) -> dict[str, str]:
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT source_venue_id,canonical_venue_id FROM venue_identity_redirect"))
    finally:
        con.close()


def read_redirect_scope(path: Path, source_venue_id: str) -> str | None:
    con = sqlite3.connect(path)
    try:
        row = con.execute(
            "SELECT source_city_key FROM venue_identity_redirect WHERE source_venue_id=?",
            (source_venue_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


class ServingVenueRedirectTests(unittest.TestCase):
    def test_same_city_exact_core_merges_without_geo(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_venue_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                [
                    ("venue:oil", "OIL", "深圳", 100),
                    ("venue:oilclub", "OIL俱乐部", "深圳", 20),
                ],
            )
            out = root / "venue_identity.sqlite"

            report = build_venue_redirects(source, out)

            self.assertEqual(read_redirects(out), {"venue:oilclub": "venue:oil"})
            self.assertEqual(report["exact_core_redirects"], 1)

    def test_same_city_geo_alias_merges_vervo_names(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_venue_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                [
                    ("venue:a", "VERVO CLUB", "昆明", 100),
                    ("venue:b", "VERVO国际独立电音俱乐部", "昆明", 50),
                ],
            )
            geo = write_geo(
                root,
                {
                    "vervo": (25.040556, 102.709282),
                    "vervo国际独立电音俱乐部": (25.040556, 102.709282),
                },
            )
            out = root / "venue_identity.sqlite"

            report = build_venue_redirects(source, out, historical_geo=geo)

            self.assertEqual(read_redirects(out), {"venue:b": "venue:a"})
            self.assertEqual(read_redirect_scope(out, "venue:b"), "昆明")
            self.assertEqual(report["historical_geo_redirects"], 1)

    def test_cross_city_name_collision_does_not_merge(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_venue_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                [
                    ("venue:a", "SPACE", "成都", 100),
                    ("venue:b", "SPACE", "上海", 50),
                ],
            )
            out = root / "venue_identity.sqlite"

            report = build_venue_redirects(source, out)

            self.assertEqual(read_redirects(out), {})
            self.assertGreaterEqual(report["review_candidates"], 1)

    def test_room_or_stage_variant_is_review_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_venue_test_") as tmp:
            root = Path(tmp)
            source = build_fixture(
                root,
                [
                    ("venue:a", "VERVO CLUB", "昆明", 100),
                    ("venue:b", "VERVO CLUB BLACK ROOM", "昆明", 20),
                ],
            )
            geo = write_geo(root, {"vervo": (25.040556, 102.709282)})
            out = root / "venue_identity.sqlite"

            report = build_venue_redirects(source, out, historical_geo=geo)

            self.assertEqual(read_redirects(out), {})
            self.assertGreaterEqual(report["review_candidates"], 1)

    def test_maxxi_vervo_timeline_collapses_to_one_bucket(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atlas_venue_test_") as tmp:
            root = Path(tmp)
            venues = [
                ("venue:vervo", "VERVO CLUB", "昆明", 100),
                ("venue:vervo-cn", "VERVO国际独立电音俱乐部", "昆明", 50),
                ("venue:vervo-guess", "VERVO国际独立电音俱乐部(推测)", "昆明", 1),
                ("venue:vervo-city-a", "VERVO CLUB(昆明)", "昆明", 10),
                ("venue:vervo-city-b", "VERVO CLUB (昆明)", "昆明", 9),
            ]
            events = [
                ("dj:maxxi", f"event:{index}", "2026-05-02", venue_id, name, "昆明")
                for index, (venue_id, name, _city, _count) in enumerate(venues)
            ]
            source = build_fixture(root, venues, events)
            geo = write_geo(
                root,
                {
                    "vervo": (25.040556, 102.709282),
                    "vervo国际独立电音俱乐部": (25.040556, 102.709282),
                    "vervo昆明": (25.040556, 102.709282),
                },
            )
            out = root / "venue_identity.sqlite"

            build_venue_redirects(source, out, historical_geo=geo)
            redirects = read_redirects(out)
            timeline_keys = {
                ("2026-05-02", redirects.get(venue_id, venue_id))
                for venue_id, _name, _city, _count in venues
            }

            self.assertEqual(timeline_keys, {("2026-05-02", "venue:vervo")})


if __name__ == "__main__":
    unittest.main()
