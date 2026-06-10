#!/usr/bin/env python3
"""Audit the rendered DevTools blocker from existing no-run evidence.

Report-only. This script does not launch WeChat DevTools, run automator,
kill processes, deploy, upload, submit review, call providers or LLMs, read
secrets, write coordinates, mutate databases, or scan broad disks.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_RENDERED_AUDIT = (
    REPORTS_ROOT
    / "weekly_miniprogram_devtools_rendered_coverage_s34_20260531"
    / "weekly_miniprogram_devtools_rendered_coverage_audit.json"
)
DEFAULT_ENVIRONMENT_AUDIT = (
    REPORTS_ROOT
    / "weekly_miniprogram_devtools_environment_s55_20260531"
    / "weekly_miniprogram_devtools_environment_audit.json"
)
DEFAULT_DEVTOOLS_NEXT_ACTION = (
    REPORTS_ROOT
    / "weekly_devtools_blocker_next_action_packet_20260603_frontend_hotfix"
    / "weekly_devtools_blocker_next_action_packet.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_devtools_rendered_blocker_audit_s98_20260601"


def latest_report_json(prefix: str, filename: str, fallback: Path) -> Path:
    candidates = [
        path / filename
        for path in REPORTS_ROOT.glob(f"{prefix}*")
        if path.is_dir() and (path / filename).exists()
    ]
    if not candidates:
        return fallback
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, str(path)))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [row for row in payload[key] if isinstance(row, dict)]
    return []


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def blocker_codes(rendered_audit: dict[str, Any]) -> list[str]:
    return [str(row.get("code")) for row in rows(rendered_audit, "blockers") if row.get("code")]


def build_audit(
    *,
    rendered_audit: dict[str, Any],
    environment_audit: dict[str, Any],
    devtools_next_action: dict[str, Any],
    rendered_audit_path: Path,
    environment_audit_path: Path,
    devtools_next_action_path: Path,
) -> dict[str, Any]:
    rendered_codes = blocker_codes(rendered_audit)
    environment_summary = (
        environment_audit.get("summary", {})
        if isinstance(environment_audit.get("summary"), dict)
        else {}
    )
    environment_from_rendered = (
        rendered_audit.get("environment", {})
        if isinstance(rendered_audit.get("environment"), dict)
        else {}
    )
    clean_for_launch = environment_audit.get("clean_for_automator_launch") is True
    rendered_coverage_proven = rendered_audit.get("rendered_coverage_proven") is True
    current_artifact_pass_count = int_value(rendered_audit.get("current_artifact_pass_count"))
    process_count = int_value(
        environment_summary.get("process_count"),
        int_value(environment_from_rendered.get("process_count")),
    )
    busy_target_ports = environment_summary.get("busy_target_ports")
    if not isinstance(busy_target_ports, list):
        busy_target_ports = environment_from_rendered.get("busy_target_ports", [])
    devtools_listener_ports = environment_summary.get("devtools_listener_ports")
    if not isinstance(devtools_listener_ports, list):
        devtools_listener_ports = environment_from_rendered.get("devtools_listener_ports", [])

    blocking_reasons: list[str] = []
    if not rendered_coverage_proven:
        blocking_reasons.append("rendered_coverage_not_proven")
    if "current_devtools_environment_dirty" in rendered_codes or not clean_for_launch:
        blocking_reasons.append("current_devtools_environment_dirty")
    if "current_devtools_automator_protocol_mismatch" in rendered_codes:
        blocking_reasons.append("current_devtools_automator_protocol_mismatch")
    if int_value(devtools_next_action.get("task_count")) > 0:
        blocking_reasons.append("devtools_next_action_tasks_open")

    decision = (
        "weekly_devtools_rendered_blocker_no_open_blockers_report_only"
        if not blocking_reasons
        else "weekly_devtools_rendered_blocker_blocked_report_only"
    )
    next_action_tasks = rows(devtools_next_action, "next_action_tasks")
    return {
        "schema_version": "weekly_devtools_rendered_blocker_audit.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat(),
        "decision": decision,
        "blocking_reason_count": len(blocking_reasons),
        "blocking_reasons": blocking_reasons,
        "rendered_audit": {
            "path": str(rendered_audit_path),
            "decision": rendered_audit.get("decision"),
            "rendered_coverage_proven": rendered_coverage_proven,
            "current_artifact_pass_count": current_artifact_pass_count,
            "finding_count": int_value(rendered_audit.get("finding_count")),
            "blocking_count": int_value(rendered_audit.get("blocking_count")),
            "blocker_codes": rendered_codes,
        },
        "environment_audit": {
            "path": str(environment_audit_path),
            "decision": environment_audit.get("decision"),
            "clean_for_automator_launch": clean_for_launch,
            "process_count": process_count,
            "busy_target_ports": busy_target_ports,
            "devtools_listener_port_count": len(devtools_listener_ports),
        },
        "devtools_next_action": {
            "path": str(devtools_next_action_path),
            "decision": devtools_next_action.get("decision"),
            "blocker_count": int_value(devtools_next_action.get("blocker_count")),
            "task_count": int_value(devtools_next_action.get("task_count")),
            "environment_task_count": int_value(devtools_next_action.get("environment_task_count")),
            "protocol_task_count": int_value(devtools_next_action.get("protocol_task_count")),
            "rendered_coverage_proven": devtools_next_action.get("rendered_coverage_proven") is True,
        },
        "next_action_tasks": next_action_tasks,
        "safety": {
            "report_only": True,
            "devtools_launched": False,
            "automator_run": False,
            "process_killed": False,
            "openclaw_pipeline_run": False,
            "deploy_upload_review": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "coordinate_write": False,
            "db_graph_vector_write": False,
            "release_rebuild": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    rendered = report["rendered_audit"]
    environment = report["environment_audit"]
    next_action = report["devtools_next_action"]
    lines = [
        "# Weekly DevTools Rendered Blocker Audit S98",
        "",
        f"- decision: `{report['decision']}`",
        f"- blocking_reason_count: `{report['blocking_reason_count']}`",
        f"- blocking_reasons: `{','.join(report['blocking_reasons']) if report['blocking_reasons'] else '<none>'}`",
        f"- rendered_coverage_proven: `{rendered['rendered_coverage_proven']}`",
        f"- current_artifact_pass_count: `{rendered['current_artifact_pass_count']}`",
        f"- rendered_blocking_count: `{rendered['blocking_count']}`",
        f"- clean_for_automator_launch: `{environment['clean_for_automator_launch']}`",
        f"- process_count: `{environment['process_count']}`",
        f"- busy_target_ports: `{','.join(str(port) for port in environment['busy_target_ports']) if environment['busy_target_ports'] else '<none>'}`",
        f"- devtools_listener_port_count: `{environment['devtools_listener_port_count']}`",
        f"- next_action_task_count: `{next_action['task_count']}`",
        f"- environment_task_count: `{next_action['environment_task_count']}`",
        f"- protocol_task_count: `{next_action['protocol_task_count']}`",
        "",
        "## Boundary",
        "",
        "Report-only. No DevTools launch, automator run, process kill, deploy/upload/review, OpenClaw pipeline run, provider/geocode/LLM call, credential read, coordinate write, DB/graph/vector write, release rebuild, restart, or broad disk scan occurred.",
    ]
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_devtools_rendered_blocker_audit.json"
    md_path = out_dir / "weekly_devtools_rendered_blocker_audit.md"
    tasks_path = out_dir / "weekly_devtools_rendered_blocker_tasks.jsonl"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    tasks_path.write_text(
        "".join(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n" for task in report["next_action_tasks"]),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rendered-audit", type=Path, default=None)
    parser.add_argument("--environment-audit", type=Path, default=None)
    parser.add_argument("--devtools-next-action", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args(argv)
    if args.rendered_audit is None:
        args.rendered_audit = latest_report_json(
            "weekly_miniprogram_devtools_rendered_coverage_",
            "weekly_miniprogram_devtools_rendered_coverage_audit.json",
            DEFAULT_RENDERED_AUDIT,
        )
    if args.environment_audit is None:
        args.environment_audit = latest_report_json(
            "weekly_miniprogram_devtools_environment_",
            "weekly_miniprogram_devtools_environment_audit.json",
            DEFAULT_ENVIRONMENT_AUDIT,
        )
    if args.devtools_next_action is None:
        args.devtools_next_action = latest_report_json(
            "weekly_devtools_blocker_next_action_packet_",
            "weekly_devtools_blocker_next_action_packet.json",
            DEFAULT_DEVTOOLS_NEXT_ACTION,
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_audit(
        rendered_audit=read_json(args.rendered_audit),
        environment_audit=read_json(args.environment_audit),
        devtools_next_action=read_json(args.devtools_next_action),
        rendered_audit_path=args.rendered_audit,
        environment_audit_path=args.environment_audit,
        devtools_next_action_path=args.devtools_next_action,
    )
    paths = write_reports(report, args.out_dir)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "blocking_reason_count": report["blocking_reason_count"],
                    "rendered_coverage_proven": report["rendered_audit"]["rendered_coverage_proven"],
                    "clean_for_automator_launch": report["environment_audit"]["clean_for_automator_launch"],
                    "task_count": report["devtools_next_action"]["task_count"],
                    "json": str(paths["json"]),
                    "markdown": str(paths["markdown"]),
                    "tasks": str(paths["tasks"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
