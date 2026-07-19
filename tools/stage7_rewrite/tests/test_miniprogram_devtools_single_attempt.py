from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_miniprogram_devtools_rendered_single_attempt.py"
SPEC = importlib.util.spec_from_file_location("devtools_single_attempt", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_missing_discovery_report_falls_back_to_versioned_builtin_contract(tmp_path: Path) -> None:
    missing = tmp_path / "missing-preflight.json"

    preflight, source = MODULE.resolve_preflight(None, fallback=missing)

    assert source == "builtin"
    assert {step["script"] for step in preflight["run_order"]} == MODULE.ALLOWED_SCRIPTS
    assert all(step["pass_contract"] for step in preflight["run_order"])
    assert all(step["expected_artifact_dir_glob"] for step in preflight["run_order"])


def test_explicit_missing_preflight_still_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "explicitly-requested.json"

    try:
        MODULE.resolve_preflight(missing, fallback=tmp_path / "unused.json")
    except FileNotFoundError as error:
        assert error.filename == str(missing)
    else:
        raise AssertionError("an explicitly requested preflight must not be silently replaced")


def test_explicit_release_scenario_uses_builtin_contract_when_discovery_is_stale() -> None:
    stale_preflight = {
        "run_order": [
            step
            for step in MODULE.builtin_preflight()["run_order"]
            if step["script"] == "devtools-current-package-rendered.cjs"
        ]
    }

    selected = MODULE.choose_step(stale_preflight, "devtools-sound-rendered.cjs")

    assert selected["script"] == "devtools-sound-rendered.cjs"
    assert selected["pass_contract"]


def test_packet_defers_devtools_http_port_until_environment_audit(tmp_path: Path) -> None:
    packet = MODULE.build_packet(
        preflight=MODULE.builtin_preflight(),
        script_name="devtools-current-package-rendered.cjs",
        out_dir=tmp_path,
        port=9460,
        avoid_busy_port=True,
        execute=True,
        timeout_sec=30,
    )

    assert packet["environment_overrides"]["MINIPROGRAM_AUTOMATOR_PORT"] == "9460"
    assert packet["environment_overrides"]["MINIPROGRAM_DEVTOOLS_IDE_PORT"] == "<auto>"


def test_existing_ide_http_port_is_reused_for_a_dirty_but_allowed_session() -> None:
    report = {"summary": {"process_count": 13, "ide_http_ports": [65057]}}

    assert MODULE.choose_ide_http_port(report, automator_port=9460, explicit="") == 65057


def test_explicit_ide_http_port_wins_and_clean_launch_reuses_automator_port() -> None:
    dirty = {"summary": {"process_count": 13, "ide_http_ports": [65057]}}
    clean = {"summary": {"process_count": 0, "ide_http_ports": []}}

    assert MODULE.choose_ide_http_port(dirty, automator_port=9460, explicit="65123") == 65123
    assert MODULE.choose_ide_http_port(clean, automator_port=9460, explicit="") == 9460


def test_running_ide_profile_localappdata_is_forwarded_to_official_cli() -> None:
    report = {
        "summary": {
            "process_count": 13,
            "devtools_local_app_data_paths": [r"F:\DevData\WeChatDevTools\Profile\AppData\Local"],
        }
    }

    assert MODULE.choose_devtools_local_app_data(report, explicit="") == (
        r"F:\DevData\WeChatDevTools\Profile\AppData\Local"
    )


def test_relocated_devtools_profile_forwards_all_windows_profile_roots() -> None:
    assert MODULE.devtools_profile_environment(
        r"F:\DevData\WeChatDevTools\Profile\AppData\Local"
    ) == {
        "USERPROFILE": r"F:\DevData\WeChatDevTools\Profile",
        "LOCALAPPDATA": r"F:\DevData\WeChatDevTools\Profile\AppData\Local",
        "APPDATA": r"F:\DevData\WeChatDevTools\Profile\AppData\Roaming",
    }
