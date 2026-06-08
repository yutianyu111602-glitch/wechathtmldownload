# DB2 Outlink Lineage Reconcile S125 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only DB2 external-link lineage reconcile script that compares live Swarm outlinks against S119, T6 overlay, and companion sidecars while keeping every row candidate/report-only by default.

**Architecture:** Add one focused Python script and one pytest module. The script opens all SQLite inputs read-only, canonicalizes URL keys into hashes, emits JSONL plus Markdown summary, and enforces `projection_allowed=false` unless a later independent gate says otherwise. It does not start workers, mutate live DB, read cookies/tokens, or expose raw URLs in JSONL.

**Tech Stack:** Python standard library only (`argparse`, `hashlib`, `json`, `sqlite3`, `urllib.parse`, `pathlib`, `datetime`), pytest for tests.

---

## Scope Check

This plan implements only S125 from `reports/DB2_OUTLINK_IMPLEMENTATION_DESIGN_PLAN_20260601.md`.

Separate implementation plans are still needed for:

- S126 recovery preflight.
- S127 safe launcher profile patch.
- S128 `sc_deep` city persistence.
- S129 OpenClaw nightwatch wrapper.
- S131 BC/RA/nuclear smoke gates.

## File Structure

- Create: `tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py`
  - Responsibility: read-only SQLite input loading, URL normalization/hash, row reconciliation, JSONL/Markdown output, CLI.
- Create: `tools/stage7_rewrite/tests/test_build_db2_outlink_lineage_reconcile_s125.py`
  - Responsibility: fixture DBs and behavior tests for candidate defaults, SearXNG blocking, URL redaction, and output files.
- Output at runtime:
  - `tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_YYYYMMDD/db2_outlink_lineage_reconcile.jsonl`
  - `tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_YYYYMMDD/db2_outlink_lineage_reconcile.md`
  - Optional mirror controlled by CLI: `/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_YYYYMMDD.jsonl`
  - Optional mirror controlled by CLI: `/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_YYYYMMDD.md`

## Task 1: Fixture Tests For Reconcile Contract

**Files:**
- Create: `tools/stage7_rewrite/tests/test_build_db2_outlink_lineage_reconcile_s125.py`
- Create later: `tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/stage7_rewrite/tests/test_build_db2_outlink_lineage_reconcile_s125.py` with this content:

```python
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_db2_outlink_lineage_reconcile_s125.py"


def load_module():
    spec = importlib.util.spec_from_file_location("build_db2_outlink_lineage_reconcile_s125", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def create_live_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE dj_outlinks (
            outlink_id TEXT PRIMARY KEY,
            eid TEXT,
            profile_id TEXT,
            outlink_url TEXT,
            outlink_platform TEXT,
            entity_name TEXT,
            source_layer TEXT,
            source_profile_url TEXT,
            profile_platform TEXT,
            discovered_at TEXT,
            source TEXT
        )
        """
    )
    con.executemany(
        """
        INSERT INTO dj_outlinks (
            outlink_id, eid, profile_id, outlink_url, outlink_platform,
            entity_name, source_layer, source_profile_url, profile_platform,
            discovered_at, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "out-1",
                "eid-1",
                "profile-1",
                "https://soundcloud.com/FixtureDJ/?utm_source=ig",
                "soundcloud",
                "Fixture DJ",
                "ig_fission_v2",
                "https://instagram.com/fixture",
                "instagram",
                "2026-06-01T00:00:00+08:00",
                "ig_fission_v2",
            ),
            (
                "out-searx",
                "eid-2",
                "profile-2",
                "https://example.test/bad",
                "_searxng",
                "Bad Search",
                "_searxng",
                "",
                "",
                "2026-06-01T00:01:00+08:00",
                "searxng",
            ),
        ],
    )
    con.commit()
    con.close()


def create_s119_db(path: Path, module) -> str:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE external_link_candidates (
            sidecar_id TEXT PRIMARY KEY,
            task_id TEXT,
            entity_search_id TEXT,
            entity_name TEXT,
            entity_type TEXT,
            platform TEXT,
            url TEXT,
            profile_url TEXT,
            parent_link_url TEXT,
            link_kind TEXT,
            public_category TEXT,
            confidence_score REAL,
            confidence_band TEXT,
            confidence_reasons_json TEXT,
            copyright_safety TEXT,
            block_reasons_json TEXT,
            fetch_status INTEGER,
            source_layer TEXT,
            db2_projection_allowed INTEGER DEFAULT 0
        )
        """
    )
    url_hash = module.url_key_hash("https://soundcloud.com/FixtureDJ/?utm_source=ig")
    con.execute(
        """
        INSERT INTO external_link_candidates (
            sidecar_id, task_id, entity_search_id, entity_name, entity_type,
            platform, url, profile_url, parent_link_url, link_kind,
            public_category, confidence_score, confidence_band,
            confidence_reasons_json, copyright_safety, block_reasons_json,
            fetch_status, source_layer, db2_projection_allowed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "s119-1",
            "task-1",
            "eid-1",
            "Fixture DJ",
            "dj",
            "soundcloud",
            "https://soundcloud.com/FixtureDJ/",
            "https://soundcloud.com/FixtureDJ/",
            "",
            "social_profile",
            "external_music_link",
            95,
            "high",
            json.dumps(["fixture"]),
            "jump_out_only",
            json.dumps([]),
            200,
            "profile_page",
            0,
        ),
    )
    con.commit()
    con.close()
    return url_hash


def create_t6_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE atlas_dj_social_links (
            candidate_id TEXT PRIMARY KEY,
            entity_id TEXT,
            candidate_kind TEXT,
            platform TEXT,
            host TEXT,
            canonical_url_key TEXT,
            canonical_url_key_hash TEXT,
            validation_status TEXT,
            merge_status TEXT,
            source_context_verified INTEGER,
            identity_review_required INTEGER,
            avatar_ready INTEGER,
            accepted_for_graph INTEGER,
            source_raw_db_write_executed INTEGER,
            serving_rebuild_allowed INTEGER,
            public_serving_field_allowed INTEGER,
            payload_hash TEXT,
            created_at TEXT
        )
        """
    )
    con.execute(
        """
        INSERT INTO atlas_dj_social_links (
            candidate_id, entity_id, candidate_kind, platform, host,
            canonical_url_key, canonical_url_key_hash, validation_status,
            merge_status, source_context_verified, identity_review_required,
            avatar_ready, accepted_for_graph, source_raw_db_write_executed,
            serving_rebuild_allowed, public_serving_field_allowed, payload_hash, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "t6-1",
            "eid-1",
            "outlink",
            "soundcloud",
            "soundcloud.com",
            "https://soundcloud.com/fixturedj/",
            "",
            "review_ready",
            "candidate",
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            "payload",
            "2026-06-01T00:00:00+08:00",
        ),
    )
    con.commit()
    con.close()


def create_companion_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE dj_outlinks (
            outlink_id TEXT PRIMARY KEY,
            eid TEXT,
            profile_id TEXT,
            outlink_url TEXT,
            outlink_platform TEXT,
            entity_name TEXT,
            source_layer TEXT,
            source_profile_url TEXT,
            profile_platform TEXT,
            discovered_at TEXT
        )
        """
    )
    con.execute(
        """
        INSERT INTO dj_outlinks (
            outlink_id, eid, profile_id, outlink_url, outlink_platform,
            entity_name, source_layer, source_profile_url, profile_platform, discovered_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "companion-1",
            "eid-1",
            "profile-1",
            "https://soundcloud.com/FixtureDJ/",
            "soundcloud",
            "Fixture DJ",
            "profile_page",
            "",
            "soundcloud",
            "2026-05-22T00:00:00+08:00",
        ),
    )
    con.commit()
    con.close()


def test_build_reconcile_rows_defaults_candidate_projection_false(tmp_path: Path):
    module = load_module()
    live = tmp_path / "live.sqlite"
    s119 = tmp_path / "s119.sqlite"
    t6 = tmp_path / "t6.sqlite"
    companion = tmp_path / "companion.sqlite"
    create_live_db(live)
    create_s119_db(s119, module)
    create_t6_db(t6)
    create_companion_db(companion)

    rows = module.build_reconcile_rows(
        live_db=live,
        s119_db=s119,
        t6_db=t6,
        companion_db=companion,
        lineage_run_id="lineage-test",
        limit=10,
    )

    row = next(item for item in rows if item["candidate_id"] == "out-1")
    assert row["source_db_role"] == "live_swarm_external_link_db2"
    assert row["source_table"] == "dj_outlinks"
    assert row["source_row_key"] == "outlink_id"
    assert row["fact_state"] == "candidate"
    assert row["projection_allowed"] is False
    assert row["matched_s119_sidecar_id"] == "s119-1"
    assert row["matched_t6_candidate_id"] == "t6-1"
    assert row["matched_companion_outlink_id"] == "companion-1"


def test_searxng_rows_are_blocked(tmp_path: Path):
    module = load_module()
    live = tmp_path / "live.sqlite"
    s119 = tmp_path / "s119.sqlite"
    t6 = tmp_path / "t6.sqlite"
    companion = tmp_path / "companion.sqlite"
    create_live_db(live)
    create_s119_db(s119, module)
    create_t6_db(t6)
    create_companion_db(companion)

    rows = module.build_reconcile_rows(
        live_db=live,
        s119_db=s119,
        t6_db=t6,
        companion_db=companion,
        lineage_run_id="lineage-test",
        limit=10,
    )

    row = next(item for item in rows if item["candidate_id"] == "out-searx")
    assert row["fact_state"] == "blocked"
    assert row["projection_allowed"] is False
    assert row["block_reason"] == "searxng_source_blocked"


def test_jsonl_uses_url_hash_not_raw_url(tmp_path: Path):
    module = load_module()
    live = tmp_path / "live.sqlite"
    s119 = tmp_path / "s119.sqlite"
    t6 = tmp_path / "t6.sqlite"
    companion = tmp_path / "companion.sqlite"
    create_live_db(live)
    create_s119_db(s119, module)
    create_t6_db(t6)
    create_companion_db(companion)

    rows = module.build_reconcile_rows(
        live_db=live,
        s119_db=s119,
        t6_db=t6,
        companion_db=companion,
        lineage_run_id="lineage-test",
        limit=10,
    )
    out_dir = tmp_path / "out"
    jsonl_path, md_path = module.write_outputs(rows, out_dir, "lineage-test")

    text = jsonl_path.read_text(encoding="utf-8")
    assert "https://soundcloud.com" not in text
    assert "url_key_hash" in text
    assert md_path.exists()


def test_cli_writes_report_files(tmp_path: Path):
    module = load_module()
    live = tmp_path / "live.sqlite"
    s119 = tmp_path / "s119.sqlite"
    t6 = tmp_path / "t6.sqlite"
    companion = tmp_path / "companion.sqlite"
    create_live_db(live)
    create_s119_db(s119, module)
    create_t6_db(t6)
    create_companion_db(companion)

    out_dir = tmp_path / "cli-out"
    rc = module.main(
        [
            "--live-db",
            str(live),
            "--s119-db",
            str(s119),
            "--t6-db",
            str(t6),
            "--companion-db",
            str(companion),
            "--output-dir",
            str(out_dir),
            "--lineage-run-id",
            "lineage-cli",
            "--limit",
            "10",
        ]
    )

    assert rc == 0
    assert (out_dir / "db2_outlink_lineage_reconcile.jsonl").exists()
    assert (out_dir / "db2_outlink_lineage_reconcile.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_db2_outlink_lineage_reconcile_s125.py -q
```

Expected:

```text
FAILED ... FileNotFoundError ... build_db2_outlink_lineage_reconcile_s125.py
```

- [ ] **Step 3: Commit the failing test**

```powershell
git add tools/stage7_rewrite/tests/test_build_db2_outlink_lineage_reconcile_s125.py
git commit -m "test: add db2 outlink lineage reconcile contract"
```

## Task 2: Implement The Reconcile Script

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py`
- Test: `tools/stage7_rewrite/tests/test_build_db2_outlink_lineage_reconcile_s125.py`

- [ ] **Step 1: Create the implementation**

Create `tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py` with this content:

```python
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_LIVE_DB = Path("/home/pc/swarm_data/atlas_swarm_data.sqlite")
DEFAULT_S119_DB = Path(
    "tools/stage7_rewrite/reports/external_link_db2_sidecar_contract_s119_20260601/"
    "external_link_db2_sidecar.sqlite"
)
DEFAULT_T6_DB = Path(
    "tools/stage7_rewrite/reports/atlas_t6_sidecar_new_db_overlay_t5_t6_20260526/"
    "atlas_t6_sidecar_social_overlay.sqlite"
)
DEFAULT_COMPANION_DB = Path(
    "tools/stage7_rewrite/reports/atlas_dj_companion_20260522/atlas_dj_v2.sqlite"
)

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "igsh",
    "mc_cid",
    "mc_eid",
    "spm",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def now_cst_date() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")


def canonicalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") + "/"
    query_pairs = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def url_key_hash(url: str) -> str:
    canonical = canonicalize_url(url)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest() if canonical else ""


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def read_live_outlinks(live_db: Path, limit: int = 0) -> list[sqlite3.Row]:
    conn = connect_readonly(live_db)
    try:
        query = """
            SELECT outlink_id, eid, profile_id, outlink_url, outlink_platform,
                   entity_name, source_layer, source_profile_url,
                   profile_platform, discovered_at, source
            FROM dj_outlinks
            ORDER BY discovered_at DESC, outlink_id
        """
        if limit > 0:
            query += " LIMIT ?"
            return list(conn.execute(query, (limit,)).fetchall())
        return list(conn.execute(query).fetchall())
    finally:
        conn.close()


def load_s119_by_hash(path: Path) -> dict[str, sqlite3.Row]:
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "external_link_candidates"):
            return {}
        rows = conn.execute("SELECT * FROM external_link_candidates").fetchall()
        by_hash: dict[str, sqlite3.Row] = {}
        for row in rows:
            hashed = url_key_hash(row["url"] if "url" in row.keys() else "")
            if hashed and hashed not in by_hash:
                by_hash[hashed] = row
        return by_hash
    finally:
        conn.close()


def load_t6_by_hash(path: Path) -> dict[str, sqlite3.Row]:
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "atlas_dj_social_links"):
            return {}
        rows = conn.execute("SELECT * FROM atlas_dj_social_links").fetchall()
        by_hash: dict[str, sqlite3.Row] = {}
        for row in rows:
            hashed = row["canonical_url_key_hash"] if "canonical_url_key_hash" in row.keys() else ""
            if not hashed:
                hashed = url_key_hash(row["canonical_url_key"] if "canonical_url_key" in row.keys() else "")
            if hashed and hashed not in by_hash:
                by_hash[hashed] = row
        return by_hash
    finally:
        conn.close()


def load_companion_by_hash(path: Path) -> dict[str, sqlite3.Row]:
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "dj_outlinks"):
            return {}
        rows = conn.execute(
            """
            SELECT outlink_id, eid, outlink_url, outlink_platform, entity_name,
                   source_layer, source_profile_url, profile_platform, discovered_at
            FROM dj_outlinks
            """
        ).fetchall()
        by_hash: dict[str, sqlite3.Row] = {}
        for row in rows:
            hashed = url_key_hash(row["outlink_url"])
            if hashed and hashed not in by_hash:
                by_hash[hashed] = row
        return by_hash
    finally:
        conn.close()


def row_value(row: sqlite3.Row | None, key: str, default=None):
    if row is None:
        return default
    return row[key] if key in row.keys() else default


def is_searxng(row: sqlite3.Row) -> bool:
    markers = [
        row_value(row, "outlink_platform", ""),
        row_value(row, "source_layer", ""),
        row_value(row, "source", ""),
    ]
    return any("searx" in str(item).lower() for item in markers)


def projection_from_matches(s119: sqlite3.Row | None, t6: sqlite3.Row | None) -> bool:
    s119_allowed = bool(row_value(s119, "db2_projection_allowed", 0))
    t6_allowed = bool(row_value(t6, "public_serving_field_allowed", 0))
    return bool(s119_allowed and t6_allowed)


def block_reason_for(row: sqlite3.Row, s119: sqlite3.Row | None, projection_allowed: bool) -> str:
    if is_searxng(row):
        return "searxng_source_blocked"
    copyright_safety = str(row_value(s119, "copyright_safety", "") or "").lower()
    if "blocked" in copyright_safety or "direct_media" in copyright_safety:
        return "copyright_safety_blocked"
    if not projection_allowed:
        return "projection_gate_not_passed"
    return ""


def build_reconcile_rows(
    *,
    live_db: Path,
    s119_db: Path,
    t6_db: Path,
    companion_db: Path,
    lineage_run_id: str,
    limit: int = 0,
) -> list[dict]:
    s119_by_hash = load_s119_by_hash(s119_db)
    t6_by_hash = load_t6_by_hash(t6_db)
    companion_by_hash = load_companion_by_hash(companion_db)
    rows: list[dict] = []

    for live in read_live_outlinks(live_db, limit=limit):
        hashed = url_key_hash(live["outlink_url"])
        s119 = s119_by_hash.get(hashed)
        t6 = t6_by_hash.get(hashed)
        companion = companion_by_hash.get(hashed)
        projection_allowed = projection_from_matches(s119, t6)
        block_reason = block_reason_for(live, s119, projection_allowed)
        fact_state = "blocked" if block_reason and block_reason != "projection_gate_not_passed" else "candidate"

        rows.append(
            {
                "lineage_run_id": lineage_run_id,
                "source_db_role": "live_swarm_external_link_db2",
                "source_table": "dj_outlinks",
                "source_row_key": "outlink_id",
                "entity_key": live["eid"],
                "platform": live["outlink_platform"],
                "url_key_hash": hashed,
                "candidate_id": live["outlink_id"],
                "matched_s119_sidecar_id": row_value(s119, "sidecar_id"),
                "matched_t6_candidate_id": row_value(t6, "candidate_id"),
                "matched_companion_outlink_id": row_value(companion, "outlink_id"),
                "fact_state": fact_state,
                "projection_allowed": projection_allowed,
                "block_reason": block_reason,
                "source_layer": live["source_layer"],
                "source_worker": live["source"],
            }
        )
    return rows


def write_outputs(rows: list[dict], output_dir: Path, lineage_run_id: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "db2_outlink_lineage_reconcile.jsonl"
    md_path = output_dir / "db2_outlink_lineage_reconcile.md"

    with jsonl_path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    fact_counts = Counter(row["fact_state"] for row in rows)
    platform_counts = Counter(row["platform"] for row in rows)
    matched_s119 = sum(1 for row in rows if row["matched_s119_sidecar_id"])
    matched_t6 = sum(1 for row in rows if row["matched_t6_candidate_id"])
    matched_companion = sum(1 for row in rows if row["matched_companion_outlink_id"])
    projection_allowed = sum(1 for row in rows if row["projection_allowed"])

    lines = [
        "# DB2 Outlink Lineage Reconcile",
        "",
        f"- lineage_run_id: `{lineage_run_id}`",
        f"- rows: `{len(rows)}`",
        f"- matched_s119: `{matched_s119}`",
        f"- matched_t6: `{matched_t6}`",
        f"- matched_companion: `{matched_companion}`",
        f"- projection_allowed: `{projection_allowed}`",
        "",
        "## Fact State Counts",
        "",
    ]
    for key, count in sorted(fact_counts.items()):
        lines.append(f"- `{key}`: `{count}`")
    lines.extend(["", "## Top Platforms", ""])
    for key, count in platform_counts.most_common(20):
        lines.append(f"- `{key}`: `{count}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- JSONL contains `url_key_hash`, not raw URL.",
            "- Rows remain candidate/report-only unless a separate projection gate approves them.",
            "- This run does not write live DB, DB1, DB2 serving, DB3, graph, vector, memory, or public state.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    today = now_cst_date()
    return_parser = argparse.ArgumentParser(description="Build DB2 outlink lineage reconcile report")
    return_parser.add_argument("--live-db", type=Path, default=DEFAULT_LIVE_DB)
    return_parser.add_argument("--s119-db", type=Path, default=DEFAULT_S119_DB)
    return_parser.add_argument("--t6-db", type=Path, default=DEFAULT_T6_DB)
    return_parser.add_argument("--companion-db", type=Path, default=DEFAULT_COMPANION_DB)
    return_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(f"tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_{today}"),
    )
    return_parser.add_argument("--lineage-run-id", default=f"db2_outlink_lineage_reconcile_{today}")
    return_parser.add_argument("--limit", type=int, default=0)
    return return_parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = build_reconcile_rows(
        live_db=args.live_db,
        s119_db=args.s119_db,
        t6_db=args.t6_db,
        companion_db=args.companion_db,
        lineage_run_id=args.lineage_run_id,
        limit=args.limit,
    )
    jsonl_path, md_path = write_outputs(rows, args.output_dir, args.lineage_run_id)
    print(json.dumps({"rows": len(rows), "jsonl": str(jsonl_path), "markdown": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run focused tests**

Run:

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_db2_outlink_lineage_reconcile_s125.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 3: Run py_compile**

Run:

```powershell
python -m py_compile tools\stage7_rewrite\scripts\build_db2_outlink_lineage_reconcile_s125.py
```

Expected: no output and exit code 0.

- [ ] **Step 4: Commit**

```powershell
git add tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py tools/stage7_rewrite/tests/test_build_db2_outlink_lineage_reconcile_s125.py
git commit -m "feat: add db2 outlink lineage reconcile"
```

## Task 3: Live Read-Only Smoke Run

**Files:**
- Use: `tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py`
- Output: `tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_20260601/`

- [ ] **Step 1: Run a bounded live read-only smoke**

Run from `C:\code\githubstar\wechathtmldownload`:

```powershell
python tools\stage7_rewrite\scripts\build_db2_outlink_lineage_reconcile_s125.py --limit 200 --output-dir tools\stage7_rewrite\reports\db2_outlink_lineage_reconcile_s125_20260601_smoke
```

Expected output shape:

```json
{"rows": 200, "jsonl": "tools\\stage7_rewrite\\reports\\db2_outlink_lineage_reconcile_s125_20260601_smoke\\db2_outlink_lineage_reconcile.jsonl", "markdown": "tools\\stage7_rewrite\\reports\\db2_outlink_lineage_reconcile_s125_20260601_smoke\\db2_outlink_lineage_reconcile.md"}
```

- [ ] **Step 2: Verify JSONL does not contain raw URLs**

Run:

```powershell
Select-String -LiteralPath tools\stage7_rewrite\reports\db2_outlink_lineage_reconcile_s125_20260601_smoke\db2_outlink_lineage_reconcile.jsonl -Pattern 'https://|http://|cookie|token|secret|C:\\|D:\\|/mnt/d' -SimpleMatch
```

Expected: no matches.

- [ ] **Step 3: Verify projection defaults remain blocked**

Run:

```powershell
python -c "import json, pathlib; p=pathlib.Path('tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_20260601_smoke/db2_outlink_lineage_reconcile.jsonl'); rows=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]; print(sum(1 for r in rows if r['projection_allowed']), len(rows))"
```

Expected:

```text
0 200
```

- [ ] **Step 4: Commit smoke artifacts if they are intentionally retained**

If the project wants the smoke report retained:

```powershell
git add tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_20260601_smoke
git commit -m "test: capture db2 lineage reconcile smoke"
```

If the project does not want smoke artifacts retained, leave them uncommitted and include the path in the handoff.

## Task 4: Full Report Run And WSL Mirror

**Files:**
- Use: `tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py`
- Output: `tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_20260601/`
- Mirror manually after generation:
  - `/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_20260601.jsonl`
  - `/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_20260601.md`

- [ ] **Step 1: Run the full read-only report**

Run:

```powershell
python tools\stage7_rewrite\scripts\build_db2_outlink_lineage_reconcile_s125.py --output-dir tools\stage7_rewrite\reports\db2_outlink_lineage_reconcile_s125_20260601
```

Expected: command prints JSON containing `rows`, `jsonl`, and `markdown`.

- [ ] **Step 2: Mirror outputs to WSL reports**

Run:

```powershell
Copy-Item -LiteralPath tools\stage7_rewrite\reports\db2_outlink_lineage_reconcile_s125_20260601\db2_outlink_lineage_reconcile.jsonl -Destination \\wsl.localhost\Ubuntu\home\pc\reports\DB2_OUTLINK_LINEAGE_RECONCILE_20260601.jsonl
Copy-Item -LiteralPath tools\stage7_rewrite\reports\db2_outlink_lineage_reconcile_s125_20260601\db2_outlink_lineage_reconcile.md -Destination \\wsl.localhost\Ubuntu\home\pc\reports\DB2_OUTLINK_LINEAGE_RECONCILE_20260601.md
```

- [ ] **Step 3: Verify WSL mirror exists**

Run:

```powershell
Get-Item -LiteralPath \\wsl.localhost\Ubuntu\home\pc\reports\DB2_OUTLINK_LINEAGE_RECONCILE_20260601.md
Get-Item -LiteralPath \\wsl.localhost\Ubuntu\home\pc\reports\DB2_OUTLINK_LINEAGE_RECONCILE_20260601.jsonl
```

Expected: both files exist and have non-zero length.

- [ ] **Step 4: Commit retained full report if desired**

If retaining the full report in repo:

```powershell
git add tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_20260601
git commit -m "docs: add db2 lineage reconcile report"
```

If the full report is too large, do not commit it; keep the WSL mirror and mention it in the handoff.

## Task 5: Update DB2 Plan Pointers

**Files:**
- Modify: `reports/DB2_OUTLINK_IMPLEMENTATION_DESIGN_PLAN_20260601.md`
- Modify: `reports/DB2_OUTLINK_GOLDMINE_COMBINED_REVIEW_20260601.md`

- [ ] **Step 1: Add S125 output path to implementation design plan**

Append this short section to `reports/DB2_OUTLINK_IMPLEMENTATION_DESIGN_PLAN_20260601.md`:

```markdown
## 10. S125 Implementation Output

S125 read-only lineage reconcile produces:

- repo report: `tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_20260601/`
- WSL mirror: `/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_20260601.md`
- WSL JSONL mirror: `/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_20260601.jsonl`

Rows remain `candidate` or `blocked` by default; `projection_allowed` remains false unless a separate projection gate approves it.
```

- [ ] **Step 2: Add S125 output path to combined review**

Append this short section to `reports/DB2_OUTLINK_GOLDMINE_COMBINED_REVIEW_20260601.md`:

```markdown
## 9. S125 Reconcile Output

The S125 lineage reconcile script is the first implementation artifact for this combined review.

Expected outputs:

- `tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_20260601/db2_outlink_lineage_reconcile.md`
- `tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_20260601/db2_outlink_lineage_reconcile.jsonl`
- `/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_20260601.md`
- `/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_20260601.jsonl`
```

- [ ] **Step 3: Run markdown pointer checks**

Run:

```powershell
Select-String -LiteralPath reports\DB2_OUTLINK_IMPLEMENTATION_DESIGN_PLAN_20260601.md -Pattern 'S125 Implementation Output|projection_allowed'
Select-String -LiteralPath reports\DB2_OUTLINK_GOLDMINE_COMBINED_REVIEW_20260601.md -Pattern 'S125 Reconcile Output|DB2_OUTLINK_LINEAGE_RECONCILE'
```

Expected: each command prints matching lines.

- [ ] **Step 4: Commit docs**

```powershell
git add reports/DB2_OUTLINK_IMPLEMENTATION_DESIGN_PLAN_20260601.md reports/DB2_OUTLINK_GOLDMINE_COMBINED_REVIEW_20260601.md
git commit -m "docs: link db2 lineage reconcile output"
```

## Task 6: Final Verification

**Files:**
- Use all files from previous tasks.

- [ ] **Step 1: Run full focused test suite**

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_db2_outlink_lineage_reconcile_s125.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 2: Run script compilation**

```powershell
python -m py_compile tools\stage7_rewrite\scripts\build_db2_outlink_lineage_reconcile_s125.py
```

Expected: exit code 0.

- [ ] **Step 3: Confirm no banned raw strings in JSONL**

```powershell
Select-String -LiteralPath tools\stage7_rewrite\reports\db2_outlink_lineage_reconcile_s125_20260601\db2_outlink_lineage_reconcile.jsonl -Pattern 'https://|http://|cookie|token|secret|C:\\|D:\\|/mnt/d'
```

Expected: no matches.

- [ ] **Step 4: Confirm git scope**

```powershell
git status --short -- tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py tools/stage7_rewrite/tests/test_build_db2_outlink_lineage_reconcile_s125.py reports/DB2_OUTLINK_IMPLEMENTATION_DESIGN_PLAN_20260601.md reports/DB2_OUTLINK_GOLDMINE_COMBINED_REVIEW_20260601.md docs/superpowers/plans/2026-06-01-db2-outlink-lineage-reconcile-s125.md
```

Expected: only S125-related files are listed.

## Self-Review

- Spec coverage: Implements S125 from the DB2 implementation design plan and the combined goldmine review requirement for `lineage_run_id`, `source_db_role`, `fact_state`, and `projection_allowed`.
- Placeholder scan: This plan contains no incomplete placeholder sections; every code-writing step includes concrete file content or concrete appended text.
- Type consistency: The planned script exports `url_key_hash`, `build_reconcile_rows`, `write_outputs`, and `main`, and tests call those same names.
- Scope check: Recovery preflight, safe launcher, nightwatch, and worker fixes are intentionally excluded and need separate plans.
