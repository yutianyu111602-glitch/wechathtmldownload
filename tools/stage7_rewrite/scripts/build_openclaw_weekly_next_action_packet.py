#!/usr/bin/env python3
"""Build a no-write OpenClaw weekly next-action packet.

The packet turns current readiness/auth/package-quality/Darwin evidence into an
ordered, machine-readable action list. It does not refresh sources, call vision
models, upload CloudBase files, patch packages, deploy, sync, upload, review, or
release.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_PUBLISH_DIR = REPORTS_ROOT / "openclaw_weekly_daily_20260606_060904"
DEFAULT_READINESS = DEFAULT_PUBLISH_DIR / "openclaw_weekly_daily_readiness_summary.round67_prebuild_qr_endpoint_frontend_contract.json"
DEFAULT_AUTH = (
    REPORTS_ROOT
    / "openclaw_exporter_auth_round67_prebuild_20260606_094830"
    / "weekly_exporter_auth_recovery_preflight.json"
)
DEFAULT_QUALITY_DIR = REPORTS_ROOT / "openclaw_package_quality_frontend_contract_round67_20260606_094949"
DEFAULT_CANDIDATE_QUALITY = DEFAULT_QUALITY_DIR / "candidate_fix2_merged_current.quality.json"
DEFAULT_RUNTIME_QUALITY = DEFAULT_QUALITY_DIR / "runtime_current_release.quality.json"
DEFAULT_DARWIN = (
    REPORTS_ROOT
    / "openclaw_darwin_scorecard_20260606_round67_prebuild"
    / "openclaw_weekly_darwin_scorecard.json"
)
DEFAULT_SOURCE_MATERIAL_CONTROLLER = (
    REPORTS_ROOT
    / "weekly_source_material_recovery_controller_packet_round73_20260606"
    / "source_material_recovery_controller_packet.json"
)
DEFAULT_AUTH_QR_RETRY_CONTROLLER = (
    REPORTS_ROOT
    / "weekly_exporter_auth_qr_retry_controller_packet_round76_20260606"
    / "weekly_exporter_auth_qr_retry_controller_packet.json"
)
DEFAULT_CURRENT_RELEASE_QUALITY_RECOVERY_PACKET = (
    REPORTS_ROOT
    / "openclaw_current_release_quality_recovery_packet_round81_20260606"
    / "openclaw_current_release_quality_recovery_packet.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "openclaw_weekly_next_action_packet_20260606_round68"


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def bool_value(value: Any) -> bool:
    return value is True


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def text_value(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def safe_path(path: Path) -> str:
    """Return a portable evidence label without leaking local absolute paths."""
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return candidate.name


def source_summary(quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool_value(quality.get("ok")),
        "item_count": int_value(quality.get("item_count")),
        "missing_internal_poster_count": int_value(quality.get("missing_internal_poster_count")),
        "invalid_poster_storage_count": int_value(quality.get("invalid_poster_storage_count")),
        "invalid_internal_poster_file_id_count": int_value(quality.get("invalid_internal_poster_file_id_count")),
        "public_or_temp_poster_url_count": int_value(quality.get("public_or_temp_poster_url_count")),
        "public_wechat_or_qpic_poster_count": int_value(quality.get("public_wechat_or_qpic_poster_count")),
        "runtime_poster_state_count": int_value(quality.get("runtime_poster_state_count")),
        "main_poster_selection_review_required_count": int_value(
            quality.get("main_poster_selection_review_required_count")
        ),
        "aggregate_child_poster_suppressed_count": int_value(quality.get("aggregate_child_poster_suppressed_count")),
        "aggregate_child_source_enabled_count": int_value(quality.get("aggregate_child_source_enabled_count")),
        "aggregate_child_source_hash_present_count": int_value(quality.get("aggregate_child_source_hash_present_count")),
        "aggregate_child_weak_date_evidence_count": int_value(quality.get("aggregate_child_weak_date_evidence_count")),
        "missing_geo_count": int_value(quality.get("missing_geo_count")),
        "manifest_provenance_issue_count": int_value(quality.get("manifest_provenance_issue_count")),
        "city_route_mismatch_count": int_value(quality.get("city_route_mismatch_count")),
        "hard_failures": quality.get("hard_failures", []) if isinstance(quality.get("hard_failures"), list) else [],
    }


def append_task(tasks: list[dict[str, Any]], **task: Any) -> None:
    task.setdefault("status", "blocked_report_only")
    task.setdefault("write_actions_allowed_now", False)
    task.setdefault("release_actions_allowed_now", False)
    tasks.append(task)


def source_material_controller_summary(controller: dict[str, Any]) -> dict[str, Any]:
    counts = controller.get("counts", {}) if isinstance(controller.get("counts"), dict) else {}
    packet = (
        controller.get("controller_release_packet", {})
        if isinstance(controller.get("controller_release_packet"), dict)
        else {}
    )
    return {
        "decision": controller.get("decision"),
        "selected_task_count": int_value(counts.get("selected_task_count")),
        "selected_candidate_source_count": int_value(counts.get("selected_candidate_source_count")),
        "offline_ocr_material_ready_task_count": int_value(counts.get("offline_ocr_material_ready_task_count")),
        "network_or_exporter_required_task_count": int_value(counts.get("network_or_exporter_required_task_count")),
        "source_material_next_action_task_id": text_value(packet.get("source_material_next_action_task_id")),
        "controller_release_created_by_this_packet": bool_value(
            controller.get("controller_release_created_by_this_packet")
        ),
        "actual_source_material_acquisition_allowed_now": bool_value(
            controller.get("actual_source_material_acquisition_allowed_now")
        ),
        "docker_worker_allowed_now": bool_value(controller.get("docker_worker_allowed_now")),
        "raw_url_private_path_secret_leak_count": int_value(controller.get("raw_url_private_path_secret_leak_count")),
        "source_input_raw_url_private_path_secret_leak_count": int_value(
            controller.get("source_input_raw_url_private_path_secret_leak_count")
        ),
    }


def auth_qr_retry_controller_summary(controller: dict[str, Any]) -> dict[str, Any]:
    counts = controller.get("counts", {}) if isinstance(controller.get("counts"), dict) else {}
    packet = (
        controller.get("controller_release_packet", {})
        if isinstance(controller.get("controller_release_packet"), dict)
        else {}
    )
    return {
        "decision": controller.get("decision"),
        "root_cause_class": text_value(controller.get("root_cause_class")),
        "auth_recovery_ready": bool_value(controller.get("auth_recovery_ready")),
        "session_requires_auth": bool_value(controller.get("session_requires_auth")),
        "qr_upstream_unavailable": bool_value(controller.get("qr_upstream_unavailable")),
        "next_action_task_id": text_value(packet.get("next_action_task_id")),
        "controller_release_created_by_this_packet": bool_value(
            controller.get("controller_release_created_by_this_packet")
        ),
        "actual_auth_retry_allowed_now": bool_value(controller.get("actual_auth_retry_allowed_now")),
        "actual_auth_sync_allowed_now": bool_value(controller.get("actual_auth_sync_allowed_now")),
        "source_refresh_allowed_now": bool_value(controller.get("source_refresh_allowed_now")),
        "docker_worker_allowed_now": bool_value(controller.get("docker_worker_allowed_now")),
        "qr_endpoint_content_length": int_value(counts.get("qr_endpoint_content_length")),
        "qr_attempts_observed": int_value(counts.get("qr_attempts_observed")),
        "max_no_secret_probe_attempts_per_controller_run": int_value(
            counts.get("max_no_secret_probe_attempts_per_controller_run")
        ),
        "failed_required_check_count": int_value(counts.get("failed_required_check_count")),
        "raw_url_private_path_secret_leak_count": int_value(controller.get("raw_url_private_path_secret_leak_count")),
        "source_input_raw_secret_key_count": int_value(controller.get("source_input_raw_secret_key_count")),
    }


def current_release_quality_recovery_summary(packet: dict[str, Any]) -> dict[str, Any]:
    current_quality = packet.get("current_release_quality", {}) if isinstance(packet.get("current_release_quality"), dict) else {}
    poster = packet.get("poster_recovery", {}) if isinstance(packet.get("poster_recovery"), dict) else {}
    main_poster = (
        packet.get("main_poster_selection_recovery", {})
        if isinstance(packet.get("main_poster_selection_recovery"), dict)
        else {}
    )
    geo = packet.get("geo_recovery", {}) if isinstance(packet.get("geo_recovery"), dict) else {}
    return {
        "decision": packet.get("decision"),
        "report_only": bool_value(packet.get("report_only")),
        "item_count": int_value(current_quality.get("item_count")),
        "missing_internal_poster_count": int_value(current_quality.get("missing_internal_poster_count")),
        "invalid_poster_storage_count": int_value(current_quality.get("invalid_poster_storage_count")),
        "public_or_temp_poster_url_count": int_value(current_quality.get("public_or_temp_poster_url_count")),
        "public_wechat_or_qpic_poster_count": int_value(current_quality.get("public_wechat_or_qpic_poster_count")),
        "main_poster_selection_review_required_count": int_value(
            current_quality.get("main_poster_selection_review_required_count")
        ),
        "missing_geo_count": int_value(current_quality.get("missing_geo_count")),
        "poster_recovery_required": bool_value(poster.get("required")),
        "poster_recovery_next_action_task_id": text_value(poster.get("next_action_task_id")),
        "poster_article_image_ocr_recovery_count": int_value(poster.get("article_image_ocr_recovery_count")),
        "poster_public_upload_candidate_count": int_value(poster.get("public_upload_candidate_count")),
        "all_missing_posters_are_aggregate_children": bool_value(poster.get("all_missing_posters_are_aggregate_children")),
        "main_poster_selection_recovery_required": bool_value(main_poster.get("required")),
        "main_poster_selection_next_action_task_id": text_value(main_poster.get("next_action_task_id")),
        "main_poster_review_required_count": int_value(main_poster.get("review_required_count")),
        "selected_poster_rejected_count": int_value(main_poster.get("selected_poster_rejected_count")),
        "accepted_selected_poster_count": int_value(main_poster.get("accepted_selected_poster_count")),
        "main_poster_manual_review_count": int_value(main_poster.get("manual_review_count")),
        "main_poster_provider_error_count": int_value(main_poster.get("provider_error_count")),
        "main_poster_vision_api_executed_in_batch": bool_value(
            main_poster.get("vision_api_executed_in_batch")
        ),
        "main_poster_mimo_api_executed_in_batch": bool_value(main_poster.get("mimo_api_executed_in_batch")),
        "geo_recovery_required": bool_value(geo.get("required")),
        "geo_recovery_next_action_task_id": text_value(geo.get("next_action_task_id")),
        "task_count": int_value(packet.get("task_count")),
        "failed_required_check_count": len(packet.get("failed_required_check_ids", []))
        if isinstance(packet.get("failed_required_check_ids"), list)
        else 0,
        "full_incremental_run_allowed_now": bool_value(packet.get("full_incremental_run_allowed_now")),
        "source_refresh_allowed_now": bool_value(packet.get("source_refresh_allowed_now")),
        "docker_worker_allowed_now": bool_value(packet.get("docker_worker_allowed_now")),
        "raw_url_private_path_secret_leak_count": int_value(packet.get("raw_url_private_path_secret_leak_count")),
    }


def build_packet(
    *,
    readiness: dict[str, Any],
    auth: dict[str, Any],
    candidate_quality: dict[str, Any],
    runtime_quality: dict[str, Any],
    darwin: dict[str, Any],
    readiness_path: Path,
    auth_path: Path,
    candidate_quality_path: Path,
    runtime_quality_path: Path,
    darwin_path: Path,
    source_material_controller: dict[str, Any] | None = None,
    source_material_controller_path: Path | None = None,
    auth_qr_retry_controller: dict[str, Any] | None = None,
    auth_qr_retry_controller_path: Path | None = None,
    current_release_quality_recovery_packet: dict[str, Any] | None = None,
    current_release_quality_recovery_packet_path: Path | None = None,
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    auth_ready = bool_value(auth.get("auth_recovery_ready"))
    qr_blocked = bool_value(auth.get("qr_upstream_unavailable"))
    release_ready = bool_value(readiness.get("release_ready"))
    package_candidate_ready = bool_value(readiness.get("package_candidate_ready"))
    failed_check_ids = [str(v) for v in readiness.get("failed_check_ids", [])] if isinstance(readiness.get("failed_check_ids"), list) else []
    exporter_freshness = readiness.get("exporter_freshness_preflight", {})
    exporter_freshness = exporter_freshness if isinstance(exporter_freshness, dict) else {}
    source_material = readiness.get("poster_ocr_source_material_preflight", {})
    source_material = source_material if isinstance(source_material, dict) else {}
    candidate = source_summary(candidate_quality)
    runtime = source_summary(runtime_quality)
    darwin_score_total = int_value(darwin.get("score_total"))
    darwin_score_max = int_value(darwin.get("score_max"))
    source_controller = source_material_controller if isinstance(source_material_controller, dict) else {}
    source_controller_summary = source_material_controller_summary(source_controller) if source_controller else {}
    auth_qr_controller = auth_qr_retry_controller if isinstance(auth_qr_retry_controller, dict) else {}
    auth_qr_controller_summary = (
        auth_qr_retry_controller_summary(auth_qr_controller) if auth_qr_controller else {}
    )
    current_release_recovery = (
        current_release_quality_recovery_packet
        if isinstance(current_release_quality_recovery_packet, dict)
        else {}
    )
    current_release_recovery_summary = (
        current_release_quality_recovery_summary(current_release_recovery) if current_release_recovery else {}
    )
    leak_count = max(
        int_value(auth.get("raw_url_private_path_secret_leak_count")),
        int_value(darwin.get("raw_url_private_path_secret_leak_count")),
        int_value(source_controller_summary.get("raw_url_private_path_secret_leak_count")),
        int_value(source_controller_summary.get("source_input_raw_url_private_path_secret_leak_count")),
        int_value(auth_qr_controller_summary.get("raw_url_private_path_secret_leak_count")),
        int_value(auth_qr_controller_summary.get("source_input_raw_secret_key_count")),
        int_value(current_release_recovery_summary.get("raw_url_private_path_secret_leak_count")),
    )

    if not auth_ready or qr_blocked:
        auth_task_extra: dict[str, Any] = {}
        if auth_qr_controller_summary:
            auth_task_extra = {
                "auth_qr_retry_controller_decision": auth_qr_controller_summary.get("decision"),
                "auth_qr_retry_root_cause_class": auth_qr_controller_summary.get("root_cause_class"),
                "auth_qr_retry_controller_release_created": auth_qr_controller_summary.get(
                    "controller_release_created_by_this_packet"
                ),
                "actual_auth_retry_allowed_now": auth_qr_controller_summary.get("actual_auth_retry_allowed_now"),
                "actual_auth_sync_allowed_now": auth_qr_controller_summary.get("actual_auth_sync_allowed_now"),
                "source_refresh_allowed_now_from_controller": auth_qr_controller_summary.get(
                    "source_refresh_allowed_now"
                ),
                "docker_worker_allowed_now": auth_qr_controller_summary.get("docker_worker_allowed_now"),
                "qr_endpoint_content_length": auth_qr_controller_summary.get("qr_endpoint_content_length"),
                "qr_attempts_observed": auth_qr_controller_summary.get("qr_attempts_observed"),
                "max_no_secret_probe_attempts_per_controller_run": auth_qr_controller_summary.get(
                    "max_no_secret_probe_attempts_per_controller_run"
                ),
            }
        append_task(
            tasks,
            task_id="openclaw_weekly:exporter_auth:qr_upstream_recovery",
            task_type="exporter_auth_recovery",
            blocker_class="source_refresh_blocker",
            evidence_path=safe_path(auth_path),
            root_cause_class=text_value(auth.get("auth_recovery_root_cause_class")),
            next_safe_actions=[
                "retry no-secret QR endpoint diagnostic after upstream mptext/WeChat QR service recovers",
                "require a nonempty article-list smoke before source refresh",
                "do not run source refresh, OCR, vision APIs, CloudBase upload, package patch, deploy, upload, review, or release while auth_recovery_ready is false",
            ],
            **auth_task_extra,
        )

    source_material_blocked = (
        "poster_ocr_source_material_missing" in failed_check_ids
        or "exporter_freshness_not_ready" in failed_check_ids
        or exporter_freshness.get("freshness_ready") is False
        or source_material.get("material_ready") is False
        or bool_value(exporter_freshness.get("source_material_account_date_gap_detected"))
        or int_value(source_material.get("network_or_exporter_required_task_count")) > 0
    )
    if source_material_blocked:
        source_task_extra: dict[str, Any] = {}
        if source_controller_summary:
            source_task_extra = {
                "source_material_controller_decision": source_controller_summary.get("decision"),
                "source_material_controller_selected_task_count": source_controller_summary.get("selected_task_count"),
                "source_material_controller_candidate_source_count": source_controller_summary.get(
                    "selected_candidate_source_count"
                ),
                "source_material_controller_release_created": source_controller_summary.get(
                    "controller_release_created_by_this_packet"
                ),
                "actual_source_material_acquisition_allowed_now": source_controller_summary.get(
                    "actual_source_material_acquisition_allowed_now"
                ),
                "docker_worker_allowed_now": source_controller_summary.get("docker_worker_allowed_now"),
            }
        append_task(
            tasks,
            task_id="openclaw_weekly:source_material:freshness_or_acquisition_recovery",
            task_type="source_material_or_freshness_recovery",
            blocker_class="source_material_blocker",
            evidence_path=safe_path(readiness_path),
            freshness_ready=bool_value(exporter_freshness.get("freshness_ready")),
            material_ready=bool_value(source_material.get("material_ready")),
            offline_ocr_material_ready_task_count=int_value(source_material.get("offline_ocr_material_ready_task_count")),
            network_or_exporter_required_task_count=int_value(source_material.get("network_or_exporter_required_task_count")),
            source_material_account_date_gap_detected=bool_value(
                exporter_freshness.get("source_material_account_date_gap_detected")
            ),
            candidate_published_max=text_value(exporter_freshness.get("candidate_published_max")),
            queue_max_post_date=text_value(exporter_freshness.get("queue_max_post_date")),
            **source_task_extra,
            next_safe_actions=[
                "restore exporter/latest-queue source material before actual poster OCR",
                "require selected aggregate-child OCR tasks to resolve local article/image material or a separate controller-authorized source-material acquisition",
                "do not run OCR, StepFun/MiMo vision, CloudBase upload, package patch, source-action repair, deploy, upload, review, or release while source material is missing",
            ],
        )

    if not candidate["ok"]:
        append_task(
            tasks,
            task_id="openclaw_weekly:candidate_package:frontend_cloudfile_quality",
            task_type="candidate_package_quality_repair",
            blocker_class="package_quality_blocker",
            evidence_path=safe_path(candidate_quality_path),
            item_count=candidate["item_count"],
            missing_internal_poster_count=candidate["missing_internal_poster_count"],
            invalid_poster_storage_count=candidate["invalid_poster_storage_count"],
            invalid_internal_poster_file_id_count=candidate["invalid_internal_poster_file_id_count"],
            public_or_temp_poster_url_count=candidate["public_or_temp_poster_url_count"],
            public_wechat_or_qpic_poster_count=candidate["public_wechat_or_qpic_poster_count"],
            runtime_poster_state_count=candidate["runtime_poster_state_count"],
            missing_geo_count=candidate["missing_geo_count"],
            next_safe_actions=[
                "rebuild or repair the candidate so every item stores cloud://.../weekly-posters/YYYYMMDD/... in poster_file_id/posterFileId/cloudFileId",
                "keep public qpic/mmbiz/temp/wxfile poster values out of package fields",
                "repair stale manifest provenance, city route drift, aggregate-child source/hash/date issues, and missing geo before deploy/upload gates",
            ],
        )

    if (
        runtime["missing_internal_poster_count"] or runtime["aggregate_child_poster_suppressed_count"]
    ) and not current_release_recovery_summary.get("poster_recovery_required"):
        append_task(
            tasks,
            task_id="openclaw_weekly:runtime_package:aggregate_child_cloudbase_posters",
            task_type="runtime_aggregate_child_poster_recovery",
            blocker_class="frontend_contract_blocker",
            evidence_path=safe_path(runtime_quality_path),
            item_count=runtime["item_count"],
            missing_internal_poster_count=runtime["missing_internal_poster_count"],
            aggregate_child_poster_suppressed_count=runtime["aggregate_child_poster_suppressed_count"],
            public_wechat_or_qpic_poster_count=runtime["public_wechat_or_qpic_poster_count"],
            next_safe_actions=[
                "use the aggregate-child poster OCR/source-material lane to find real child activity posters",
                "only after explicit write authorization may CloudBase file IDs be produced and patched",
                "frontend temp-URL support is not a substitute for backend cloud:// package truth",
            ],
        )

    if current_release_recovery_summary.get("poster_recovery_required"):
        append_task(
            tasks,
            task_id=current_release_recovery_summary.get("poster_recovery_next_action_task_id")
            or "openclaw_weekly:poster_fileid:aggregate_child_ocr_recovery",
            task_type="current_release_quality_recovery_packet_poster_fileid",
            blocker_class="frontend_backend_contract_blocker",
            evidence_path=safe_path(current_release_quality_recovery_packet_path)
            if current_release_quality_recovery_packet_path
            else "",
            item_count=current_release_recovery_summary.get("item_count"),
            missing_internal_poster_count=current_release_recovery_summary.get("missing_internal_poster_count"),
            invalid_poster_storage_count=current_release_recovery_summary.get("invalid_poster_storage_count"),
            public_or_temp_poster_url_count=current_release_recovery_summary.get("public_or_temp_poster_url_count"),
            public_wechat_or_qpic_poster_count=current_release_recovery_summary.get(
                "public_wechat_or_qpic_poster_count"
            ),
            article_image_ocr_recovery_count=current_release_recovery_summary.get(
                "poster_article_image_ocr_recovery_count"
            ),
            public_upload_candidate_count=current_release_recovery_summary.get(
                "poster_public_upload_candidate_count"
            ),
            all_missing_posters_are_aggregate_children=current_release_recovery_summary.get(
                "all_missing_posters_are_aggregate_children"
            ),
            next_safe_actions=[
                "follow current-release recovery packet before any full incremental run",
                "recover real child activity posters and CloudBase file IDs; do not store frontend temp URLs",
                "do not run OCR, StepFun/MiMo, CloudBase upload, package patch, deploy, upload, review, or release without later controller gates",
            ],
        )

    if current_release_recovery_summary.get("main_poster_selection_recovery_required"):
        append_task(
            tasks,
            task_id=current_release_recovery_summary.get("main_poster_selection_next_action_task_id")
            or "openclaw_weekly:poster_selection:current_release_mimo_rejected_recovery",
            task_type="current_release_quality_recovery_packet_main_poster_selection",
            blocker_class="semantic_main_poster_quality_blocker",
            evidence_path=safe_path(current_release_quality_recovery_packet_path)
            if current_release_quality_recovery_packet_path
            else "",
            item_count=current_release_recovery_summary.get("item_count"),
            review_required_count=current_release_recovery_summary.get(
                "main_poster_review_required_count"
            ),
            selected_poster_rejected_count=current_release_recovery_summary.get(
                "selected_poster_rejected_count"
            ),
            accepted_selected_poster_count=current_release_recovery_summary.get(
                "accepted_selected_poster_count"
            ),
            manual_review_count=current_release_recovery_summary.get("main_poster_manual_review_count"),
            provider_error_count=current_release_recovery_summary.get("main_poster_provider_error_count"),
            vision_api_executed_in_batch=current_release_recovery_summary.get(
                "main_poster_vision_api_executed_in_batch"
            ),
            mimo_api_executed_in_batch=current_release_recovery_summary.get(
                "main_poster_mimo_api_executed_in_batch"
            ),
            next_safe_actions=[
                "use existing MiMo rejection evidence to replace bad selected posters from article body images",
                "demote venue notices, opening-hours cards, QR/social cards, maps, menus, safety rules, recruitment cards, and generic photos",
                "rerun MiMo main-poster review after selection changes and before CloudBase/package/deploy gates",
                "do not run CloudBase upload, package patch, deploy, upload, review, or release without later controller gates",
            ],
        )

    if (candidate["missing_geo_count"] or runtime["missing_geo_count"]) and not current_release_recovery_summary.get(
        "geo_recovery_required"
    ):
        append_task(
            tasks,
            task_id="openclaw_weekly:package_quality:missing_geo_repair",
            task_type="missing_geo_repair_queue",
            blocker_class="package_quality_blocker",
            evidence_path=safe_path(runtime_quality_path),
            candidate_missing_geo_count=candidate["missing_geo_count"],
            runtime_missing_geo_count=runtime["missing_geo_count"],
            next_safe_actions=[
                "repair missing geo through source-backed map evidence and locked place fields",
                "do not guess coordinates or mark coordinate freshness green without provider/source evidence",
            ],
        )

    if current_release_recovery_summary.get("geo_recovery_required"):
        append_task(
            tasks,
            task_id=current_release_recovery_summary.get("geo_recovery_next_action_task_id")
            or "openclaw_weekly:geo:current_missing_geo_recovery",
            task_type="current_release_quality_recovery_packet_missing_geo",
            blocker_class="package_quality_debt",
            evidence_path=safe_path(current_release_quality_recovery_packet_path)
            if current_release_quality_recovery_packet_path
            else "",
            missing_geo_count=current_release_recovery_summary.get("missing_geo_count"),
            next_safe_actions=[
                "repair current missing geo with source-backed map evidence",
                "rerun quality/readiness/full incremental gates after poster and geo recovery",
            ],
        )

    if darwin_score_total and darwin_score_max and darwin_score_total >= darwin_score_max:
        darwin_interpretation = "score_green_not_release_authority"
    elif darwin_score_total and darwin_score_max:
        darwin_interpretation = "score_partial_not_release_authority"
    else:
        darwin_interpretation = "score_incomplete_or_missing"

    if release_ready and package_candidate_ready and auth_ready and not tasks:
        decision = "openclaw_weekly_next_action_packet_ready_for_full_incremental_candidate_run"
    else:
        decision = "openclaw_weekly_next_action_packet_blocked_report_only"

    return {
        "schema_version": "openclaw_weekly_next_action_packet.v1",
        "generated_at": now_cst(),
        "decision": decision,
        "release_ready": release_ready,
        "package_candidate_ready": package_candidate_ready,
        "auth_recovery_ready": auth_ready,
        "source_refresh_allowed_now": auth_ready and not qr_blocked,
        "full_incremental_run_allowed_now": release_ready and package_candidate_ready and auth_ready and not tasks,
        "task_count": len(tasks),
        "next_action_tasks": tasks,
        "inputs": {
            "readiness": safe_path(readiness_path),
            "auth_recovery": safe_path(auth_path),
            "candidate_quality": safe_path(candidate_quality_path),
            "runtime_quality": safe_path(runtime_quality_path),
            "darwin_scorecard": safe_path(darwin_path),
            "source_material_controller": safe_path(source_material_controller_path)
            if source_material_controller_path
            else "",
            "auth_qr_retry_controller": safe_path(auth_qr_retry_controller_path)
            if auth_qr_retry_controller_path
            else "",
            "current_release_quality_recovery_packet": safe_path(current_release_quality_recovery_packet_path)
            if current_release_quality_recovery_packet_path
            else "",
        },
        "source_summaries": {
            "readiness_decision": readiness.get("decision"),
            "auth_decision": auth.get("decision"),
            "auth_root_cause_class": auth.get("auth_recovery_root_cause_class"),
            "exporter_freshness_preflight": {
                "decision": exporter_freshness.get("decision"),
                "freshness_ready": bool_value(exporter_freshness.get("freshness_ready")),
                "queue_max_post_date": text_value(exporter_freshness.get("queue_max_post_date")),
                "candidate_published_max": text_value(exporter_freshness.get("candidate_published_max")),
                "source_material_account_date_gap_detected": bool_value(
                    exporter_freshness.get("source_material_account_date_gap_detected")
                ),
            },
            "poster_ocr_source_material_preflight": {
                "decision": source_material.get("decision"),
                "material_ready": bool_value(source_material.get("material_ready")),
                "offline_ocr_material_ready_task_count": int_value(
                    source_material.get("offline_ocr_material_ready_task_count")
                ),
                "network_or_exporter_required_task_count": int_value(
                    source_material.get("network_or_exporter_required_task_count")
                ),
            },
            "candidate_quality": candidate,
            "runtime_quality": runtime,
            "darwin_decision": darwin.get("decision"),
            "darwin_score_total": darwin_score_total,
            "darwin_score_max": darwin_score_max,
            "darwin_interpretation": darwin_interpretation,
            "source_material_controller": source_controller_summary,
            "auth_qr_retry_controller": auth_qr_controller_summary,
            "current_release_quality_recovery_packet": current_release_recovery_summary,
        },
        "horizontal_comparison": {
            "frontend_runtime_adapter": "green_for_display_when_backend_has_cloud_file_id",
            "backend_candidate_package": "blocked" if not candidate["ok"] else "ok",
            "runtime_current_package": "blocked" if not runtime["ok"] else "ok",
            "exporter_source_refresh": "blocked" if not auth_ready or qr_blocked else "ready",
            "auth_qr_retry_controller": "ready_report_only"
            if auth_qr_controller_summary
            and auth_qr_controller_summary.get("decision")
            == "weekly_exporter_auth_qr_retry_controller_packet_ready_report_only_waiting_operator_or_retry_window"
            else ("missing_or_not_consumed" if (not auth_ready or qr_blocked) else "not_required"),
            "source_material_for_ocr": "blocked" if source_material_blocked else "ready_or_not_required",
            "source_material_controller": "ready_report_only"
            if source_controller_summary
            and source_controller_summary.get("decision")
            == "weekly_source_material_recovery_controller_packet_ready_report_only_waiting_controller_release"
            else ("missing_or_not_consumed" if source_material_blocked else "not_required"),
            "current_release_quality_recovery_packet": "blocked_report_only"
            if current_release_recovery_summary
            and (
                current_release_recovery_summary.get("poster_recovery_required")
                or current_release_recovery_summary.get("main_poster_selection_recovery_required")
                or current_release_recovery_summary.get("geo_recovery_required")
            )
            else ("missing_or_not_consumed" if not current_release_recovery_summary else "not_required"),
            "darwin_skill_loop": darwin_interpretation,
        },
        "vertical_gate_chain": [
            {"gate": "prebuild_exporter_auth", "status": "ready" if auth_ready else "blocked"},
            {"gate": "source_refresh", "status": "ready" if auth_ready and not qr_blocked else "blocked"},
            {"gate": "source_material_for_ocr", "status": "blocked" if source_material_blocked else "ready_or_not_required"},
            {"gate": "candidate_package_quality", "status": "ready" if candidate["ok"] else "blocked"},
            {"gate": "runtime_frontend_contract", "status": "ready" if runtime["ok"] else "blocked"},
            {"gate": "cloudbase_poster_fileid_write", "status": "blocked_explicit_write_gate_required"},
            {"gate": "deploy_upload_release", "status": "ready" if release_ready else "blocked"},
        ],
        "safety": {
            "report_only": True,
            "secret_read": False,
            "source_refresh_executed": False,
            "network_fetch_executed": False,
            "ocr_executed": False,
            "vision_api_executed": False,
            "stepfun_api_executed": False,
            "mimo_api_executed": False,
            "cloudbase_storage_write_executed": False,
            "cloudbase_db_write_executed": False,
            "db2_write_executed": False,
            "db3_write_executed": False,
            "package_patch_executed": False,
            "cloudrun_deploy_executed": False,
            "miniprogram_upload_executed": False,
            "wechat_review_submitted": False,
            "public_release_executed": False,
            "raw_url_private_path_secret_leak_count": leak_count,
        },
    }


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# OpenClaw Weekly Next Action Packet",
        "",
        f"Generated: `{packet['generated_at']}`",
        "",
        "## Decision",
        "",
        f"`{packet['decision']}`",
        "",
        "## Gate State",
        "",
        f"- Auth recovery ready: `{packet['auth_recovery_ready']}`",
        f"- Source refresh allowed now: `{packet['source_refresh_allowed_now']}`",
        f"- Package candidate ready: `{packet['package_candidate_ready']}`",
        f"- Release ready: `{packet['release_ready']}`",
        f"- Full incremental run allowed now: `{packet['full_incremental_run_allowed_now']}`",
        f"- Task count: `{packet['task_count']}`",
        "",
        "## Next Actions",
        "",
    ]
    for task in packet["next_action_tasks"]:
        lines.append(f"- `{task['task_id']}` `{task['task_type']}` `{task['blocker_class']}`")
    if not packet["next_action_tasks"]:
        lines.append("- `<none>`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No source refresh, OCR, vision API, CloudBase write, DB2/DB3 write, package patch, deploy, upload, review, or release occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "openclaw_weekly_next_action_packet.json"
    md_path = out_dir / "openclaw_weekly_next_action_packet.md"
    tasks_path = out_dir / "openclaw_weekly_next_action_tasks.jsonl"
    write_json(json_path, packet)
    md_path.write_text(render_markdown(packet), encoding="utf-8")
    tasks_path.write_text(
        "".join(json.dumps(task, ensure_ascii=False, sort_keys=True) + "\n" for task in packet["next_action_tasks"]),
        encoding="utf-8",
    )
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument("--auth-recovery", type=Path, default=DEFAULT_AUTH)
    parser.add_argument("--candidate-quality", type=Path, default=DEFAULT_CANDIDATE_QUALITY)
    parser.add_argument("--runtime-quality", type=Path, default=DEFAULT_RUNTIME_QUALITY)
    parser.add_argument("--darwin-scorecard", type=Path, default=DEFAULT_DARWIN)
    parser.add_argument("--source-material-controller", type=Path, default=DEFAULT_SOURCE_MATERIAL_CONTROLLER)
    parser.add_argument("--auth-qr-retry-controller", type=Path, default=DEFAULT_AUTH_QR_RETRY_CONTROLLER)
    parser.add_argument("--current-release-quality-recovery-packet", type=Path, default=DEFAULT_CURRENT_RELEASE_QUALITY_RECOVERY_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(
        readiness=read_json(args.readiness),
        auth=read_json(args.auth_recovery),
        candidate_quality=read_json(args.candidate_quality),
        runtime_quality=read_json(args.runtime_quality),
        darwin=read_json(args.darwin_scorecard),
        readiness_path=args.readiness,
        auth_path=args.auth_recovery,
        candidate_quality_path=args.candidate_quality,
        runtime_quality_path=args.runtime_quality,
        darwin_path=args.darwin_scorecard,
        source_material_controller=read_json(args.source_material_controller)
        if args.source_material_controller.exists()
        else {},
        source_material_controller_path=args.source_material_controller
        if args.source_material_controller.exists()
        else None,
        auth_qr_retry_controller=read_json(args.auth_qr_retry_controller)
        if args.auth_qr_retry_controller.exists()
        else {},
        auth_qr_retry_controller_path=args.auth_qr_retry_controller
        if args.auth_qr_retry_controller.exists()
        else None,
        current_release_quality_recovery_packet=read_json(args.current_release_quality_recovery_packet)
        if args.current_release_quality_recovery_packet.exists()
        else {},
        current_release_quality_recovery_packet_path=args.current_release_quality_recovery_packet
        if args.current_release_quality_recovery_packet.exists()
        else None,
    )
    paths = write_reports(packet, args.out_dir)
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        print(f"decision={packet['decision']}")
        print(f"task_count={packet['task_count']}")
        print(f"source_refresh_allowed_now={packet['source_refresh_allowed_now']}")
        print(f"full_incremental_run_allowed_now={packet['full_incremental_run_allowed_now']}")
        print(f"json={safe_path(paths['json'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
