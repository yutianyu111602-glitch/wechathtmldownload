#!/usr/bin/env python3
"""Merge a Stage4 shard candidate (new Sanji articles only) into a COPY of the base serving DB.

Phase 4 building block of the Atlas v2 dedupe/freshness design
(`C:\\code\\mavelpoint-cn-v2\\docs\\site-clone\\ATLAS_V2_DEDUP_SANJI_AUTOMATION_DEEP_DESIGN_2026-07-06.md`).

`stage4_rollup.py`'s output schema is column-for-column identical to the base serving DB
for the four tables this pipeline actually reads (`performance_event`, `dj_event`,
`evidence_ref`, `dj_profile`), so merging is a plain `INSERT OR IGNORE` keyed on each
table's own primary key — no schema translation needed. Deliberately NOT merged:
`dj_relation_rollup` / `dj_venue_rollup` / `dj_org_rollup` / `canonical_subject` /
`search_document` — those serve search/relations elsewhere in the system and need their
own incremental-aggregate logic. Any canonical projection copied from the base is stale
after this operation and must be rebuilt before the candidate can be promoted.

The merge also writes an incoming-identity manifest from the shard's `dj_profile` rows.
That preserves whether each identity was already present in the base/canonical projection
before `INSERT OR IGNORE` makes the distinction harder to audit.

Never touches the base DB in place: copies it to `--out` first, then merges into the copy.

Usage:
  python merge_stage4_shard_into_base.py --base-serving-db <base.sqlite> --shard-db <shard.sqlite> --out <merged.sqlite>
  python merge_stage4_shard_into_base.py --self-check
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE7_SCRIPTS = REPO_ROOT / "tools" / "stage7_rewrite" / "scripts"
if str(STAGE7_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(STAGE7_SCRIPTS))

from build_atlas_dj_first_canary import now_iso, write_json  # noqa: E402

MERGED_TABLES = ("performance_event", "dj_event", "evidence_ref", "dj_profile")
FORBIDDEN_OUTPUT_MARKERS = (
    "appdata\\roaming\\sanji",
    "appdata/roaming/sanji",
    "appdata\\local\\hermes",
    "appdata/local/hermes",
)


def assert_output_boundaries(base_db: Path, out_db: Path) -> None:
    if base_db.resolve() == out_db.resolve():
        raise SystemExit("refusing to run: --out must not be the same path as --base-serving-db (never merge in place)")
    out_str = str(out_db.resolve()).lower()
    for marker in FORBIDDEN_OUTPUT_MARKERS:
        if marker in out_str:
            raise SystemExit(f"refusing to run: output path looks like a Sanji/Hermes path ({marker})")


def _table_exists(conn: sqlite3.Connection, schema: str, table: str) -> bool:
    return conn.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _incoming_identity_manifest(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "shard", "dj_profile"):
        return {"rows": [], "counts": {"shard_profiles": 0, "new_to_base": 0, "not_in_canonical": 0}}

    shard_columns = {
        row[1] for row in conn.execute("PRAGMA shard.table_info('dj_profile')").fetchall()
    }
    fields = ("dj_id", "display_name", "normalized_name", "city_primary")
    select_fields = [field if field in shard_columns else f"'' AS {field}" for field in fields]
    shard_rows = conn.execute(
        f"SELECT {', '.join(select_fields)} FROM shard.dj_profile ORDER BY dj_id"
    ).fetchall()
    base_ids = {row[0] for row in conn.execute("SELECT dj_id FROM main.dj_profile").fetchall()}

    if _table_exists(conn, "main", "canonical_dj_profile"):
        canonical_ids = {
            row[0] for row in conn.execute("SELECT dj_id FROM main.canonical_dj_profile").fetchall()
        }
    elif _table_exists(conn, "main", "canonical_subject"):
        canonical_ids = {
            row[0]
            for row in conn.execute(
                "SELECT subject_id FROM main.canonical_subject WHERE subject_type='dj'"
            ).fetchall()
        }
    else:
        canonical_ids = set()

    rows = [
        {
            "dj_id": str(row[0] or ""),
            "display_name": str(row[1] or ""),
            "normalized_name": str(row[2] or ""),
            "city_primary": str(row[3] or ""),
            "was_in_base": row[0] in base_ids,
            "was_canonical_subject": row[0] in canonical_ids,
        }
        for row in shard_rows
    ]
    return {
        "rows": rows,
        "counts": {
            "shard_profiles": len(rows),
            "new_to_base": sum(not row["was_in_base"] for row in rows),
            "not_in_canonical": sum(not row["was_canonical_subject"] for row in rows),
        },
    }


def merge(
    base_db: Path,
    shard_db: Path,
    out_db: Path,
    identity_manifest_path: Path | None = None,
) -> dict[str, Any]:
    assert_output_boundaries(base_db, out_db)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(base_db, out_db)

    conn = sqlite3.connect(str(out_db))
    conn.execute("ATTACH DATABASE ? AS shard", (str(shard_db),))

    shard_tables = {
        row[0] for row in conn.execute("SELECT name FROM shard.sqlite_master WHERE type='table'").fetchall()
    }
    identity_manifest = _incoming_identity_manifest(conn)

    inserted: dict[str, int] = {}
    for table in MERGED_TABLES:
        if table not in shard_tables:
            inserted[table] = 0
            continue
        before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        conn.execute(f"INSERT OR IGNORE INTO {table} SELECT * FROM shard.{table}")
        after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        inserted[table] = after - before

    base_generated_at = conn.execute("SELECT value FROM build_metadata WHERE key = 'generated_at'").fetchone()
    conn.execute(
        "INSERT OR REPLACE INTO build_metadata VALUES ('generated_at', ?)",
        (now_iso(),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO build_metadata VALUES ('merged_shard_db', ?)",
        (str(shard_db),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO build_metadata VALUES ('base_generated_at_before_merge', ?)",
        (base_generated_at[0] if base_generated_at else "",),
    )
    conn.commit()
    conn.execute("DETACH DATABASE shard")
    conn.close()

    identity_manifest_path = identity_manifest_path or out_db.with_suffix(".incoming_identity_manifest.json")
    identity_manifest.update(
        {
            "schema_version": "atlas_incoming_identity_manifest.v1",
            "generated_at": now_iso(),
            "base_serving_db": str(base_db),
            "shard_db": str(shard_db),
        }
    )
    write_json(identity_manifest_path, identity_manifest)

    return {
        "base_serving_db": str(base_db),
        "shard_db": str(shard_db),
        "out_db": str(out_db),
        "not_merged_tables": [t for t in ("dj_relation_rollup", "dj_venue_rollup", "dj_org_rollup", "canonical_subject", "search_document") ],
        "rows_inserted": inserted,
        "incoming_identity_manifest": str(identity_manifest_path),
        "incoming_identity_counts": identity_manifest["counts"],
        "generated_at": now_iso(),
    }


def _self_check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        base_db = tmp_path / "base.sqlite"
        conn = sqlite3.connect(str(base_db))
        conn.executescript(
            """
            CREATE TABLE performance_event (event_id TEXT PRIMARY KEY, event_title TEXT, starts_at TEXT);
            CREATE TABLE dj_event (dj_id TEXT, event_id TEXT, starts_at TEXT, PRIMARY KEY (dj_id, event_id));
            CREATE TABLE evidence_ref (source_ref_id TEXT PRIMARY KEY, source_title TEXT);
            CREATE TABLE dj_profile (dj_id TEXT PRIMARY KEY, display_name TEXT);
            CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT);
            """
        )
        conn.execute("INSERT INTO performance_event VALUES ('evt1', 'Existing Party', '2026-01-01')")
        conn.execute("INSERT INTO dj_profile VALUES ('dj1', 'Existing DJ')")
        conn.execute("INSERT INTO build_metadata VALUES ('generated_at', '2026-05-25T00:00:00')")
        conn.commit()
        conn.close()

        shard_db = tmp_path / "shard.sqlite"
        sconn = sqlite3.connect(str(shard_db))
        sconn.executescript(
            """
            CREATE TABLE performance_event (event_id TEXT PRIMARY KEY, event_title TEXT, starts_at TEXT);
            CREATE TABLE dj_event (dj_id TEXT, event_id TEXT, starts_at TEXT, PRIMARY KEY (dj_id, event_id));
            CREATE TABLE evidence_ref (source_ref_id TEXT PRIMARY KEY, source_title TEXT);
            CREATE TABLE dj_profile (dj_id TEXT PRIMARY KEY, display_name TEXT);
            """
        )
        # evt1 also appears in the shard (e.g. reprocessed) -> must NOT duplicate/overwrite
        sconn.execute("INSERT INTO performance_event VALUES ('evt1', 'Existing Party (reprocessed)', '2099-01-01')")
        sconn.execute("INSERT INTO performance_event VALUES ('evt2', 'New Party', '2026-07-10')")
        sconn.execute("INSERT INTO dj_profile VALUES ('dj1', 'Existing DJ (reprocessed)')")
        sconn.execute("INSERT INTO dj_profile VALUES ('dj2', 'New DJ')")
        sconn.commit()
        sconn.close()

        out_db = tmp_path / "merged.sqlite"
        identity_manifest_path = tmp_path / "incoming_identity_manifest.json"
        result = merge(base_db, shard_db, out_db, identity_manifest_path)

        assert result["rows_inserted"]["performance_event"] == 1, result
        assert result["rows_inserted"]["dj_profile"] == 1, result
        manifest = json.loads(identity_manifest_path.read_text(encoding="utf-8"))
        manifest_rows = {row["dj_id"]: row for row in manifest["rows"]}
        assert manifest_rows["dj1"]["was_in_base"] is True
        assert manifest_rows["dj2"]["was_in_base"] is False
        assert manifest["counts"]["new_to_base"] == 1

        mconn = sqlite3.connect(str(out_db))
        mconn.row_factory = sqlite3.Row
        titles = {r["event_id"]: r["event_title"] for r in mconn.execute("SELECT event_id, event_title FROM performance_event")}
        assert titles["evt1"] == "Existing Party", "existing row must not be overwritten by a shard reprocess"
        assert titles["evt2"] == "New Party"

        bconn = sqlite3.connect(str(base_db))
        base_still_intact = bconn.execute("SELECT event_title FROM performance_event WHERE event_id='evt1'").fetchone()[0]
        bconn.close()
        assert base_still_intact == "Existing Party", "merge must never touch the base DB in place"
        mconn.close()

        print(f"incoming identity manifest: {identity_manifest_path}")
        print("self-check OK: shard merge is insert-or-ignore (no overwrite), base DB untouched in place")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-serving-db", type=Path)
    ap.add_argument("--shard-db", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--identity-manifest", type=Path, default=None)
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    if args.self_check:
        _self_check()
        return 0

    if not args.base_serving_db or not args.base_serving_db.exists():
        raise SystemExit(f"--base-serving-db not found: {args.base_serving_db}")
    if not args.shard_db or not args.shard_db.exists():
        raise SystemExit(f"--shard-db not found: {args.shard_db}")
    if not args.out:
        raise SystemExit("--out is required")

    result = merge(args.base_serving_db, args.shard_db, args.out, args.identity_manifest)
    if args.report:
        write_json(args.report, result)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
