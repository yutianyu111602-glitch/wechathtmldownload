#!/usr/bin/env python3
"""Build S232D-3B target-resolution release preflight.

This report-only guard sits after S232D-3A. It verifies that the seed target
resolver contract is safe enough to request a future controller release, while
keeping every execution surface closed. It does not resolve targets, build
search URLs, fetch network resources, start Docker, read credentials, write DBs,
project DB2, or release downstream consumers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_S232D3A = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3a_seed_target_resolver_contract_20260602"
    / "atlas_relation_identity_s232d3a_seed_target_resolver_contract.json"
)
DEFAULT_QUEUE = (
    REPORTS_ROOT
    / "atlas_relation_identity_s232d3a_seed_target_resolver_contract_20260602"
    / "s232d3a_seed_target_resolver_queue.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b_target_resolution_release_preflight_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B_TARGET_RESOLUTION_PREFLIGHT_20260602.md"

STORY_ID = "S232D-3B-0"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b_target_resolution_release_preflight.v1"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return f"external-fixture/{path.name}"


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ok"}
    return bool(value)


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
        for kind, pattern in (("raw_url", RAW_URL_RE), ("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(text):
                findings.append({"kind": kind, "path": path, "severity": "block"})

    walk(payload, "")
    return findings


def extract_release_token(args: argparse.Namespace) -> str:
    if args.controller_release_id:
        return args.controller_release_id.strip()
    return os.environ.get("ATLAS_S232D3B_CONTROLLER_RELEASE", "").strip()


def validate_s232d3a_contract(report: dict[str, Any], queue_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    contract = report.get("contract") if isinstance(report.get("contract"), dict) else {}

    if report.get("decision") != "atlas_relation_identity_s232d3a_seed_target_resolver_contract_ready_report_only":
        failed.append({"check": "s232d3a_ready_decision_required"})
    if as_int(counts.get("target_resolver_queue_count")) != 5:
        failed.append({"check": "s232d3a_queue_count_5_required"})
    if len(queue_rows) != 5:
        failed.append({"check": "s232d3a_queue_jsonl_count_5_required", "actual": len(queue_rows)})
    if not as_bool(contract.get("seed_names_are_not_fetch_targets")):
        failed.append({"check": "seed_names_must_not_be_fetch_targets"})
    if as_bool(contract.get("raw_url_output_allowed")):
        failed.append({"check": "raw_url_output_must_not_be_allowed"})
    if as_bool(contract.get("credential_read_allowed")):
        failed.append({"check": "credential_read_must_not_be_allowed"})
    if as_bool(contract.get("db1_db2_db3_write_allowed")) or as_bool(contract.get("db2_projection_allowed")):
        failed.append({"check": "db_write_projection_must_not_be_allowed"})
    if as_int(counts.get("network_fetch_ready_count")) != 0 or as_int(counts.get("network_fetch_attempt_count")) != 0:
        failed.append({"check": "s232d3a_network_counts_must_be_zero"})
    if as_int(counts.get("db_write_candidate_count")) != 0 or as_int(counts.get("db2_projection_candidate_count")) != 0:
        failed.append({"check": "s232d3a_db_projection_candidates_must_be_zero"})
    if as_int(counts.get("raw_url_private_path_secret_leak_count")) != 0 or report.get("leak_findings"):
        failed.append({"check": "s232d3a_leak_count_zero_required"})

    for row in queue_rows:
        if row.get("story_id") != "S232D-3A":
            failed.append({"check": "queue_row_story_id_s232d3a_required", "work_order_id": row.get("work_order_id", "")})
        if as_bool(row.get("target_material_present")):
            failed.append({"check": "target_material_must_not_preexist_in_s232d3a", "work_order_id": row.get("work_order_id", "")})
        for flag in ("network_fetch_ready", "network_fetch_attempted", "db_write_executed", "db2_projection_executed"):
            if as_bool(row.get(flag)):
                failed.append({"check": "queue_row_forbidden_flag_false", "flag": flag, "work_order_id": row.get("work_order_id", "")})
    return failed


def queue_preview(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for row in rows:
        preview.append(
            {
                "ordinal": as_int(row.get("ordinal")),
                "work_order_id": row.get("work_order_id") or "",
                "seed_value_hash": row.get("seed_value_hash") or "",
                "seed_kind": row.get("seed_kind") or "",
                "target_resolution_status": row.get("target_resolution_status") or "",
                "target_material_present": as_bool(row.get("target_material_present")),
                "network_fetch_ready": as_bool(row.get("network_fetch_ready")),
                "db_write_executed": as_bool(row.get("db_write_executed")),
                "db2_projection_executed": as_bool(row.get("db2_projection_executed")),
            }
        )
    return preview


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    s232d3a = read_json(args.s232d3a)
    queue_rows = read_jsonl(args.queue)
    release_token = extract_release_token(args)
    controller_release_present = release_token.startswith("CTRL-S232D-3B-")

    failed_checks = validate_s232d3a_contract(s232d3a, queue_rows)
    s232d3a_contract_green = not failed_checks
    preconditions_ready_except_release = s232d3a_contract_green
    blocked_reasons: list[dict[str, Any]] = []
    if not controller_release_present:
        blocked_reasons.append(
            {
                "reason": "s232d3b_controller_release_missing",
                "effect": "target_resolution_canary_must_not_start",
                "severity": "hold",
            }
        )
    if not s232d3a_contract_green:
        blocked_reasons.append(
            {
                "reason": "s232d3a_contract_or_queue_not_green",
                "effect": "target_resolution_canary_must_not_start",
                "severity": "block",
            }
        )

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": (
            "atlas_relation_identity_s232d3b_target_resolution_preflight_ready_waiting_execute_release_report_only"
            if controller_release_present and preconditions_ready_except_release
            else "atlas_relation_identity_s232d3b_target_resolution_preflight_blocked_no_controller_release_report_only"
        ),
        "inputs": {
            "s232d3a_summary": rel(args.s232d3a),
            "s232d3a_queue": rel(args.queue),
        },
        "readiness": {
            "controller_release_present": controller_release_present,
            "controller_release_id_present_but_redacted": bool(release_token),
            "s232d3a_contract_green": s232d3a_contract_green,
            "target_resolution_preconditions_ready_except_release": preconditions_ready_except_release,
            "queue_count": len(queue_rows),
            "target_material_present_count": sum(1 for row in queue_rows if as_bool(row.get("target_material_present"))),
            "network_fetch_ready_count": sum(1 for row in queue_rows if as_bool(row.get("network_fetch_ready"))),
            "db_write_candidate_count": 0,
            "db2_projection_candidate_count": 0,
        },
        "target_resolution_contract": {
            "allowed_runtime": "docker_container_worker_only_after_controller_release",
            "allowed_scope": "s232d3a_first5_queue_only",
            "seed_names_are_not_urls": True,
            "seed_to_search_url_generation_allowed": False,
            "network_fetch_allowed_by_this_report": False,
            "credential_read_allowed": False,
            "raw_url_output_allowed": False,
            "output_policy": "hashed_target_or_domain_metadata_only_after_new_release",
            "required_future_evidence": [
                "new CTRL-S232D-3B controller release",
                "container worker/runtime contract for target resolution",
                "allowlist exactly matches S232D-3A five work_order_ids",
                "no cookie/token/.env/browser-profile/API-key requirement",
                "no raw URL/private path/secret emitted in JSON/markdown/logs",
                "no DB1/DB2/DB3 write, DB2 projection, deploy, sync, upload, review, or release",
            ],
        },
        "queue_preview": queue_preview(queue_rows),
        "failed_checks": failed_checks,
        "blocked_reasons": blocked_reasons,
        "target_resolution_execution_allowed_now": False,
        "collector_executed": False,
        "docker_started": False,
        "db2_worker_started": False,
        "network_fetch_executed": False,
        "db_write_executed": False,
        "db1_mutation": False,
        "db2_mutation": False,
        "db3_mutation": False,
        "db2_projection_allowed_now": False,
        "db3_write_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "cookie_or_token_read": False,
        "api_key_read": False,
        "browser_profile_read": False,
        "raw_source_url_emitted": False,
        "private_path_emitted": False,
        "next_gate": "S232D-3B target-resolution canary requires a new controller release and must run only through Docker/container worker/runtime; S232D-4 and DB3 write remain unreleased.",
        "production_state_difference": "Report-only S232D-3B release preflight; no target resolution, Docker start, network fetch, DB mutation, DB2 projection, deploy/sync/upload/review/release, credential read, or raw URL output.",
    }
    leaks = leak_scan(report)
    report["leak_findings"] = leaks
    report["raw_url_private_path_secret_leak_count"] = len(leaks)
    if leaks:
        report["decision"] = "atlas_relation_identity_s232d3b_target_resolution_preflight_blocked_leak_findings_report_only"
        report["readiness"]["target_resolution_preconditions_ready_except_release"] = False
    return report


def render_markdown(report: dict[str, Any]) -> str:
    readiness = report["readiness"]
    return "\n".join(
        [
            "# S232D-3B Target Resolution Release Preflight",
            "",
            f"- Decision: `{report['decision']}`",
            f"- Controller release present: `{readiness['controller_release_present']}`",
            f"- S232D-3A contract green: `{readiness['s232d3a_contract_green']}`",
            f"- Preconditions ready except release: `{readiness['target_resolution_preconditions_ready_except_release']}`",
            f"- Queue count: `{readiness['queue_count']}`",
            f"- Target material present: `{readiness['target_material_present_count']}`",
            f"- Network fetch ready: `{readiness['network_fetch_ready_count']}`",
            f"- Leak count: `{report['raw_url_private_path_secret_leak_count']}`",
            "",
            "## Boundary",
            "",
            "- Report-only preflight. No target resolution, no Docker start, no collector, and no network fetch.",
            "- Seed names must not be converted into search URLs by this gate.",
            "- No cookie/token/.env/browser profile/API key/credential read.",
            "- No DB1/DB2/DB3 write, no DB2 projection, no deploy/sync/upload/review/release.",
            "- S232D-4 / DB3 write remains unreleased.",
            "",
            "## Next Gate",
            "",
            report["next_gate"],
            "",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(args)
    json_path = args.out_dir / "atlas_relation_identity_s232d3b_target_resolution_release_preflight.json"
    markdown_path = args.out_dir / "atlas_relation_identity_s232d3b_target_resolution_release_preflight.md"
    report["artifacts"] = {
        "summary_json": rel(json_path),
        "markdown": rel(markdown_path),
        "scorecard": rel(args.scorecard),
    }
    write_json(json_path, report)
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    args.scorecard.parent.mkdir(parents=True, exist_ok=True)
    args.scorecard.write_text(markdown, encoding="utf-8")
    write_json(json_path, report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S232D-3B target-resolution release preflight")
    parser.add_argument("--s232d3a", type=Path, default=DEFAULT_S232D3A)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--controller-release-id", default="")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not report.get("leak_findings") else 1


if __name__ == "__main__":
    raise SystemExit(main())
