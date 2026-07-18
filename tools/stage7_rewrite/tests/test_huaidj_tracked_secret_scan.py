from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SCRIPT = ROOT / "scripts" / "scan_huaidj_tracked_secrets.py"
SPEC = importlib.util.spec_from_file_location("scan_huaidj_tracked_secrets", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_tracked_huaidj_sources_have_no_auth_literals() -> None:
    report = MODULE.scan_repo(REPO)
    assert report["findings"] == []
    assert report["ok"] is True


def test_scanner_reports_rules_without_echoing_secret_values() -> None:
    secret = "a" * 32
    findings = MODULE.scan_text(
        "fixture.ps1",
        f'$env:MPTEXT_AUTH_KEY = "{secret}"',  # secret-scan: allow-test-fixture
    )
    assert {item["rule"] for item in findings} == {
        "literal_mptext_auth_assignment",
        "auth_context_32_hex_literal",
    }
    assert secret not in repr(findings)


def test_legacy_launcher_is_env_only_delegator() -> None:
    launcher = (ROOT / "scripts" / "run_pipeline_background.ps1").read_text(encoding="utf-8")
    assert "HUAIDJ_REPO" in launcher
    assert "run_openclaw_weekly_daily_publish.ps1" in launcher
    assert "C:\\code\\githubstar\\wechathtmldownload" not in launcher
    assert "$env:MPTEXT_AUTH_KEY =" not in launcher
