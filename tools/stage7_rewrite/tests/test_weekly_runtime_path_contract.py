from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def test_daily_and_fast_watch_plumb_authoritative_runtime_paths() -> None:
    daily = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8")
    fast_watch = (ROOT / "run_huaidj_sanji_rss_fast_watch.ps1").read_text(encoding="utf-8")
    detector = (ROOT / "scripts" / "watch_sanji_rss_fast_trigger.py").read_text(encoding="utf-8")

    for source in (daily, fast_watch):
        assert "HUAIDJ_CURRENT_RELEASE_DIR" in source
        assert "HUAIDJ_PUBLISHED_API_DIR" in source
        assert "HUAIDJ_CLOUDRUN_DATA_ROOT" in source
        assert "HUAIDJ_CLOUDRUN_WORK_ROOT" in source
        assert '"-IncrementalBaseApiDir", $IncrementalBaseApiDir' in source
        assert '"-PublishedApiDir", $PublishedApiDir' in source
    assert "$ApiDir = $IncrementalBaseApiDir" in fast_watch
    assert "DEFAULT_RUNTIME_DATA_ROOT" in detector
    assert "HUAIDJ_CURRENT_RELEASE_DIR" in detector


def test_publish_runner_validates_external_base_and_keeps_post_deploy_readback() -> None:
    runner = (ROOT / "run_openclaw_weekly_daily_publish.ps1").read_text(encoding="utf-8")

    assert "validate_weekly_authoritative_base.py" in runner
    assert '[string]$PublishedApiDir = ""' in runner
    assert "PublishedApiDir = $PublishedApiDir" in runner
    assert '"--require-external-runtime"' in runner
    assert '"--expected-online-item-count"' in runner
    assert '"HUAIDJ_PROXY_URL"' in runner
    assert '"http://127.0.0.1:7890"' in runner
    assert "-Proxy $ProxyUrl" in runner
    assert "Candidate package would roll back online item coverage" in runner
    assert "--data-root $CloudRunDataRoot" in runner
    assert "--current-release-dir $IncrementalBaseApiDir" in runner
    assert "--work-root $CloudRunWorkRoot" in runner
    assert "--context-dir $CloudRunDeployContextDir" in runner
    assert "Assert-RemotePagination -BaseUrl $PublicApiBase -ExpectedCount $itemCount" in runner


def test_monitor_and_prefect_default_to_runtime_ssot() -> None:
    monitor = (ROOT / "scripts" / "report_huaidj_package_api_tg_status.py").read_text(encoding="utf-8")
    prefect = (ROOT / "prefect" / "huaidj_weekly_flow.py").read_text(encoding="utf-8")

    for source in (monitor, prefect):
        assert "HUAIDJ_CURRENT_RELEASE_DIR" in source
        assert "HUAIDJ_CLOUDRUN_DATA_ROOT" in source
        assert "F:\\DevData\\HuaidjRuntime\\state\\weekly_activity_cloudrun\\data" in source
    assert "--current-release-dir" in prefect


def load_bake_module():
    script = REPO / "services" / "weekly_activity_cloudrun" / "scripts" / "bake_and_deploy.py"
    spec = importlib.util.spec_from_file_location("weekly_bake_and_deploy_runtime_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_bake_runtime_path_contract_rejects_checkout_for_production(tmp_path: Path) -> None:
    bake = load_bake_module()
    repo_data = REPO / "services" / "weekly_activity_cloudrun" / "data"
    with pytest.raises(ValueError, match="outside the source checkout"):
        bake.configure_runtime_paths(
            data_root=str(repo_data),
            current_release_dir=str(repo_data / "current_release"),
            work_root=str(REPO / "services" / "weekly_activity_cloudrun" / "tmp"),
            production_write=True,
        )

    external_data = tmp_path / "state" / "data"
    data, current, work = bake.configure_runtime_paths(
        data_root=str(external_data),
        current_release_dir=str(external_data / "current_release"),
        work_root=str(tmp_path / "state" / "work"),
        production_write=True,
    )
    assert current == data / "current_release"
    assert work == (tmp_path / "state" / "work").resolve()


def test_bake_rejects_candidate_smaller_than_authoritative_base(tmp_path: Path) -> None:
    bake = load_bake_module()
    data_root = tmp_path / "state" / "data"
    current = data_root / "current_release"
    candidate = tmp_path / "candidate"
    bake.configure_runtime_paths(
        data_root=str(data_root),
        current_release_dir=str(current),
        work_root=str(tmp_path / "state" / "work"),
        production_write=True,
    )

    for directory, count in ((current, 604), (candidate, 171)):
        directory.mkdir(parents=True)
        items = [{"id": f"event-{index}"} for index in range(count)]
        (directory / "current.json").write_text(json.dumps({"items": items}), encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps({"item_count": count}), encoding="utf-8")

    ok, failures = bake.validate_production_bake_input(candidate)
    assert ok is False
    assert failures == ["release_item_count_below_authoritative_base"]
