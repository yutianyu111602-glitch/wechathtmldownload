#!/usr/bin/env python3
"""Consolidate the remaining Atlas/HUAIDJ goal blockers into one closure matrix.

Report-only. This script only reads existing audit packets. It does not run
OpenClaw or weekly pipelines, call map providers or LLMs, launch DevTools,
deploy, upload, submit review, read secrets, write coordinates, mutate
databases, rebuild releases, restart services, or scan broad disks.
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
DEFAULT_GOAL_COMPLETION_AUDIT = (
    REPORTS_ROOT
    / "weekly_goal_completion_audit_s109_20260601"
    / "weekly_goal_completion_audit.json"
)
DEFAULT_DEPLOY_PREFLIGHT_BLOCKER = (
    REPORTS_ROOT
    / "weekly_deploy_preflight_blocker_next_action_packet_s106_20260601"
    / "weekly_deploy_preflight_blocker_next_action_packet.json"
)
DEFAULT_RELATION_IDENTITY_WRITE_BLOCKER = (
    REPORTS_ROOT
    / "atlas_relation_identity_write_blocker_audit_s102_20260601"
    / "atlas_relation_identity_write_blocker_audit.json"
)
DEFAULT_COORDINATE_WRITE_BLOCKER = (
    REPORTS_ROOT
    / "weekly_coordinate_write_blocker_audit_s109_20260601"
    / "weekly_coordinate_write_blocker_audit.json"
)
DEFAULT_DEVTOOLS_RENDERED_BLOCKER = (
    REPORTS_ROOT
    / "weekly_devtools_rendered_blocker_audit_s101_20260601"
    / "weekly_devtools_rendered_blocker_audit.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_remaining_blocker_closure_audit_s110_20260601"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def compact_task(task_id: str, requirement_id: str, task_type: str, status: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "requirement_id": requirement_id,
        "task_type": task_type,
        "status": status,
        "detail": detail,
    }


def build_deploy_tasks(deploy_blocker: dict[str, Any], relation_blocker: dict[str, Any]) -> list[dict[str, Any]]:
    failed_ids = [str(item) for item in list_value(deploy_blocker.get("failed_required_check_ids"))]
    relation_integrity = dict_value(relation_blocker.get("relation_integrity"))
    review_validations = dict_value(relation_blocker.get("review_validations"))
    tasks: list[dict[str, Any]] = []
    if "coordinate_freshness_latest_claim" in failed_ids:
        tasks.append(
            compact_task(
                "remaining:deploy:coordinate_freshness_latest_claim",
                "deploy_upload_local_preflight",
                "final_preflight_coordinate_latest_claim_gate",
                "blocked_pending_coordinate_write_gate",
                {
                    "check_id": "coordinate_freshness_latest_claim",
                    "required": True,
                    "safe_to_claim_all_latest": False,
                },
            )
        )
    if "atlas_relation_field_integrity" in failed_ids or int_value(relation_integrity.get("blocking_total_count")) > 0:
        tasks.append(
            compact_task(
                "remaining:deploy:atlas_relation_field_integrity",
                "deploy_upload_local_preflight",
                "final_preflight_relation_identity_write_gate",
                "blocked_pending_identity_disposition_write_gate",
                {
                    "check_id": "atlas_relation_field_integrity",
                    "required": True,
                    "relation_blocking_total_count": int_value(relation_integrity.get("blocking_total_count")),
                    "approved_for_write_gate_count": int_value(
                        review_validations.get("approved_for_write_gate_count")
                    ),
                    "write_gate_candidate_count": int_value(review_validations.get("write_gate_candidate_count")),
                },
            )
        )
    if int_value(deploy_blocker.get("optional_skipped_count")) > 0:
        tasks.append(
            compact_task(
                "remaining:deploy:miniapp_clean_ci_quality",
                "deploy_upload_local_preflight",
                "final_upload_clean_ci_explicit_key_gate",
                "skipped_until_explicit_private_key_path_at_final_upload_time",
                {
                    "check_id": "miniapp_clean_ci_quality",
                    "required": False,
                    "secret_read_allowed": False,
                },
            )
        )
    return tasks


def build_coordinate_tasks(coordinate_blocker: dict[str, Any]) -> list[dict[str, Any]]:
    coordinate_next_action = dict_value(coordinate_blocker.get("coordinate_next_action"))
    tasks: list[dict[str, Any]] = []
    if int_value(coordinate_next_action.get("rust_current_missing_geo_count")) > 0:
        tasks.append(
            compact_task(
                "remaining:coordinate:rust_club_provider_crosscheck",
                "address_coordinate_repair",
                "rust_club_provider_crosscheck",
                "blocked_pending_provider_acceptance",
                {
                    "venue_id": "rust_club_daqing",
                    "rust_current_missing_geo_count": int_value(
                        coordinate_next_action.get("rust_current_missing_geo_count")
                    ),
                    "provider_accepted_count": int_value(
                        coordinate_next_action.get("rust_user_address_provider_accepted_count")
                    ),
                    "provider_review_count": int_value(
                        coordinate_next_action.get("rust_user_address_provider_review_count")
                    ),
                    "coordinate_write_allowed": coordinate_next_action.get("coordinate_write_allowed") is True,
                },
            )
        )
    if int_value(coordinate_next_action.get("stale_registry_recheck_count")) > 0:
        tasks.append(
            compact_task(
                "remaining:coordinate:active_registry_latest_claim_recheck",
                "address_coordinate_repair",
                "stale_registry_latest_claim_recheck",
                "blocked_pending_external_recheck",
                {
                    "stale_registry_recheck_count": int_value(
                        coordinate_next_action.get("stale_registry_recheck_count")
                    ),
                    "map_api_calls_performed": coordinate_next_action.get("map_api_calls_performed") is True,
                },
            )
        )
    return tasks


def build_devtools_tasks(devtools_blocker: dict[str, Any]) -> list[dict[str, Any]]:
    environment = dict_value(devtools_blocker.get("environment_audit"))
    rendered = dict_value(devtools_blocker.get("rendered_audit"))
    devtools_next_action = dict_value(devtools_blocker.get("devtools_next_action"))
    tasks: list[dict[str, Any]] = []
    if int_value(devtools_next_action.get("environment_task_count")) > 0 or environment.get("clean_for_automator_launch") is False:
        tasks.append(
            compact_task(
                "remaining:devtools:environment_reset_preflight",
                "rendered_devtools_miniapp_coverage",
                "devtools_environment_reset_preflight",
                "blocked_pending_clean_devtools_environment",
                {
                    "clean_for_automator_launch": environment.get("clean_for_automator_launch") is True,
                    "process_count": int_value(environment.get("process_count")),
                    "busy_target_ports": list_value(environment.get("busy_target_ports")),
                },
            )
        )
    if int_value(devtools_next_action.get("protocol_task_count")) > 0 or rendered.get("rendered_coverage_proven") is False:
        tasks.append(
            compact_task(
                "remaining:devtools:protocol_adapter_diagnosis",
                "rendered_devtools_miniapp_coverage",
                "devtools_protocol_adapter_diagnosis",
                "blocked_pending_automator_protocol_fix",
                {
                    "rendered_coverage_proven": rendered.get("rendered_coverage_proven") is True,
                    "current_artifact_pass_count": int_value(rendered.get("current_artifact_pass_count")),
                    "blocker_codes": list_value(rendered.get("blocker_codes")),
                },
            )
        )
    return tasks


def requirement_summary(
    requirement_id: str,
    source_decision: str,
    blocking_signals: dict[str, Any],
    tasks: list[dict[str, Any]],
    blocked: bool,
) -> dict[str, Any]:
    hard_tasks = [task for task in tasks if task["detail"].get("required", True) is not False]
    return {
        "requirement_id": requirement_id,
        "status": "blocked_pending_exit_criteria" if blocked or hard_tasks else "closed_report_only",
        "source_decision": source_decision,
        "blocking_signals": blocking_signals,
        "exit_task_count": len(tasks),
        "hard_exit_task_count": len(hard_tasks),
        "exit_task_ids": [task["task_id"] for task in tasks],
    }


def build_audit(
    *,
    goal_completion: dict[str, Any],
    deploy_blocker: dict[str, Any],
    relation_blocker: dict[str, Any],
    coordinate_blocker: dict[str, Any],
    devtools_blocker: dict[str, Any],
    goal_completion_path: Path,
    deploy_blocker_path: Path,
    relation_blocker_path: Path,
    coordinate_blocker_path: Path,
    devtools_blocker_path: Path,
) -> dict[str, Any]:
    deploy_tasks = build_deploy_tasks(deploy_blocker, relation_blocker)
    coordinate_tasks = build_coordinate_tasks(coordinate_blocker)
    devtools_tasks = build_devtools_tasks(devtools_blocker)
    all_tasks = deploy_tasks + coordinate_tasks + devtools_tasks

    blocked_requirements = [
        str(item.get("id"))
        for item in list_value(goal_completion.get("blocking_requirements"))
        if isinstance(item, dict) and item.get("id")
    ]
    relation_integrity = dict_value(relation_blocker.get("relation_integrity"))
    relation_validations = dict_value(relation_blocker.get("review_validations"))
    coordinate_freshness = dict_value(coordinate_blocker.get("coordinate_freshness"))
    coordinate_next_action = dict_value(coordinate_blocker.get("coordinate_next_action"))
    devtools_rendered = dict_value(devtools_blocker.get("rendered_audit"))
    devtools_environment = dict_value(devtools_blocker.get("environment_audit"))
    deploy_blocked = (
        int_value(deploy_blocker.get("required_failed_count")) > 0
        or int_value(deploy_blocker.get("hard_blocking_task_count")) > 0
        or int_value(relation_integrity.get("blocking_total_count")) > 0
    )
    coordinate_blocked = (
        int_value(coordinate_blocker.get("blocking_reason_count")) > 0
        or coordinate_freshness.get("safe_to_claim_all_latest") is not True
        or int_value(coordinate_freshness.get("current_items_missing_geo")) > 0
        or int_value(coordinate_freshness.get("stale_registry_active_rows")) > 0
        or (
            int_value(coordinate_next_action.get("rust_current_missing_geo_count")) > 0
            and int_value(coordinate_next_action.get("rust_user_address_provider_accepted_count")) == 0
        )
    )
    devtools_blocked = (
        int_value(devtools_blocker.get("blocking_reason_count")) > 0
        or devtools_rendered.get("rendered_coverage_proven") is not True
        or devtools_environment.get("clean_for_automator_launch") is not True
    )

    closure_requirements = [
        requirement_summary(
            "deploy_upload_local_preflight",
            str(deploy_blocker.get("decision")),
            {
                "required_failed_count": int_value(deploy_blocker.get("required_failed_count")),
                "hard_blocking_task_count": int_value(deploy_blocker.get("hard_blocking_task_count")),
                "relation_blocking_total_count": int_value(relation_integrity.get("blocking_total_count")),
                "approved_for_write_gate_count": int_value(
                    relation_validations.get("approved_for_write_gate_count")
                ),
            },
            deploy_tasks,
            deploy_blocked,
        ),
        requirement_summary(
            "address_coordinate_repair",
            str(coordinate_blocker.get("decision")),
            {
                "blocking_reason_count": int_value(coordinate_blocker.get("blocking_reason_count")),
                "safe_to_claim_all_latest": coordinate_freshness.get("safe_to_claim_all_latest") is True,
                "current_items_missing_geo": int_value(coordinate_freshness.get("current_items_missing_geo")),
                "stale_registry_active_rows": int_value(coordinate_freshness.get("stale_registry_active_rows")),
                "provider_accepted_count": int_value(
                    coordinate_next_action.get("rust_user_address_provider_accepted_count")
                ),
            },
            coordinate_tasks,
            coordinate_blocked,
        ),
        requirement_summary(
            "rendered_devtools_miniapp_coverage",
            str(devtools_blocker.get("decision")),
            {
                "blocking_reason_count": int_value(devtools_blocker.get("blocking_reason_count")),
                "rendered_coverage_proven": devtools_rendered.get("rendered_coverage_proven") is True,
                "clean_for_automator_launch": devtools_environment.get("clean_for_automator_launch") is True,
                "current_artifact_pass_count": int_value(devtools_rendered.get("current_artifact_pass_count")),
            },
            devtools_tasks,
            devtools_blocked,
        ),
    ]
    open_requirements = [item for item in closure_requirements if item["status"] != "closed_report_only"]
    hard_exit_task_count = sum(int_value(item.get("hard_exit_task_count")) for item in closure_requirements)
    decision = (
        "weekly_remaining_blocker_closure_no_open_blockers_report_only"
        if not open_requirements
        else "weekly_remaining_blocker_closure_blocked_report_only"
    )
    return {
        "schema_version": "weekly_remaining_blocker_closure_audit.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat(),
        "decision": decision,
        "goal_completion": {
            "path": str(goal_completion_path),
            "decision": goal_completion.get("decision"),
            "completed_count": int_value(goal_completion.get("completed_count")),
            "incomplete_count": int_value(goal_completion.get("incomplete_count")),
            "blocking_requirement_ids": blocked_requirements,
        },
        "source_inputs": {
            "deploy_preflight_blocker": str(deploy_blocker_path),
            "relation_identity_write_blocker": str(relation_blocker_path),
            "coordinate_write_blocker": str(coordinate_blocker_path),
            "devtools_rendered_blocker": str(devtools_blocker_path),
        },
        "blocker_summary": {
            "open_top_level_blocker_count": len(open_requirements),
            "open_top_level_blocker_ids": [item["requirement_id"] for item in open_requirements],
            "exit_task_count": len(all_tasks),
            "hard_exit_task_count": hard_exit_task_count,
            "final_preflight_allowed": len(open_requirements) == 0,
            "deploy_upload_allowed": False,
            "coordinate_write_allowed": False,
            "devtools_launch_allowed": False,
        },
        "closure_requirements": closure_requirements,
        "next_action_tasks": all_tasks,
        "safety": {
            "report_only": True,
            "openclaw_pipeline_run": False,
            "weekly_pipeline_run": False,
            "provider_or_llm_call": False,
            "devtools_launched": False,
            "deploy_upload_review": False,
            "secret_read": False,
            "coordinate_write": False,
            "db_graph_vector_write": False,
            "release_rebuild": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["blocker_summary"]
    lines = [
        "# Weekly Remaining Blocker Closure Audit S110",
        "",
        f"- decision: `{report['decision']}`",
        f"- open_top_level_blocker_count: `{summary['open_top_level_blocker_count']}`",
        f"- open_top_level_blocker_ids: `{','.join(summary['open_top_level_blocker_ids']) if summary['open_top_level_blocker_ids'] else '<none>'}`",
        f"- exit_task_count: `{summary['exit_task_count']}`",
        f"- hard_exit_task_count: `{summary['hard_exit_task_count']}`",
        f"- final_preflight_allowed: `{summary['final_preflight_allowed']}`",
        "",
        "## Closure Requirements",
        "",
        "| Requirement | Status | Exit tasks | Hard exit tasks |",
        "| --- | --- | --- | --- |",
    ]
    for item in report["closure_requirements"]:
        lines.append(
            f"| `{item['requirement_id']}` | `{item['status']}` | `{item['exit_task_count']}` | `{item['hard_exit_task_count']}` |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No OpenClaw/weekly pipeline run, provider/geocode/LLM call, DevTools launch, deploy/upload/review, secret read, coordinate write, DB/graph/vector write, release rebuild, restart, or broad disk scan occurred.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_remaining_blocker_closure_audit.json"
    md_path = out_dir / "weekly_remaining_blocker_closure_audit.md"
    tasks_path = out_dir / "weekly_remaining_blocker_closure_tasks.jsonl"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    tasks_path.write_text(
        "".join(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n" for task in report["next_action_tasks"]),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal-completion", type=Path, default=DEFAULT_GOAL_COMPLETION_AUDIT)
    parser.add_argument("--deploy-preflight-blocker", type=Path, default=DEFAULT_DEPLOY_PREFLIGHT_BLOCKER)
    parser.add_argument("--relation-identity-write-blocker", type=Path, default=DEFAULT_RELATION_IDENTITY_WRITE_BLOCKER)
    parser.add_argument("--coordinate-write-blocker", type=Path, default=DEFAULT_COORDINATE_WRITE_BLOCKER)
    parser.add_argument("--devtools-rendered-blocker", type=Path, default=DEFAULT_DEVTOOLS_RENDERED_BLOCKER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = build_audit(
        goal_completion=read_json(args.goal_completion),
        deploy_blocker=read_json(args.deploy_preflight_blocker),
        relation_blocker=read_json(args.relation_identity_write_blocker),
        coordinate_blocker=read_json(args.coordinate_write_blocker),
        devtools_blocker=read_json(args.devtools_rendered_blocker),
        goal_completion_path=args.goal_completion,
        deploy_blocker_path=args.deploy_preflight_blocker,
        relation_blocker_path=args.relation_identity_write_blocker,
        coordinate_blocker_path=args.coordinate_write_blocker,
        devtools_blocker_path=args.devtools_rendered_blocker,
    )
    paths = write_reports(report, args.out_dir)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "open_top_level_blocker_count": report["blocker_summary"]["open_top_level_blocker_count"],
                    "exit_task_count": report["blocker_summary"]["exit_task_count"],
                    "hard_exit_task_count": report["blocker_summary"]["hard_exit_task_count"],
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
