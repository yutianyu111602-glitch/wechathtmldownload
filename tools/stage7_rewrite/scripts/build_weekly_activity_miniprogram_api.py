#!/usr/bin/env python3
"""Compatibility entrypoint for the weekly mini-program API builder."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


IMPL_PATH = Path(__file__).resolve().parent / "archive_old" / "build_weekly_activity_miniprogram_api.py"
SPEC = importlib.util.spec_from_file_location("_weekly_miniprogram_api_impl", IMPL_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load implementation: {IMPL_PATH}")
_impl = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = _impl
SPEC.loader.exec_module(_impl)

for _name in dir(_impl):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_impl, _name)


if __name__ == "__main__":
    raise SystemExit(_impl.main())
