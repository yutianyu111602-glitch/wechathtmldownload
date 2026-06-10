#!/usr/bin/env python
"""Build a report-only Docker worker contract for aggregate-child poster OCR recovery.

This preflight consumes the redacted OCR recovery task queue and validates that
the dedicated Docker profile is wired for a future worker. It does not start
Docker, fetch network content, OCR images, call vision APIs, upload CloudBase
Storage files, patch packages, or re-enable child source actions.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_COMPOSE = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-weekly" / "docker-compose.openclaw-weekly.yml"
DEFAULT_PROFILE = "openclaw-poster-ocr-recovery"
DEFAULT_SERVICE = "openclaw-poster-ocr-recovery-worker"
DEFAULT_QUEUE = "openclaw.poster_ocr_recovery"
DEFAULT_LAYER = "L3A"
SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_worker_contract.v1"

FORBIDDEN_RAW_URL_RE = re.compile(
    r"https?://|wxfile://|blob:|/api/v1/weekly/poster/|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|mp\.weixin\.qq\.com",
    re.I,
)
EXECUTION_FLAGS = (
    "network_executed",
    "download_executed",
    "ocr_executed",
    "vision_api_executed",
    "cloudbase_storage_write_executed",
    "package_patch_executed",
    "child_source_action_reenabled",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def safe_path_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except (OSError, ValueError):
        return path.name


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            found = first_text(*value)
            if found:
                return found
        elif value is not None and str(value).strip():
            return str(value).strip()
    return ""


def service_blocks(compose_text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^  ([a-z0-9-]+):\s*$", compose_text, flags=re.MULTILINE))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        name = match.group(1)
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(compose_text)
        blocks[name] = compose_text[start:end]
    return blocks


def check(check_id: str, passed: bool, evidence: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": required,
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def raw_url_leak_count(payload: Any) -> int:
    return len(FORBIDDEN_RAW_URL_RE.findall(json.dumps(payload, ensure_ascii=False)))


def validate_task_payload(tasks_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks = [row for row in as_list(tasks_payload.get("tasks")) if isinstance(row, dict)]
    checks: list[dict[str, Any]] = [
        check(
            "tasks_schema_version",
            first_text(tasks_payload.get("schema_version")) == "weekly_aggregate_child_poster_ocr_recovery_tasks.v1",
            "Input must be aggregate-child poster OCR recovery tasks.",
        ),
        check("task_count_positive", int(tasks_payload.get("task_count") or 0) > 0, "Task queue must not be empty."),
        check(
            "all_tasks_ready",
            int(tasks_payload.get("ready_task_count") or 0) == int(tasks_payload.get("task_count") or 0),
            "Every selected aggregate child must be ready for candidate article image OCR review.",
        ),
        check(
            "candidate_article_total_present",
            int(tasks_payload.get("candidate_article_total") or 0) >= int(tasks_payload.get("task_count") or 0),
            "Every ready task should have at least one candidate source article.",
        ),
        check(
            "candidate_source_map_complete",
            int(tasks_payload.get("candidate_source_map_missing_total") or 0) == 0,
            "Candidate source keys must all resolve to source-map entries before a worker can act.",
        ),
        check(
            "input_raw_url_leak_free",
            int(tasks_payload.get("raw_public_url_leak_count") or 0) == 0 and raw_url_leak_count(tasks_payload) == 0,
            "Input task report must not expose public article/image URLs or temp file paths.",
        ),
    ]
    for flag in EXECUTION_FLAGS:
        checks.append(
            check(
                f"input_{flag}_false",
                tasks_payload.get(flag) is False,
                f"Input task report must remain report-only: {flag}=false.",
            )
        )

    sanitized_tasks: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        task_id = first_text(task.get("id")) or f"task-{index + 1}"
        source_action_available = task.get("source_action_available")
        release_write_allowed = task.get("release_write_allowed")
        candidates = [row for row in as_list(task.get("candidate_articles")) if isinstance(row, dict)]
        selector = as_dict(task.get("selector"))
        checks.extend(
            [
                check(f"task.{task_id}.source_action_disabled", source_action_available is False, "Child source actions must remain disabled until source target is repaired."),
                check(f"task.{task_id}.release_write_not_allowed", release_write_allowed is False, "No task may authorize a package or CloudBase write."),
                check(f"task.{task_id}.candidate_articles_present", len(candidates) > 0, "Worker input needs at least one redacted candidate article key."),
                check(f"task.{task_id}.selector_has_title_or_date", bool(first_text(selector.get("event_date_start"), selector.get("event_date_end"), selector.get("title_terms"))), "OCR selector must include event date or title terms."),
                check(f"task.{task_id}.raw_url_leak_free", raw_url_leak_count(task) == 0, "Task rows must keep raw URLs redacted."),
            ]
        )
        sanitized_tasks.append(
            {
                "id": task_id,
                "status": first_text(task.get("status")),
                "source_action_available": False,
                "release_write_allowed": False,
                "candidate_source_article_count": len(candidates),
                "candidate_source_keys": [first_text(row.get("source_key")) for row in candidates if first_text(row.get("source_key"))],
                "selector": {
                    "title_terms": as_list(selector.get("title_terms"))[:8],
                    "event_date_start": first_text(selector.get("event_date_start")),
                    "event_date_end": first_text(selector.get("event_date_end")),
                    "venue": first_text(selector.get("venue")),
                    "city": as_list(selector.get("city")),
                },
                "high_risk_reasons": as_list(task.get("high_risk_reasons")),
            }
        )
    return checks, sanitized_tasks


def validate_compose(compose_path: Path, profile: str, service: str, queue: str, layer: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    compose_text = compose_path.read_text(encoding="utf-8", errors="replace") if compose_path.exists() else ""
    blocks = service_blocks(compose_text)
    block = blocks.get(service, "")
    checks = [
        check("compose_file_exists", compose_path.exists(), safe_path_label(compose_path)),
        check("compose_service_declared", bool(block), f"Service {service} must exist."),
        check("compose_profile_declared", f'profiles: ["{profile}"]' in block, f"Service must be gated by profile {profile}."),
        check("compose_layer_declared", f'OPENCLAW_LAYER: "{layer}"' in block, f"Service must declare layer {layer}."),
        check("compose_queue_declared", f'OPENCLAW_QUEUE_NAME: "{queue}"' in block, f"Service must declare queue {queue}."),
        check("compose_report_only_contract", "<<: *openclaw-contract-common" in block, "Service must inherit the common report-only contract."),
        check("compose_common_environment", "<<: *openclaw-common-env" in block, "Service must inherit common disabled policy environment."),
        check("compose_network_disabled", 'network_mode: "none"' in compose_text, "Common contract must keep Docker network disabled."),
        check("compose_workspace_read_only", "target: /workspace" in compose_text and "read_only: true" in compose_text, "Workspace mount must be read-only."),
        check("compose_poster_package_policy", 'OPENCLAW_POSTER_PACKAGE_POLICY: "cloudbase_file_id_only_no_temp_url"' in block, "Worker must preserve backend package cloud:// fileId policy."),
    ]
    return checks, {
        "compose_path": safe_path_label(compose_path),
        "profile": profile,
        "service": service,
        "queue_name": queue,
        "layer": layer,
    }


def unique_source_keys(tasks: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    keys: list[str] = []
    for task in tasks:
        for key in as_list(task.get("candidate_source_keys")):
            text = first_text(key)
            if text and text not in seen:
                seen.add(text)
                keys.append(text)
    return keys


def build_contract(tasks_path: Path, compose_path: Path, profile: str, service: str, queue: str, layer: str) -> dict[str, Any]:
    tasks_payload = read_json(tasks_path)
    task_checks, sanitized_tasks = validate_task_payload(tasks_payload)
    compose_checks, docker_contract = validate_compose(compose_path, profile, service, queue, layer)
    checks = task_checks + compose_checks
    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    source_keys = unique_source_keys(sanitized_tasks)
    ready = not failed
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "aggregate_child_poster_ocr_worker_contract_ready_report_only_no_execution" if ready else "aggregate_child_poster_ocr_worker_contract_blocked_report_only_no_execution",
        "report_only": True,
        "source_tasks_report": safe_path_label(tasks_path),
        "docker_worker_contract": docker_contract,
        "front_end_adaptation_contract": {
            "backend_package_truth": "cloudbase_internal_file_id",
            "accepted_package_file_id_pattern": "cloud://.../weekly-posters/YYYYMMDD/...",
            "poster_storage_required": "cloudbase",
            "coverUrl_policy": "may_equal_cloud_file_id_before_frontend_runtime_resolution",
            "frontend_runtime_resolution": "wx.cloud.getTempFileURL then image temp URL; binderror may downloadFile and finally retry original cloud://",
            "package_must_not_contain_categories": [
                "public_http_or_https_url",
                "frontend_local_temp_file_scheme",
                "browser_blob_url",
                "weekly_poster_proxy_path",
                "wechat_or_qpic_public_image_domain",
                "wechat_public_article_domain",
            ],
        },
        "post_run_acceptance_gate": {
            "missing_internal_poster_count": 0,
            "invalid_internal_poster_file_id_count": 0,
            "invalid_poster_storage_count": 0,
            "public_or_temp_poster_url_count": 0,
            "public_wechat_or_qpic_poster_count": 0,
            "aggregate_child_poster_suppressed_count": 0,
            "aggregate_child_poster_field_present_count": 0,
            "devtools_render_proof_expected": "frontend-level temp URL/image load proof remains separate from backend package quality",
        },
        "required_controls": {
            "queue_allowlist": source_keys,
            "source_key_allowlist_count": len(source_keys),
            "lease_file_required": True,
            "checkpoint_file_required": True,
            "append_only_log_required": True,
            "retry_max": 2,
            "kill_switch_required": True,
            "raw_url_report_forbidden": True,
            "cloudbase_upload_confirm_token_required": True,
            "package_patch_confirm_token_required": True,
            "controller_release_required_before_actual_worker": True,
        },
        "queue": {
            "task_count": len(sanitized_tasks),
            "ready_task_count": int(tasks_payload.get("ready_task_count") or 0),
            "candidate_article_total": int(tasks_payload.get("candidate_article_total") or 0),
            "candidate_source_map_missing_total": int(tasks_payload.get("candidate_source_map_missing_total") or 0),
        },
        "tasks": sanitized_tasks,
        "checks": checks,
        "failed_required_check_ids": failed,
        "execution_flags": {
            "docker_started": False,
            "worker_started": False,
            "network_fetch_executed": False,
            "download_executed": False,
            "ocr_executed": False,
            "vision_api_executed": False,
            "cloudbase_storage_write_executed": False,
            "package_patch_executed": False,
            "child_source_action_reenabled": False,
            "cloudbase_db_write_executed": False,
            "db2_write_executed": False,
            "db3_write_executed": False,
            "cloudrun_deploy_executed": False,
            "miniprogram_upload_executed": False,
            "wechat_review_submitted": False,
        },
        "release_gate_green": False,
        "execution_allowed_now": False,
        "docker_worker_allowed_now": False,
        "network_fetch_allowed_now": False,
        "ocr_allowed_now": False,
        "vision_api_allowed_now": False,
        "cloudbase_storage_write_allowed_now": False,
        "package_patch_allowed_now": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--service", default=DEFAULT_SERVICE)
    parser.add_argument("--queue-name", default=DEFAULT_QUEUE)
    parser.add_argument("--layer", default=DEFAULT_LAYER)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = build_contract(args.tasks, args.compose, args.profile, args.service, args.queue_name, args.layer)
    write_json(args.report, contract)
    print(json.dumps({"decision": contract["decision"], "report": str(args.report)}, ensure_ascii=False))
    return 0 if not contract["failed_required_check_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
