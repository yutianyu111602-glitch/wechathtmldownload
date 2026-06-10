#!/usr/bin/env python3
"""Build S232D-0 Docker worker contract for bounded evidence collection.

S232D-0 is report-only. It consumes the S232C work-order queue and defines how
those orders must be handed to the DB2 weapons Docker/container runtime after a
future controller release. It does not start Docker, execute collectors, fetch
network resources, write DB1/DB2/DB3, project DB2, or release anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_S232C_DIR = REPORTS_ROOT / "atlas_relation_identity_s232c_bounded_evidence_gate_20260602"
DEFAULT_S232C_REPORT = DEFAULT_S232C_DIR / "atlas_relation_identity_s232c_bounded_evidence_gate.json"
DEFAULT_S232C_WORK_ORDERS = DEFAULT_S232C_DIR / "s232c_bounded_evidence_acquisition_queue.jsonl"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d0_docker_worker_contract_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D0_DOCKER_WORKER_CONTRACT_20260602.md"

STORY_ID = "S232D-0"
SCHEMA_VERSION = "atlas_relation_identity_s232d0_docker_worker_contract.v1"
ALLOWLIST_SCHEMA_VERSION = f"{SCHEMA_VERSION}.allowlist"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
ABS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|sessionid=|authorization\s*[:=])",
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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def leaf_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        items: list[str] = []
        for nested in value.values():
            items.extend(leaf_strings(nested))
        return items
    if isinstance(value, list):
        items = []
        for nested in value:
            items.extend(leaf_strings(nested))
        return items
    if value is None:
        return []
    return [str(value)]


def scan_payload(payload: Any, *, scope: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, text in enumerate(leaf_strings(payload)):
        for kind, pattern in (
            ("raw_url", RAW_URL_RE),
            ("absolute_path", ABS_PATH_RE),
            ("secret_like_value", SECRET_VALUE_RE),
        ):
            if pattern.search(text):
                findings.append({"scope": scope, "leaf_index": index, "kind": kind, "severity": "block"})
    return findings


def build_allowlist(work_orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for order, row in enumerate(work_orders, start=1):
        rows.append(
            {
                "schema_version": ALLOWLIST_SCHEMA_VERSION,
                "ordinal": order,
                "work_order_id": row.get("work_order_id") or f"s232c:missing:{order:04d}",
                "source_task_id_hash": stable_hash(row.get("source_task_id")),
                "group_id_hash": stable_hash(row.get("group_id")),
                "subject_id_hash": stable_hash(row.get("subject_id")),
                "s228_lane": row.get("s228_lane") or "",
                "recommended_evidence_mode": row.get("recommended_evidence_mode") or "",
                "priority_score": as_int(row.get("priority_score")),
                "collector_release_required": True,
                "execution_allowed_now": False,
                "network_fetch_allowed_now": False,
                "db3_write_allowed_now": False,
                "db2_projection_allowed_now": False,
                "writer_event_allowed_now": False,
                "raw_source_url_emitted": False,
                "cookie_or_token_required": False,
            }
        )
    return rows


def build_contract(
    s232c_report: dict[str, Any],
    work_orders: list[dict[str, Any]],
    allowlist_path: Path,
    evidence_dir: Path,
    s232c_report_path: Path,
    work_orders_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.docker_contract",
        "story_id": STORY_ID,
        "contract_status": "report_only_waiting_controller_release",
        "input_queue": rel(work_orders_path),
        "work_order_allowlist": rel(allowlist_path),
        "selected_work_order_count": len(work_orders),
        "selected_lane_counts": dict(sorted(Counter(str(row.get("s228_lane") or "unknown") for row in work_orders).items())),
        "recommended_evidence_mode_counts": dict(
            sorted(Counter(str(row.get("recommended_evidence_mode") or "unknown") for row in work_orders).items())
        ),
        "source_state": {
            "s232c_decision": s232c_report.get("decision") or "",
            "db3_same_normalized_name_multi_id": as_int(
                (s232c_report.get("source_state") or {}).get("db3_same_normalized_name_multi_id")
            ),
            "s232b_evidence_gap_count": as_int((s232c_report.get("source_state") or {}).get("s232b_evidence_gap_count")),
            "s232b_candidate_subset_count": as_int(
                (s232c_report.get("source_state") or {}).get("s232b_candidate_subset_count")
            ),
        },
        "control_plane_rule": {
            "skill_role": "control_plane_only",
            "required_runtime": "docker_container_worker",
            "forbidden_skill_pattern": "do_not_embed_collector_logic_or_many_scripts_inside_skill",
            "entrypoint_style": "skill_may_call_docker_compose_or_db2ctl_entrypoint_after_controller_release_only",
        },
        "container_runtime": {
            "compose_profile": "db2-light-workers",
            "service": "db2-light-workers",
            "entrypoint_contract": (
                "db2ctl identity-provider collect --contract /db2-reports/s232d0_docker_worker_contract.json "
                "--input /db2-reports/s232c_bounded_evidence_acquisition_queue.jsonl "
                "--allowlist /db2-reports/s232d0_work_order_allowlist.jsonl "
                "--output /db2-reports/s232d0_report_local_evidence --mode report-only"
            ),
            "controller_release_env": "ATLAS_S232D_CONTROLLER_RELEASE=required",
            "forced_dry_run_env": {
                "ATLAS_COLLECTOR_EXECUTION_ALLOWED": "0",
                "DB2_WORKER_EXECUTE": "0",
                "DB2_WRITER_EXECUTE": "0",
                "DB2_PROJECTION_EXECUTE": "0",
            },
        },
        "mount_contract": {
            "read_only": [
                {
                    "host_artifact": rel(work_orders_path),
                    "container_path": "/db2-reports/s232c_bounded_evidence_acquisition_queue.jsonl",
                },
                {
                    "host_artifact": rel(allowlist_path),
                    "container_path": "/db2-reports/s232d0_work_order_allowlist.jsonl",
                },
                {
                    "host_artifact": rel(s232c_report_path),
                    "container_path": "/db2-reports/atlas_relation_identity_s232c_bounded_evidence_gate.json",
                },
            ],
            "write_only_report_local": [
                {
                    "host_artifact": rel(evidence_dir),
                    "container_path": "/db2-reports/s232d0_report_local_evidence",
                }
            ],
            "production_db_mount": "forbidden",
            "browser_profile_mount": "forbidden",
            "credential_mount": "forbidden",
        },
        "output_evidence_schema": {
            "artifact": "s232d_report_local_normalized_evidence.jsonl",
            "required_fields": [
                "work_order_id",
                "source_task_id_hash",
                "provider_anchor_hash",
                "evidence_kind",
                "evidence_status",
                "artifact_hash",
                "collected_at",
                "confidence",
                "needs_human_review",
            ],
            "forbidden_fields": [
                "raw_source_url",
                "cookie",
                "token",
                "authorization",
                "db3_write_sql",
                "db2_projection_event",
            ],
            "promotion_status": "report_local_candidate_only",
        },
        "policy": {
            "allowlist_only": True,
            "no_cookie_public_only": True,
            "no_secret_or_raw_url_output": True,
            "no_db1_db2_db3_write": True,
            "no_db2_projection": True,
            "no_deploy_sync_upload_review_release": True,
            "single_writer_required_for_future_db_writes": True,
            "backup_rollback_readback_required_for_future_db_writes": True,
        },
        "evidence_dir": rel(evidence_dir),
        "collector_execution_allowed_now": False,
        "container_smoke_allowed_now": False,
        "network_fetch_allowed_now": False,
        "db_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
    }


def validate_contract(
    s232c_report: dict[str, Any],
    work_orders: list[dict[str, Any]],
    allowlist: list[dict[str, Any]],
    contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    failed: list[dict[str, Any]] = []
    hold_conditions: list[dict[str, Any]] = []
    expected = as_int(s232c_report.get("selected_work_order_count"))

    if s232c_report.get("decision") != "atlas_relation_identity_s232c_bounded_evidence_gate_ready_report_only":
        failed.append({"check": "s232c_decision_ready_report_only", "value": s232c_report.get("decision")})
    if len(work_orders) != expected:
        failed.append({"check": "work_order_count_matches_s232c", "expected": expected, "actual": len(work_orders)})
    if len(allowlist) != len(work_orders):
        failed.append({"check": "allowlist_count_matches_work_orders", "expected": len(work_orders), "actual": len(allowlist)})
    for row in allowlist:
        for flag in (
            "execution_allowed_now",
            "network_fetch_allowed_now",
            "db3_write_allowed_now",
            "db2_projection_allowed_now",
            "writer_event_allowed_now",
            "raw_source_url_emitted",
            "cookie_or_token_required",
        ):
            if bool(row.get(flag)):
                failed.append({"check": f"allowlist_flag_false:{flag}", "work_order_id": row.get("work_order_id")})
    for flag in (
        "collector_execution_allowed_now",
        "container_smoke_allowed_now",
        "network_fetch_allowed_now",
        "db_write_allowed_now",
        "db2_projection_allowed_now",
        "deploy_upload_release_allowed_now",
    ):
        if bool(contract.get(flag)):
            failed.append({"check": f"contract_flag_false:{flag}"})

    failed.extend(scan_payload(work_orders, scope="s232c_work_orders"))
    failed.extend(scan_payload(allowlist, scope="s232d0_allowlist"))
    failed.extend(scan_payload(contract, scope="s232d0_contract"))

    if not bool(s232c_report.get("collector_execution_allowed_now")):
        hold_conditions.append(
            {
                "condition": "controller_release_missing",
                "effect": "collector_and_container_smoke_execution_remain_blocked",
                "severity": "hold",
            }
        )
    if as_int((s232c_report.get("source_state") or {}).get("db3_same_normalized_name_multi_id")) != 0:
        hold_conditions.append(
            {
                "condition": "db3_relation_integrity_not_green",
                "value": as_int((s232c_report.get("source_state") or {}).get("db3_same_normalized_name_multi_id")),
                "effect": "db3_write_db2_projection_and_release_remain_blocked",
                "severity": "hold",
            }
        )
    return failed, hold_conditions


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# S232D-0 Docker Worker Contract And Container-Smoke Preflight",
            "",
            f"- Decision: `{report['decision']}`",
            f"- S232C work orders: `{counts['work_order_count']}`",
            f"- Allowlist rows: `{counts['allowlist_count']}`",
            f"- Failed contract checks: `{counts['failed_contract_check_count']}`",
            f"- Hold conditions: `{counts['hold_condition_count']}`",
            f"- DB3 same-normalized blocker count: `{report['source_state']['db3_same_normalized_name_multi_id']}`",
            "",
            "## Lane Counts",
            "",
        ]
        + [f"- `{lane}`: `{count}`" for lane, count in report["selected_lane_counts"].items()]
        + [
            "",
            "## Boundary",
            "",
            "- Report-only Docker worker contract and preflight.",
            "- Skill remains control-plane only; collector logic belongs in Docker/container worker/runtime.",
            "- No Docker start, DB2 worker start, network fetch, DB1/DB2/DB3 mutation, DB2 projection, deploy, sync, upload, review, release, or secret/raw URL output.",
            "",
            "## Next",
            "",
            report["next_gate"],
            "",
        ]
    )


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    s232c_report = read_json(args.s232c_report)
    work_orders = read_jsonl(args.s232c_work_orders)
    allowlist_path = args.out_dir / "s232d0_work_order_allowlist.jsonl"
    evidence_dir = args.out_dir / "s232d0_report_local_evidence"
    allowlist = build_allowlist(work_orders)
    contract = build_contract(
        s232c_report,
        work_orders,
        allowlist_path,
        evidence_dir,
        args.s232c_report,
        args.s232c_work_orders,
    )
    failed, hold_conditions = validate_contract(s232c_report, work_orders, allowlist, contract)
    lane_counts = dict(sorted(Counter(str(row.get("s228_lane") or "unknown") for row in work_orders).items()))
    decision = (
        "atlas_relation_identity_s232d0_docker_worker_contract_ready_report_only_waiting_controller_release"
        if not failed
        else "atlas_relation_identity_s232d0_docker_worker_contract_blocked_contract_failed"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": decision,
        "inputs": {
            "s232c_report": rel(args.s232c_report),
            "s232c_work_orders": rel(args.s232c_work_orders),
        },
        "source_state": contract["source_state"],
        "selected_lane_counts": lane_counts,
        "recommended_evidence_mode_counts": contract["recommended_evidence_mode_counts"],
        "counts": {
            "work_order_count": len(work_orders),
            "allowlist_count": len(allowlist),
            "failed_contract_check_count": len(failed),
            "hold_condition_count": len(hold_conditions),
        },
        "failed_contract_checks": failed,
        "hold_conditions": hold_conditions,
        "contract_validation_passed": not failed,
        "controller_release_present": False,
        "collector_execution_allowed_now": False,
        "container_smoke_allowed_now": False,
        "container_smoke_executed": False,
        "db2_worker_started": False,
        "db2_weapons_worktree_touched": False,
        "docker_started": False,
        "network_fetch_executed": False,
        "db_write_executed": False,
        "db2_projection_allowed_now": False,
        "db3_write_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "cookie_or_token_read": False,
        "raw_source_url_emitted": False,
        "production_state_difference": "report-only Docker/container contract; no worker execution, network fetch, DB mutation, projection, deploy/upload/review/release, or secret read",
        "next_gate": "Wait for explicit controller release, then run a bounded Docker/container smoke and collector over the S232D-0 allowlist only; DB3 writes still require S232B/S232A/S146 plus guarded write preflight/readback.",
    }
    return report, contract, allowlist


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    scorecard = None if getattr(args, "no_scorecard", False) else args.scorecard
    report, contract, allowlist = build_report(args)
    paths = {
        "json": out_dir / "atlas_relation_identity_s232d0_docker_worker_contract.json",
        "markdown": out_dir / "atlas_relation_identity_s232d0_docker_worker_contract.md",
        "docker_worker_contract": out_dir / "s232d0_docker_worker_contract.json",
        "work_order_allowlist": out_dir / "s232d0_work_order_allowlist.jsonl",
        "container_smoke_preflight": out_dir / "s232d0_container_smoke_preflight.json",
    }
    report["output_dir"] = rel(out_dir)
    report["artifacts"] = {name: rel(path) for name, path in paths.items()}
    write_json(paths["json"], report)
    write_json(paths["docker_worker_contract"], contract)
    write_jsonl(paths["work_order_allowlist"], allowlist)
    write_json(paths["container_smoke_preflight"], {"schema_version": f"{SCHEMA_VERSION}.container_smoke_preflight", **report})
    markdown = render_markdown(report)
    paths["markdown"].write_text(markdown, encoding="utf-8")
    if scorecard:
        scorecard.parent.mkdir(parents=True, exist_ok=True)
        scorecard.write_text(markdown, encoding="utf-8")
        report["artifacts"]["scorecard"] = rel(scorecard)
        write_json(paths["json"], report)
        write_json(paths["container_smoke_preflight"], {"schema_version": f"{SCHEMA_VERSION}.container_smoke_preflight", **report})
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S232D-0 Docker worker contract")
    parser.add_argument("--s232c-report", type=Path, default=DEFAULT_S232C_REPORT)
    parser.add_argument("--s232c-work-orders", type=Path, default=DEFAULT_S232C_WORK_ORDERS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--no-scorecard", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["contract_validation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
