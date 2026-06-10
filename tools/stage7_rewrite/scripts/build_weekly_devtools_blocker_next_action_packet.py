#!/usr/bin/env python3
"""Build a no-run next-action packet for rendered DevTools blockers.

This packet consolidates current rendered mini-program blocker evidence only.
It does not launch DevTools, run OpenClaw, deploy, upload, submit review, call
providers or LLMs, read secrets, write coordinates, mutate databases, or scan
broad disks.
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
DEFAULT_GOAL_BLOCKER_NEXT_ACTION = (
    REPORTS_ROOT
    / "weekly_goal_blocker_next_action_packet_s91_20260531"
    / "weekly_goal_blocker_next_action_packet.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_devtools_blocker_next_action_packet_20260603_frontend_hotfix"


def latest_report_json(prefix: str, filename: str, fallback: Path) -> Path:
    candidates = [
        path / filename
        for path in REPORTS_ROOT.glob(f"{prefix}*")
        if path.is_dir() and (path / filename).exists()
    ]
    if not candidates:
        return fallback
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, str(path)))


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [row for row in payload[key] if isinstance(row, dict)]
    return []


def blocker_codes(rendered_audit: dict[str, Any]) -> list[str]:
    return [str(blocker.get("code")) for blocker in rows(rendered_audit, "blockers") if blocker.get("code")]


def goal_devtools_task_types(goal_blocker_next_action: dict[str, Any]) -> list[str]:
    return [
        str(task.get("task_type"))
        for task in rows(goal_blocker_next_action, "next_action_tasks")
        if task.get("requirement_id") == "rendered_devtools_miniapp_coverage" and task.get("task_type")
    ]


def build_packet(
    *,
    rendered_audit: dict[str, Any],
    goal_blocker_next_action: dict[str, Any],
    rendered_audit_path: Path,
    goal_blocker_next_action_path: Path,
) -> dict[str, Any]:
    codes = blocker_codes(rendered_audit)
    environment = rendered_audit.get("environment") if isinstance(rendered_audit.get("environment"), dict) else {}
    tasks: list[dict[str, Any]] = []

    if "current_devtools_environment_dirty" in codes:
        tasks.append(
            {
                "task_id": "devtools_blocker:environment_reset_preflight",
                "task_type": "devtools_environment_reset_preflight",
                "requirement_id": "rendered_devtools_miniapp_coverage",
                "status": "blocked_pending_clean_devtools_environment",
                "process_count": environment.get("process_count"),
                "busy_target_ports": environment.get("busy_target_ports", []),
                "next_safe_actions": [
                    "collect a fresh environment audit after the local DevTools process/port state is clean",
                    "do not launch rendered attempts while clean_for_automator_launch is false",
                    "do not kill processes automatically from this report-only lane",
                ],
            }
        )

    if "current_devtools_automator_protocol_mismatch" in codes:
        tasks.append(
            {
                "task_id": "devtools_blocker:protocol_adapter_diagnosis",
                "task_type": "devtools_protocol_adapter_diagnosis",
                "requirement_id": "rendered_devtools_miniapp_coverage",
                "status": "blocked_pending_automator_protocol_fix",
                "current_artifact_pass_count": rendered_audit.get("current_artifact_pass_count"),
                "rendered_coverage_proven": rendered_audit.get("rendered_coverage_proven") is True,
                "next_safe_actions": [
                    "diagnose the current DevTools CLI long-connection protocol before claiming rendered coverage",
                    "keep websocket endpoint parsing dynamic and do not hard-code 9430 as the automator endpoint",
                    "keep static mini-program tests separate from rendered tap coverage",
                ],
            }
        )

    no_open_blockers = rendered_audit.get("rendered_coverage_proven") is True and not codes
    decision = (
        "weekly_devtools_blocker_next_action_packet_no_open_blockers_report_only"
        if no_open_blockers
        else "weekly_devtools_blocker_next_action_packet_blocked_report_only"
    )
    environment_task_count = sum(1 for task in tasks if task["task_type"] == "devtools_environment_reset_preflight")
    protocol_task_count = sum(1 for task in tasks if task["task_type"] == "devtools_protocol_adapter_diagnosis")
    return {
        "schema_version": "weekly_devtools_blocker_next_action_packet.v1",
        "generated_at": now_cst(),
        "decision": decision,
        "rendered_audit_decision": rendered_audit.get("decision"),
        "rendered_coverage_proven": rendered_audit.get("rendered_coverage_proven") is True,
        "current_artifact_pass_count": rendered_audit.get("current_artifact_pass_count"),
        "finding_count": rendered_audit.get("finding_count"),
        "blocker_count": len(codes),
        "blocker_codes": codes,
        "task_count": len(tasks),
        "environment_task_count": environment_task_count,
        "protocol_task_count": protocol_task_count,
        "goal_blocker_devtools_task_types": goal_devtools_task_types(goal_blocker_next_action),
        "inputs": {
            "rendered_audit": str(rendered_audit_path),
            "goal_blocker_next_action": str(goal_blocker_next_action_path),
        },
        "next_action_tasks": tasks,
        "safety": {
            "report_only": True,
            "devtools_launched": False,
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


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# Weekly DevTools Blocker Next Action Packet S92",
        "",
        f"Generated: `{packet['generated_at']}`",
        "",
        "## Decision",
        "",
        f"`{packet['decision']}`",
        "",
        "## Summary",
        "",
        f"- Rendered coverage proven: `{packet['rendered_coverage_proven']}`",
        f"- Rendered audit decision: `{packet['rendered_audit_decision']}`",
        f"- Current artifact pass count: `{packet['current_artifact_pass_count']}`",
        f"- Finding count: `{packet['finding_count']}`",
        f"- Blocker count: `{packet['blocker_count']}`",
        f"- Task count: `{packet['task_count']}`",
        f"- Environment tasks: `{packet['environment_task_count']}`",
        f"- Protocol tasks: `{packet['protocol_task_count']}`",
        f"- Blocker codes: `{','.join(packet['blocker_codes']) if packet['blocker_codes'] else '<none>'}`",
        "",
        "## Next Action Tasks",
        "",
    ]
    if not packet["next_action_tasks"]:
        lines.append("No DevTools rendered blockers remain.")
    else:
        for task in packet["next_action_tasks"]:
            lines.append(
                f"- `{task['task_id']}` `{task['task_type']}` `{task['status']}`"
            )

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No DevTools launch, OpenClaw/weekly pipeline run, map provider/geocode call, coordinate write, DB/graph/vector mutation, release rebuild, deploy/upload/review, LLM call, secret read, restart, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_devtools_blocker_next_action_packet.json"
    md_path = out_dir / "weekly_devtools_blocker_next_action_packet.md"
    tasks_path = out_dir / "weekly_devtools_blocker_next_action_tasks.jsonl"
    write_json(json_path, packet)
    md_path.write_text(render_markdown(packet), encoding="utf-8")
    tasks_path.write_text(
        "".join(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n" for task in packet["next_action_tasks"]),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rendered-audit", type=Path, default=None)
    parser.add_argument("--goal-blocker-next-action", type=Path, default=DEFAULT_GOAL_BLOCKER_NEXT_ACTION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    if args.rendered_audit is None:
        args.rendered_audit = latest_report_json(
            "weekly_miniprogram_devtools_rendered_coverage_",
            "weekly_miniprogram_devtools_rendered_coverage_audit.json",
            DEFAULT_RENDERED_AUDIT,
        )
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    packet = build_packet(
        rendered_audit=read_json(args.rendered_audit),
        goal_blocker_next_action=read_json(args.goal_blocker_next_action),
        rendered_audit_path=args.rendered_audit,
        goal_blocker_next_action_path=args.goal_blocker_next_action,
    )
    paths = write_reports(packet, args.out_dir)
    print(f"decision={packet['decision']}")
    print(f"blocker_count={packet['blocker_count']}")
    print(f"task_count={packet['task_count']}")
    print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
