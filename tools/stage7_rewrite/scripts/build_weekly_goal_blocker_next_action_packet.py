#!/usr/bin/env python3
"""Build a no-write next-action packet for the remaining weekly goal blockers.

This packet consolidates current blocker evidence only. It does not run
OpenClaw, map providers, DevTools, deployment, upload, LLM calls, or writes.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_GOAL_AUDIT = REPORTS_ROOT / "weekly_goal_completion_audit_s90_20260531" / "weekly_goal_completion_audit.json"
DEFAULT_PREFLIGHT = (
    REPORTS_ROOT
    / "weekly_deploy_upload_preflight_relation_identity_s61_blocked_20260531"
    / "weekly_deploy_upload_preflight.json"
)
DEFAULT_COORDINATE_NEXT_ACTION = (
    REPORTS_ROOT
    / "weekly_coordinate_repair_next_action_packet_s90_20260531"
    / "weekly_coordinate_repair_next_action_packet.json"
)
DEFAULT_RENDERED_AUDIT = (
    REPORTS_ROOT
    / "weekly_miniprogram_devtools_rendered_coverage_s67_20260531"
    / "weekly_miniprogram_devtools_rendered_coverage_audit.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_goal_blocker_next_action_packet_s91_20260531"


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


def first(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def blocked_ids(goal_audit: dict[str, Any]) -> list[str]:
    return [
        str(item.get("id"))
        for item in rows(goal_audit, "blocking_requirements")
        if item.get("id")
    ]


def preflight_failed_required_check_ids(preflight: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for check in rows(preflight, "checks"):
        if check.get("status") == "failed" and check.get("required", True) and check.get("check_id"):
            ids.append(str(check["check_id"]))
    return ids


def preflight_skipped_optional_check_ids(preflight: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for check in rows(preflight, "checks"):
        if check.get("status") == "skipped" and not check.get("required", True) and check.get("check_id"):
            ids.append(str(check["check_id"]))
    return ids


def rendered_blocker_codes(rendered_audit: dict[str, Any]) -> list[str]:
    return [str(blocker.get("code")) for blocker in rows(rendered_audit, "blockers") if blocker.get("code")]


def build_packet(
    *,
    goal_audit: dict[str, Any],
    preflight: dict[str, Any],
    coordinate_next_action: dict[str, Any],
    rendered_audit: dict[str, Any],
    goal_audit_path: Path,
    preflight_path: Path,
    coordinate_next_action_path: Path,
    rendered_audit_path: Path,
) -> dict[str, Any]:
    ids = blocked_ids(goal_audit)
    tasks: list[dict[str, Any]] = []

    if "deploy_upload_local_preflight" in ids:
        failed_required = preflight_failed_required_check_ids(preflight)
        tasks.append(
            {
                "task_id": "goal_blocker:deploy_upload_local_preflight:failed_required_checks",
                "task_type": "deploy_upload_failed_required_checks",
                "requirement_id": "deploy_upload_local_preflight",
                "status": "blocked_pending_required_gate_clearance",
                "failed_required_check_ids": failed_required,
                "skipped_optional_check_ids": preflight_skipped_optional_check_ids(preflight),
                "next_safe_actions": [
                    "clear coordinate_freshness_latest_claim through the coordinate next-action packet without guessed coordinates",
                    "clear atlas_relation_field_integrity through DB3 identity review/write-gate evidence before any database mutation",
                    "run Clean-CI only with an explicit private key path at final upload preflight time",
                ],
            }
        )

    if "address_coordinate_repair" in ids:
        for source_task in rows(coordinate_next_action, "next_action_tasks"):
            tasks.append(
                {
                    "task_id": f"goal_blocker:address_coordinate_repair:{first(source_task.get('task_id'), source_task.get('task_type'))}",
                    "task_type": "coordinate_repair_task",
                    "requirement_id": "address_coordinate_repair",
                    "status": first(source_task.get("status"), "blocked_pending_coordinate_evidence"),
                    "source_task_type": first(source_task.get("task_type")),
                    "source_task_id": first(source_task.get("task_id")),
                    "write_gate_ready": coordinate_next_action.get("write_gate_ready") is True,
                    "coordinate_write_allowed": coordinate_next_action.get("coordinate_write_allowed") is True,
                    "next_safe_actions": source_task.get("requirements_before_any_write")
                    or source_task.get("requirements_before_latest_claim")
                    or [],
                }
            )

    if "rendered_devtools_miniapp_coverage" in ids:
        codes = rendered_blocker_codes(rendered_audit)
        environment = rendered_audit.get("environment") if isinstance(rendered_audit.get("environment"), dict) else {}
        if "current_devtools_environment_dirty" in codes:
            tasks.append(
                {
                    "task_id": "goal_blocker:rendered_devtools_miniapp_coverage:environment_reset_preflight",
                    "task_type": "devtools_environment_reset_preflight",
                    "requirement_id": "rendered_devtools_miniapp_coverage",
                    "status": "blocked_pending_clean_devtools_environment",
                    "process_count": environment.get("process_count"),
                    "busy_target_ports": environment.get("busy_target_ports", []),
                    "next_safe_actions": [
                        "rerun the environment audit after DevTools processes and target ports are clean",
                        "do not launch rendered attempts while clean_for_automator_launch is false",
                    ],
                }
            )
        if "current_devtools_automator_protocol_mismatch" in codes:
            tasks.append(
                {
                    "task_id": "goal_blocker:rendered_devtools_miniapp_coverage:protocol_adapter_diagnosis",
                    "task_type": "devtools_protocol_adapter_diagnosis",
                    "requirement_id": "rendered_devtools_miniapp_coverage",
                    "status": "blocked_pending_automator_protocol_fix",
                    "current_artifact_pass_count": rendered_audit.get("current_artifact_pass_count"),
                    "rendered_coverage_proven": rendered_audit.get("rendered_coverage_proven") is True,
                    "next_safe_actions": [
                        "diagnose the current CLI long-connection protocol before claiming rendered coverage",
                        "keep static mini-program tests separate from rendered tap coverage",
                    ],
                }
            )

    no_open_blockers = not ids and goal_audit.get("completion_proven") is True
    decision = (
        "weekly_goal_blocker_next_action_packet_no_open_blockers_report_only"
        if no_open_blockers
        else "weekly_goal_blocker_next_action_packet_blocked_report_only"
    )
    return {
        "schema_version": "weekly_goal_blocker_next_action_packet.v1",
        "generated_at": now_cst(),
        "decision": decision,
        "completion_proven": goal_audit.get("completion_proven") is True,
        "goal_audit_decision": goal_audit.get("decision"),
        "completed_count": int_value(goal_audit.get("completed_count")),
        "incomplete_count": int_value(goal_audit.get("incomplete_count"), len(ids)),
        "blocker_count": len(ids),
        "blocked_requirement_ids": ids,
        "task_count": len(tasks),
        "inputs": {
            "goal_audit": str(goal_audit_path),
            "preflight": str(preflight_path),
            "coordinate_next_action": str(coordinate_next_action_path),
            "rendered_audit": str(rendered_audit_path),
        },
        "source_summaries": {
            "preflight_decision": preflight.get("decision"),
            "preflight_failed_required_check_ids": preflight_failed_required_check_ids(preflight),
            "coordinate_next_action_decision": coordinate_next_action.get("decision"),
            "coordinate_blocking_task_count": coordinate_next_action.get("blocking_task_count"),
            "rendered_audit_decision": rendered_audit.get("decision"),
            "rendered_blocker_codes": rendered_blocker_codes(rendered_audit),
        },
        "next_action_tasks": tasks,
        "safety": {
            "report_only": True,
            "openclaw_pipeline_run": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "coordinate_write": False,
            "db_graph_vector_write": False,
            "deploy_upload_review": False,
            "devtools_launched": False,
            "release_rebuild": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# Weekly Goal Blocker Next Action Packet S91",
        "",
        f"Generated: `{packet['generated_at']}`",
        "",
        "## Decision",
        "",
        f"`{packet['decision']}`",
        "",
        "## Summary",
        "",
        f"- Completion proven: `{packet['completion_proven']}`",
        f"- Goal audit decision: `{packet['goal_audit_decision']}`",
        f"- Completed requirements: `{packet['completed_count']}`",
        f"- Incomplete requirements: `{packet['incomplete_count']}`",
        f"- Blocker count: `{packet['blocker_count']}`",
        f"- Task count: `{packet['task_count']}`",
        f"- Blocked requirements: `{','.join(packet['blocked_requirement_ids']) if packet['blocked_requirement_ids'] else '<none>'}`",
        "",
        "## Next Action Tasks",
        "",
    ]
    if packet["next_action_tasks"]:
        for task in packet["next_action_tasks"]:
            lines.append(
                f"- `{task['task_id']}` `{task['task_type']}` `{task['requirement_id']}` `{task['status']}`"
            )
    else:
        lines.append("- `<none>`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No OpenClaw/weekly pipeline run, map provider/geocode call, DevTools launch, coordinate write, DB/graph/vector mutation, release rebuild, deploy/upload/review, LLM call, secret read, restart, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_goal_blocker_next_action_packet.json"
    md_path = out_dir / "weekly_goal_blocker_next_action_packet.md"
    tasks_path = out_dir / "weekly_goal_blocker_next_action_tasks.jsonl"
    write_json(json_path, packet)
    md_path.write_text(render_markdown(packet), encoding="utf-8")
    tasks_path.write_text(
        "".join(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n" for task in packet["next_action_tasks"]),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal-audit", type=Path, default=DEFAULT_GOAL_AUDIT)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--coordinate-next-action", type=Path, default=DEFAULT_COORDINATE_NEXT_ACTION)
    parser.add_argument("--rendered-audit", type=Path, default=DEFAULT_RENDERED_AUDIT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(
        goal_audit=read_json(args.goal_audit),
        preflight=read_json(args.preflight),
        coordinate_next_action=read_json(args.coordinate_next_action),
        rendered_audit=read_json(args.rendered_audit),
        goal_audit_path=args.goal_audit,
        preflight_path=args.preflight,
        coordinate_next_action_path=args.coordinate_next_action,
        rendered_audit_path=args.rendered_audit,
    )
    paths = write_reports(packet, args.out_dir)
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        print(f"decision={packet['decision']}")
        print(f"blocker_count={packet['blocker_count']}")
        print(f"task_count={packet['task_count']}")
        print(f"blocked_requirement_ids={','.join(packet['blocked_requirement_ids']) if packet['blocked_requirement_ids'] else '<none>'}")
        print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
