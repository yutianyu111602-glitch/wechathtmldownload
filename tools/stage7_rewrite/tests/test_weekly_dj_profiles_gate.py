import csv
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "tools" / "stage7_rewrite" / "weekly_activity_next_week_pipeline.ps1"
WRAPPER = ROOT / "tools" / "stage7_rewrite" / "run_openclaw_weekly_daily_publish.ps1"


def test_pipeline_requires_dj_profiles_before_any_source_or_model_work() -> None:
    source = PIPELINE.read_text(encoding="utf-8-sig")

    assert "[switch]$RequireDjProfiles" in source
    assert "[ValidateRange(1000, 10000000)]" in source
    assert "[int]$MinDjProfileKeys = 1000" in source
    preflight = source.index('if ($RequireDjProfiles) {')
    first_source_step = source.index("# ─── Step 0:")
    first_model_step = source.index("# ─── Step 3:")
    assert preflight < first_source_step < first_model_step
    assert "Import-Csv -LiteralPath $DJ_PROFILES" in source[preflight:first_source_step]
    assert '($djProfileHeaders -contains "name")' in source[preflight:first_source_step]
    assert "DJ profile CSV has fewer unique non-empty names than the production minimum" in source[preflight:first_source_step]


def test_pipeline_checks_exact_entity_registry_keys_and_disables_fallback() -> None:
    source = PIPELINE.read_text(encoding="utf-8-sig")

    entity_step = source.index("# ─── Step 3.5:")
    aggregate_step = source.index("# ─── Step 3.6:")
    entity_section = source[entity_step:aggregate_step]
    assert "entity_enrichment_summary.json" in entity_section
    assert 'weekly_entity_enrichment.v1' in entity_section
    assert "dj_profiles_keys" in entity_section
    assert "[int]$entitySummary.dj_profiles_keys -lt $MinDjProfileKeys" in entity_section
    assert "Required DJ entity enrichment output is missing; fallback is forbidden" in entity_section


def test_deploy_wrapper_enforces_source_and_pack_evidence_even_for_skip_build() -> None:
    source = WRAPPER.read_text(encoding="utf-8-sig")

    assert "[string]$DjProfilesPath = \"\"" in source
    assert "[ValidateRange(1000, 10000000)]" in source
    assert "[int]$MinDjProfileKeys = 1000" in source
    assert "function Assert-DjProfilesSourceReady" in source
    assert "function Assert-DjProfilesEnrichmentEvidence" in source
    source_gate = source.index('Invoke-RunStep "Validate production DJ profile source"')
    build = source.index("if (-not $SkipBuild) {")
    evidence_gate = source.index('Invoke-RunStep "Validate production DJ entity enrichment evidence"')
    merge = source.index("if (-not $DisableIncrementalMerge) {", build)
    assert source_gate < build < evidence_gate < merge
    assert "RequireDjProfiles = $true" in source[build:evidence_gate]
    assert "MinDjProfileKeys = $MinDjProfileKeys" in source[build:evidence_gate]
    assert "Assert-DjProfilesEnrichmentEvidence -PackPath $PackDir" in source[evidence_gate:merge]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is required")
def test_minimum_cannot_be_lowered_below_production_contract(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            shutil.which("pwsh") or "pwsh",
            "-NoProfile",
            "-File",
            str(PIPELINE),
            "-DryRun",
            "-RequireDjProfiles",
            "-MinDjProfileKeys",
            "999",
            "-DjProfilesPath",
            str(tmp_path / "unused.csv"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "HUAIDJ_PYTHON": sys.executable},
        timeout=30,
    )

    assert result.returncode != 0
    assert "1000" in (result.stdout + result.stderr)


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 is required")
def test_source_preflight_rejects_many_rows_without_valid_unique_names(tmp_path: Path) -> None:
    csv_path = tmp_path / "invalid_profiles.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "entity_id"])
        writer.writeheader()
        for index in range(1200):
            writer.writerow({"name": "" if index % 2 == 0 else "duplicate", "entity_id": index})

    result = subprocess.run(
        [
            shutil.which("pwsh") or "pwsh",
            "-NoProfile",
            "-File",
            str(PIPELINE),
            "-DryRun",
            "-RequireDjProfiles",
            "-DjProfilesPath",
            str(csv_path),
            "-WeekStart",
            "2026-07-18",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "HUAIDJ_PYTHON": sys.executable},
        timeout=30,
    )

    assert result.returncode != 0
    assert "fewer unique non-empty names" in (result.stdout + result.stderr)
