#!/usr/bin/env python3
"""Build S126 rendered DevTools blocker closure workbench.

Report-only. It does not launch DevTools, run automator, kill processes,
deploy/upload, read secrets, or mutate application data.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
SCHEMA_VERSION = "miniprogram_devtools_rendered_blocker_closure_s126.v1"
DEFAULT_PREFLIGHT = REPORTS_ROOT / "weekly_miniprogram_devtools_run_preflight_s126_20260601" / "weekly_miniprogram_devtools_rendered_run_preflight.json"
DEFAULT_ENVIRONMENT = REPORTS_ROOT / "weekly_miniprogram_devtools_environment_s126_current_20260601" / "weekly_miniprogram_devtools_environment_audit.json"
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_miniprogram_devtools_blocker_closure_s126_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_MINIPROGRAM_DEVTOOLS_RENDERED_BLOCKER_CLOSURE_S126_20260601.md"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def environment_summary(environment: dict[str, Any]) -> dict[str, Any]:
    summary = environment.get("summary") if isinstance(environment.get("summary"), dict) else {}
    processes = environment.get("processes") if isinstance(environment.get("processes"), list) else []
    ports = environment.get("listening_ports") if isinstance(environment.get("listening_ports"), list) else []
    owners = Counter(str(port.get("OwningProcess") or "") for port in ports if port.get("OwningProcess"))
    return {
        "decision": environment.get("decision", ""),
        "clean_for_automator_launch": environment.get("clean_for_automator_launch") is True,
        "process_count": int(summary.get("process_count") or 0),
        "busy_target_ports": summary.get("busy_target_ports", []),
        "devtools_listener_ports": summary.get("devtools_listener_ports", []),
        "process_ids": [row.get("Id") for row in processes if row.get("Id")],
        "listener_owner_counts": dict(owners),
    }


def build_tasks(preflight: dict[str, Any], environment: dict[str, Any]) -> list[dict[str, Any]]:
    env = environment_summary(environment)
    preflight_summary = preflight.get("summary") if isinstance(preflight.get("summary"), dict) else {}
    tasks: list[dict[str, Any]] = []

    tasks.append(
        {
            "task_id": "s126:environment_clean_readback",
            "task_type": "devtools_environment_clean_readback",
            "status": "blocked_pending_clean_environment" if not env["clean_for_automator_launch"] else "ready",
            "required_evidence": [
                "fresh audit_miniprogram_devtools_environment.py report",
                "clean_for_automator_launch=true",
                "process_count=0",
                "busy_target_ports=[] for 9430,9431",
            ],
            "current_evidence": env,
            "allowed_actions_by_this_packet": ["read_current_process_and_port_state", "write_report_artifacts"],
            "forbidden_actions_by_this_packet": ["kill_process", "restart_devtools", "launch_devtools", "upload_or_review"],
            "operator_approval_required_for": ["closing existing WeChat DevTools GUI/processes", "killing any PID", "changing DevTools global config"],
        }
    )

    tasks.append(
        {
            "task_id": "s126:protocol_adapter_proof",
            "task_type": "devtools_protocol_adapter_proof",
            "status": "blocked_pending_protocol_pass" if int(preflight_summary.get("protocol_blocker_count") or 0) else "ready",
            "required_evidence": [
                "single-attempt wrapper parses dynamic DevTools endpoint",
                "no fixed MINIPROGRAM_AUTOMATOR_WS or hard-coded 9430 endpoint",
                "miniprogram-automator command protocol completes for loading, haptics, and extreme scripts",
            ],
            "current_evidence": {
                "protocol_blocker_count": preflight_summary.get("protocol_blocker_count"),
                "ready_to_attempt_launch_mode": preflight_summary.get("ready_to_attempt_launch_mode"),
                "rendered_coverage_proven": preflight_summary.get("rendered_coverage_proven"),
            },
            "allowed_actions_by_this_packet": ["inspect_scripts", "write_report_artifacts", "run_unit_tests"],
            "forbidden_actions_by_this_packet": ["launch_devtools", "force_ws_endpoint", "claim_static_tests_as_rendered_coverage"],
        }
    )

    tasks.append(
        {
            "task_id": "s126:rendered_artifact_gate",
            "task_type": "rendered_pass_artifact_gate",
            "status": "blocked_pending_environment_and_protocol",
            "required_evidence": [
                "fresh report.json for devtools-loading-fallback.cjs",
                "fresh report.json for devtools-haptics.cjs",
                "fresh report.json for devtools-extreme.cjs",
                "all reports pass their pass_contract and rendered_coverage_proven=true",
            ],
            "current_evidence": {
                "step_count": preflight_summary.get("step_count"),
                "run_order": [row.get("script") for row in preflight.get("run_order", []) if isinstance(row, dict)],
            },
            "allowed_actions_by_this_packet": ["prepare_run_order", "verify_artifact_paths"],
            "forbidden_actions_by_this_packet": ["upload_or_review", "deploy", "public_release_pointer_mutation"],
        }
    )
    return tasks


def build_workbench(preflight_path: Path, environment_path: Path, out_dir: Path, scorecard_path: Path) -> dict[str, Any]:
    preflight = read_json(preflight_path)
    environment = read_json(environment_path)
    tasks = build_tasks(preflight, environment)
    blocked = [task for task in tasks if str(task.get("status", "")).startswith("blocked")]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "miniprogram_devtools_rendered_blocker_closure_blocked_report_only" if blocked else "miniprogram_devtools_rendered_blocker_closure_ready_report_only",
        "inputs": {
            "preflight": rel_path(preflight_path),
            "environment": rel_path(environment_path),
        },
        "outputs": {
            "report": rel_path(out_dir / "miniprogram_devtools_rendered_blocker_closure.json"),
            "tasks": rel_path(out_dir / "miniprogram_devtools_rendered_blocker_closure_tasks.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "summary": {
            "task_count": len(tasks),
            "blocked_task_count": len(blocked),
            "environment_clean": environment_summary(environment)["clean_for_automator_launch"],
            "ready_to_attempt_launch_mode": bool(preflight.get("summary", {}).get("ready_to_attempt_launch_mode")),
            "rendered_coverage_proven": bool(preflight.get("summary", {}).get("rendered_coverage_proven")),
        },
        "tasks": tasks,
        "boundary": {
            "report_only": True,
            "devtools_launched": False,
            "automator_run": False,
            "process_killed": False,
            "upload_executed": False,
            "review_submitted": False,
            "cloudrun_deployed": False,
            "db_graph_vector_write": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
        "next_story": "S126",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "miniprogram_devtools_rendered_blocker_closure.json", report)
    atomic_write_jsonl(out_dir / "miniprogram_devtools_rendered_blocker_closure_tasks.jsonl", tasks)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Mini-Program DevTools Rendered Blocker Closure S126",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Task count: `{summary['task_count']}`",
        f"- Blocked task count: `{summary['blocked_task_count']}`",
        f"- Environment clean: `{summary['environment_clean']}`",
        f"- Ready to attempt launch mode: `{summary['ready_to_attempt_launch_mode']}`",
        f"- Rendered coverage proven: `{summary['rendered_coverage_proven']}`",
        "",
        "## Tasks",
        "",
    ]
    for task in report["tasks"]:
        lines.append(f"- `{task['task_id']}`: `{task['status']}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No DevTools launch, automator run, process kill, upload/review/deploy, DB/graph/vector write, provider/LLM call, secret read, or broad disk scan occurred.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT)
    parser.add_argument("--environment", type=Path, default=DEFAULT_ENVIRONMENT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_workbench(args.preflight, args.environment, args.out_dir, args.scorecard)
    print(json.dumps({"decision": report["decision"], "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
