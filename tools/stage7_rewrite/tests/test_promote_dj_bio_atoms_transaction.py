from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "tools" / "stage7_rewrite" / "scripts" / "promote_dj_bio_atoms.py"


def load_module():
    spec = importlib.util.spec_from_file_location("promote_dj_bio_atoms_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_fixture(data_root: Path, *, include_db: bool = True) -> tuple[Path, Path]:
    index_path = data_root / "atlas_index.json.gz"
    db_path = data_root / "atlas_miniapp.sqlite"
    data_root.mkdir(parents=True, exist_ok=True)
    index = {
        "profiles": {
            "dj:Alice": {"n": "Alice", "b": "", "bs": ""},
            "dj:Bob": {"n": "Bob", "b": "", "bs": ""},
        },
        "bio_atoms": {
            "dj:Alice": [
                {
                    "t": "Alice is a Shanghai based producer and selector known for deep electronic music.",
                    "cf": 0.9,
                    "sr": "fixture:alice",
                    "lang": "en",
                }
            ],
            "dj:Bob": [
                {
                    "t": "Bob is a Beijing based artist and resident selector with a long-running radio show.",
                    "cf": 0.8,
                    "sr": "fixture:bob",
                    "lang": "en",
                }
            ],
        },
    }
    index_path.write_bytes(
        gzip.compress(
            json.dumps(index, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            mtime=0,
        )
    )
    if include_db:
        connection = sqlite3.connect(db_path)
        connection.execute(
            """
            CREATE TABLE dj_profile (
                dj_id TEXT PRIMARY KEY,
                display_name TEXT,
                normalized_name TEXT,
                bio TEXT,
                bio_source TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO dj_profile VALUES (?, ?, ?, ?, ?)",
            ("dj-alice", "Alice", "alice", "", ""),
        )
        connection.commit()
        connection.close()
    return index_path, db_path


def load_index(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def test_missing_database_is_a_hard_failure_and_index_is_unchanged(tmp_path: Path) -> None:
    promotion = load_module()
    index_path, db_path = write_fixture(tmp_path / "candidate", include_db=False)
    before = index_path.read_bytes()

    with pytest.raises(FileNotFoundError, match="required Atlas promotion artifact missing"):
        promotion.promote_dj_bio_atoms(
            index_path=index_path,
            db_path=db_path,
            write=True,
            transaction_id="missing-db",
        )

    assert index_path.read_bytes() == before


def test_explicit_candidate_paths_emit_counts_and_before_after_digests(tmp_path: Path) -> None:
    promotion = load_module()
    data_root = tmp_path / "publish_transactions" / "run-001" / "staged_data"
    index_path, db_path = write_fixture(data_root)
    checkout_sentinel = tmp_path / "checkout" / "data" / "atlas_index.json.gz"
    checkout_sentinel.parent.mkdir(parents=True)
    checkout_sentinel.write_bytes(b"checkout must remain untouched")
    checkout_before = checkout_sentinel.read_bytes()
    before_index = digest(index_path)
    before_db = digest(db_path)
    report_path = data_root / "dj_bio_promotion.json"

    report = promotion.promote_dj_bio_atoms(
        index_path=index_path,
        db_path=db_path,
        write=True,
        transaction_id="run-001",
        report_path=report_path,
    )

    assert checkout_sentinel.read_bytes() == checkout_before
    assert report["schema_version"] == "dj_bio_promotion_transaction.v1"
    assert report["transaction_id"] == "run-001"
    assert report["selected_count"] == 2
    assert report["matched_count"] == 1
    assert report["unmatched_count"] == 1
    assert report["db_update_count"] == 1
    assert report["index_update_count"] == 1
    assert report["write_applied"] is True
    assert report["committed"] is True
    assert report["changed"] is True
    assert report["before"]["atlas_index.json.gz"]["sha256"] == before_index
    assert report["before"]["atlas_miniapp.sqlite"]["sha256"] == before_db
    assert report["after"]["atlas_index.json.gz"]["sha256"] == digest(index_path)
    assert report["after"]["atlas_miniapp.sqlite"]["sha256"] == digest(db_path)
    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    assert load_index(index_path)["profiles"]["dj:Alice"]["b"].startswith("Alice is")
    assert load_index(index_path)["profiles"]["dj:Bob"]["b"] == ""
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT bio, bio_source FROM dj_profile WHERE dj_id='dj-alice'"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None and row[0].startswith("Alice is")
    assert row[1] == "fixture:alice"


def test_dry_run_reports_matches_without_mutating_candidate(tmp_path: Path) -> None:
    promotion = load_module()
    index_path, db_path = write_fixture(tmp_path / "candidate")
    before_index = index_path.read_bytes()
    before_db = db_path.read_bytes()

    report = promotion.promote_dj_bio_atoms(
        index_path=index_path,
        db_path=db_path,
        write=False,
        transaction_id="dry-run",
    )

    assert report["matched_count"] == 1
    assert report["db_update_count"] == 1
    assert report["index_update_count"] == 1
    assert report["write_applied"] is False
    assert report["committed"] is False
    assert report["changed"] is False
    assert index_path.read_bytes() == before_index
    assert db_path.read_bytes() == before_db
