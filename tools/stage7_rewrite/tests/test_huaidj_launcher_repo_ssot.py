from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_huaidj_sanji_hermes_jobs.py"
AUDIT = ROOT / "scripts" / "audit_huaidj_sanji_hermes_contract.py"


def _make_valid_repo(path: Path) -> Path:
    marker = path / "tools" / "stage7_rewrite" / "scripts" / INSTALLER.name
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("# fixture\n", encoding="utf-8")
    return path


def _fake_hkcu(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    winreg = pytest.importorskip("winreg")

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(winreg, "OpenKey", lambda *args, **kwargs: FakeKey())

    def query_value(_key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name], winreg.REG_SZ

    monkeypatch.setattr(winreg, "QueryValueEx", query_value)


def test_launcher_refreshes_coherent_hkcu_tuple_and_ignores_stale_gateway_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _make_valid_repo(tmp_path / "current-release")
    report_root = tmp_path / "runtime-reports"
    stale_repo = _make_valid_repo(tmp_path / "stale-process-release")
    stale_report = tmp_path / "stale-process-reports"
    monkeypatch.setenv("HUAIDJ_REPO", str(stale_repo))
    monkeypatch.setenv("HUAIDJ_PYTHON", str(tmp_path / "missing-python.exe"))
    monkeypatch.setenv("HUAIDJ_REPORT_ROOT", str(stale_report))
    _fake_hkcu(
        monkeypatch,
        {
            "HUAIDJ_REPO": str(repo),
            "HUAIDJ_PYTHON": sys.executable,
            "HUAIDJ_REPORT_ROOT": str(report_root),
        },
    )

    installer = runpy.run_path(str(INSTALLER), run_name="__test__")
    rendered = installer["render_script_template"](
        "huaidj/health_check.py",
        hermes_home=tmp_path / "hermes",
        repo=repo,
        python_exe=Path(sys.executable),
        report_root=tmp_path / "installer-reports",
    )
    launcher: dict[str, object] = {"__name__": "__test__"}
    exec(compile(rendered, "huaidj/health_check.py", "exec"), launcher)

    assert launcher["RUNTIME"]["source"] == "hkcu_runtime_tuple"
    assert launcher["REPO"] == repo.resolve()
    assert Path(launcher["PYTHON_EXE"]) == Path(sys.executable)
    assert launcher["REPORT_ROOT"] == report_root
    assert Path(os.environ["HUAIDJ_REPO"]) == repo.resolve()
    assert Path(os.environ["HUAIDJ_REPORT_ROOT"]) == report_root


def test_mismatched_hkcu_repo_cannot_override_installer_tuple(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _make_valid_repo(tmp_path / "current-release")
    stale_repo = _make_valid_repo(tmp_path / "stale-registry-release")
    installer_report = tmp_path / "installer-reports"
    _fake_hkcu(
        monkeypatch,
        {
            "HUAIDJ_REPO": str(stale_repo),
            "HUAIDJ_PYTHON": str(tmp_path / "stale-python.exe"),
            "HUAIDJ_REPORT_ROOT": str(tmp_path / "stale-registry-reports"),
        },
    )

    installer = runpy.run_path(str(INSTALLER), run_name="__test__")
    rendered = installer["render_script_template"](
        "huaidj/package_api_tg_status.py",
        hermes_home=tmp_path / "hermes",
        repo=repo,
        python_exe=Path(sys.executable),
        report_root=installer_report,
    )
    launcher: dict[str, object] = {"__name__": "__test__"}
    exec(compile(rendered, "huaidj/package_api_tg_status.py", "exec"), launcher)

    assert launcher["RUNTIME"]["source"] == "installer_rendered_defaults"
    assert launcher["REPO"] == repo.resolve()
    assert Path(launcher["PYTHON_EXE"]) == Path(sys.executable).resolve()
    assert launcher["REPORT_ROOT"] == installer_report.resolve()


def test_stale_launcher_fails_alignment_then_installer_repairs_idempotently(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_root = tmp_path / "reports"
    monkeypatch.setenv("HUAIDJ_PYTHON", sys.executable)
    monkeypatch.setenv("HUAIDJ_REPORT_ROOT", str(report_root))
    installer = runpy.run_path(str(INSTALLER), run_name="__test__")
    audit = runpy.run_path(str(AUDIT), run_name="__test__")
    repo = Path(installer["REPO"]).resolve()
    hermes_home = tmp_path / "hermes"
    rel = "huaidj/atlas_v2_sanji_import_nightly.py"
    live_script = hermes_home / "scripts" / Path(rel)
    live_script.parent.mkdir(parents=True)
    desired = installer["render_script_template"](
        rel,
        hermes_home=hermes_home,
        repo=repo,
        python_exe=Path(sys.executable),
        report_root=report_root,
    )
    stale_repo = str(tmp_path / "old-release")
    stale = desired.replace(
        f'INSTALLER_REPO = Path(r"{repo}")',
        f'INSTALLER_REPO = Path(r"{stale_repo}")',
        1,
    )
    live_script.write_text(stale, encoding="utf-8")

    aligned, _ = audit["launcher_repo_alignment"](
        stale,
        job_workdir=repo,
        installer_repo=repo,
    )
    assert aligned is False
    dry_run = installer["write_scripts"](hermes_home, apply=False)
    stale_action = next(row for row in dry_run if Path(row["path"]) == live_script)
    assert stale_action["contract_ok"] is False
    assert stale_action["changed"] is True

    installer["write_scripts"](hermes_home, apply=True)
    repaired = live_script.read_text(encoding="utf-8")
    aligned, _ = audit["launcher_repo_alignment"](
        repaired,
        job_workdir=repo,
        installer_repo=repo,
    )
    assert aligned is True

    second = installer["write_scripts"](hermes_home, apply=True)
    second_action = next(row for row in second if Path(row["path"]) == live_script)
    assert second_action["contract_ok"] is True
    assert second_action["changed"] is False
    assert live_script.read_text(encoding="utf-8") == repaired


def test_alignment_requires_all_three_repo_values_to_match() -> None:
    audit = runpy.run_path(str(AUDIT), run_name="__test__")
    repo = ROOT.parents[1]
    script = f'INSTALLER_REPO = Path(r"{repo}")\n'

    ok, _ = audit["launcher_repo_alignment"](
        script,
        job_workdir=repo,
        installer_repo=repo,
    )
    assert ok is True
    wrong_workdir, _ = audit["launcher_repo_alignment"](
        script,
        job_workdir=repo.parent / "old-release",
        installer_repo=repo,
    )
    assert wrong_workdir is False
