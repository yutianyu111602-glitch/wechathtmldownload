"""Offline smoke for the Phase 1 canonical-event candidate builder.

Usage:
  python test_build_canonical_event_candidates.py
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from build_canonical_event_candidates import load_dj_redirects, norm_key, run

HERE = Path(__file__).resolve().parent


def create_source(path: Path, performance_rows: list[tuple], dj_rows: list[tuple]) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE performance_event (
          event_id TEXT,event_title TEXT,starts_at TEXT,venue_id TEXT,venue_name TEXT,city TEXT,
          source_ref_id TEXT,confidence REAL
        );
        CREATE TABLE dj_event (
          dj_id TEXT,event_id TEXT,starts_at TEXT,source_ref_id TEXT,confidence REAL
        );
        CREATE TABLE evidence_ref (
          source_ref_id TEXT,source_title TEXT,source_account TEXT,post_date TEXT
        );
        CREATE TABLE build_metadata (key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE dj_profile (dj_id TEXT PRIMARY KEY,display_name TEXT);
        """
    )
    con.executemany("INSERT INTO performance_event VALUES (?,?,?,?,?,?,?,?)", performance_rows)
    con.executemany("INSERT INTO dj_event VALUES (?,?,?,?,?)", dj_rows)
    con.executemany(
        "INSERT INTO evidence_ref VALUES (?,?,?,?)",
        [(row[6], row[1], "fixture", row[2]) for row in performance_rows],
    )
    con.executemany(
        "INSERT OR IGNORE INTO dj_profile VALUES (?,?)",
        [(row[0], row[0]) for row in dj_rows],
    )
    con.execute("INSERT INTO build_metadata VALUES ('generated_at','2026-07-12T00:00:00')")
    con.commit()
    con.close()


def create_redirects(root: Path) -> tuple[Path, Path]:
    identity = root / "identity.sqlite"
    con = sqlite3.connect(identity)
    con.execute(
        "CREATE TABLE dj_identity_redirect(source_dj_id TEXT PRIMARY KEY,canonical_dj_id TEXT NOT NULL)"
    )
    con.execute("INSERT INTO dj_identity_redirect VALUES ('dj:legacy','dj:canonical')")
    con.commit()
    con.close()

    venue = root / "venue.sqlite"
    con = sqlite3.connect(venue)
    con.execute(
        """
        CREATE TABLE venue_identity_redirect(
          source_venue_id TEXT PRIMARY KEY,
          source_city_key TEXT NOT NULL,
          canonical_venue_id TEXT NOT NULL
        )
        """
    )
    con.execute("INSERT INTO venue_identity_redirect VALUES ('venue:alias','昆明','venue:canonical')")
    con.commit()
    con.close()
    return identity, venue


def test_identity_and_venue_redirects_collapse_timeline(root: Path) -> None:
    source = root / "redirect_source.sqlite"
    create_source(
        source,
        [
            ("event:a", "VERVO Night", "2026-05-02", "venue:canonical", "VERVO CLUB", "昆明", "source:a", 0.9),
            ("event:b", "VERVO Night", "2026-05-02", "venue:alias", "VERVO国际独立电音俱乐部", "昆明", "source:b", 0.8),
        ],
        [
            ("dj:canonical", "event:a", "2026-05-02", "source:a", 0.9),
            ("dj:legacy", "event:b", "2026-05-02", "source:b", 0.8),
        ],
    )
    identity, venue = create_redirects(root)
    out = root / "redirect_out"

    run(
        source,
        out,
        limit_events=0,
        top_groups=20,
        sample_multi_event=10,
        identity_db=identity,
        venue_redirect_db=venue,
    )

    con = sqlite3.connect(out / "canonical_event_candidates.sqlite")
    assert con.execute("SELECT COUNT(*) FROM canonical_event").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM canonical_dj_event").fetchone()[0] == 1
    row = con.execute(
        "SELECT d.dj_id,e.venue_id FROM canonical_dj_event d JOIN canonical_event e USING(canonical_event_id)"
    ).fetchone()
    con.close()
    assert row == ("dj:canonical", "venue:canonical"), row


def test_cross_city_venue_reuse_stays_separate(root: Path) -> None:
    source = root / "cross_city_source.sqlite"
    create_source(
        source,
        [
            ("event:km", "Same Night Kunming", "2026-05-02", "venue:shared", "Shared", "昆明", "source:km", 0.9),
            ("event:sz", "Same Night Shenzhen", "2026-05-02", "venue:shared", "Shared", "深圳", "source:sz", 0.9),
        ],
        [],
    )
    decisions = root / "cross_city_decisions.sqlite"
    con = sqlite3.connect(decisions)
    con.execute(
        """
        CREATE TABLE weak_key_merge_decision(
          event_date TEXT,venue_id TEXT,title_norm_a TEXT,title_norm_b TEXT,decision TEXT
        )
        """
    )
    con.execute(
        "INSERT INTO weak_key_merge_decision VALUES (?,?,?,?, 'merge')",
        ("2026-05-02", "venue:shared", norm_key("Same Night Kunming"), norm_key("Same Night Shenzhen")),
    )
    con.commit()
    con.close()
    out = root / "cross_city_out"
    report = run(
        source,
        out,
        limit_events=0,
        top_groups=20,
        sample_multi_event=10,
        merge_decisions_db=decisions,
    )
    con = sqlite3.connect(out / "canonical_event_candidates.sqlite")
    count = con.execute("SELECT COUNT(*) FROM canonical_event").fetchone()[0]
    con.close()
    assert count == 2, count
    assert report["weak_key_application"]["pairs_skipped_cross_city"] == 1


def test_venue_redirect_does_not_escape_city_scope(root: Path) -> None:
    source = root / "scope_source.sqlite"
    create_source(
        source,
        [
            ("event:sz", "Alias Night", "2026-05-02", "venue:alias", "Alias", "深圳", "source:sz", 0.9),
        ],
        [],
    )
    redirect_root = root / "scope_redirects"
    redirect_root.mkdir()
    _identity, venue = create_redirects(redirect_root)
    out = root / "scope_out"
    run(
        source,
        out,
        limit_events=0,
        top_groups=20,
        sample_multi_event=10,
        venue_redirect_db=venue,
    )
    con = sqlite3.connect(out / "canonical_event_candidates.sqlite")
    venue_id = con.execute("SELECT venue_id FROM canonical_event").fetchone()[0]
    con.close()
    assert venue_id == "venue:alias", venue_id


def test_unicode_identifier_is_not_nfkc_normalized(root: Path) -> None:
    source = root / "unicode_id_source.sqlite"
    create_source(
        source,
        [
            ("event:unicode", "Unicode ID", "2026-05-02", "venue:unicode", "Unicode", "上海", "source:unicode", 0.9),
        ],
        [("dj:dan²", "event:unicode", "2026-05-02", "source:unicode", 0.9)],
    )
    out = root / "unicode_id_out"
    run(source, out, limit_events=0, top_groups=20, sample_multi_event=10)
    con = sqlite3.connect(out / "canonical_event_candidates.sqlite")
    dj_id = con.execute("SELECT dj_id FROM canonical_dj_event").fetchone()[0]
    con.close()
    assert dj_id == "dj:dan²", repr(dj_id)


def test_redirect_cycle_fails(root: Path) -> None:
    cycle = root / "cycle.sqlite"
    con = sqlite3.connect(cycle)
    con.execute(
        "CREATE TABLE dj_identity_redirect(source_dj_id TEXT PRIMARY KEY,canonical_dj_id TEXT NOT NULL)"
    )
    con.executemany(
        "INSERT INTO dj_identity_redirect VALUES (?,?)",
        [("dj:a", "dj:b"), ("dj:b", "dj:a")],
    )
    con.commit()
    con.close()
    try:
        load_dj_redirects(cycle)
    except ValueError as exc:
        assert "cycle" in str(exc).lower()
    else:
        raise AssertionError("redirect cycle must fail")


def test_shared_source_and_lineup_expand_review_without_auto_merge(root: Path) -> None:
    source = root / "evidence_review_source.sqlite"
    titles = ["无形之夜", "无形有形派对"]
    create_source(
        source,
        [
            (f"event:{index}", title, "2026-05-02", "venue:vervo", "VERVO", "昆明", "source:shared", 0.9)
            for index, title in enumerate(titles)
        ],
        [
            (dj_id, f"event:{index}", "2026-05-02", "source:shared", 0.9)
            for index in range(len(titles))
            for dj_id in ("dj:maxxi", "dj:sunny", "dj:zeming")
        ],
    )
    out = root / "evidence_review_out"
    report = run(source, out, limit_events=0, top_groups=20, sample_multi_event=10)

    con = sqlite3.connect(out / "canonical_event_candidates.sqlite")
    try:
        event_count = con.execute("SELECT COUNT(*) FROM canonical_event").fetchone()[0]
        candidate = con.execute(
            "SELECT shared_source_count,shared_dj_count,dj_jaccard,candidate_reason "
            "FROM canonical_event_merge_review_candidate"
        ).fetchone()
    finally:
        con.close()

    assert event_count == 2, "evidence signals expand review but never auto-merge"
    assert candidate == (1, 3, 1.0, "shared_source_lineup"), candidate
    assert report["weak_key_review"]["evidence_supported_candidate_count"] == 1


def main() -> None:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "build_canonical_event_candidates.py", "--self-check"],
        cwd=HERE,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"canonical-event self-check failed:\n{result.stdout}\n{result.stderr}"
    assert "self-check OK" in result.stdout
    with tempfile.TemporaryDirectory(prefix="atlas_canonical_redirect_test_") as tmp:
        root = Path(tmp)
        test_identity_and_venue_redirects_collapse_timeline(root)
        test_cross_city_venue_reuse_stays_separate(root)
        test_venue_redirect_does_not_escape_city_scope(root)
        test_unicode_identifier_is_not_nfkc_normalized(root)
        test_redirect_cycle_fails(root)
        test_shared_source_and_lineup_expand_review_without_auto_merge(root)
    print(result.stdout)


if __name__ == "__main__":
    main()
