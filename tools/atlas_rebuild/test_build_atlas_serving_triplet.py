from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "build_atlas_serving_triplet.py"
DATASET_ID = "atlas-release-20260719-integration-0001"


def _write_source_dbs(root: Path) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=False)
    v2 = root / "atlas_serving_v2.sqlite"
    serving = root / "atlas_serving_candidate.sqlite"
    miniapp = root / "atlas_miniapp.sqlite"

    con = sqlite3.connect(v2)
    con.executescript(
        """
        CREATE TABLE subject(
          subject_id TEXT PRIMARY KEY, subject_type TEXT, display_name TEXT,
          normalized_name TEXT, name_en TEXT, aliases_json TEXT,
          city_primary TEXT, event_count INTEGER, relation_count INTEGER,
          source_count INTEGER, confidence REAL, first_seen_at TEXT,
          last_seen_at TEXT, taxon_path TEXT, public_state TEXT
        );
        CREATE TABLE dj_profile(
          subject_id TEXT PRIMARY KEY, name_en TEXT, nationality TEXT,
          origin_city TEXT, roles_json TEXT, styles_json TEXT, genre TEXT,
          social_json TEXT, gear TEXT, bio_snippet TEXT,
          affiliations_json TEXT, venue_count INTEGER, org_count INTEGER
        );
        CREATE TABLE relation(
          relation_id TEXT PRIMARY KEY, src_subject_id TEXT,
          dst_subject_id TEXT, relation_type TEXT, weight REAL,
          same_event_count INTEGER, b2b_count INTEGER, label_zh TEXT,
          first_seen_at TEXT, last_seen_at TEXT, public_state TEXT,
          sample_evidence_json TEXT
        );
        INSERT INTO subject VALUES
          ('dj:alpha','dj','Alpha','alpha',NULL,'[]','上海',3,2,2,1.0,'2026-01-01','2026-07-19','atlas/dj','public'),
          ('dj:beta','dj','Beta','beta',NULL,'[]','上海',2,2,2,1.0,'2026-01-01','2026-07-19','atlas/dj','public'),
          ('venue:club','venue','Club','club',NULL,'[]','上海',4,2,2,1.0,'2026-01-01','2026-07-19','atlas/venue','public');
        INSERT INTO dj_profile VALUES
          ('dj:alpha',NULL,NULL,NULL,NULL,NULL,NULL,'{}',NULL,'Alpha profile',NULL,1,0),
          ('dj:beta',NULL,NULL,NULL,NULL,NULL,NULL,'{}',NULL,'Beta profile',NULL,1,0);
        INSERT INTO relation VALUES
          ('rel:ab','dj:alpha','dj:beta','collab',10.0,2,0,'同台','','','public','[]'),
          ('rel:ac','dj:alpha','venue:club','resident_at',8.0,0,0,'常驻','','','public','[]'),
          ('rel:bc','dj:beta','venue:club','resident_at',6.0,0,0,'常驻','','','public','[]');
        """
    )
    con.commit()
    con.close()

    con = sqlite3.connect(serving)
    con.executescript(
        """
        CREATE TABLE evidence_ref(
          source_ref_id TEXT, source_hash TEXT, source_account TEXT,
          source_title TEXT, post_date TEXT, public_snippet TEXT,
          source_kind TEXT, public_url_allowed INTEGER
        );
        CREATE TABLE dj_event(
          dj_id TEXT,event_id TEXT,starts_at TEXT,time_text TEXT,
          event_title TEXT,venue_id TEXT,venue_name TEXT,city TEXT,
          source_ref_id TEXT,confidence REAL
        );
        CREATE TABLE dj_venue_rollup(
          dj_id TEXT,venue_id TEXT,venue_name TEXT,city TEXT,event_count INTEGER,
          first_seen_at TEXT,last_seen_at TEXT,score REAL
        );
        CREATE TABLE dj_relation_rollup(
          src_dj_id TEXT,dst_dj_id TEXT,same_event_count INTEGER,
          same_label_count INTEGER,same_venue_count INTEGER,
          same_source_context_count INTEGER,b2b_count INTEGER,
          source_diversity INTEGER,first_seen_at TEXT,last_seen_at TEXT,
          relation_score REAL,relation_label_zh TEXT,
          sample_evidence_json TEXT,public_state TEXT
        );
        INSERT INTO evidence_ref VALUES
          ('src:1','hash-1','Club','Night','2026-07-19','','article',0);
        INSERT INTO dj_event VALUES
          ('dj:alpha','event:1','2026-07-19','','Night','venue:club','Club','上海','src:1',0.9),
          ('dj:beta','event:1','2026-07-19','','Night','venue:club','Club','上海','src:1',0.9);
        INSERT INTO dj_venue_rollup VALUES
          ('dj:alpha','venue:club','Club','上海',1,'2026-07-19','2026-07-19',1.0),
          ('dj:beta','venue:club','Club','上海',1,'2026-07-19','2026-07-19',1.0);
        INSERT INTO dj_relation_rollup VALUES
          ('dj:alpha','dj:beta',1,0,1,1,0,1,'2026-07-19','2026-07-19',5.0,'同台','[]','public');
        """
    )
    con.commit()
    con.close()

    con = sqlite3.connect(miniapp)
    con.executescript(
        """
        CREATE TABLE subject(
          subject_id TEXT PRIMARY KEY, subject_type TEXT, display_name TEXT,
          normalized_name TEXT, aliases_json TEXT, city_primary TEXT,
          event_count INTEGER, relation_count INTEGER
        );
        CREATE TABLE dj_collaborator(
          src_dj_id TEXT, dst_dj_id TEXT, same_event_count INTEGER,
          relation_label_zh TEXT, relation_score REAL
        );
        CREATE TABLE dj_venue(
          dj_id TEXT, venue_id TEXT, venue_name TEXT, city TEXT,
          event_count INTEGER, first_seen_at TEXT, last_seen_at TEXT
        );
        CREATE TABLE dj_profile(
          dj_id TEXT PRIMARY KEY, display_name TEXT, normalized_name TEXT,
          aliases_json TEXT, city_primary TEXT, event_count INTEGER,
          venue_count INTEGER, collaborator_count INTEGER, first_seen_at TEXT,
          last_seen_at TEXT, bio TEXT, bio_source TEXT, avatar_url TEXT
        );
        CREATE TABLE dj_event(
          dj_id TEXT, event_id TEXT, starts_at TEXT, event_title TEXT,
          venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT,
          confidence REAL
        );
        CREATE TABLE source_ref(
          source_ref_id TEXT PRIMARY KEY, source_hash TEXT,
          source_account TEXT, source_title TEXT, post_date TEXT,
          source_kind TEXT
        );
        INSERT INTO subject VALUES
          ('dj:alpha','dj','Alpha','alpha','[]','上海',3,2),
          ('dj:beta','dj','Beta','beta','[]','上海',2,2),
          ('venue:club','venue','Club','club','[]','上海',4,2);
        INSERT INTO dj_collaborator VALUES
          ('dj:alpha','dj:beta',2,'同台',10.0);
        INSERT INTO dj_venue VALUES
          ('dj:alpha','venue:club','Club','上海',1,'2026-07-19','2026-07-19'),
          ('dj:beta','venue:club','Club','上海',1,'2026-07-19','2026-07-19');
        INSERT INTO dj_profile VALUES
          ('dj:alpha','Alpha','alpha','[]','上海',3,1,1,'2026-01-01','2026-07-19','Alpha profile','curated',''),
          ('dj:beta','Beta','beta','[]','上海',2,1,1,'2026-01-01','2026-07-19','Beta profile','curated','');
        INSERT INTO dj_event VALUES
          ('dj:alpha','event:1','2026-07-19','Night','venue:club','Club','上海','src:1',0.9),
          ('dj:beta','event:1','2026-07-19','Night','venue:club','Club','上海','src:1',0.9);
        INSERT INTO source_ref VALUES
          ('src:1','hash-1','Club','Night','2026-07-19','article');
        """
    )
    con.commit()
    con.close()
    return v2, serving, miniapp


def _load_gzip_json(path: Path) -> dict:
    return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))


def _stamp_upstream_generation(paths: tuple[Path, ...], generation: str) -> None:
    for path in paths:
        con = sqlite3.connect(path)
        try:
            con.execute("CREATE TABLE build_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            con.execute(
                "INSERT INTO build_metadata VALUES ('upstream_generation_id', ?)",
                (generation,),
            )
            con.commit()
        finally:
            con.close()


def _run_build(tmp_path: Path, out_dir: Path) -> subprocess.CompletedProcess[str]:
    v2, serving, miniapp = _write_source_dbs(tmp_path / "sources")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--v2",
            str(v2),
            "--serving",
            str(serving),
            "--miniapp-db",
            str(miniapp),
            "--frozen-release-id",
            "atlas-test-frozen-release-20260719",
            "--out-dir",
            str(out_dir),
            "--max-nodes",
            "20",
            "--max-edges",
            "40",
            "--neighbor-cap",
            "20",
        ],
        cwd=HERE,
        capture_output=True,
        text=True,
    )


def test_builds_one_atomic_external_triplet_with_shared_dataset_id(tmp_path: Path) -> None:
    out_dir = tmp_path / "external-candidate" / "atlas-generation"

    result = _run_build(tmp_path, out_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    expected = {
        "atlas_starmap.json",
        "atlas_starmap.js",
        "atlas_index.json.gz",
        "atlas_index.json.gz.manifest.json",
        "atlas_neighborhood.json.gz",
        "atlas_triplet_manifest.json",
    }
    assert {item.name for item in out_dir.iterdir()} == expected

    static_payload = json.loads((out_dir / "atlas_starmap.json").read_text(encoding="utf-8"))
    static_js = (out_dir / "atlas_starmap.js").read_text(encoding="utf-8")
    index_payload = _load_gzip_json(out_dir / "atlas_index.json.gz")
    neighborhood_payload = _load_gzip_json(out_dir / "atlas_neighborhood.json.gz")
    manifest = json.loads((out_dir / "atlas_triplet_manifest.json").read_text(encoding="utf-8"))

    assert static_js == "module.exports = " + json.dumps(
        static_payload, ensure_ascii=False, separators=(",", ":")
    ) + ";\n"
    dataset_ids = {
        static_payload["datasetId"],
        index_payload["datasetId"],
        neighborhood_payload["datasetId"],
        manifest["datasetId"],
    }
    assert len(dataset_ids) == 1
    identity_payload = {
        role: {"sha256": row["sha256"], "size": row["size"]}
        for role, row in sorted(manifest["sourceDigests"].items())
    }
    expected_snapshot_id = "atlas-triplet-sha256-" + hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert manifest["datasetId"] == expected_snapshot_id
    assert manifest["sourceSnapshot"] == {
        "method": "sqlite3.Connection.backup",
        "sqliteRoles": ["miniapp", "serving", "v2"],
        "exportersReadFrozenCopies": True,
        "temporarySnapshotsRetained": False,
        "releaseIdentityGuard": {
            "mode": "explicit_frozen_release_identity",
            "releaseIdentity": "atlas-test-frozen-release-20260719",
            "roles": ["miniapp", "serving", "v2"],
            "markerPresent": {"miniapp": False, "serving": False, "v2": False},
            "sqliteDataVersionGuarded": True,
            "beforeAndAfterEachRoleVerified": True,
        },
    }
    assert manifest["decision"] == "atlas_serving_triplet_candidate_ready"
    assert manifest["productionWriteExecuted"] is False
    assert manifest["deployExecuted"] is False
    assert manifest["verification"]["pathLeakCount"] == 0
    assert manifest["verification"]["neighborhoodUnknownSubjectCount"] == 0
    assert set(manifest["artifacts"]) == {
        "atlas_starmap.json",
        "atlas_starmap.js",
        "atlas_index.json.gz",
        "atlas_index.json.gz.manifest.json",
        "atlas_neighborhood.json.gz",
    }
    serialized = json.dumps(
        [static_payload, index_payload, neighborhood_payload, manifest],
        ensure_ascii=False,
    )
    assert str(tmp_path) not in serialized


def test_rejects_missing_mismatched_or_path_leaking_artifacts(tmp_path: Path) -> None:
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "atlas_starmap.json").write_text(
        json.dumps({"schemaVersion": "atlas.mp.starmap.v2", "datasetId": DATASET_ID, "nodes": [{"u": "dj:a"}], "edges": [], "counts": {"nodes": 1, "edges": 0}}),
        encoding="utf-8",
    )
    (candidate / "atlas_starmap.js").write_text(
        "module.exports = " + (candidate / "atlas_starmap.json").read_text(encoding="utf-8") + ";\n",
        encoding="utf-8",
    )
    (candidate / "atlas_index.json.gz").write_bytes(
        gzip.compress(json.dumps({"v": 5, "datasetId": DATASET_ID, "subjects": [{"i": "dj:a"}]}).encode("utf-8"))
    )

    with pytest.raises(triplet.TripletValidationError, match="missing artifact"):
        triplet.verify_triplet(candidate, DATASET_ID)

    (candidate / "atlas_neighborhood.json.gz").write_bytes(
        gzip.compress(
            json.dumps(
                {
                    "schemaVersion": "atlas.miniapp.neighborhood_bundle.v1",
                    "datasetId": "atlas-release-other-generation-0002",
                    "generation": {"nodeCount": 1, "relationCount": 1, "subjectCount": 1, "edgeCount": 1, "perSubjectLimit": 60},
                    "byNode": {"dj:a": [{"u": "dj:a", "rt": "collab", "w": 1, "rs": 1}]},
                }
            ).encode("utf-8")
        )
    )
    with pytest.raises(triplet.TripletValidationError, match="datasetId mismatch"):
        triplet.verify_triplet(candidate, DATASET_ID)

    leaking = _load_gzip_json(candidate / "atlas_neighborhood.json.gz")
    leaking["datasetId"] = DATASET_ID
    leaking["generation"]["source"] = r"C:\Users\win\AppData\Local\Temp\atlas.sqlite"
    (candidate / "atlas_neighborhood.json.gz").write_bytes(
        gzip.compress(json.dumps(leaking).encode("utf-8"))
    )
    with pytest.raises(triplet.TripletValidationError, match="local path leak"):
        triplet.verify_triplet(candidate, DATASET_ID)


def test_local_path_gate_catches_general_posix_paths_but_allows_public_urls_and_routes() -> None:
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    for local_path in (
        "/home/alice/private/atlas.sqlite",
        "/mnt/c/code/private.db",
        "/srv/atlas/secret.sqlite",
        "/opt/huaidj/private/index.json",
        "/home",
        "/数据/私有/atlas.sqlite",
    ):
        findings = triplet.find_local_path_leaks({"artifact.json": {"source": local_path}})
        assert findings
        assert findings[0]["reason"] == "posix_absolute_path"

    assert triplet.find_local_path_leaks(
        {
            "artifact.json": {
                "publicUrl": "https://example.com/atlas/dj/alpha",
                "publicRoute": "/api/v1/atlas/dj/alpha",
                "staticRoute": "/atlas/starmap/alpha",
            }
        }
    ) == []

    key_findings = triplet.find_local_path_leaks(
        {"artifact.json": {"fieldEvidence": {"/home/alice/private/key.json": "safe value"}}}
    )
    assert key_findings
    assert key_findings[0]["field"].endswith(".<key>")


def test_refuses_repo_or_existing_output_and_leaves_no_partial_candidate(tmp_path: Path) -> None:
    out_dir = tmp_path / "already-exists"
    out_dir.mkdir()

    result = _run_build(tmp_path, out_dir)

    assert result.returncode != 0
    assert "out-dir must not already exist" in result.stderr
    assert list(out_dir.iterdir()) == []

    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    repo_output = HERE.parents[1] / "services" / "weekly_activity_cloudrun" / "data" / "triplet-test"
    with pytest.raises(ValueError, match="outside the repository"):
        triplet.validate_external_output_dir(repo_output)

    other_worktree = tmp_path / "other-worktree"
    (other_worktree / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="outside every Git worktree"):
        triplet.validate_external_output_dir(other_worktree / "candidate")

    runtime_data = tmp_path / "weekly_activity_cloudrun" / "data" / "candidate"
    with pytest.raises(ValueError, match="runtime data directory"):
        triplet.validate_external_output_dir(runtime_data)


def test_cross_artifact_subject_drift_fails_closed_before_candidate_appears(tmp_path: Path) -> None:
    v2, serving, miniapp = _write_source_dbs(tmp_path / "sources")
    con = sqlite3.connect(miniapp)
    con.execute(
        "INSERT INTO subject VALUES(?,?,?,?,?,?,?,?)",
        ("dj:orphan", "dj", "Orphan", "orphan", "[]", "上海", 1, 1),
    )
    con.execute(
        "INSERT INTO dj_collaborator VALUES(?,?,?,?,?)",
        ("dj:alpha", "dj:orphan", 1, "同台", 2.0),
    )
    con.commit()
    con.close()
    out_dir = tmp_path / "external-candidate" / "drifted-generation"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--v2",
            str(v2),
            "--serving",
            str(serving),
            "--miniapp-db",
            str(miniapp),
            "--frozen-release-id",
            "atlas-test-frozen-release-subject-drift",
            "--out-dir",
            str(out_dir),
        ],
        cwd=HERE,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "v2/miniapp subject identity mismatch" in result.stderr
    assert not out_dir.exists()
    assert not list(out_dir.parent.glob(f".{out_dir.name}.building-*"))


def test_preflight_proves_required_schema_and_cross_database_identity(tmp_path: Path) -> None:
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    v2, serving, miniapp = _write_source_dbs(tmp_path / "sources")

    report = triplet.preflight_inputs(v2=v2, serving=serving, miniapp_db=miniapp)

    assert report["decision"] == "atlas_serving_triplet_inputs_compatible"
    assert report["roles"]["v2"]["tables"]["subject"] == 3
    assert report["roles"]["serving"]["tables"]["dj_event"] == 2
    assert report["roles"]["miniapp"]["tables"]["subject"] == 3
    assert report["identity"]["v2SubjectCount"] == 3
    assert report["identity"]["miniappSubjectCount"] == 3
    assert report["identity"]["subjectIntersectionCount"] == 3
    assert report["identity"]["servingUnknownSubjectCount"] == 0


def test_miniapp_only_mode_generates_all_three_routes_from_one_identity_source(tmp_path: Path) -> None:
    _v2, _serving, miniapp = _write_source_dbs(tmp_path / "sources")
    out_dir = tmp_path / "external-candidate" / "miniapp-single-source"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--miniapp-db",
            str(miniapp),
            "--out-dir",
            str(out_dir),
            "--max-nodes",
            "20",
            "--max-edges",
            "40",
            "--neighbor-cap",
            "20",
        ],
        cwd=HERE,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    index_payload = _load_gzip_json(out_dir / "atlas_index.json.gz")
    static_payload = json.loads((out_dir / "atlas_starmap.json").read_text(encoding="utf-8"))
    neighborhood_payload = _load_gzip_json(out_dir / "atlas_neighborhood.json.gz")
    index_manifest = json.loads(
        (out_dir / "atlas_index.json.gz.manifest.json").read_text(encoding="utf-8")
    )
    triplet_manifest = json.loads(
        (out_dir / "atlas_triplet_manifest.json").read_text(encoding="utf-8")
    )

    assert index_payload["v"] == 5
    assert (out_dir / "atlas_index.json.gz").read_bytes()[4:8] == b"\x00\x00\x00\x00"
    assert (out_dir / "atlas_neighborhood.json.gz").read_bytes()[4:8] == b"\x00\x00\x00\x00"
    assert len(index_payload["subjects"]) == 3
    assert len(index_payload["profiles"]) == 2
    dataset_ids = {
        index_payload["datasetId"],
        static_payload["datasetId"],
        neighborhood_payload["datasetId"],
        index_manifest["datasetId"],
        triplet_manifest["datasetId"],
    }
    assert len(dataset_ids) == 1
    assert triplet_manifest["datasetId"] == (
        "atlas-miniapp-sha256-" + triplet_manifest["sourceDigests"]["miniapp"]["sha256"]
    )
    assert triplet_manifest["sourceMode"] == "miniapp_single_source"
    assert set(triplet_manifest["sourceDigests"]) == {"miniapp"}
    assert set(triplet_manifest["builderDigests"]) >= {
        "tripletOrchestrator",
        "miniappStarmapExporter",
        "miniappIndexExporter",
        "miniappNeighborhoodBridge",
        "neighborhoodExporter",
        "v2ReadmodelBuilder",
    }
    assert all(
        len(row["sha256"]) == 64 and row["size"] > 0
        for row in triplet_manifest["builderDigests"].values()
    )
    assert triplet_manifest["inputPreflight"]["identity"]["miniappSubjectCount"] == 3
    assert str(tmp_path) not in json.dumps(
        [index_payload, static_payload, neighborhood_payload, index_manifest, triplet_manifest],
        ensure_ascii=False,
    )


def test_live_source_change_after_snapshot_does_not_mix_atomic_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    _v2, _serving, miniapp = _write_source_dbs(tmp_path / "sources")
    out_dir = tmp_path / "external-candidate" / "source-raced"
    original_builder = triplet.build_neighborhood

    def build_then_mutate_source(*args, **kwargs):
        report = original_builder(*args, **kwargs)
        with miniapp.open("ab") as handle:
            handle.write(b"source-changed-after-read")
        return report

    monkeypatch.setattr(triplet, "build_neighborhood", build_then_mutate_source)

    manifest = triplet.build_triplet(
        miniapp_db=miniapp,
        dataset_id=None,
        out_dir=out_dir,
        max_nodes=20,
        max_edges=40,
        neighbor_cap=20,
    )

    assert out_dir.is_dir()
    assert manifest["sourceSnapshot"]["exportersReadFrozenCopies"] is True


def test_same_source_and_dataset_id_rebuild_byte_identically(tmp_path: Path) -> None:
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    _v2, _serving, miniapp = _write_source_dbs(tmp_path / "sources")
    first = tmp_path / "external-candidate" / "first"
    second = tmp_path / "external-candidate" / "second"
    for out_dir in (first, second):
        triplet.build_triplet(
            miniapp_db=miniapp,
            dataset_id=None,
            out_dir=out_dir,
            max_nodes=20,
            max_edges=40,
            neighbor_cap=20,
        )

    def digests(root: Path) -> dict[str, str]:
        return {
            item.name: hashlib.sha256(item.read_bytes()).hexdigest()
            for item in sorted(root.iterdir())
            if item.is_file()
        }

    assert digests(first) == digests(second)


def test_explicit_dataset_id_is_only_an_expected_snapshot_guard(tmp_path: Path) -> None:
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    _v2, _serving, miniapp = _write_source_dbs(tmp_path / "sources")
    out_dir = tmp_path / "external-candidate" / "wrong-explicit-id"
    with pytest.raises(triplet.TripletValidationError, match="does not match the immutable SQLite snapshot"):
        triplet.build_triplet(
            miniapp_db=miniapp,
            dataset_id=DATASET_ID,
            out_dir=out_dir,
            max_nodes=20,
            max_edges=40,
            neighbor_cap=20,
        )
    assert not out_dir.exists()
    assert not list(out_dir.parent.glob(f".{out_dir.name}.building-*"))


def test_wal_commits_are_frozen_into_one_snapshot_and_temporary_snapshot_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A commit between exporters must not create one mixed serving generation."""
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    _v2, _serving, miniapp = _write_source_dbs(tmp_path / "sources")
    writer = sqlite3.connect(miniapp)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute(
        "INSERT INTO subject VALUES(?,?,?,?,?,?,?,?)",
        ("dj:wal-before", "dj", "WAL Before", "wal before", "[]", "上海", 1, 0),
    )
    writer.commit()

    out_dir = tmp_path / "external-candidate" / "wal-generation"
    snapshot_paths: list[Path] = []
    original_builder = triplet.build_starmap_from_miniapp
    original_index_builder = triplet.export_index_from_miniapp
    original_neighborhood_builder = triplet.build_neighborhood

    def build_then_commit_to_live_source(*args, **kwargs):
        snapshot_paths.append(Path(args[0]))
        report = original_builder(*args, **kwargs)
        writer.execute(
            "INSERT INTO subject VALUES(?,?,?,?,?,?,?,?)",
            ("dj:wal-after", "dj", "WAL After", "wal after", "[]", "上海", 1, 0),
        )
        writer.commit()
        return report

    def capture_index_snapshot(*args, **kwargs):
        snapshot_paths.append(Path(args[0]))
        return original_index_builder(*args, **kwargs)

    def capture_neighborhood_snapshot(*args, **kwargs):
        snapshot_paths.append(Path(args[0]))
        return original_neighborhood_builder(*args, **kwargs)

    monkeypatch.setattr(triplet, "build_starmap_from_miniapp", build_then_commit_to_live_source)
    monkeypatch.setattr(triplet, "export_index_from_miniapp", capture_index_snapshot)
    monkeypatch.setattr(triplet, "build_neighborhood", capture_neighborhood_snapshot)
    try:
        manifest = triplet.build_triplet(
            miniapp_db=miniapp,
            dataset_id=None,
            out_dir=out_dir,
            max_nodes=20,
            max_edges=40,
            neighbor_cap=20,
        )
    finally:
        writer.close()

    index_payload = _load_gzip_json(out_dir / "atlas_index.json.gz")
    index_ids = {row["i"] for row in index_payload["subjects"]}
    assert "dj:wal-before" in index_ids
    assert "dj:wal-after" not in index_ids
    assert manifest["inputPreflight"]["identity"]["miniappSubjectCount"] == 4
    snapshot_digest = manifest["sourceDigests"]["miniapp"]["sha256"]
    assert manifest["datasetId"] == f"atlas-miniapp-sha256-{snapshot_digest}"
    assert len(snapshot_paths) == 3
    assert len(set(snapshot_paths)) == 1
    assert snapshot_paths[0] != miniapp
    assert all(not path.exists() for path in snapshot_paths)
    assert not list(out_dir.parent.glob(f".{out_dir.name}.building-*"))


def test_multi_role_backup_fails_closed_when_generation_marker_drifts_between_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    v2, serving, miniapp = _write_source_dbs(tmp_path / "sources")
    initial_generation = "atlas-upstream-generation-20260719-a"
    _stamp_upstream_generation((v2, serving, miniapp), initial_generation)
    out_dir = tmp_path / "external-candidate" / "multi-role-marker-raced"
    original_snapshot = triplet._sqlite_online_snapshot
    snapshot_calls = 0

    def snapshot_then_drift_another_role(*args, **kwargs):
        nonlocal snapshot_calls
        result = original_snapshot(*args, **kwargs)
        snapshot_calls += 1
        if snapshot_calls == 1:
            writer = sqlite3.connect(serving)
            try:
                writer.execute(
                    "UPDATE build_metadata SET value = ? WHERE key = 'upstream_generation_id'",
                    ("atlas-upstream-generation-20260719-b",),
                )
                writer.commit()
            finally:
                writer.close()
        return result

    monkeypatch.setattr(triplet, "_sqlite_online_snapshot", snapshot_then_drift_another_role)

    with pytest.raises(triplet.TripletValidationError, match="changed during multi-role snapshot"):
        triplet.build_triplet(
            v2=v2,
            serving=serving,
            miniapp_db=miniapp,
            out_dir=out_dir,
            max_nodes=20,
            max_edges=40,
            neighbor_cap=20,
        )

    assert not out_dir.exists()
    assert not list(out_dir.parent.glob(f".{out_dir.name}.building-*"))


def test_multi_role_without_marker_requires_explicit_frozen_release_identity(
    tmp_path: Path,
) -> None:
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    v2, serving, miniapp = _write_source_dbs(tmp_path / "sources")
    out_dir = tmp_path / "external-candidate" / "missing-release-identity"

    with pytest.raises(
        triplet.TripletValidationError,
        match="shared upstream generation marker or --frozen-release-id",
    ):
        triplet.build_triplet(
            v2=v2,
            serving=serving,
            miniapp_db=miniapp,
            out_dir=out_dir,
            max_nodes=20,
            max_edges=40,
            neighbor_cap=20,
        )

    assert not out_dir.exists()
    assert not list(out_dir.parent.glob(f".{out_dir.name}.building-*"))


def test_multi_role_backup_fails_closed_on_non_marker_commit_between_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sys.path.insert(0, str(HERE))
    import build_atlas_serving_triplet as triplet

    v2, serving, miniapp = _write_source_dbs(tmp_path / "sources")
    _stamp_upstream_generation(
        (v2, serving, miniapp),
        "atlas-upstream-generation-20260719-stable",
    )
    out_dir = tmp_path / "external-candidate" / "multi-role-data-raced"
    original_snapshot = triplet._sqlite_online_snapshot
    snapshot_calls = 0

    def snapshot_then_commit_data(*args, **kwargs):
        nonlocal snapshot_calls
        result = original_snapshot(*args, **kwargs)
        snapshot_calls += 1
        if snapshot_calls == 1:
            writer = sqlite3.connect(serving)
            try:
                writer.execute(
                    "INSERT INTO evidence_ref VALUES (?,?,?,?,?,?,?,?)",
                    (
                        "src:raced",
                        "hash-raced",
                        "Club",
                        "Raced",
                        "2026-07-19",
                        "",
                        "article",
                        0,
                    ),
                )
                writer.commit()
            finally:
                writer.close()
        return result

    monkeypatch.setattr(triplet, "_sqlite_online_snapshot", snapshot_then_commit_data)

    with pytest.raises(triplet.TripletValidationError, match="changed during multi-role snapshot"):
        triplet.build_triplet(
            v2=v2,
            serving=serving,
            miniapp_db=miniapp,
            out_dir=out_dir,
            max_nodes=20,
            max_edges=40,
            neighbor_cap=20,
        )

    assert not out_dir.exists()
    assert not list(out_dir.parent.glob(f".{out_dir.name}.building-*"))
