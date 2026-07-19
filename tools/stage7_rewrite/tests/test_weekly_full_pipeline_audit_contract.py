from __future__ import annotations

import re
import runpy
from pathlib import Path
from zoneinfo import ZoneInfoNotFoundError


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_weekly_miniprogram_all_pipelines.py"


def load_audit() -> dict:
    return runpy.run_path(str(SCRIPT), run_name="__test__")


def test_audit_has_windows_shanghai_timezone_fallback() -> None:
    namespace = load_audit()
    function = namespace["today_shanghai"]

    def missing_zone(_name: str):
        raise ZoneInfoNotFoundError("tzdata intentionally unavailable")

    function.__globals__["ZoneInfo"] = missing_zone
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", function())


def test_audit_storage_slug_matches_package_writer_and_cloudrun_reader() -> None:
    namespace = load_audit()
    assert namespace["storage_slug"](
        "陀地音乐TOTE MUSIC:d78318b809090dd4:schedule:20260718:21"
    ) == "u9640u5730u97f3u4e50tote-musicu3ad78318b809090dd4u3ascheduleu3a20260718u3a21"


def test_audit_cache_contract_tracks_visibility_v2_namespace() -> None:
    namespace = load_audit()
    assert namespace["EXPECTED_CACHE_PREFIX"] == "weeklyActivityApiCache:v20260719-visibility-v2:"
