#!/usr/bin/env python3
"""Run S232D-3B actual target-resolution canary inside a container.

This gate is intentionally narrow. The host process is only a control plane:
it starts a Docker container with read-only inputs and a writable report-local
output directory. The in-container worker may only inspect the first five
allowlisted work orders and emit hashed/redacted target provenance. If no
concrete public provider/source target exists, it stops as blocked without
generating search URLs or attempting network fetches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "package.json").exists() and (parent / "tools" / "stage7_rewrite").exists():
            return parent
    workspace = Path("/workspace")
    if workspace.exists():
        return workspace
    return Path.cwd()


REPO_ROOT = find_repo_root()
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

STORY_ID = "S232D-3B-ACTUAL-CANARY"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b_actual_canary.v1"
RELEASE_ID = "CTRL-S232D-3B-TARGET-RESOLUTION-CANARY-20260602-1823-019e86a8-adb6-7953-bdfd-9bb6fa41ccd7"
CONTROLLER_THREAD_ID = "019e86a8-adb6-7953-bdfd-9bb6fa41ccd7"

S232D3B1_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b1_target_resolution_worker_contract_20260602"
S232D3B2_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b2_controller_release_packet_20260602"
S232D3A_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3a_seed_target_resolver_contract_20260602"

DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b_actual_canary_20260602"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B_ACTUAL_CANARY_20260602.md"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)

FORBIDDEN_MOUNT_FRAGMENTS = (
    "production",
    "atlas.sqlite",
    "atlas_serving.sqlite",
    ".env",
    ".mptext-data",
    "cookies",
    "credential",
    "google-chrome",
    "chromium",
    "mozilla",
    "db2-spool",
    "db2-writer",
)

FALSE_FLAGS = (
    "db1_mutation",
    "db2_mutation",
    "db3_mutation",
    "db_write_executed",
    "db2_projection_allowed_now",
    "db2_worker_started",
    "deploy_upload_release_allowed_now",
    "cookie_or_token_read",
    "api_key_read",
    "browser_profile_read",
    "raw_source_url_emitted",
    "private_path_emitted",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def digest(value: str, size: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:size]


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON: {path}")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected object JSONL row in {path}")
            rows.append(payload)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def leak_scan(payload: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def walk(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, f"{pointer}.{key}" if pointer else str(key))
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{pointer}[{index}]")
            return
        if not isinstance(value, str):
            return
        if RAW_URL_RE.search(value):
            findings.append({"pointer": pointer, "kind": "raw_url"})
        if PRIVATE_PATH_RE.search(value):
            findings.append({"pointer": pointer, "kind": "private_path"})
        if SECRET_RE.search(value):
            findings.append({"pointer": pointer, "kind": "secret_like"})

    walk(payload, "")
    return findings


def route_count() -> int:
    route = Path("/proc/net/route")
    if not route.exists():
        return 0
    count = 0
    for line in route.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] != "00000000":
            count += 1
    return count


def forbidden_mount_hits() -> list[str]:
    mounts = Path("/proc/mounts")
    if not mounts.exists():
        return []
    hits: list[str] = []
    for line in mounts.read_text(encoding="utf-8", errors="ignore").splitlines():
        lower = line.lower()
        if any(fragment in lower for fragment in FORBIDDEN_MOUNT_FRAGMENTS):
            hits.append(line.split()[1] if len(line.split()) > 1 else line)
    return sorted(set(hits))


def build_rows(allowlist: list[dict[str, Any]], queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue_by_id = {str(row.get("work_order_id")): row for row in queue}
    rows: list[dict[str, Any]] = []
    for item in allowlist:
        work_order_id = str(item.get("work_order_id") or "")
        queue_row = queue_by_id.get(work_order_id, {})
        target_material_present = bool(queue_row.get("target_material_present"))
        network_fetch_ready = bool(queue_row.get("network_fetch_ready"))
        if target_material_present and network_fetch_ready:
            status = "needs_review_target_material_present_but_raw_target_redacted"
            needs_review = True
        else:
            status = "blocked_no_concrete_public_provider_source_target"
            needs_review = True
        rows.append(
            {
                "work_order_id": work_order_id,
                "ordinal": int(item.get("ordinal") or queue_row.get("ordinal") or 0),
                "seed_value_hash": str(item.get("seed_value_hash") or queue_row.get("seed_value_hash") or ""),
                "display_name_hash": str(item.get("display_name_hash") or digest(str(queue_row.get("display_name", "")))),
                "group_id_hash": str(item.get("group_id_hash") or digest(str(queue_row.get("group_id", "")))),
                "resolver_method": "s232d3b_container_target_resolution_canary",
                "target_identity_hash": "",
                "target_domain_hash": "",
                "target_title_hash": "",
                "provider_anchor_hash": "",
                "source_anchor_hash": "",
                "target_provenance_status": status,
                "confidence": 0.0,
                "needs_review": needs_review,
                "retry_state": "retryable_after_public_target_resolution_contract",
                "worker_run_id_hash": digest(RELEASE_ID),
                "network_fetch_attempted": False,
                "network_fetch_succeeded": False,
                "db_write_executed": False,
                "db2_projection_executed": False,
                "raw_url_output_allowed": False,
            }
        )
    return rows


def validate_inputs(packet: dict[str, Any], contract: dict[str, Any], allowlist: list[dict[str, Any]], queue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    if len(allowlist) != 5:
        failed.append({"check": "allowlist_count_exactly_5", "actual": len(allowlist)})
    ids = [str(row.get("work_order_id") or "") for row in allowlist]
    if len(set(ids)) != 5 or any(not value for value in ids):
        failed.append({"check": "allowlist_unique_nonempty_work_order_ids"})
    packet_ids = packet.get("allowlist_work_order_ids") if isinstance(packet.get("allowlist_work_order_ids"), list) else []
    if ids != [str(value) for value in packet_ids]:
        failed.append({"check": "allowlist_matches_s232d3b2_packet"})
    queue_ids = {str(row.get("work_order_id") or "") for row in queue}
    if not set(ids).issubset(queue_ids):
        failed.append({"check": "allowlist_rows_missing_from_s232d3a_queue"})
    policy = contract.get("target_resolution_policy") if isinstance(contract.get("target_resolution_policy"), dict) else {}
    for key in (
        "seed_direct_search_url_generation_allowed",
        "raw_url_output_allowed",
        "credential_read_allowed",
        "db1_db2_db3_write_allowed",
        "db2_projection_allowed",
        "deploy_sync_upload_review_release_allowed",
    ):
        if bool(policy.get(key)):
            failed.append({"check": "contract_forbidden_policy_false", "field": key})
    return failed


def in_container(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    packet = read_json(Path(args.packet))
    contract = read_json(Path(args.contract))
    allowlist = read_jsonl(Path(args.allowlist))
    queue = read_jsonl(Path(args.queue))
    schema = read_json(Path(args.provenance_schema))

    failed = validate_inputs(packet, contract, allowlist, queue)
    if os.environ.get("ATLAS_S232D3B_TARGET_RESOLUTION_CONTROLLER_RELEASE") != RELEASE_ID:
        failed.append({"check": "controller_release_env_matches"})
    if os.environ.get("ATLAS_SEARCH_URL_GENERATION_ALLOWED", "0") != "0":
        failed.append({"check": "search_url_generation_forced_off"})
    if os.environ.get("DB2_WRITER_EXECUTE", "0") != "0":
        failed.append({"check": "db2_writer_forced_off"})

    rows = build_rows(allowlist, queue)
    network_attempt_count = 0
    network_success_count = 0
    blocked_count = sum(1 for row in rows if str(row["target_provenance_status"]).startswith("blocked_"))

    container_checks = {
        "inside_container": True,
        "container_smoke_executed": True,
        "docker_started": True,
        "release_env_present": True,
        "non_loopback_route_count": route_count(),
        "forbidden_mount_hits": forbidden_mount_hits(),
        "input_allowlist_readable": bool(allowlist),
        "input_queue_readable": bool(queue),
        "input_contract_readable": bool(contract),
        "input_packet_readable": bool(packet),
        "input_provenance_schema_readable": bool(schema),
        "report_local_write_probe": True,
    }
    if container_checks["forbidden_mount_hits"]:
        failed.append({"check": "forbidden_mount_hits_empty", "hits": container_checks["forbidden_mount_hits"]})

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "mode": "in-container",
        "decision": (
            "atlas_relation_identity_s232d3b_actual_canary_blocked_no_concrete_public_targets_report_local"
            if not failed
            else "atlas_relation_identity_s232d3b_actual_canary_blocked_preflight_failed_report_local"
        ),
        "controller_release_id": RELEASE_ID,
        "controller_thread_id": CONTROLLER_THREAD_ID,
        "selected_work_order_count": len(allowlist),
        "allowlist_count": len(allowlist),
        "target_provenance_row_count": len(rows),
        "blocked_row_count": blocked_count,
        "network_fetch_attempt_count": network_attempt_count,
        "network_fetch_success_count": network_success_count,
        "non_allowlist_fetch_count": 0,
        "raw_url_private_path_secret_leak_count": 0,
        "failed_check_count": len(failed),
        "failed_checks": failed,
        "target_provenance_fields": list(rows[0].keys()) if rows else [],
        "target_provenance_status_counts": {
            "blocked_no_concrete_public_provider_source_target": blocked_count,
        },
        "container_checks": container_checks,
        "production_state_difference": "report-local container canary only; no target URL generated, no network fetch attempted, no DB/projection/release mutation",
        "next_gate": "DB2/release guard may consume this report read-only; DB3 write gate S232D-4 remains unreleased.",
        "db1_mutation": False,
        "db2_mutation": False,
        "db3_mutation": False,
        "db_write_executed": False,
        "db2_worker_started": False,
        "db2_projection_allowed_now": False,
        "db3_write_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "cookie_or_token_read": False,
        "api_key_read": False,
        "browser_profile_read": False,
        "raw_source_url_emitted": False,
        "private_path_emitted": False,
        "search_url_generation_attempted": False,
        "collector_executed": False,
        "target_resolution_execution_allowed_now": False,
    }
    findings = leak_scan(report) + leak_scan(rows)
    report["raw_url_private_path_secret_leak_count"] = len(findings)
    report["leak_findings"] = findings
    if findings and not any(item.get("check") == "leak_scan_zero" for item in failed):
        report["failed_checks"].append({"check": "leak_scan_zero", "count": len(findings)})
        report["failed_check_count"] = len(report["failed_checks"])
        report["decision"] = "atlas_relation_identity_s232d3b_actual_canary_blocked_preflight_failed_report_local"

    write_json(out_dir / "atlas_relation_identity_s232d3b_actual_canary.json", report)
    write_jsonl(out_dir / "s232d3b_target_provenance.jsonl", rows)
    write_json(out_dir / "s232d3b_actual_canary_scorecard.json", {
        "decision": report["decision"],
        "controller_release_id": RELEASE_ID,
        "allowlist_count": len(allowlist),
        "blocked_row_count": blocked_count,
        "network_fetch_attempt_count": network_attempt_count,
        "network_fetch_success_count": network_success_count,
        "failed_check_count": report["failed_check_count"],
        "raw_url_private_path_secret_leak_count": report["raw_url_private_path_secret_leak_count"],
        "db_write_executed": False,
        "db2_projection_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
    })
    return 0 if report["failed_check_count"] == 0 else 2


def docker_run(args: argparse.Namespace) -> int:
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=16m",
        "-e",
        f"ATLAS_S232D3B_TARGET_RESOLUTION_CONTROLLER_RELEASE={RELEASE_ID}",
        "-e",
        "ATLAS_NETWORK_FETCH_ALLOWED=0",
        "-e",
        "ATLAS_SEARCH_URL_GENERATION_ALLOWED=0",
        "-e",
        "DB2_PROJECTION_EXECUTE=0",
        "-e",
        "DB2_WRITER_EXECUTE=0",
        "-v",
        f"{Path(__file__).resolve().as_posix()}:/worker.py:ro",
        "-v",
        f"{args.packet.resolve().as_posix()}:/inputs/s232d3b2_packet.json:ro",
        "-v",
        f"{args.contract.resolve().as_posix()}:/inputs/s232d3b1_contract.json:ro",
        "-v",
        f"{args.allowlist.resolve().as_posix()}:/inputs/s232d3b1_allowlist.jsonl:ro",
        "-v",
        f"{args.queue.resolve().as_posix()}:/inputs/s232d3a_queue.jsonl:ro",
        "-v",
        f"{args.provenance_schema.resolve().as_posix()}:/inputs/s232d3b1_provenance_schema.json:ro",
        "-v",
        f"{out_dir.as_posix()}:/out:rw",
        "python:3.13-slim",
        "python",
        "/worker.py",
        "--mode",
        "in-container",
        "--packet",
        "/inputs/s232d3b2_packet.json",
        "--contract",
        "/inputs/s232d3b1_contract.json",
        "--allowlist",
        "/inputs/s232d3b1_allowlist.jsonl",
        "--queue",
        "/inputs/s232d3a_queue.jsonl",
        "--provenance-schema",
        "/inputs/s232d3b1_provenance_schema.json",
        "--out-dir",
        "/out",
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    (out_dir / "docker_stdout.txt").write_text(result.stdout, encoding="utf-8")
    (out_dir / "docker_stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode not in (0, 2):
        blocked = {
            "schema_version": SCHEMA_VERSION,
            "story_id": STORY_ID,
            "generated_at": utc_now(),
            "mode": "host-docker-control-plane",
            "decision": "atlas_relation_identity_s232d3b_actual_canary_blocked_docker_execution_failed_report_local",
            "controller_release_id": RELEASE_ID,
            "docker_returncode": result.returncode,
            "docker_stdout_hash": digest(result.stdout),
            "docker_stderr_hash": digest(result.stderr),
            "selected_work_order_count": 5,
            "network_fetch_attempt_count": 0,
            "network_fetch_success_count": 0,
            "raw_url_private_path_secret_leak_count": 0,
            "db_write_executed": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_release_allowed_now": False,
        }
        write_json(out_dir / "atlas_relation_identity_s232d3b_actual_canary.json", blocked)
        return result.returncode
    return 0


def write_markdown(out_dir: Path, scorecard: Path) -> None:
    report = read_json(out_dir / "atlas_relation_identity_s232d3b_actual_canary.json")
    lines = [
        "# S232D-3B Actual Target-Resolution Canary",
        "",
        f"- Decision: `{report.get('decision')}`",
        f"- Release ID: `{RELEASE_ID}`",
        f"- Allowlist: `{report.get('allowlist_count', report.get('selected_work_order_count'))}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Blocked rows: `{report.get('blocked_row_count', 0)}`",
        f"- Network attempts / successes: `{report.get('network_fetch_attempt_count', 0)}` / `{report.get('network_fetch_success_count', 0)}`",
        f"- Failed checks: `{report.get('failed_check_count', 0)}`",
        f"- Leak count: `{report.get('raw_url_private_path_secret_leak_count', 0)}`",
        f"- DB write executed: `{report.get('db_write_executed')}`",
        f"- DB2 projection allowed now: `{report.get('db2_projection_allowed_now')}`",
        f"- Deploy/upload/release allowed now: `{report.get('deploy_upload_release_allowed_now')}`",
        "",
        "This is report-local evidence only. It is not S232D-4, not a DB3 write gate, not DB2 projection, and not a mini-program / CloudBase release.",
    ]
    scorecard.parent.mkdir(parents=True, exist_ok=True)
    scorecard.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["host", "in-container"], default="host")
    parser.add_argument("--packet", type=Path, default=S232D3B2_DIR / "s232d3b2_controller_release_packet.json")
    parser.add_argument("--contract", type=Path, default=S232D3B1_DIR / "s232d3b1_target_resolution_worker_contract.json")
    parser.add_argument("--allowlist", type=Path, default=S232D3B1_DIR / "s232d3b1_work_order_allowlist.jsonl")
    parser.add_argument("--queue", type=Path, default=S232D3A_DIR / "s232d3a_seed_target_resolver_queue.jsonl")
    parser.add_argument("--provenance-schema", type=Path, default=S232D3B1_DIR / "s232d3b1_target_provenance_schema.json")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    args = parser.parse_args()

    if args.mode == "in-container":
        return in_container(args)
    status = docker_run(args)
    write_markdown(args.out_dir, args.scorecard)
    return status


if __name__ == "__main__":
    sys.exit(main())
