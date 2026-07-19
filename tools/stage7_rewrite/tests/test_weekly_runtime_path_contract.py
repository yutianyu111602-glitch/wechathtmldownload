from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
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


def test_daily_path_resolver_accepts_intentionally_empty_default() -> None:
    daily = (ROOT / "run_huaidj_sanji_daily_twice.ps1").read_text(encoding="utf-8")

    assert "[AllowEmptyString()][string]$Default" in daily
    assert '-EnvironmentVariableName "HUAIDJ_CURRENT_RELEASE_DIR" -Default ""' in daily
    assert '-EnvironmentVariableName "HUAIDJ_CLOUDRUN_DATA_ROOT" -Default ""' in daily


def test_fast_watch_path_resolver_binds_intentionally_empty_default() -> None:
    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell 7 is required to exercise the wrapper parameter binder")

    script_path = ROOT / "run_huaidj_sanji_rss_fast_watch.ps1"
    probe = r"""
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $env:HUAIDJ_FAST_WATCH_TEST_SCRIPT,
    [ref]$tokens,
    [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
    throw "Fast Watch wrapper did not parse cleanly."
}
$resolver = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Resolve-ConfiguredPath"
}, $true)
if ($null -eq $resolver) {
    throw "Resolve-ConfiguredPath was not found."
}
Invoke-Expression $resolver.Extent.Text
[Environment]::SetEnvironmentVariable("HUAIDJ_TEST_UNSET_PATH", $null, "Process")
$resolved = Resolve-ConfiguredPath `
    -Value "" `
    -EnvironmentVariableName "HUAIDJ_TEST_UNSET_PATH" `
    -Default ""
if ($null -ne $resolved -and $resolved -ne "") {
    throw "Unexpected non-empty resolver result: $resolved"
}
Write-Output "ok"
"""
    probe_env = os.environ.copy()
    probe_env["HUAIDJ_FAST_WATCH_TEST_SCRIPT"] = str(script_path)
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", probe],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        env=probe_env,
    )

    assert result.returncode == 0, (result.stdout + result.stderr).strip()
    assert "ok" in result.stdout


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
    assert 'f"{cloudrun_base}/readyz"' in monitor
    assert 'endpoint_result("readyz"' in monitor


def test_scheduled_runtime_reports_and_locks_stay_outside_checkout() -> None:
    sources = {
        ROOT / "run_huaidj_sanji_daily_twice.ps1": (
            'Join-Path $Stage7 "reports',
            'Join-Path $Repo ".locks"',
        ),
        ROOT / "run_huaidj_sanji_rss_fast_watch.ps1": (
            'Join-Path $Stage7 "reports',
            'Join-Path $Repo ".locks"',
        ),
        ROOT / "run_openclaw_weekly_daily_publish.ps1": (
            'Join-Path $Stage7 "reports',
            'Join-Path $Repo "reports',
        ),
        ROOT / "run_sanji_desktop_recent_export.ps1": ("Join-Path $RepoRoot '.locks'",),
        ROOT / "scripts" / "report_huaidj_package_api_tg_status.py": (
            'REPO / "tools/stage7_rewrite/reports',
        ),
        ROOT / "scripts" / "watch_sanji_rss_fast_trigger.py": (
            'ROOT / "reports" / "sanji_rss_fast_watch"',
        ),
        ROOT / "scripts" / "send_sanji_publish_wechat_notification.py": (
            'repo / "tools" / "stage7_rewrite" / "reports"',
        ),
        ROOT / "prefect" / "huaidj_weekly_flow.py": (
            'REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "prefect_weekly_flow"',
        ),
    }
    for path, forbidden in sources.items():
        text = path.read_text(encoding="utf-8")
        assert "HUAIDJ_REPORT_ROOT" in text, path
        assert not [fragment for fragment in forbidden if fragment in text], path

    for name in (
        "run_sanji_desktop_recent_export.ps1",
        "run_huaidj_sanji_daily_twice.ps1",
        "run_huaidj_sanji_rss_fast_watch.ps1",
        "run_openclaw_weekly_daily_publish.ps1",
        "weekly_activity_next_week_pipeline.ps1",
    ):
        assert "PYTHONDONTWRITEBYTECODE" in (ROOT / name).read_text(encoding="utf-8")


def test_python_report_defaults_honor_explicit_external_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    report_root = tmp_path / "runtime-reports"
    monkeypatch.setenv("HUAIDJ_REPORT_ROOT", str(report_root))

    def load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    monitor = load("huaidj_monitor_report_root_test", ROOT / "scripts" / "report_huaidj_package_api_tg_status.py")
    watcher = load("huaidj_watch_report_root_test", ROOT / "scripts" / "watch_sanji_rss_fast_trigger.py")

    assert monitor.DEFAULT_REPORT_ROOT == report_root
    assert monitor.DEFAULT_JSON_OUT.is_relative_to(report_root)
    assert monitor.DEFAULT_STATUS_JSON.is_relative_to(report_root)
    assert watcher.DEFAULT_STATE.is_relative_to(report_root)
    assert watcher.DEFAULT_REPORT.is_relative_to(report_root)


def load_resource_field_repair_module():
    script = ROOT / "scripts" / "repair_weekly_current_resource_fields.py"
    spec = importlib.util.spec_from_file_location("weekly_resource_field_repair_path_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_resource_field_repair_path_label_is_repo_relative_or_external_absolute(tmp_path: Path) -> None:
    repair = load_resource_field_repair_module()

    in_repo = REPO / "tools" / "stage7_rewrite" / "reports" / "repair.json"
    external = tmp_path / "runtime-reports" / "repair.json"

    assert repair.portable_path_label(in_repo) == "tools/stage7_rewrite/reports/repair.json"
    assert repair.portable_path_label(external) == external.resolve().as_posix()


def test_resource_field_repair_writes_external_report_path_to_manifest(tmp_path: Path) -> None:
    repair = load_resource_field_repair_module()
    api_dir = tmp_path / "candidate"
    report_dir = tmp_path / "runtime-reports" / "weekly-run"
    registry = tmp_path / "weekly_venues_seed.json"
    format_js = tmp_path / "mapLocationBook.js"
    api_dir.mkdir()
    (api_dir / "current.json").write_text(json.dumps({"items": []}), encoding="utf-8")
    (api_dir / "manifest.json").write_text(json.dumps({"item_count": 0}), encoding="utf-8")
    registry.write_text(json.dumps({"venues": []}), encoding="utf-8")
    format_js.write_text("const VERIFIED_MAP_LOCATION_BOOK = [];", encoding="utf-8")

    repair.repair_package(
        api_dir=api_dir,
        registry_path=registry,
        format_js=format_js,
        history_paths=[],
        report_dir=report_dir,
        dry_run=False,
        update_registry=False,
    )

    manifest = json.loads((api_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = (report_dir / "weekly_resource_field_repair_report.json").resolve().as_posix()
    assert manifest["field_resource_repair"]["report_path"] == expected


def test_installer_templates_make_health_canary_checkout_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import runpy
    import subprocess

    repo = tmp_path / "immutable-checkout"
    report_root = tmp_path / "runtime-reports"
    monkeypatch.setenv("HUAIDJ_REPO", str(repo))
    monkeypatch.setenv("HUAIDJ_REPORT_ROOT", str(report_root))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")
    templates = namespace["SCRIPT_TEMPLATES"]
    assert all("HUAIDJ_REPORT_ROOT" in template for template in templates.values())
    assert all("PYTHONDONTWRITEBYTECODE" in template for template in templates.values())

    health: dict[str, object] = {"__name__": "__test__"}
    exec(compile(templates["huaidj/health_check.py"], "huaidj/health_check.py", "exec"), health)
    command = health["CMD"]
    json_out = Path(command[command.index("--json-out") + 1])
    assert json_out == report_root / "huaidj_health" / "latest.json"

    subprocess_module = health["subprocess"]
    monkeypatch.setattr(
        subprocess_module,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
    )
    assert health["main"]() == 0
    assert not repo.exists()


@pytest.mark.parametrize(
    "template_name",
    ("huaidj/health_check.py", "huaidj/package_api_tg_status.py"),
)
def test_installer_upgrades_status_launchers_missing_console_safe_emit(
    tmp_path: Path, template_name: str
) -> None:
    import runpy

    namespace = runpy.run_path(
        str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"),
        run_name="__test__",
    )
    template = namespace["SCRIPT_TEMPLATES"][template_name]
    emit_start = template.index("\ndef _emit(text: str) -> None:")
    main_start = template.index("\ndef main() -> int:", emit_start)
    legacy = template[:emit_start] + "\n" + template[main_start:]
    legacy = legacy.replace("_emit(", "print(")

    live_script = tmp_path / "scripts" / Path(template_name)
    live_script.parent.mkdir(parents=True)
    live_script.write_text(legacy, encoding="utf-8")

    actions = namespace["write_scripts"](tmp_path, apply=True)
    action = next(row for row in actions if Path(row["path"]) == live_script)
    installed = live_script.read_text(encoding="utf-8")

    assert action["contract_ok"] is False
    assert action["changed"] is True
    assert "def _emit(text: str) -> None:" in installed
    assert 'text.encode(encoding, errors="replace").decode(encoding, errors="replace")' in installed
    assert "sys.stdout.write(rendered)" in installed


@pytest.mark.parametrize(
    "template_name",
    ("huaidj/health_check.py", "huaidj/package_api_tg_status.py"),
)
def test_installer_keeps_current_status_launchers_idempotent(tmp_path: Path, template_name: str) -> None:
    import runpy

    namespace = runpy.run_path(
        str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"),
        run_name="__test__",
    )
    namespace["write_scripts"](tmp_path, apply=True)
    live_script = tmp_path / "scripts" / Path(template_name)
    before = live_script.read_bytes()

    actions = namespace["write_scripts"](tmp_path, apply=True)
    action = next(row for row in actions if Path(row["path"]) == live_script)

    assert action["contract_ok"] is True
    assert action["changed"] is False
    assert live_script.read_bytes() == before


@pytest.mark.parametrize(
    "template_name",
    ("huaidj/health_check.py", "huaidj/package_api_tg_status.py"),
)
def test_installer_status_launchers_preserve_exit_code_on_gbk_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, template_name: str
) -> None:
    import io
    import runpy
    import subprocess

    monkeypatch.setenv("HUAIDJ_REPO", str(tmp_path / "immutable-checkout"))
    monkeypatch.setenv("HUAIDJ_REPORT_ROOT", str(tmp_path / "runtime-reports"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    namespace = runpy.run_path(
        str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"),
        run_name="__test__",
    )
    generated: dict[str, object] = {"__name__": "__test__"}
    exec(compile(namespace["SCRIPT_TEMPLATES"][template_name], template_name, "exec"), generated)

    subprocess_module = generated["subprocess"]
    monkeypatch.setattr(
        subprocess_module,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd,
            7,
            stdout="status contains replacement: \ufffd\n",
            stderr="stderr contains replacement: \ufffd\n",
        ),
    )
    raw_output = io.BytesIO()
    gbk_console = io.TextIOWrapper(raw_output, encoding="gbk", errors="strict")
    monkeypatch.setattr(generated["sys"], "stdout", gbk_console)

    assert generated["main"]() == 7
    gbk_console.flush()
    rendered = raw_output.getvalue().decode("gbk")
    assert "status contains replacement: ?" in rendered
    assert "stderr contains replacement: ?" in rendered


def test_installer_templates_scope_proxy_to_child_env_and_atlas_reloads_user_runtime_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runpy

    winreg = pytest.importorskip("winreg")

    namespace = runpy.run_path(str(ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"), run_name="__test__")
    templates = namespace["SCRIPT_TEMPLATES"]
    proxy_url = "http://127.0.0.1:7890"
    monkeypatch.setenv("HUAIDJ_PROXY_URL", proxy_url)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)

    for name in (
        "huaidj/sanji_publish_afternoon.py",
        "huaidj/sanji_rss_fast_watch.py",
        "huaidj/health_check.py",
        "huaidj/package_api_tg_status.py",
    ):
        generated: dict[str, object] = {"__name__": "__test__"}
        exec(compile(templates[name], name, "exec"), generated)
        child_env = generated["_child_env"]()
        assert child_env["HTTP_PROXY"] == proxy_url
        assert child_env["HTTPS_PROXY"] == proxy_url
        assert "HTTP_PROXY" not in os.environ
        assert "HTTPS_PROXY" not in os.environ

    historical_geo = r"F:\DevData\HuaidjRuntime\state\atlas_v2\historical_venue_geo.json"
    registry_values = {
        "ATLAS_HISTORICAL_VENUE_GEO": historical_geo,
        "HUAIDJ_PROXY_URL": proxy_url,
    }

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(winreg, "OpenKey", lambda *args, **kwargs: FakeKey())

    def query_value(_key, name):
        if name not in registry_values:
            raise FileNotFoundError(name)
        return registry_values[name], winreg.REG_SZ

    monkeypatch.setattr(winreg, "QueryValueEx", query_value)
    atlas: dict[str, object] = {"__name__": "__test__"}
    exec(
        compile(
            templates["huaidj/atlas_v2_sanji_import_nightly.py"],
            "huaidj/atlas_v2_sanji_import_nightly.py",
            "exec",
        ),
        atlas,
    )
    launch_env = atlas["_fresh_launch_env"]()
    assert launch_env["ATLAS_HISTORICAL_VENUE_GEO"] == historical_geo
    assert launch_env["HUAIDJ_PROXY_URL"] == proxy_url
    assert launch_env["HTTP_PROXY"] == proxy_url
    assert launch_env["HTTPS_PROXY"] == proxy_url


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


def test_bake_rejects_candidate_with_mixed_generation_derived_routes(tmp_path: Path) -> None:
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
    current.mkdir(parents=True)
    candidate.mkdir(parents=True)
    item = {
        "id": "event-a",
        "title": "new title",
        "city_key": "shanghai",
        "city_keys": ["shanghai"],
        "city": ["上海"],
        "event_date_start": "2026-07-24",
        "event_date_end": "2026-07-24",
        "detail_path": "by-id/event-a.json",
    }
    for directory in (current, candidate):
        (directory / "current.json").write_text(json.dumps({"items": [item]}), encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps({"item_count": 1}), encoding="utf-8")
    (candidate / "by-id").mkdir()
    (candidate / "by-id" / "event-a.json").write_text(
        json.dumps({"item": {**item, "title": "old title"}}),
        encoding="utf-8",
    )
    (candidate / "by-city").mkdir()
    (candidate / "by-date").mkdir()

    ok, failures = bake.validate_production_bake_input(candidate)

    assert ok is False
    assert "release_derived_route_closure_failed" in failures
