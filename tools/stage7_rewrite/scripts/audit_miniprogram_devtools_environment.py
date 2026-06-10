#!/usr/bin/env python3
"""Audit local WeChat DevTools process and port state for rendered tests.

Report-only. This does not launch DevTools, kill processes, deploy, upload,
read secrets, call providers, or mutate any application data.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = (
    REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_miniprogram_devtools_environment_s55_20260531"
)


def is_port_listening(port: int, host: str = "127.0.0.1", timeout_sec: float = 0.2) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_sec)
        return sock.connect_ex((host, int(port))) == 0


def run_powershell_json(command: str, timeout_sec: int = 20) -> Any:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
    )
    if completed.returncode != 0:
        return {"error": completed.stderr.strip()[:2000], "returncode": completed.returncode}
    text = completed.stdout.strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": text[:2000], "returncode": completed.returncode}


def collect_windows_state(target_ports: list[int]) -> dict[str, Any]:
    process_command = (
        "Get-Process | Where-Object { $_.ProcessName -match 'wechatdevtools|微信开发者工具' } | "
        "Select-Object ProcessName,Id,StartTime,Path | ConvertTo-Json -Compress"
    )
    port_list = ",".join(str(int(port)) for port in target_ports)
    port_command = (
        "$devIds = (Get-Process | Where-Object { $_.ProcessName -match 'wechatdevtools|微信开发者工具' }).Id; "
        f"Get-NetTCPConnection -State Listen | Where-Object {{ $_.LocalPort -in {port_list} -or $_.OwningProcess -in $devIds }} | "
        "Select-Object LocalAddress,LocalPort,OwningProcess,State | Sort-Object LocalPort | ConvertTo-Json -Compress"
    )
    return {
        "processes": normalize_json_list(run_powershell_json(process_command)),
        "listening_ports": normalize_json_list(run_powershell_json(port_command)),
    }


def normalize_json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and not value.get("error"):
        return [value]
    if isinstance(value, dict) and value.get("error"):
        return [{"probe_error": value.get("error"), "returncode": value.get("returncode")}]
    return []


def build_report(
    *,
    target_ports: list[int],
    process_rows: list[dict[str, Any]],
    port_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    busy_target_ports = sorted(
        {
            int(row.get("LocalPort"))
            for row in port_rows
            if str(row.get("LocalPort") or "").isdigit() and int(row.get("LocalPort")) in target_ports
        }
    )
    devtools_listener_ports = sorted(
        {
            int(row.get("LocalPort"))
            for row in port_rows
            if str(row.get("LocalPort") or "").isdigit()
        }
    )
    process_count = len([row for row in process_rows if row.get("Id")])
    findings: list[dict[str, Any]] = []
    if process_count:
        findings.append({"code": "wechat_devtools_processes_running", "count": process_count})
    if busy_target_ports:
        findings.append({"code": "target_ports_busy", "ports": busy_target_ports})
    if any(row.get("probe_error") for row in process_rows + port_rows):
        findings.append({"code": "probe_error", "count": sum(1 for row in process_rows + port_rows if row.get("probe_error"))})

    clean = not findings
    decision = (
        "weekly_miniprogram_devtools_environment_clean"
        if clean
        else "weekly_miniprogram_devtools_environment_dirty"
    )
    return {
        "schema_version": "weekly_miniprogram_devtools_environment_audit.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "clean_for_automator_launch": clean,
        "summary": {
            "process_count": process_count,
            "target_ports": target_ports,
            "busy_target_ports": busy_target_ports,
            "devtools_listener_ports": devtools_listener_ports,
            "finding_count": len(findings),
        },
        "processes": process_rows,
        "listening_ports": port_rows,
        "findings": findings,
        "next_rule": (
            "Do not start rendered automator attempts while this audit is dirty unless the attempt explicitly documents why existing DevTools state is acceptable."
            if not clean
            else "Clean local state is suitable for the next bounded rendered automator attempt."
        ),
        "boundary": {
            "report_only": True,
            "devtools_launched": False,
            "process_killed": False,
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


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Mini-Program DevTools Environment Audit",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        f"Decision: `{report['decision']}`",
        f"Clean for automator launch: `{str(report['clean_for_automator_launch']).lower()}`",
        "",
        "## Summary",
        "",
        f"- DevTools process count: `{summary['process_count']}`",
        f"- Target ports: `{', '.join(str(port) for port in summary['target_ports'])}`",
        f"- Busy target ports: `{', '.join(str(port) for port in summary['busy_target_ports']) or '<none>'}`",
        f"- DevTools listener ports: `{', '.join(str(port) for port in summary['devtools_listener_ports']) or '<none>'}`",
        f"- Findings: `{summary['finding_count']}`",
        "",
        "## Findings",
        "",
    ]
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- `{finding['code']}`: `{json.dumps(finding, ensure_ascii=False, sort_keys=True)}`")
    else:
        lines.append("No dirty local DevTools state detected.")
    lines.extend(
        [
            "",
            "## Rule",
            "",
            report["next_rule"],
            "",
            "## Boundary",
            "",
            "Report-only. It did not launch DevTools, kill processes, deploy, upload, submit review, mutate DB/graph/vector data, write coordinates, call providers or LLMs, read secrets, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_miniprogram_devtools_environment_audit.json"
    md_path = out_dir / "weekly_miniprogram_devtools_environment_audit.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--ports", default="9430,9431", help="Comma-separated target ports to inspect.")
    return parser.parse_args(argv)


def parse_ports(value: str) -> list[int]:
    ports: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        ports.append(int(part))
    return ports or [9430, 9431]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ports = parse_ports(args.ports)
    if sys.platform.startswith("win"):
        state = collect_windows_state(ports)
        process_rows = state["processes"]
        port_rows = state["listening_ports"]
    else:
        process_rows = []
        port_rows = [
            {"LocalAddress": "127.0.0.1", "LocalPort": port, "OwningProcess": None, "State": "Listen"}
            for port in ports
            if is_port_listening(port)
        ]
    report = build_report(target_ports=ports, process_rows=process_rows, port_rows=port_rows)
    paths = write_outputs(report, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "clean_for_automator_launch": report["clean_for_automator_launch"],
                "process_count": report["summary"]["process_count"],
                "busy_target_ports": report["summary"]["busy_target_ports"],
                "json": str(paths["json"]),
                "markdown": str(paths["markdown"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
