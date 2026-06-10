#!/usr/bin/env python3
"""Build S232D-3 collector release preflight.

This is a report-only guard after S232D-2. It decides whether a real no-cookie
collector canary may be requested. It never starts Docker, collectors, DB2
workers, network fetches, DB writes, projections, deploys, uploads, reviews, or
releases.
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
DEFAULT_S232D2 = REPORTS_ROOT / "atlas_relation_identity_s232d2_docker_smoke_20260602" / "atlas_relation_identity_s232d2_docker_smoke.json"
DEFAULT_RELEASE_GUARD = (
    REPORTS_ROOT
    / "weekly_cloudbase_ai_health_guard_20260602_20260602_154701"
    / "guard_release_with_s232d2_in_container_smoke_no_network.json"
)
DEFAULT_S232B = REPORTS_ROOT / "atlas_relation_identity_s232b_source_backed_prewrite_contract_20260602" / "atlas_relation_identity_s232b_source_backed_prewrite_contract.json"
DEFAULT_S232C = REPORTS_ROOT / "atlas_relation_identity_s232c_bounded_evidence_gate_20260602" / "atlas_relation_identity_s232c_bounded_evidence_gate.json"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3_collector_release_preflight_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3_COLLECTOR_RELEASE_PREFLIGHT_20260602.md"

STORY_ID = "S232D-3P"
SCHEMA_VERSION = "atlas_relation_identity_s232d3_collector_release_preflight.v1"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
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
    except (ValueError, OSError):
        return path.as_posix()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def check_rows(guard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = guard.get("checks")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("name"):
            result[str(row["name"])] = row
    return result


def ok_check(checks: dict[str, dict[str, Any]], name: str) -> bool:
    return bool(checks.get(name, {}).get("ok"))


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
    return os.environ.get("ATLAS_S232D3_CONTROLLER_RELEASE", "").strip()


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    s232d2 = read_json(args.s232d2)
    guard = read_json(args.release_guard) if args.release_guard.exists() else {}
    s232b = read_json(args.s232b) if args.s232b.exists() else {}
    s232c = read_json(args.s232c) if args.s232c.exists() else {}
    checks = check_rows(guard)

    release_token = extract_release_token(args)
    controller_release_present = release_token.startswith("CTRL-S232D-3-")
    s232d2_green = all(
        [
            s232d2.get("decision") == "atlas_relation_identity_s232d2_docker_read_only_smoke_passed",
            s232d2.get("mode") == "in-container",
            as_bool(s232d2.get("inside_container")),
            as_bool(s232d2.get("docker_started")),
            as_bool(s232d2.get("container_smoke_executed")),
            as_int((s232d2.get("counts") or {}).get("failed_check_count")) == 0,
            not s232d2.get("leak_findings"),
            as_int(((s232d2.get("container_checks") or {}).get("network") or {}).get("non_loopback_route_count")) == 0,
            not ((s232d2.get("container_checks") or {}).get("forbidden_mount_hits") or []),
        ]
    )
    s232d2_guard_consumed = ok_check(checks, "s232d2_docker_smoke_json_exists") and ok_check(
        checks, "s232d2_in_container_artifact_green"
    )
    no_forbidden_execution = not any(
        as_bool(s232d2.get(flag))
        for flag in (
            "collector_executed",
            "collector_execution_allowed_now",
            "network_fetch_executed",
            "db_write_executed",
            "db1_mutation",
            "db2_mutation",
            "db3_mutation",
            "db2_projection_allowed_now",
            "db3_write_allowed_now",
            "deploy_upload_release_allowed_now",
            "cookie_or_token_read",
            "raw_source_url_emitted",
            "private_path_emitted",
        )
    )
    allowlist_ready = (
        as_int((s232d2.get("counts") or {}).get("work_order_count")) == 25
        and as_int((s232d2.get("counts") or {}).get("allowlist_count")) == 25
        and as_int((s232d2.get("counts") or {}).get("s232c_queue_count")) == 25
    )
    collector_preconditions_ready_except_release = all(
        [s232d2_green, s232d2_guard_consumed, no_forbidden_execution, allowlist_ready]
    )

    blocked_reasons: list[dict[str, Any]] = []
    if not controller_release_present:
        blocked_reasons.append(
            {
                "reason": "s232d3_controller_release_missing",
                "effect": "collector_canary_must_not_start",
                "severity": "hold",
            }
        )
    if not collector_preconditions_ready_except_release:
        blocked_reasons.append(
            {
                "reason": "s232d3_preconditions_not_green",
                "effect": "collector_canary_must_not_start",
                "severity": "block",
            }
        )

    release_guard_failed = [
        {"name": str(row.get("name")), "detail": str(row.get("detail") or "")[:240]}
        for row in (guard.get("checks") or [])
        if isinstance(row, dict) and not bool(row.get("ok"))
    ]

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": (
            "atlas_relation_identity_s232d3_collector_release_preflight_ready_waiting_execute_release_report_only"
            if controller_release_present and collector_preconditions_ready_except_release
            else "atlas_relation_identity_s232d3_collector_release_preflight_blocked_no_controller_release_report_only"
        ),
        "inputs": {
            "s232d2_smoke": rel(args.s232d2),
            "release_guard": rel(args.release_guard) if args.release_guard.exists() else "",
            "s232b_prewrite_contract": rel(args.s232b) if args.s232b.exists() else "",
            "s232c_gate": rel(args.s232c) if args.s232c.exists() else "",
        },
        "readiness": {
            "controller_release_present": controller_release_present,
            "controller_release_id_present_but_redacted": bool(release_token),
            "s232d2_smoke_green": s232d2_green,
            "s232d2_release_guard_consumed": s232d2_guard_consumed,
            "allowlist_ready": allowlist_ready,
            "no_forbidden_execution": no_forbidden_execution,
            "collector_preconditions_ready_except_release": collector_preconditions_ready_except_release,
        },
        "source_state": {
            "db3_same_normalized_name_multi_id": as_int(
                ((s232b.get("source_state") or {}).get("db3_same_normalized_name_multi_id"))
            ),
            "s232b_evidence_gap_count": as_int(s232b.get("evidence_gap_count")),
            "s232b_candidate_subset_count": as_int(s232b.get("candidate_subset_count")),
            "s232c_selected_work_order_count": as_int(s232c.get("selected_work_order_count")),
            "release_guard_ok": bool(guard.get("ok")),
            "release_guard_failed_check_count": len(release_guard_failed),
        },
        "collector_canary_contract": {
            "requires_new_s232d3_controller_release": True,
            "input_allowlist": "tools/stage7_rewrite/reports/atlas_relation_identity_s232d0_docker_worker_contract_20260602/s232d0_work_order_allowlist.jsonl",
            "work_order_count": as_int((s232d2.get("counts") or {}).get("work_order_count")),
            "allowed_runtime": "docker_container_worker_only",
            "allowed_output": "report_local_source_provider_evidence_only",
            "forbidden": [
                "collector start without new S232D-3 release",
                "cookie/token/.env/browser-profile read",
                "network fetch outside selected allowlist",
                "DB1/DB2/DB3 mutation",
                "DB2 projection",
                "deploy/sync/upload/review/release",
                "raw source URL/private path/secret output",
            ],
        },
        "blocked_reasons": blocked_reasons,
        "release_guard_failed_checks": release_guard_failed,
        "collector_execution_allowed_now": False,
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
        "raw_source_url_emitted": False,
        "private_path_emitted": False,
        "next_gate": "Wait for a new S232D-3 controller release before any no-cookie collector canary; DB writes/projection/release remain separately blocked by S232B/S232A/S146 and release-guard gates.",
        "production_state_difference": "report-only S232D-3 release preflight; no Docker start, collector, network fetch, DB mutation, DB2 projection, deploy/sync/upload/review/release, or secret read",
    }
    report["leak_findings"] = leak_scan(report)
    if report["leak_findings"]:
        report["decision"] = "atlas_relation_identity_s232d3_collector_release_preflight_blocked_leak_findings_report_only"
        report["readiness"]["collector_preconditions_ready_except_release"] = False
    return report


def render_markdown(report: dict[str, Any]) -> str:
    readiness = report["readiness"]
    source = report["source_state"]
    return "\n".join(
        [
            "# S232D-3 Collector Release Preflight",
            "",
            f"- Decision: `{report['decision']}`",
            f"- Controller release present: `{readiness['controller_release_present']}`",
            f"- S232D-2 smoke green: `{readiness['s232d2_smoke_green']}`",
            f"- S232D-2 consumed by release guard: `{readiness['s232d2_release_guard_consumed']}`",
            f"- Allowlist ready: `{readiness['allowlist_ready']}`",
            f"- Preconditions ready except release: `{readiness['collector_preconditions_ready_except_release']}`",
            f"- DB3 same-normalized blocker: `{source['db3_same_normalized_name_multi_id']}`",
            f"- S232B evidence gaps / candidate subset: `{source['s232b_evidence_gap_count']}` / `{source['s232b_candidate_subset_count']}`",
            f"- Release guard failed checks: `{source['release_guard_failed_check_count']}`",
            "",
            "## Boundary",
            "",
            "- Report-only. No Docker start, collector, network fetch, DB write, DB2 projection, deploy, sync, upload, review, or release.",
            "- S232D-3 collector canary still requires a new controller release.",
            "- DB writes/projection/release remain separate gates after evidence collection.",
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
    report = build_report(args)
    json_path = out_dir / "atlas_relation_identity_s232d3_collector_release_preflight.json"
    markdown_path = out_dir / "atlas_relation_identity_s232d3_collector_release_preflight.md"
    report["output_dir"] = rel(out_dir)
    report["artifacts"] = {
        "json": rel(json_path),
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
    parser = argparse.ArgumentParser(description="Build S232D-3 collector release preflight")
    parser.add_argument("--s232d2", type=Path, default=DEFAULT_S232D2)
    parser.add_argument("--release-guard", type=Path, default=DEFAULT_RELEASE_GUARD)
    parser.add_argument("--s232b", type=Path, default=DEFAULT_S232B)
    parser.add_argument("--s232c", type=Path, default=DEFAULT_S232C)
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
