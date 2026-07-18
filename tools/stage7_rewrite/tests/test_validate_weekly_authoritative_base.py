from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_weekly_authoritative_base.py"
SPEC = importlib.util.spec_from_file_location("validate_weekly_authoritative_base", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_package(api_dir: Path, count: int, *, manifest_count: int | None = None) -> None:
    api_dir.mkdir(parents=True)
    items = [{"id": f"event-{index}"} for index in range(count)]
    (api_dir / "current.json").write_text(
        json.dumps({"item_count": count, "items": items}),
        encoding="utf-8",
    )
    (api_dir / "manifest.json").write_text(
        json.dumps({"item_count": count if manifest_count is None else manifest_count}),
        encoding="utf-8",
    )


def test_external_runtime_matching_online_manifest_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "runtime" / "data"
    api_dir = data_root / "current_release"
    repo.mkdir()
    write_package(api_dir, 604)

    report = MODULE.validate_authoritative_base(
        api_dir=api_dir,
        data_root=data_root,
        repo_root=repo,
        min_items=40,
        expected_online_item_count=604,
        require_external_runtime=True,
    )

    assert report["ok"] is True
    assert report["current_item_count"] == 604
    assert report["failures"] == []


def test_stale_local_baseline_cannot_beat_larger_online_manifest(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "runtime" / "data"
    api_dir = data_root / "current_release"
    repo.mkdir()
    write_package(api_dir, 171)

    report = MODULE.validate_authoritative_base(
        api_dir=api_dir,
        data_root=data_root,
        repo_root=repo,
        min_items=40,
        expected_online_item_count=604,
        require_external_runtime=True,
    )

    assert report["ok"] is False
    assert "base_item_count_below_online_manifest" in report["failures"]


def test_production_rejects_checkout_data_even_when_counts_are_valid(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data_root = repo / "services" / "weekly_activity_cloudrun" / "data"
    api_dir = data_root / "current_release"
    write_package(api_dir, 604)

    report = MODULE.validate_authoritative_base(
        api_dir=api_dir,
        data_root=data_root,
        repo_root=repo,
        min_items=40,
        expected_online_item_count=604,
        require_external_runtime=True,
    )

    assert report["ok"] is False
    assert "current_release_inside_source_checkout" in report["failures"]
    assert "cloudrun_data_root_inside_source_checkout" in report["failures"]


def test_manifest_and_current_counts_must_agree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data_root = tmp_path / "runtime" / "data"
    api_dir = data_root / "current_release"
    repo.mkdir()
    write_package(api_dir, 604, manifest_count=171)

    report = MODULE.validate_authoritative_base(
        api_dir=api_dir,
        data_root=data_root,
        repo_root=repo,
        min_items=40,
        expected_online_item_count=0,
        require_external_runtime=True,
    )

    assert report["ok"] is False
    assert "manifest_current_item_count_mismatch" in report["failures"]
