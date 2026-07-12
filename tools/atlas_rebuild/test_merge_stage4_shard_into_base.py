"""Offline smoke for the Stage4 shard-into-base merge script.

Usage:
  python test_merge_stage4_shard_into_base.py
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
        [sys.executable, "merge_stage4_shard_into_base.py", "--self-check"],
        cwd=HERE,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"shard merge self-check failed:\n{result.stdout}\n{result.stderr}"
    assert "self-check OK" in result.stdout
    assert "incoming identity manifest" in result.stdout.lower()
    print(result.stdout)


if __name__ == "__main__":
    main()
