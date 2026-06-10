from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from atlas_core_common import connect_readonly, integer, json_loads, row_count, text, write_gzip_json, write_json, json_dumps  # noqa: E402


def norm_key(value: str) -> str:
    return " ".join(text(value).casefold().split())


def export_index(miniapp_db: Path, out: Path) -> dict[str, Any]:
    conn = connect_readonly(miniapp_db)
    try:
        subjects = []
        for row in conn.execute("SELECT subject_id, subject_type, display_name, normalized_name, aliases_json, city_primary, event_count FROM subject ORDER BY subject_id"):
            aliases = json_loads(row["aliases_json"], [])
            if not isinstance(aliases, list):
                aliases = []
            subjects.append(
                {
                    "i": row["subject_id"],
                    "t": row["subject_type"],
                    "n": row["display_name"],
                    "nn": row["normalized_name"],
                    "a": aliases,
                    "c": row["city_primary"] or "",
                    "ec": integer(row["event_count"]),
                }
            )

        profiles = {}
        for row in conn.execute("SELECT * FROM dj_profile ORDER BY dj_id"):
            profiles[row["dj_id"]] = {
                "n": row["display_name"],
                "c": row["city_primary"] or "",
                "ec": integer(row["event_count"]),
                "vc": integer(row["venue_count"]),
                "cc": integer(row["collaborator_count"]),
                "fs": row["first_seen_at"] or "",
                "ls": row["last_seen_at"] or "",
                "b": row["bio"] or "",
                "bs": row["bio_source"] or "",
            }

        source_refs = {}
        for row in conn.execute("SELECT source_ref_id, source_hash, source_account, source_title, post_date, source_kind FROM source_ref ORDER BY source_ref_id"):
            rid = text(row["source_ref_id"])
            if not rid:
                continue
            source_refs[rid] = {
                "h": row["source_hash"] or "",
                "a": row["source_account"] or "",
                "t": row["source_title"] or "",
                "p": row["post_date"] or "",
                "k": row["source_kind"] or "",
            }

        events = {}
        seen_by_dj = {}
        for row in conn.execute("SELECT * FROM dj_event ORDER BY starts_at DESC, event_id"):
            dj = row["dj_id"]
            events.setdefault(dj, [])
            seen_by_dj.setdefault(dj, set())
            if len(events[dj]) >= 100:
                continue
            key = (row["event_title"] or "", row["starts_at"] or "", row["venue_id"] or "")
            if key in seen_by_dj[dj]:
                continue
            seen_by_dj[dj].add(key)
            item = {
                "eid": row["event_id"],
                "t": row["event_title"],
                "d": row["starts_at"] or "",
                "v": row["venue_name"] or "",
                "vi": row["venue_id"] or "",
                "ci": row["city"] or "",
            }
            if row["source_ref_id"]:
                item["sr"] = row["source_ref_id"]
            events[dj].append(item)

        dj_venues = {}
        for row in conn.execute("SELECT * FROM dj_venue ORDER BY event_count DESC, venue_name"):
            dj = row["dj_id"]
            dj_venues.setdefault(dj, [])
            if len(dj_venues[dj]) < 20:
                dj_venues[dj].append({"vn": row["venue_name"], "ec": integer(row["event_count"]), "vi": row["venue_id"]})

        venue_events = {}
        venue_by_name: dict[str, set[str]] = {}
        vseen = set()
        for row in conn.execute("SELECT venue_id, event_id, event_title, starts_at, venue_name, city, dj_id, source_ref_id FROM dj_event WHERE COALESCE(venue_id, '') <> '' ORDER BY starts_at DESC"):
            vid = row["venue_id"]
            venue_events.setdefault(vid, [])
            if len(venue_events[vid]) < 200:
                key = (row["event_id"], vid)
                if key not in vseen:
                    vseen.add(key)
                    item = {"eid": row["event_id"], "t": row["event_title"], "d": row["starts_at"] or "", "di": row["dj_id"], "ci": row["city"] or ""}
                    if row["source_ref_id"]:
                        item["sr"] = row["source_ref_id"]
                    venue_events[vid].append(item)
            name_key = norm_key(row["venue_name"] or "")
            if name_key:
                venue_by_name.setdefault(name_key, set()).add(vid)

        for subject in subjects:
            if subject["t"] in {"venue", "org", "radio", "organizer"} and subject["n"]:
                key = norm_key(subject["n"])
                if key in venue_by_name:
                    venue_by_name[key].add(subject["i"])
                    for vid in list(venue_by_name[key]):
                        if vid in venue_events and subject["i"] not in venue_events:
                            venue_events[subject["i"]] = venue_events[vid]

        collabs = {}
        subject_names = {row["subject_id"]: row["display_name"] for row in conn.execute("SELECT subject_id, display_name FROM subject")}
        for row in conn.execute("SELECT * FROM dj_collaborator ORDER BY same_event_count DESC, relation_score DESC"):
            dj = row["src_dj_id"]
            collabs.setdefault(dj, [])
            if len(collabs[dj]) >= 30:
                continue
            if any(item["di"] == row["dst_dj_id"] for item in collabs[dj]):
                continue
            collabs[dj].append({"di": row["dst_dj_id"], "n": subject_names.get(row["dst_dj_id"], row["dst_dj_id"]), "ec": integer(row["same_event_count"])})

        payload = {
            "v": 4,
            "subjects": subjects,
            "profiles": profiles,
            "events": events,
            "dj_venues": dj_venues,
            "venue_events": venue_events,
            "venue_by_name": {key: sorted(values) for key, values in venue_by_name.items()},
            "collabs": collabs,
            "source_refs": source_refs,
        }
        write_gzip_json(out, payload)
        report = {
            "decision": "atlas_core_miniapp_index_export_ready_candidate",
            "miniapp_db": str(miniapp_db),
            "out": str(out),
            "counts": {
                "subjects": len(subjects),
                "profiles": len(profiles),
                "events_dj_keys": len(events),
                "source_refs": len(source_refs),
                "sqlite_dj_event": row_count(conn, "dj_event"),
            },
            "production_db_write_executed": False,
        }
        write_json(out.with_suffix(out.suffix + ".manifest.json"), report)
        return report
    finally:
        conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export candidate atlas_index.json.gz from atlas_miniapp.sqlite.")
    parser.add_argument("--miniapp-db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    return export_index(args.miniapp_db, args.out)


if __name__ == "__main__":
    print(json_dumps(main()))
