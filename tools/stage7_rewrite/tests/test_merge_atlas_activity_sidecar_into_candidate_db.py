import importlib.util
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "merge_atlas_activity_sidecar_into_candidate_db.py"
spec = importlib.util.spec_from_file_location("merge_atlas_activity_sidecar_into_candidate_db", SCRIPT)
merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge)


def make_real_serving_base(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE canonical_build_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE activity_event_detail (event_id TEXT PRIMARY KEY, source_event_id TEXT);
        CREATE TABLE activity_evidence_ref (evidence_ref_id TEXT PRIMARY KEY, event_id TEXT);
        CREATE TABLE performance_event (event_id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE canonical_event (canonical_event_id TEXT PRIMARY KEY, title TEXT);
        CREATE TABLE search_document (document_id TEXT PRIMARY KEY, body TEXT);
        CREATE TABLE graph_window_cache (cache_key TEXT PRIMARY KEY, payload TEXT);
        INSERT INTO build_metadata VALUES ('source', 'base');
        INSERT INTO canonical_build_metadata VALUES ('canonical', 'unchanged');
        INSERT INTO activity_event_detail VALUES ('old-projected', 'old-source');
        INSERT INTO activity_evidence_ref VALUES ('old-ref', 'old-projected');
        INSERT INTO performance_event VALUES ('perf-1', 'Protected performance');
        INSERT INTO canonical_event VALUES ('canon-1', 'Protected canonical');
        INSERT INTO search_document VALUES ('search-1', 'Protected search');
        INSERT INTO graph_window_cache VALUES ('window-1', 'Protected graph');
        """
    )
    conn.commit()
    conn.close()


def make_sidecar_db(
    path: Path,
    *,
    event_id: str,
    package: str,
    title: str,
    activity_event_id: str | None = None,
    evidence_ref_id: str | None = None,
) -> None:
    activity_event_id = activity_event_id or f"ae:{package}:{event_id}"
    evidence_ref_id = evidence_ref_id or f"er:{package}:{event_id}"
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
          city_key TEXT,
          city_name TEXT,
          lineup_artists_json TEXT,
          music_styles_json TEXT,
          genres_json TEXT,
          price_json TEXT,
          ticketing_text TEXT,
          source_url_map_key TEXT,
          source_url_hash TEXT,
          source_token_hash TEXT,
          source_article_json TEXT,
          source_action_json TEXT,
          raw_event_json TEXT,
          generated_at TEXT
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
          quote_policy TEXT,
          ocr_span_id TEXT,
          ocr_span_status TEXT,
          confidence REAL,
          created_at TEXT
        );
        CREATE TABLE prov_activities (
          prov_activity_id TEXT PRIMARY KEY,
          schema_version TEXT,
          activity_type TEXT,
          generated_at TEXT,
          input_current_path TEXT,
          input_source_map_path TEXT,
          output_dir TEXT,
          summary_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO activity_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            activity_event_id,
            event_id,
            package,
            title,
            "[]",
            "2026-07-24",
            "2026-07-24",
            "20:00",
            "20:00",
            "",
            "Venue",
            "venue:1",
            "Address",
            "shanghai",
            "上海",
            "[]",
            '["techno"]',
            '["techno"]',
            "[]",
            "",
            "source-key",
            "sha256:source",
            "sha256:token",
            "{}",
            "{}",
            json.dumps({"event_id": event_id, "title": title}, ensure_ascii=False),
            "2026-07-19T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO evidence_refs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            evidence_ref_id,
            activity_event_id,
            "title",
            title,
            "source_text",
            "wechat_article",
            "source-key",
            "sha256:source",
            "Account",
            "2026-07-18",
            title,
            "short_quote",
            "",
            "not_available",
            0.92,
            "2026-07-19T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO prov_activities VALUES (?,?,?,?,?,?,?,?)",
        ("prov:1", "prov.v1", "test", "2026-07-19", r"C:\private\current.json", "", "", "{}"),
    )
    conn.commit()
    conn.close()


def protected_snapshot(path: Path) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(path)
    try:
        return {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in (
                "canonical_build_metadata",
                "activity_event_detail",
                "activity_evidence_ref",
                "performance_event",
                "canonical_event",
                "search_document",
                "graph_window_cache",
            )
        }
    finally:
        conn.close()


def test_real_schema_cumulative_merge_is_idempotent_and_preserves_projections(tmp_path):
    base = tmp_path / "base.sqlite"
    old_sidecar = tmp_path / "old.sqlite"
    current_sidecar = tmp_path / "current.sqlite"
    repeated_sidecar = tmp_path / "current-repeated.sqlite"
    out = tmp_path / "run" / "atlas.sqlite"
    make_real_serving_base(base)
    make_sidecar_db(old_sidecar, event_id="old-event", package="weekly-202605", title="Old Title")
    make_sidecar_db(current_sidecar, event_id="new-event", package="weekly-202607", title="New Title")
    make_sidecar_db(
        repeated_sidecar,
        event_id="new-event",
        package="weekly-202607-rerun",
        title="New Title enriched",
        activity_event_id="ae:different-package:new-event",
        evidence_ref_id="er:different-package:new-event",
    )
    protected_before = protected_snapshot(base)

    report = merge.build_activity_candidate_db(
        base,
        [old_sidecar, current_sidecar, repeated_sidecar],
        out,
        report_dir=tmp_path / "report",
        import_id="import-test",
        source_hashes={"current_sha256": "abc", "manifest_sha256": "def"},
    )

    assert report["decision"] == "activity_source_namespace_merged_into_derived_candidate_db"
    assert report["candidate_counts"]["activity_events"] == 2
    assert report["candidate_counts"]["evidence_refs"] == 3
    assert report["current_event_ids_present"] is True
    assert report["protected_tables_unchanged"] is True
    assert report["safety"]["raw_url_leak_hits"] == []
    assert protected_snapshot(base) == protected_before
    assert protected_snapshot(out) == protected_before

    conn = sqlite3.connect(out)
    try:
        row = conn.execute(
            "SELECT title, first_publish_package, latest_publish_package, last_import_id "
            "FROM atlas_activity_events WHERE event_id='new-event'"
        ).fetchone()
        assert row == ("New Title enriched", "weekly-202607", "weekly-202607-rerun", "import-test")
        assert conn.execute("SELECT count(DISTINCT event_id) FROM atlas_activity_events").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM atlas_activity_import_watermark").fetchone()[0] == 1
        assert conn.execute(
            "SELECT value FROM build_metadata WHERE key='atlas_activity_projection_status'"
        ).fetchone()[0] == "source_namespace_only"
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='atlas_activity_prov_activities'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_invalid_sidecar_never_replaces_existing_output(tmp_path):
    base = tmp_path / "base.sqlite"
    sidecar = tmp_path / "invalid.sqlite"
    out = tmp_path / "out.sqlite"
    make_real_serving_base(base)
    sqlite3.connect(sidecar).close()
    out.write_bytes(b"existing-output")

    try:
        merge.build_activity_candidate_db(base, [sidecar], out)
    except (ValueError, sqlite3.Error):
        pass
    else:
        raise AssertionError("invalid sidecar must fail closed")

    assert out.read_bytes() == b"existing-output"
