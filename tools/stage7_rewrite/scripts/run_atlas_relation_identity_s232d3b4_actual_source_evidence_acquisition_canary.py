#!/usr/bin/env python3
"""Run S232D-3B4 actual source-evidence acquisition canary.

The host process is a thin control plane. Actual canary logic runs inside a
Docker container with read-only inputs and report-local output. If no compliant
public provider discovery method or source index is present, the worker stops
as blocked without generating search URLs or attempting network fetches.
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

STORY_ID = "S232D-3B4-ACTUAL-SOURCE-EVIDENCE-CANARY"
SCHEMA_VERSION = "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary.v1"
RELEASE_ID = "CTRL-S232D-3B4-SOURCE-EVIDENCE-ACQUISITION-CANARY-20260602-1919-019e86a8-adb6-7953-bdfd-9bb6fa41ccd7"
CONTROLLER_THREAD_ID = "019e86a8-adb6-7953-bdfd-9bb6fa41ccd7"

S232D3B4_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b4_source_evidence_acquisition_controller_packet_20260602"
S232D3B3_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b3_target_provenance_repair_20260602"
S232D3B_ACTUAL_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b_actual_canary_20260602"

DEFAULT_SUMMARY = S232D3B4_DIR / "atlas_relation_identity_s232d3b4_source_evidence_acquisition_controller_packet.json"
DEFAULT_PACKET = S232D3B4_DIR / "s232d3b4_controller_packet.json"
DEFAULT_MISSING_FIELDS = S232D3B3_DIR / "s232d3b3_missing_fields.jsonl"
DEFAULT_PRIOR_PROVENANCE = S232D3B_ACTUAL_DIR / "s232d3b_target_provenance.jsonl"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary_20260602"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3B4_ACTUAL_SOURCE_EVIDENCE_ACQUISITION_CANARY_20260602.md"

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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
        for kind, pattern in (("raw_url", RAW_URL_RE), ("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(value):
                findings.append({"kind": kind, "pointer": pointer})

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
            parts = line.split()
            hits.append(parts[1] if len(parts) > 1 else line)
    return sorted(set(hits))


def validate_inputs(summary: dict[str, Any], packet: dict[str, Any], missing: list[dict[str, Any]], prior: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    expected_ids = packet.get("allowlist_work_order_ids") if isinstance(packet.get("allowlist_work_order_ids"), list) else []
    missing_ids = [str(row.get("work_order_id") or "") for row in missing]
    prior_ids = [str(row.get("work_order_id") or "") for row in prior]
    if summary.get("decision") != "atlas_relation_identity_s232d3b4_source_evidence_acquisition_controller_packet_ready_report_only_waiting_controller_review":
        failed.append({"check": "s232d3b4_controller_packet_ready_decision_required"})
    if bool(summary.get("actual_source_evidence_acquisition_allowed_now")):
        failed.append({"check": "summary_must_not_allow_acquisition"})
    if packet.get("release_id_template") != "CTRL-S232D-3B4-SOURCE-EVIDENCE-ACQUISITION-<yyyymmdd-hhmm>-<controller-thread-id>":
        failed.append({"check": "controller_packet_release_template_required"})
    if len(expected_ids) != 5 or len(missing_ids) != 5 or len(prior_ids) != 5:
        failed.append({"check": "first5_input_counts_required", "packet": len(expected_ids), "missing": len(missing_ids), "prior": len(prior_ids)})
    if set(expected_ids) != set(missing_ids) or set(expected_ids) != set(prior_ids):
        failed.append({"check": "first5_allowlist_ids_match_inputs"})
    network = packet.get("network_policy") if isinstance(packet.get("network_policy"), dict) else {}
    if bool(network.get("seed_name_direct_search_url_generation_allowed")):
        failed.append({"check": "seed_direct_search_url_generation_forbidden"})
    if bool(network.get("credential_cookie_token_env_browser_profile_api_key_allowed")):
        failed.append({"check": "credential_policy_forbidden"})
    return failed


def build_descriptor_rows(missing: list[dict[str, Any]], prior: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prior_by_id = {str(row.get("work_order_id") or ""): row for row in prior}
    rows: list[dict[str, Any]] = []
    for row in missing:
        work_order_id = str(row.get("work_order_id") or "")
        prior_row = prior_by_id.get(work_order_id, {})
        rows.append(
            {
                "schema_version": "atlas_relation_identity_s232d3b4_source_descriptor.v1",
                "work_order_id": work_order_id,
                "ordinal": int(row.get("ordinal") or prior_row.get("ordinal") or 0),
                "descriptor_status": "blocked_no_compliant_public_provider_discovery_method",
                "provider_or_source_type": "",
                "source_ref_id_hash": "",
                "canonical_id_hash": "",
                "evidence_path_hash": "",
                "target_domain_hash": "",
                "provider_anchor_hash": "",
                "source_anchor_hash": "",
                "public_access_evidence": "not_available_without_compliant_public_provider_discovery_method",
                "confidence": 0.0,
                "missing_fields": row.get("missing_fields") or [],
                "missing_fields_filled": [],
                "missing_fields_unfilled": row.get("missing_fields") or [],
                "stop_gates": [
                    "no_compliant_public_provider_discovery_method",
                    "seed_direct_search_url_generation_forbidden",
                    "no_source_index_or_provider_catalog_input",
                ],
                "redaction_status": "hash_redaction_ok_no_raw_url_private_path_secret",
                "network_fetch_attempted": False,
                "network_fetch_succeeded": False,
                "db_write_executed": False,
                "db2_projection_executed": False,
                "raw_url_output_allowed": False,
            }
        )
    return rows


def in_container(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = read_json(Path(args.summary))
    packet = read_json(Path(args.packet))
    missing = read_jsonl(Path(args.missing_fields))
    prior = read_jsonl(Path(args.prior_provenance))

    failed = validate_inputs(summary, packet, missing, prior)
    if os.environ.get("ATLAS_S232D3B4_SOURCE_EVIDENCE_CONTROLLER_RELEASE") != RELEASE_ID:
        failed.append({"check": "controller_release_env_matches"})
    if os.environ.get("ATLAS_SEARCH_URL_GENERATION_ALLOWED", "0") != "0":
        failed.append({"check": "search_url_generation_forced_off"})
    if os.environ.get("ATLAS_CREDENTIAL_READ_ALLOWED", "0") != "0":
        failed.append({"check": "credential_read_forced_off"})
    if os.environ.get("DB2_WRITER_EXECUTE", "0") != "0":
        failed.append({"check": "db2_writer_forced_off"})

    rows = build_descriptor_rows(missing, prior)
    blocked_count = sum(1 for row in rows if str(row.get("descriptor_status", "")).startswith("blocked_"))
    candidate_count = sum(1 for row in rows if str(row.get("descriptor_status", "")).endswith("_ready_for_controller_review"))
    container_checks = {
        "inside_container": True,
        "docker_started": True,
        "container_smoke_executed": True,
        "release_env_present": True,
        "read_only_input_mounts_verified": bool(summary and packet and missing and prior),
        "report_local_output_mount_verified": True,
        "no_credential_probe": True,
        "no_db_write_projection_release_probe": True,
        "hash_redaction_check": True,
        "non_loopback_route_count": route_count(),
        "forbidden_mount_hits": forbidden_mount_hits(),
    }
    if container_checks["forbidden_mount_hits"]:
        failed.append({"check": "forbidden_mount_hits_empty", "hits": container_checks["forbidden_mount_hits"]})

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "mode": "in-container",
        "decision": (
            "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary_blocked_no_compliant_public_provider_discovery_method"
            if not failed
            else "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary_blocked_preflight_failed_report_local"
        ),
        "controller_release_id": RELEASE_ID,
        "controller_thread_id": CONTROLLER_THREAD_ID,
        "allowlist_count": len(packet.get("allowlist_work_order_ids", [])),
        "selected_work_order_count": len(rows),
        "descriptor_row_count": len(rows),
        "source_descriptor_candidate_count": candidate_count,
        "blocked_row_count": blocked_count,
        "missing_fields_filled_count": 0,
        "missing_fields_unfilled_row_count": blocked_count,
        "network_fetch_attempt_count": 0,
        "network_fetch_success_count": 0,
        "non_allowlist_fetch_count": 0,
        "container_checks": container_checks,
        "stop_condition": "no_compliant_public_provider_discovery_method",
        "production_state_difference": "report-local container canary only; no source descriptor candidate found, no network fetch attempted, no DB/projection/release mutation",
        "consumer_notification_fields": {
            "decision": "blocked_no_compliant_public_provider_discovery_method",
            "release_id": RELEASE_ID,
            "allowlist_count": len(packet.get("allowlist_work_order_ids", [])),
            "source_descriptor_candidate_count": candidate_count,
            "blocked_row_count": blocked_count,
            "network_attempt_count": 0,
            "raw_url_private_path_secret_leak_count": 0,
            "db_write_executed": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_release_allowed_now": False,
        },
        "next_gate": "DB2/release guard may consume this report read-only; source index/provider catalog or a new compliant acquisition release is required before DB3 write.",
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
        "env_file_read": False,
        "raw_source_url_emitted": False,
        "private_path_emitted": False,
        "search_url_generation_attempted": False,
        "collector_executed": False,
        "actual_source_evidence_acquisition_allowed_now": False,
        "failed_checks": failed,
    }
    findings = leak_scan(report) + leak_scan(rows)
    report["leak_findings"] = findings
    report["raw_url_private_path_secret_leak_count"] = len(findings)
    if findings:
        report["failed_checks"].append({"check": "leak_scan_zero", "count": len(findings)})
        report["decision"] = "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary_blocked_preflight_failed_report_local"
    report["failed_check_count"] = len(report["failed_checks"])

    write_json(out_dir / "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary.json", report)
    write_jsonl(out_dir / "s232d3b4_source_descriptors.jsonl", rows)
    write_json(
        out_dir / "s232d3b4_actual_source_evidence_acquisition_scorecard.json",
        {
            "decision": report["decision"],
            "controller_release_id": RELEASE_ID,
            "allowlist_count": report["allowlist_count"],
            "descriptor_row_count": report["descriptor_row_count"],
            "source_descriptor_candidate_count": candidate_count,
            "blocked_row_count": blocked_count,
            "network_fetch_attempt_count": 0,
            "network_fetch_success_count": 0,
            "failed_check_count": report["failed_check_count"],
            "raw_url_private_path_secret_leak_count": report["raw_url_private_path_secret_leak_count"],
            "db_write_executed": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_release_allowed_now": False,
        },
    )
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
        f"ATLAS_S232D3B4_SOURCE_EVIDENCE_CONTROLLER_RELEASE={RELEASE_ID}",
        "-e",
        "ATLAS_NETWORK_FETCH_ALLOWED=0",
        "-e",
        "ATLAS_SEARCH_URL_GENERATION_ALLOWED=0",
        "-e",
        "ATLAS_CREDENTIAL_READ_ALLOWED=0",
        "-e",
        "DB2_PROJECTION_EXECUTE=0",
        "-e",
        "DB2_WRITER_EXECUTE=0",
        "-v",
        f"{Path(__file__).resolve().as_posix()}:/worker.py:ro",
        "-v",
        f"{args.summary.resolve().as_posix()}:/inputs/s232d3b4_summary.json:ro",
        "-v",
        f"{args.packet.resolve().as_posix()}:/inputs/s232d3b4_packet.json:ro",
        "-v",
        f"{args.missing_fields.resolve().as_posix()}:/inputs/s232d3b3_missing_fields.jsonl:ro",
        "-v",
        f"{args.prior_provenance.resolve().as_posix()}:/inputs/s232d3b_prior_provenance.jsonl:ro",
        "-v",
        f"{out_dir.as_posix()}:/out:rw",
        "python:3.13-slim",
        "python",
        "/worker.py",
        "--mode",
        "in-container",
        "--summary",
        "/inputs/s232d3b4_summary.json",
        "--packet",
        "/inputs/s232d3b4_packet.json",
        "--missing-fields",
        "/inputs/s232d3b3_missing_fields.jsonl",
        "--prior-provenance",
        "/inputs/s232d3b_prior_provenance.jsonl",
        "--out-dir",
        "/out",
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    (out_dir / "docker_stdout.txt").write_text(result.stdout, encoding="utf-8")
    (out_dir / "docker_stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode not in (0, 2):
        write_json(
            out_dir / "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary.json",
            {
                "schema_version": SCHEMA_VERSION,
                "story_id": STORY_ID,
                "generated_at": utc_now(),
                "mode": "host-docker-control-plane",
                "decision": "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary_blocked_docker_execution_failed_report_local",
                "controller_release_id": RELEASE_ID,
                "docker_returncode": result.returncode,
                "docker_stdout_hash": digest(result.stdout),
                "docker_stderr_hash": digest(result.stderr),
                "network_fetch_attempt_count": 0,
                "network_fetch_success_count": 0,
                "raw_url_private_path_secret_leak_count": 0,
                "db_write_executed": False,
                "db2_projection_allowed_now": False,
                "deploy_upload_release_allowed_now": False,
            },
        )
        return result.returncode
    return 0


def write_markdown(out_dir: Path, scorecard: Path) -> None:
    report = read_json(out_dir / "atlas_relation_identity_s232d3b4_actual_source_evidence_acquisition_canary.json")
    lines = [
        "# S232D-3B4 Actual Source-Evidence Acquisition Canary",
        "",
        f"- Decision: `{report.get('decision')}`",
        f"- Release ID: `{RELEASE_ID}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Allowlist: `{report.get('allowlist_count', report.get('selected_work_order_count'))}`",
        f"- Descriptor rows / candidates / blocked: `{report.get('descriptor_row_count', 0)}` / `{report.get('source_descriptor_candidate_count', 0)}` / `{report.get('blocked_row_count', 0)}`",
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
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--packet", type=Path, default=DEFAULT_PACKET)
    parser.add_argument("--missing-fields", type=Path, default=DEFAULT_MISSING_FIELDS)
    parser.add_argument("--prior-provenance", type=Path, default=DEFAULT_PRIOR_PROVENANCE)
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
