import importlib.util
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_atlas_activity_sidecar_current_drift.py"
spec = importlib.util.spec_from_file_location("audit_atlas_activity_sidecar_current_drift", SCRIPT)
drift = importlib.util.module_from_spec(spec)
sys.modules["audit_atlas_activity_sidecar_current_drift"] = drift
spec.loader.exec_module(drift)


def make_sidecar(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE activity_events (
          activity_event_id TEXT PRIMARY KEY,
          event_id TEXT,
          publish_package TEXT,
          title TEXT,
          event_date_text_json TEXT,
          event_date_start TEXT,
          event_date_end TEXT,
          event_time_text TEXT,
          time_start TEXT,
          time_end TEXT,
          venue_name TEXT,
          venue_id TEXT,
          address TEXT,
          city_name TEXT
        );
        CREATE TABLE evidence_refs (
          evidence_ref_id TEXT PRIMARY KEY,
          activity_event_id TEXT,
          field_path TEXT,
          field_value TEXT,
          support_type TEXT,
          source_kind TEXT,
          source_url_map_key TEXT,
          source_url_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          quote TEXT,
          quote_policy TEXT
        );
        CREATE TABLE prov_activities (prov_activity_id TEXT PRIMARY KEY);
        """
    )
    conn.execute(
        "INSERT INTO activity_events VALUES ('ae:1','event:1','pkg','Current Title','[]','2026-06-01','','20:00','','','Club','venue:1','Addr','上海')"
    )
    conn.execute(
        "INSERT INTO evidence_refs VALUES ('er:current','ae:1','address','Addr','quote','atlas_article','k','hash','Account','2026-05-01','Addr','short')"
    )
    conn.execute(
        "INSERT INTO evidence_refs VALUES ('er:new','ae:1','lineup_artists','Artist A','quote','atlas_article','k','hash','Account','2026-05-01','Artist A','short')"
    )
    conn.execute("INSERT INTO prov_activities VALUES ('prov:1')")
    conn.commit()
    conn.close()


def make_candidate(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE atlas_activity_events (
          activity_event_id TEXT PRIMARY KEY,
          event_id TEXT,
          publish_package TEXT,
          title TEXT,
          event_date_text_json TEXT,
          event_date_start TEXT,
          event_date_end TEXT,
          event_time_text TEXT,
          time_start TEXT,
          time_end TEXT,
          venue_name TEXT,
          venue_id TEXT,
          address TEXT,
          city_name TEXT
        );
        CREATE TABLE atlas_activity_evidence_refs (
          evidence_ref_id TEXT PRIMARY KEY,
          activity_event_id TEXT,
          field_path TEXT,
          field_value TEXT,
          support_type TEXT,
          source_kind TEXT,
          source_url_map_key TEXT,
          source_url_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          quote TEXT,
          quote_policy TEXT
        );
        CREATE TABLE atlas_activity_prov_activities (prov_activity_id TEXT PRIMARY KEY);
        """
    )
    conn.execute(
        "INSERT INTO atlas_activity_events VALUES ('ae:old','event:1','pkg','Old Title','[]','2026-06-01','','20:00','','','Club','venue:1','Addr','上海')"
    )
    conn.execute(
        "INSERT INTO atlas_activity_evidence_refs VALUES ('er:old','ae:old','address','Addr','quote','atlas_article','k','hash','Account','2026-05-01','Addr','short')"
    )
    conn.execute(
        "INSERT INTO atlas_activity_evidence_refs VALUES ('er:stale','ae:old','music_styles','techno','quote','atlas_article','k','hash','Account','2026-05-01','techno','short')"
    )
    conn.execute("INSERT INTO atlas_activity_prov_activities VALUES ('prov:old')")
    conn.commit()
    conn.close()


def make_selected_serving(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE activity_event_detail (event_id TEXT PRIMARY KEY);
        CREATE TABLE activity_evidence_ref (evidence_ref_id TEXT PRIMARY KEY);
        """
    )
    conn.execute("INSERT INTO activity_event_detail VALUES ('event:1')")
    conn.execute("INSERT INTO activity_evidence_ref VALUES ('er:1')")
    conn.commit()
    conn.close()


def test_audit_detects_current_sidecar_drift(tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecar.sqlite"
    candidate = tmp_path / "candidate.sqlite"
    selected = tmp_path / "selected.sqlite"
    out_dir = tmp_path / "out"
    report_path = tmp_path / "report.md"
    make_sidecar(sidecar)
    make_candidate(candidate)
    make_selected_serving(selected)

    report = drift.audit_drift(sidecar, candidate, selected, out_dir, report_path)

    assert report["decision"] == "atlas_activity_sidecar_current_drift_refresh_needed_report_only"
    assert report["event_id_drift"] == {
        "candidate_not_in_sidecar": 0,
        "sidecar_missing_in_candidate": 0,
    }
    assert report["event_core_changed_count"] == 1
    assert report["evidence_natural_key_drift"] == {
        "candidate_not_in_sidecar": 1,
        "sidecar_not_in_candidate": 1,
    }
    assert report["selected_serving_counts"] == {
        "activity_event_detail": 1,
        "activity_evidence_ref": 1,
    }
    assert report["safety"]["production_write_executed"] is False
    assert (out_dir / "atlas_activity_sidecar_current_drift_summary.json").exists()
    assert report_path.exists()


def test_historical_candidate_extras_do_not_fail_current_subset_audit(tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecar.sqlite"
    candidate = tmp_path / "candidate.sqlite"
    selected = tmp_path / "selected.sqlite"
    make_sidecar(sidecar)
    make_candidate(candidate)
    make_selected_serving(selected)
    conn = sqlite3.connect(candidate)
    try:
        conn.execute("UPDATE atlas_activity_events SET title='Current Title' WHERE event_id='event:1'")
        conn.execute(
            "INSERT INTO atlas_activity_evidence_refs VALUES "
            "('er:new','ae:old','lineup_artists','Artist A','quote','atlas_article','k','hash','Account','2026-05-01','Artist A','short')"
        )
        conn.execute(
            "INSERT INTO atlas_activity_events VALUES "
            "('ae:history','event:history','old-package','Historical','[]','2026-05-01','','20:00','','','Old Club','venue:old','Old Addr','上海')"
        )
        conn.commit()
    finally:
        conn.close()

    report = drift.audit_drift(sidecar, candidate, selected, tmp_path / "out", tmp_path / "report.md")

    assert report["decision"] == "atlas_activity_sidecar_current_aligned_report_only"
    assert report["event_id_drift"]["candidate_not_in_sidecar"] == 1
    assert report["evidence_natural_key_drift"]["candidate_not_in_sidecar"] == 1
    assert report["candidate_historical_extras_expected"] is True
