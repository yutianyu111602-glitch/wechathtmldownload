#!/usr/bin/env python3
"""Audit the rendered WeChat DevTools mini-program coverage lane.

Report-only. This does not launch DevTools, upload or submit a mini-program,
deploy CloudRun, call providers or LLMs, read secrets, write coordinates,
mutate databases, or scan broad disks.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MINIAPP_ROOT = REPO_ROOT / "apps" / "weekly_activity_miniprogram"
DEFAULT_FRONTEND_CLI_REPORT = REPO_ROOT / "reports" / "WEEKLY_MINIPROGRAM_FRONTEND_CLI_TEST_AUDIT_20260531.md"
DEFAULT_PROTOCOL_REPORT = REPO_ROOT / "reports" / "WEEKLY_MINIPROGRAM_DEVTOOLS_CURRENT_CLI_PROTOCOL_AUDIT_20260531.md"
DEFAULT_CLI_PATH = Path("C:/Program Files (x86)/Tencent/微信web开发者工具/cli.bat")
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_miniprogram_devtools_rendered_coverage_s34_20260531"
)

REQUIRED_RENDERED_SCRIPTS = {
    "devtools-current-package-rendered.cjs": "rendered current-package freshness, no snapshot/cache notice, and poster cover evidence",
    "devtools-extreme.cjs": "end-to-end rendered navigation/filter/relation/extreme behavior",
    "devtools-haptics.cjs": "rendered haptic interaction behavior",
    "devtools-loading-fallback.cjs": "rendered first-screen loading fallback behavior",
}

ARTIFACT_PREFIX_BY_SCRIPT = {
    "devtools-current-package-rendered.cjs": "devtools-current-package-rendered",
    "devtools-extreme.cjs": "devtools-extreme",
    "devtools-haptics.cjs": "devtools-haptics",
    "devtools-loading-fallback.cjs": "devtools-loading-fallback",
}

REQUIRED_HAPTIC_CHECKS = {
    "feedSlow": 1,
    "feedTouchMove": 1,
    "feedFast": 1,
    "feedBackAndForth": 1,
    "posterFast": 1,
    "topTab": 2,
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in value.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def collect_devtools_scripts(miniapp_root: Path) -> list[dict[str, Any]]:
    tests_dir = miniapp_root / "tests"
    scripts: list[dict[str, Any]] = []
    for name, scope in REQUIRED_RENDERED_SCRIPTS.items():
        path = tests_dir / name
        exists = path.exists()
        text = read_text(path) if exists else ""
        scripts.append(
            {
                "name": name,
                "scope": scope,
                "path": str(path),
                "exists": exists,
                "uses_current_port_flag": "--port 9430" in text or "port: launchPort" in text,
                "stale_auto_port_token": "--auto-port" in text,
                "supports_launch_mode": "MINIPROGRAM_AUTOMATOR_LAUNCH" in text,
                "supports_ws_connect_mode": "MINIPROGRAM_AUTOMATOR_WS" in text,
                "uses_fixed_ws_default": "const DEFAULT_WS" in text
                or "MINIPROGRAM_AUTOMATOR_WS || DEFAULT_WS" in text
                or "ws://127.0.0.1:9430" in text,
                "defaults_to_launch_mode": "const launchMode" in text and "!explicitConnectMode" in text,
            }
        )
    return scripts


def run_cli_help(cli_path: Path, timeout_s: int = 20) -> dict[str, Any]:
    if not cli_path.exists():
        return {"available": False, "exit_code": None, "stdout": "", "stderr": "", "error": "cli_path_missing"}
    try:
        completed = subprocess.run(
            [str(cli_path), "auto", "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
        return {
            "available": True,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "error": "",
        }
    except Exception as error:  # pragma: no cover - machine specific failure path
        return {"available": True, "exit_code": None, "stdout": "", "stderr": "", "error": str(error)}


def inspect_automator(miniapp_root: Path) -> dict[str, Any]:
    package_path = miniapp_root / "node_modules" / "miniprogram-automator" / "package.json"
    launcher_path = miniapp_root / "node_modules" / "miniprogram-automator" / "out" / "Launcher.js"
    result: dict[str, Any] = {
        "package_path": str(package_path),
        "launcher_path": str(launcher_path),
        "installed": package_path.exists() and launcher_path.exists(),
        "version": "",
        "version_supported": False,
        "launcher_uses_cli_port": False,
        "launcher_connects_bare_ws": False,
    }
    if not result["installed"]:
        return result
    package = read_json(package_path)
    launcher_text = read_text(launcher_path)
    version = str(package.get("version", ""))
    result.update(
        {
            "version": version,
            "version_supported": version_tuple(version) >= (0, 12, 1),
            "launcher_uses_cli_port": '"--port"' in launcher_text or "'--port'" in launcher_text,
            "launcher_connects_bare_ws": "connectTool({ wsEndpoint:" in launcher_text
            and "ws://127.0.0.1" in launcher_text,
        }
    )
    return result


def latest_file(paths: list[Path]) -> Path | None:
    return max(paths, key=lambda path: (path.stat().st_mtime_ns, str(path))) if paths else None


def haptic_checks_pass(checks: dict[str, Any]) -> bool:
    for name, minimum in REQUIRED_HAPTIC_CHECKS.items():
        value = checks.get(name)
        if not isinstance(value, dict) or int(value.get("count") or 0) < minimum:
            return False
    bottom_api = checks.get("bottomTabSwitchApi") if isinstance(checks.get("bottomTabSwitchApi"), dict) else {}
    bottom_hook = checks.get("bottomTabHook") if isinstance(checks.get("bottomTabHook"), dict) else {}
    return int(bottom_api.get("count") or 0) >= 1 or int(bottom_hook.get("count") or 0) >= 1


def artifact_report_passes(script_name: str, payload: dict[str, Any]) -> tuple[bool, str]:
    if payload.get("error"):
        return False, "report_contains_error"
    exceptions = payload.get("exceptions")
    if isinstance(exceptions, list) and exceptions:
        return False, "report_contains_runtime_exceptions"

    if script_name == "devtools-haptics.cjs":
        checks = payload.get("checks")
        if not isinstance(checks, dict) or not haptic_checks_pass(checks):
            return False, "haptic_required_checks_missing_or_below_threshold"
        return True, "haptic_checks_passed"

    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return False, "rendered_steps_missing"

    if script_name == "devtools-extreme.cjs":
        return (len(steps) >= 8, "extreme_steps_passed" if len(steps) >= 8 else "extreme_step_count_too_low")

    if script_name == "devtools-current-package-rendered.cjs":
        first = steps[0] if isinstance(steps[0], dict) else {}
        item_count = int(first.get("itemCount") or 0)
        total_items = int(first.get("totalItems") or 0)
        poster_count = int(first.get("posterCoverCount") or 0)
        popular_count = int(first.get("popularItemCount") or 0)
        image_load_count = int(first.get("posterImageLoadCount") or 0)
        image_error_count = int(first.get("posterImageErrorCount") or 0)
        dates = first.get("dates") if isinstance(first.get("dates"), list) else []
        ok = (
            item_count >= 78
            and total_items >= 78
            and first.get("cacheNotice", "") == ""
            and "2026-05-29" not in dates
            and "2026-06-02" in dates
            and "2026-06-03" in dates
            and popular_count > 0
            and poster_count > 0
            and poster_count >= min(8, popular_count)
            and image_load_count >= 1
            and image_error_count == 0
        )
        return (ok, "current_package_rendered_passed" if ok else "current_package_rendered_contract_invalid")

    if script_name == "devtools-loading-fallback.cjs":
        first = steps[0] if isinstance(steps[0], dict) else {}
        ok = int(first.get("itemCount") or 0) > 0 and int(first.get("abortCount") or 0) >= 3
        return (ok, "loading_fallback_passed" if ok else "loading_fallback_counts_invalid")

    return False, "unknown_script_artifact_contract"


def collect_rendered_artifacts(
    *,
    miniapp_root: Path,
    scripts: list[dict[str, Any]],
    protocol_report: Path,
    current_protocol_mismatch: bool,
) -> list[dict[str, Any]]:
    artifact_root = miniapp_root / "test-artifacts"
    protocol_mtime_ns = protocol_report.stat().st_mtime_ns if protocol_report.exists() else 0
    results: list[dict[str, Any]] = []

    for script in scripts:
        script_name = script["name"]
        prefix = ARTIFACT_PREFIX_BY_SCRIPT[script_name]
        dirs = [path for path in artifact_root.glob(f"{prefix}-*") if path.is_dir()] if artifact_root.exists() else []
        latest_report = latest_file([path / "report.json" for path in dirs if (path / "report.json").exists()])
        latest_failure = latest_file([path / "failure.json" for path in dirs if (path / "failure.json").exists()])
        script_path = Path(script["path"])
        script_mtime_ns = script_path.stat().st_mtime_ns if script_path.exists() else 0

        status = "missing_report"
        reason = "no_report_json_found"
        report_mtime_ns = latest_report.stat().st_mtime_ns if latest_report else 0
        report_passed = False

        if latest_report:
            try:
                payload = read_json(latest_report)
                report_passed, reason = artifact_report_passes(script_name, payload)
                status = "report_passed" if report_passed else "report_failed_contract"
            except Exception as error:  # pragma: no cover - corrupt local artifact
                status = "report_unreadable"
                reason = str(error)

        failure_mtime_ns = latest_failure.stat().st_mtime_ns if latest_failure else 0
        failure_newer_than_report = bool(latest_failure and failure_mtime_ns > report_mtime_ns)
        fresh_for_script = bool(latest_report and report_mtime_ns >= script_mtime_ns)
        fresh_after_protocol_blocker = bool(
            latest_report and (not current_protocol_mismatch or report_mtime_ns >= protocol_mtime_ns)
        )
        current_pass = bool(report_passed and fresh_for_script and fresh_after_protocol_blocker and not failure_newer_than_report)

        results.append(
            {
                "script": script_name,
                "artifact_prefix": prefix,
                "latest_report": str(latest_report) if latest_report else "",
                "latest_failure": str(latest_failure) if latest_failure else "",
                "status": status,
                "reason": reason,
                "report_passed": report_passed,
                "failure_newer_than_report": failure_newer_than_report,
                "fresh_for_script": fresh_for_script,
                "fresh_after_protocol_blocker": fresh_after_protocol_blocker,
                "current_pass": current_pass,
            }
        )
    return results


def inspect_environment_report(environment_report: Path | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(environment_report) if environment_report else "",
        "provided": environment_report is not None,
        "exists": False,
        "readable": False,
        "decision": "",
        "clean_for_automator_launch": None,
        "process_count": None,
        "busy_target_ports": [],
        "devtools_listener_ports": [],
        "finding_count": None,
        "read_error": "",
    }
    if environment_report is None:
        return result
    if not environment_report.exists():
        result["read_error"] = "environment_report_missing"
        return result
    result["exists"] = True
    try:
        payload = read_json(environment_report)
    except Exception as error:
        result["read_error"] = str(error)
        return result

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    result.update(
        {
            "readable": True,
            "decision": str(payload.get("decision") or ""),
            "clean_for_automator_launch": payload.get("clean_for_automator_launch"),
            "process_count": summary.get("process_count"),
            "busy_target_ports": summary.get("busy_target_ports") if isinstance(summary.get("busy_target_ports"), list) else [],
            "devtools_listener_ports": summary.get("devtools_listener_ports")
            if isinstance(summary.get("devtools_listener_ports"), list)
            else [],
            "finding_count": summary.get("finding_count"),
        }
    )
    return result


def audit_rendered_coverage(
    *,
    miniapp_root: Path,
    cli_path: Path,
    frontend_cli_report: Path,
    protocol_report: Path,
    environment_report: Path | None = None,
    cli_help_text: str | None = None,
) -> dict[str, Any]:
    scripts = collect_devtools_scripts(miniapp_root)
    automator = inspect_automator(miniapp_root)
    environment = inspect_environment_report(environment_report)
    frontend_text = read_text(frontend_cli_report) if frontend_cli_report.exists() else ""
    protocol_text = read_text(protocol_report) if protocol_report.exists() else ""
    if cli_help_text is None:
        cli_help = run_cli_help(cli_path)
        help_text = f"{cli_help.get('stdout', '')}\n{cli_help.get('stderr', '')}"
    else:
        cli_help = {"available": True, "exit_code": 0, "stdout": cli_help_text, "stderr": "", "error": ""}
        help_text = cli_help_text

    findings: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    if environment["provided"] and not environment["exists"]:
        findings.append({"code": "devtools_environment_report_missing", "path": environment["path"]})
    elif environment["provided"] and not environment["readable"]:
        findings.append(
            {
                "code": "devtools_environment_report_unreadable",
                "path": environment["path"],
                "error": environment["read_error"],
            }
        )
    elif environment["clean_for_automator_launch"] is False:
        blockers.append(
            {
                "code": "current_devtools_environment_dirty",
                "evidence": environment["path"],
                "notes": "Current local WeChat DevTools process or target-port state is dirty, so rendered automator launch is not safe to claim.",
            }
        )

    for script in scripts:
        if not script["exists"]:
            findings.append({"code": "missing_rendered_devtools_script", "script": script["name"]})
        if script["stale_auto_port_token"]:
            findings.append({"code": "stale_auto_port_hint", "script": script["name"]})
        if script["exists"] and not script["supports_launch_mode"]:
            findings.append({"code": "missing_launch_mode", "script": script["name"]})
        if script["exists"] and not script["supports_ws_connect_mode"]:
            findings.append({"code": "missing_ws_connect_mode", "script": script["name"]})
        if script["exists"] and script["uses_fixed_ws_default"]:
            findings.append({"code": "fixed_ws_endpoint_default", "script": script["name"]})
        if script["exists"] and not script["defaults_to_launch_mode"]:
            findings.append({"code": "rendered_script_does_not_default_to_launch_mode", "script": script["name"]})

    if cli_help["error"]:
        findings.append({"code": "devtools_cli_help_unavailable", "error": cli_help["error"]})
    if "--port" not in help_text:
        findings.append({"code": "devtools_cli_help_missing_port_flag"})
    if "--auto-port" in help_text:
        findings.append({"code": "devtools_cli_help_still_lists_auto_port"})

    if not automator["installed"]:
        findings.append({"code": "miniprogram_automator_missing"})
    elif not automator["version_supported"]:
        findings.append({"code": "miniprogram_automator_version_unsupported", "version": automator["version"]})

    static_cli_green = (
        "node --test tests/*.test.cjs" in frontend_text
        and ("fail: `0`" in frontend_text or "`0` failed" in frontend_text)
        and "Clean CI quality also passed" in frontend_text
    )
    if not static_cli_green:
        findings.append({"code": "static_cli_frontend_evidence_missing_or_not_green"})

    current_protocol_mismatch = (
        "weekly_miniprogram_devtools_automator_current_cli_protocol_mismatch_confirmed" in protocol_text
        and "tool_getinfo_response=false" in protocol_text
    )
    artifacts = collect_rendered_artifacts(
        miniapp_root=miniapp_root,
        scripts=scripts,
        protocol_report=protocol_report,
        current_protocol_mismatch=current_protocol_mismatch,
    )
    current_artifact_pass_count = sum(1 for artifact in artifacts if artifact["current_pass"])
    current_rendered_pass_artifacts = current_artifact_pass_count == len(REQUIRED_RENDERED_SCRIPTS)
    if current_protocol_mismatch:
        if current_rendered_pass_artifacts:
            pass
        else:
            blockers.append(
                {
                    "code": "current_devtools_automator_protocol_mismatch",
                    "evidence": str(protocol_report),
                    "notes": "Current DevTools opens the long connection, but miniprogram-automator does not complete the command protocol.",
                }
            )
    else:
        if not current_rendered_pass_artifacts:
            findings.append({"code": "current_protocol_mismatch_evidence_missing"})

    rendered_coverage_proven = not findings and not blockers and current_rendered_pass_artifacts
    if findings:
        decision = "weekly_miniprogram_devtools_rendered_coverage_audit_failed"
    elif rendered_coverage_proven:
        decision = "weekly_miniprogram_devtools_rendered_coverage_proven"
    elif blockers:
        blocker_codes = {blocker["code"] for blocker in blockers}
        if "current_devtools_automator_protocol_mismatch" in blocker_codes:
            decision = "weekly_miniprogram_devtools_rendered_coverage_blocked_with_current_protocol_evidence"
        elif "current_devtools_environment_dirty" in blocker_codes:
            decision = "weekly_miniprogram_devtools_rendered_coverage_blocked_with_current_environment_evidence"
        else:
            decision = "weekly_miniprogram_devtools_rendered_coverage_blocked_with_current_evidence"
    else:
        decision = "weekly_miniprogram_devtools_rendered_coverage_unproven"

    return {
        "schema_version": "weekly_miniprogram_devtools_rendered_coverage_audit.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": decision,
        "rendered_coverage_proven": rendered_coverage_proven,
        "critical_script_count": len(scripts),
        "current_artifact_pass_count": current_artifact_pass_count,
        "finding_count": len(findings),
        "blocking_count": len(blockers),
        "scripts": scripts,
        "artifacts": artifacts,
        "environment": environment,
        "cli": {
            "path": str(cli_path),
            "help_available": cli_help["available"],
            "help_exit_code": cli_help["exit_code"],
            "help_contains_port": "--port" in help_text,
            "help_contains_auto_port": "--auto-port" in help_text,
            "help_error": cli_help["error"],
        },
        "automator": automator,
        "evidence": {
            "frontend_cli_report": str(frontend_cli_report),
            "static_cli_green": static_cli_green,
            "protocol_report": str(protocol_report),
            "current_protocol_mismatch": current_protocol_mismatch,
        },
        "findings": findings,
        "blockers": blockers,
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
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weekly Mini-Program DevTools Rendered Coverage Audit",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Rendered coverage proven: `{str(report['rendered_coverage_proven']).lower()}`",
        f"- Critical scripts: `{report['critical_script_count']}`",
        f"- Current pass artifacts: `{report['current_artifact_pass_count']}`",
        f"- Findings: `{report['finding_count']}`",
        f"- Blockers: `{report['blocking_count']}`",
        "",
        "## Critical Rendered Scripts",
        "",
        "| Script | Exists | Launch | WS | Launch default | Fixed WS default | Stale auto-port | Scope |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for script in report["scripts"]:
        lines.append(
            "| `{name}` | `{exists}` | `{launch}` | `{ws}` | `{launch_default}` | `{fixed_ws}` | `{stale}` | {scope} |".format(
                name=script["name"],
                exists=str(script["exists"]).lower(),
                launch=str(script["supports_launch_mode"]).lower(),
                ws=str(script["supports_ws_connect_mode"]).lower(),
                launch_default=str(script["defaults_to_launch_mode"]).lower(),
                fixed_ws=str(script["uses_fixed_ws_default"]).lower(),
                stale=str(script["stale_auto_port_token"]).lower(),
                scope=script["scope"],
            )
        )

    lines.extend(
        [
            "",
            "## Rendered Artifacts",
            "",
            "| Script | Current pass | Status | Fresh for script | Fresh after protocol | Latest report | Latest failure |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for artifact in report["artifacts"]:
        lines.append(
            "| `{script}` | `{current}` | `{status}` | `{fresh_script}` | `{fresh_protocol}` | `{report_path}` | `{failure_path}` |".format(
                script=artifact["script"],
                current=str(artifact["current_pass"]).lower(),
                status=artifact["status"],
                fresh_script=str(artifact["fresh_for_script"]).lower(),
                fresh_protocol=str(artifact["fresh_after_protocol_blocker"]).lower(),
                report_path=artifact["latest_report"] or "<missing>",
                failure_path=artifact["latest_failure"] or "<missing>",
            )
        )

    environment = report["environment"]
    lines.extend(
        [
            "",
            "## DevTools Environment",
            "",
            f"- Environment report: `{environment['path'] or '<not supplied>'}`",
            f"- Clean for automator launch: `{str(environment['clean_for_automator_launch']).lower()}`",
            f"- DevTools process count: `{environment['process_count']}`",
            f"- Busy target ports: `{', '.join(str(port) for port in environment['busy_target_ports']) or '<none>'}`",
            f"- DevTools listener ports: `{', '.join(str(port) for port in environment['devtools_listener_ports']) or '<none>'}`",
        ]
    )

    lines.extend(
        [
            "",
            "## CLI And Automator",
            "",
            f"- DevTools CLI: `{report['cli']['path']}`",
            f"- CLI help contains `--port`: `{str(report['cli']['help_contains_port']).lower()}`",
            f"- CLI help contains `--auto-port`: `{str(report['cli']['help_contains_auto_port']).lower()}`",
            f"- miniprogram-automator installed: `{str(report['automator']['installed']).lower()}`",
            f"- miniprogram-automator version: `{report['automator']['version']}`",
            f"- Launcher connects bare WS endpoint: `{str(report['automator']['launcher_connects_bare_ws']).lower()}`",
            "",
            "## Blockers",
            "",
        ]
    )
    if report["blockers"]:
        for blocker in report["blockers"]:
            lines.append(f"- `{blocker['code']}`: {blocker['notes']} Evidence: `{blocker['evidence']}`")
    else:
        lines.append("No protocol blocker was detected, but rendered coverage is still not marked proven without pass artifacts.")

    lines.extend(["", "## Findings", ""])
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- `{finding['code']}`")
    else:
        lines.append("No local hygiene findings remain in this audit.")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This audit is report-only. It did not launch DevTools, upload or submit a mini-program, deploy CloudRun, mutate DB/graph/vector data, write coordinates, call providers or LLMs, read secrets, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_miniprogram_devtools_rendered_coverage_audit.json"
    md_path = out_dir / "weekly_miniprogram_devtools_rendered_coverage_audit.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--miniapp-root", type=Path, default=DEFAULT_MINIAPP_ROOT)
    parser.add_argument("--cli-path", type=Path, default=DEFAULT_CLI_PATH)
    parser.add_argument("--frontend-cli-report", type=Path, default=DEFAULT_FRONTEND_CLI_REPORT)
    parser.add_argument("--protocol-report", type=Path, default=DEFAULT_PROTOCOL_REPORT)
    parser.add_argument("--environment-report", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = audit_rendered_coverage(
        miniapp_root=args.miniapp_root,
        cli_path=args.cli_path,
        frontend_cli_report=args.frontend_cli_report,
        protocol_report=args.protocol_report,
        environment_report=args.environment_report,
    )
    paths = write_reports(report, args.out_dir)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "rendered_coverage_proven": report["rendered_coverage_proven"],
                    "finding_count": report["finding_count"],
                    "blocking_count": report["blocking_count"],
                    "json": str(paths["json"]),
                    "markdown": str(paths["markdown"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
