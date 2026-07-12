"""Offline smoke for the weak-key deterministic adjudicator (W1).

Usage:
  python test_adjudicate_weak_key_candidates.py
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from adjudicate_weak_key_candidates import adjudicate, ensure_store, llm_adjudicate

HERE = Path(__file__).resolve().parent


def test_existing_store_migrates_evidence_columns() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_adjudicate_store_migration_") as tmp:
        decisions = Path(tmp) / "decisions.sqlite"
        con = sqlite3.connect(decisions)
        con.execute(
            """
            CREATE TABLE weak_key_merge_decision (
              pair_key TEXT PRIMARY KEY,event_date TEXT,venue_id TEXT,title_norm_a TEXT,title_norm_b TEXT,
              title_display_a TEXT,title_display_b TEXT,title_similarity REAL,tier TEXT,decision TEXT,
              method TEXT,confidence REAL,reason TEXT,llm_verdict_raw TEXT,decided_at TEXT
            )
            """
        )
        ensure_store(con)
        columns = {row[1] for row in con.execute("PRAGMA table_info(weak_key_merge_decision)")}
        con.close()
        assert {"shared_source_count", "shared_dj_count", "dj_jaccard", "candidate_reason"} <= columns


def test_zero_budget_never_creates_a_cloud_client() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_adjudicate_zero_budget_") as tmp:
        decisions = Path(tmp) / "decisions.sqlite"
        con = sqlite3.connect(decisions)
        ensure_store(con)
        con.execute(
            """INSERT INTO weak_key_merge_decision (
              pair_key,event_date,venue_id,title_norm_a,title_norm_b,title_display_a,title_display_b,
              title_similarity,tier,decision,method,confidence,reason,llm_verdict_raw,decided_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "pair",
                "2026-01-01",
                "venue",
                "title a",
                "title b",
                "Title A",
                "Title B",
                0.9,
                "pending",
                "pending_llm",
                "",
                0.0,
                "fixture",
                "",
                "",
            ),
        )
        con.commit()
        con.close()

        report = llm_adjudicate(decisions, 0, 20, 0, None)

        assert report["model"] == "not_called"
        assert report["spent_rmb_estimate"] == 0
        assert report["run_counts"]["pending_selected"] == 1
        assert report["run_counts"]["budget_stopped"] == 1


def test_stronger_evidence_requeues_only_unresolved_decisions() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas_adjudicate_evidence_requeue_") as tmp:
        root = Path(tmp)
        candidates = root / "candidates.sqlite"
        con = sqlite3.connect(candidates)
        con.executescript(
            """
            CREATE TABLE canonical_event (
              canonical_event_id TEXT PRIMARY KEY,event_date TEXT,venue_id TEXT,venue_name TEXT,
              title_norm TEXT,title_display TEXT
            );
            CREATE TABLE canonical_event_merge_review_candidate (
              canonical_event_id_a TEXT,canonical_event_id_b TEXT,event_date TEXT,venue_id TEXT,
              title_display_a TEXT,title_display_b TEXT,title_similarity REAL,review_state TEXT,
              shared_source_count INTEGER,shared_dj_count INTEGER,dj_jaccard REAL,candidate_reason TEXT
            );
            INSERT INTO canonical_event VALUES
              ('a','2026-05-02','venue:vervo','VERVO','无形之夜','无形之夜'),
              ('b','2026-05-02','venue:vervo','VERVO','无形有形派对','无形有形派对');
            INSERT INTO canonical_event_merge_review_candidate VALUES
              ('a','b','2026-05-02','venue:vervo','无形之夜','无形有形派对',0.4,'needs_review',1,3,1.0,'shared_source_lineup');
            """
        )
        con.close()

        decisions = root / "decisions.sqlite"
        store = sqlite3.connect(decisions)
        ensure_store(store)
        pair_key = "2026-05-02|venue:vervo|无形之夜|无形有形派对"
        store.execute(
            """INSERT INTO weak_key_merge_decision (
              pair_key,event_date,venue_id,title_norm_a,title_norm_b,title_display_a,title_display_b,
              title_similarity,tier,decision,method,confidence,reason,llm_verdict_raw,decided_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pair_key,"2026-05-02","venue:vervo","无形之夜","无形有形派对","无形之夜","无形有形派对",
                0.4,"d_low_sim","needs_human","llm",0.0,"old title-only review","unsure","2026-01-01",
            ),
        )
        store.commit()
        store.close()

        report = adjudicate(candidates, decisions, None)
        assert report["run_counts"]["evidence_backfilled"] == 1
        assert report["run_counts"]["evidence_requeued"] == 1

        store = sqlite3.connect(decisions)
        row = store.execute(
            "SELECT decision,method,shared_source_count,shared_dj_count,dj_jaccard,candidate_reason FROM weak_key_merge_decision WHERE pair_key=?",
            (pair_key,),
        ).fetchone()
        store.close()
        assert row == ("pending_llm", "evidence_requeue", 1, 3, 1.0, "shared_source_lineup")


def main() -> None:
    test_existing_store_migrates_evidence_columns()
    test_zero_budget_never_creates_a_cloud_client()
    test_stronger_evidence_requeues_only_unresolved_decisions()
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "adjudicate_weak_key_candidates.py", "--self-check"],
        cwd=HERE,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"weak-key adjudicator self-check failed:\n{result.stdout}\n{result.stderr}"
    assert "self-check OK" in result.stdout
    print(result.stdout)


if __name__ == "__main__":
    main()
