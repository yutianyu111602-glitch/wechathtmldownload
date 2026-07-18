import importlib.util
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_cloudrun_weekly_production.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("smoke_cloudrun_weekly_production", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_tcb_cwd_is_owned_by_the_current_checkout():
    smoke = load_script_module()

    expected = ROOT.parents[1] / "services" / "weekly_activity_cloudrun"
    assert smoke.DEFAULT_TCB_CWD == expected
    assert smoke.resolve_tcb_cwd(None) == expected.resolve()
    assert r"C:\code\githubstar\wechathtmldownload" not in SCRIPT.read_text(encoding="utf-8")


def test_explicit_tcb_cwd_is_passed_to_cloudbase_cli(monkeypatch, tmp_path):
    smoke = load_script_module()
    explicit = tmp_path / "cloudrun"
    explicit.mkdir()
    (explicit / "package.json").write_text("{}\n", encoding="utf-8")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, stdout='{"data": {"ok": true}}', stderr="")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    payload = smoke.tcb_api("DescribeCloudRunServerDetail", {}, 30, tcb_cwd=explicit)

    assert payload == {"ok": True}
    assert captured["cwd"] == explicit.resolve()


def test_explicit_tcb_cwd_must_be_a_cloudrun_project(tmp_path):
    smoke = load_script_module()
    invalid = tmp_path / "not-a-project"
    invalid.mkdir()

    try:
        smoke.resolve_tcb_cwd(invalid)
    except ValueError as exc:
        assert "package.json" in str(exc)
    else:
        raise AssertionError("invalid TCB cwd was accepted")
