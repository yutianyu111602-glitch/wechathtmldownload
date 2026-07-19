#!/usr/bin/env python3
"""Build or run one bounded rendered WeChat DevTools script attempt.

Default mode is report-only. Passing ``--execute`` runs exactly one rendered
script and writes redacted stdout/stderr plus a compact execution summary.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PREFLIGHT_JSON = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_miniprogram_devtools_run_preflight_20260603_frontend_hotfix"
    / "weekly_miniprogram_devtools_rendered_run_preflight.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_miniprogram_devtools_single_attempt_20260603_frontend_hotfix"
)
ALLOWED_SCRIPTS = {
    "devtools-current-package-rendered.cjs",
    "devtools-loading-fallback.cjs",
    "devtools-haptics.cjs",
    "devtools-extreme.cjs",
    "devtools-atlas-neighborhood-rendered.cjs",
    "devtools-artist-max-richness-rendered.cjs",
    "devtools-city-guide-rendered.cjs",
    "devtools-sound-rendered.cjs",
}
BUILTIN_RUN_ORDER = [
    {
        "script": "devtools-current-package-rendered.cjs",
        "current_pass": False,
        "pass_contract": "Render the current package and verify feed, city/date facets, interactions, posters, and runtime exceptions.",
        "expected_artifact_dir_glob": "devtools-current-package-rendered-*",
    },
    {
        "script": "devtools-loading-fallback.cjs",
        "current_pass": False,
        "pass_contract": "Verify loading, timeout, retry, and static fallback states without a stuck spinner.",
        "expected_artifact_dir_glob": "devtools-loading-fallback-*",
    },
    {
        "script": "devtools-haptics.cjs",
        "current_pass": False,
        "pass_contract": "Verify bounded haptic interaction handlers and absence of runtime exceptions.",
        "expected_artifact_dir_glob": "devtools-haptics-*",
    },
    {
        "script": "devtools-extreme.cjs",
        "current_pass": False,
        "pass_contract": "Verify extreme viewport and interaction scenarios without render or runtime failures.",
        "expected_artifact_dir_glob": "devtools-extreme-*",
    },
    {
        "script": "devtools-atlas-neighborhood-rendered.cjs",
        "current_pass": False,
        "pass_contract": "Render an Atlas neighborhood and verify generation-bound graph expansion without runtime exceptions.",
        "expected_artifact_dir_glob": "devtools-atlas-neighborhood-rendered-*",
    },
    {
        "script": "devtools-artist-max-richness-rendered.cjs",
        "current_pass": False,
        "pass_contract": "Render the richest artist surface and verify its complete evidence-backed sections.",
        "expected_artifact_dir_glob": "devtools-artist-max-richness-rendered-*",
    },
    {
        "script": "devtools-city-guide-rendered.cjs",
        "current_pass": False,
        "pass_contract": "Render the city guide, select a city, and verify its decision and venue routes.",
        "expected_artifact_dir_glob": "devtools-city-guide-rendered-*",
    },
    {
        "script": "devtools-sound-rendered.cjs",
        "current_pass": False,
        "pass_contract": "Render the safe empty Sound form and prove validation stops before upload or persistence.",
        "expected_artifact_dir_glob": "devtools-sound-rendered-*",
    },
]
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|cookie|authorization|bearer|sk)\s*[:=]\s*([^\s\"'<>]+)"
)
URL_QUERY_RE = re.compile(r"((?:https?|wss?)://[^\s\"'<>?]+)\?([^\s\"'<>]+)")


Runner = Callable[..., subprocess.CompletedProcess[str]]


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def builtin_preflight() -> dict[str, Any]:
    """Return the versioned portable run contract for a clean checkout."""
    return {
        "schema_version": "weekly_miniprogram_devtools_rendered_run_preflight.builtin.v1",
        "decision": "portable_builtin_run_contract",
        "run_order": [dict(step) for step in BUILTIN_RUN_ORDER],
    }


def latest_report_json(prefix: str, filename: str, fallback: Path) -> Path:
    reports_root = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
    candidates = [
        path / filename
        for path in reports_root.glob(f"{prefix}*")
        if path.is_dir() and (path / filename).exists()
    ]
    if not candidates:
        return fallback
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, str(path)))


def resolve_preflight(
    explicit: Path | None,
    *,
    fallback: Path = DEFAULT_PREFLIGHT_JSON,
) -> tuple[dict[str, Any], str]:
    """Resolve optional discovery evidence without making it a runtime dependency."""
    if explicit is not None:
        return load_json(explicit), str(explicit)
    candidate = latest_report_json(
        "weekly_miniprogram_devtools_run_preflight_",
        "weekly_miniprogram_devtools_rendered_run_preflight.json",
        fallback,
    )
    if candidate.exists():
        return load_json(candidate), str(candidate)
    return builtin_preflight(), "builtin"


def sanitize_log(value: str, limit: int = 200_000) -> str:
    text = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value or "")
    text = URL_QUERY_RE.sub(r"\1?[redacted_query]", text)
    return text[:limit]


def is_port_listening(port: int, host: str = "127.0.0.1", timeout_sec: float = 0.2) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_sec)
        return sock.connect_ex((host, int(port))) == 0


def choose_execution_port(port: int, *, avoid_busy_port: bool, max_scan: int = 50) -> dict[str, Any]:
    busy = is_port_listening(port)
    selected = int(port)
    if avoid_busy_port and busy:
        for candidate in range(int(port) + 1, int(port) + 1 + max_scan):
            if not is_port_listening(candidate):
                selected = candidate
                break
    return {
        "requested_port": int(port),
        "selected_port": selected,
        "requested_port_busy": busy,
        "avoid_busy_port": avoid_busy_port,
        "port_changed": selected != int(port),
    }


def choose_ide_http_port(
    environment_report: dict[str, Any],
    *,
    automator_port: int,
    explicit: str,
) -> int:
    """Reuse an existing IDE HTTP server while keeping the automator WS port independent."""
    explicit_value = str(explicit or "").strip()
    if explicit_value:
        port = int(explicit_value)
        if port <= 0:
            raise ValueError("MINIPROGRAM_DEVTOOLS_IDE_PORT must be a positive integer")
        return port
    summary = environment_report.get("summary", {})
    detected = sorted(
        {
            int(value)
            for value in summary.get("ide_http_ports", [])
            if str(value).isdigit() and int(value) > 0
        }
    )
    if len(detected) == 1:
        return detected[0]
    if len(detected) > 1:
        raise RuntimeError(f"multiple WeChat DevTools IDE HTTP ports detected: {detected}")
    if int(summary.get("process_count") or 0) > 0:
        raise RuntimeError("WeChat DevTools is running but its IDE HTTP port could not be detected")
    return int(automator_port)


def choose_devtools_local_app_data(environment_report: dict[str, Any], *, explicit: str) -> str:
    explicit_value = str(explicit or "").strip()
    if explicit_value:
        return explicit_value
    detected = sorted(
        {
            str(value).strip()
            for value in environment_report.get("summary", {}).get("devtools_local_app_data_paths", [])
            if str(value).strip()
        },
        key=str.lower,
    )
    if len(detected) == 1:
        return detected[0]
    if len(detected) > 1:
        raise RuntimeError(f"multiple WeChat DevTools LocalAppData roots detected: {detected}")
    return ""


def devtools_profile_environment(local_app_data: str) -> dict[str, str]:
    value = str(local_app_data or "").strip()
    if not value:
        return {}
    local_path = Path(value)
    if local_path.name.lower() != "local" or local_path.parent.name.lower() != "appdata":
        raise RuntimeError(
            "WeChat DevTools LocalAppData must use a complete <profile>\\AppData\\Local layout"
        )
    profile_root = local_path.parent.parent
    return {
        "USERPROFILE": str(profile_root),
        "LOCALAPPDATA": str(local_path),
        "APPDATA": str(local_path.parent / "Roaming"),
    }


def audit_devtools_environment(target_ports: list[int]) -> dict[str, Any]:
    """Run the local report-only DevTools environment audit in-process."""
    audit_path = Path(__file__).with_name("audit_miniprogram_devtools_environment.py")
    spec = importlib.util.spec_from_file_location("audit_miniprogram_devtools_environment", audit_path)
    auditor = importlib.util.module_from_spec(spec)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load environment auditor: {audit_path}")
    spec.loader.exec_module(auditor)
    ports = sorted({int(port) for port in target_ports})
    if sys.platform.startswith("win"):
        state = auditor.collect_windows_state(ports)
        process_rows = state["processes"]
        port_rows = state["listening_ports"]
    else:
        process_rows = []
        port_rows = [
            {"LocalAddress": "127.0.0.1", "LocalPort": port, "OwningProcess": None, "State": "Listen"}
            for port in ports
            if auditor.is_port_listening(port)
        ]
    return auditor.build_report(target_ports=ports, process_rows=process_rows, port_rows=port_rows)


def choose_step(preflight: dict[str, Any], script_name: str | None) -> dict[str, Any]:
    steps = [step for step in preflight.get("run_order", []) if step.get("script") in ALLOWED_SCRIPTS]
    if script_name:
        for step in steps:
            if step.get("script") == script_name:
                return step
        # Discovery reports are historical evidence and can legitimately
        # predate a newly required release scenario. An explicit allowed
        # scenario uses the versioned built-in contract instead of becoming
        # impossible to run because the latest old report omitted it.
        for step in BUILTIN_RUN_ORDER:
            if step.get("script") == script_name:
                return dict(step)
        raise ValueError(f"script is not in preflight run_order: {script_name}")
    if not steps:
        raise ValueError("preflight has no allowed rendered run steps")
    for step in steps:
        if not step.get("current_pass"):
            return step
    return steps[0]


def build_packet(
    *,
    preflight: dict[str, Any],
    script_name: str | None,
    out_dir: Path,
    port: int,
    avoid_busy_port: bool,
    execute: bool,
    timeout_sec: int,
) -> dict[str, Any]:
    step = choose_step(preflight, script_name)
    script_path = REPO_ROOT / "apps" / "weekly_activity_miniprogram" / "tests" / str(step["script"])
    if not script_path.exists():
        raise FileNotFoundError(script_path)
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    attempt_dir = out_dir / f"{script_path.stem}-{stamp}"
    stdout_log = attempt_dir / "stdout.log"
    stderr_log = attempt_dir / "stderr.log"
    summary_json = attempt_dir / "execution_summary.json"
    command = ["node", rel(script_path)]
    port_selection = choose_execution_port(port, avoid_busy_port=avoid_busy_port)
    return {
        "schema_version": "weekly_miniprogram_devtools_rendered_single_attempt.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": "weekly_miniprogram_devtools_rendered_single_attempt_packet_ready",
        "selected_script": step["script"],
        "execute_requested": execute,
        "executed": False,
        "timeout_sec": timeout_sec,
        "cwd": rel(REPO_ROOT),
        "command": command,
        "port_selection": port_selection,
        "environment_overrides": {
            "MINIPROGRAM_AUTOMATOR_LAUNCH": "1",
            "MINIPROGRAM_AUTOMATOR_PORT": str(port_selection["selected_port"]),
            "MINIPROGRAM_DEVTOOLS_IDE_PORT": "<auto>",
            "MINIPROGRAM_DEVTOOLS_LOCALAPPDATA": "<inherit-or-auto>",
            "MINIPROGRAM_DEVTOOLS_USERPROFILE": "<inherit-or-auto>",
            "MINIPROGRAM_DEVTOOLS_APPDATA": "<inherit-or-auto>",
            "MINIPROGRAM_AUTOMATOR_WS": "<unset>",
        },
        "environment_guard": {
            "required_clean_before_execute": True,
            "allow_dirty_override": False,
            "checked": False,
            "clean_for_automator_launch": None,
            "decision": "",
            "process_count": None,
            "busy_target_ports": [],
            "devtools_listener_ports": [],
            "blocked_reason": "",
        },
        "pass_contract": step.get("pass_contract", ""),
        "expected_artifact_dir_glob": step.get("expected_artifact_dir_glob", ""),
        "latest_report_before_attempt": step.get("latest_report", ""),
        "latest_failure_before_attempt": step.get("latest_failure", ""),
        "attempt_dir": rel(attempt_dir),
        "stdout_log": rel(stdout_log),
        "stderr_log": rel(stderr_log),
        "execution_summary_json": rel(summary_json),
        "execution": {
            "returncode": None,
            "stdout_bytes_redacted": 0,
            "stderr_bytes_redacted": 0,
            "timed_out": False,
        },
        "boundary": {
            "single_script_only": True,
            "devtools_launch_requires_execute_flag": True,
            "upload_executed": False,
            "review_submitted": False,
            "cloudrun_deployed": False,
            "db_graph_vector_write": False,
            "coordinate_write": False,
            "provider_or_llm_call": False,
            "secret_file_read": False,
            "broad_disk_scan": False,
            "stdout_stderr_redacted": True,
            "port_probe_only_connects_localhost": True,
            "devtools_environment_guard_checked": False,
            "dirty_devtools_environment_override": False,
        },
    }


def run_packet(
    packet: dict[str, Any],
    *,
    runner: Runner = subprocess.run,
    allow_dirty_devtools_environment: bool = False,
) -> dict[str, Any]:
    attempt_dir = REPO_ROOT / packet["attempt_dir"]
    attempt_dir.mkdir(parents=True, exist_ok=True)
    target_ports = [
        packet["port_selection"]["requested_port"],
        packet["port_selection"]["selected_port"],
    ]
    environment_report = audit_devtools_environment(target_ports)
    packet["environment_guard"] = {
        "required_clean_before_execute": True,
        "allow_dirty_override": allow_dirty_devtools_environment,
        "checked": True,
        "clean_for_automator_launch": environment_report.get("clean_for_automator_launch"),
        "decision": environment_report.get("decision", ""),
        "process_count": environment_report.get("summary", {}).get("process_count"),
        "busy_target_ports": environment_report.get("summary", {}).get("busy_target_ports", []),
        "devtools_listener_ports": environment_report.get("summary", {}).get("devtools_listener_ports", []),
        "blocked_reason": "",
    }
    packet["boundary"]["devtools_environment_guard_checked"] = True
    packet["boundary"]["dirty_devtools_environment_override"] = allow_dirty_devtools_environment
    if not packet["environment_guard"]["clean_for_automator_launch"] and not allow_dirty_devtools_environment:
        packet["decision"] = "weekly_miniprogram_devtools_rendered_single_attempt_blocked_dirty_environment"
        packet["executed"] = False
        packet["environment_guard"]["blocked_reason"] = "dirty_devtools_environment"
        summary_path = REPO_ROOT / packet["execution_summary_json"]
        summary_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return packet

    try:
        ide_http_port = choose_ide_http_port(
            environment_report,
            automator_port=int(packet["environment_overrides"]["MINIPROGRAM_AUTOMATOR_PORT"]),
            explicit=os.environ.get("MINIPROGRAM_DEVTOOLS_IDE_PORT", ""),
        )
        devtools_local_app_data = choose_devtools_local_app_data(
            environment_report,
            explicit=os.environ.get("MINIPROGRAM_DEVTOOLS_LOCALAPPDATA", ""),
        )
        devtools_profile_env = devtools_profile_environment(devtools_local_app_data)
    except (TypeError, ValueError, RuntimeError) as error:
        packet["decision"] = "weekly_miniprogram_devtools_rendered_single_attempt_blocked_ide_port"
        packet["executed"] = False
        packet["environment_guard"]["blocked_reason"] = str(error)
        summary_path = REPO_ROOT / packet["execution_summary_json"]
        summary_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return packet
    packet["environment_overrides"]["MINIPROGRAM_DEVTOOLS_IDE_PORT"] = str(ide_http_port)
    packet["environment_overrides"]["MINIPROGRAM_DEVTOOLS_LOCALAPPDATA"] = (
        devtools_local_app_data or "<inherit>"
    )
    packet["environment_overrides"]["MINIPROGRAM_DEVTOOLS_USERPROFILE"] = (
        devtools_profile_env.get("USERPROFILE") or "<inherit>"
    )
    packet["environment_overrides"]["MINIPROGRAM_DEVTOOLS_APPDATA"] = (
        devtools_profile_env.get("APPDATA") or "<inherit>"
    )

    env = os.environ.copy()
    env["MINIPROGRAM_AUTOMATOR_LAUNCH"] = packet["environment_overrides"]["MINIPROGRAM_AUTOMATOR_LAUNCH"]
    env["MINIPROGRAM_AUTOMATOR_PORT"] = packet["environment_overrides"]["MINIPROGRAM_AUTOMATOR_PORT"]
    env["MINIPROGRAM_DEVTOOLS_IDE_PORT"] = packet["environment_overrides"]["MINIPROGRAM_DEVTOOLS_IDE_PORT"]
    env.update(devtools_profile_env)
    env.pop("MINIPROGRAM_AUTOMATOR_WS", None)
    try:
        completed = runner(
            packet["command"],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(packet["timeout_sec"]),
            check=False,
        )
        stdout = sanitize_log(completed.stdout)
        stderr = sanitize_log(completed.stderr)
        (REPO_ROOT / packet["stdout_log"]).write_text(stdout, encoding="utf-8")
        (REPO_ROOT / packet["stderr_log"]).write_text(stderr, encoding="utf-8")
        packet["executed"] = True
        packet["decision"] = (
            "weekly_miniprogram_devtools_rendered_single_attempt_executed"
            if completed.returncode == 0
            else "weekly_miniprogram_devtools_rendered_single_attempt_failed"
        )
        packet["execution"] = {
            "returncode": completed.returncode,
            "stdout_bytes_redacted": len(stdout.encode("utf-8")),
            "stderr_bytes_redacted": len(stderr.encode("utf-8")),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as error:
        stdout = sanitize_log(error.stdout if isinstance(error.stdout, str) else "")
        stderr = sanitize_log(error.stderr if isinstance(error.stderr, str) else "")
        (REPO_ROOT / packet["stdout_log"]).write_text(stdout, encoding="utf-8")
        (REPO_ROOT / packet["stderr_log"]).write_text(stderr, encoding="utf-8")
        packet["executed"] = True
        packet["decision"] = "weekly_miniprogram_devtools_rendered_single_attempt_timeout"
        packet["execution"] = {
            "returncode": None,
            "stdout_bytes_redacted": len(stdout.encode("utf-8")),
            "stderr_bytes_redacted": len(stderr.encode("utf-8")),
            "timed_out": True,
        }
    summary_path = REPO_ROOT / packet["execution_summary_json"]
    summary_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return packet


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# Weekly Mini-Program DevTools Rendered Single Attempt",
        "",
        f"Generated: `{packet['generated_at']}`",
        "",
        f"Decision: `{packet['decision']}`",
        f"Selected script: `{packet['selected_script']}`",
        f"Execute requested: `{str(packet['execute_requested']).lower()}`",
        f"Executed: `{str(packet['executed']).lower()}`",
        "",
        "## Command",
        "",
        "```powershell",
        "$env:MINIPROGRAM_AUTOMATOR_LAUNCH='1'; $env:MINIPROGRAM_AUTOMATOR_PORT='{port}'; $env:MINIPROGRAM_DEVTOOLS_IDE_PORT='{ide_port}'; node {script}".format(
            port=packet["environment_overrides"]["MINIPROGRAM_AUTOMATOR_PORT"],
            ide_port=packet["environment_overrides"]["MINIPROGRAM_DEVTOOLS_IDE_PORT"],
            script=packet["command"][1],
        ),
        "```",
        "",
        "## Contract",
        "",
        f"- Pass contract: {packet['pass_contract']}",
        f"- Expected artifact glob: `{packet['expected_artifact_dir_glob']}`",
        f"- Attempt dir: `{packet['attempt_dir']}`",
        f"- Execution summary: `{packet['execution_summary_json']}`",
        "",
        "## Execution",
        "",
        f"- Return code: `{packet['execution']['returncode']}`",
        f"- Timed out: `{str(packet['execution']['timed_out']).lower()}`",
        f"- Redacted stdout bytes: `{packet['execution']['stdout_bytes_redacted']}`",
        f"- Redacted stderr bytes: `{packet['execution']['stderr_bytes_redacted']}`",
        f"- Requested port busy: `{str(packet['port_selection']['requested_port_busy']).lower()}`",
        f"- Selected port: `{packet['port_selection']['selected_port']}`",
        f"- Port changed: `{str(packet['port_selection']['port_changed']).lower()}`",
        f"- Environment guard checked: `{str(packet['environment_guard']['checked']).lower()}`",
        f"- Environment clean: `{str(packet['environment_guard']['clean_for_automator_launch']).lower()}`",
        f"- Environment decision: `{packet['environment_guard']['decision']}`",
        f"- Environment process count: `{packet['environment_guard']['process_count']}`",
        f"- Environment busy target ports: `{', '.join(str(port) for port in packet['environment_guard']['busy_target_ports']) or '<none>'}`",
        f"- Dirty environment override: `{str(packet['environment_guard']['allow_dirty_override']).lower()}`",
        "",
        "## Boundary",
        "",
        "This wrapper runs at most one rendered DevTools script and only when `--execute` is supplied. It does not upload, submit review, deploy CloudRun, mutate DB/graph/vector data, write coordinates, call map providers or LLMs, read secret files, or scan broad disks.",
        "",
    ]
    return "\n".join(lines)


def write_outputs(packet: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_miniprogram_devtools_rendered_single_attempt.json"
    md_path = out_dir / "weekly_miniprogram_devtools_rendered_single_attempt.md"
    json_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(packet), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-json", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--script", choices=sorted(ALLOWED_SCRIPTS), default=None)
    parser.add_argument("--port", type=int, default=9430)
    parser.add_argument("--avoid-busy-port", action="store_true")
    parser.add_argument(
        "--allow-dirty-devtools-environment",
        action="store_true",
        help="Allow --execute to launch even when the local DevTools environment audit is dirty.",
    )
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    preflight, preflight_source = resolve_preflight(args.preflight_json)
    packet = build_packet(
        preflight=preflight,
        script_name=args.script,
        out_dir=args.out_dir,
        port=args.port,
        avoid_busy_port=args.avoid_busy_port,
        execute=args.execute,
        timeout_sec=args.timeout_sec,
    )
    packet["preflight_source"] = preflight_source
    if args.execute:
        packet = run_packet(packet, allow_dirty_devtools_environment=args.allow_dirty_devtools_environment)
    paths = write_outputs(packet, args.out_dir)
    print(
        json.dumps(
            {
                "decision": packet["decision"],
                "selected_script": packet["selected_script"],
                "executed": packet["executed"],
                "returncode": packet["execution"]["returncode"],
                "requested_port_busy": packet["port_selection"]["requested_port_busy"],
                "selected_port": packet["port_selection"]["selected_port"],
                "environment_guard_checked": packet["environment_guard"]["checked"],
                "environment_clean": packet["environment_guard"]["clean_for_automator_launch"],
                "json": str(paths["json"]),
                "markdown": str(paths["markdown"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not args.execute or packet["execution"]["returncode"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
