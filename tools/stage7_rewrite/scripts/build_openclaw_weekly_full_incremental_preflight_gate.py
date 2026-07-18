#!/usr/bin/env python3
"""Build the final report-only gate before a full OpenClaw weekly run.

This script consumes next-action/Darwin/readiness evidence and decides whether
the controller may start a full incremental candidate run. It does not execute
source refresh, Docker workers, OCR, model calls, CloudBase writes, DB writes,
deploy, upload, review, or release.
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
SCHEMA_VERSION = "openclaw_weekly_full_incremental_preflight_gate.v1"
READY_DECISION = "openclaw_weekly_full_incremental_preflight_gate_ready_report_only"
BLOCKED_DECISION = "openclaw_weekly_full_incremental_preflight_gate_blocked_report_only"
INCOMPLETE_DECISION = "openclaw_weekly_full_incremental_preflight_gate_incomplete_report_only"
NEXT_ACTION_SCHEMA = "openclaw_weekly_next_action_packet.v1"
DARWIN_SCHEMA = "openclaw_weekly_darwin_scorecard.v1"
DEFAULT_NEXT_ACTION = (
    REPORTS_ROOT
    / "openclaw_weekly_next_action_packet_round77_auth_qr_reprobe_20260606"
    / "openclaw_weekly_next_action_packet.json"
)
DEFAULT_DARWIN = (
    REPORTS_ROOT
    / "openclaw_darwin_scorecard_round77_auth_qr_reprobe_20260606"
    / "openclaw_weekly_darwin_scorecard.json"
)
DEFAULT_READINESS = (
    REPORTS_ROOT
    / "openclaw_weekly_daily_20260606_101657"
    / "openclaw_weekly_daily_readiness_summary.json"
)
DEFAULT_REPORT = (
    REPORTS_ROOT
    / "openclaw_weekly_full_incremental_preflight_gate_round78_20260606"
    / "openclaw_weekly_full_incremental_preflight_gate.json"
)
DEFAULT_SCORECARD = (
    REPORTS_ROOT
    / "openclaw_weekly_full_incremental_preflight_gate_round78_20260606"
    / "openclaw_weekly_full_incremental_preflight_gate.md"
)
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://|blob:", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\|D:\\DDownload\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})"
)
RAW_SECRET_KEYS = {
    "api_key",
    "auth_key",
    "x-auth-key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "raw_key",
    "raw_api_key",
}
FORBIDDEN_EXECUTION_FLAGS = (
    "source_refresh_executed",
    "network_fetch_executed",
    "download_executed",
    "ocr_executed",
    "vision_api_executed",
    "stepfun_api_executed",
    "mimo_api_executed",
    "cloudbase_storage_write_executed",
    "cloudbase_db_write_executed",
    "db2_write_executed",
    "db3_write_executed",
    "package_patch_executed",
    "cloudrun_deploy_executed",
    "cloudbase_sync_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
    "public_release_executed",
    "credential_value_read",
    "secret_file_read",
    "browser_profile_read",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def bool_value(value: Any) -> bool:
    return value is True


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_repo_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(RAW_URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def raw_secret_key_hits(value: Any) -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key or "").strip()
            if key_text.lower() in RAW_SECRET_KEYS and str(child or "").strip():
                hits.append(key_text)
            hits.extend(raw_secret_key_hits(child))
    elif isinstance(value, list):
        for child in value:
            hits.extend(raw_secret_key_hits(child))
    return hits


def check(check_id: str, passed: bool, evidence: str, *, required: bool = True) -> dict[str, str]:
    return {
        "check_id": check_id,
        "required": "true" if required else "false",
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def false_flag_violations(*payloads: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    for index, payload in enumerate(payloads):
        safety = as_dict(payload.get("safety"))
        boundary = as_dict(payload.get("boundary"))
        controller = as_dict(payload.get("controller_release_packet"))
        for scope_name, scope in (("top", payload), ("safety", safety), ("boundary", boundary), ("controller", controller)):
            for key in FORBIDDEN_EXECUTION_FLAGS:
                if scope.get(key) is True:
                    hits.append(f"payload{index}:{scope_name}.{key}")
    return sorted(set(hits))


def summarize_next_action(next_action: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(next_action),
        "schema_version": str(next_action.get("schema_version") or ""),
        "decision": str(next_action.get("decision") or ""),
        "task_count": int_value(next_action.get("task_count")),
        "source_refresh_allowed_now": bool_value(next_action.get("source_refresh_allowed_now")),
        "full_incremental_run_allowed_now": bool_value(next_action.get("full_incremental_run_allowed_now")),
        "release_ready": bool_value(next_action.get("release_ready")),
        "package_candidate_ready": bool_value(next_action.get("package_candidate_ready")),
        "auth_recovery_ready": bool_value(next_action.get("auth_recovery_ready")),
        "open_task_ids": [str(as_dict(row).get("task_id") or "") for row in as_list(next_action.get("next_action_tasks"))],
        "leak_count": int_value(as_dict(next_action.get("safety")).get("raw_url_private_path_secret_leak_count")),
    }


def summarize_darwin(darwin: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(darwin),
        "schema_version": str(darwin.get("schema_version") or ""),
        "decision": str(darwin.get("decision") or ""),
        "score_total": int_value(darwin.get("score_total")),
        "score_max": int_value(darwin.get("score_max")),
        "prompt_count": len(as_list(darwin.get("test_prompts"))),
        "leak_count": int_value(darwin.get("raw_url_private_path_secret_leak_count")),
    }


def summarize_readiness(readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(readiness),
        "decision": str(readiness.get("decision") or ""),
        "release_ready": bool_value(readiness.get("release_ready")),
        "package_candidate_ready": bool_value(readiness.get("package_candidate_ready")),
        "failed_check_ids": [str(value) for value in as_list(readiness.get("failed_check_ids"))],
        "write_actions_allowed_now": bool_value(readiness.get("write_actions_allowed_now")),
        "release_writes_allowed_now": bool_value(readiness.get("release_writes_allowed_now")),
    }


def summarize_auth_recovery(auth: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(auth),
        "schema_version": str(auth.get("schema_version") or ""),
        "decision": str(auth.get("decision") or ""),
        "auth_recovery_ready": bool_value(auth.get("auth_recovery_ready")),
        "session_requires_auth": bool_value(auth.get("session_requires_auth")),
        "qr_upstream_unavailable": bool_value(auth.get("qr_upstream_unavailable")),
    }


def build_gate(
    *,
    next_action_path: Path,
    darwin_path: Path | None = None,
    readiness_path: Path | None = None,
    auth_recovery_path: Path | None = None,
) -> dict[str, Any]:
    next_action_raw = read_json(next_action_path)
    darwin_raw = read_json(darwin_path)
    readiness_raw = read_json(readiness_path)
    auth_recovery_raw = read_json(auth_recovery_path)
    next_action = summarize_next_action(next_action_raw)
    darwin = summarize_darwin(darwin_raw)
    readiness = summarize_readiness(readiness_raw)
    auth_recovery = summarize_auth_recovery(auth_recovery_raw)
    raw_secret_keys = sorted(
        set(
            raw_secret_key_hits(next_action_raw)
            + raw_secret_key_hits(darwin_raw)
            + raw_secret_key_hits(readiness_raw)
            + raw_secret_key_hits(auth_recovery_raw)
        )
    )
    forbidden_true_flags = false_flag_violations(next_action_raw, darwin_raw, readiness_raw, auth_recovery_raw)
    input_leak_count = leak_count(
        {
            "next_action": next_action,
            "darwin": darwin,
            "readiness": readiness,
            "auth_recovery": auth_recovery,
        }
    )
    prebuild_auth_gate_present = auth_recovery["present"]
    prebuild_source_refresh_allowed = (
        prebuild_auth_gate_present
        and auth_recovery["auth_recovery_ready"]
        and not auth_recovery["session_requires_auth"]
    )
    checks = [
        check("auth_recovery_ready_for_source_refresh", prebuild_source_refresh_allowed, str(prebuild_source_refresh_allowed), required=prebuild_auth_gate_present),
        check("next_action_present", next_action["present"], str(next_action["present"]), required=not prebuild_auth_gate_present),
        check("next_action_schema", next_action["schema_version"] == NEXT_ACTION_SCHEMA, next_action["schema_version"], required=next_action["present"]),
        check("next_action_has_no_open_tasks", next_action["task_count"] == 0, str(next_action["task_count"]), required=not prebuild_auth_gate_present),
        check(
            "next_action_source_refresh_allowed",
            next_action["source_refresh_allowed_now"] or prebuild_source_refresh_allowed,
            str(next_action["source_refresh_allowed_now"] or prebuild_source_refresh_allowed),
        ),
        check(
            "next_action_full_incremental_allowed",
            next_action["full_incremental_run_allowed_now"] or prebuild_source_refresh_allowed,
            str(next_action["full_incremental_run_allowed_now"] or prebuild_source_refresh_allowed),
        ),
        check("next_action_leak_free", next_action["leak_count"] == 0, str(next_action["leak_count"]), required=next_action["present"]),
        check("darwin_schema", not darwin["present"] or darwin["schema_version"] == DARWIN_SCHEMA, darwin["schema_version"], required=darwin["present"]),
        check("darwin_leak_free", not darwin["present"] or darwin["leak_count"] == 0, str(darwin["leak_count"]), required=darwin["present"]),
        check("readiness_release_ready", not readiness["present"] or readiness["release_ready"] or prebuild_source_refresh_allowed, str(readiness["release_ready"]), required=readiness["present"]),
        check(
            "readiness_package_candidate_ready",
            not readiness["present"] or readiness["package_candidate_ready"] or prebuild_source_refresh_allowed,
            str(readiness["package_candidate_ready"]),
            required=readiness["present"],
        ),
        check("raw_secret_keys_absent", not raw_secret_keys, ",".join(raw_secret_keys) or "none"),
        check("forbidden_execution_flags_false", not forbidden_true_flags, ",".join(forbidden_true_flags) or "none"),
        check("sanitized_output_leak_free", input_leak_count == 0, str(input_leak_count)),
    ]
    failed = [row["check_id"] for row in checks if row["required"] == "true" and row["status"] != "passed"]
    full_incremental_allowed = not failed
    if not next_action["present"] and not prebuild_auth_gate_present:
        decision = INCOMPLETE_DECISION
    elif full_incremental_allowed:
        decision = READY_DECISION
    else:
        decision = BLOCKED_DECISION
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "report_only": True,
        "full_incremental_candidate_run_allowed_now": full_incremental_allowed,
        "source_refresh_allowed_now": full_incremental_allowed
        and (next_action["source_refresh_allowed_now"] or prebuild_source_refresh_allowed),
        "docker_worker_allowed_now": full_incremental_allowed,
        "release_actions_allowed_now": False,
        "write_actions_allowed_now": False,
        "next_action_summary": next_action,
        "darwin_summary": darwin,
        "readiness_summary": readiness,
        "auth_recovery_summary": auth_recovery,
        "checks": checks,
        "failed_required_check_ids": failed,
        "counts": {
            "failed_required_check_count": len(failed),
            "next_action_task_count": next_action["task_count"],
            "darwin_prompt_count": darwin["prompt_count"],
        },
        "inputs": {
            "next_action_packet": safe_repo_path(next_action_path),
            "darwin_scorecard": safe_repo_path(darwin_path),
            "readiness": safe_repo_path(readiness_path),
            "auth_recovery": safe_repo_path(auth_recovery_path),
        },
        "next_gate": "run_full_incremental_candidate_pipeline" if full_incremental_allowed else "continue_ordered_next_action_recovery",
        "forbidden_true_flags": forbidden_true_flags,
        "source_input_raw_secret_key_count": len(raw_secret_keys),
        "raw_url_private_path_secret_leak_count": input_leak_count,
    }
    for key in FORBIDDEN_EXECUTION_FLAGS:
        report[key] = False
    return report


def render_markdown(report: dict[str, Any]) -> str:
    next_action = as_dict(report.get("next_action_summary"))
    darwin = as_dict(report.get("darwin_summary"))
    return "\n".join(
        [
            "# OpenClaw Weekly Full Incremental Preflight Gate",
            "",
            f"- decision: `{report.get('decision')}`",
            f"- full_incremental_candidate_run_allowed_now: `{report.get('full_incremental_candidate_run_allowed_now')}`",
            f"- source_refresh_allowed_now: `{report.get('source_refresh_allowed_now')}`",
            f"- docker_worker_allowed_now: `{report.get('docker_worker_allowed_now')}`",
            f"- next_action_task_count: `{next_action.get('task_count')}`",
            f"- next_action_decision: `{next_action.get('decision')}`",
            f"- darwin_score: `{darwin.get('score_total')}/{darwin.get('score_max')}`",
            f"- failed_required_check_ids: `{', '.join(str(value) for value in as_list(report.get('failed_required_check_ids'))) or '[]'}`",
            f"- leak_count: `{report.get('raw_url_private_path_secret_leak_count')}`",
            "",
            "Boundary: report-only. No source refresh, Docker worker, OCR, vision/model API, CloudBase write, DB write, package patch, deploy, upload, review, release, or secret read occurred.",
        ]
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--next-action-packet", type=Path, default=DEFAULT_NEXT_ACTION)
    parser.add_argument("--darwin-scorecard", type=Path, default=DEFAULT_DARWIN)
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument("--auth-recovery", type=Path)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_gate(
        next_action_path=args.next_action_packet,
        darwin_path=args.darwin_scorecard,
        readiness_path=args.readiness,
        auth_recovery_path=args.auth_recovery,
    )
    write_json(args.report, report)
    write_text(args.scorecard, render_markdown(report))
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "full_incremental_candidate_run_allowed_now": report["full_incremental_candidate_run_allowed_now"],
                "report": safe_repo_path(args.report),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["full_incremental_candidate_run_allowed_now"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
