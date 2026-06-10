#!/usr/bin/env python3
"""Validate S232D-2 Docker/container read-only smoke.

S232D-2 is a container smoke only. It proves that the S232D-0 contract and
allowlist are readable in a bounded container and that only report-local output
is writable. It does not execute a collector, fetch network resources, read
secrets, mutate DB1/DB2/DB3, project DB2, deploy, upload, review, or release.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
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
CONTAINER_REPORTS_ROOT = Path("/db2-reports")

S232C_DIR_NAME = "atlas_relation_identity_s232c_bounded_evidence_gate_20260602"
S232D0_DIR_NAME = "atlas_relation_identity_s232d0_docker_worker_contract_20260602"
S232D1_DIR_NAME = "atlas_relation_identity_s232d1_controller_release_readiness_20260602"
S232D2_DIR_NAME = "atlas_relation_identity_s232d2_docker_smoke_20260602"

DEFAULT_OUT_DIR = REPORTS_ROOT / S232D2_DIR_NAME
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D2_DOCKER_SMOKE_20260602.md"

STORY_ID = "S232D-2"
SCHEMA_VERSION = "atlas_relation_identity_s232d2_docker_smoke.v1"
CONTROLLER_RELEASE_ID = "CTRL-S232D-2-DOCKER-SMOKE-20260602-1631"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=)",
    re.IGNORECASE,
)

FORBIDDEN_SUMMARY_FLAGS = (
    "collector_execution_allowed_now",
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

ALLOWLIST_FALSE_FLAGS = (
    "execution_allowed_now",
    "network_fetch_allowed_now",
    "writer_event_allowed_now",
    "db3_write_allowed_now",
    "db2_projection_allowed_now",
    "cookie_or_token_required",
    "raw_source_url_emitted",
)

FORBIDDEN_MOUNT_TARGETS = (
    "/db2-data",
    "/db2-spool",
    "/db2-cache",
    "/db2-avatar-output",
    "/db2-credentials",
    "/secrets",
    "/root/.config/google-chrome",
    "/root/.config/chromium",
    "/root/.mozilla",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def public_path(path: Path, mode: str) -> str:
    if mode == "in-container":
        return path.as_posix()
    try:
        return rel(path)
    except OSError:
        pass
    text = path.as_posix()
    if PRIVATE_PATH_RE.search(text):
        return f"external-fixture/{path.name}"
    return text


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
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                payload = json.loads(text)
                if isinstance(payload, dict):
                    rows.append(payload)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_roots(mode: str) -> tuple[Path, Path, Path, Path]:
    reports_root = CONTAINER_REPORTS_ROOT if mode == "in-container" else REPORTS_ROOT
    return (
        reports_root / S232C_DIR_NAME,
        reports_root / S232D0_DIR_NAME,
        reports_root / S232D1_DIR_NAME,
        reports_root / S232D2_DIR_NAME,
    )


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
        for kind, pattern in (
            ("raw_url", RAW_URL_RE),
            ("private_path", PRIVATE_PATH_RE),
            ("secret_like", SECRET_RE),
        ):
            if pattern.search(text):
                findings.append({"kind": kind, "path": path, "severity": "block"})

    walk(payload, "")
    return findings


def unescape_mount_path(path: str) -> str:
    return path.replace("\\040", " ")


def read_mounts() -> list[dict[str, Any]]:
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in mountinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        before, _, after = line.partition(" - ")
        fields = before.split()
        after_fields = after.split()
        if len(fields) < 6:
            continue
        rows.append(
            {
                "target": unescape_mount_path(fields[4]),
                "options": fields[5].split(","),
                "fstype": after_fields[0] if after_fields else "",
                "source": after_fields[1] if len(after_fields) > 1 else "",
            }
        )
    return rows


def mount_by_target(mounts: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    for row in mounts:
        if row.get("target") == target:
            return row
    return None


def route_table_summary() -> dict[str, Any]:
    route_file = Path("/proc/net/route")
    if not route_file.exists():
        return {"available": False, "non_loopback_route_count": 0}
    rows = route_file.read_text(encoding="utf-8", errors="replace").splitlines()[1:]
    non_loopback = [row for row in rows if row.split() and row.split()[0] != "lo"]
    return {"available": True, "non_loopback_route_count": len(non_loopback)}


def probe_report_local_write(out_dir: Path) -> dict[str, Any]:
    probe_dir = out_dir / "s232d2_report_local_write_probe"
    probe_path = probe_dir / "write_probe.json"
    probe_payload = {
        "schema_version": "atlas_relation_identity_s232d2_report_local_write_probe.v1",
        "story_id": STORY_ID,
        "probe_kind": "report_local_container_smoke_only",
        "collector_executed": False,
        "network_fetch_executed": False,
        "db_write_executed": False,
    }
    probe_dir.mkdir(parents=True, exist_ok=True)
    write_json(probe_path, probe_payload)
    return {
        "probe_dir_exists": probe_dir.exists(),
        "probe_file_exists": probe_path.exists(),
        "probe_file": f"{S232D2_DIR_NAME}/s232d2_report_local_write_probe/write_probe.json",
    }


def validate_mounts(mode: str, s232c_dir: Path, s232d0_dir: Path, s232d1_dir: Path, out_dir: Path) -> dict[str, Any]:
    mounts = read_mounts()
    input_targets = [str(s232c_dir), str(s232d0_dir), str(s232d1_dir)]
    mount_checks: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    if mode != "in-container":
        return {
            "mountinfo_available": bool(mounts),
            "input_mount_checks": [],
            "output_mount_check": {},
            "forbidden_mount_hits": [],
            "failed_mount_checks": [],
            "network": {"available": False, "non_loopback_route_count": 0},
        }

    for target in input_targets:
        row = mount_by_target(mounts, target)
        ok = bool(row) and "ro" in row.get("options", [])
        mount_checks.append({"target": target, "exists": Path(target).exists(), "mount_found": bool(row), "read_only": ok})
        if not ok:
            failed.append({"check": "input_mount_read_only", "target": target})

    out_mount = mount_by_target(mounts, str(out_dir))
    output_check = {
        "target": str(out_dir),
        "exists": out_dir.exists(),
        "mount_found": bool(out_mount),
        "writable_mount": bool(out_mount) and "rw" in out_mount.get("options", []),
    }
    if not output_check["writable_mount"]:
        failed.append({"check": "report_local_output_mount_writable", "target": str(out_dir)})

    forbidden_hits = []
    mounted_targets = {str(row.get("target")) for row in mounts}
    for target in FORBIDDEN_MOUNT_TARGETS:
        if target in mounted_targets:
            forbidden_hits.append({"target": target, "severity": "block"})
    failed.extend({"check": "forbidden_mount_absent", **hit} for hit in forbidden_hits)

    network = route_table_summary()
    if as_int(network.get("non_loopback_route_count")) != 0:
        failed.append({"check": "network_disabled_non_loopback_routes_zero", "value": network})

    return {
        "mountinfo_available": bool(mounts),
        "input_mount_checks": mount_checks,
        "output_mount_check": output_check,
        "forbidden_mount_hits": forbidden_hits,
        "failed_mount_checks": failed,
        "network": network,
    }


def validate_payloads(
    *,
    mode: str,
    s232c_dir: Path,
    s232d0_dir: Path,
    s232d1_dir: Path,
    out_dir: Path,
) -> dict[str, Any]:
    failed_checks: list[dict[str, Any]] = []

    s232d0_summary_path = s232d0_dir / "atlas_relation_identity_s232d0_docker_worker_contract.json"
    s232d0_contract_path = s232d0_dir / "s232d0_docker_worker_contract.json"
    allowlist_path = s232d0_dir / "s232d0_work_order_allowlist.jsonl"
    s232c_queue_path = s232c_dir / "s232c_bounded_evidence_acquisition_queue.jsonl"
    s232c_summary_path = s232c_dir / "atlas_relation_identity_s232c_bounded_evidence_gate.json"
    s232d1_summary_path = s232d1_dir / "atlas_relation_identity_s232d1_controller_release_readiness.json"
    workspace_compose_path = Path("/workspace/tools/stage7_rewrite/db2_weapons/compose.yaml")

    required_paths = {
        "s232d0_summary": s232d0_summary_path,
        "s232d0_contract": s232d0_contract_path,
        "s232d0_allowlist": allowlist_path,
        "s232c_queue": s232c_queue_path,
        "s232c_summary": s232c_summary_path,
        "s232d1_summary": s232d1_summary_path,
    }
    if mode == "in-container":
        required_paths["workspace_compose"] = workspace_compose_path

    for name, path in required_paths.items():
        if not path.exists():
            failed_checks.append({"check": "required_artifact_readable", "artifact": name, "path": public_path(path, mode)})

    s232d0_summary = read_json(s232d0_summary_path) if s232d0_summary_path.exists() else {}
    s232d0_contract = read_json(s232d0_contract_path) if s232d0_contract_path.exists() else {}
    allowlist = read_jsonl(allowlist_path) if allowlist_path.exists() else []
    s232c_queue = read_jsonl(s232c_queue_path) if s232c_queue_path.exists() else []
    s232c_summary = read_json(s232c_summary_path) if s232c_summary_path.exists() else {}
    s232d1_summary = read_json(s232d1_summary_path) if s232d1_summary_path.exists() else {}

    expected_work_orders = as_int((s232d0_summary.get("counts") or {}).get("work_order_count"))
    expected_allowlist = as_int((s232d0_summary.get("counts") or {}).get("allowlist_count"))
    contract_work_orders = as_int(s232d0_contract.get("selected_work_order_count"))
    s232c_selected = as_int(s232c_summary.get("selected_work_order_count"))

    if not s232d0_summary.get("contract_validation_passed"):
        failed_checks.append({"check": "s232d0_contract_validation_passed"})
    if as_int((s232d0_summary.get("counts") or {}).get("failed_contract_check_count")) != 0:
        failed_checks.append(
            {
                "check": "s232d0_failed_contract_check_count_zero",
                "value": (s232d0_summary.get("counts") or {}).get("failed_contract_check_count"),
            }
        )
    if len(allowlist) != expected_allowlist or expected_allowlist != expected_work_orders:
        failed_checks.append(
            {
                "check": "allowlist_count_matches_s232d0",
                "allowlist_count": len(allowlist),
                "expected_allowlist": expected_allowlist,
                "expected_work_orders": expected_work_orders,
            }
        )
    if len(s232c_queue) != expected_work_orders or s232c_selected != expected_work_orders:
        failed_checks.append(
            {
                "check": "s232c_queue_count_matches_s232d0",
                "s232c_queue_count": len(s232c_queue),
                "s232c_selected": s232c_selected,
                "expected_work_orders": expected_work_orders,
            }
        )
    if contract_work_orders != expected_work_orders:
        failed_checks.append({"check": "contract_selected_work_order_count_matches", "value": contract_work_orders})

    if (s232d0_contract.get("control_plane_rule") or {}).get("skill_role") != "control_plane_only":
        failed_checks.append({"check": "skill_control_plane_only"})
    if (s232d0_contract.get("control_plane_rule") or {}).get("required_runtime") != "docker_container_worker":
        failed_checks.append({"check": "required_runtime_docker_container_worker"})

    mount_contract = s232d0_contract.get("mount_contract") or {}
    for field in ("production_db_mount", "browser_profile_mount", "credential_mount"):
        if mount_contract.get(field) != "forbidden":
            failed_checks.append({"check": "contract_forbids_mount", "field": field, "value": mount_contract.get(field)})
    if not mount_contract.get("read_only"):
        failed_checks.append({"check": "contract_read_only_mounts_declared"})
    if not mount_contract.get("write_only_report_local"):
        failed_checks.append({"check": "contract_report_local_output_declared"})

    policy = s232d0_contract.get("policy") or {}
    for key in (
        "allowlist_only",
        "no_cookie_public_only",
        "no_db1_db2_db3_write",
        "no_db2_projection",
        "no_deploy_sync_upload_review_release",
        "no_secret_or_raw_url_output",
    ):
        if not as_bool(policy.get(key)):
            failed_checks.append({"check": "policy_required_true", "field": key, "value": policy.get(key)})

    for flag in FORBIDDEN_SUMMARY_FLAGS:
        if as_bool(s232d0_summary.get(flag)):
            failed_checks.append({"check": "s232d0_forbidden_flag_false", "flag": flag})

    for index, row in enumerate(allowlist):
        for flag in ALLOWLIST_FALSE_FLAGS:
            if as_bool(row.get(flag)):
                failed_checks.append({"check": "allowlist_forbidden_flag_false", "index": index, "flag": flag})
        if not as_bool(row.get("collector_release_required")):
            failed_checks.append({"check": "allowlist_collector_release_required_true", "index": index})

    if not as_bool((s232d1_summary.get("readiness") or {}).get("collector_release_preconditions_ready")):
        failed_checks.append({"check": "s232d1_preconditions_ready"})

    release_token_present = os.environ.get("ATLAS_S232D2_DOCKER_SMOKE_RELEASE") == CONTROLLER_RELEASE_ID
    if mode == "in-container" and not release_token_present:
        failed_checks.append({"check": "s232d2_smoke_release_token_present"})

    if mode == "in-container":
        for env_name in ("ATLAS_COLLECTOR_EXECUTION_ALLOWED", "DB2_WORKER_EXECUTE", "DB2_WRITER_EXECUTE", "DB2_PROJECTION_EXECUTE"):
            if os.environ.get(env_name) != "0":
                failed_checks.append({"check": "forced_dry_run_env_zero", "env": env_name})

    mount_report = validate_mounts(mode, s232c_dir, s232d0_dir, s232d1_dir, out_dir)
    failed_checks.extend(mount_report["failed_mount_checks"])
    write_probe = probe_report_local_write(out_dir) if mode == "in-container" else {}

    lane_counts = Counter(str(row.get("s228_lane") or "unknown") for row in allowlist)
    evidence_mode_counts = Counter(str(row.get("recommended_evidence_mode") or "unknown") for row in allowlist)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "controller_release_id": CONTROLLER_RELEASE_ID,
        "generated_at": utc_now(),
        "mode": mode,
        "inside_container": mode == "in-container",
        "decision": "",
        "inputs": {
            "s232c_summary": public_path(s232c_summary_path, mode),
            "s232c_work_orders": public_path(s232c_queue_path, mode),
            "s232d0_summary": public_path(s232d0_summary_path, mode),
            "s232d0_contract": public_path(s232d0_contract_path, mode),
            "s232d0_allowlist": public_path(allowlist_path, mode),
            "s232d1_readiness": public_path(s232d1_summary_path, mode),
            "workspace_compose": public_path(workspace_compose_path, mode) if mode == "in-container" else "",
        },
        "counts": {
            "work_order_count": expected_work_orders,
            "allowlist_count": len(allowlist),
            "s232c_queue_count": len(s232c_queue),
            "failed_check_count": len(failed_checks),
            "selected_lane_counts": dict(lane_counts),
            "recommended_evidence_mode_counts": dict(evidence_mode_counts),
        },
        "contract_checks": {
            "s232d0_contract_validation_passed": bool(s232d0_summary.get("contract_validation_passed")),
            "failed_contract_check_count": as_int((s232d0_summary.get("counts") or {}).get("failed_contract_check_count")),
            "allowlist_matches_work_orders": len(allowlist) == expected_work_orders == expected_allowlist,
            "contract_selected_work_order_count": contract_work_orders,
            "skill_control_plane_only": (s232d0_contract.get("control_plane_rule") or {}).get("skill_role") == "control_plane_only",
            "docker_runtime_declared": (s232d0_contract.get("control_plane_rule") or {}).get("required_runtime")
            == "docker_container_worker",
            "production_db_mount_forbidden": mount_contract.get("production_db_mount") == "forbidden",
            "browser_profile_mount_forbidden": mount_contract.get("browser_profile_mount") == "forbidden",
            "credential_mount_forbidden": mount_contract.get("credential_mount") == "forbidden",
            "s232d1_preconditions_ready": as_bool((s232d1_summary.get("readiness") or {}).get("collector_release_preconditions_ready")),
        },
        "container_checks": {
            "container_smoke_allowed_by_controller_release": mode == "in-container" and release_token_present,
            "workspace_exists": Path("/workspace").exists() if mode == "in-container" else False,
            "workspace_compose_readable": workspace_compose_path.exists() if mode == "in-container" else False,
            "read_only_input_mounts": mount_report["input_mount_checks"],
            "report_local_output_mount": mount_report["output_mount_check"],
            "forbidden_mount_hits": mount_report["forbidden_mount_hits"],
            "network": mount_report["network"],
            "report_local_write_probe": write_probe,
        },
        "failed_checks": failed_checks,
        "collector_execution_allowed_now": False,
        "collector_executed": False,
        "container_smoke_executed": mode == "in-container",
        "docker_started": mode == "in-container",
        "db2_worker_started": False,
        "network_fetch_allowed_now": False,
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
        "s232d3_required_for_collector": True,
        "next_gate": "Stop after S232D-2. A real no-cookie collector canary requires a new S232D-3 controller release.",
        "production_state_difference": "Docker/container read-only smoke only; no collector, network fetch, DB1/DB2/DB3 mutation, DB2 projection, deploy/sync/upload/review/release, or secret read",
    }
    summary["leak_findings"] = leak_scan(summary)
    summary["raw_source_url_emitted"] = any(row.get("kind") == "raw_url" for row in summary["leak_findings"])
    summary["private_path_emitted"] = any(row.get("kind") == "private_path" for row in summary["leak_findings"])
    if summary["leak_findings"]:
        failed_checks.extend(summary["leak_findings"])
        summary["counts"]["failed_check_count"] = len(failed_checks)
    summary["decision"] = (
        "atlas_relation_identity_s232d2_docker_read_only_smoke_passed"
        if mode == "in-container" and not failed_checks
        else "atlas_relation_identity_s232d2_docker_read_only_smoke_blocked"
    )
    if mode == "local-preflight" and not failed_checks:
        summary["decision"] = "atlas_relation_identity_s232d2_local_preflight_passed_waiting_container_smoke"
    return summary


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# S232D-2 Docker Read-Only Smoke",
            "",
            f"- Decision: `{report['decision']}`",
            f"- Controller release ID: `{report['controller_release_id']}`",
            f"- Inside container: `{report['inside_container']}`",
            f"- Work orders / allowlist: `{counts['work_order_count']}` / `{counts['allowlist_count']}`",
            f"- Failed checks: `{counts['failed_check_count']}`",
            f"- DB3 same-normalized blocker remains: `348`",
            "",
            "## Boundary",
            "",
            "- Container smoke only. No collector execution and no network fetch.",
            "- No cookie/token/.env/browser credential read.",
            "- No DB1/DB2/DB3 write, no DB2 projection, no deploy/sync/upload/review/release.",
            "- S232D-3 controller release is required before any no-cookie collector canary.",
            "",
            "## Artifact",
            "",
            f"- `{report.get('artifacts', {}).get('json', '')}`",
            "",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    s232c_dir, s232d0_dir, s232d1_dir, default_out_dir = resolve_roots(args.mode)
    out_dir = args.out_dir or default_out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    report = validate_payloads(mode=args.mode, s232c_dir=s232c_dir, s232d0_dir=s232d0_dir, s232d1_dir=s232d1_dir, out_dir=out_dir)
    json_path = out_dir / "atlas_relation_identity_s232d2_docker_smoke.json"
    markdown_path = out_dir / "atlas_relation_identity_s232d2_docker_smoke.md"
    report["output_dir"] = str(out_dir) if args.mode == "in-container" else rel(out_dir)
    report["artifacts"] = {
        "json": f"{S232D2_DIR_NAME}/atlas_relation_identity_s232d2_docker_smoke.json"
        if args.mode == "in-container"
        else rel(json_path),
        "markdown": f"{S232D2_DIR_NAME}/atlas_relation_identity_s232d2_docker_smoke.md"
        if args.mode == "in-container"
        else rel(markdown_path),
    }
    if args.scorecard and args.mode != "in-container":
        report["artifacts"]["scorecard"] = rel(args.scorecard)

    write_json(json_path, report)
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    if args.scorecard and args.mode != "in-container":
        args.scorecard.parent.mkdir(parents=True, exist_ok=True)
        args.scorecard.write_text(markdown, encoding="utf-8")
        write_json(json_path, report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate S232D-2 Docker/container read-only smoke")
    parser.add_argument("--mode", choices=("local-preflight", "in-container"), default="local-preflight")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not report.get("failed_checks") else 1


if __name__ == "__main__":
    raise SystemExit(main())
