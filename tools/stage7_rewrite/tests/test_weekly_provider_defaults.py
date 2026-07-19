from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def test_openclaw_weekly_publish_defaults_to_online_qwen_vl() -> None:
    source = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8-sig")

    assert '[string]$PosterExtractionMode = "vl_direct_qwen"' in source


def test_atlas_bio_promotion_is_explicit_and_baked_before_deploy() -> None:
    source = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8-sig")

    assert "[switch]$PromoteDjBioAtoms" in source
    assert "if ($PromoteDjBioAtoms -and -not $DeployBackend)" in source
    assert "atlas_miniapp_bio_write_executed" in source
    assert source.index('Invoke-RunStep "Promote DJ bio atoms before baking deploy context"') < source.index(
        'Invoke-RunStep "Bake CloudRun deploy context"'
    )
    assert "Promote DJ bio atoms to atlas profiles" not in source


def test_weekly_wrapper_does_not_launch_separate_atlas_nightly_state_machine() -> None:
    source = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8-sig")

    assert "$AtlasV2ImportLauncher" not in source
    assert "$AtlasV2Python" not in source
    assert "AtlasV2 is a separate Hermes nightly state machine" in source


def test_daily_wrapper_requires_explicit_cloudbase_poster_write_authority() -> None:
    source = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8-sig")

    assert "[switch]$EnablePosterCloudBaseMigration" in source
    assert 'poster_cloudbase_migration_enabled = [bool]$EnablePosterCloudBaseMigration' in source
    assert 'if ($EnablePosterCloudBaseMigration) { $publishArgs += "-EnablePosterCloudBaseMigration" }' in source
    assert 'if (-not [string]::IsNullOrWhiteSpace($Version)) { $publishArgs += @("-Version", $Version) }' in source
    assert 'if (-not [string]::IsNullOrWhiteSpace($Desc)) { $publishArgs += @("-Desc", $Desc) }' in source
    publish_args = source[source.index("$publishArgs = @(") : source.index(")", source.index("$publishArgs = @("))]
    assert '"-EnablePosterCloudBaseMigration"' not in publish_args

    installer = (ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py").read_text(encoding="utf-8")
    publish_template = installer[installer.index('"huaidj/sanji_publish_afternoon.py"') :]
    publish_template = publish_template[: publish_template.index("''',")]
    assert '"-DeployBackend"' in publish_template
    assert '"-EnablePosterCloudBaseMigration"' in publish_template


def test_candidate_scripts_resolve_paths_from_their_own_repo() -> None:
    bake = (REPO / "services" / "weekly_activity_cloudrun" / "scripts" / "bake_and_deploy.py").read_text(
        encoding="utf-8"
    )
    promotion = (ROOT / "scripts" / "promote_dj_bio_atoms.py").read_text(encoding="utf-8")

    assert r"C:\code\githubstar\wechathtmldownload" not in bake
    assert 'MINIPROGRAM_DIR = _REPO_ROOT / "apps" / "weekly_activity_miniprogram"' in bake
    assert r"C:\code\githubstar\wechathtmldownload" not in promotion
    assert "REPO = Path(__file__).resolve().parents[3]" in promotion
