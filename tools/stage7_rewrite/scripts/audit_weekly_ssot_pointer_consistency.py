#!/usr/bin/env python3
"""Audit current Atlas/HUAIDJ SSOT pointers for stale latest-artifact values.

Report-only. This script only reads manifest, PRD, docs, and existing report
artifacts. It does not run OpenClaw or weekly pipelines, call map providers or
LLMs, launch DevTools, deploy, upload, submit review, read secrets, write
coordinates, mutate databases, rebuild releases, restart services, or scan
broad disks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LONGRUN_ROOT = REPO_ROOT / "docs" / "longrun" / "atlas-route-external-db-20260531"
DEFAULT_MANIFEST = LONGRUN_ROOT / "manifest.md"
DEFAULT_PRD = LONGRUN_ROOT / "04-prd.json"
DEFAULT_CURRENT_RUNTIME = REPO_ROOT / "docs" / "current-runtime.md"
DEFAULT_DOCUMENTATION_INDEX = REPO_ROOT / "docs" / "DOCUMENTATION_INDEX.md"
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_ssot_pointer_consistency_audit_s116_20260601"
)

EXPECTED_POINTERS: dict[str, str] = {
    "latest_scorecard": (
        "reports/WEEKLY_ATLAS_RELATION_IDENTITY_SOURCE_REF_DISPOSITION_WORKBENCH_S116_20260601.md"
    ),
    "latest_relation_identity_source_ref_disposition_workbench": (
        "tools/stage7_rewrite/reports/atlas_relation_identity_source_ref_disposition_workbench_s116_20260601/"
        "atlas_relation_identity_source_ref_disposition_workbench.json"
    ),
    "latest_relation_identity_source_ref_disposition_workbench_rows": (
        "tools/stage7_rewrite/reports/atlas_relation_identity_source_ref_disposition_workbench_s116_20260601/"
        "atlas_relation_identity_source_ref_disposition_rows.jsonl"
    ),
    "latest_relation_identity_write_gate_starter": (
        "tools/stage7_rewrite/reports/atlas_relation_identity_write_gate_starter_s115_20260601/"
        "atlas_relation_identity_write_gate_starter_packet.json"
    ),
    "latest_relation_identity_write_gate_starter_tasks": (
        "tools/stage7_rewrite/reports/atlas_relation_identity_write_gate_starter_s115_20260601/"
        "atlas_relation_identity_write_gate_starter_tasks.jsonl"
    ),
    "latest_user_command_ledger_current_status": (
        "tools/stage7_rewrite/reports/weekly_user_command_ledger_current_status_s114_20260601/"
        "weekly_user_command_ledger_current_status.json"
    ),
    "latest_user_command_ledger_current_status_tasks": (
        "tools/stage7_rewrite/reports/weekly_user_command_ledger_current_status_s114_20260601/"
        "weekly_user_command_ledger_current_status_tasks.jsonl"
    ),
    "latest_coordinate_write_blocker_scorecard": (
        "reports/WEEKLY_COORDINATE_WRITE_BLOCKER_EVIDENCE_HARDENING_S109_20260601.md"
    ),
    "latest_coordinate_write_blocker_audit": (
        "tools/stage7_rewrite/reports/weekly_coordinate_write_blocker_audit_s109_20260601/"
        "weekly_coordinate_write_blocker_audit.json"
    ),
    "latest_coordinate_write_blocker_tasks": (
        "tools/stage7_rewrite/reports/weekly_coordinate_write_blocker_audit_s109_20260601/"
        "weekly_coordinate_write_blocker_tasks.jsonl"
    ),
    "latest_deploy_preflight_blocker_current_scorecard": (
        "reports/WEEKLY_DEPLOY_PREFLIGHT_BLOCKER_CURRENT_S112_20260601.md"
    ),
    "latest_deploy_preflight_blocker_next_action_packet": (
        "tools/stage7_rewrite/reports/weekly_deploy_preflight_blocker_next_action_packet_s112_20260601/"
        "weekly_deploy_preflight_blocker_next_action_packet.json"
    ),
    "latest_deploy_preflight_blocker_next_action_tasks": (
        "tools/stage7_rewrite/reports/weekly_deploy_preflight_blocker_next_action_packet_s112_20260601/"
        "weekly_deploy_preflight_blocker_next_action_tasks.jsonl"
    ),
    "latest_ssot_pointer_consistency_audit": (
        "tools/stage7_rewrite/reports/weekly_ssot_pointer_consistency_audit_s116_20260601/"
        "weekly_ssot_pointer_consistency_audit.json"
    ),
    "latest_ssot_pointer_consistency_tasks": (
        "tools/stage7_rewrite/reports/weekly_ssot_pointer_consistency_audit_s116_20260601/"
        "weekly_ssot_pointer_consistency_tasks.jsonl"
    ),
    "latest_relation_identity_write_blocker_scorecard": (
        "reports/WEEKLY_ATLAS_RELATION_IDENTITY_NEXT_ACTION_HARDENING_S111_20260601.md"
    ),
    "latest_relation_identity_write_blocker_audit": (
        "tools/stage7_rewrite/reports/atlas_relation_identity_write_blocker_audit_s111_20260601/"
        "atlas_relation_identity_write_blocker_audit.json"
    ),
    "latest_relation_identity_write_blocker_tasks": (
        "tools/stage7_rewrite/reports/atlas_relation_identity_write_blocker_audit_s111_20260601/"
        "atlas_relation_identity_write_blocker_tasks.jsonl"
    ),
    "latest_remaining_blocker_closure_current_scorecard": (
        "reports/WEEKLY_REMAINING_BLOCKER_CLOSURE_CURRENT_S113_20260601.md"
    ),
    "latest_remaining_blocker_closure_audit": (
        "tools/stage7_rewrite/reports/weekly_remaining_blocker_closure_audit_s113_20260601/"
        "weekly_remaining_blocker_closure_audit.json"
    ),
    "latest_remaining_blocker_closure_tasks": (
        "tools/stage7_rewrite/reports/weekly_remaining_blocker_closure_audit_s113_20260601/"
        "weekly_remaining_blocker_closure_tasks.jsonl"
    ),
    "latest_goal_completion_audit": (
        "tools/stage7_rewrite/reports/weekly_goal_completion_audit_s116_20260601/"
        "weekly_goal_completion_audit.json"
    ),
}

EXPECTED_DOC_TERMS = {
    "current_runtime": [
        "WEEKLY_ATLAS_RELATION_IDENTITY_EXIT_MATRIX_S102_20260601.md",
        "atlas_relation_identity_write_blocker_audit_s102_20260601",
        "weekly_remaining_blocker_closure_audit_s105_20260601",
        "weekly_goal_completion_audit_s110_20260601",
        "WEEKLY_DEPLOY_PREFLIGHT_BLOCKER_CURRENT_S106_20260601.md",
        "weekly_deploy_preflight_blocker_next_action_packet_s106_20260601",
        "WEEKLY_REMAINING_BLOCKER_CLOSURE_CURRENT_S107_20260601.md",
        "weekly_remaining_blocker_closure_audit_s107_20260601",
        "WEEKLY_GOAL_COMPLETION_CURRENT_S108_20260601.md",
        "WEEKLY_COORDINATE_WRITE_BLOCKER_EVIDENCE_HARDENING_S109_20260601.md",
        "weekly_coordinate_write_blocker_audit_s109_20260601",
        "WEEKLY_REMAINING_BLOCKER_CLOSURE_CURRENT_S110_20260601.md",
        "weekly_remaining_blocker_closure_audit_s110_20260601",
        "WEEKLY_ATLAS_RELATION_IDENTITY_NEXT_ACTION_HARDENING_S111_20260601.md",
        "atlas_relation_identity_write_blocker_audit_s111_20260601",
        "weekly_goal_completion_audit_s111_20260601",
        "WEEKLY_DEPLOY_PREFLIGHT_BLOCKER_CURRENT_S112_20260601.md",
        "weekly_deploy_preflight_blocker_next_action_packet_s112_20260601",
        "weekly_goal_completion_audit_s112_20260601",
        "WEEKLY_REMAINING_BLOCKER_CLOSURE_CURRENT_S113_20260601.md",
        "weekly_remaining_blocker_closure_audit_s113_20260601",
        "weekly_goal_completion_audit_s113_20260601",
        "WEEKLY_USER_COMMAND_LEDGER_CURRENT_STATUS_S114_20260601.md",
        "weekly_user_command_ledger_current_status_s114_20260601",
        "weekly_goal_completion_audit_s114_20260601",
        "weekly_ssot_pointer_consistency_audit_s114_20260601",
        "WEEKLY_ATLAS_RELATION_IDENTITY_WRITE_GATE_STARTER_S115_20260601.md",
        "atlas_relation_identity_write_gate_starter_s115_20260601",
        "weekly_goal_completion_audit_s115_20260601",
        "WEEKLY_ATLAS_RELATION_IDENTITY_SOURCE_REF_DISPOSITION_WORKBENCH_S116_20260601.md",
        "atlas_relation_identity_source_ref_disposition_workbench_s116_20260601",
        "weekly_goal_completion_audit_s116_20260601",
    ],
    "documentation_index": [
        "WEEKLY_ATLAS_RELATION_IDENTITY_EXIT_MATRIX_S102_20260601.md",
        "atlas_relation_identity_write_blocker_audit_s102_20260601",
        "weekly_remaining_blocker_closure_audit_s105_20260601",
        "weekly_goal_completion_audit_s110_20260601",
        "WEEKLY_DEPLOY_PREFLIGHT_BLOCKER_CURRENT_S106_20260601.md",
        "weekly_deploy_preflight_blocker_next_action_packet_s106_20260601",
        "WEEKLY_REMAINING_BLOCKER_CLOSURE_CURRENT_S107_20260601.md",
        "weekly_remaining_blocker_closure_audit_s107_20260601",
        "WEEKLY_GOAL_COMPLETION_CURRENT_S108_20260601.md",
        "WEEKLY_COORDINATE_WRITE_BLOCKER_EVIDENCE_HARDENING_S109_20260601.md",
        "weekly_coordinate_write_blocker_audit_s109_20260601",
        "WEEKLY_REMAINING_BLOCKER_CLOSURE_CURRENT_S110_20260601.md",
        "weekly_remaining_blocker_closure_audit_s110_20260601",
        "WEEKLY_ATLAS_RELATION_IDENTITY_NEXT_ACTION_HARDENING_S111_20260601.md",
        "atlas_relation_identity_write_blocker_audit_s111_20260601",
        "weekly_goal_completion_audit_s111_20260601",
        "WEEKLY_DEPLOY_PREFLIGHT_BLOCKER_CURRENT_S112_20260601.md",
        "weekly_deploy_preflight_blocker_next_action_packet_s112_20260601",
        "weekly_goal_completion_audit_s112_20260601",
        "WEEKLY_REMAINING_BLOCKER_CLOSURE_CURRENT_S113_20260601.md",
        "weekly_remaining_blocker_closure_audit_s113_20260601",
        "weekly_goal_completion_audit_s113_20260601",
        "WEEKLY_USER_COMMAND_LEDGER_CURRENT_STATUS_S114_20260601.md",
        "weekly_user_command_ledger_current_status_s114_20260601",
        "weekly_goal_completion_audit_s114_20260601",
        "weekly_ssot_pointer_consistency_audit_s114_20260601",
        "WEEKLY_ATLAS_RELATION_IDENTITY_WRITE_GATE_STARTER_S115_20260601.md",
        "atlas_relation_identity_write_gate_starter_s115_20260601",
        "weekly_goal_completion_audit_s115_20260601",
        "WEEKLY_ATLAS_RELATION_IDENTITY_SOURCE_REF_DISPOSITION_WORKBENCH_S116_20260601.md",
        "atlas_relation_identity_source_ref_disposition_workbench_s116_20260601",
        "weekly_goal_completion_audit_s116_20260601",
    ],
}

CURRENT_STORY_ID = "S116"
CURRENT_STORY_FILE_FRAGMENTS = [
    "WEEKLY_ATLAS_RELATION_IDENTITY_SOURCE_REF_DISPOSITION_WORKBENCH_S116_20260601.md",
    "atlas_relation_identity_source_ref_disposition_workbench_s116_20260601",
    "atlas_relation_identity_source_ref_disposition_rows.jsonl",
    "weekly_goal_completion_audit_s116_20260601",
]


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def normalize_ref(value: str) -> str:
    cleaned = value.strip().strip('"').strip("'")
    cleaned = cleaned.split(" #", 1)[0].strip()
    return cleaned.replace("\\", "/")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_manifest_pointer_occurrences(text: str) -> dict[str, list[dict[str, Any]]]:
    occurrences: dict[str, list[dict[str, Any]]] = {}
    pattern = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_]+):\s*(?P<value>.+?)\s*$")
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = pattern.match(line)
        if not match:
            continue
        key = match.group("key")
        value = match.group("value").strip()
        occurrences.setdefault(key, []).append(
            {
                "line": line_number,
                "raw_value": value,
                "normalized_value": normalize_ref(value),
            }
        )
    return occurrences


def expected_file_status(expected_ref: str) -> dict[str, Any]:
    path = REPO_ROOT / expected_ref
    return {
        "path": expected_ref,
        "exists": path.exists(),
    }


def audit_pointer(
    key: str,
    expected_ref: str,
    occurrences: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    key_occurrences = occurrences.get(key, [])
    expected_normalized = normalize_ref(expected_ref)
    stale_occurrences = [
        item for item in key_occurrences if item["normalized_value"] != expected_normalized
    ]
    normalized_values = sorted({item["normalized_value"] for item in key_occurrences})
    status = "clear"
    if not key_occurrences:
        status = "missing"
    elif stale_occurrences:
        status = "stale"
    file_status = expected_file_status(expected_ref)
    if not file_status["exists"] and status == "clear":
        status = "missing_artifact"
    return {
        "key": key,
        "status": status,
        "expected": expected_ref,
        "occurrence_count": len(key_occurrences),
        "stale_occurrence_count": len(stale_occurrences),
        "occurrences": key_occurrences,
        "normalized_values": normalized_values,
        "expected_file": file_status,
    }


def audit_docs(current_runtime_text: str, documentation_index_text: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    doc_map = {
        "current_runtime": current_runtime_text,
        "documentation_index": documentation_index_text,
    }
    for doc_id, terms in EXPECTED_DOC_TERMS.items():
        text = doc_map[doc_id]
        missing_terms = [term for term in terms if term not in text]
        checks.append(
            {
                "doc_id": doc_id,
                "status": "clear" if not missing_terms else "missing_terms",
                "missing_terms": missing_terms,
            }
        )
    return checks


def audit_prd(prd: dict[str, Any]) -> dict[str, Any]:
    stories = prd.get("stories")
    story_list = stories if isinstance(stories, list) else []
    story_ids = [story.get("id") for story in story_list if isinstance(story, dict)]
    s102_story = next(
        (story for story in story_list if isinstance(story, dict) and story.get("id") == "S102"),
        None,
    )
    s102_files = s102_story.get("files") if isinstance(s102_story, dict) else []
    s102_file_list = s102_files if isinstance(s102_files, list) else []
    required_file_fragments = [
        "WEEKLY_ATLAS_RELATION_IDENTITY_EXIT_MATRIX_S102_20260601.md",
        "atlas_relation_identity_write_blocker_audit_s102_20260601",
        "weekly_goal_completion_audit_s102_20260601",
    ]
    missing_file_fragments = [
        fragment
        for fragment in required_file_fragments
        if not any(fragment in str(item) for item in s102_file_list)
    ]
    current_story = next(
        (story for story in story_list if isinstance(story, dict) and story.get("id") == CURRENT_STORY_ID),
        None,
    )
    current_files = current_story.get("files") if isinstance(current_story, dict) else []
    current_file_list = current_files if isinstance(current_files, list) else []
    missing_current_file_fragments = [
        fragment
        for fragment in CURRENT_STORY_FILE_FRAGMENTS
        if not any(fragment in str(item) for item in current_file_list)
    ]
    current_story_clear = (
        prd.get("current_story_id") == CURRENT_STORY_ID
        and current_story is not None
        and not missing_current_file_fragments
        and (story_ids[-1] if story_ids else None) == CURRENT_STORY_ID
    )
    return {
        "status": (
            "clear"
            if s102_story and not missing_file_fragments and current_story_clear
            else "missing_or_stale_prd_reference"
        ),
        "current_story_id": prd.get("current_story_id"),
        "story_count": len(story_list),
        "has_s102_story": s102_story is not None,
        "missing_s102_file_fragments": missing_file_fragments,
        "expected_current_story_id": CURRENT_STORY_ID,
        "has_current_story": current_story is not None,
        "missing_current_file_fragments": missing_current_file_fragments,
        "latest_story_id": story_ids[-1] if story_ids else None,
    }


def build_audit(
    manifest_text: str,
    prd: dict[str, Any],
    current_runtime_text: str,
    documentation_index_text: str,
    manifest_path: Path,
    prd_path: Path,
    current_runtime_path: Path,
    documentation_index_path: Path,
) -> dict[str, Any]:
    occurrences = parse_manifest_pointer_occurrences(manifest_text)
    pointer_checks = [
        audit_pointer(key, expected_ref, occurrences)
        for key, expected_ref in EXPECTED_POINTERS.items()
    ]
    doc_checks = audit_docs(current_runtime_text, documentation_index_text)
    prd_check = audit_prd(prd)
    open_pointer_count = sum(1 for item in pointer_checks if item["status"] != "clear")
    open_doc_count = sum(1 for item in doc_checks if item["status"] != "clear")
    open_prd_count = 0 if prd_check["status"] == "clear" else 1
    finding_count = open_pointer_count + open_doc_count + open_prd_count
    decision = (
        "weekly_ssot_pointer_consistency_passed_report_only"
        if finding_count == 0
        else "weekly_ssot_pointer_consistency_blocked_report_only"
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "finding_count": finding_count,
        "open_pointer_count": open_pointer_count,
        "open_doc_count": open_doc_count,
        "open_prd_count": open_prd_count,
        "manifest_path": rel_path(manifest_path),
        "prd_path": rel_path(prd_path),
        "current_runtime_path": rel_path(current_runtime_path),
        "documentation_index_path": rel_path(documentation_index_path),
        "expected_pointers": EXPECTED_POINTERS,
        "pointer_checks": pointer_checks,
        "doc_checks": doc_checks,
        "prd_check": prd_check,
        "safety": {
            "report_only": True,
            "openclaw_pipeline_run": False,
            "weekly_pipeline_run": False,
            "provider_or_llm_call": False,
            "devtools_launched": False,
            "deploy_upload_review": False,
            "database_mutation": False,
            "coordinate_write": False,
            "secret_read": False,
            "release_rebuild": False,
            "service_restart": False,
            "broad_disk_scan": False,
        },
    }


def tasks_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for item in report["pointer_checks"]:
        if item["status"] == "clear":
            continue
        tasks.append(
            {
                "task_id": f"ssot:pointer:{item['key']}",
                "task_type": "manifest_latest_pointer_repair",
                "status": "blocked_pending_manifest_update",
                "key": item["key"],
                "expected": item["expected"],
                "current_values": item["normalized_values"],
                "stale_occurrence_count": item["stale_occurrence_count"],
            }
        )
    for item in report["doc_checks"]:
        if item["status"] == "clear":
            continue
        tasks.append(
            {
                "task_id": f"ssot:doc:{item['doc_id']}",
                "task_type": "doc_latest_reference_repair",
                "status": "blocked_pending_doc_update",
                "doc_id": item["doc_id"],
                "missing_terms": item["missing_terms"],
            }
        )
    if report["prd_check"]["status"] != "clear":
        tasks.append(
            {
                "task_id": f"ssot:prd:{CURRENT_STORY_ID.lower()}_current_reference",
                "task_type": "prd_latest_story_reference_repair",
                "status": "blocked_pending_prd_update",
                "missing_s102_file_fragments": report["prd_check"]["missing_s102_file_fragments"],
                "expected_current_story_id": report["prd_check"]["expected_current_story_id"],
                "missing_current_file_fragments": report["prd_check"]["missing_current_file_fragments"],
            }
        )
    return tasks


def write_markdown(path: Path, report: dict[str, Any], tasks: list[dict[str, Any]]) -> None:
    lines = [
        "# Weekly SSOT Pointer Consistency Audit",
        "",
        f"- Decision: `{report['decision']}`.",
        f"- Finding count: `{report['finding_count']}`.",
        f"- Open pointer count: `{report['open_pointer_count']}`.",
        f"- Open doc count: `{report['open_doc_count']}`.",
        f"- Open PRD count: `{report['open_prd_count']}`.",
        "",
        "## Pointer Checks",
        "",
    ]
    for item in report["pointer_checks"]:
        lines.append(
            f"- `{item['key']}`: `{item['status']}`, occurrences `{item['occurrence_count']}`, "
            f"stale `{item['stale_occurrence_count']}`, expected `{item['expected']}`."
        )
    lines.extend(["", "## Tasks", ""])
    if tasks:
        for task in tasks:
            lines.append(f"- `{task['task_id']}`: `{task['status']}`.")
    else:
        lines.append("- No open SSOT pointer tasks.")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No OpenClaw/weekly pipeline run, provider/geocode/LLM call, DevTools launch, "
            "deploy/upload/review, DB write, coordinate write, credential read, release rebuild, service restart, "
            "or broad disk scan occurred.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_tasks(path: Path, tasks: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n" for task in tasks),
        encoding="utf-8",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--prd", type=Path, default=DEFAULT_PRD)
    parser.add_argument("--current-runtime", type=Path, default=DEFAULT_CURRENT_RUNTIME)
    parser.add_argument("--documentation-index", type=Path, default=DEFAULT_DOCUMENTATION_INDEX)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_audit(
        manifest_text=read_text(args.manifest),
        prd=read_json(args.prd),
        current_runtime_text=read_text(args.current_runtime),
        documentation_index_text=read_text(args.documentation_index),
        manifest_path=args.manifest,
        prd_path=args.prd,
        current_runtime_path=args.current_runtime,
        documentation_index_path=args.documentation_index,
    )
    tasks = tasks_from_report(report)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "weekly_ssot_pointer_consistency_audit.json"
    markdown_path = args.out_dir / "weekly_ssot_pointer_consistency_audit.md"
    tasks_path = args.out_dir / "weekly_ssot_pointer_consistency_tasks.jsonl"
    write_json(json_path, report)
    write_markdown(markdown_path, report, tasks)
    write_tasks(tasks_path, tasks)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "finding_count": report["finding_count"],
                "json": str(json_path),
                "markdown": str(markdown_path),
                "tasks": str(tasks_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
