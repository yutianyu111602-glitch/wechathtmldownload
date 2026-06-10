#!/usr/bin/env python3
"""Build a report-only gate for weekly remote-effective proof collection."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_upload_effective_data_proof_gate.v1"
DECISION = "weekly_upload_effective_data_proof_gate_ready_report_only_waiting_explicit_execution"
SOURCE_DECISION = "weekly_remote_effective_upload_cache_drift_gate_ready_report_only_local_green_remote_unproven"

DEFAULT_SOURCE_GATE = (
    REPORTS_ROOT
    / "weekly_remote_effective_upload_cache_drift_gate_20260603"
    / "weekly_remote_effective_upload_cache_drift_gate.json"
)
DEFAULT_SOURCE_ROWS = (
    REPORTS_ROOT
    / "weekly_remote_effective_upload_cache_drift_gate_20260603"
    / "weekly_remote_effective_required_proof_rows.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_upload_effective_data_proof_gate_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_UPLOAD_EFFECTIVE_DATA_PROOF_GATE_20260603.md"

EXPECTED_PROOF_IDS = [
    "remote_effective:miniprogram_render_after_storage_clear",
    "remote_effective:cloudrun_current_endpoint",
    "remote_effective:cloudbase_database_current",
    "remote_effective:miniprogram_uploaded_version",
    "remote_effective:poster_image_fetch",
]

PROOF_STEP_CONTRACTS: dict[str, dict[str, Any]] = {
    "remote_effective:miniprogram_render_after_storage_clear": {
        "lane": "miniprogram_render",
        "command_family": "WeChat DevTools/miniprogram-automator rendered proof in a test session",
        "required_output": "Rendered current package after storage clear: 78 items, 2026-06-02/2026-06-03 present, 2026-05-29 absent, no snapshot/cache notice, poster image load >= 1, image error count = 0.",
        "allowed_future_actions": [
            "clear_miniprogram_storage_in_test_session",
            "navigate_pages_index_index",
            "read_rendered_test_artifact",
        ],
    },
    "remote_effective:cloudrun_current_endpoint": {
        "lane": "cloudrun_read_only",
        "command_family": "HTTP GET against the public weekly current endpoint",
        "required_output": "Public current endpoint returns package identity matching the local current release: total 78, 2026-06-02 window start, no 2026-05-29 rows, poster fields present.",
        "allowed_future_actions": [
            "read_public_current_endpoint",
            "record_response_hash_and_count",
        ],
    },
    "remote_effective:cloudbase_database_current": {
        "lane": "cloudbase_read_only",
        "command_family": "CloudBase read-only DB/current or health-check proof without token output",
        "required_output": "CloudBase current hot path returns 78 current rows with matching package identity and poster field coverage; no credentials or token values printed.",
        "allowed_future_actions": [
            "read_cloudbase_current_status",
            "read_health_check_counts",
            "record_redacted_artifact",
        ],
    },
    "remote_effective:miniprogram_uploaded_version": {
        "lane": "upload_metadata",
        "command_family": "Upload/version metadata proof after a separate explicit upload-only gate",
        "required_output": "Uploaded development or experience version metadata is bound to the current package identity; formal review and public release remain false.",
        "allowed_future_actions": [
            "read_current_uploaded_version_metadata",
            "after_explicit_upload_only_gate_record_upload_result",
        ],
    },
    "remote_effective:poster_image_fetch": {
        "lane": "poster_fetch_read_only",
        "command_family": "HTTP image fetch or DevTools image load counter proof",
        "required_output": "At least one remote-effective poster image URL fetch succeeds and rendered image error count remains 0.",
        "allowed_future_actions": [
            "read_current_poster_url",
            "fetch_one_or_more_poster_images",
            "record_status_code_or_image_load_counter",
        ],
    },
}

FORBIDDEN_ACTIONS = [
    "cloudrun_deploy",
    "cloudbase_sync_or_write",
    "database_or_coordinate_write",
    "package_rebuild",
    "miniprogram_upload_without_explicit_upload_only_gate",
    "wechat_review_submit",
    "public_release",
    "credential_or_secret_print",
    "provider_or_model_call",
    "docker_worker_runtime",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def build_proof_steps(source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_id = {str(row.get("proof_id", "")): row for row in source_rows}
    steps: list[dict[str, Any]] = []
    for index, proof_id in enumerate(EXPECTED_PROOF_IDS, start=1):
        source_row = rows_by_id.get(proof_id, {})
        contract = PROOF_STEP_CONTRACTS[proof_id]
        steps.append(
            {
                "schema_version": SCHEMA_VERSION,
                "step_id": f"upload_effective_proof:{index:02d}",
                "proof_id": proof_id,
                "lane": contract["lane"],
                "source_status": source_row.get("status", "missing_source_row"),
                "status": "waiting_explicit_execution_gate",
                "command_family": contract["command_family"],
                "required_output": contract["required_output"],
                "allowed_future_actions": contract["allowed_future_actions"],
                "forbidden_actions": FORBIDDEN_ACTIONS,
                "evidence_artifact_required": True,
                "evidence_artifact": "",
                "proof_executed_by_this_gate": False,
                "upload_allowed_by_this_step": False,
                "review_release_allowed_by_this_step": False,
            }
        )
    return steps


def build_report(repo_root: Path, source_gate_path: Path, source_rows_path: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    source_gate_path = source_gate_path if source_gate_path.is_absolute() else repo_root / source_gate_path
    source_rows_path = source_rows_path if source_rows_path.is_absolute() else repo_root / source_rows_path
    source_gate = read_json(source_gate_path)
    source_rows = read_jsonl(source_rows_path)
    summary = source_gate.get("summary", {})
    proof_steps = build_proof_steps(source_rows)
    expected_rows_present = sorted(str(row.get("proof_id", "")) for row in source_rows) == sorted(EXPECTED_PROOF_IDS)
    source_gate_ready = bool(
        source_gate.get("decision") == SOURCE_DECISION
        and summary.get("local_current_package_green") is True
        and summary.get("remote_effective_required_proof_count") == len(EXPECTED_PROOF_IDS)
        and summary.get("remote_effective_proven_count") == 0
        and summary.get("remote_effective_unproven_count") == len(EXPECTED_PROOF_IDS)
        and summary.get("upload_allowed_now") is False
        and summary.get("review_release_allowed_now") is False
        and expected_rows_present
    )
    blockers: list[dict[str, Any]] = []
    if not source_gate_ready:
        blockers.append(
            {
                "schema_version": SCHEMA_VERSION,
                "blocker_id": "source_remote_effective_gate_not_ready_or_inconsistent",
                "status": "blocking",
                "details": "The source remote-effective drift gate must be local-green, five-proof unproven, and fail-closed before this proof gate can be used.",
            }
        )
    for step in proof_steps:
        blockers.append(
            {
                "schema_version": SCHEMA_VERSION,
                "blocker_id": f"explicit_execution_gate_missing:{step['proof_id']}",
                "proof_id": step["proof_id"],
                "status": "blocking",
                "details": "This proof has a collection contract but no explicit controller execution gate or evidence artifact yet.",
            }
        )
    report_summary = {
        "source_gate_ready_for_proof_gate": source_gate_ready,
        "local_current_package_green": bool(summary.get("local_current_package_green") is True),
        "local_current_item_count": int(summary.get("local_current_item_count", 0) or 0),
        "local_poster_cover_field_count": int(summary.get("local_poster_cover_field_count", 0) or 0),
        "local_contains_2026_05_29": bool(summary.get("local_contains_2026_05_29") is True),
        "required_proof_step_count": len(proof_steps),
        "proof_steps_waiting_explicit_gate_count": len(proof_steps),
        "proof_steps_proven_count": 0,
        "blocking_condition_count": len(blockers),
        "upload_only_gate_present": False,
        "proof_execution_allowed_now": False,
        "upload_only_execution_allowed_now": False,
        "miniprogram_upload_allowed_now": False,
        "cloudrun_deploy_allowed_now": False,
        "cloudbase_sync_allowed_now": False,
        "database_write_allowed_now": False,
        "coordinate_write_allowed_now": False,
        "review_release_allowed_now": False,
        "release_ready": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": DECISION,
        "mode": "report_only_no_execution_no_upload_no_credentials",
        "objective": "Turn the five remote-effective proof gaps into an explicit execution contract without performing the proof collection or upload.",
        "source_gate": display_path(source_gate_path, repo_root),
        "source_rows": display_path(source_rows_path, repo_root),
        "proof_steps": proof_steps,
        "blockers": blockers,
        "summary": report_summary,
        "boundary": {
            "network_probe_executed": False,
            "devtools_or_phone_render_executed": False,
            "cloudrun_deployed": False,
            "cloudbase_sync_executed": False,
            "database_mutations": False,
            "coordinate_writes": False,
            "package_rebuild_executed": False,
            "miniprogram_upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "credential_or_secret_read": False,
            "browser_profile_read": False,
            "docker_or_worker_started": False,
            "provider_or_model_call": False,
        },
        "next_required_gate": "explicit_controller_upload_effective_data_proof_execution_gate",
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Weekly Upload/Effective-Data Proof Gate",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- source gate ready: `{summary['source_gate_ready_for_proof_gate']}`",
        f"- local current package green: `{summary['local_current_package_green']}`",
        f"- local item count: `{summary['local_current_item_count']}`",
        f"- local poster/cover field count: `{summary['local_poster_cover_field_count']}`",
        f"- required proof steps: `{summary['required_proof_step_count']}`",
        f"- proof steps proven: `{summary['proof_steps_proven_count']}`",
        f"- proof execution allowed now: `{summary['proof_execution_allowed_now']}`",
        f"- upload-only execution allowed now: `{summary['upload_only_execution_allowed_now']}`",
        f"- review/release allowed now: `{summary['review_release_allowed_now']}`",
        f"- blocking conditions: `{summary['blocking_condition_count']}`",
        "",
        "## Proof Steps",
        "",
    ]
    for step in report["proof_steps"]:
        lines.append(f"- `{step['proof_id']}`: `{step['status']}` via {step['command_family']}")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This gate does not run DevTools, fetch network resources, upload, submit review, publish, deploy CloudRun, sync CloudBase, mutate DB/current packages, write coordinates, start workers, read credentials, or run provider/model calls.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build weekly upload/effective-data proof gate.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--source-gate", type=Path, default=DEFAULT_SOURCE_GATE)
    parser.add_argument("--source-rows", type=Path, default=DEFAULT_SOURCE_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report = build_report(repo_root, args.source_gate, args.source_rows)
    output_json = args.out_dir / "weekly_upload_effective_data_proof_gate.json"
    steps_jsonl = args.out_dir / "weekly_upload_effective_data_proof_steps.jsonl"
    blockers_jsonl = args.out_dir / "weekly_upload_effective_data_proof_blockers.jsonl"
    write_json(output_json, report)
    write_jsonl(steps_jsonl, report["proof_steps"])
    write_jsonl(blockers_jsonl, report["blockers"])
    write_scorecard(args.scorecard, report)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": report["decision"],
                "summary": report["summary"],
                "output_json": str(output_json),
                "scorecard": str(args.scorecard),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
