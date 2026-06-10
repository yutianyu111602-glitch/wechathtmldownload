#!/usr/bin/env python3
"""Build a report-only recovery packet for current-release quality blockers.

The latest mini-program frontend adapter can render CloudBase ``cloud://`` file
IDs by resolving temporary URLs at runtime. It cannot create missing backend
file IDs. This packet turns the current-release quality report into a safe
next-action queue without running OCR, calling vision APIs, uploading
CloudBase files, patching packages, or touching release surfaces.
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
DEFAULT_QUALITY_REPORT = (
    REPORTS_ROOT
    / "openclaw_weekly_daily_nonllm_20260606_132233"
    / "current_release_quality_gate.json"
)
DEFAULT_OUT_DIR = (
    REPORTS_ROOT
    / "openclaw_current_release_quality_recovery_packet_round81_20260606"
)
SCHEMA_VERSION = "openclaw_current_release_quality_recovery_packet.v1"
QUALITY_SCHEMA = "weekly_release_package_quality.v1"
POSTER_RECOVERY_TASK_ID = "openclaw_weekly:poster_fileid:aggregate_child_ocr_recovery"
GEO_RECOVERY_TASK_ID = "openclaw_weekly:geo:current_missing_geo_recovery"
RERUN_GATE_TASK_ID = "openclaw_weekly:gate:rerun_quality_readiness_full_incremental"
RAW_URL_RE = re.compile(
    r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://|blob:",
    re.I,
)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
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


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def bool_value(value: Any) -> bool:
    return value is True


def text_value(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def redact_text(value: Any) -> str:
    text = text_value(value)
    text = RAW_URL_RE.sub("[redacted-url]", text)
    text = PRIVATE_PATH_RE.sub("[redacted-path]", text)
    text = SECRET_RE.sub("[redacted-secret]", text)
    return text


def safe_repo_path(path: Path | None) -> str:
    if not path:
        return ""
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return candidate.name


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(RAW_URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def check(check_id: str, passed: bool, evidence: str, required: bool = True) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "required": required,
        "status": "passed" if passed else "failed",
        "evidence": redact_text(evidence),
    }


def item_id(row: dict[str, Any]) -> str:
    return redact_text(row.get("id"))


def is_aggregate_child(row: dict[str, Any]) -> bool:
    return bool(row.get("aggregation_child") is True or item_id(row).startswith("agg-child-"))


def sanitize_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item_id(row),
        "title": redact_text(row.get("title")),
        "event_date_start": redact_text(row.get("event_date_start")),
        "event_date_end": redact_text(row.get("event_date_end")),
        "city": [redact_text(value) for value in as_list(row.get("city"))],
        "city_keys": [redact_text(value) for value in as_list(row.get("city_keys"))],
        "venue": redact_text(row.get("venue")),
        "aggregation_child": is_aggregate_child(row),
    }


def sanitize_missing_poster_item(row: dict[str, Any]) -> dict[str, Any]:
    item = sanitize_item(row)
    item.update(
        {
            "requires_cloudbase_file_id": True,
            "required_file_id_pattern": "cloud://.../weekly-posters/YYYYMMDD/...",
            "required_poster_storage": "cloudbase",
            "recovery_lane": "article_image_ocr_main_poster_recovery",
            "must_not_inherit_parent_overview_poster": item["aggregation_child"],
        }
    )
    return item


def sanitize_missing_geo_item(row: dict[str, Any]) -> dict[str, Any]:
    item = sanitize_item(row)
    item.update(
        {
            "requires_source_backed_geo": True,
            "must_not_guess_coordinate": True,
        }
    )
    return item


def summary_from_work_orders(work_orders: dict[str, Any]) -> dict[str, Any]:
    if not work_orders:
        return {}
    rows = [row for row in as_list(work_orders.get("work_orders")) if isinstance(row, dict)]
    return {
        "schema_version": text_value(work_orders.get("schema_version")),
        "decision": text_value(work_orders.get("decision")),
        "report_only": bool_value(work_orders.get("report_only")),
        "missing_internal_poster_count": int_value(work_orders.get("missing_internal_poster_count")),
        "work_order_count": int_value(work_orders.get("work_order_count")),
        "public_url_upload_candidate_count": int_value(work_orders.get("public_url_upload_candidate_count")),
        "article_image_ocr_recovery_count": int_value(work_orders.get("no_public_url_recovery_count")),
        "aggregate_child_recovery_count": int_value(work_orders.get("aggregate_child_recovery_count")),
        "raw_public_url_leak_count": int_value(work_orders.get("raw_public_url_leak_count")),
        "all_work_orders_are_aggregate_children": bool(rows) and all(is_aggregate_child(row) for row in rows),
    }


def summary_from_split_packet(split_packet: dict[str, Any]) -> dict[str, Any]:
    if not split_packet:
        return {}
    counts = as_dict(split_packet.get("counts"))
    lane_status = as_dict(split_packet.get("mixed_lane_status"))
    return {
        "schema_version": text_value(split_packet.get("schema_version")),
        "decision": text_value(split_packet.get("decision")),
        "report_only": bool_value(split_packet.get("report_only")),
        "missing_internal_poster_count": int_value(counts.get("missing_internal_poster_count")),
        "public_url_upload_candidate_count": int_value(counts.get("public_url_upload_candidate_count")),
        "article_image_ocr_recovery_count": int_value(counts.get("article_image_ocr_recovery_count")),
        "aggregate_child_recovery_count": int_value(counts.get("aggregate_child_recovery_count")),
        "ocr_only_recovery_required": bool_value(lane_status.get("ocr_only_recovery_required")),
        "public_upload_subset_can_clear_quality_gate": bool_value(
            lane_status.get("public_upload_subset_can_clear_quality_gate")
        ),
        "raw_url_private_path_secret_leak_count": int_value(split_packet.get("raw_url_private_path_secret_leak_count")),
        "controller_release_created_by_this_packet": bool_value(
            split_packet.get("controller_release_created_by_this_packet")
        ),
        "article_image_ocr_allowed_now": bool_value(split_packet.get("article_image_ocr_allowed_now")),
        "cloudbase_storage_write_allowed_now": bool_value(split_packet.get("cloudbase_storage_write_allowed_now")),
        "package_patch_allowed_now": bool_value(split_packet.get("package_patch_allowed_now")),
    }


def no_execution_flags() -> dict[str, bool]:
    return {
        "source_refresh_allowed_now": False,
        "docker_worker_allowed_now": False,
        "network_fetch_allowed_now": False,
        "ocr_allowed_now": False,
        "stepfun_api_allowed_now": False,
        "mimo_api_allowed_now": False,
        "cloudbase_storage_write_allowed_now": False,
        "cloudbase_db_write_allowed_now": False,
        "package_patch_allowed_now": False,
        "db2_write_allowed_now": False,
        "db3_write_allowed_now": False,
        "cloudrun_deploy_allowed_now": False,
        "miniprogram_upload_allowed_now": False,
        "wechat_review_allowed_now": False,
        "public_release_allowed_now": False,
        "secret_read": False,
    }


def build_packet(
    *,
    quality: dict[str, Any],
    quality_path: Path,
    poster_work_orders: dict[str, Any] | None = None,
    poster_work_orders_path: Path | None = None,
    poster_split_packet: dict[str, Any] | None = None,
    poster_split_packet_path: Path | None = None,
    poster_limit: int = 20,
    geo_limit: int = 20,
) -> dict[str, Any]:
    poster_work_orders = poster_work_orders if isinstance(poster_work_orders, dict) else {}
    poster_split_packet = poster_split_packet if isinstance(poster_split_packet, dict) else {}
    missing_poster_items = [row for row in as_list(quality.get("missing_internal_poster_items")) if isinstance(row, dict)]
    invalid_storage_items = [row for row in as_list(quality.get("invalid_poster_storage_items")) if isinstance(row, dict)]
    missing_geo_items = [row for row in as_list(quality.get("missing_geo_items")) if isinstance(row, dict)]
    missing_internal_poster_count = int_value(quality.get("missing_internal_poster_count"))
    invalid_poster_storage_count = int_value(quality.get("invalid_poster_storage_count"))
    public_or_temp_poster_url_count = int_value(quality.get("public_or_temp_poster_url_count"))
    public_wechat_or_qpic_poster_count = int_value(quality.get("public_wechat_or_qpic_poster_count"))
    missing_geo_count = int_value(quality.get("missing_geo_count"))
    hard_failures = [text_value(value) for value in as_list(quality.get("hard_failures"))]
    all_missing_posters_are_aggregate_children = bool(missing_poster_items) and all(
        is_aggregate_child(row) for row in missing_poster_items
    )
    work_order_summary = summary_from_work_orders(poster_work_orders)
    split_summary = summary_from_split_packet(poster_split_packet)
    public_upload_candidate_count = int_value(work_order_summary.get("public_url_upload_candidate_count"))
    ocr_recovery_count = int_value(work_order_summary.get("article_image_ocr_recovery_count"))
    if not work_order_summary:
        public_upload_candidate_count = 0 if public_wechat_or_qpic_poster_count == 0 else public_wechat_or_qpic_poster_count
        ocr_recovery_count = missing_internal_poster_count - public_upload_candidate_count
    poster_recovery_required = missing_internal_poster_count > 0 or invalid_poster_storage_count > 0
    geo_recovery_required = missing_geo_count > 0
    current_release_quality_hard_blocker = bool(
        poster_recovery_required or public_or_temp_poster_url_count or public_wechat_or_qpic_poster_count or hard_failures
    )

    next_action_tasks: list[dict[str, Any]] = []
    if poster_recovery_required:
        next_action_tasks.append(
            {
                "task_id": POSTER_RECOVERY_TASK_ID,
                "task_type": "current_release_cloudbase_poster_fileid_recovery",
                "blocker_class": "frontend_backend_contract_blocker",
                "priority": 1,
                "evidence_path": safe_repo_path(quality_path),
                "missing_internal_poster_count": missing_internal_poster_count,
                "invalid_poster_storage_count": invalid_poster_storage_count,
                "public_or_temp_poster_url_count": public_or_temp_poster_url_count,
                "public_wechat_or_qpic_poster_count": public_wechat_or_qpic_poster_count,
                "article_image_ocr_recovery_count": max(0, ocr_recovery_count),
                "public_upload_candidate_count": public_upload_candidate_count,
                "all_missing_posters_are_aggregate_children": all_missing_posters_are_aggregate_children,
                "next_safe_actions": [
                    "enumerate article body images for each aggregate child",
                    "rank main activity poster with OCR/layout rules before vision review",
                    "use StepFun/MiMo only as ambiguity reviewers after source material is fresh",
                    "upload selected posters to CloudBase only after separate controller release",
                    "patch package only after every missing poster has a cloud file ID and poster_storage=cloudbase",
                ],
            }
        )
    if geo_recovery_required:
        next_action_tasks.append(
            {
                "task_id": GEO_RECOVERY_TASK_ID,
                "task_type": "current_release_missing_geo_recovery",
                "blocker_class": "package_quality_debt",
                "priority": 2 if poster_recovery_required else 1,
                "evidence_path": safe_repo_path(quality_path),
                "missing_geo_count": missing_geo_count,
                "next_safe_actions": [
                    "repair coordinates only with source-backed map evidence",
                    "preserve locked place fields and do not guess coordinates",
                    "rerun package quality after geo repair evidence is generated",
                ],
            }
        )
    if poster_recovery_required or geo_recovery_required or not bool_value(quality.get("ok")):
        next_action_tasks.append(
            {
                "task_id": RERUN_GATE_TASK_ID,
                "task_type": "rerun_quality_readiness_and_full_incremental_gate",
                "blocker_class": "gate_revalidation",
                "priority": 3 if poster_recovery_required else 2,
                "evidence_path": safe_repo_path(quality_path),
                "next_safe_actions": [
                    "rerun validate_weekly_release_package_quality.py",
                    "rerun OpenClaw readiness summary",
                    "rerun full incremental preflight gate before any source refresh or Docker worker",
                ],
            }
        )

    safety = no_execution_flags()
    front_end_adaptation_contract = {
        "backend_package_truth": "cloudbase_internal_file_id",
        "accepted_package_file_id_pattern": "cloud://.../weekly-posters/YYYYMMDD/...",
        "poster_storage_required": "cloudbase",
        "frontend_runtime_resolution": "wx.cloud.getTempFileURL converts cloud file IDs to display temp URLs",
        "temp_url_policy": "display_only_never_package_truth",
        "latest_frontend_adapter_is_not_a_missing_fileid_repair": True,
    }
    packet: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "",
        "report_only": True,
        "quality_report": safe_repo_path(quality_path),
        "poster_work_orders_report": safe_repo_path(poster_work_orders_path),
        "poster_split_controller_packet": safe_repo_path(poster_split_packet_path),
        "front_end_adaptation_contract": front_end_adaptation_contract,
        "current_release_quality": {
            "ok": bool_value(quality.get("ok")),
            "item_count": int_value(quality.get("item_count")),
            "manifest_item_count": int_value(quality.get("manifest_item_count")),
            "hard_failures": hard_failures,
            "missing_internal_poster_count": missing_internal_poster_count,
            "invalid_poster_storage_count": invalid_poster_storage_count,
            "invalid_internal_poster_file_id_count": int_value(quality.get("invalid_internal_poster_file_id_count")),
            "public_or_temp_poster_url_count": public_or_temp_poster_url_count,
            "public_wechat_or_qpic_poster_count": public_wechat_or_qpic_poster_count,
            "runtime_poster_state_count": int_value(quality.get("runtime_poster_state_count")),
            "missing_geo_count": missing_geo_count,
            "fail_on_missing_geo": bool_value(quality.get("fail_on_missing_geo")),
        },
        "poster_recovery": {
            "required": poster_recovery_required,
            "next_action_task_id": POSTER_RECOVERY_TASK_ID if poster_recovery_required else "",
            "missing_internal_poster_count": missing_internal_poster_count,
            "invalid_poster_storage_count": invalid_poster_storage_count,
            "article_image_ocr_recovery_count": max(0, ocr_recovery_count),
            "public_upload_candidate_count": public_upload_candidate_count,
            "all_missing_posters_are_aggregate_children": all_missing_posters_are_aggregate_children,
            "missing_internal_poster_queue": [
                sanitize_missing_poster_item(row) for row in missing_poster_items[:poster_limit]
            ],
            "invalid_poster_storage_queue": [
                sanitize_missing_poster_item(row) for row in invalid_storage_items[:poster_limit]
            ],
            "work_order_summary": work_order_summary,
            "split_controller_summary": split_summary,
        },
        "geo_recovery": {
            "required": geo_recovery_required,
            "next_action_task_id": GEO_RECOVERY_TASK_ID if geo_recovery_required else "",
            "missing_geo_count": missing_geo_count,
            "missing_geo_queue": [sanitize_missing_geo_item(row) for row in missing_geo_items[:geo_limit]],
        },
        "current_release_quality_hard_blocker": current_release_quality_hard_blocker,
        "full_incremental_run_allowed_now": False,
        "source_refresh_allowed_now": False,
        "docker_worker_allowed_now": False,
        "next_action_tasks": next_action_tasks,
        "task_count": len(next_action_tasks),
        "safety": safety,
    }
    packet_leaks = leak_count(packet)
    checks = [
        check("quality_schema", text_value(quality.get("schema_version")) == QUALITY_SCHEMA, text_value(quality.get("schema_version"))),
        check("quality_not_ok_or_recovery_needed", not bool_value(quality.get("ok")) or poster_recovery_required or geo_recovery_required, f"ok={quality.get('ok')} poster={poster_recovery_required} geo={geo_recovery_required}"),
        check("missing_poster_count_matches_queue", len(missing_poster_items) == missing_internal_poster_count, f"{len(missing_poster_items)} == {missing_internal_poster_count}"),
        check("invalid_storage_count_matches_queue", len(invalid_storage_items) == invalid_poster_storage_count, f"{len(invalid_storage_items)} == {invalid_poster_storage_count}"),
        check("no_public_or_temp_poster_pollution", public_or_temp_poster_url_count == 0 and public_wechat_or_qpic_poster_count == 0, f"public_or_temp={public_or_temp_poster_url_count} public_wechat_or_qpic={public_wechat_or_qpic_poster_count}"),
        check("geo_count_matches_queue", len(missing_geo_items) == missing_geo_count, f"{len(missing_geo_items)} == {missing_geo_count}"),
        check("poster_task_precedes_geo_task", not (poster_recovery_required and geo_recovery_required) or next_action_tasks[0]["task_id"] == POSTER_RECOVERY_TASK_ID, next_action_tasks[0]["task_id"] if next_action_tasks else ""),
        check("all_execution_flags_false", all(value is False for value in safety.values()), "all safety flags false"),
        check("sanitized_output_leak_free", packet_leaks == 0, str(packet_leaks)),
    ]
    if poster_work_orders:
        checks.extend(
            [
                check("work_orders_report_only", bool_value(poster_work_orders.get("report_only")), str(poster_work_orders.get("report_only"))),
                check("work_orders_leak_free", int_value(poster_work_orders.get("raw_public_url_leak_count")) == 0, str(poster_work_orders.get("raw_public_url_leak_count"))),
            ]
        )
    if poster_split_packet:
        checks.extend(
            [
                check("split_packet_report_only", bool_value(poster_split_packet.get("report_only")), str(poster_split_packet.get("report_only"))),
                check("split_packet_no_write_authority", not any(
                    bool_value(poster_split_packet.get(key))
                    for key in (
                        "article_image_ocr_allowed_now",
                        "cloudbase_storage_write_allowed_now",
                        "package_patch_allowed_now",
                        "controller_release_created_by_this_packet",
                    )
                ), "split packet kept report-only"),
                check("split_packet_leak_free", int_value(poster_split_packet.get("raw_url_private_path_secret_leak_count")) == 0, str(poster_split_packet.get("raw_url_private_path_secret_leak_count"))),
            ]
        )
    failed = [row["check_id"] for row in checks if row["required"] and row["status"] != "passed"]
    if failed:
        decision = "openclaw_current_release_quality_recovery_packet_blocked_report_only_failed_checks"
    elif poster_recovery_required:
        decision = "openclaw_current_release_quality_recovery_packet_blocked_report_only_poster_fileid_recovery"
    elif geo_recovery_required:
        decision = "openclaw_current_release_quality_recovery_packet_blocked_report_only_geo_recovery"
    elif bool_value(quality.get("ok")):
        decision = "openclaw_current_release_quality_recovery_packet_no_recovery_required"
    else:
        decision = "openclaw_current_release_quality_recovery_packet_blocked_report_only_quality_not_ok"
    packet["decision"] = decision
    packet["checks"] = checks
    packet["failed_required_check_ids"] = failed
    packet["raw_url_private_path_secret_leak_count"] = packet_leaks
    return packet


def render_markdown(packet: dict[str, Any]) -> str:
    quality = as_dict(packet.get("current_release_quality"))
    poster = as_dict(packet.get("poster_recovery"))
    geo = as_dict(packet.get("geo_recovery"))
    lines = [
        "# OpenClaw Current Release Quality Recovery Packet",
        "",
        f"Decision: `{packet['decision']}`",
        "",
        "## Current Package",
        "",
        f"- Items: `{quality.get('item_count')}`",
        f"- Missing internal posters: `{quality.get('missing_internal_poster_count')}`",
        f"- Invalid poster storage: `{quality.get('invalid_poster_storage_count')}`",
        f"- Public/temp poster count: `{quality.get('public_or_temp_poster_url_count')}`",
        f"- Public WeChat/qpic poster count: `{quality.get('public_wechat_or_qpic_poster_count')}`",
        f"- Missing geo: `{quality.get('missing_geo_count')}`",
        "",
        "## Frontend Contract",
        "",
        "Backend package truth remains CloudBase `cloud://.../weekly-posters/YYYYMMDD/...` plus `poster_storage=cloudbase`. The frontend resolves those file IDs to temp URLs at runtime; temp URLs and local file paths are not package truth.",
        "",
        "## Recovery",
        "",
        f"- Poster recovery required: `{poster.get('required')}`",
        f"- Poster OCR recovery rows: `{poster.get('article_image_ocr_recovery_count')}`",
        f"- Poster public upload candidates: `{poster.get('public_upload_candidate_count')}`",
        f"- All missing posters are aggregate children: `{poster.get('all_missing_posters_are_aggregate_children')}`",
        f"- Geo recovery required: `{geo.get('required')}`",
        "",
        "## Next Actions",
        "",
    ]
    for task in as_list(packet.get("next_action_tasks")):
        if isinstance(task, dict):
            lines.append(f"- `{task.get('task_id')}` `{task.get('task_type')}`")
    if not packet.get("next_action_tasks"):
        lines.append("- `<none>`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No source refresh, Docker worker, network fetch, OCR, StepFun/MiMo call, CloudBase write, DB2/DB3 write, package patch, deploy, upload, review, or release occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality-report", type=Path, default=DEFAULT_QUALITY_REPORT)
    parser.add_argument("--poster-work-orders", type=Path)
    parser.add_argument("--poster-split-packet", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--scorecard", type=Path)
    parser.add_argument("--poster-limit", type=int, default=20)
    parser.add_argument("--geo-limit", type=int, default=20)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report_path = args.report or args.out_dir / "openclaw_current_release_quality_recovery_packet.json"
    scorecard_path = args.scorecard or args.out_dir / "openclaw_current_release_quality_recovery_packet.md"
    packet = build_packet(
        quality=read_json(args.quality_report),
        quality_path=args.quality_report,
        poster_work_orders=read_json(args.poster_work_orders),
        poster_work_orders_path=args.poster_work_orders,
        poster_split_packet=read_json(args.poster_split_packet),
        poster_split_packet_path=args.poster_split_packet,
        poster_limit=args.poster_limit,
        geo_limit=args.geo_limit,
    )
    write_json(report_path, packet)
    write_text(scorecard_path, render_markdown(packet))
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": packet["decision"],
                    "task_count": packet["task_count"],
                    "poster_recovery_required": packet["poster_recovery"]["required"],
                    "geo_recovery_required": packet["geo_recovery"]["required"],
                    "full_incremental_run_allowed_now": packet["full_incremental_run_allowed_now"],
                    "report": safe_repo_path(report_path),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return 0 if packet["raw_url_private_path_secret_leak_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
