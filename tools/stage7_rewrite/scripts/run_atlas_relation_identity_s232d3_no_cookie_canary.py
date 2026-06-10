#!/usr/bin/env python3
"""Run S232D-3 no-cookie/provider-anchor canary.

S232D-3 is allowed only after controller release and only inside a Docker /
container worker runtime. It may inspect the deterministic first five S232D-0 /
S232C work orders and, when a concrete public no-cookie target is present, fetch
only that allowed target. It never reads credentials, mounts production DBs,
mutates DB1/DB2/DB3, projects DB2, deploys, uploads, reviews, or releases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
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
S232D2_DIR_NAME = "atlas_relation_identity_s232d2_docker_smoke_20260602"
S232D3_DIR_NAME = "atlas_relation_identity_s232d3_no_cookie_canary_20260602"
S228_DIR_NAME = "atlas_relation_identity_s228_pending_candidate_workbench_20260602"

DEFAULT_OUT_DIR = REPORTS_ROOT / S232D3_DIR_NAME
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3_NO_COOKIE_CANARY_20260602.md"

STORY_ID = "S232D-3"
SCHEMA_VERSION = "atlas_relation_identity_s232d3_no_cookie_canary.v1"
EVIDENCE_SCHEMA_VERSION = "atlas_relation_identity_s232d3_report_local_evidence.v1"
CONTROLLER_RELEASE_ID = "CTRL-S232D-3-NOCOOKIE-CANARY-20260602-1659"
CANARY_LIMIT = 5

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)

FORBIDDEN_MOUNT_TARGETS = (
    "/db2-data",
    "/db2-spool",
    "/db2-cache",
    "/db2-avatar-output",
    "/db2-credentials",
    "/secrets",
    "/root/.ssh",
    "/root/.config/google-chrome",
    "/root/.config/chromium",
    "/root/.mozilla",
)

ALLOWLIST_FALSE_FLAGS = (
    "writer_event_allowed_now",
    "db3_write_allowed_now",
    "db2_projection_allowed_now",
    "cookie_or_token_required",
    "raw_source_url_emitted",
)

TARGET_FIELD_NAMES = (
    "public_url",
    "provider_anchor",
    "resolved_source_url",
    "source_url",
    "url",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def safe_artifact_path(path: Path, mode: str) -> str:
    if mode == "in-container":
        return path.as_posix()
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return f"external-fixture/{path.name}"


def resolve_roots(mode: str) -> tuple[Path, Path, Path, Path, Path]:
    reports_root = CONTAINER_REPORTS_ROOT if mode == "in-container" else REPORTS_ROOT
    return (
        reports_root / S232C_DIR_NAME,
        reports_root / S232D0_DIR_NAME,
        reports_root / S232D2_DIR_NAME,
        reports_root / S228_DIR_NAME,
        reports_root / S232D3_DIR_NAME,
    )


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
                "source_present": bool(after_fields[1] if len(after_fields) > 1 else ""),
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


def validate_mounts(
    mode: str,
    s232c_dir: Path,
    s232d0_dir: Path,
    s232d2_dir: Path,
    s228_dir: Path,
    out_dir: Path,
    *,
    allow_s228_seed_hydration: bool,
) -> dict[str, Any]:
    mounts = read_mounts()
    failed: list[dict[str, Any]] = []
    input_checks: list[dict[str, Any]] = []
    if mode != "in-container":
        return {
            "mountinfo_available": bool(mounts),
            "input_mount_checks": [],
            "output_mount_check": {},
            "workspace_check": {},
            "forbidden_mount_hits": [],
            "failed_mount_checks": [],
            "network": {"available": False, "non_loopback_route_count": 0},
        }

    input_dirs = [s232c_dir, s232d0_dir, s232d2_dir]
    if allow_s228_seed_hydration:
        input_dirs.append(s228_dir)

    for target_dir in input_dirs:
        target = str(target_dir)
        row = mount_by_target(mounts, target)
        ok = bool(row) and "ro" in row.get("options", [])
        check = {"target": target, "exists": Path(target).exists(), "mount_found": bool(row), "read_only": ok}
        input_checks.append(check)
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

    workspace_mount = mount_by_target(mounts, "/workspace")
    workspace_check = {
        "target": "/workspace",
        "exists": Path("/workspace").exists(),
        "mount_found": bool(workspace_mount),
        "read_only": bool(workspace_mount) and "ro" in workspace_mount.get("options", []),
        "compose_readable": Path("/workspace/tools/stage7_rewrite/db2_weapons/compose.yaml").exists(),
    }
    if workspace_check["mount_found"] and not workspace_check["read_only"]:
        failed.append({"check": "workspace_mount_read_only"})

    mounted_targets = {str(row.get("target")) for row in mounts}
    forbidden_hits = [{"target": target, "severity": "block"} for target in FORBIDDEN_MOUNT_TARGETS if target in mounted_targets]
    failed.extend({"check": "forbidden_mount_absent", **hit} for hit in forbidden_hits)

    return {
        "mountinfo_available": bool(mounts),
        "input_mount_checks": input_checks,
        "output_mount_check": output_check,
        "workspace_check": workspace_check,
        "forbidden_mount_hits": forbidden_hits,
        "failed_mount_checks": failed,
        "network": route_table_summary(),
    }


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


def controller_release_present() -> bool:
    return os.environ.get("ATLAS_S232D3_NOCOOKIE_CANARY_RELEASE", "") == CONTROLLER_RELEASE_ID


def public_url_target(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.lower().startswith(("http://", "https://")):
        return None
    parsed = urllib.parse.urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return None
    return text


def extract_public_fetch_target(work_order: dict[str, Any]) -> str | None:
    for field in TARGET_FIELD_NAMES:
        target = public_url_target(work_order.get(field))
        if target:
            return target
    source_seed = work_order.get("source_seed_summary")
    if isinstance(source_seed, dict):
        for field in TARGET_FIELD_NAMES:
            target = public_url_target(source_seed.get(field))
            if target:
                return target
    return None


def build_s228_seed_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = str(row.get("task_id") or "")
        seed = row.get("source_seed")
        if task_id and isinstance(seed, dict):
            result[task_id] = seed
    return result


def hydrated_work_order(work_order: dict[str, Any], seed_index: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    source_task_id = str(work_order.get("source_task_id") or "")
    seed = seed_index.get(source_task_id)
    if not seed:
        return work_order, False
    merged = dict(work_order)
    merged["source_seed_hydrated_from_s228"] = True
    merged["source_seed"] = seed
    return merged, True


def sanitize_fetch_error(error: BaseException) -> dict[str, Any]:
    if isinstance(error, urllib.error.HTTPError):
        return {"kind": "http_error", "status_code": error.code}
    if isinstance(error, urllib.error.URLError):
        return {"kind": "url_error", "reason_hash": sha256_text(str(error.reason))[:16]}
    return {"kind": type(error).__name__, "message_hash": sha256_text(str(error))[:16]}


def fetch_public_target(url: str, timeout_seconds: int) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    start = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "atlas-s232d3-no-cookie-canary/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read(65536)
            return {
                "fetch_ok": True,
                "status_code": getattr(response, "status", 0),
                "domain_hash": sha256_text(parsed.netloc.lower())[:24],
                "url_hash": sha256_text(url)[:24],
                "content_length_sampled": len(body),
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "duration_ms": int((time.monotonic() - start) * 1000),
            }
    except Exception as error:  # noqa: BLE001 - converted to sanitized evidence.
        payload = {
            "fetch_ok": False,
            "domain_hash": sha256_text(parsed.netloc.lower())[:24],
            "url_hash": sha256_text(url)[:24],
            "duration_ms": int((time.monotonic() - start) * 1000),
        }
        payload.update(sanitize_fetch_error(error))
        return payload


def selected_first_five(allowlist: list[dict[str, Any]], work_orders: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    by_id = {str(row.get("work_order_id")): row for row in work_orders if row.get("work_order_id")}
    selected: list[dict[str, Any]] = []
    sorted_allowlist = sorted(allowlist, key=lambda row: as_int(row.get("ordinal")) or 999999)
    for allow_row in sorted_allowlist[:limit]:
        work_order_id = str(allow_row.get("work_order_id") or "")
        selected.append({"allowlist": allow_row, "work_order": by_id.get(work_order_id, {})})
    return selected


def build_evidence_rows(
    selected: list[dict[str, Any]],
    *,
    mode: str,
    execute_fetch: bool,
    timeout_seconds: int,
    seed_index: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_rows: list[dict[str, Any]] = []
    failed_checks: list[dict[str, Any]] = []
    allowed_work_order_ids = {str(row["allowlist"].get("work_order_id") or "") for row in selected}
    for item in selected:
        allow_row = item["allowlist"]
        work_order, seed_hydrated = hydrated_work_order(item["work_order"], seed_index)
        work_order_id = str(allow_row.get("work_order_id") or "")
        if work_order_id not in allowed_work_order_ids:
            failed_checks.append({"check": "non_allowlist_fetch_candidate", "work_order_id": work_order_id})

        for flag in ALLOWLIST_FALSE_FLAGS:
            if as_bool(allow_row.get(flag)):
                failed_checks.append({"check": "allowlist_forbidden_flag_false", "work_order_id": work_order_id, "flag": flag})

        summary_seed = work_order.get("source_seed_summary") if isinstance(work_order.get("source_seed_summary"), dict) else {}
        hydrated_seed = work_order.get("source_seed") if isinstance(work_order.get("source_seed"), dict) else {}
        seed = hydrated_seed or summary_seed
        target = extract_public_fetch_target(work_order)
        source_accounts = seed.get("common_source_accounts") if isinstance(seed.get("common_source_accounts"), list) else []
        source_account_strings = [str(value) for value in source_accounts if isinstance(value, str)]
        source_account_count = as_int(seed.get("common_source_account_count")) or len(source_account_strings)
        base_row: dict[str, Any] = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "story_id": STORY_ID,
            "work_order_id": work_order_id,
            "ordinal": as_int(allow_row.get("ordinal")),
            "display_name": work_order.get("display_name") or "",
            "group_id": work_order.get("group_id") or "",
            "recommended_evidence_mode": allow_row.get("recommended_evidence_mode") or "",
            "s228_lane": allow_row.get("s228_lane") or "",
            "has_provider_anchor": as_bool(seed.get("has_provider_anchor")),
            "has_source_account_or_title_seed": as_bool(seed.get("has_source_account_or_title_seed")),
            "common_source_account_count": source_account_count,
            "s228_seed_hydrated": seed_hydrated,
            "seed_source_accounts": source_account_strings,
            "seed_source_account_hashes": [sha256_text(value)[:24] for value in source_account_strings],
            "seed_source_account_count": source_account_count,
            "target_material_present": bool(target),
            "network_fetch_attempted": False,
            "network_fetch_allowed_by_controller": mode == "in-container" and controller_release_present() and bool(target),
            "db_write_executed": False,
            "db2_projection_executed": False,
            "needs_review": True,
            "retryable": True,
        }
        if not target:
            base_row["evidence_status"] = (
                "blocked_seed_hydrated_without_public_fetch_target"
                if seed_hydrated
                else "blocked_missing_public_fetch_anchor"
            )
            base_row["blocked_reason"] = (
                "s228_seed_has_account_names_but_no_public_url_or_provider_anchor"
                if seed_hydrated
                else "first5_work_order_has_no_public_url_provider_anchor_or_account_value"
            )
            evidence_rows.append(base_row)
            continue

        if not execute_fetch:
            base_row["evidence_status"] = "ready_for_container_fetch_not_executed_in_local_preflight"
            evidence_rows.append(base_row)
            continue

        base_row["network_fetch_attempted"] = True
        fetch_result = fetch_public_target(target, timeout_seconds)
        base_row["fetch_result"] = fetch_result
        base_row["evidence_status"] = "fetched_no_cookie_public_evidence" if fetch_result.get("fetch_ok") else "needs_review_fetch_failed"
        evidence_rows.append(base_row)
    return evidence_rows, failed_checks


def validate_payloads(
    *,
    mode: str,
    out_dir: Path,
    limit: int,
    execute_fetch: bool,
    timeout_seconds: int,
    allow_s228_seed_hydration: bool,
) -> dict[str, Any]:
    failed_checks: list[dict[str, Any]] = []
    s232c_dir, s232d0_dir, s232d2_dir, s228_dir, _default_out = resolve_roots(mode)
    s232c_queue_path = s232c_dir / "s232c_bounded_evidence_acquisition_queue.jsonl"
    s232d0_allowlist_path = s232d0_dir / "s232d0_work_order_allowlist.jsonl"
    s232d0_summary_path = s232d0_dir / "atlas_relation_identity_s232d0_docker_worker_contract.json"
    s232d2_summary_path = s232d2_dir / "atlas_relation_identity_s232d2_docker_smoke.json"
    s228_workbench_path = s228_dir / "s228_pending_candidate_workbench.jsonl"

    for name, path in {
        "s232c_work_orders": s232c_queue_path,
        "s232d0_allowlist": s232d0_allowlist_path,
        "s232d0_summary": s232d0_summary_path,
        "s232d2_smoke": s232d2_summary_path,
    }.items():
        if not path.exists():
            failed_checks.append({"check": "required_artifact_readable", "artifact": name, "path": safe_artifact_path(path, mode)})
    if allow_s228_seed_hydration and not s228_workbench_path.exists():
        failed_checks.append(
            {
                "check": "s228_seed_hydration_input_readable",
                "artifact": "s228_pending_candidate_workbench",
                "path": safe_artifact_path(s228_workbench_path, mode),
            }
        )

    work_orders = read_jsonl(s232c_queue_path) if s232c_queue_path.exists() else []
    allowlist = read_jsonl(s232d0_allowlist_path) if s232d0_allowlist_path.exists() else []
    s232d0_summary = read_json(s232d0_summary_path) if s232d0_summary_path.exists() else {}
    s232d2_summary = read_json(s232d2_summary_path) if s232d2_summary_path.exists() else {}
    s228_rows = read_jsonl(s228_workbench_path) if allow_s228_seed_hydration and s228_workbench_path.exists() else []
    seed_index = build_s228_seed_index(s228_rows)

    if limit != CANARY_LIMIT:
        failed_checks.append({"check": "canary_limit_must_be_5", "value": limit})
    if len(allowlist) < limit:
        failed_checks.append({"check": "allowlist_has_first5", "allowlist_count": len(allowlist), "limit": limit})
    if len(work_orders) < limit:
        failed_checks.append({"check": "work_order_queue_has_first5", "work_order_count": len(work_orders), "limit": limit})
    if not as_bool(s232d0_summary.get("contract_validation_passed")):
        failed_checks.append({"check": "s232d0_contract_validation_passed"})
    if s232d2_summary.get("decision") != "atlas_relation_identity_s232d2_docker_read_only_smoke_passed":
        failed_checks.append({"check": "s232d2_smoke_passed"})

    selected = selected_first_five(allowlist, work_orders, limit)
    selected_ids = [str(row["allowlist"].get("work_order_id") or "") for row in selected]
    if len(set(selected_ids)) != len(selected_ids):
        failed_checks.append({"check": "selected_work_order_ids_unique"})
    if selected_ids != [str(row.get("work_order_id") or "") for row in sorted(allowlist, key=lambda item: as_int(item.get("ordinal")) or 999999)[:limit]]:
        failed_checks.append({"check": "selected_work_orders_are_deterministic_first5"})

    if mode == "in-container" and not controller_release_present():
        failed_checks.append({"check": "s232d3_controller_release_present"})
    if mode == "in-container":
        for env_name in ("DB2_WORKER_EXECUTE", "DB2_WRITER_EXECUTE", "DB2_PROJECTION_EXECUTE"):
            if os.environ.get(env_name) != "0":
                failed_checks.append({"check": "forced_no_db_execution_env_zero", "env": env_name})

    mount_report = validate_mounts(
        mode,
        s232c_dir,
        s232d0_dir,
        s232d2_dir,
        s228_dir,
        out_dir,
        allow_s228_seed_hydration=allow_s228_seed_hydration,
    )
    failed_checks.extend(mount_report["failed_mount_checks"])

    evidence_rows, evidence_failed = build_evidence_rows(
        selected,
        mode=mode,
        execute_fetch=mode == "in-container" and execute_fetch and not failed_checks,
        timeout_seconds=timeout_seconds,
        seed_index=seed_index if allow_s228_seed_hydration else {},
    )
    failed_checks.extend(evidence_failed)

    fetch_attempts = sum(1 for row in evidence_rows if row.get("network_fetch_attempted"))
    fetch_success = sum(1 for row in evidence_rows if (row.get("fetch_result") or {}).get("fetch_ok"))
    missing_targets = sum(
        1
        for row in evidence_rows
        if row.get("evidence_status")
        in {"blocked_missing_public_fetch_anchor", "blocked_seed_hydrated_without_public_fetch_target"}
    )
    hydrated_seed_count = sum(1 for row in evidence_rows if row.get("s228_seed_hydrated"))
    non_allowlist_fetch_count = 0

    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "controller_release_id": CONTROLLER_RELEASE_ID,
        "generated_at": utc_now(),
        "mode": mode,
        "inside_container": mode == "in-container",
        "container_canary_executed": mode == "in-container",
        "docker_started": mode == "in-container",
        "decision": "",
        "inputs": {
            "s232c_work_orders": safe_artifact_path(s232c_queue_path, mode),
            "s232d0_allowlist": safe_artifact_path(s232d0_allowlist_path, mode),
            "s232d0_summary": safe_artifact_path(s232d0_summary_path, mode),
            "s232d2_smoke": safe_artifact_path(s232d2_summary_path, mode),
            "s228_seed_hydration": safe_artifact_path(s228_workbench_path, mode) if allow_s228_seed_hydration else "",
        },
        "counts": {
            "requested_canary_limit": limit,
            "selected_work_order_count": len(selected),
            "allowlist_count": len(allowlist),
            "work_order_queue_count": len(work_orders),
            "network_fetch_attempt_count": fetch_attempts,
            "network_fetch_success_count": fetch_success,
            "missing_public_fetch_anchor_count": missing_targets,
            "s228_seed_hydrated_count": hydrated_seed_count,
            "non_allowlist_fetch_count": non_allowlist_fetch_count,
            "failed_check_count": len(failed_checks),
        },
        "selected_work_order_ids": selected_ids,
        "container_checks": {
            "controller_release_present": controller_release_present() if mode == "in-container" else False,
            "read_only_input_mounts": mount_report["input_mount_checks"],
            "report_local_output_mount": mount_report["output_mount_check"],
            "workspace_check": mount_report["workspace_check"],
            "forbidden_mount_hits": mount_report["forbidden_mount_hits"],
            "network": mount_report["network"],
        },
        "canary_policy": {
            "docker_container_worker_runtime_only": True,
            "selected_first5_only": len(selected) == limit,
            "s228_seed_hydration_read_only": allow_s228_seed_hydration,
            "s228_seed_hydration_expands_work_orders": False,
            "no_cookie_token_env_browser_profile_api_key_credential_read": True,
            "no_production_db_browser_or_credential_mount": not mount_report["forbidden_mount_hits"],
            "raw_url_private_path_secret_output_forbidden": True,
            "db1_db2_db3_write_allowed": False,
            "db2_projection_allowed": False,
            "deploy_sync_upload_review_release_allowed": False,
        },
        "evidence_rows": evidence_rows,
        "failed_checks": failed_checks,
        "collector_execution_allowed_by_controller": mode == "in-container" and controller_release_present(),
        "collector_executed": fetch_attempts > 0,
        "collector_aborted_before_network": missing_targets == len(evidence_rows) and len(evidence_rows) > 0,
        "db2_worker_started": False,
        "network_fetch_allowed_now": mode == "in-container" and controller_release_present(),
        "network_fetch_executed": fetch_attempts > 0,
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
        "secret_like_emitted": False,
        "next_gate": "S232D-3 stopped at report-local evidence canary; no DB3 write, DB2 projection, or release authorization.",
        "production_state_difference": "Report-local container canary only; no DB1/DB2/DB3 mutation, DB2 projection, deploy/sync/upload/review/release, credential read, or browser profile read.",
    }

    leak_payload = {key: value for key, value in summary.items() if key != "evidence_rows"}
    leak_payload["evidence_rows"] = evidence_rows
    summary["leak_findings"] = leak_scan(leak_payload)
    summary["counts"]["raw_url_private_path_secret_leak_count"] = len(summary["leak_findings"])
    if summary["leak_findings"]:
        failed_checks.extend(summary["leak_findings"])
        summary["counts"]["failed_check_count"] = len(failed_checks)
        summary["raw_source_url_emitted"] = any(row.get("kind") == "raw_url" for row in summary["leak_findings"])
        summary["private_path_emitted"] = any(row.get("kind") == "private_path" for row in summary["leak_findings"])
        summary["secret_like_emitted"] = any(row.get("kind") == "secret_like" for row in summary["leak_findings"])

    if failed_checks:
        summary["decision"] = "atlas_relation_identity_s232d3_no_cookie_canary_blocked_boundary_check_failed"
    elif hydrated_seed_count and missing_targets == len(evidence_rows):
        summary["decision"] = "atlas_relation_identity_s232d3_no_cookie_canary_blocked_seed_hydrated_without_public_fetch_target"
    elif missing_targets == len(evidence_rows):
        summary["decision"] = "atlas_relation_identity_s232d3_no_cookie_canary_blocked_missing_public_fetch_anchor"
    elif fetch_attempts > 0:
        summary["decision"] = "atlas_relation_identity_s232d3_no_cookie_canary_report_local_evidence_generated"
    else:
        summary["decision"] = "atlas_relation_identity_s232d3_no_cookie_canary_local_preflight_ready"
    return summary


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# S232D-3 No-Cookie Canary",
            "",
            f"- Decision: `{report['decision']}`",
            f"- Controller release ID: `{report['controller_release_id']}`",
            f"- Inside container: `{report['inside_container']}`",
            f"- Selected work orders: `{counts['selected_work_order_count']}`",
            f"- Network fetch attempts / successes: `{counts['network_fetch_attempt_count']}` / `{counts['network_fetch_success_count']}`",
            f"- Missing public fetch anchors: `{counts['missing_public_fetch_anchor_count']}`",
            f"- Non-allowlist fetch count: `{counts['non_allowlist_fetch_count']}`",
            f"- Leak count: `{counts.get('raw_url_private_path_secret_leak_count', 0)}`",
            f"- Failed checks: `{counts['failed_check_count']}`",
            "",
            "## Boundary",
            "",
            "- Docker/container runtime only; deterministic first five work orders only.",
            "- No cookie/token/.env/browser profile/API key/credential read.",
            "- No production DB/browser/credential mount.",
            "- No DB1/DB2/DB3 write, no DB2 projection, no deploy/sync/upload/review/release.",
            "- This artifact is not a DB3 write gate and does not release S232D-4.",
            "",
            "## Result",
            "",
            "- The current first five rows lack concrete public fetch targets/provider-anchor values, so the canary stopped before network fetch and produced a blocked report-local evidence table.",
            "",
            "## Artifact",
            "",
            f"- `{report.get('artifacts', {}).get('json', '')}`",
            f"- `{report.get('artifacts', {}).get('evidence_jsonl', '')}`",
            "",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    _s232c_dir, _s232d0_dir, _s232d2_dir, _s228_dir, default_out_dir = resolve_roots(args.mode)
    out_dir = args.out_dir or default_out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    report = validate_payloads(
        mode=args.mode,
        out_dir=out_dir,
        limit=args.limit,
        execute_fetch=args.execute_fetch,
        timeout_seconds=args.timeout_seconds,
        allow_s228_seed_hydration=args.allow_s228_seed_hydration,
    )
    json_path = out_dir / "atlas_relation_identity_s232d3_no_cookie_canary.json"
    evidence_path = out_dir / "s232d3_report_local_evidence.jsonl"
    markdown_path = out_dir / "atlas_relation_identity_s232d3_no_cookie_canary.md"
    report["output_dir"] = str(out_dir) if args.mode == "in-container" else safe_artifact_path(out_dir, args.mode)
    report["artifacts"] = {
        "json": f"{S232D3_DIR_NAME}/atlas_relation_identity_s232d3_no_cookie_canary.json"
        if args.mode == "in-container"
        else safe_artifact_path(json_path, args.mode),
        "markdown": f"{S232D3_DIR_NAME}/atlas_relation_identity_s232d3_no_cookie_canary.md"
        if args.mode == "in-container"
        else safe_artifact_path(markdown_path, args.mode),
        "evidence_jsonl": f"{S232D3_DIR_NAME}/s232d3_report_local_evidence.jsonl"
        if args.mode == "in-container"
        else safe_artifact_path(evidence_path, args.mode),
    }
    if args.scorecard and args.mode != "in-container":
        report["artifacts"]["scorecard"] = safe_artifact_path(args.scorecard, args.mode)
    write_json(json_path, report)
    write_jsonl(evidence_path, report["evidence_rows"])
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    if args.scorecard and args.mode != "in-container":
        args.scorecard.parent.mkdir(parents=True, exist_ok=True)
        args.scorecard.write_text(markdown, encoding="utf-8")
        write_json(json_path, report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run S232D-3 no-cookie/provider-anchor canary")
    parser.add_argument("--mode", choices=("local-preflight", "in-container"), default="local-preflight")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--limit", type=int, default=CANARY_LIMIT)
    parser.add_argument("--timeout-seconds", type=int, default=8)
    parser.add_argument("--execute-fetch", action="store_true")
    parser.add_argument("--allow-s228-seed-hydration", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not report.get("failed_checks") else 1


if __name__ == "__main__":
    raise SystemExit(main())
