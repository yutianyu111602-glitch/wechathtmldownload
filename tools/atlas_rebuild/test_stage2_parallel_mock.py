"""Smoke-test Stage2 parallel single-writer mode with the mock backend."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))


def _make_clean_db(work_dir: str, n: int = 9) -> None:
    con = sqlite3.connect(os.path.join(work_dir, "clean.sqlite"))
    con.executescript(
        """
        CREATE TABLE clean (
          token TEXT PRIMARY KEY,
          account_key TEXT, title TEXT,
          clean_text TEXT, text_len INTEGER,
          poster_json TEXT,
          poster_candidates_json TEXT,
          poster_selection_report_json TEXT,
          poster_count INTEGER,
          dup_group TEXT, route TEXT, status TEXT,
          article_type TEXT,
          should_process_text INTEGER,
          should_process_images INTEGER,
          image_route_reason TEXT,
          classification_confidence REAL,
          classification_reasons TEXT
        );
        """
    )
    for i in range(n):
        con.execute(
            "INSERT INTO clean VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"parallel_mock_{i}",
                "acct",
                f"Parallel Mock {i}",
                "Electronic music event, Friday, club, DJ A / DJ B.",
                64,
                json.dumps([], ensure_ascii=False),
                "[]",
                "[]",
                0,
                None,
                "needs_vision",
                "clean",
                "event",
                1,
                1,
                "test",
                1.0,
                "[]",
            ),
        )
    con.commit()
    con.close()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="atlas_stage2_parallel_") as work_dir:
        _make_clean_db(work_dir)
        env = os.environ.copy()
        env["ATLAS_WORK_DIR"] = work_dir
        env.setdefault("PYTHONUTF8", "1")
        cmd = [
            sys.executable,
            os.path.join(HERE, "stage2_extract.py"),
            "--backend",
            "mock",
            "--route",
            "needs_vision",
            "--workers",
            "3",
            "--limit",
            "9",
        ]
        result = subprocess.run(cmd, cwd=HERE, env=env, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            return result.returncode
        con = sqlite3.connect(os.path.join(work_dir, "extractions.sqlite"))
        rows = con.execute("SELECT status, COUNT(*) FROM extractions GROUP BY status").fetchall()
        con.close()
        assert rows == [("extracted", 9)], rows
    print("stage2 parallel mock smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
