from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "recover_weekly_authoritative_base.py"
SPEC = importlib.util.spec_from_file_location("recover_weekly_authoritative_base", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_package(path: Path, ids: list[str], generated_at: str = "2026-07-28T23:26:09+08:00") -> None:
    path.mkdir(parents=True)
    (path / "current.json").write_text(
        json.dumps({"generated_at": generated_at, "item_count": len(ids), "items": [{"id": item_id} for item_id in ids]}),
        encoding="utf-8",
    )
    (path / "manifest.json").write_text(
        json.dumps({"generated_at": generated_at, "item_count": len(ids)}),
        encoding="utf-8",
    )


def test_matching_candidate_passes_and_reports_stable_id_digest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_package(source, ["b", "a"])

    report = MODULE.validate_candidate(
        source,
        {"item_count": 2, "generated_at": "2026-07-28T23:26:09+08:00"},
        [{"id": "a"}, {"id": "b"}],
    )

    assert report["ok"] is True
    assert report["source_activity_id_sha256"] == report["public_activity_id_sha256"]


def test_id_drift_blocks_even_when_counts_match(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_package(source, ["a", "b"])

    report = MODULE.validate_candidate(
        source,
        {"item_count": 2, "generated_at": "2026-07-28T23:26:09+08:00"},
        [{"id": "a"}, {"id": "c"}],
    )

    assert report["ok"] is False
    assert "source_public_activity_id_digest_mismatch" in report["failures"]


def test_promotion_preserves_previous_current_release_as_backup(tmp_path: Path) -> None:
    source = tmp_path / "source"
    data_root = tmp_path / "runtime" / "data"
    write_package(source, ["new-a", "new-b"])
    write_package(data_root / "current_release", ["old"])

    result = MODULE.promote_candidate(source, data_root)

    promoted = MODULE.read_json(data_root / "current_release" / "current.json")
    backup = MODULE.read_json(Path(result["backup"]) / "current.json")
    assert MODULE.item_ids(promoted) == ["new-a", "new-b"]
    assert MODULE.item_ids(backup) == ["old"]
    assert result["backup_recoverable"] is True
