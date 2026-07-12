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

from adjudicate_weak_key_candidates import ensure_store, llm_adjudicate

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


def main() -> None:
    test_existing_store_migrates_evidence_columns()
    test_zero_budget_never_creates_a_cloud_client()
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
