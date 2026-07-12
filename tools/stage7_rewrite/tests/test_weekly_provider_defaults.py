from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_openclaw_weekly_publish_defaults_to_local_ocr() -> None:
    source = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8-sig")

    assert '[string]$PosterExtractionMode = "legacy_ocr"' in source
    assert '[string]$PosterExtractionMode = "vl_direct_qwen"' not in source
