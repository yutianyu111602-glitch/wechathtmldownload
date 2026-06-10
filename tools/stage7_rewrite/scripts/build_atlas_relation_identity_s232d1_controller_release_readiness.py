#!/usr/bin/env python3
"""Build S232D-1 controller-release readiness report.

This report consumes S232D-0 and release-guard evidence to decide whether the
controller has enough report-only proof to consider releasing a bounded Docker
collector. It never grants release by itself and never starts Docker, workers,
network fetches, DB writes, projection, deploy, upload, review, or release.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_S232D0_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d0_docker_worker_contract_20260602"
DEFAULT_S232D0_SUMMARY = DEFAULT_S232D0_DIR / "atlas_relation_identity_s232d0_docker_worker_contract.json"
DEFAULT_S232D0_CONTRACT = DEFAULT_S232D0_DIR / "s232d0_docker_worker_contract.json"
DEFAULT_RELEASE_GUARD = (
    REPORTS_ROOT
    / "weekly_cloudbase_ai_health_guard_20260602_20260602_154701"
    / "guard_release_with_s232d0_upstream_gates.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d1_controller_release_readiness_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D1_CONTROLLER_RELEASE_READINESS_20260602.md"

STORY_ID = "S232D-1"
SCHEMA_VERSION = "atlas_relation_identity_s232d1_controller_release_readiness.v1"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
ABS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=)",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "ok"}
    return bool(value)


def check_map(guard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = guard.get("checks")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("name"):
            result[str(row["name"])] = row
    return result


def guard_check_ok(guard_checks: dict[str, dict[str, Any]], name: str) -> bool:
    return bool(guard_checks.get(name, {}).get("ok"))


def compact_guard_detail(guard_checks: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    row = guard_checks.get(name) or {}
    return {"name": name, "ok": bool(row.get("ok"))}


def leak_scan(payload: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, f"{path}.{key}" if path else str(key))
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")
            return
        if value is None:
            return
        text = str(value)
        for kind, pattern in (("raw_url", RAW_URL_RE), ("absolute_path", ABS_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(text):
                findings.append({"kind": kind, "path": path, "severity": "block"})

    walk(payload, "")
    return findings


def release_guard_summary(guard: dict[str, Any]) -> dict[str, Any]:
    checks = check_map(guard)
    names = [
        "s232d0_docker_worker_contract_json_exists",
        "s232d0_contract_validation_green",
        "s232d0_controller_release_green",
        "s232d0_container_smoke_green",
        "s232d0_release_gate_green",
    ]
    return {
        "guard_mode": guard.get("gateMode") or "",
        "ok": bool(guard.get("ok")),
        "remote_total": as_int(guard.get("remoteTotal")),
        "failed_check_count": sum(1 for row in checks.values() if not bool(row.get("ok"))),
        "s232d0_checks": [compact_guard_detail(checks, name) for name in names],
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    s232d0 = read_json(args.s232d0_summary)
    contract = read_json(args.s232d0_contract)
    guard = read_json(args.release_guard) if args.release_guard.exists() else {}
    guard_checks = check_map(guard)

    work_order_count = as_int((s232d0.get("counts") or {}).get("work_order_count"))
    allowlist_count = as_int((s232d0.get("counts") or {}).get("allowlist_count"))
    failed_contract_checks = as_int((s232d0.get("counts") or {}).get("failed_contract_check_count"))
    contract_valid = bool(s232d0.get("contract_validation_passed")) and failed_contract_checks == 0
    allowlist_valid = work_order_count > 0 and allowlist_count == work_order_count
    downstream_release_guard_consumed_s232d0 = (
        guard_check_ok(guard_checks, "s232d0_docker_worker_contract_json_exists")
        and guard_check_ok(guard_checks, "s232d0_contract_validation_green")
    )
    skill_control_plane = (contract.get("control_plane_rule") or {}).get("skill_role") == "control_plane_only"
    docker_runtime_declared = (contract.get("control_plane_rule") or {}).get("required_runtime") == "docker_container_worker"
    no_forbidden_execution = not any(
        bool(s232d0.get(flag))
        for flag in (
            "collector_execution_allowed_now",
            "container_smoke_allowed_now",
            "container_smoke_executed",
            "docker_started",
            "db2_worker_started",
            "network_fetch_executed",
            "db_write_executed",
            "db2_projection_allowed_now",
            "db3_write_allowed_now",
            "deploy_upload_release_allowed_now",
            "cookie_or_token_read",
            "raw_source_url_emitted",
        )
    )

    collector_release_preconditions_ready = all(
        [
            contract_valid,
            allowlist_valid,
            skill_control_plane,
            docker_runtime_declared,
            no_forbidden_execution,
        ]
    )
    controller_release_present = bool(s232d0.get("controller_release_present"))
    db3_blocker = as_int((s232d0.get("source_state") or {}).get("db3_same_normalized_name_multi_id"))

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": (
            "atlas_relation_identity_s232d1_ready_for_controller_release_decision_report_only"
            if collector_release_preconditions_ready
            else "atlas_relation_identity_s232d1_controller_release_readiness_blocked_report_only"
        ),
        "inputs": {
            "s232d0_summary": rel(args.s232d0_summary),
            "s232d0_contract": rel(args.s232d0_contract),
            "release_guard": rel(args.release_guard) if args.release_guard.exists() else "",
        },
        "source_state": {
            "s232d0_decision": s232d0.get("decision") or "",
            "db3_same_normalized_name_multi_id": db3_blocker,
            "s232b_evidence_gap_count": as_int((s232d0.get("source_state") or {}).get("s232b_evidence_gap_count")),
            "s232b_candidate_subset_count": as_int(
                (s232d0.get("source_state") or {}).get("s232b_candidate_subset_count")
            ),
        },
        "release_guard_summary": release_guard_summary(guard),
        "hard_evidence_required_for_controller_release": [
            "S232D-0 contract_validation_passed=true and failed_contract_check_count=0",
            "S232D-0 allowlist_count equals selected work_order_count and every row keeps execution/network/write/projection flags false",
            "Docker/container runtime is declared as the only collector runtime; skill remains control-plane only",
            "Input mounts are read-only; output is report-local evidence only; production DB, browser profile, and credential mounts are forbidden",
            "Output evidence schema contains hashed source/provider identifiers, evidence status, confidence, artifact hash, collected_at, and needs_human_review",
            "No cookie/token/API key/browser-profile read is required for the selected work orders",
            "No raw source URL, private archive path, credential, DB write SQL, or DB2 projection event is emitted before a later promotion gate",
            "Controller release is explicit, current, and scoped only to S232D Docker/container smoke plus collector over the S232D-0 allowlist",
        ],
        "docker_contract_required_fields": [
            "control_plane_rule.skill_role=control_plane_only",
            "control_plane_rule.required_runtime=docker_container_worker",
            "container_runtime.compose_profile",
            "container_runtime.service",
            "container_runtime.entrypoint_contract",
            "container_runtime.forced_dry_run_env",
            "mount_contract.read_only",
            "mount_contract.write_only_report_local",
            "mount_contract.production_db_mount=forbidden",
            "mount_contract.browser_profile_mount=forbidden",
            "mount_contract.credential_mount=forbidden",
            "output_evidence_schema.required_fields",
            "output_evidence_schema.forbidden_fields",
            "policy.allowlist_only=true",
            "policy.no_cookie_public_only=true",
            "policy.no_db1_db2_db3_write=true",
            "policy.no_db2_projection=true",
            "policy.no_deploy_sync_upload_review_release=true",
        ],
        "source_backed_evidence_gate": {
            "purpose": "S232D collector may only create report-local source/provider evidence that can feed S232B/S232A/S146; it cannot promote DB3 rows by itself.",
            "minimum_evidence_fields": [
                "work_order_id",
                "source_task_id_hash",
                "provider_anchor_hash",
                "evidence_kind",
                "evidence_status",
                "confidence",
                "artifact_hash",
                "collected_at",
                "needs_human_review",
            ],
            "post_collection_required_gates": [
                "S232B rerun proves source-backed disposition-ready rows and a non-empty candidate subset",
                "S232A rerun proves DB3 safe write subset and DB2 projection gate state",
                "S146 or equivalent guarded write preflight proves source-ref coverage, lock, backup/rollback, field preservation, no-empty-overwrite, transaction, and postwrite readback",
            ],
        },
        "readiness": {
            "collector_release_preconditions_ready": collector_release_preconditions_ready,
            "contract_valid": contract_valid,
            "allowlist_valid": allowlist_valid,
            "downstream_release_guard_consumed_s232d0": downstream_release_guard_consumed_s232d0,
            "skill_control_plane": skill_control_plane,
            "docker_runtime_declared": docker_runtime_declared,
            "no_forbidden_execution": no_forbidden_execution,
            "controller_release_present": controller_release_present,
        },
        "counts": {
            "work_order_count": work_order_count,
            "allowlist_count": allowlist_count,
            "failed_contract_check_count": failed_contract_checks,
            "hold_condition_count": as_int((s232d0.get("counts") or {}).get("hold_condition_count")),
        },
        "controller_release_allowed_by_this_report": False,
        "collector_execution_allowed_now": False,
        "container_smoke_allowed_now": False,
        "container_smoke_executed": False,
        "docker_started": False,
        "db2_worker_started": False,
        "network_fetch_executed": False,
        "db_write_executed": False,
        "db2_projection_allowed_now": False,
        "db3_write_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "cookie_or_token_read": False,
        "raw_source_url_emitted": False,
        "blocked_now": [
            "explicit_controller_release_missing",
            "db3_write_projection_release_blocked_until_s232b_s232a_s146_and_write_gate",
        ],
        "stop_conditions": [
            "controller release is absent, stale, or broader than S232D Docker/container smoke plus allowlist collector",
            "any collector path would run outside Docker/container worker runtime",
            "any input requires cookie/token/browser profile/API key/credential access",
            "any raw source URL, private archive path, credential value, DB write SQL, or DB2 projection event would be printed or written to public docs",
            "any DB1/DB2/DB3 mutation, DB2 projection, deploy, sync, upload, review, or release is requested before S232B/S232A/S146 and guarded write gates pass",
            "any DB/file lock, single-writer, backup/rollback, transaction, or readback requirement is missing for a future write gate",
        ],
        "next_gate": (
            "Controller may decide whether to release a bounded Docker/container smoke and collector for the S232D-0 "
            "allowlist only; this report does not grant release and does not allow DB writes, DB2 projection, deploy, upload, review, or public release."
        ),
        "production_state_difference": "report-only controller-release readiness; no Docker start, DB2 worker, network fetch, DB mutation, projection, deploy/upload/review/release, or secret read",
    }
    report["leak_findings"] = leak_scan(report)
    if report["leak_findings"]:
        report["decision"] = "atlas_relation_identity_s232d1_controller_release_readiness_blocked_leak_findings_report_only"
        report["readiness"]["collector_release_preconditions_ready"] = False
    return report


def render_markdown(report: dict[str, Any]) -> str:
    readiness = report["readiness"]
    counts = report["counts"]
    return "\n".join(
        [
            "# S232D-1 Controller Release Readiness",
            "",
            f"- Decision: `{report['decision']}`",
            f"- Collector release preconditions ready: `{readiness['collector_release_preconditions_ready']}`",
            f"- Controller release present: `{readiness['controller_release_present']}`",
            f"- Work orders / allowlist: `{counts['work_order_count']}` / `{counts['allowlist_count']}`",
            f"- Failed contract checks: `{counts['failed_contract_check_count']}`",
            f"- DB3 same-normalized blocker count: `{report['source_state']['db3_same_normalized_name_multi_id']}`",
            "",
            "## Readiness",
            "",
            f"- Contract valid: `{readiness['contract_valid']}`",
            f"- Downstream release guard consumed S232D-0: `{readiness['downstream_release_guard_consumed_s232d0']}`",
            f"- Skill control-plane only: `{readiness['skill_control_plane']}`",
            f"- Docker runtime declared: `{readiness['docker_runtime_declared']}`",
            f"- No forbidden execution: `{readiness['no_forbidden_execution']}`",
            "",
            "## Boundary",
            "",
            "- Report-only controller-release readiness.",
            "- No controller release is granted by this report.",
            "- No Docker start, collector, DB2 worker, network fetch, DB1/DB2/DB3 mutation, DB2 projection, deploy, sync, upload, review, release, or secret/raw URL output.",
            "",
            "## Next",
            "",
            report["next_gate"],
            "",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    scorecard = None if getattr(args, "no_scorecard", False) else args.scorecard
    report = build_report(args)
    paths = {
        "json": out_dir / "atlas_relation_identity_s232d1_controller_release_readiness.json",
        "markdown": out_dir / "atlas_relation_identity_s232d1_controller_release_readiness.md",
    }
    report["output_dir"] = rel(out_dir)
    report["artifacts"] = {name: rel(path) for name, path in paths.items()}
    write_json(paths["json"], report)
    markdown = render_markdown(report)
    paths["markdown"].write_text(markdown, encoding="utf-8")
    if scorecard:
        scorecard.parent.mkdir(parents=True, exist_ok=True)
        scorecard.write_text(markdown, encoding="utf-8")
        report["artifacts"]["scorecard"] = rel(scorecard)
        write_json(paths["json"], report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S232D-1 controller-release readiness report")
    parser.add_argument("--s232d0-summary", type=Path, default=DEFAULT_S232D0_SUMMARY)
    parser.add_argument("--s232d0-contract", type=Path, default=DEFAULT_S232D0_CONTRACT)
    parser.add_argument("--release-guard", type=Path, default=DEFAULT_RELEASE_GUARD)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not report.get("leak_findings") else 1


if __name__ == "__main__":
    raise SystemExit(main())
