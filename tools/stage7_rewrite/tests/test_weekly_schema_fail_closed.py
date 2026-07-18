import importlib.util
import json
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_weekly_schema_compat.py"
spec = importlib.util.spec_from_file_location("validate_weekly_schema_compat_fail_closed", SCRIPT)
compat = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(compat)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_build_report_rejects_missing_expected_schema_set(tmp_path):
    release_pack = tmp_path / "pack"
    _write_jsonl(release_pack / "articles.jsonl", [])
    _write_jsonl(release_pack / "events.jsonl", [])

    report = compat.build_report(
        Namespace(
            release_pack=release_pack,
            schemas=tmp_path / "missing-schemas",
            registries=tmp_path / "registries",
            out_dir=tmp_path / "out",
            sample_per_file=1,
            coverage_limit=1,
            weekly_path_report=None,
            allow_selected_weekly_path=False,
            report_only_exit_zero=False,
        )
    )

    assert report["ok"] is False
    assert report["decision"] == "weekly_schema_set_missing_or_unexpected"
    assert set(report["schema_set"]["missing"]) == set(compat.EXPECTED_SCHEMA_NAMES)
