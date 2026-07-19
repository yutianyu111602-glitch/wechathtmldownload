#!/usr/bin/env python3
"""Export a mini-program-compatible atlas_index.json.gz from ATLAS v2.

Candidate-only: reads v2 + accepted Stage4 rollups/bio atoms + optional column.json,
and writes a gzip JSON bundle for the CloudRun miniappAtlasApi reader. It does not
touch the production CloudRun data directory unless explicitly pointed there.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
import tempfile
import time
from pathlib import Path

from atlas_dataset_identity import resolve_dataset_id


def norm_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").casefold())


def json_loads(value, fallback):
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def integer(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def clean_text(value: str | None, limit: int = 360) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def clean_social(value) -> dict:
    raw = json_loads(value, {}) if isinstance(value, str) else (value or {})
    if not isinstance(raw, dict):
        return {}
    empty = {"", "未提及", "未知", "未明确", "不详", "none", "null", "n/a", "na", "unknown"}
    out = {}
    for key, val in raw.items():
        text = clean_text(val, 240)
        if text.casefold() in empty:
            continue
        if text:
            out[str(key)] = text
    return out


def connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_column_enrichment(column_json: Path | None, name_to_djs: dict[str, set[str]], limit_per_dj: int = 6) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    if not column_json or not column_json.exists():
        return {}, {}
    data = json.loads(column_json.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return {}, {}
    out: dict[str, list[dict]] = {}
    social_by_dj: dict[str, dict] = {}
    social_keys = {
        "soundcloud": "soundcloud",
        "instagram": "instagram",
        "residentAdvisor": "resident_advisor",
        "resident_advisor": "resident_advisor",
        "ra": "resident_advisor",
        "mixcloud": "mixcloud",
        "bandcamp": "bandcamp",
        "spotify": "spotify",
        "website": "website",
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_names = str(item.get("djName") or item.get("artistName") or "")
        parts = [p for p in re.split(r"[/,，、|]+", raw_names) if p.strip()]
        matched = set()
        for part in parts:
            matched.update(name_to_djs.get(norm_key(part), set()))
        if not matched:
            continue
        row = {
            "id": clean_text(item.get("id"), 120),
            "t": clean_text(item.get("title"), 160),
            "s": clean_text(item.get("summary") or item.get("deck"), 260),
            "sr": clean_text(item.get("sourceRefId") or item.get("sourceDetailId") or item.get("sourceHash"), 160),
            "st": clean_text(item.get("sourceName") or item.get("toneSource"), 180),
            "p": clean_text(item.get("date") or item.get("publishedAt"), 40),
        }
        for dj_id in matched:
            bucket = out.setdefault(dj_id, [])
            if len(bucket) < limit_per_dj and not any(existing.get("id") == row["id"] for existing in bucket):
                bucket.append(row)
            social = social_by_dj.setdefault(dj_id, {})
            for src_key, dst_key in social_keys.items():
                value = clean_text(item.get(src_key), 240)
                if value and dst_key not in social:
                    social[dst_key] = value
    return out, social_by_dj


def _load_json_gz(path: Path) -> dict:
    raw = path.read_bytes()
    if str(path).endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def export_index(
    v2_path: Path,
    serving_path: Path,
    out_path: Path,
    column_json: Path | None = None,
    bio_serving_path: Path | None = None,
    bio_candidate_path: Path | None = None,
    links_candidate_path: Path | None = None,
    venue_merge_map_path: Path | None = None,
    dataset_id: str | None = None,
) -> dict:
    resolved_dataset_id = resolve_dataset_id(v2_path, dataset_id)
    v2 = connect_ro(v2_path)
    serving = connect_ro(serving_path)
    bio_serving = connect_ro(bio_serving_path or serving_path)
    venue_mm: dict[str, str] = {}
    if venue_merge_map_path and venue_merge_map_path.exists():
        venue_mm = json.loads(venue_merge_map_path.read_text(encoding="utf-8")).get("merge_map", {})

    def cv(vid):
        return venue_mm.get(vid, vid) if vid else vid

    try:
        subjects = []
        subject_names = {}
        dj_ids = set()
        name_to_djs: dict[str, set[str]] = {}
        for row in v2.execute(
            "SELECT subject_id, subject_type, display_name, normalized_name, aliases_json, "
            "city_primary, event_count, relation_count FROM subject ORDER BY subject_id"
        ):
            aliases = json_loads(row["aliases_json"], [])
            if not isinstance(aliases, list):
                aliases = []
            subject = {
                "i": row["subject_id"],
                "t": row["subject_type"],
                "n": row["display_name"],
                "nn": row["normalized_name"],
                "a": aliases,
                "c": row["city_primary"] or "",
                "ec": integer(row["event_count"]),
            }
            subjects.append(subject)
            subject_names[row["subject_id"]] = row["display_name"]
            if row["subject_type"] == "dj":
                dj_ids.add(row["subject_id"])
                for name in [row["display_name"], row["normalized_name"], *aliases]:
                    key = norm_key(name)
                    if key:
                        name_to_djs.setdefault(key, set()).add(row["subject_id"])

        bio_atoms: dict[str, list[dict]] = {}
        if "dj_bio_atom" in {r[0] for r in bio_serving.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            for row in bio_serving.execute(
                "SELECT dj_id, source_ref_id, source_title, language, bio_text_raw, confidence "
                "FROM dj_bio_atom ORDER BY dj_id, confidence DESC, length(bio_text_raw) DESC"
            ):
                dj_id = row["dj_id"]
                if dj_id not in dj_ids:
                    continue
                bucket = bio_atoms.setdefault(dj_id, [])
                if len(bucket) >= 4:
                    continue
                text = clean_text(row["bio_text_raw"], 420)
                if len(text) < 36:
                    continue
                bucket.append({
                    "t": text,
                    "sr": row["source_ref_id"] or "",
                    "st": row["source_title"] or "",
                    "lang": row["language"] or "",
                    "cf": float(row["confidence"] or 0),
                })

        related_columns, column_social = load_column_enrichment(column_json, name_to_djs)

        profiles = {}
        for row in v2.execute(
            "SELECT s.subject_id, s.display_name, s.normalized_name, s.aliases_json, s.city_primary, "
            "s.event_count, s.relation_count, s.first_seen_at, s.last_seen_at, "
            "p.social_json, p.bio_snippet, p.venue_count "
            "FROM subject s JOIN dj_profile p ON p.subject_id=s.subject_id "
            "WHERE s.subject_type='dj' ORDER BY s.subject_id"
        ):
            profile = {
                "n": row["display_name"],
                "c": row["city_primary"] or "",
                "ec": integer(row["event_count"]),
                "vc": integer(row["venue_count"]),
                "cc": integer(row["relation_count"]),
                "fs": row["first_seen_at"] or "",
                "ls": row["last_seen_at"] or "",
                "b": clean_text(row["bio_snippet"], 420),
                "bs": "atlas_serving_v2.bio_snippet" if row["bio_snippet"] else "",
            }
            social = clean_social(row["social_json"])
            social.update({k: v for k, v in clean_social(column_social.get(row["subject_id"], {})).items() if k not in social})
            if social:
                profile["s"] = social
            profiles[row["subject_id"]] = profile

        # Optional candidate enrichment (additive; no-op when paths absent).
        # bio: fill only when the v2 profile has no bio_snippet (never override the
        # curated 4164). links: attach classified external links under "x".
        bio_candidate_filled = 0
        if bio_candidate_path:
            cand_bios = _load_json_gz(bio_candidate_path).get("bios", {})
            for sid, profile in profiles.items():
                if profile.get("b"):
                    continue
                entry = cand_bios.get(sid)
                if entry and entry.get("bio"):
                    profile["b"] = clean_text(entry["bio"], 420)
                    profile["bs"] = "dj_bio_snippet_candidate"
                    bio_candidate_filled += 1
        external_link_djs = 0
        if links_candidate_path:
            cand_links = _load_json_gz(links_candidate_path).get("djLinks", {})
            for sid, profile in profiles.items():
                items = cand_links.get(sid)
                if items:
                    profile["x"] = [
                        {"u": e["url"], "p": e["platform"], "r": e["role"], "l": e.get("label", "")}
                        for e in items
                    ]
                    external_link_djs += 1

        source_refs = {}
        for row in serving.execute("SELECT source_ref_id, source_hash, source_account, source_title, post_date, source_kind FROM evidence_ref"):
            rid = row["source_ref_id"] or ""
            if not rid:
                continue
            source_refs[rid] = {
                "h": row["source_hash"] or "",
                "a": row["source_account"] or "",
                "t": row["source_title"] or "",
                "p": row["post_date"] or "",
                "k": row["source_kind"] or "",
            }

        events: dict[str, list[dict]] = {}
        seen_events: dict[str, set[tuple]] = {}
        for row in serving.execute(
            "SELECT dj_id,event_id,starts_at,event_title,venue_id,venue_name,city,source_ref_id "
            "FROM dj_event ORDER BY dj_id, starts_at DESC, event_id"
        ):
            dj_id = row["dj_id"]
            if dj_id not in dj_ids:
                continue
            bucket = events.setdefault(dj_id, [])
            if len(bucket) >= 100:
                continue
            key = (row["event_title"] or "", row["starts_at"] or "", row["venue_id"] or "")
            seen = seen_events.setdefault(dj_id, set())
            if key in seen:
                continue
            seen.add(key)
            item = {
                "eid": row["event_id"],
                "t": row["event_title"],
                "d": row["starts_at"] or "",
                "v": row["venue_name"] or "",
                "vi": cv(row["venue_id"] or ""),
                "ci": row["city"] or "",
            }
            if row["source_ref_id"]:
                item["sr"] = row["source_ref_id"]
            bucket.append(item)

        # dj_venues: aggregate by canonical venue (fold merged venue_ids), keep top 20 by events
        dj_venues_acc: dict[str, dict[str, dict]] = {}
        for row in serving.execute("SELECT dj_id,venue_id,venue_name,city,event_count FROM dj_venue_rollup ORDER BY dj_id, event_count DESC"):
            dj_id = row["dj_id"]
            if dj_id not in dj_ids:
                continue
            cvid = cv(row["venue_id"])
            acc = dj_venues_acc.setdefault(dj_id, {})
            if cvid in acc:
                acc[cvid]["ec"] += integer(row["event_count"])
            elif len(acc) < 20:
                acc[cvid] = {"vn": subject_names.get(cvid, row["venue_name"]), "ec": integer(row["event_count"]), "vi": cvid}
        dj_venues: dict[str, list[dict]] = {
            dj: sorted(v.values(), key=lambda x: -x["ec"]) for dj, v in dj_venues_acc.items()
        }

        collabs: dict[str, list[dict]] = {}
        for row in serving.execute(
            "SELECT src_dj_id,dst_dj_id,same_event_count FROM dj_relation_rollup "
            "ORDER BY src_dj_id, same_event_count DESC, relation_score DESC"
        ):
            src = row["src_dj_id"]
            dst = row["dst_dj_id"]
            if src not in dj_ids or dst not in dj_ids:
                continue
            bucket = collabs.setdefault(src, [])
            if len(bucket) < 30:
                bucket.append({"di": dst, "n": subject_names.get(dst, dst), "ec": integer(row["same_event_count"])})

        venue_events: dict[str, list[dict]] = {}
        venue_by_name: dict[str, set[str]] = {}
        vseen = set()
        for row in serving.execute(
            "SELECT venue_id,event_id,event_title,starts_at,venue_name,city,dj_id,source_ref_id "
            "FROM dj_event WHERE COALESCE(venue_id,'')<>'' ORDER BY starts_at DESC, event_id"
        ):
            vid = cv(row["venue_id"])
            if vid not in subject_names:
                continue
            bucket = venue_events.setdefault(vid, [])
            key = (row["event_id"], vid, row["dj_id"])
            if len(bucket) < 200 and key not in vseen:
                vseen.add(key)
                item = {"eid": row["event_id"], "t": row["event_title"], "d": row["starts_at"] or "", "di": row["dj_id"], "ci": row["city"] or ""}
                if row["source_ref_id"]:
                    item["sr"] = row["source_ref_id"]
                bucket.append(item)
            nk = norm_key(row["venue_name"])
            if nk:
                venue_by_name.setdefault(nk, set()).add(vid)

        payload = {
            "v": 5,
            "datasetId": resolved_dataset_id,
            "subjects": subjects,
            "profiles": profiles,
            "events": events,
            "dj_venues": dj_venues,
            "venue_events": venue_events,
            "venue_by_name": {key: sorted(values) for key, values in venue_by_name.items()},
            "collabs": collabs,
            "source_refs": source_refs,
            "bio_atoms": bio_atoms,
            "related_columns": related_columns,
            "meta": {
                "generation": "g1_g7_full_semantic_filtered",
                "candidate_only": True,
                "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(
            gzip.compress(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                compresslevel=9,
                mtime=0,
            )
        )
        manifest = {
            "decision": "atlas_v2_miniapp_index_candidate_ready",
            "datasetId": resolved_dataset_id,
            "artifact": out_path.name,
            "production_db_write_executed": False,
            "counts": {
                "subjects": len(subjects),
                "profiles": len(profiles),
                "events_dj_keys": len(events),
                "bio_atom_dj_keys": len(bio_atoms),
                "related_column_dj_keys": len(related_columns),
                "source_refs": len(source_refs),
                "bio_candidate_filled": bio_candidate_filled,
                "external_link_djs": external_link_djs,
            },
        }
        out_path.with_suffix(out_path.suffix + ".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest
    finally:
        v2.close()
        serving.close()
        bio_serving.close()


def _selftest() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_v2_miniapp_index_") as tmp:
        root = Path(tmp)
        v2 = root / "v2.sqlite"
        serving = root / "serving.sqlite"
        bio_serving = root / "bio_serving.sqlite"
        column = root / "column.json"
        out = root / "atlas_index.json.gz"
        con = sqlite3.connect(v2)
        con.executescript(
            """
            CREATE TABLE subject(subject_id TEXT,subject_type TEXT,display_name TEXT,normalized_name TEXT,name_en TEXT,aliases_json TEXT,city_primary TEXT,event_count INT,relation_count INT,source_count INT,confidence REAL,first_seen_at TEXT,last_seen_at TEXT,taxon_path TEXT,public_state TEXT);
            CREATE TABLE dj_profile(subject_id TEXT PRIMARY KEY,name_en TEXT,nationality TEXT,origin_city TEXT,roles_json TEXT,styles_json TEXT,genre TEXT,social_json TEXT,gear TEXT,bio_snippet TEXT,affiliations_json TEXT,venue_count INT,org_count INT);
            CREATE TABLE relation(relation_id TEXT,src_subject_id TEXT,dst_subject_id TEXT,relation_type TEXT,weight REAL,same_event_count INT,b2b_count INT,label_zh TEXT,first_seen_at TEXT,last_seen_at TEXT,public_state TEXT,sample_evidence_json TEXT);
            INSERT INTO subject VALUES('dj:alpha','dj','Alpha','alpha',NULL,'["A"]','深圳',2,1,1,1,'2026-01-01','2026-01-02','atlas/dj','public');
            INSERT INTO subject VALUES('dj:beta','dj','Beta','beta',NULL,'[]','上海',1,0,1,1,'2026-01-01','2026-01-02','atlas/dj','public');
            INSERT INTO subject VALUES('venue:oil','venue','OIL','oil',NULL,'[]','深圳',1,1,1,1,'2026-01-01','2026-01-02','atlas/venue','public');
            INSERT INTO dj_profile VALUES('dj:alpha',NULL,NULL,NULL,NULL,NULL,NULL,'{"soundcloud":"https://soundcloud.example/a","instagram":"未提及"}',NULL,'Alpha bio',NULL,1,0);
            INSERT INTO dj_profile VALUES('dj:beta',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,0);
            """
        )
        con.close()
        con = sqlite3.connect(serving)
        con.executescript(
            """
            CREATE TABLE evidence_ref(source_ref_id TEXT,source_hash TEXT,source_account TEXT,source_title TEXT,post_date TEXT,public_snippet TEXT,source_kind TEXT,public_url_allowed INT);
            CREATE TABLE dj_event(dj_id TEXT,event_id TEXT,starts_at TEXT,time_text TEXT,event_title TEXT,venue_id TEXT,venue_name TEXT,city TEXT,source_ref_id TEXT,confidence REAL);
            CREATE TABLE dj_venue_rollup(dj_id TEXT,venue_id TEXT,venue_name TEXT,city TEXT,event_count INT,first_seen_at TEXT,last_seen_at TEXT,score REAL);
            CREATE TABLE dj_relation_rollup(src_dj_id TEXT,dst_dj_id TEXT,same_event_count INT,same_label_count INT,same_venue_count INT,same_source_context_count INT,b2b_count INT,source_diversity INT,first_seen_at TEXT,last_seen_at TEXT,relation_score REAL,relation_label_zh TEXT,sample_evidence_json TEXT,public_state TEXT);
            INSERT INTO evidence_ref VALUES('src:a','hash-a','Club A','Alpha source','2026-01-01','snippet','article',0);
            INSERT INTO dj_event VALUES('dj:alpha','event:a','2026-01-02','','Alpha Night','venue:oil','OIL','深圳','src:a',0.9);
            INSERT INTO dj_venue_rollup VALUES('dj:alpha','venue:oil','OIL','深圳',1,'2026-01-01','2026-01-02',1.0);
            """
        )
        con.close()
        con = sqlite3.connect(bio_serving)
        con.executescript(
            """
            CREATE TABLE dj_bio_atom(bio_atom_id TEXT,dj_id TEXT,dj_surface TEXT,source_token TEXT,source_ref_id TEXT,source_account TEXT,source_title TEXT,language TEXT,bio_text_raw TEXT,start_char INT,end_char INT,section_heading TEXT,extraction_method TEXT,confidence REAL,source_text_sha1 TEXT);
            INSERT INTO dj_bio_atom VALUES('bio:a','dj:alpha','Alpha','tok','src:a','Club A','Alpha source','en','Alpha is a DJ and producer with a source-backed profile paragraph.',1,80,'bio','test',0.99,'sha');
            """
        )
        con.close()
        column.write_text(json.dumps({"items": [{"id": "col:a", "title": "Alpha column", "djName": "Alpha / A", "summary": "Column summary", "date": "2026-01-03", "bandcamp": "https://alpha.bandcamp.com"}]}), encoding="utf-8")
        bio_cand = root / "bio_cand.json.gz"
        links_cand = root / "links_cand.json.gz"
        bio_cand.write_bytes(gzip.compress(json.dumps({"bios": {
            "dj:beta": {"bio": "Beta is a techno producer based in Shanghai."},
            "dj:alpha": {"bio": "should not override the curated bio"},
        }}).encode("utf-8")))
        links_cand.write_bytes(gzip.compress(json.dumps({"djLinks": {
            "dj:alpha": [{"url": "https://soundcloud.com/alpha", "platform": "soundcloud", "role": "listen", "label": "SC"}],
        }}).encode("utf-8")))
        test_dataset_id = "atlas-selftest-shared-generation-0001"
        report = export_index(
            v2,
            serving,
            out,
            column,
            bio_serving,
            bio_cand,
            links_cand,
            dataset_id=test_dataset_id,
        )
        payload = json.loads(gzip.decompress(out.read_bytes()).decode("utf-8"))
        assert report["counts"]["profiles"] == 2
        assert report["datasetId"] == payload["datasetId"]
        assert payload["datasetId"] == test_dataset_id
        assert resolve_dataset_id(v2).startswith("atlas-sha256-")
        assert str(root) not in json.dumps(payload, ensure_ascii=False)
        assert not any(key.startswith("source_") for key in payload["meta"])
        assert payload["profiles"]["dj:alpha"]["s"]["soundcloud"] == "https://soundcloud.example/a"
        assert payload["profiles"]["dj:alpha"]["s"]["bandcamp"] == "https://alpha.bandcamp.com"
        assert payload["bio_atoms"]["dj:alpha"][0]["sr"] == "src:a"
        assert payload["related_columns"]["dj:alpha"][0]["id"] == "col:a"
        # candidate enrichment: beta gets backfilled bio; alpha's curated bio is NOT overridden; links attach
        assert payload["profiles"]["dj:beta"]["b"].startswith("Beta is a techno"), payload["profiles"]["dj:beta"]
        assert payload["profiles"]["dj:beta"]["bs"] == "dj_bio_snippet_candidate"
        assert payload["profiles"]["dj:alpha"]["b"] == "Alpha bio", "must not override existing bio"
        assert payload["profiles"]["dj:alpha"]["x"][0]["u"] == "https://soundcloud.com/alpha"
        assert report["counts"]["bio_candidate_filled"] == 1, report["counts"]
        assert report["counts"]["external_link_djs"] == 1, report["counts"]
    print("selftest OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v2", type=Path, default=Path("_sandbox_v2_semantic_filtered_20260621/atlas_serving_v2.sqlite"))
    ap.add_argument("--serving", type=Path, default=Path("_fleet_14w_g1_g7_full_union_fast2_retry_20260621/merged/atlas_serving_candidate.sqlite"))
    ap.add_argument("--bio-serving", type=Path, default=None)
    ap.add_argument("--bio-candidate", type=Path, default=None, help="dj_bio_snippet_candidate.json[.gz] to backfill empty bios")
    ap.add_argument("--links-candidate", type=Path, default=None, help="dj_external_links_candidate.json[.gz] to attach external links")
    ap.add_argument("--venue-merge-map", type=Path, default=None, help="*.venue_merge_map.json to remap merged venue_ids in event/venue refs")
    ap.add_argument("--column-json", type=Path, default=Path("../../services/weekly_activity_cloudrun/data/current_release/column.json"))
    ap.add_argument("--out", type=Path, default=Path("_sandbox_v2_semantic_filtered_20260621/atlas_index.json.gz"))
    ap.add_argument("--dataset-id", help="Shared public ATLAS generation id; defaults to the v2 DB SHA256")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
        return
    report = export_index(
        args.v2,
        args.serving,
        args.out,
        args.column_json,
        args.bio_serving,
        args.bio_candidate,
        args.links_candidate,
        args.venue_merge_map,
        args.dataset_id,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
