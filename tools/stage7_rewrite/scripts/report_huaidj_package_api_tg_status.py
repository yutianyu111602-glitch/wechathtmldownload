#!/usr/bin/env python3
"""Report HUAIDJ activity package and online API status for Hermes Telegram.

The script is read-only: it reads local status/package JSON files, checks public
CloudRun endpoints, writes a small non-secret report, and prints a Telegram
message only when a package/status signature changes, an API problem appears,
or a problem recovers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[3]
TZ = timezone(timedelta(hours=8))

DEFAULT_CLOUDRUN_BASE = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com"
DEFAULT_REPORT_ROOT = Path(
    os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports")
)
DEFAULT_STATUS_JSON = DEFAULT_REPORT_ROOT / "sanji_twice_daily_7day/latest_status.json"
DEFAULT_PUBLISH_REPORT_ROOT = DEFAULT_REPORT_ROOT
DEFAULT_RUNTIME_DATA_ROOT = Path(
    r"F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data"
)


def default_local_deploy_dir() -> Path:
    configured_current = os.environ.get("HUAIDJ_CURRENT_RELEASE_DIR", "").strip()
    if configured_current:
        return Path(configured_current)
    configured_data = os.environ.get("HUAIDJ_CLOUDRUN_DATA_ROOT", "").strip()
    return Path(configured_data or DEFAULT_RUNTIME_DATA_ROOT) / "current_release"


DEFAULT_LOCAL_DEPLOY_DIR = default_local_deploy_dir()
DEFAULT_JSON_OUT = DEFAULT_REPORT_ROOT / "huaidj_package_api_tg_status/latest.json"
DEFAULT_STATE_FILE = (
    Path(os.environ.get("HERMES_HOME", r"F:\DevData\Hermes"))
    / "scripts/huaidj/.package_api_tg_state.json"
)


def now_dt() -> datetime:
    return datetime.now(TZ)


def now_text() -> str:
    return now_dt().strftime("%Y-%m-%d %H:%M")


def read_json(path: Path) -> tuple[Any | None, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), ""
    except FileNotFoundError:
        return None, f"missing: {path}"
    except Exception as exc:
        return None, f"read error: {exc}"


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def short_text(value: Any, limit: int = 160) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        dt = None
        for pattern in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def http_get_json(url: str, timeout: float) -> tuple[int, Any | None, str, int]:
    started = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Hermes-HUAIDJ-TG-Monitor/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(2_000_000).decode("utf-8", errors="replace")
            ms = int((time.time() - started) * 1000)
            try:
                return resp.status, json.loads(body), "", ms
            except Exception as exc:
                return resp.status, None, f"bad JSON: {exc}", ms
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return exc.code, None, short_text(body or exc.reason), int((time.time() - started) * 1000)
    except Exception as exc:
        return 0, None, short_text(exc), int((time.time() - started) * 1000)


def endpoint_result(name: str, ok: bool, status: int, ms: int, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "status": status, "ms": ms, "detail": detail}


def count_cities(payload: Any) -> int:
    if isinstance(payload, dict):
        return int_or_zero(payload.get("city_count")) or len(payload.get("cities") or [])
    if isinstance(payload, list):
        return len(payload)
    return 0


def load_local_package(local_deploy_dir: Path) -> dict[str, Any]:
    manifest_path = local_deploy_dir / "manifest.json"
    current_path = local_deploy_dir / "current.json"
    manifest, manifest_error = read_json(manifest_path)
    current, current_error = read_json(current_path)

    manifest_items = int_or_zero(manifest.get("item_count")) if isinstance(manifest, dict) else 0
    current_items = 0
    if isinstance(current, dict):
        current_items = int_or_zero(current.get("item_count")) or len(current.get("items") or [])

    generated_at = manifest.get("generated_at") if isinstance(manifest, dict) else ""
    return {
        "manifest_path": str(manifest_path),
        "current_path": str(current_path),
        "manifest_exists": manifest_path.exists(),
        "current_exists": current_path.exists(),
        "manifest_error": manifest_error,
        "current_error": current_error,
        "manifest_item_count": manifest_items,
        "current_item_count": current_items,
        "generated_at": str(generated_at or ""),
    }


def summarize_latest_status(status_json: Path) -> dict[str, Any]:
    payload, error = read_json(status_json)
    if not isinstance(payload, dict):
        return {
            "exists": status_json.exists(),
            "error": error,
            "ok": None,
            "state": "unknown",
            "run_id": "",
            "stage": "",
            "generated_at": "",
            "sanji_exported_rows": 0,
            "deploy_backend": None,
            "cloudrun_deploy_executed": None,
            "message": error or "status unavailable",
        }

    ok_value = payload.get("ok")
    state = "success" if ok_value is True else "failure" if ok_value is False else "unknown"
    return {
        "exists": True,
        "error": "",
        "ok": ok_value if isinstance(ok_value, bool) else None,
        "state": state,
        "run_id": str(payload.get("run_id") or ""),
        "stage": str(payload.get("stage") or ""),
        "generated_at": str(payload.get("generated_at") or ""),
        "sanji_generated_at": str(payload.get("sanji_generated_at") or ""),
        "sanji_exported_rows": int_or_zero(payload.get("sanji_exported_rows")),
        "deploy_backend": payload.get("deploy_backend") if isinstance(payload.get("deploy_backend"), bool) else None,
        "cloudrun_deploy_executed": payload.get("cloudrun_deploy_executed")
        if isinstance(payload.get("cloudrun_deploy_executed"), bool)
        else None,
        "message": short_text(payload.get("error") or payload.get("publish_decision") or payload.get("publish_status")),
    }


def is_failure_superseded_by_online_manifest(latest_status: dict[str, Any], manifest_generated_at: str) -> bool:
    if latest_status.get("state") != "failure":
        return False
    failed_at = parse_time(str(latest_status.get("generated_at") or ""))
    manifest_at = parse_time(manifest_generated_at)
    return bool(failed_at and manifest_at and manifest_at > failed_at)


def find_confirmed_publish_recovery(
    *,
    report_root: Path,
    latest_status: dict[str, Any],
    manifest_generated_at: str,
    remote_items: int,
    local_remote_match: bool,
) -> dict[str, Any] | None:
    """Return a newer, fully deployed Sanji recovery that matches production."""
    if latest_status.get("state") != "failure" or not local_remote_match or remote_items <= 0:
        return None
    failed_at = parse_time(latest_status.get("generated_at"))
    manifest_at = parse_time(manifest_generated_at)
    if not failed_at or not manifest_at or manifest_at <= failed_at:
        return None

    candidates: list[dict[str, Any]] = []
    for summary_path in report_root.glob(
        "openclaw_weekly_daily_*/openclaw_weekly_daily_publish_summary.json"
    ):
        payload, _ = read_json(summary_path)
        if not isinstance(payload, dict):
            continue
        boundary = payload.get("boundary") if isinstance(payload.get("boundary"), dict) else {}
        if not (
            payload.get("ok") is True
            and payload.get("status") == "ok"
            and payload.get("decision") == "ok"
            and payload.get("dry_run") is False
            and payload.get("source_mode") in {"sanji_desktop_client", "sanji_desktop_rss"}
            and payload.get("release_ready") is True
            and int_or_zero(payload.get("quality_gate_exit_code")) == 0
            and boundary.get("cloudrun_deploy_executed") is True
            and int_or_zero(payload.get("item_count")) == remote_items
        ):
            continue
        try:
            completed_at = datetime.fromtimestamp(summary_path.stat().st_mtime, TZ)
        except OSError:
            continue
        if completed_at <= failed_at:
            continue
        queue_rows = 0
        gap_report_text = str(payload.get("sanji_queue_package_gap_audit_report") or "").strip()
        if gap_report_text:
            gap_report_path = Path(gap_report_text)
            if not gap_report_path.is_absolute():
                gap_report_path = summary_path.parent / gap_report_path
            gap_payload, _ = read_json(gap_report_path)
            if isinstance(gap_payload, dict) and gap_payload.get("ok") is True:
                queue_rows = int_or_zero(gap_payload.get("queue_row_count"))
        candidates.append(
            {
                "run_id": str(payload.get("run_id") or summary_path.parent.name),
                "stage": "complete:weekly_publish",
                "generated_at": completed_at.isoformat(),
                "item_count": remote_items,
                "sanji_exported_rows": queue_rows,
                "summary_path": str(summary_path.resolve()),
                "message": "恢复发布已通过质量门并完成 CloudRun 部署",
                "completed_at": completed_at,
            }
        )
    if not candidates:
        return None
    recovery = max(candidates, key=lambda item: item["completed_at"])
    recovery.pop("completed_at", None)
    return recovery


def classify_local_remote_package(
    *,
    local_items: int,
    local_generated_at: str,
    remote_items: int,
    remote_generated_at: str,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    if remote_items <= 0:
        errors.append("remote package item_count unavailable")
        return {
            "ok": False,
            "health_ok": False,
            "status": "remote_unavailable",
            "local_item_count": local_items,
            "remote_item_count": remote_items,
            "local_generated_at": local_generated_at,
            "remote_generated_at": remote_generated_at,
        }
    if local_items <= 0:
        warnings.append("local package unavailable; remote package checked only")
        return {
            "ok": True,
            "health_ok": True,
            "status": "local_unavailable_remote_checked",
            "local_item_count": local_items,
            "remote_item_count": remote_items,
            "local_generated_at": local_generated_at,
            "remote_generated_at": remote_generated_at,
        }
    if local_items == remote_items:
        return {
            "ok": True,
            "health_ok": True,
            "status": "matched",
            "local_item_count": local_items,
            "remote_item_count": remote_items,
            "local_generated_at": local_generated_at,
            "remote_generated_at": remote_generated_at,
        }

    local_dt = parse_time(local_generated_at)
    remote_dt = parse_time(remote_generated_at)
    if local_dt and remote_dt and local_dt > remote_dt:
        status = "local_candidate_newer_than_online"
        warnings.append(
            f"local candidate package is newer than online: local={local_items}, remote={remote_items}; deploy may be pending or propagating"
        )
    elif local_dt and remote_dt and local_dt < remote_dt:
        status = "local_package_older_than_online"
        warnings.append(
            f"local package is older than online: local={local_items}, remote={remote_items}; local deploy context may be stale"
        )
    else:
        status = "local_remote_item_count_mismatch"
        warnings.append(
            f"local and online package item_count differ: local={local_items}, remote={remote_items}; online API endpoints are checked separately"
        )
    return {
        "ok": False,
        "health_ok": True,
        "status": status,
        "local_item_count": local_items,
        "remote_item_count": remote_items,
        "local_generated_at": local_generated_at,
        "remote_generated_at": remote_generated_at,
    }


def collect_status(
    *,
    cloudrun_base: str,
    status_json: Path,
    local_deploy_dir: Path,
    timeout_sec: float,
    publish_report_root: Path = DEFAULT_PUBLISH_REPORT_ROOT,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    endpoints: list[dict[str, Any]] = []
    cloudrun_base = cloudrun_base.rstrip("/")

    status_code, payload, error, ms = http_get_json(f"{cloudrun_base}/healthz", timeout_sec)
    health_ok = status_code == 200 and isinstance(payload, dict) and payload.get("ok") is True
    detail = payload.get("service", "ok") if isinstance(payload, dict) else error or f"HTTP {status_code}"
    endpoints.append(endpoint_result("healthz", health_ok, status_code, ms, str(detail)))
    if not health_ok:
        errors.append(f"/healthz {status_code}: {detail}")

    status_code, payload, error, ms = http_get_json(f"{cloudrun_base}/readyz", timeout_sec)
    ready_package_count = int_or_zero(payload.get("packageItemCount")) if isinstance(payload, dict) else 0
    ready_detail_count = int_or_zero(payload.get("derivedDetailCount")) if isinstance(payload, dict) else 0
    ready_generation = str(payload.get("generationId") or "") if isinstance(payload, dict) else ""
    ready_ok = (
        status_code == 200
        and isinstance(payload, dict)
        and payload.get("ok") is True
        and bool(ready_generation)
        and ready_package_count > 0
        and ready_detail_count == ready_package_count
    )
    detail = (
        f"generation={ready_generation[:24]}, package={ready_package_count}, detail={ready_detail_count}"
        if isinstance(payload, dict)
        else error or f"HTTP {status_code}"
    )
    endpoints.append(endpoint_result("readyz", ready_ok, status_code, ms, str(detail)))
    if not ready_ok:
        errors.append(f"/readyz {status_code}: {detail}")

    remote_items = 0
    manifest_generated_at = ""
    window_start = ""
    window_end = ""
    status_code, payload, error, ms = http_get_json(f"{cloudrun_base}/api/v1/weekly/manifest", timeout_sec)
    manifest_ok = status_code == 200 and isinstance(payload, dict)
    if manifest_ok:
        remote_items = int_or_zero(payload.get("item_count"))
        manifest_generated_at = str(payload.get("generated_at") or "")
        window_start = str(payload.get("window_start") or "")
        window_end = str(payload.get("window_end") or "")
        detail = f"{remote_items} items, {window_start}~{window_end}"
        if remote_items < 1:
            manifest_ok = False
            errors.append("/manifest item_count < 1")
        generated_dt = parse_time(manifest_generated_at)
        if generated_dt:
            age_hours = (now_dt() - generated_dt).total_seconds() / 3600
            if age_hours > 96:
                errors.append(f"manifest stale {age_hours:.0f}h")
            elif age_hours > 72:
                warnings.append(f"manifest {age_hours:.0f}h old")
    else:
        detail = error or f"HTTP {status_code}"
        errors.append(f"/manifest {status_code}: {detail}")
    endpoints.append(endpoint_result("manifest", manifest_ok, status_code, ms, detail))

    current_total = 0
    status_code, payload, error, ms = http_get_json(f"{cloudrun_base}/api/v1/weekly/current?limit=1", timeout_sec)
    current_ok = status_code == 200 and isinstance(payload, dict)
    if current_ok:
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        current_total = int_or_zero(page.get("total")) or int_or_zero(payload.get("item_count")) or len(payload.get("items") or [])
        detail = f"{current_total} events"
        if current_total < 1:
            current_ok = False
            errors.append("/current total < 1")
    else:
        detail = error or f"HTTP {status_code}"
        errors.append(f"/current {status_code}: {detail}")
    endpoints.append(endpoint_result("current", current_ok, status_code, ms, detail))

    city_count = 0
    status_code, payload, error, ms = http_get_json(f"{cloudrun_base}/api/v1/weekly/cities", timeout_sec)
    cities_ok = status_code == 200 and payload is not None
    if cities_ok:
        city_count = count_cities(payload)
        detail = f"{city_count} cities"
        if city_count < 1:
            cities_ok = False
            errors.append("/cities city_count < 1")
    else:
        detail = error or f"HTTP {status_code}"
        errors.append(f"/cities {status_code}: {detail}")
    endpoints.append(endpoint_result("cities", cities_ok, status_code, ms, detail))

    local = load_local_package(local_deploy_dir)
    if local["manifest_error"]:
        warnings.append("local manifest unavailable")
    if local["current_error"]:
        warnings.append("local current unavailable")
    local_items = int_or_zero(local.get("manifest_item_count")) or int_or_zero(local.get("current_item_count"))
    cross_check = classify_local_remote_package(
        local_items=local_items,
        local_generated_at=str(local.get("generated_at") or ""),
        remote_items=remote_items,
        remote_generated_at=manifest_generated_at,
        errors=errors,
        warnings=warnings,
    )

    latest_status = summarize_latest_status(status_json)
    latest_status["failure_superseded_by_online_manifest"] = is_failure_superseded_by_online_manifest(
        latest_status, manifest_generated_at
    )
    latest_status["online_manifest_generated_at"] = manifest_generated_at
    recovery = find_confirmed_publish_recovery(
        report_root=publish_report_root,
        latest_status=latest_status,
        manifest_generated_at=manifest_generated_at,
        remote_items=remote_items,
        local_remote_match=bool(cross_check.get("ok")),
    )
    latest_status["recovery_confirmed"] = recovery is not None
    latest_status["recovery"] = recovery or {}
    if recovery:
        latest_status["effective_state"] = "success"
        latest_status["effective_run_id"] = recovery["run_id"]
        latest_status["effective_stage"] = recovery["stage"]
        latest_status["effective_generated_at"] = recovery["generated_at"]
        latest_status["effective_message"] = recovery["message"]
        latest_status["effective_sanji_exported_rows"] = recovery["sanji_exported_rows"]
    else:
        latest_status["effective_state"] = latest_status["state"]
        latest_status["effective_run_id"] = latest_status["run_id"]
        latest_status["effective_stage"] = latest_status["stage"]
        latest_status["effective_generated_at"] = latest_status["generated_at"]
        latest_status["effective_message"] = latest_status["message"]
        latest_status["effective_sanji_exported_rows"] = latest_status["sanji_exported_rows"]
    if latest_status["effective_state"] == "failure" and not latest_status["failure_superseded_by_online_manifest"]:
        warnings.append(f"latest Sanji publish task failed: {latest_status.get('stage')}")

    endpoints_ok = all(endpoint["ok"] for endpoint in endpoints)
    api_ok = not errors and endpoints_ok
    package_online_ok = remote_items > 0 and endpoints_ok

    signature_payload = {
        "remote_items": remote_items,
        "manifest_generated_at": manifest_generated_at,
        "local_items": local_items,
        "cross_check_status": cross_check.get("status"),
        "latest_run_id": latest_status.get("run_id"),
        "latest_state": latest_status.get("state"),
        "latest_stage": latest_status.get("stage"),
        "latest_generated_at": latest_status.get("generated_at"),
        "latest_failure_superseded": latest_status.get("failure_superseded_by_online_manifest"),
        "latest_recovery_confirmed": latest_status.get("recovery_confirmed"),
        "latest_effective_run_id": latest_status.get("effective_run_id"),
        "latest_effective_state": latest_status.get("effective_state"),
        "latest_effective_generated_at": latest_status.get("effective_generated_at"),
        "latest_effective_sanji_exported_rows": latest_status.get("effective_sanji_exported_rows"),
        "api_ok": api_ok,
        "errors": errors,
    }
    signature = hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "schema_version": "huaidj_package_api_tg_status.v1",
        "generated_at": now_dt().isoformat(),
        "cloudrun_base": cloudrun_base,
        "api_ok": api_ok,
        "package_online_ok": package_online_ok,
        "signature": signature,
        "errors": errors,
        "warnings": warnings,
        "latest_status": latest_status,
        "remote": {
            "item_count": remote_items,
            "current_total": current_total,
            "city_count": city_count,
            "manifest_generated_at": manifest_generated_at,
            "window_start": window_start,
            "window_end": window_end,
            "endpoints": endpoints,
        },
        "local": local,
        "cross_check": cross_check,
    }


def load_state(path: Path) -> dict[str, Any]:
    payload, _ = read_json(path)
    return payload if isinstance(payload, dict) else {}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def should_emit(report: dict[str, Any], state: dict[str, Any], force: bool, degraded_repeat_hours: float) -> tuple[bool, str]:
    if force:
        return True, "force"
    if not state:
        return True, "first_report"
    if report["signature"] != state.get("last_signature"):
        return True, "package_or_status_changed"
    if report["api_ok"] is True and state.get("last_api_ok") is False:
        return True, "recovered"
    if report["api_ok"] is False:
        last_degraded_ts = float(state.get("last_degraded_report_ts") or 0)
        elapsed_hours = (time.time() - last_degraded_ts) / 3600 if last_degraded_ts else 999999
        if elapsed_hours >= degraded_repeat_hours:
            return True, "degraded_repeat"
    return False, "unchanged"


def next_state(report: dict[str, Any], emitted: bool) -> dict[str, Any]:
    state = {
        "last_check_ts": time.time(),
        "last_checked_at": now_dt().isoformat(),
        "last_signature": report["signature"],
        "last_api_ok": bool(report["api_ok"]),
        "last_package_online_ok": bool(report["package_online_ok"]),
        "last_error_count": len(report.get("errors") or []),
    }
    if emitted:
        state["last_emit_ts"] = time.time()
        state["last_emitted_at"] = now_dt().isoformat()
    if report["api_ok"] is False and emitted:
        state["last_degraded_report_ts"] = time.time()
    return state


def build_message(report: dict[str, Any], reason: str) -> str:
    latest = report["latest_status"]
    remote = report["remote"]
    cross = report["cross_check"]
    local = report["local"]

    api_label = "正常" if report["api_ok"] else "异常"
    package_label = "正常" if report["package_online_ok"] else "异常"
    if latest.get("recovery_confirmed"):
        latest_state = "成功（恢复发布）"
    elif latest.get("failure_superseded_by_online_manifest"):
        latest_state = "旧失败已被当前线上包覆盖"
    else:
        latest_state = {
            "success": "成功",
            "failure": "失败",
            "unknown": "未知",
        }.get(str(latest.get("effective_state") or latest.get("state")), "未知")

    lines = [
        "HUAIDJ 活动包/API 状态",
        f"时间: {now_text()}",
        f"触发: {reason}",
        "",
        f"活动包: {package_label}",
        f"线上 API: {api_label}",
        f"最近 Sanji 发布任务: {latest_state}",
    ]
    effective_run_id = latest.get("effective_run_id") or latest.get("run_id")
    effective_stage = latest.get("effective_stage") or latest.get("stage")
    effective_message = latest.get("effective_message") or latest.get("message")
    if effective_run_id:
        lines.append(f"任务: {effective_run_id}")
    if effective_stage:
        lines.append(f"阶段: {effective_stage}")
    if effective_message:
        lines.append(f"说明: {effective_message}")

    lines.extend(
        [
            "",
            f"CloudRun: {remote['item_count']} items / {remote['city_count']} cities",
            f"current: {remote['current_total']} events",
            f"manifest: {remote['manifest_generated_at'] or 'unknown'}",
            f"window: {remote['window_start'] or '?'} ~ {remote['window_end'] or '?'}",
            f"本地包: {cross['local_item_count']} items",
            f"本地/线上: {'匹配' if cross['ok'] else '不匹配'}",
        ]
    )
    effective_sanji_rows = int_or_zero(
        latest.get("effective_sanji_exported_rows") or latest.get("sanji_exported_rows")
    )
    if effective_sanji_rows:
        lines.append(f"Sanji 导出: {effective_sanji_rows} rows")
    if local.get("generated_at"):
        lines.append(f"本地生成: {local['generated_at']}")

    if report.get("errors"):
        lines.append("")
        lines.append("异常:")
        for item in report["errors"][:5]:
            lines.append(f"- {short_text(item, 220)}")
    if report.get("warnings"):
        lines.append("")
        lines.append("提醒:")
        for item in report["warnings"][:5]:
            lines.append(f"- {short_text(item, 220)}")

    message = "\n".join(lines)
    if len(message) > 3800:
        message = message[:3790] + "\n..."
    return message


def write_json_report(path: Path, report: dict[str, Any], emitted: bool, reason: str) -> None:
    payload = dict(report)
    payload["emitted"] = emitted
    payload["emit_reason"] = reason
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloudrun-base", default=DEFAULT_CLOUDRUN_BASE)
    parser.add_argument("--status-json", default=str(DEFAULT_STATUS_JSON))
    parser.add_argument("--local-deploy-dir", default=str(DEFAULT_LOCAL_DEPLOY_DIR))
    parser.add_argument("--publish-report-root", default=str(DEFAULT_PUBLISH_REPORT_ROOT))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument("--degraded-repeat-hours", type=float, default=3.0)
    parser.add_argument("--force", action="store_true", help="Always print a Telegram message.")
    parser.add_argument("--no-state-write", action="store_true", help="Do not update the suppression state file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = collect_status(
        cloudrun_base=args.cloudrun_base,
        status_json=Path(args.status_json),
        local_deploy_dir=Path(args.local_deploy_dir),
        timeout_sec=args.timeout_sec,
        publish_report_root=Path(args.publish_report_root),
    )
    state_file = Path(args.state_file)
    state = load_state(state_file)
    emitted, reason = should_emit(report, state, args.force, args.degraded_repeat_hours)
    if not args.no_state_write:
        save_state(state_file, next_state(report, emitted))
    if args.json_out:
        write_json_report(Path(args.json_out), report, emitted, reason)
    if emitted:
        print(build_message(report, reason))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
