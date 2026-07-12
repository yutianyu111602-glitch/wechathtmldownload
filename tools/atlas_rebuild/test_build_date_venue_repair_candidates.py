"""Offline smoke for the Phase 2 date/venue repair candidate builder.

Usage:
  python test_build_date_venue_repair_candidates.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    result = subprocess.run(
        [sys.executable, "build_date_venue_repair_candidates.py", "--self-check"],
        cwd=HERE,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"date/venue repair self-check failed:\n{result.stdout}\n{result.stderr}"
    assert "self-check OK" in result.stdout
    print(result.stdout)


if __name__ == "__main__":
    main()
