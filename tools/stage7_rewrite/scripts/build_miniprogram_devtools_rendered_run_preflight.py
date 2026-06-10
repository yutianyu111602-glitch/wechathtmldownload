#!/usr/bin/env python3
"""Build a report-only run preflight for rendered WeChat DevTools scripts.

This does not launch DevTools. It turns the current rendered-coverage audit into
a concrete, safe run plan for producing fresh pass artifacts later.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUDIT_JSON = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_miniprogram_devtools_rendered_coverage_s34_20260531"
    / "weekly_miniprogram_devtools_rendered_coverage_audit.json"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_miniprogram_devtools_run_preflight_20260603_frontend_hotfix"
)
DEFAULT_TARGET_PORTS = [9430, 9431]

SCRIPT_ORDER = [
    "devtools-current-package-rendered.cjs",
    "devtools-loading-fallback.cjs",
    "devtools-haptics.cjs",
    "devtools-extreme.cjs",
]

PASS_CONTRACTS = {
    "devtools-current-package-rendered.cjs": "report.json first step proves itemCount/totalItems >= 78, no cache/snapshot notice, no 2026-05-29, includes 2026-06-02 and 2026-06-03, poster coverUrl values exist, and at least one poster image load event with zero image errors",
    "devtools-loading-fallback.cjs": "report.json first step has itemCount > 0 and abortCount >= 3",
    "devtools-haptics.cjs": "report.json contains required haptic check counts and no exceptions",
    "devtools-extreme.cjs": "report.json contains at least 8 rendered steps and no exceptions",
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


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def script_command(script_name: str) -> str:
    return (
        "npm run weekly:miniprogram:devtools-rendered:single-attempt -- "
        f"--execute --avoid-busy-port --script {script_name} --timeout-sec 180"
    )


def audit_devtools_environment(target_ports: list[int]) -> dict[str, Any]:
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


def environment_guard_from_payload(environment_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not environment_payload:
        return {
            "checked": False,
            "clean_for_automator_launch": None,
            "decision": "",
            "process_count": None,
            "busy_target_ports": [],
            "devtools_listener_ports": [],
        }
    summary = environment_payload.get("summary", {}) if isinstance(environment_payload.get("summary"), dict) else {}
    return {
        "checked": True,
        "clean_for_automator_launch": environment_payload.get("clean_for_automator_launch"),
        "decision": environment_payload.get("decision", ""),
        "process_count": summary.get("process_count"),
        "busy_target_ports": summary.get("busy_target_ports", []),
        "devtools_listener_ports": summary.get("devtools_listener_ports", []),
    }


def build_preflight(audit_payload: dict[str, Any], environment_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    scripts_by_name = {script.get("name"): script for script in audit_payload.get("scripts", [])}
    artifacts_by_name = {artifact.get("script"): artifact for artifact in audit_payload.get("artifacts", [])}
    environment_guard = environment_guard_from_payload(environment_payload)
    findings: list[dict[str, Any]] = []
    steps = []

    for index, script_name in enumerate(SCRIPT_ORDER, start=1):
        script = scripts_by_name.get(script_name, {})
        artifact = artifacts_by_name.get(script_name, {})
        if not script.get("exists"):
            findings.append({"code": "missing_rendered_script", "script": script_name})
        if not script.get("defaults_to_launch_mode"):
            findings.append({"code": "script_does_not_default_to_launch_mode", "script": script_name})
        if script.get("uses_fixed_ws_default"):
            findings.append({"code": "script_uses_fixed_ws_default", "script": script_name})
        if script.get("stale_auto_port_token"):
            findings.append({"code": "script_has_stale_auto_port_hint", "script": script_name})

        prefix = script_name.replace(".cjs", "")
        steps.append(
            {
                "order": index,
                "script": script_name,
                "command": script_command(script_name),
                "artifact_prefix": prefix,
                "expected_artifact_dir_glob": f"apps\\weekly_activity_miniprogram\\test-artifacts\\{prefix}-*",
                "pass_contract": PASS_CONTRACTS[script_name],
                "latest_report": artifact.get("latest_report", ""),
                "latest_failure": artifact.get("latest_failure", ""),
                "current_pass": bool(artifact.get("current_pass")),
            }
        )

    protocol_blockers = [
        blocker
        for blocker in audit_payload.get("blockers", [])
        if blocker.get("code") == "current_devtools_automator_protocol_mismatch"
    ]
    environment_blockers = []
    if environment_guard["checked"] and environment_guard["clean_for_automator_launch"] is False:
        environment_blockers.append(
            {
                "code": "local_devtools_environment_dirty",
                "notes": "Existing DevTools processes or target port listeners make rendered launch unsafe without an explicit override.",
                "process_count": environment_guard["process_count"],
                "busy_target_ports": environment_guard["busy_target_ports"],
            }
        )
    ready_to_attempt = (
        not findings
        and all(step["command"] for step in steps)
        and not environment_blockers
    )
    decision = (
        "weekly_miniprogram_devtools_rendered_run_preflight_ready"
        if ready_to_attempt
        else "weekly_miniprogram_devtools_rendered_run_preflight_blocked"
    )
    return {
        "schema_version": "weekly_miniprogram_devtools_rendered_run_preflight.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "summary": {
            "step_count": len(steps),
            "finding_count": len(findings),
            "protocol_blocker_count": len(protocol_blockers),
            "environment_blocker_count": len(environment_blockers),
            "ready_to_attempt_launch_mode": ready_to_attempt,
            "rendered_coverage_proven": False,
        },
        "environment_guard": environment_guard,
        "run_order": steps,
        "rules": [
            "Do not set MINIPROGRAM_AUTOMATOR_WS unless a compatible bridge has produced a verified dynamic endpoint.",
            "Use the single-attempt wrapper so the S55/S56 local DevTools environment guard runs before launch.",
            "Default to launch mode so miniprogram-automator can parse DevTools dynamic socket output.",
            "A successful run must produce fresh report.json artifacts for all required scripts.",
            "Do not claim rendered coverage while blockers remain or current_pass is false for any script.",
        ],
        "blockers": protocol_blockers + environment_blockers,
        "findings": findings,
        "boundary": {
            "report_only": True,
            "devtools_launched": False,
            "upload_executed": False,
            "review_submitted": False,
            "cloudrun_deployed": False,
            "db_graph_vector_write": False,
            "coordinate_write": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
        "exit_code_policy": {
            "blocked_returns_nonzero": True,
            "allow_blocked_exit_zero": False,
        },
    }


def write_outputs(packet: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_miniprogram_devtools_rendered_run_preflight.json"
    md_path = out_dir / "weekly_miniprogram_devtools_rendered_run_preflight.md"
    json_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(packet), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        "# Weekly Mini-Program DevTools Rendered Run Preflight S51",
        "",
        f"Generated: `{packet['generated_at']}`",
        "",
        f"Decision: `{packet['decision']}`",
        "",
        "## Summary",
        "",
        f"- Step count: `{summary['step_count']}`",
        f"- Findings: `{summary['finding_count']}`",
        f"- Protocol blockers: `{summary['protocol_blocker_count']}`",
        f"- Environment blockers: `{summary['environment_blocker_count']}`",
        f"- Ready to attempt launch mode: `{summary['ready_to_attempt_launch_mode']}`",
        f"- Rendered coverage proven: `{summary['rendered_coverage_proven']}`",
        "",
        "## Environment Guard",
        "",
        f"- Checked: `{str(packet['environment_guard']['checked']).lower()}`",
        f"- Clean for automator launch: `{str(packet['environment_guard']['clean_for_automator_launch']).lower()}`",
        f"- Decision: `{packet['environment_guard']['decision']}`",
        f"- Process count: `{packet['environment_guard']['process_count']}`",
        f"- Busy target ports: `{', '.join(str(port) for port in packet['environment_guard']['busy_target_ports']) or '<none>'}`",
        "",
        "## Run Order",
        "",
        "| Order | Script | Current pass | Artifact prefix | Pass contract |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for step in packet["run_order"]:
        lines.append(
            "| {order} | `{script}` | `{current}` | `{prefix}` | {contract} |".format(
                order=step["order"],
                script=step["script"],
                current=str(step["current_pass"]).lower(),
                prefix=step["artifact_prefix"],
                contract=step["pass_contract"],
            )
        )
    lines.extend(["", "## Commands", ""])
    for step in packet["run_order"]:
        lines.extend([f"### {step['script']}", "", "```powershell", step["command"], "```", ""])
    lines.extend(["## Blockers", ""])
    if packet["blockers"]:
        for blocker in packet["blockers"]:
            lines.append(f"- `{blocker.get('code')}`: {blocker.get('notes', '')}")
    else:
        lines.append("No current protocol blocker was copied from the rendered coverage audit.")
    lines.extend(["", "## Findings", ""])
    if packet["findings"]:
        for finding in packet["findings"]:
            lines.append(f"- `{finding['code']}`: `{finding.get('script', '')}`")
    else:
        lines.append("No preflight hygiene findings.")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This preflight is report-only. It did not launch DevTools, upload or submit a mini-program, deploy CloudRun, mutate DB/graph/vector data, write coordinates, call providers or LLMs, read secrets, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-json", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--ports", default="9430,9431", help="Comma-separated target ports for the environment guard.")
    parser.add_argument("--skip-environment-guard", action="store_true")
    parser.add_argument(
        "--allow-blocked-exit-zero",
        action="store_true",
        help="Write a blocked report but return exit code 0 for report collection jobs.",
    )
    args = parser.parse_args(argv)
    if args.audit_json is None:
        args.audit_json = latest_report_json(
            "weekly_miniprogram_devtools_rendered_coverage_",
            "weekly_miniprogram_devtools_rendered_coverage_audit.json",
            DEFAULT_AUDIT_JSON,
        )
    return args


def parse_ports(value: str) -> list[int]:
    ports: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if part:
            ports.append(int(part))
    return ports or list(DEFAULT_TARGET_PORTS)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    audit_payload = load_json(args.audit_json, {})
    environment_payload = None if args.skip_environment_guard else audit_devtools_environment(parse_ports(args.ports))
    packet = build_preflight(audit_payload, environment_payload=environment_payload)
    packet["exit_code_policy"]["allow_blocked_exit_zero"] = args.allow_blocked_exit_zero
    paths = write_outputs(packet, args.out_dir)
    print(
        json.dumps(
            {
                "decision": packet["decision"],
                "step_count": packet["summary"]["step_count"],
                "finding_count": packet["summary"]["finding_count"],
                "protocol_blocker_count": packet["summary"]["protocol_blocker_count"],
                "environment_blocker_count": packet["summary"]["environment_blocker_count"],
                "ready_to_attempt_launch_mode": packet["summary"]["ready_to_attempt_launch_mode"],
                "json": str(paths["json"]),
                "markdown": str(paths["markdown"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.allow_blocked_exit_zero:
        return 0
    return 0 if packet["summary"]["ready_to_attempt_launch_mode"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
