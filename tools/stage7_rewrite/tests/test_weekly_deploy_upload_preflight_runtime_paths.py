from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_weekly_deploy_upload_preflight.py"


def load_module():
    spec = importlib.util.spec_from_file_location("weekly_deploy_upload_preflight", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_relation_guard_accepts_explicit_external_runtime_paths(tmp_path):
    module = load_module()
    db2 = tmp_path / "atlas-db2.sqlite"
    db3 = tmp_path / "atlas-db3.sqlite"
    current = tmp_path / "current.json"

    specs = module.build_check_specs(
        tmp_path / "report",
        atlas_db2_path=db2,
        atlas_db3_path=db3,
        weekly_current_path=current,
        include_weekly_api=False,
        include_miniapp=False,
        include_coordinate_freshness=False,
    )

    argv = specs[0].argv
    assert argv[argv.index("--db2") + 1] == str(db2)
    assert argv[argv.index("--db3") + 1] == str(db3)
    assert argv[argv.index("--weekly-current") + 1] == str(current)


def test_subprocess_output_is_always_decoded_as_utf8(tmp_path):
    module = load_module()
    captured = {}

    def runner(argv, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout="✓ UTF-8", stderr="")

    spec = module.CheckSpec("utf8", "utf8", ("node", "probe.js"), cwd=tmp_path)
    result = module.execute_spec(spec, runner=runner)

    assert result["status"] == "passed"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
