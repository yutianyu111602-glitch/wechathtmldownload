#!/usr/bin/env python3
"""Build an explicit bounded execution gate for weekly remote-effective proof collection."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_upload_effective_data_proof_execution_gate.v1"
SOURCE_SCHEMA = "weekly_upload_effective_data_proof_gate.v1"
SOURCE_DECISION = "weekly_upload_effective_data_proof_gate_ready_report_only_waiting_explicit_execution"
DECISION = "weekly_upload_effective_data_proof_execution_gate_ready_bounded_read_only_no_upload"
RELEASE_ID = "CTRL-WEEKLY-UPLOAD-EFFECTIVE-DATA-PROOF-READONLY-20260603-019e86a8-adb6-7953-bdfd-9bb6fa41ccd7"

DEFAULT_SOURCE_GATE = (
    REPORTS_ROOT
    / "weekly_upload_effective_data_proof_gate_20260603"
    / "weekly_upload_effective_data_proof_gate.json"
)
DEFAULT_SOURCE_STEPS = (
    REPORTS_ROOT
    / "weekly_upload_effective_data_proof_gate_20260603"
    / "weekly_upload_effective_data_proof_steps.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_upload_effective_data_proof_execution_gate_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_UPLOAD_EFFECTIVE_DATA_PROOF_EXECUTION_GATE_20260603.md"

EXECUTION_CONTRACTS: dict[str, dict[str, Any]] = {
    "remote_effective:miniprogram_render_after_storage_clear": {
        "execution_lane": "devtools_render_single_attempt",
        "allowed_now": True,
        "command": [
            "python",
            "tools/stage7_rewrite/scripts/run_miniprogram_devtools_rendered_single_attempt.py",
            "--script",
            "devtools-current-package-rendered.cjs",
            "--port",
            "9441",
            "--avoid-busy-port",
            "--execute",
        ],
        "requires": [
            "clean_or_explicitly_overridden_devtools_environment",
            "redacted_stdout_stderr",
            "single_script_only",
        ],
        "expected_artifact": "tools/stage7_rewrite/reports/weekly_miniprogram_devtools_single_attempt_*/weekly_miniprogram_devtools_rendered_single_attempt.json",
    },
    "remote_effective:cloudrun_current_endpoint": {
        "execution_lane": "public_cloudrun_current_read",
        "allowed_now": True,
        "command": [
            "powershell",
            "-NoProfile",
            "-Command",
            "Invoke-RestMethod 'https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com/api/v1/weekly/current?limit=100' | ConvertTo-Json -Depth 30",
        ],
        "requires": [
            "read_only_http_get",
            "record_total_window_dates_poster_fields",
            "no_credentials",
        ],
        "expected_artifact": "tools/stage7_rewrite/reports/weekly_upload_effective_data_proof_execution_*/cloudrun_current_endpoint_proof.json",
    },
    "remote_effective:cloudbase_database_current": {
        "execution_lane": "cloudbase_current_read_only",
        "allowed_now": True,
        "command": [
            "node",
            "tools/stage7_rewrite/scripts/weekly-cloudbase-read-current-proof.cjs",
        ],
        "requires": [
            "read_only_cloudbase_or_health_route",
            "redact_tokens",
            "record_counts_and_source",
        ],
        "expected_artifact": "tools/stage7_rewrite/reports/weekly_upload_effective_data_proof_execution_*/cloudbase_database_current_proof.json",
    },
    "remote_effective:miniprogram_uploaded_version": {
        "execution_lane": "uploaded_version_metadata_read_only",
        "allowed_now": True,
        "command": [
            "powershell",
            "-NoProfile",
            "-Command",
            "Read the current WeChat DevTools upload metadata only; do not upload. Record version/appid/package identity in a redacted proof artifact.",
        ],
        "requires": [
            "read_metadata_only",
            "no_upload",
            "no_review",
            "no_public_release",
        ],
        "expected_artifact": "tools/stage7_rewrite/reports/weekly_upload_effective_data_proof_execution_*/uploaded_version_metadata_proof.json",
    },
    "remote_effective:poster_image_fetch": {
        "execution_lane": "poster_image_public_fetch",
        "allowed_now": True,
        "command": [
            "powershell",
            "-NoProfile",
            "-Command",
            "Fetch one or more poster image URLs from the current package and record HTTP status/content-type/content-length; do not write DB or package data.",
        ],
        "requires": [
            "read_current_poster_url",
            "bounded_http_get",
            "record_no_image_errors",
        ],
        "expected_artifact": "tools/stage7_rewrite/reports/weekly_upload_effective_data_proof_execution_*/poster_image_fetch_proof.json",
    },
}

FORBIDDEN_ACTIONS = [
    "miniprogram_upload",
    "wechat_review_submit",
    "public_release",
    "cloudrun_deploy",
    "cloudbase_sync_or_write",
    "database_or_coordinate_write",
    "package_rebuild",
    "provider_or_model_call",
    "docker_worker_runtime",
    "credential_or_secret_print",
    "browser_cookie_or_profile_read",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
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


def build_execution_steps(source_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    execution_steps: list[dict[str, Any]] = []
    for source_step in source_steps:
        proof_id = str(source_step.get("proof_id", ""))
        contract = EXECUTION_CONTRACTS.get(proof_id)
        if not contract:
            continue
        execution_steps.append(
            {
                "schema_version": SCHEMA_VERSION,
                "proof_id": proof_id,
                "source_step_id": source_step.get("step_id", ""),
                "execution_lane": contract["execution_lane"],
                "status": "execution_allowed_waiting_artifact",
                "execution_allowed_by_this_gate": bool(contract["allowed_now"]),
                "command": contract["command"],
                "requires": contract["requires"],
                "expected_artifact": contract["expected_artifact"],
                "evidence_artifact": "",
                "proof_artifact_present": False,
                "proof_proven": False,
                "forbidden_actions": FORBIDDEN_ACTIONS,
                "upload_allowed_by_this_step": False,
                "review_release_allowed_by_this_step": False,
            }
        )
    return execution_steps


def build_report(repo_root: Path, source_gate_path: Path, source_steps_path: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    source_gate_path = source_gate_path if source_gate_path.is_absolute() else repo_root / source_gate_path
    source_steps_path = source_steps_path if source_steps_path.is_absolute() else repo_root / source_steps_path
    source_gate = read_json(source_gate_path)
    source_steps = read_jsonl(source_steps_path)
    source_summary = source_gate.get("summary", {})
    execution_steps = build_execution_steps(source_steps)
    source_ready = bool(
        source_gate.get("schema_version") == SOURCE_SCHEMA
        and source_gate.get("decision") == SOURCE_DECISION
        and source_summary.get("source_gate_ready_for_proof_gate") is True
        and source_summary.get("proof_execution_allowed_now") is False
        and source_summary.get("miniprogram_upload_allowed_now") is False
        and source_summary.get("release_ready") is False
        and len(execution_steps) == 5
    )
    blockers: list[dict[str, Any]] = []
    if not source_ready:
        blockers.append(
            {
                "schema_version": SCHEMA_VERSION,
                "blocker_id": "source_upload_effective_proof_gate_not_ready",
                "status": "blocking",
                "details": "The source proof gate must be local-green, five-step, and fail-closed before proof execution can be released.",
            }
        )
    for step in execution_steps:
        blockers.append(
            {
                "schema_version": SCHEMA_VERSION,
                "blocker_id": f"proof_artifact_missing:{step['proof_id']}",
                "proof_id": step["proof_id"],
                "status": "blocking",
                "details": "Execution is allowed by this gate, but no proof artifact has been collected yet.",
            }
        )
    summary = {
        "source_proof_gate_ready": source_ready,
        "execution_gate_released": source_ready,
        "release_id": RELEASE_ID,
        "proof_step_count": len(execution_steps),
        "proof_execution_allowed_count": sum(1 for step in execution_steps if step["execution_allowed_by_this_gate"]),
        "proof_artifact_present_count": 0,
        "proof_steps_proven_count": 0,
        "proof_artifact_missing_count": len(execution_steps),
        "blocking_condition_count": len(blockers),
        "devtools_render_execution_allowed_now": source_ready,
        "public_network_read_allowed_now": source_ready,
        "cloudbase_read_only_allowed_now": source_ready,
        "upload_metadata_read_only_allowed_now": source_ready,
        "poster_fetch_allowed_now": source_ready,
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
        "decision": DECISION if source_ready else "weekly_upload_effective_data_proof_execution_gate_blocked_source_not_ready",
        "release_id": RELEASE_ID,
        "mode": "bounded_read_only_proof_execution_no_upload_no_release",
        "objective": "Explicitly release bounded read-only proof collection for the five remote-effective proof steps while keeping upload/review/release closed.",
        "source_gate": display_path(source_gate_path, repo_root),
        "source_steps": display_path(source_steps_path, repo_root),
        "execution_steps": execution_steps,
        "blockers": blockers,
        "summary": summary,
        "boundary": {
            "devtools_single_attempt_allowed": source_ready,
            "public_http_get_allowed": source_ready,
            "cloudbase_read_only_allowed": source_ready,
            "upload_metadata_read_only_allowed": source_ready,
            "poster_image_fetch_allowed": source_ready,
            "cloudrun_deployed": False,
            "cloudbase_sync_executed": False,
            "database_mutations": False,
            "coordinate_writes": False,
            "package_rebuild_executed": False,
            "miniprogram_upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "credential_or_secret_read": False,
            "browser_cookie_or_profile_read": False,
            "docker_or_worker_started": False,
            "provider_or_model_call": False,
        },
        "next_required_artifacts": [step["expected_artifact"] for step in execution_steps],
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Weekly Upload/Effective-Data Proof Execution Gate",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- release id: `{report['release_id']}`",
        f"- source proof gate ready: `{summary['source_proof_gate_ready']}`",
        f"- execution gate released: `{summary['execution_gate_released']}`",
        f"- proof steps: `{summary['proof_step_count']}`",
        f"- proof execution allowed count: `{summary['proof_execution_allowed_count']}`",
        f"- proof artifacts present: `{summary['proof_artifact_present_count']}`",
        f"- proof artifacts missing: `{summary['proof_artifact_missing_count']}`",
        f"- mini-program upload allowed now: `{summary['miniprogram_upload_allowed_now']}`",
        f"- review/release allowed now: `{summary['review_release_allowed_now']}`",
        f"- release ready: `{summary['release_ready']}`",
        "",
        "## Execution Steps",
        "",
    ]
    for step in report["execution_steps"]:
        command = " ".join(str(part) for part in step["command"])
        lines.append(f"- `{step['proof_id']}`: `{step['status']}`; command: `{command}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This gate may be used to collect bounded read-only proof artifacts. It does not upload, submit review, publish, deploy CloudRun, sync CloudBase, mutate DB/current packages, write coordinates, start Docker/worker runtimes, read credentials, read browser cookies/profiles, or call providers/models.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build weekly upload/effective-data proof execution gate.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--source-gate", type=Path, default=DEFAULT_SOURCE_GATE)
    parser.add_argument("--source-steps", type=Path, default=DEFAULT_SOURCE_STEPS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    report = build_report(repo_root, args.source_gate, args.source_steps)
    output_json = args.out_dir / "weekly_upload_effective_data_proof_execution_gate.json"
    steps_jsonl = args.out_dir / "weekly_upload_effective_data_proof_execution_steps.jsonl"
    blockers_jsonl = args.out_dir / "weekly_upload_effective_data_proof_execution_blockers.jsonl"
    write_json(output_json, report)
    write_jsonl(steps_jsonl, report["execution_steps"])
    write_jsonl(blockers_jsonl, report["blockers"])
    write_scorecard(args.scorecard, report)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": report["decision"],
                "release_id": report["release_id"],
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
