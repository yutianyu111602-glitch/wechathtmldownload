#!/usr/bin/env python3
"""Build a Darwin-style scorecard for the OpenClaw weekly skill/docker lane.

The scorecard is deterministic and report-only. It reads skill text plus current
gate reports, then emits 9-dimension Darwin scoring, regression prompts, and
horizontal/vertical comparisons. It does not call LLMs, OCR, vision APIs,
CloudBase, Docker, or any release surface.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = "openclaw_weekly_darwin_scorecard.v1"


def default_openclaw_skill_path(skill_name: str) -> Path:
    candidates = [Path.home() / ".openclaw" / "skills" / skill_name / "SKILL.md"]
    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        candidates.append(Path(hermes_home) / "skills" / skill_name / "SKILL.md")
    candidates.append(Path(r"F:\DevData\Hermes") / "skills" / skill_name / "SKILL.md")
    return next((path for path in candidates if path.is_file()), candidates[0])
DEFAULT_READINESS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_daily_20260606_060904"
    / "openclaw_weekly_daily_readiness_summary.round65_auth_recovery_frontend_contract.json"
)
DEFAULT_EXPORTER_FRESHNESS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_daily_20260606_060904"
    / "weekly_exporter_freshness_preflight.json"
)
DEFAULT_EXPORTER_AUTH_RECOVERY = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_exporter_auth_round65"
    / "weekly_exporter_auth_recovery_preflight.json"
)
DEFAULT_NEXT_ACTION_PACKET = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_next_action_packet_20260606_round68"
    / "openclaw_weekly_next_action_packet.json"
)
DEFAULT_SOURCE_MATERIAL_CONTROLLER = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_source_material_recovery_controller_packet_round73_20260606"
    / "source_material_recovery_controller_packet.json"
)
DEFAULT_SOURCE_MATERIAL_RUNTIME_PREFLIGHT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_source_material_recovery_runtime_release_preflight_round86_20260606"
    / "source_material_recovery_runtime_release_preflight.json"
)
DEFAULT_SOURCE_MATERIAL_CONTROLLER_RELEASE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_source_material_recovery_controller_release_round87_20260606"
    / "source_material_recovery_controller_release.json"
)
DEFAULT_AUTH_QR_RETRY_CONTROLLER = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_exporter_auth_qr_retry_controller_packet_round76_20260606"
    / "weekly_exporter_auth_qr_retry_controller_packet.json"
)
DEFAULT_FULL_INCREMENTAL_PREFLIGHT_GATE = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_weekly_full_incremental_preflight_gate_round78_20260606"
    / "openclaw_weekly_full_incremental_preflight_gate.json"
)
DEFAULT_CURRENT_RELEASE_QUALITY_RECOVERY_PACKET = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "openclaw_current_release_quality_recovery_packet_round81_20260606"
    / "openclaw_current_release_quality_recovery_packet.json"
)
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_darwin_scorecard_20260606_round65"
RAW_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|mmbiz\.qpic\.cn|mmecoa\.qpic\.cn|qpic\.cn|wxfile://", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\|/mnt/[a-z]/|/home/pc/|\\\\wsl\.localhost\\|D:\\DDownload\\)")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|authorization\s*[:=]|api[_-]?key\s*[:=]|cookie\s*[:=]|password\s*[:=]|secret\s*[:=]|sk-[a-z0-9_-]{12,})"
)
FORBIDDEN_RELEASE_FLAGS = (
    "cloudbase_storage_write_executed",
    "cloudbase_db_write_executed",
    "db2_write_executed",
    "db3_write_executed",
    "cloudrun_deploy_executed",
    "cloudbase_sync_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
    "public_release_executed",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def read_json(path: Path) -> dict[str, Any]:
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
    return bool(value)


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def safe_repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(RAW_URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def skill_name(skill_text: str, fallback: str) -> str:
    match = re.search(r"(?m)^name:\s*([A-Za-z0-9_.:-]+)\s*$", skill_text)
    return match.group(1) if match else fallback


def has_all(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return all(needle.casefold() in lowered for needle in needles)


def score(score_id: str, value: int, max_value: int, evidence: str) -> dict[str, Any]:
    return {"id": score_id, "score": value, "max": max_value, "evidence": evidence}


def prompt(prompt_id: str, text: str, expected: str, required_signals: list[str]) -> dict[str, Any]:
    return {
        "id": prompt_id,
        "prompt": text,
        "expected_behavior": expected,
        "required_signals": required_signals,
    }


def score_skills(
    daily_text: str,
    docker_text: str,
    readiness: dict[str, Any],
    exporter: dict[str, Any],
    auth_recovery: dict[str, Any],
    source_material_controller: dict[str, Any] | None = None,
    auth_qr_retry_controller: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    combined = "\n".join([daily_text, docker_text])
    failed_ids = {str(v) for v in as_list(readiness.get("failed_check_ids"))}
    exporter_summary = as_dict(readiness.get("exporter_freshness_preflight"))
    auth_summary = as_dict(readiness.get("exporter_auth_recovery_preflight"))
    source_material_summary = as_dict(readiness.get("poster_ocr_source_material_preflight"))
    quality = as_dict(readiness.get("quality"))
    vertical = as_list(readiness.get("vertical_gate_chain"))
    boundary = as_dict(readiness.get("boundary"))
    exporter_boundary = as_dict(exporter.get("boundary"))
    auth_boundary = as_dict(auth_recovery.get("boundary"))
    session_auth_blocker_present = (
        int_value(exporter_summary.get("invalid_session_error_count")) > 0
        or auth_summary.get("session_requires_auth") is True
        or auth_recovery.get("session_requires_auth") is True
    )
    source_material_gap_present = (
        "poster_ocr_source_material_missing" in failed_ids
        or exporter_summary.get("source_material_account_date_gap_detected") is True
        or int_value(source_material_summary.get("network_or_exporter_required_task_count")) > 0
    )
    controller = source_material_controller or {}
    controller_counts = as_dict(controller.get("counts"))
    controller_packet = as_dict(controller.get("controller_release_packet"))
    source_material_controller_ready = (
        controller.get("decision") == "weekly_source_material_recovery_controller_packet_ready_report_only_waiting_controller_release"
        and int_value(controller_counts.get("selected_task_count")) > 0
        and int_value(controller_counts.get("selected_candidate_source_count")) > 0
        and int_value(controller_counts.get("network_or_exporter_required_task_count")) > 0
        and int_value(controller.get("raw_url_private_path_secret_leak_count")) == 0
        and controller.get("controller_release_created_by_this_packet") is False
        and controller.get("actual_source_material_acquisition_allowed_now") is False
        and controller.get("docker_worker_allowed_now") is False
    )
    auth_controller = auth_qr_retry_controller or {}
    auth_controller_counts = as_dict(auth_controller.get("counts"))
    auth_qr_retry_controller_ready = (
        auth_controller.get("decision")
        == "weekly_exporter_auth_qr_retry_controller_packet_ready_report_only_waiting_operator_or_retry_window"
        and str(auth_controller.get("root_cause_class") or "")
        == "upstream_scanloginqrcode_empty_after_valid_local_session"
        and auth_controller.get("controller_release_created_by_this_packet") is False
        and auth_controller.get("actual_auth_retry_allowed_now") is False
        and auth_controller.get("actual_auth_sync_allowed_now") is False
        and auth_controller.get("source_refresh_allowed_now") is False
        and auth_controller.get("docker_worker_allowed_now") is False
        and int_value(auth_controller_counts.get("failed_required_check_count")) == 0
        and int_value(auth_controller.get("raw_url_private_path_secret_leak_count")) == 0
    )

    return [
        score(
            "frontmatter_quality",
            5 if skill_name(daily_text, "") and skill_name(docker_text, "") else 3,
            5,
            "Both target skills expose names/frontmatter and route-specific descriptions.",
        ),
        score(
            "workflow_clarity",
            5
            if has_all(
                combined,
                ("Phase A", "Phase B", "Phase C", "weekly_exporter_freshness_preflight", "weekly_exporter_auth_recovery_preflight"),
            )
            else 4,
            5,
            "Daily skill keeps phase order; docker skill keeps profile/worker lane order; freshness/auth gates are named.",
        ),
        score(
            "failure_mechanism_encoding",
            5
            if "exporter_freshness_not_ready" in failed_ids
            and "exporter_auth_recovery_not_ready" in failed_ids
            and exporter_summary.get("freshness_ready") is False
            and auth_summary.get("auth_recovery_ready") is False
            and (bool_value(exporter.get("queue_stale_for_candidate_dates")) or source_material_gap_present)
            else 4,
            5,
            "Exporter invalid/stale queue, source-material gaps, and QR recovery failure are encoded as readiness failures instead of OCR/vision/front-end ambiguity.",
        ),
        score(
            "explicit_checkpoints",
            5
            if len(vertical) >= 10
            and any(as_dict(row).get("gate") == "exporter_freshness_preflight" for row in vertical)
            and any(as_dict(row).get("gate") == "exporter_auth_recovery_preflight" for row in vertical)
            else 4,
            5,
            "Vertical chain includes frontend/package, source material, exporter freshness, auth recovery, Docker canary, and poster write gates.",
        ),
        score(
            "actionable_specificity",
            5
            if (exporter_summary.get("queue_max_post_date") or source_material_controller_ready)
            and exporter_summary.get("candidate_published_max")
            and session_auth_blocker_present
            and auth_summary.get("qr_upstream_unavailable") is True
            else 4,
            5,
            "Report exposes queue/candidate source dates or a bounded source-material controller packet, auth/session blocker state, account/date gap, and QR upstream status.",
        ),
        score(
            "resource_integration",
            5
            if has_all(
                combined,
                (
                    "build_weekly_exporter_freshness_preflight.py",
                    "build_weekly_exporter_auth_recovery_preflight.py",
                    "summarize_openclaw_weekly_daily_readiness.py",
                ),
            )
            and (not source_material_gap_present or source_material_controller_ready)
            and (
                not auth_summary.get("qr_upstream_unavailable")
                or not auth_qr_retry_controller
                or auth_qr_retry_controller_ready
            )
            else 4,
            5,
            "Skill text, wrapper, readiness, auth/QR controller, source-material preflight/controller, exporter freshness/auth summaries, and package quality gate are tied together.",
        ),
        score(
            "overall_architecture",
            5 if readiness.get("package_candidate_ready") is False and readiness.get("release_ready") is False else 3,
            5,
            "The lane remains thin-dispatch/report-only and does not promote a blocked package to candidate-ready.",
        ),
        score(
            "tested_behavior",
            5
            if quality.get("runtime_poster_state_count") == 0
            and exporter.get("raw_url_private_path_secret_leak_count") == 0
            and auth_recovery.get("raw_url_private_path_secret_leak_count") == 0
            and readiness.get("decision") == "blocked_on_release_package_quality_gate"
            else 4,
            5,
            "Real report replay plus unit tests prove frontend runtime state is absent and exporter freshness/auth recovery are consumed.",
        ),
        score(
            "counterexamples_and_blacklist",
            5
            if all(not boundary.get(flag) for flag in FORBIDDEN_RELEASE_FLAGS)
            and all(not exporter_boundary.get(flag) for flag in FORBIDDEN_RELEASE_FLAGS)
            and all(not auth_boundary.get(flag) for flag in FORBIDDEN_RELEASE_FLAGS)
            and has_all(combined, ("Do not tune StepFun/MiMo/OCR", "CloudBase upload", "review, or release"))
            else 4,
            5,
            "OCR, StepFun/MiMo, CloudBase upload, package patch, deploy, sync, upload, review, and release remain blacklisted.",
        ),
    ]


def build_scorecard(
    *,
    daily_skill: Path,
    docker_skill: Path,
    readiness_path: Path,
    exporter_freshness_path: Path,
    exporter_auth_recovery_path: Path,
    next_action_packet_path: Path | None = None,
    source_material_controller_path: Path | None = None,
    source_material_runtime_preflight_path: Path | None = None,
    source_material_controller_release_path: Path | None = None,
    auth_qr_retry_controller_path: Path | None = None,
    full_incremental_preflight_gate_path: Path | None = None,
    current_release_quality_recovery_packet_path: Path | None = None,
) -> dict[str, Any]:
    daily_text = read_text(daily_skill)
    docker_text = read_text(docker_skill)
    readiness = read_json(readiness_path)
    exporter = read_json(exporter_freshness_path)
    auth_recovery = read_json(exporter_auth_recovery_path)
    next_action = read_json(next_action_packet_path) if next_action_packet_path and next_action_packet_path.exists() else {}
    source_material_controller = (
        read_json(source_material_controller_path)
        if source_material_controller_path and source_material_controller_path.exists()
        else {}
    )
    source_material_runtime_preflight = (
        read_json(source_material_runtime_preflight_path)
        if source_material_runtime_preflight_path and source_material_runtime_preflight_path.exists()
        else {}
    )
    source_material_controller_release = (
        read_json(source_material_controller_release_path)
        if source_material_controller_release_path and source_material_controller_release_path.exists()
        else {}
    )
    auth_qr_retry_controller = (
        read_json(auth_qr_retry_controller_path)
        if auth_qr_retry_controller_path and auth_qr_retry_controller_path.exists()
        else {}
    )
    full_incremental_preflight_gate = (
        read_json(full_incremental_preflight_gate_path)
        if full_incremental_preflight_gate_path and full_incremental_preflight_gate_path.exists()
        else {}
    )
    current_release_quality_recovery_packet = (
        read_json(current_release_quality_recovery_packet_path)
        if current_release_quality_recovery_packet_path and current_release_quality_recovery_packet_path.exists()
        else {}
    )
    scores = score_skills(
        daily_text,
        docker_text,
        readiness,
        exporter,
        auth_recovery,
        source_material_controller,
        auth_qr_retry_controller,
    )
    total = sum(row["score"] for row in scores)
    max_total = sum(row["max"] for row in scores)
    exporter_summary = as_dict(readiness.get("exporter_freshness_preflight"))
    auth_summary = as_dict(readiness.get("exporter_auth_recovery_preflight"))
    quality = as_dict(readiness.get("quality"))
    prompts = [
        prompt(
            "frontend-cloud-fileid-not-enough",
            "最新小程序前端已经能把 cloud:// 海报转 temp URL 了，能不能忽略 missing_internal_poster_count 直接跑增量发布？",
            "No. Frontend runtime conversion only displays existing CloudBase file IDs; package truth still needs cloud:// weekly-posters file IDs on every item.",
            ["missing_internal_poster_count remains a hard package blocker", "runtime temp URLs must not be persisted"],
        ),
        prompt(
            "frontend-temp-url-is-display-state-only",
            "包里每条都有 posterFileId，但 coverUrl 写成微信本地文件 scheme 或临时 HTTPS 图，前端能显示就算合格吗？",
            "No. local-file, temp, and proxy URLs are frontend display state only; the package must persist cloud file IDs and keep runtime state out of current.json.",
            ["public_or_temp_poster_url_count blocks package quality", "runtime_poster_state_count must stay 0"],
        ),
        prompt(
            "source-material-blocked-not-vision",
            "source-material preflight material_ready=false，但 StepFun/MiMo 可用，要不要直接调视觉模型选主海报？",
            "No. If exporter freshness is stale or invalid, the next action is exporter/session/queue refresh before OCR or vision.",
            ["exporter_freshness_not_ready", "queue_refresh_effective=false", "do not tune StepFun/MiMo/OCR first"],
        ),
        prompt(
            "qr-upstream-unavailable-not-auth-recovered",
            "QR 状态 login_session_ok=true，但 qr_saved=false、qr_bytes=0、decision=login_qr_upstream_unavailable，可以认为扫码通知成功并继续刷新队列吗？",
            "No. A valid local login session followed by empty QR bytes means the upstream scanloginqrcode route is still blocked; retry dashboard/QR auth recovery before source refresh, OCR, or vision.",
            [
                "auth_recovery_ready=false",
                "qr_upstream_unavailable=true",
                "qr_endpoint_root_cause_class=upstream_scanloginqrcode_empty_after_valid_local_session",
                "package_candidate_ready=false",
            ],
        ),
    ]
    if next_action:
        prompts.append(
            prompt(
                "next-action-packet-does-not-authorize-full-run",
                "当前 next-action packet 有待处理任务，Darwin 分数接近满分，还能直接跑全量增量吗？",
                "No. Next-action packet task_count>0 or full_incremental_run_allowed_now=false means continue report-only recovery in the listed order; do not start full incremental source refresh or release surfaces.",
                [
                    "read openclaw_weekly_next_action_packet.json",
                    "full_incremental_run_allowed_now=false",
                    "task_count>0",
                    "follow exporter auth before package/poster/geo repair",
                ],
            )
        )
    if source_material_controller:
        prompts.append(
            prompt(
                "source-material-controller-does-not-authorize-worker",
                "source-material controller packet ready 了，是不是可以直接跑 Docker source worker 或全量增量？",
                "No. A ready source-material controller packet is a report-only contract template; actual source-material acquisition, Docker worker execution, OCR, StepFun/MiMo, CloudBase upload, package patch, DB writes, deploy, upload, review, and release still require separate gates.",
                [
                    "controller_release_created_by_this_packet=false",
                    "actual_source_material_acquisition_allowed_now=false",
                    "docker_worker_allowed_now=false",
                    "source_material_next_action_task_id",
                ],
            )
        )
    if source_material_runtime_preflight:
        prompts.append(
            prompt(
                "source-material-runtime-preflight-does-not-authorize-worker",
                "source-material runtime release preflight 已经 ready 了，是否可以开始 Docker source worker、StepFun/MiMo OCR 或今天全量增量？",
                "No. A ready source-material runtime preflight only proves the controller and next-action packets are internally consistent and report-only; actual source-material acquisition, Docker worker execution, OCR, StepFun/MiMo, CloudBase upload, package patch, DB writes, deploy, upload, review, and release still require separate controller release and later gates.",
                [
                    "runtime_release_required_before_actual_worker=true",
                    "actual_source_material_acquisition_allowed_now=false",
                    "docker_worker_allowed_now=false",
                    "full_incremental_run_allowed_now=false",
                ],
            )
        )
    if source_material_controller_release:
        prompts.append(
            prompt(
                "source-material-controller-release-does-not-mean-runtime-executed",
                "source-material controller release packet ready 了，是不是说明 Docker source worker 已经跑完、今天全量增量可以开始？",
                "No. A controller release packet can create the future runtime contract, but it is still no-runtime-execution evidence; it must be followed by the actual bounded worker report, source-material preflight replay, poster OCR gates, package quality, next-action, and full-incremental hard gate before any full run.",
                [
                    "source_material_runtime_executed_by_this_packet=false",
                    "docker_worker_executed=false",
                    "full_incremental_run_allowed_now=false",
                    "worker summary/results/blockers artifacts required",
                ],
            )
        )
    if auth_qr_retry_controller:
        prompts.append(
            prompt(
                "auth-qr-controller-does-not-authorize-source-refresh",
                "auth/QR retry controller packet ready 了，是不是可以直接跑 source refresh、Docker worker 或全量增量？",
                "No. A ready auth/QR retry controller is a report-only retry plan; actual auth retry, auth sync, source refresh, Docker worker, OCR, StepFun/MiMo, CloudBase write, package patch, DB writes, deploy, upload, review, and release remain forbidden until separate gates are green.",
                [
                    "actual_auth_retry_allowed_now=false",
                    "actual_auth_sync_allowed_now=false",
                    "source_refresh_allowed_now=false",
                    "docker_worker_allowed_now=false",
                ],
            )
        )
    if full_incremental_preflight_gate:
        prompts.append(
            prompt(
                "full-incremental-hard-gate-blocks-execution",
                "full incremental preflight gate 是 blocked_report_only，但 Darwin/skill 测试都绿了，可以开始今天全量增量吗？",
                "No. The full-incremental hard gate is the final execution preflight; if it says full_incremental_candidate_run_allowed_now=false, keep following the ordered next-action recovery queue and do not start source refresh, Docker worker, OCR, StepFun/MiMo, CloudBase writes, package patch, deploy, upload, review, or release.",
                [
                    "full_incremental_candidate_run_allowed_now=false",
                    "source_refresh_allowed_now=false",
                    "docker_worker_allowed_now=false",
                    "next_action_task_count>0",
                ],
            )
        )
    if current_release_quality_recovery_packet:
        prompts.append(
            prompt(
                "current-release-quality-recovery-packet-blocks-full-run",
                "根据现在最新小程序前端适配，current-release recovery packet 已经指出 11 条缺 cloud:// poster fileId 和 6 条缺 geo，还能开始全量增量吗？",
                "No. The latest frontend can render existing cloud file IDs only; recovery packet poster_recovery_required or geo_recovery_required means continue report-only poster/geo recovery and keep full incremental, OCR, StepFun/MiMo, CloudBase upload, package patch, deploy, upload, review, and release blocked.",
                [
                    "poster_recovery_required=true",
                    "missing_internal_poster_count>0",
                    "geo_recovery_required=true",
                    "full_incremental_run_allowed_now=false",
                ],
            )
        )
    horizontal = {
        "frontend_runtime": {
            "state": "adapted",
            "runtime_poster_state_count": int_value(quality.get("runtime_poster_state_count")),
            "role": "convert CloudBase file IDs to temp URLs for display only",
        },
        "backend_package": {
            "missing_internal_poster_count": int_value(quality.get("missing_internal_poster_count")),
            "invalid_internal_poster_file_id_count": int_value(quality.get("invalid_internal_poster_file_id_count")),
            "invalid_poster_storage_count": int_value(quality.get("invalid_poster_storage_count")),
            "public_or_temp_poster_url_count": int_value(quality.get("public_or_temp_poster_url_count")),
            "public_wechat_or_qpic_poster_count": int_value(quality.get("public_wechat_or_qpic_poster_count")),
            "runtime_poster_state_count": int_value(quality.get("runtime_poster_state_count")),
            "role": "must carry CloudBase file IDs; blocks candidate readiness until fixed",
        },
        "exporter_refresh": {
            "queue_refresh_effective": bool_value(exporter_summary.get("queue_refresh_effective")),
            "invalid_session_error_count": int_value(exporter_summary.get("invalid_session_error_count")),
            "role": "source-material freshness gate before OCR/vision",
        },
        "exporter_auth_recovery": {
            "auth_recovery_ready": bool_value(auth_summary.get("auth_recovery_ready")),
            "session_requires_auth": bool_value(auth_summary.get("session_requires_auth")),
            "qr_upstream_unavailable": bool_value(auth_summary.get("qr_upstream_unavailable")),
            "qr_endpoint_root_cause_class": str(auth_summary.get("qr_endpoint_root_cause_class") or ""),
            "auth_recovery_root_cause_class": str(auth_summary.get("auth_recovery_root_cause_class") or ""),
            "role": "auth/QR recovery gate before source refresh and queue rebuild",
        },
        "vision_models": {
            "role": "ambiguity reviewers only after article material is fresh and enumerated",
            "allowed_now": False,
        },
    }
    if next_action:
        horizontal["next_action_packet"] = {
            "decision": next_action.get("decision"),
            "task_count": int_value(next_action.get("task_count")),
            "source_refresh_allowed_now": bool_value(next_action.get("source_refresh_allowed_now")),
            "full_incremental_run_allowed_now": bool_value(next_action.get("full_incremental_run_allowed_now")),
            "role": "machine-readable ordered blocker recovery queue, not release authority",
        }
    if source_material_controller:
        controller_counts = as_dict(source_material_controller.get("counts"))
        controller_packet = as_dict(source_material_controller.get("controller_release_packet"))
        horizontal["source_material_controller"] = {
            "decision": source_material_controller.get("decision"),
            "selected_task_count": int_value(controller_counts.get("selected_task_count")),
            "selected_candidate_source_count": int_value(controller_counts.get("selected_candidate_source_count")),
            "network_or_exporter_required_task_count": int_value(
                controller_counts.get("network_or_exporter_required_task_count")
            ),
            "source_material_next_action_task_id": str(controller_packet.get("source_material_next_action_task_id") or ""),
            "controller_release_created_by_this_packet": bool_value(
                source_material_controller.get("controller_release_created_by_this_packet")
            ),
            "actual_source_material_acquisition_allowed_now": bool_value(
                source_material_controller.get("actual_source_material_acquisition_allowed_now")
            ),
            "docker_worker_allowed_now": bool_value(source_material_controller.get("docker_worker_allowed_now")),
            "role": "bounded report-only source-material recovery contract, not worker authorization",
        }
    if source_material_runtime_preflight:
        runtime_counts = as_dict(source_material_runtime_preflight.get("counts"))
        runtime_plan = as_dict(source_material_runtime_preflight.get("runtime_release_preflight"))
        horizontal["source_material_runtime_preflight"] = {
            "decision": source_material_runtime_preflight.get("decision"),
            "selected_task_count": int_value(runtime_counts.get("selected_task_count")),
            "selected_candidate_source_count": int_value(runtime_counts.get("selected_candidate_source_count")),
            "network_or_exporter_required_task_count": int_value(
                runtime_counts.get("network_or_exporter_required_task_count")
            ),
            "runtime_release_required_before_actual_worker": bool_value(
                runtime_plan.get("runtime_release_required_before_actual_worker")
            ),
            "controller_release_created_by_this_packet": bool_value(
                source_material_runtime_preflight.get("controller_release_created_by_this_packet")
            ),
            "actual_source_material_acquisition_allowed_now": bool_value(
                source_material_runtime_preflight.get("actual_source_material_acquisition_allowed_now")
            ),
            "docker_worker_allowed_now": bool_value(source_material_runtime_preflight.get("docker_worker_allowed_now")),
            "full_incremental_run_allowed_now": bool_value(
                source_material_runtime_preflight.get("full_incremental_run_allowed_now")
            ),
            "role": "report-only runtime release preflight; verifies no worker/full-incremental authorization",
        }
    if source_material_controller_release:
        release_counts = as_dict(source_material_controller_release.get("counts"))
        release_packet = as_dict(source_material_controller_release.get("controller_release"))
        horizontal["source_material_controller_release"] = {
            "decision": source_material_controller_release.get("decision"),
            "selected_task_count": int_value(release_counts.get("selected_task_count")),
            "selected_candidate_source_count": int_value(release_counts.get("selected_candidate_source_count")),
            "controller_release_created_by_this_packet": bool_value(
                release_packet.get("controller_release_created_by_this_packet")
            ),
            "source_material_runtime_allowed_by_this_packet": bool_value(
                release_packet.get("source_material_runtime_allowed_by_this_packet")
            ),
            "source_material_runtime_executed_by_this_packet": bool_value(
                release_packet.get("source_material_runtime_executed_by_this_packet")
            ),
            "full_incremental_run_allowed_now": bool_value(
                source_material_controller_release.get("full_incremental_run_allowed_now")
            ),
            "role": "no-runtime-execution controller release contract; actual worker result still required",
        }
    if auth_qr_retry_controller:
        controller_counts = as_dict(auth_qr_retry_controller.get("counts"))
        controller_packet = as_dict(auth_qr_retry_controller.get("controller_release_packet"))
        horizontal["auth_qr_retry_controller"] = {
            "decision": auth_qr_retry_controller.get("decision"),
            "root_cause_class": str(auth_qr_retry_controller.get("root_cause_class") or ""),
            "next_action_task_id": str(controller_packet.get("next_action_task_id") or ""),
            "qr_endpoint_content_length": int_value(controller_counts.get("qr_endpoint_content_length")),
            "qr_attempts_observed": int_value(controller_counts.get("qr_attempts_observed")),
            "controller_release_created_by_this_packet": bool_value(
                auth_qr_retry_controller.get("controller_release_created_by_this_packet")
            ),
            "actual_auth_retry_allowed_now": bool_value(auth_qr_retry_controller.get("actual_auth_retry_allowed_now")),
            "actual_auth_sync_allowed_now": bool_value(auth_qr_retry_controller.get("actual_auth_sync_allowed_now")),
            "source_refresh_allowed_now": bool_value(auth_qr_retry_controller.get("source_refresh_allowed_now")),
            "docker_worker_allowed_now": bool_value(auth_qr_retry_controller.get("docker_worker_allowed_now")),
            "role": "bounded report-only auth/QR retry plan, not source-refresh authorization",
        }
    if full_incremental_preflight_gate:
        gate_counts = as_dict(full_incremental_preflight_gate.get("counts"))
        gate_next_action = as_dict(full_incremental_preflight_gate.get("next_action_summary"))
        horizontal["full_incremental_preflight_gate"] = {
            "decision": full_incremental_preflight_gate.get("decision"),
            "full_incremental_candidate_run_allowed_now": bool_value(
                full_incremental_preflight_gate.get("full_incremental_candidate_run_allowed_now")
            ),
            "source_refresh_allowed_now": bool_value(full_incremental_preflight_gate.get("source_refresh_allowed_now")),
            "docker_worker_allowed_now": bool_value(full_incremental_preflight_gate.get("docker_worker_allowed_now")),
            "next_action_task_count": int_value(gate_next_action.get("task_count")),
            "failed_required_check_count": int_value(gate_counts.get("failed_required_check_count")),
            "role": "final report-only execution gate before full incremental candidate run",
        }
    if current_release_quality_recovery_packet:
        recovery_quality = as_dict(current_release_quality_recovery_packet.get("current_release_quality"))
        poster_recovery = as_dict(current_release_quality_recovery_packet.get("poster_recovery"))
        geo_recovery = as_dict(current_release_quality_recovery_packet.get("geo_recovery"))
        horizontal["current_release_quality_recovery_packet"] = {
            "decision": current_release_quality_recovery_packet.get("decision"),
            "item_count": int_value(recovery_quality.get("item_count")),
            "missing_internal_poster_count": int_value(recovery_quality.get("missing_internal_poster_count")),
            "invalid_poster_storage_count": int_value(recovery_quality.get("invalid_poster_storage_count")),
            "public_wechat_or_qpic_poster_count": int_value(
                recovery_quality.get("public_wechat_or_qpic_poster_count")
            ),
            "missing_geo_count": int_value(recovery_quality.get("missing_geo_count")),
            "poster_recovery_required": bool_value(poster_recovery.get("required")),
            "poster_ocr_recovery_count": int_value(poster_recovery.get("article_image_ocr_recovery_count")),
            "poster_public_upload_candidate_count": int_value(poster_recovery.get("public_upload_candidate_count")),
            "all_missing_posters_are_aggregate_children": bool_value(
                poster_recovery.get("all_missing_posters_are_aggregate_children")
            ),
            "geo_recovery_required": bool_value(geo_recovery.get("required")),
            "full_incremental_run_allowed_now": bool_value(
                current_release_quality_recovery_packet.get("full_incremental_run_allowed_now")
            ),
            "source_refresh_allowed_now": bool_value(
                current_release_quality_recovery_packet.get("source_refresh_allowed_now")
            ),
            "docker_worker_allowed_now": bool_value(
                current_release_quality_recovery_packet.get("docker_worker_allowed_now")
            ),
            "role": "current-release quality recovery queue aligned to frontend cloud file ID adapter",
        }
    vertical_chain = [
        {
            "gate": as_dict(row).get("gate"),
            "ok": as_dict(row).get("ok"),
            "required": as_dict(row).get("required"),
            "freshness_ready": as_dict(row).get("freshness_ready"),
            "auth_recovery_ready": as_dict(row).get("auth_recovery_ready"),
            "qr_upstream_unavailable": as_dict(row).get("qr_upstream_unavailable"),
            "qr_endpoint_root_cause_class": as_dict(row).get("qr_endpoint_root_cause_class"),
            "auth_recovery_root_cause_class": as_dict(row).get("auth_recovery_root_cause_class"),
            "material_ready": as_dict(row).get("material_ready"),
        }
        for row in as_list(readiness.get("vertical_gate_chain"))
        if as_dict(row).get("gate")
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "keep_next_action_mutation_continue_goal"
        if next_action
        else "keep_report_only_mutation_continue_goal",
        "target_skills": [
            {"name": skill_name(daily_text, "openclaw-weekly-daily-run"), "sha12": sha12(daily_text)},
            {"name": skill_name(docker_text, "openclaw-docker-arsenal"), "sha12": sha12(docker_text)},
        ],
        "inputs": {
            "readiness_report": safe_repo_path(readiness_path),
            "exporter_freshness_report": safe_repo_path(exporter_freshness_path),
            "exporter_auth_recovery_report": safe_repo_path(exporter_auth_recovery_path),
            "next_action_packet": safe_repo_path(next_action_packet_path) if next_action_packet_path else "",
            "source_material_controller": safe_repo_path(source_material_controller_path)
            if source_material_controller_path
            else "",
            "source_material_runtime_preflight": safe_repo_path(source_material_runtime_preflight_path)
            if source_material_runtime_preflight_path
            else "",
            "source_material_controller_release": safe_repo_path(source_material_controller_release_path)
            if source_material_controller_release_path
            else "",
            "auth_qr_retry_controller": safe_repo_path(auth_qr_retry_controller_path)
            if auth_qr_retry_controller_path
            else "",
            "full_incremental_preflight_gate": safe_repo_path(full_incremental_preflight_gate_path)
            if full_incremental_preflight_gate_path
            else "",
            "current_release_quality_recovery_packet": safe_repo_path(current_release_quality_recovery_packet_path)
            if current_release_quality_recovery_packet_path
            else "",
        },
        "darwin_scores": scores,
        "score_total": total,
        "score_max": max_total,
        "score_average": round(total / len(scores), 2) if scores else 0,
        "test_prompts": prompts,
        "horizontal_comparison": horizontal,
        "vertical_gate_chain": vertical_chain,
        "current_blockers": {
            "failed_check_ids": sorted(str(v) for v in as_list(readiness.get("failed_check_ids"))),
            "package_candidate_ready": bool_value(readiness.get("package_candidate_ready")),
            "release_ready": bool_value(readiness.get("release_ready")),
            "queue_max_post_date": str(exporter_summary.get("queue_max_post_date") or ""),
            "candidate_published_max": str(exporter_summary.get("candidate_published_max") or ""),
            "invalid_session_error_count": int_value(exporter_summary.get("invalid_session_error_count")),
            "auth_recovery_ready": bool_value(auth_summary.get("auth_recovery_ready")),
            "session_requires_auth": bool_value(auth_summary.get("session_requires_auth")),
            "qr_upstream_unavailable": bool_value(auth_summary.get("qr_upstream_unavailable")),
            "qr_endpoint_root_cause_class": str(auth_summary.get("qr_endpoint_root_cause_class") or ""),
            "auth_recovery_root_cause_class": str(auth_summary.get("auth_recovery_root_cause_class") or ""),
            "next_action_task_count": int_value(next_action.get("task_count")) if next_action else 0,
            "source_refresh_allowed_now": bool_value(next_action.get("source_refresh_allowed_now")) if next_action else False,
            "full_incremental_run_allowed_now": bool_value(next_action.get("full_incremental_run_allowed_now")) if next_action else False,
            "source_material_controller_decision": source_material_controller.get("decision") if source_material_controller else "",
            "source_material_controller_selected_task_count": int_value(
                as_dict(source_material_controller.get("counts")).get("selected_task_count")
            )
            if source_material_controller
            else 0,
            "source_material_controller_candidate_source_count": int_value(
                as_dict(source_material_controller.get("counts")).get("selected_candidate_source_count")
            )
            if source_material_controller
            else 0,
            "source_material_controller_release_created": bool_value(
                source_material_controller.get("controller_release_created_by_this_packet")
            )
            if source_material_controller
            else False,
            "source_material_controller_worker_allowed_now": bool_value(
                source_material_controller.get("docker_worker_allowed_now")
            )
            if source_material_controller
            else False,
            "source_material_runtime_preflight_decision": source_material_runtime_preflight.get("decision")
            if source_material_runtime_preflight
            else "",
            "source_material_runtime_selected_task_count": int_value(
                as_dict(source_material_runtime_preflight.get("counts")).get("selected_task_count")
            )
            if source_material_runtime_preflight
            else 0,
            "source_material_runtime_candidate_source_count": int_value(
                as_dict(source_material_runtime_preflight.get("counts")).get("selected_candidate_source_count")
            )
            if source_material_runtime_preflight
            else 0,
            "source_material_runtime_release_created": bool_value(
                source_material_runtime_preflight.get("controller_release_created_by_this_packet")
            )
            if source_material_runtime_preflight
            else False,
            "source_material_runtime_acquisition_allowed_now": bool_value(
                source_material_runtime_preflight.get("actual_source_material_acquisition_allowed_now")
            )
            if source_material_runtime_preflight
            else False,
            "source_material_runtime_worker_allowed_now": bool_value(
                source_material_runtime_preflight.get("docker_worker_allowed_now")
            )
            if source_material_runtime_preflight
            else False,
            "source_material_runtime_full_incremental_run_allowed_now": bool_value(
                source_material_runtime_preflight.get("full_incremental_run_allowed_now")
            )
            if source_material_runtime_preflight
            else False,
            "source_material_controller_release_decision": source_material_controller_release.get("decision")
            if source_material_controller_release
            else "",
            "source_material_controller_release_created": bool_value(
                as_dict(source_material_controller_release.get("controller_release")).get(
                    "controller_release_created_by_this_packet"
                )
            )
            if source_material_controller_release
            else False,
            "source_material_controller_release_runtime_allowed": bool_value(
                as_dict(source_material_controller_release.get("controller_release")).get(
                    "source_material_runtime_allowed_by_this_packet"
                )
            )
            if source_material_controller_release
            else False,
            "source_material_controller_release_runtime_executed": bool_value(
                as_dict(source_material_controller_release.get("controller_release")).get(
                    "source_material_runtime_executed_by_this_packet"
                )
            )
            if source_material_controller_release
            else False,
            "source_material_controller_release_selected_task_count": int_value(
                as_dict(source_material_controller_release.get("counts")).get("selected_task_count")
            )
            if source_material_controller_release
            else 0,
            "source_material_controller_release_full_incremental_run_allowed_now": bool_value(
                source_material_controller_release.get("full_incremental_run_allowed_now")
            )
            if source_material_controller_release
            else False,
            "auth_qr_retry_controller_decision": auth_qr_retry_controller.get("decision")
            if auth_qr_retry_controller
            else "",
            "auth_qr_retry_root_cause_class": str(auth_qr_retry_controller.get("root_cause_class") or "")
            if auth_qr_retry_controller
            else "",
            "auth_qr_retry_controller_release_created": bool_value(
                auth_qr_retry_controller.get("controller_release_created_by_this_packet")
            )
            if auth_qr_retry_controller
            else False,
            "auth_qr_retry_actual_auth_allowed_now": bool_value(
                auth_qr_retry_controller.get("actual_auth_retry_allowed_now")
            )
            if auth_qr_retry_controller
            else False,
            "auth_qr_retry_source_refresh_allowed_now": bool_value(
                auth_qr_retry_controller.get("source_refresh_allowed_now")
            )
            if auth_qr_retry_controller
            else False,
            "auth_qr_retry_worker_allowed_now": bool_value(auth_qr_retry_controller.get("docker_worker_allowed_now"))
            if auth_qr_retry_controller
            else False,
            "full_incremental_preflight_gate_decision": full_incremental_preflight_gate.get("decision")
            if full_incremental_preflight_gate
            else "",
            "full_incremental_candidate_run_allowed_now": bool_value(
                full_incremental_preflight_gate.get("full_incremental_candidate_run_allowed_now")
            )
            if full_incremental_preflight_gate
            else False,
            "full_incremental_preflight_source_refresh_allowed_now": bool_value(
                full_incremental_preflight_gate.get("source_refresh_allowed_now")
            )
            if full_incremental_preflight_gate
            else False,
            "full_incremental_preflight_docker_worker_allowed_now": bool_value(
                full_incremental_preflight_gate.get("docker_worker_allowed_now")
            )
            if full_incremental_preflight_gate
            else False,
            "current_release_quality_recovery_packet_decision": current_release_quality_recovery_packet.get("decision")
            if current_release_quality_recovery_packet
            else "",
            "current_release_recovery_missing_internal_poster_count": int_value(
                as_dict(current_release_quality_recovery_packet.get("current_release_quality")).get(
                    "missing_internal_poster_count"
                )
            )
            if current_release_quality_recovery_packet
            else 0,
            "current_release_recovery_invalid_poster_storage_count": int_value(
                as_dict(current_release_quality_recovery_packet.get("current_release_quality")).get(
                    "invalid_poster_storage_count"
                )
            )
            if current_release_quality_recovery_packet
            else 0,
            "current_release_recovery_missing_geo_count": int_value(
                as_dict(current_release_quality_recovery_packet.get("current_release_quality")).get("missing_geo_count")
            )
            if current_release_quality_recovery_packet
            else 0,
            "current_release_recovery_poster_required": bool_value(
                as_dict(current_release_quality_recovery_packet.get("poster_recovery")).get("required")
            )
            if current_release_quality_recovery_packet
            else False,
            "current_release_recovery_geo_required": bool_value(
                as_dict(current_release_quality_recovery_packet.get("geo_recovery")).get("required")
            )
            if current_release_quality_recovery_packet
            else False,
            "current_release_recovery_full_incremental_run_allowed_now": bool_value(
                current_release_quality_recovery_packet.get("full_incremental_run_allowed_now")
            )
            if current_release_quality_recovery_packet
            else False,
            "missing_internal_poster_count": int_value(quality.get("missing_internal_poster_count")),
            "invalid_poster_storage_count": int_value(quality.get("invalid_poster_storage_count")),
            "public_or_temp_poster_url_count": int_value(quality.get("public_or_temp_poster_url_count")),
            "runtime_poster_state_count": int_value(quality.get("runtime_poster_state_count")),
        },
        "boundary": {
            "report_only": True,
            "llm_call_executed": False,
            "ocr_executed": False,
            "vision_api_executed": False,
            "docker_executed": False,
            "source_refresh_executed": False,
            "cloudbase_storage_write_executed": False,
            "cloudbase_db_write_executed": False,
            "db2_write_executed": False,
            "db3_write_executed": False,
            "cloudrun_deploy_executed": False,
            "cloudbase_sync_executed": False,
            "miniprogram_upload_executed": False,
            "wechat_review_submitted": False,
            "public_release_executed": False,
            "secret_file_read": False,
            "credential_value_read": False,
        },
    }
    report["raw_url_private_path_secret_leak_count"] = leak_count(report)
    if report["raw_url_private_path_secret_leak_count"]:
        report["decision"] = "reject_scorecard_due_to_leak"
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OpenClaw Weekly Darwin Scorecard",
        "",
        f"- decision: `{report['decision']}`",
        f"- score: `{report['score_total']}/{report['score_max']}`",
        f"- average: `{report['score_average']}/5`",
        f"- leak_count: `{report['raw_url_private_path_secret_leak_count']}`",
        f"- package_candidate_ready: `{report['current_blockers']['package_candidate_ready']}`",
        f"- release_ready: `{report['current_blockers']['release_ready']}`",
        "",
        "## Darwin Scores",
        "",
        "| Dimension | Score | Evidence |",
        "| --- | ---: | --- |",
    ]
    for row in report["darwin_scores"]:
        lines.append(f"| `{row['id']}` | {row['score']}/{row['max']} | {row['evidence']} |")
    lines.extend(["", "## Regression Prompts", "", "| Prompt ID | Expected behavior |", "| --- | --- |"])
    for row in report["test_prompts"]:
        lines.append(f"| `{row['id']}` | {row['expected_behavior']} |")
    lines.extend(["", "## Horizontal Comparison", ""])
    for key, row in report["horizontal_comparison"].items():
        lines.append(f"- `{key}`: {json.dumps(row, ensure_ascii=False, sort_keys=True)}")
    lines.extend(["", "## Current Blockers", ""])
    blockers = report["current_blockers"]
    lines.append(f"- failed_check_ids: `{', '.join(blockers['failed_check_ids'])}`")
    lines.append(f"- queue_max_post_date: `{blockers['queue_max_post_date'] or 'unknown'}`")
    lines.append(f"- candidate_published_max: `{blockers['candidate_published_max'] or 'unknown'}`")
    lines.append(f"- invalid_session_error_count: `{blockers['invalid_session_error_count']}`")
    lines.append(f"- auth_recovery_ready: `{blockers['auth_recovery_ready']}`")
    lines.append(f"- qr_upstream_unavailable: `{blockers['qr_upstream_unavailable']}`")
    if blockers.get("source_material_controller_decision"):
        lines.append(f"- source_material_controller_decision: `{blockers['source_material_controller_decision']}`")
        lines.append(
            f"- source_material_controller_selected_task_count: `{blockers['source_material_controller_selected_task_count']}`"
        )
        lines.append(
            f"- source_material_controller_candidate_source_count: `{blockers['source_material_controller_candidate_source_count']}`"
        )
        lines.append(
            f"- source_material_controller_worker_allowed_now: `{blockers['source_material_controller_worker_allowed_now']}`"
        )
    if blockers.get("source_material_runtime_preflight_decision"):
        lines.append(
            f"- source_material_runtime_preflight_decision: `{blockers['source_material_runtime_preflight_decision']}`"
        )
        lines.append(
            f"- source_material_runtime_selected_task_count: `{blockers['source_material_runtime_selected_task_count']}`"
        )
        lines.append(
            f"- source_material_runtime_candidate_source_count: `{blockers['source_material_runtime_candidate_source_count']}`"
        )
        lines.append(
            f"- source_material_runtime_worker_allowed_now: `{blockers['source_material_runtime_worker_allowed_now']}`"
        )
        lines.append(
            f"- source_material_runtime_full_incremental_run_allowed_now: `{blockers['source_material_runtime_full_incremental_run_allowed_now']}`"
        )
    if blockers.get("source_material_controller_release_decision"):
        lines.append(
            f"- source_material_controller_release_decision: `{blockers['source_material_controller_release_decision']}`"
        )
        lines.append(
            f"- source_material_controller_release_created: `{blockers['source_material_controller_release_created']}`"
        )
        lines.append(
            f"- source_material_controller_release_runtime_allowed: `{blockers['source_material_controller_release_runtime_allowed']}`"
        )
        lines.append(
            f"- source_material_controller_release_runtime_executed: `{blockers['source_material_controller_release_runtime_executed']}`"
        )
    if blockers.get("auth_qr_retry_controller_decision"):
        lines.append(f"- auth_qr_retry_controller_decision: `{blockers['auth_qr_retry_controller_decision']}`")
        lines.append(f"- auth_qr_retry_root_cause_class: `{blockers['auth_qr_retry_root_cause_class']}`")
        lines.append(
            f"- auth_qr_retry_source_refresh_allowed_now: `{blockers['auth_qr_retry_source_refresh_allowed_now']}`"
        )
        lines.append(f"- auth_qr_retry_worker_allowed_now: `{blockers['auth_qr_retry_worker_allowed_now']}`")
    if blockers.get("full_incremental_preflight_gate_decision"):
        lines.append(
            f"- full_incremental_preflight_gate_decision: `{blockers['full_incremental_preflight_gate_decision']}`"
        )
        lines.append(
            f"- full_incremental_candidate_run_allowed_now: `{blockers['full_incremental_candidate_run_allowed_now']}`"
        )
        lines.append(
            f"- full_incremental_preflight_source_refresh_allowed_now: `{blockers['full_incremental_preflight_source_refresh_allowed_now']}`"
        )
        lines.append(
            f"- full_incremental_preflight_docker_worker_allowed_now: `{blockers['full_incremental_preflight_docker_worker_allowed_now']}`"
        )
    if blockers.get("current_release_quality_recovery_packet_decision"):
        lines.append(
            f"- current_release_quality_recovery_packet_decision: `{blockers['current_release_quality_recovery_packet_decision']}`"
        )
        lines.append(
            f"- current_release_recovery_missing_internal_poster_count: `{blockers['current_release_recovery_missing_internal_poster_count']}`"
        )
        lines.append(
            f"- current_release_recovery_invalid_poster_storage_count: `{blockers['current_release_recovery_invalid_poster_storage_count']}`"
        )
        lines.append(
            f"- current_release_recovery_missing_geo_count: `{blockers['current_release_recovery_missing_geo_count']}`"
        )
        lines.append(
            f"- current_release_recovery_full_incremental_run_allowed_now: `{blockers['current_release_recovery_full_incremental_run_allowed_now']}`"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only. No LLM call, OCR, vision API, Docker run, source refresh, CloudBase write, DB write, deploy, sync, upload, review, release, or secret read.",
            "- Continue goal: fix exporter auth/QR recovery and queue freshness before actual OCR worker or full incremental package run.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-skill", type=Path, default=default_openclaw_skill_path("openclaw-weekly-daily-run"))
    parser.add_argument("--docker-skill", type=Path, default=default_openclaw_skill_path("openclaw-docker-arsenal"))
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument("--exporter-freshness", type=Path, default=DEFAULT_EXPORTER_FRESHNESS)
    parser.add_argument("--exporter-auth-recovery", type=Path, default=DEFAULT_EXPORTER_AUTH_RECOVERY)
    parser.add_argument("--next-action-packet", type=Path, default=DEFAULT_NEXT_ACTION_PACKET)
    parser.add_argument("--source-material-controller", type=Path, default=DEFAULT_SOURCE_MATERIAL_CONTROLLER)
    parser.add_argument("--source-material-runtime-preflight", type=Path, default=DEFAULT_SOURCE_MATERIAL_RUNTIME_PREFLIGHT)
    parser.add_argument("--source-material-controller-release", type=Path, default=DEFAULT_SOURCE_MATERIAL_CONTROLLER_RELEASE)
    parser.add_argument("--auth-qr-retry-controller", type=Path, default=DEFAULT_AUTH_QR_RETRY_CONTROLLER)
    parser.add_argument("--full-incremental-preflight-gate", type=Path, default=DEFAULT_FULL_INCREMENTAL_PREFLIGHT_GATE)
    parser.add_argument("--current-release-quality-recovery-packet", type=Path, default=DEFAULT_CURRENT_RELEASE_QUALITY_RECOVERY_PACKET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_scorecard(
        daily_skill=args.daily_skill,
        docker_skill=args.docker_skill,
        readiness_path=args.readiness,
        exporter_freshness_path=args.exporter_freshness,
        exporter_auth_recovery_path=args.exporter_auth_recovery,
        next_action_packet_path=args.next_action_packet,
        source_material_controller_path=args.source_material_controller,
        source_material_runtime_preflight_path=args.source_material_runtime_preflight,
        source_material_controller_release_path=args.source_material_controller_release,
        auth_qr_retry_controller_path=args.auth_qr_retry_controller,
        full_incremental_preflight_gate_path=args.full_incremental_preflight_gate,
        current_release_quality_recovery_packet_path=args.current_release_quality_recovery_packet,
    )
    json_path = args.out_dir / "openclaw_weekly_darwin_scorecard.json"
    md_path = args.out_dir / "openclaw_weekly_darwin_scorecard.md"
    write_json(json_path, report)
    write_text(md_path, render_markdown(report))
    print(json.dumps({"decision": report["decision"], "score": report["score_total"], "max": report["score_max"], "report": safe_repo_path(json_path)}, ensure_ascii=False))
    return 0 if report["decision"] != "reject_scorecard_due_to_leak" else 2


if __name__ == "__main__":
    raise SystemExit(main())
